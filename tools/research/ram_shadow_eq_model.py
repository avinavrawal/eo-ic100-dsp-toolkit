"""Offline contract model for a queued, RAM-shadow EQ update.

This is not a firmware emulator. It models validation, single-request
mailbox ownership, command-ring ordering, configuration-pointer publication,
the stock open-EQ call order, and bounded failure reporting. It performs no
USB or hardware access.
"""
from __future__ import annotations

import math
import struct
from dataclasses import dataclass
from enum import Enum, auto

from codec_queue_model import CommandRing, EQ_COMMAND_ID, PushResult, pack_command


GAIN_MIN_DB = -12.0
GAIN_MAX_DB = 0.0
BUSY_RETRY_LIMIT = 4
E1_SETUP = (0x40, 0xE1, 0x454F, 0x4943, 4)
STATUS_SETUP = (0xC0, 0xE6, 0x454F, 0x4943, 32)


@dataclass(frozen=True)
class Band:
    filter_type: int
    gain_db: float
    frequency_hz: float
    q: float


@dataclass(frozen=True)
class EqConfig:
    left_preamp_db: float
    right_preamp_db: float
    bands: tuple[Band, ...]

    def with_band_gain(self, index: int, gain_db: float) -> "EqConfig":
        bands = list(self.bands)
        old = bands[index]
        bands[index] = Band(old.filter_type, gain_db, old.frequency_hz, old.q)
        return EqConfig(self.left_preamp_db, self.right_preamp_db, tuple(bands))


STOCK_CONFIG = EqConfig(
    0.0, 0.0,
    (Band(1, -2.0, 220.0, 0.6), Band(1, -2.0, 9000.0, 8.0)),
)


class Status(Enum):
    IDLE = auto()
    QUEUED = auto()
    WAITING_CODEC = auto()
    APPLYING = auto()
    APPLIED = auto()
    REJECTED = auto()
    QUEUE_FULL = auto()
    CODEC_NOT_READY = auto()
    BUSY_TIMEOUT = auto()
    ACK_TIMEOUT = auto()
    SETTER_ERROR = auto()
    WRONG_CONTEXT = auto()


class ReconfigureResult(Enum):
    ACKNOWLEDGED = auto()
    ACK_TIMEOUT = auto()
    SETTER_ERROR = auto()


@dataclass(frozen=True)
class Snapshot:
    status: Status
    requested_gain_db: float | None
    applied_gain_db: float
    queue_depth: int
    worker_calls: int
    reconfigure_calls: int
    busy_retries: int
    failure_count: int


class RamShadowEqPrototype:
    """Single outstanding band-gain request, applied only by worker context.

    ``config_pointer`` models the selector's currently published RAM config.
    A real firmware implementation must provide equivalent atomicity and
    separately prove that failed hardware updates leave the old bank active.
    """

    def __init__(self, *, busy_retry_limit: int = BUSY_RETRY_LIMIT,
                 ring: CommandRing | None = None):
        if busy_retry_limit <= 0:
            raise ValueError("busy retry limit must be positive")
        self.ring = ring or CommandRing()
        self.stock_config = STOCK_CONFIG
        self.shadow_buffers: list[EqConfig | None] = [None, None]
        self.active_shadow: int | None = None
        self.pending_shadow: int | None = None
        self.config_pointer = "stock"
        self._pending_work = False
        self.pending_gain: float | None = None
        self.status = Status.IDLE
        self.busy_retry_limit = busy_retry_limit
        self.busy_retries = 0
        self.worker_calls = 0
        self.reconfigure_calls = 0
        self.failure_count = 0
        self.lifecycle_order: list[str] = []
        self.event_flags = 0
        self.event_notifications = 0

    @property
    def active_config(self) -> EqConfig:
        if self.active_shadow is None:
            return self.stock_config
        selected = self.shadow_buffers[self.active_shadow]
        assert selected is not None
        return selected

    @property
    def active_pointer(self) -> str:
        return "stock" if self.active_shadow is None else f"shadow{self.active_shadow}"

    @property
    def ram_shadow(self) -> EqConfig | None:
        if self.pending_shadow is None:
            return None
        return self.shadow_buffers[self.pending_shadow]

    @staticmethod
    def _decode_gain(payload: bytes) -> float:
        if len(payload) != 4:
            raise ValueError("E1 requires exactly four payload bytes")
        gain = struct.unpack("<f", payload)[0]
        if not math.isfinite(gain) or not GAIN_MIN_DB <= gain <= GAIN_MAX_DB:
            raise ValueError("gain must be finite and in [-12, 0] dB")
        return gain

    def ep0_submit(self, setup: tuple[int, int, int, int, int],
                   payload: bytes) -> PushResult:
        """Validate, copy into separate shadow storage and enqueue; never apply."""
        if setup != E1_SETUP:
            self.status = Status.REJECTED
            raise ValueError("unsupported E1 setup packet")
        gain = self._decode_gain(payload)
        if self.pending_gain is not None:
            self.status = Status.QUEUE_FULL
            return PushResult.FULL
        inactive = 0 if self.active_shadow != 0 else 1
        candidate = self.active_config.with_band_gain(0, gain)
        # Stage a complete independent config; do not touch stock config or
        # coefficient scratch. Publish it only to the private mailbox here.
        self.shadow_buffers[inactive] = candidate
        result = self.ring.try_push(pack_command(EQ_COMMAND_ID))
        if result is not PushResult.OK:
            self.shadow_buffers[inactive] = None
            self.status = Status.QUEUE_FULL if result is PushResult.FULL else Status.REJECTED
            return result
        self.pending_gain = gain
        self.pending_shadow = inactive
        self.status = Status.QUEUED
        # Mirrors the stock post-push event-bit-3 notification.
        self.event_flags |= 1 << 3
        self.event_notifications += 1
        return result

    def worker_step(self, *, codec_busy: bool, context: str,
                    codec_initialized: bool = True, eq_enabled: bool = True,
                    sample_rate_valid: bool = True,
                    result: ReconfigureResult = ReconfigureResult.ACKNOWLEDGED) -> Status | None:
        """Drain existing commands in FIFO order; mutate selector only in worker."""
        if context != "usb_audio_app":
            if context == "af_thread":
                self.status = Status.WRONG_CONTEXT
                return self.status
            return None
        if not self._pending_work:
            popped, word = self.ring.try_pop()
            if popped is not PushResult.OK:
                return None
            if (word & 0xFF) != EQ_COMMAND_ID:
                return Status.IDLE
            self.worker_calls += 1
            self._pending_work = True
        if self.pending_gain is None or self.ram_shadow is None or self.pending_shadow is None:
            self._fail(Status.SETTER_ERROR)
            return self.status
        if not codec_initialized or not eq_enabled or not sample_rate_valid:
            self._fail(Status.CODEC_NOT_READY)
            return self.status
        if codec_busy:
            self.busy_retries += 1
            if self.busy_retries >= self.busy_retry_limit:
                self._fail(Status.BUSY_TIMEOUT)
            else:
                self.status = Status.WAITING_CODEC
            return self.status

        # Stock open path's verified order: codec lifecycle helper with
        # enable=1, then fixed selector/setter. Model choosing the private RAM
        # shadow at the selector boundary. No call occurs in EP0.
        self.status = Status.APPLYING
        self.config_pointer = f"shadow{self.pending_shadow}"
        self.lifecycle_order.extend(("codec_lifecycle_enable", "select_eq_config", "stock_setter"))
        self.reconfigure_calls += 1
        if result is ReconfigureResult.ACK_TIMEOUT:
            self.config_pointer = self.active_pointer
            self._fail(Status.ACK_TIMEOUT)
        elif result is ReconfigureResult.SETTER_ERROR:
            self.config_pointer = self.active_pointer
            self._fail(Status.SETTER_ERROR)
        else:
            self.active_shadow = self.pending_shadow
            self.config_pointer = f"shadow{self.active_shadow}"
            self._finish(Status.APPLIED)
        return self.status

    def read_status(self, setup: tuple[int, int, int, int, int] = STATUS_SETUP) -> Snapshot:
        if setup != STATUS_SETUP:
            raise ValueError("unsupported read-only E6 setup packet")
        return Snapshot(
            self.status, self.pending_gain,
            self.active_config.bands[0].gain_db, len(self.ring),
            self.worker_calls, self.reconfigure_calls, self.busy_retries,
            self.failure_count,
        )

    def encode_status(self, setup: tuple[int, int, int, int, int] = STATUS_SETUP) -> bytes:
        """Return a stable 32-byte read-only E6 status without side effects."""
        snapshot = self.read_status(setup)
        status_code = list(Status).index(snapshot.status) + 1
        active_slot = 0xFF if self.active_shadow is None else self.active_shadow
        flags = 1 if snapshot.requested_gain_db is not None else 0
        requested = 0.0 if snapshot.requested_gain_db is None else snapshot.requested_gain_db
        return struct.pack(
            "<4sBBBBffIIII", b"EQSR", 1, status_code, active_slot, flags,
            requested, snapshot.applied_gain_db, snapshot.queue_depth,
            snapshot.worker_calls, snapshot.reconfigure_calls,
            snapshot.failure_count,
        )

    def _finish(self, status: Status) -> None:
        self.status = status
        self.pending_gain = None
        self.pending_shadow = None
        self._pending_work = False
        self.busy_retries = 0

    def _fail(self, status: Status) -> None:
        self.failure_count += 1
        # Keep committed config and selected pointer unchanged. Never clear or
        # write codec busy state. The hardware bank rollback itself is outside
        # this software model and remains a firmware-level proof obligation.
        self._finish(status)

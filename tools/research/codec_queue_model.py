"""Offline model of the reconstructed EO-IC100 USB-audio command ring.

This is a behavioral test model, not an emulator of BES firmware or proof of
the task scheduler. Ring ABI values are taken from focused 0.23 disassembly.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from enum import Enum, auto
from threading import Lock
from typing import Callable


QUEUE_CAPACITY = 30
QUEUE_ENTRY_BYTES = 4
EQ_COMMAND_ID = 0x13  # candidate: stock dispatch routes this ID to unknown logger


class PushResult(Enum):
    OK = auto()
    FULL = auto()
    CONTENDED = auto()


class EqResult(Enum):
    SUCCESS = auto()
    BUSY_TIMEOUT = auto()
    ACK_TIMEOUT = auto()
    SETTER_ERROR = auto()
    WRONG_CONTEXT = auto()


def pack_command(command_id: int, arg0: int = 0, arg1: int = 0, high: int = 0) -> int:
    """Pack the observed command word: ID in bits 0..7, args in 8..23."""
    fields = (command_id, arg0, arg1, high)
    if any(not 0 <= item <= 0xFF for item in fields):
        raise ValueError("command fields must be bytes")
    return command_id | (arg0 << 8) | (arg1 << 16) | (high << 24)


def unpack_command(word: int) -> tuple[int, int, int, int]:
    if not 0 <= word <= 0xFFFFFFFF:
        raise ValueError("command must be uint32")
    return tuple((word >> shift) & 0xFF for shift in (0, 8, 16, 24))


class CommandRing:
    """30-word FIFO with interrupt-mask-equivalent critical sections.

    The firmware preserves PRIMASK around each short ring mutation. Here a
    lock models mutual exclusion; try_* operations intentionally never wait.
    """

    def __init__(self, capacity: int = QUEUE_CAPACITY):
        if capacity <= 0:
            raise ValueError("capacity must be positive")
        self.capacity = capacity
        self._items: deque[int] = deque()
        self._lock = Lock()

    def try_push(self, word: int) -> PushResult:
        if not self._lock.acquire(blocking=False):
            return PushResult.CONTENDED
        try:
            if len(self._items) >= self.capacity:
                return PushResult.FULL
            self._items.append(word & 0xFFFFFFFF)
            return PushResult.OK
        finally:
            self._lock.release()

    def try_pop(self) -> tuple[PushResult, int | None]:
        if not self._lock.acquire(blocking=False):
            return PushResult.CONTENDED, None
        try:
            if not self._items:
                return PushResult.FULL, None
            return PushResult.OK, self._items.popleft()
        finally:
            self._lock.release()

    def __len__(self) -> int:
        with self._lock:
            return len(self._items)

    def hold_lock_for_test(self):
        """Test-only hook to emulate an interrupt-masked critical section."""
        return self._lock


@dataclass(frozen=True)
class EqConfig:
    gain_db: float


@dataclass
class EqMailbox:
    config: EqConfig | None = None
    queued: bool = False
    lock: Lock = field(default_factory=Lock)


class EqCommandPath:
    """Candidate deferred path with nonblocking EP0 admission and worker drain.

    The mailbox/queue lock models an atomic publish operation. A real patch
    must establish equivalent ownership in the firmware's interrupt model.
    """

    def __init__(self, ring: CommandRing | None = None, busy_limit: int = 4):
        self.ring = ring or CommandRing()
        self.mailbox = EqMailbox()
        self.busy_limit = busy_limit
        self.busy_ticks = 0
        self.previous_gain = 0.0
        self.setter_calls = 0
        self.status: EqResult | None = None
        self.stock_commands: list[int] = []
        self._pending_eq = False
        self.event_flags = 0
        self.event_notifications = 0

    def ep0_submit(self, gain_db: float) -> PushResult:
        """Validate and enqueue without waiting or invoking codec code."""
        if not (-12.0 <= gain_db <= 0.0) or gain_db != gain_db:
            raise ValueError("invalid gain")
        if not self.mailbox.lock.acquire(blocking=False):
            return PushResult.CONTENDED
        try:
            if self.mailbox.queued:
                return PushResult.FULL
            self.mailbox.config = EqConfig(gain_db)
            result = self.ring.try_push(pack_command(EQ_COMMAND_ID))
            if result is PushResult.OK:
                self.mailbox.queued = True
                # Mirrors the stock wrapper's successful-push signal: event 3.
                self.event_flags |= 1 << 3
                self.event_notifications += 1
            else:
                self.mailbox.config = None
            return result
        finally:
            self.mailbox.lock.release()

    def enqueue_stock(self, word: int) -> PushResult:
        return self.ring.try_push(word)

    def worker_step(
        self,
        *,
        codec_busy: bool,
        context: str,
        ack_ok: bool = True,
        setter_ok: bool = True,
    ) -> EqResult | None:
        """Run one non-frame-critical consumer step; no guard is bypassed."""
        if context == "af_thread":
            return EqResult.WRONG_CONTEXT
        if self._pending_eq:
            return self._service_eq(codec_busy, ack_ok, setter_ok)
        result, word = self.ring.try_pop()
        if result is not PushResult.OK:
            return None
        command_id, _, _, _ = unpack_command(word)
        if command_id == EQ_COMMAND_ID:
            self._pending_eq = True
            return self._service_eq(codec_busy, ack_ok, setter_ok)
        self.stock_commands.append(word)
        return None

    def _service_eq(self, codec_busy: bool, ack_ok: bool, setter_ok: bool) -> EqResult | None:
        if codec_busy:
            self.busy_ticks += 1
            if self.busy_ticks >= self.busy_limit:
                self._finish(EqResult.BUSY_TIMEOUT)
                return self.status
            return None
        config = self.mailbox.config
        if config is None:
            self._finish(EqResult.SETTER_ERROR)
            return self.status
        self.setter_calls += 1
        # Model transactional visibility: commit only after acknowledged success.
        if not ack_ok:
            self._finish(EqResult.ACK_TIMEOUT)
        elif not setter_ok:
            self._finish(EqResult.SETTER_ERROR)
        else:
            self.previous_gain = config.gain_db
            self._finish(EqResult.SUCCESS)
        return self.status

    def _finish(self, status: EqResult) -> None:
        self.status = status
        self._pending_eq = False
        with self.mailbox.lock:
            self.mailbox.config = None
            self.mailbox.queued = False
        self.busy_ticks = 0

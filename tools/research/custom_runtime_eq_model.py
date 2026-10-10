#!/usr/bin/env python3
"""Offline design model for a future custom EO-IC100 runtime-EQ subsystem.

This models a proposed protocol/worker contract. It is not firmware emulation,
does not model codec registers, and does not establish RAM/scheduler safety.
"""
from __future__ import annotations

import math
import struct
from collections import deque
from dataclasses import dataclass
from enum import Enum, IntEnum


USB_VALUE = 0x454F
USB_INDEX = 0x4943
SET_GAIN = 0xE7
GET_STATUS = 0xE8
QUEUE_COMMAND = 0x13
QUEUE_CAPACITY = 30
STATUS_SIZE = 20


class State(IntEnum):
    IDLE = 0
    QUEUED = 1
    WAIT_READY = 2
    WRITE_INACTIVE = 3
    WAIT_ACK_HIGH = 4
    WAIT_ACK_LOW = 5
    COMPLETE = 6
    ERROR = 7
    HARDWARE_UNKNOWN = 8


class Result(IntEnum):
    NONE = 0
    ACCEPTED = 1
    APPLIED = 2
    BAD_REQUEST = 3
    BAD_PAYLOAD = 4
    QUEUE_FULL = 5
    READY_TIMEOUT = 6
    ACK_HIGH_TIMEOUT = 7
    ACK_LOW_TIMEOUT = 8
    REINIT_PENDING = 9


class PushResult(Enum):
    OK = "ok"
    FULL = "full"


def decode_set_gain(bm_request_type: int, request: int, value: int,
                    index: int, payload: bytes, w_length: int | None = None) -> int:
    """Validate proposed E7 and return signed gain in centi-dB."""
    if (bm_request_type, request, value, index) != (0x40, SET_GAIN, USB_VALUE, USB_INDEX):
        raise ValueError("bad setup packet")
    if (w_length is not None and w_length != 4) or len(payload) != 4:
        raise ValueError("bad payload length")
    gain, = struct.unpack("<f", payload)
    if not math.isfinite(gain) or not -12.0 <= gain <= 0.0:
        raise ValueError("gain out of range")
    return round(gain * 100)


def validate_status_request(bm_request_type: int, request: int, value: int,
                            index: int, w_length: int) -> None:
    if (bm_request_type, request, value, index, w_length) != (
            0xC0, GET_STATUS, USB_VALUE, USB_INDEX, STATUS_SIZE):
        raise ValueError("bad status setup packet")


def pack_queue_word(gain_cdb: int) -> int:
    if not -1200 <= gain_cdb <= 0:
        raise ValueError("gain outside protocol range")
    return QUEUE_COMMAND | ((gain_cdb & 0xFFFF) << 8)


def unpack_queue_word(word: int) -> tuple[int, int]:
    if word & 0xFF != QUEUE_COMMAND:
        raise ValueError("not runtime-EQ command ID")
    raw = (word >> 8) & 0xFFFF
    gain_cdb = raw - 0x10000 if raw & 0x8000 else raw
    if not -1200 <= gain_cdb <= 0:
        raise ValueError("invalid packed gain")
    return QUEUE_COMMAND, gain_cdb


@dataclass(frozen=True)
class Status:
    state: State = State.IDLE
    result: Result = Result.NONE
    flags: int = 0
    generation: int = 0
    applied_cdb: int = 0
    requested_cdb: int = 0
    active_bank: int = 0xFF
    ack_bits: int = 0
    success_count: int = 0
    error_count: int = 0

    def encode(self) -> bytes:
        """Proposed E8 fixed little-endian response, exactly 20 bytes."""
        data = struct.pack("<4sBBBBHhhBBHH", b"EOEQ", 1, self.state,
                           self.result, self.flags, self.generation & 0xFFFF,
                           self.applied_cdb, self.requested_cdb,
                           self.active_bank & 0xFF, self.ack_bits & 0xFF,
                           self.success_count & 0xFFFF,
                           self.error_count & 0xFFFF)
        assert len(data) == STATUS_SIZE
        return data


class BoundedQueue:
    """Single-core reference model; firmware must preserve its IRQ semantics."""
    def __init__(self, capacity: int = QUEUE_CAPACITY):
        self.capacity = capacity
        self.items: deque[int] = deque()

    def try_push(self, word: int) -> PushResult:
        if len(self.items) == self.capacity:
            return PushResult.FULL
        self.items.append(word & 0xFFFFFFFF)
        return PushResult.OK

    def try_pop(self) -> int | None:
        return self.items.popleft() if self.items else None


class RuntimeEqWorker:
    """Proposed one-transition-per-turn transaction model.

    The active software config is committed only after ACK high then low. A
    post-request timeout marks hardware state unknown; it never claims that
    the former bank is still active and never retries or clears stock flags.
    """
    def __init__(self, queue: BoundedQueue | None = None, ready_limit: int = 8,
                 ack_limit: int = 16):
        self.queue = queue or BoundedQueue()
        self.ready_limit = ready_limit
        self.ack_limit = ack_limit
        self.state = State.IDLE
        self.result = Result.NONE
        self.requested_cdb = 0
        self.applied_cdb = 0
        self.active_bank = 0
        self.pending_bank = 1
        self.bank_gain = [0, 0]
        self.waits = 0
        self.generation = 0
        self.success_count = 0
        self.error_count = 0
        self.hardware_known = True
        self.needs_reapply = False
        self.coefficient_writes = 0

    def submit(self, gain_cdb: int) -> PushResult:
        word = pack_queue_word(gain_cdb)
        result = self.queue.try_push(word)
        if result is PushResult.OK:
            self.requested_cdb = gain_cdb
            self.generation += 1
            self.state = State.QUEUED
            self.result = Result.ACCEPTED
        else:
            self.result = Result.QUEUE_FULL
        return result

    def fail(self, result: Result, uncertain: bool = False) -> None:
        self.result = result
        self.error_count += 1
        self.state = State.HARDWARE_UNKNOWN if uncertain else State.ERROR
        if uncertain:
            self.hardware_known = False

    def step(self, *, initialized: bool, stock_busy: bool,
             request_bit: bool = False, ack_bit: bool = False) -> State:
        if self.state in (State.IDLE, State.QUEUED, State.COMPLETE, State.ERROR):
            word = self.queue.try_pop()
            if word is None:
                self.state = State.IDLE
                return self.state
            _, self.requested_cdb = unpack_queue_word(word)
            self.pending_bank = self.active_bank ^ 1
            self.waits = 0
            self.state = State.WAIT_READY

        if self.state == State.WAIT_READY:
            if initialized and not stock_busy and not request_bit and not ack_bit:
                self.state = State.WRITE_INACTIVE
                self.waits = 0
            else:
                self.waits += 1
                if self.waits >= self.ready_limit:
                    self.fail(Result.READY_TIMEOUT)

        elif self.state == State.WRITE_INACTIVE:
            self.bank_gain[self.pending_bank] = self.requested_cdb
            self.coefficient_writes += 1
            self.state = State.WAIT_ACK_HIGH
            self.waits = 0

        elif self.state == State.WAIT_ACK_HIGH:
            if ack_bit:
                self.state = State.WAIT_ACK_LOW
                self.waits = 0
            else:
                self.waits += 1
                if self.waits >= self.ack_limit:
                    self.fail(Result.ACK_HIGH_TIMEOUT, uncertain=True)

        elif self.state == State.WAIT_ACK_LOW:
            if not ack_bit and not request_bit:
                self.active_bank = self.pending_bank
                self.applied_cdb = self.requested_cdb
                self.needs_reapply = False
                self.hardware_known = True
                self.success_count += 1
                self.result = Result.APPLIED
                self.state = State.COMPLETE
            else:
                self.waits += 1
                if self.waits >= self.ack_limit:
                    self.fail(Result.ACK_LOW_TIMEOUT, uncertain=True)
        return self.state

    def codec_reinitialized(self) -> None:
        """RAM intent persists; hardware-bank state becomes unknown."""
        self.hardware_known = False
        self.needs_reapply = True
        self.result = Result.REINIT_PENDING

    def status(self, request_bit: bool = False, ack_bit: bool = False) -> Status:
        flags = int(self.hardware_known) | (int(self.needs_reapply) << 1)
        ack = int(request_bit) | (int(ack_bit) << 1)
        return Status(self.state, self.result, flags, self.generation,
                      self.applied_cdb, self.requested_cdb,
                      self.active_bank if self.hardware_known else 0xFF,
                      ack, self.success_count, self.error_count)

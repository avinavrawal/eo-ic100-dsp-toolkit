import math
import threading
import time
import unittest

from codec_queue_model import (
    CommandRing,
    EqCommandPath,
    EqResult,
    PushResult,
    QUEUE_CAPACITY,
    pack_command,
    unpack_command,
)


class QueueModelTests(unittest.TestCase):
    def test_command_abi_and_normal_fifo(self):
        word = pack_command(0x12, 0x34, 0x56, 0x78)
        self.assertEqual(word, 0x78563412)
        self.assertEqual(unpack_command(word), (0x12, 0x34, 0x56, 0x78))
        q = CommandRing()
        for n in range(10):
            self.assertIs(q.try_push(pack_command(n)), PushResult.OK)
        got = [q.try_pop()[1] for _ in range(10)]
        self.assertEqual(got, [pack_command(n) for n in range(10)])

    def test_full_returns_without_overwrite(self):
        q = CommandRing()
        for n in range(QUEUE_CAPACITY):
            self.assertIs(q.try_push(n), PushResult.OK)
        self.assertIs(q.try_push(999), PushResult.FULL)
        self.assertEqual([q.try_pop()[1] for _ in range(QUEUE_CAPACITY)], list(range(QUEUE_CAPACITY)))

    def test_ep0_queue_full_is_reported_without_wait_or_mailbox_leak(self):
        path = EqCommandPath()
        for n in range(QUEUE_CAPACITY):
            self.assertIs(path.enqueue_stock(pack_command(n)), PushResult.OK)
        started = time.perf_counter()
        result = path.ep0_submit(-6.0)
        elapsed = time.perf_counter() - started
        self.assertIs(result, PushResult.FULL)
        self.assertLess(elapsed, 0.05)
        self.assertFalse(path.mailbox.queued)
        self.assertIsNone(path.mailbox.config)
        self.assertEqual(path.event_notifications, 0)

    def test_concurrent_single_producer_consumer_no_loss(self):
        q = CommandRing()
        total = 5000
        received = []
        producer_done = threading.Event()

        def producer():
            for n in range(total):
                while q.try_push(n) is not PushResult.OK:
                    time.sleep(0)
            producer_done.set()

        def consumer():
            while len(received) < total:
                result, value = q.try_pop()
                if result is PushResult.OK:
                    received.append(value)
                elif producer_done.is_set() and len(received) == total:
                    break
                else:
                    time.sleep(0)

        pt = threading.Thread(target=producer)
        ct = threading.Thread(target=consumer)
        pt.start(); ct.start()
        pt.join(5); ct.join(5)
        self.assertFalse(pt.is_alive())
        self.assertFalse(ct.is_alive())
        self.assertEqual(received, list(range(total)))

    def test_ep0_path_is_nonblocking_when_ring_critical_section_held(self):
        path = EqCommandPath()
        ring_lock = path.ring.hold_lock_for_test()
        ring_lock.acquire()
        try:
            started = time.perf_counter()
            result = path.ep0_submit(-6.0)
            elapsed = time.perf_counter() - started
        finally:
            ring_lock.release()
        self.assertIs(result, PushResult.CONTENDED)
        self.assertLess(elapsed, 0.05)
        self.assertFalse(path.mailbox.queued)
        self.assertEqual(path.setter_calls, 0)

    def test_mailbox_lock_contention_rejects_without_wait(self):
        path = EqCommandPath()
        path.mailbox.lock.acquire()
        try:
            started = time.perf_counter()
            result = path.ep0_submit(-6.0)
            elapsed = time.perf_counter() - started
        finally:
            path.mailbox.lock.release()
        self.assertIs(result, PushResult.CONTENDED)
        self.assertLess(elapsed, 0.05)

    def test_busy_defers_then_ready_calls_setter_once(self):
        path = EqCommandPath()
        self.assertIs(path.ep0_submit(-6.0), PushResult.OK)
        self.assertIsNone(path.worker_step(codec_busy=True, context="usb_audio_app"))
        self.assertEqual(path.setter_calls, 0)
        self.assertIs(path.worker_step(codec_busy=False, context="usb_audio_app"), EqResult.SUCCESS)
        self.assertEqual(path.setter_calls, 1)
        self.assertEqual(path.previous_gain, -6.0)
        self.assertEqual(path.event_flags & (1 << 3), 1 << 3)
        self.assertEqual(path.event_notifications, 1)

    def test_permanent_busy_expires_without_setter_or_flag_modification(self):
        path = EqCommandPath(busy_limit=3)
        self.assertIs(path.ep0_submit(-6.0), PushResult.OK)
        self.assertIsNone(path.worker_step(codec_busy=True, context="usb_audio_app"))
        self.assertIsNone(path.worker_step(codec_busy=True, context="usb_audio_app"))
        self.assertIs(path.worker_step(codec_busy=True, context="usb_audio_app"), EqResult.BUSY_TIMEOUT)
        self.assertEqual(path.setter_calls, 0)
        self.assertEqual(path.previous_gain, 0.0)
        self.assertFalse(path.mailbox.queued)

    def test_ack_timeout_preserves_committed_gain(self):
        path = EqCommandPath()
        path.previous_gain = -3.0
        self.assertIs(path.ep0_submit(-6.0), PushResult.OK)
        self.assertIs(path.worker_step(codec_busy=False, context="usb_audio_app", ack_ok=False), EqResult.ACK_TIMEOUT)
        self.assertEqual(path.previous_gain, -3.0)

    def test_existing_commands_preserved_in_fifo_order_around_eq(self):
        path = EqCommandPath()
        first, second = pack_command(1, 2), pack_command(2, 3)
        self.assertIs(path.enqueue_stock(first), PushResult.OK)
        self.assertIs(path.ep0_submit(-6.0), PushResult.OK)
        self.assertIs(path.enqueue_stock(second), PushResult.OK)
        path.worker_step(codec_busy=False, context="usb_audio_app")
        path.worker_step(codec_busy=False, context="usb_audio_app")
        path.worker_step(codec_busy=False, context="usb_audio_app")
        self.assertEqual(path.stock_commands, [first, second])

    def test_busy_does_not_reorder_later_stock_command(self):
        path = EqCommandPath()
        command = pack_command(0x42)
        path.ep0_submit(-6.0)
        path.enqueue_stock(command)
        self.assertIsNone(path.worker_step(codec_busy=True, context="usb_audio_app"))
        self.assertEqual(path.stock_commands, [])
        path.worker_step(codec_busy=False, context="usb_audio_app")
        path.worker_step(codec_busy=False, context="usb_audio_app")
        self.assertEqual(path.stock_commands, [command])

    def test_no_queue_or_setter_work_on_frame_critical_thread(self):
        path = EqCommandPath()
        path.ep0_submit(-6.0)
        self.assertIs(path.worker_step(codec_busy=False, context="af_thread"), EqResult.WRONG_CONTEXT)
        self.assertEqual(path.setter_calls, 0)

    def test_invalid_payload_rejected_before_queue(self):
        path = EqCommandPath()
        for gain in (-12.01, 0.01, float("inf"), float("-inf"), float("nan")):
            with self.subTest(gain=gain):
                with self.assertRaises(ValueError):
                    path.ep0_submit(gain)
        self.assertEqual(len(path.ring), 0)

    def test_second_pending_eq_rejected_without_overwrite(self):
        path = EqCommandPath()
        self.assertIs(path.ep0_submit(-6.0), PushResult.OK)
        self.assertIs(path.ep0_submit(-9.0), PushResult.FULL)
        path.worker_step(codec_busy=False, context="usb_audio_app")
        self.assertEqual(path.previous_gain, -6.0)


if __name__ == "__main__":
    unittest.main()

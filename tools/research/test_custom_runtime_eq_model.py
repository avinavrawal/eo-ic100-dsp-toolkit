import math
import struct
import unittest

from custom_runtime_eq_model import (
    BoundedQueue, GET_STATUS, PushResult, Result, RuntimeEqWorker, SET_GAIN,
    State, STATUS_SIZE, USB_INDEX, USB_VALUE, decode_set_gain, pack_queue_word,
    unpack_queue_word, validate_status_request,
)


class CustomRuntimeEqModelTests(unittest.TestCase):
    def request(self, gain):
        return decode_set_gain(0x40, SET_GAIN, USB_VALUE, USB_INDEX,
                               struct.pack('<f', gain))

    def test_exact_set_protocol_and_gain_quantization(self):
        cdb = self.request(-6.0)
        self.assertEqual(cdb, -600)
        self.assertEqual(unpack_queue_word(pack_queue_word(cdb)), (0x13, -600))
        with self.assertRaises(ValueError):
            decode_set_gain(0xC0, SET_GAIN, USB_VALUE, USB_INDEX, struct.pack('<f', -6.0))
        with self.assertRaises(ValueError):
            decode_set_gain(0x40, GET_STATUS, USB_VALUE, USB_INDEX, struct.pack('<f', -6.0))
        with self.assertRaises(ValueError):
            decode_set_gain(0x40, SET_GAIN, USB_VALUE, USB_INDEX, b'\0\0\0')
        with self.assertRaises(ValueError):
            decode_set_gain(0x40, SET_GAIN, USB_VALUE, USB_INDEX,
                            struct.pack('<f', -6.0), w_length=5)

    def test_exact_status_setup_packet(self):
        validate_status_request(0xC0, GET_STATUS, USB_VALUE, USB_INDEX, STATUS_SIZE)
        with self.assertRaises(ValueError):
            validate_status_request(0x40, GET_STATUS, USB_VALUE, USB_INDEX, STATUS_SIZE)
        with self.assertRaises(ValueError):
            validate_status_request(0xC0, GET_STATUS, USB_VALUE, USB_INDEX, STATUS_SIZE - 1)

    def test_reject_nonfinite_and_out_of_range_gain(self):
        for value in (math.nan, math.inf, -math.inf, -12.01, 0.01):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.request(value)
        self.assertEqual(self.request(-12.0), -1200)
        self.assertEqual(self.request(0.0), 0)

    def test_bounded_queue_rejects_full_without_overwrite(self):
        q = BoundedQueue(capacity=2)
        self.assertIs(q.try_push(pack_queue_word(-600)), PushResult.OK)
        self.assertIs(q.try_push(pack_queue_word(-300)), PushResult.OK)
        self.assertIs(q.try_push(pack_queue_word(0)), PushResult.FULL)
        self.assertEqual(unpack_queue_word(q.try_pop()), (0x13, -600))
        self.assertEqual(unpack_queue_word(q.try_pop()), (0x13, -300))

    def test_success_commits_only_after_ack_high_then_low(self):
        w = RuntimeEqWorker()
        self.assertIs(w.submit(-600), PushResult.OK)
        self.assertEqual(w.step(initialized=True, stock_busy=False), State.WRITE_INACTIVE)
        self.assertEqual(w.step(initialized=True, stock_busy=False), State.WAIT_ACK_HIGH)
        self.assertEqual(w.applied_cdb, 0)
        self.assertEqual(w.active_bank, 0)
        self.assertEqual(w.step(initialized=True, stock_busy=False, ack_bit=True), State.WAIT_ACK_LOW)
        self.assertEqual(w.applied_cdb, 0)
        self.assertEqual(w.step(initialized=True, stock_busy=False), State.COMPLETE)
        self.assertEqual(w.applied_cdb, -600)
        self.assertEqual(w.active_bank, 1)
        self.assertEqual(w.result, Result.APPLIED)

    def test_ready_timeout_performs_no_coefficient_write(self):
        w = RuntimeEqWorker(ready_limit=2)
        w.submit(-600)
        w.step(initialized=True, stock_busy=True)
        w.step(initialized=True, stock_busy=True)
        self.assertEqual(w.state, State.ERROR)
        self.assertEqual(w.result, Result.READY_TIMEOUT)
        self.assertEqual(w.coefficient_writes, 0)
        self.assertEqual(w.applied_cdb, 0)

    def test_ack_timeout_preserves_logical_old_config_but_marks_hardware_unknown(self):
        w = RuntimeEqWorker(ack_limit=2)
        w.submit(-600)
        w.step(initialized=True, stock_busy=False)
        w.step(initialized=True, stock_busy=False)
        w.step(initialized=True, stock_busy=False)
        w.step(initialized=True, stock_busy=False)
        self.assertEqual(w.state, State.HARDWARE_UNKNOWN)
        self.assertEqual(w.result, Result.ACK_HIGH_TIMEOUT)
        self.assertEqual(w.applied_cdb, 0)
        self.assertFalse(w.hardware_known)
        self.assertEqual(w.active_bank, 0)

    def test_reinitialization_retains_desired_gain_but_does_not_claim_applied(self):
        w = RuntimeEqWorker()
        w.submit(-300)
        w.step(initialized=True, stock_busy=False)
        w.step(initialized=True, stock_busy=False)
        w.step(initialized=True, stock_busy=False, ack_bit=True)
        w.step(initialized=True, stock_busy=False)
        self.assertEqual(w.applied_cdb, -300)
        w.codec_reinitialized()
        status = w.status()
        self.assertTrue(status.flags & 0x02)  # reapply pending
        self.assertFalse(status.flags & 0x01)  # hardware state unknown
        self.assertEqual(status.applied_cdb, -300)
        self.assertEqual(status.active_bank, 0xFF)

    def test_status_wire_size_and_identity(self):
        w = RuntimeEqWorker()
        response = w.status().encode()
        self.assertEqual(len(response), STATUS_SIZE)
        self.assertEqual(response[:5], b'EOEQ\x01')
        self.assertEqual(response[14], 0)


if __name__ == '__main__':
    unittest.main()

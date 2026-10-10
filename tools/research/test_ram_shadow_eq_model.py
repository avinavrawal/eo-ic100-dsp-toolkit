import math
import struct
import unittest

from codec_queue_model import CommandRing, PushResult, pack_command
from ram_shadow_eq_model import (
    E1_SETUP, STATUS_SETUP, RamShadowEqPrototype, ReconfigureResult,
    Status, STOCK_CONFIG,
)


def payload(gain):
    return struct.pack("<f", gain)


class RamShadowEqTests(unittest.TestCase):
    def test_ep0_validates_and_stages_without_reconfigure(self):
        p = RamShadowEqPrototype()
        self.assertIs(p.ep0_submit(E1_SETUP, payload(-6.0)), PushResult.OK)
        self.assertEqual(p.status, Status.QUEUED)
        self.assertEqual(p.stock_config, STOCK_CONFIG)
        self.assertEqual(p.ram_shadow.bands[0].gain_db, -6.0)
        self.assertEqual(p.active_config, STOCK_CONFIG)
        self.assertEqual(p.reconfigure_calls, 0)
        self.assertEqual(p.config_pointer, "stock")
        self.assertEqual(p.event_flags & 8, 8)
        self.assertEqual(p.event_notifications, 1)

    def test_malformed_setup_length_and_nonfinite_gain_rejected(self):
        for setup, data in [
            ((0xC0, 0xE1, 0x454F, 0x4943, 4), payload(-6.0)),
            ((0x40, 0xE1, 0x454F, 0x4943, 8), payload(-6.0)),
        ]:
            with self.assertRaises(ValueError):
                RamShadowEqPrototype().ep0_submit(setup, data)
        for gain in (-12.01, 0.01, math.nan, math.inf, -math.inf):
            with self.subTest(gain=gain), self.assertRaises(ValueError):
                RamShadowEqPrototype().ep0_submit(E1_SETUP, payload(gain))

    def test_busy_defer_then_worker_runs_stock_lifecycle_then_setter(self):
        p = RamShadowEqPrototype()
        p.ep0_submit(E1_SETUP, payload(-6.0))
        self.assertEqual(p.worker_step(codec_busy=True, context="usb_audio_app"), Status.WAITING_CODEC)
        self.assertEqual(p.reconfigure_calls, 0)
        self.assertEqual(p.worker_step(codec_busy=False, context="usb_audio_app"), Status.APPLIED)
        self.assertEqual(p.lifecycle_order, ["codec_lifecycle_enable", "select_eq_config", "stock_setter"])
        self.assertEqual(p.active_config.bands[0].gain_db, -6.0)
        self.assertEqual(p.config_pointer, "shadow0")

    def test_busy_timeout_preserves_stock_and_does_not_clear_busy(self):
        p = RamShadowEqPrototype(busy_retry_limit=2)
        p.ep0_submit(E1_SETUP, payload(-6.0))
        self.assertEqual(p.worker_step(codec_busy=True, context="usb_audio_app"), Status.WAITING_CODEC)
        self.assertEqual(p.worker_step(codec_busy=True, context="usb_audio_app"), Status.BUSY_TIMEOUT)
        self.assertEqual(p.active_config, STOCK_CONFIG)
        self.assertEqual(p.config_pointer, "stock")
        self.assertEqual(p.reconfigure_calls, 0)

    def test_unready_codec_never_reaches_stock_reconfiguration(self):
        for state in ((False, True, True), (True, False, True), (True, True, False)):
            p = RamShadowEqPrototype()
            p.ep0_submit(E1_SETUP, payload(-6.0))
            result = p.worker_step(
                codec_busy=False, context="usb_audio_app",
                codec_initialized=state[0], eq_enabled=state[1],
                sample_rate_valid=state[2],
            )
            self.assertEqual(result, Status.CODEC_NOT_READY)
            self.assertEqual(p.reconfigure_calls, 0)

    def test_ack_timeout_and_setter_error_restore_pointer_and_logical_config(self):
        for result, expected in [(ReconfigureResult.ACK_TIMEOUT, Status.ACK_TIMEOUT),
                                 (ReconfigureResult.SETTER_ERROR, Status.SETTER_ERROR)]:
            p = RamShadowEqPrototype()
            p.shadow_buffers[0] = STOCK_CONFIG.with_band_gain(0, -4.0)
            p.active_shadow = 0
            p.config_pointer = "shadow0"
            p.ep0_submit(E1_SETUP, payload(-6.0))
            self.assertEqual(p.worker_step(codec_busy=False, context="usb_audio_app", result=result), expected)
            self.assertEqual(p.active_config.bands[0].gain_db, -4.0)
            self.assertEqual(p.config_pointer, "shadow0")

    def test_repeated_updates_use_inactive_shadow_and_commit_only_after_ack(self):
        p = RamShadowEqPrototype()
        p.ep0_submit(E1_SETUP, payload(-6.0))
        p.worker_step(codec_busy=False, context="usb_audio_app")
        self.assertEqual(p.config_pointer, "shadow0")
        p.ep0_submit(E1_SETUP, payload(-9.0))
        self.assertEqual(p.pending_shadow, 1)
        self.assertEqual(p.config_pointer, "shadow0")
        self.assertEqual(p.active_config.bands[0].gain_db, -6.0)
        p.worker_step(codec_busy=False, context="usb_audio_app", result=ReconfigureResult.ACK_TIMEOUT)
        self.assertEqual(p.config_pointer, "shadow0")
        self.assertEqual(p.active_config.bands[0].gain_db, -6.0)

    def test_status_is_read_only_and_rejects_wrong_request(self):
        p = RamShadowEqPrototype()
        p.ep0_submit(E1_SETUP, payload(-6.0))
        before = p.read_status()
        self.assertEqual(before.status, Status.QUEUED)
        self.assertEqual(before.requested_gain_db, -6.0)
        self.assertEqual(before.applied_gain_db, -2.0)
        with self.assertRaises(ValueError):
            p.read_status((0x40, 0xE6, 0x454F, 0x4943, 32))
        self.assertEqual(p.status, Status.QUEUED)
        encoded = p.encode_status(STATUS_SETUP)
        self.assertEqual(len(encoded), 32)
        self.assertEqual(encoded[:4], b"EQSR")
        self.assertEqual(p.status, Status.QUEUED)

    def test_queue_full_has_no_shadow_or_pending_leak(self):
        ring = CommandRing(capacity=1)
        ring.try_push(pack_command(0x12))
        p = RamShadowEqPrototype(ring=ring)
        self.assertIs(p.ep0_submit(E1_SETUP, payload(-6.0)), PushResult.FULL)
        self.assertIsNone(p.ram_shadow)
        self.assertIsNone(p.pending_gain)
        self.assertEqual(p.status, Status.QUEUE_FULL)

    def test_frame_critical_context_never_applies_eq(self):
        p = RamShadowEqPrototype()
        p.ep0_submit(E1_SETUP, payload(-6.0))
        self.assertEqual(p.worker_step(codec_busy=False, context="af_thread"), Status.WRONG_CONTEXT)
        self.assertEqual(p.reconfigure_calls, 0)


if __name__ == "__main__":
    unittest.main()

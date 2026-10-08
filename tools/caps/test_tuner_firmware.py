import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from patch_eq import KNOWN
from tuner_firmware import build_image, validate_preset
from tuner_package import OUT, ROOT, preflight, verify_prepared_flash
import subprocess

ROOT = Path(__file__).resolve().parents[2]


class TunerFirmwareTests(unittest.TestCase):
    def setUp(self):
        self.stock = ROOT / "firmware/private/stock_b.bin"
        self.diamond = ROOT / "patcher/presets/diamond8.json"

    def test_diamond8_image_is_deterministic_and_official_hash_locked(self):
        with tempfile.TemporaryDirectory() as td:
            a = Path(td) / "a.bin"
            b = Path(td) / "b.bin"
            ra = build_image(self.stock, self.diamond, a)
            rb = build_image(self.stock, self.diamond, b)
            self.assertEqual(ra["output_sha256"], rb["output_sha256"])
            self.assertEqual(a.read_bytes(), b.read_bytes())
            self.assertEqual(ra["input_sha256"], KNOWN["b"]["stock"])
            self.assertEqual(ra["output_sha256"], "b03ff7f24b2ca54a11ac83ab0ed5b56083d4afb8a40a076094e759648ed8dc62")
            self.assertEqual(len(a.read_bytes()), 0x20004)
            self.assertEqual(a.read_bytes()[:4], b"\xff" * 4)
            self.assertEqual(a.read_bytes()[0x1EDC4:0x1EDC8], b"\xff" * 4)
            self.assertEqual(a.read_bytes()[-4:], (0x3C02E000).to_bytes(4, "little"))
            self.assertEqual(ra["changed_firmware_range"], ["0x1e4c4", "0x1e550"])

    def test_wrong_stock_hash_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            fake = Path(td) / "stock.bin"
            fake.write_bytes(b"not official firmware")
            with self.assertRaisesRegex(ValueError, "official Samsung"):
                build_image(fake, self.diamond, Path(td) / "out.bin")

    def test_invalid_preset_values_are_rejected(self):
        obj = json.loads(self.diamond.read_text())
        obj["filters"][0]["frequency_hz"] = float("nan")
        with self.assertRaisesRegex(ValueError, "frequency"):
            validate_preset(obj)
        obj = json.loads(self.diamond.read_text())
        obj["filters"].pop()
        with self.assertRaisesRegex(ValueError, "exactly eight"):
            validate_preset(obj)

    def test_local_deployment_preflight_and_phase_confirmation_guard(self):
        with tempfile.TemporaryDirectory() as td:
            image = Path(td) / "eq-b.bin"
            build_image(self.stock, self.diamond, image)
            verified = preflight(ROOT / "firmware/private", image)
            self.assertEqual(verified["input_sha256"], KNOWN["b"]["stock"])
            result = subprocess.run([
                str(OUT / "eq_native"), "stage-running", str(ROOT / "firmware/private"),
                str(image), str(Path(td) / "session"), "WRONG", "0" * 64
            ], text=True, capture_output=True)
            self.assertEqual(result.returncode, 70)
            self.assertIn("explicit phase authorization required", result.stderr)
            self.assertNotIn("VID:PID=", result.stdout)

    def test_pre_stage_flash_gate_and_faults(self):
        backup = (ROOT / "firmware/private/flash-backup.bin").read_bytes()
        fixture = bytearray(backup)
        fixture[0x2e000:0x2e004] = bytes.fromhex("1c ec 57 be")
        fixture[0x2e00c:0x2e010] = (0x3c04cc8c).to_bytes(4, "little")
        with tempfile.TemporaryDirectory() as td:
            phase = Path(td)
            path = phase / "flash-current.bin"
            path.write_bytes(fixture)
            self.assertEqual(verify_prepared_flash(ROOT / "firmware/private", phase)["active"], "A")
            for offset in (0x6010, 0x4000, 0x2e000, 0x2e00c):
                bad = bytearray(fixture)
                bad[offset] ^= 1
                path.write_bytes(bad)
                with self.subTest(offset=hex(offset)), self.assertRaises(ValueError):
                    verify_prepared_flash(ROOT / "firmware/private", phase)


if __name__ == "__main__":
    unittest.main()

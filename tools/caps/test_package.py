"""Offline tests only. Physical entry scripts and helper are never executed."""
import ctypes
import hashlib
import json
import os
import shlex
import subprocess
import tempfile
import unittest
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import patch
import package


class PackageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.output = package.ROOT / 'research/cache/caps-package-tests'
        cls.output.mkdir(parents=True, exist_ok=True)
        cls.fake = cls.output / 'offline_test'
        flags = shlex.split(subprocess.check_output(['pkg-config', '--cflags', '--libs', 'libusb-1.0'], text=True))
        parents = ['-I' + str(Path(f[2:]).parent) for f in flags if f.startswith('-I')]
        subprocess.run(['clang', '-O2', '-std=c11', '-D_DEFAULT_SOURCE', '-Wall', '-Wextra', '-Werror', '-Wno-unused-function',
                        str(package.SOURCE / 'offline_transport_test.c'), '-pthread', *parents, *flags, '-o', str(cls.fake)], check=True)
        cls.private = package.ROOT / 'firmware/private'
        cls.image = package.ROOT / 'research/cache/custom-vendor/caps-only.bin'
        cls.before = {p: package.digest(cls.private / p) for p in ('flash-backup.bin', 'stock_b.bin', 'programmer3001sp.bin')}

    @classmethod
    def tearDownClass(cls):
        for p, sha in cls.before.items():
            assert package.digest(cls.private / p) == sha

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=self.output)
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)

    def run_fake(self, mode, phase, fault='none', image=None):
        directory = self.base / phase
        directory.mkdir()
        env = dict(os.environ, CAPS_TEST_FAULT=fault)
        result = subprocess.run([str(self.fake), mode, str(self.private), str(image or self.image), str(directory), '0'],
                                text=True, capture_output=True, env=env, timeout=30)
        return result, directory

    def no_write(self, result):
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn('TEST_WRITE=', result.stdout)
        self.assertNotIn('TEST_ERASE=', result.stdout)
        self.assertNotIn('TEST_VENDOR_MUTATION=', result.stdout)

    def test_stage_only_b_complete_readback_and_flags(self):
        r, d = self.run_fake('stage-bootstrap', 'stage')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.count('TEST_WRITE=B'), 1)
        self.assertNotIn('TEST_ERASE=', r.stdout)
        self.assertEqual((d / 'a-before.bin').read_bytes(), (self.private / 'flash-backup.bin').read_bytes()[0x6000:0x2e000])
        self.assertEqual((d / 'a-before.bin').read_bytes(), (d / 'a-after.bin').read_bytes())
        self.assertEqual((d / 'flags-before.bin').read_bytes(), (d / 'flags-after.bin').read_bytes())
        expected = bytearray(self.image.read_bytes()[:-4]); expected[:4] = bytes.fromhex('1c ec 57 be')
        self.assertEqual((d / 'b-staged.bin').read_bytes(), expected)

    def test_activation_reverifies_and_writes_only_flags(self):
        stage, _ = self.run_fake('stage-bootstrap', 'stage')
        self.assertEqual(stage.returncode, 0)
        r, d = self.run_fake('activate-running', 'activate')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn('TEST_WRITE=B', r.stdout)
        self.assertEqual(r.stdout.count('TEST_WRITE='), 2)
        self.assertNotIn('TEST_VENDOR_MUTATION=', r.stdout)
        after = (d / 'flags-after.bin').read_bytes()
        self.assertEqual(after[:8], b'B' * 8)
        self.assertEqual(after[4096:4104], (d / 'flags-before.bin').read_bytes()[:8])

    def test_recovery_full_a_only_active_flag(self):
        r, d = self.run_fake('recover-running', 'recover')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('CAPS_A_FULL_READBACK=VERIFIED', r.stdout)
        self.assertEqual(r.stdout.count('TEST_WRITE='), 1)
        self.assertIn('TEST_WRITE=3c004000', r.stdout)
        self.assertNotIn('TEST_WRITE=B', r.stdout)
        self.assertEqual((d / 'flags-after.bin').read_bytes()[:8], b'A' * 8)
        self.assertEqual((d / 'flags-after.bin').read_bytes()[4096:], (d / 'flags-before.bin').read_bytes()[4096:])

    def test_bad_a_prevents_all_writes(self):
        for fault in ('A-read', 'A-corrupt'):
            r, _ = self.run_fake('stage-bootstrap', fault, fault)
            self.no_write(r)

    def test_already_a_recovery_rechecks_without_write(self):
        r, d = self.run_fake('recover-bootstrap-A', 'recover')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('CAPS_ALREADY_A=YES no write', r.stdout)
        self.assertNotIn('TEST_ERASE=', r.stdout)
        self.assertNotIn('TEST_WRITE=', r.stdout)
        self.assertEqual((d / 'flags-before.bin').read_bytes(), (d / 'flags-after.bin').read_bytes())

    def test_bad_b_prevents_activation_flags(self):
        self.run_fake('stage-bootstrap', 'stage')
        r, _ = self.run_fake('activate-running', 'activate', 'B-corrupt')
        self.no_write(r)

    def test_flag_identity_bootstrap_hard_stops(self):
        for fault in ('flag', 'identity', 'bootstrap'):
            r, _ = self.run_fake('stage-bootstrap', fault, fault)
            self.no_write(r)

    def test_version_and_check_stop_before_ota(self):
        for fault in ('version', 'CHECK'):
            r, _ = self.run_fake('enter-A', fault, fault)
            self.no_write(r)

    def test_bad_image_hash_stops_before_transport(self):
        changed = self.base / 'changed.bin'
        b = bytearray(self.image.read_bytes()); b[100] ^= 1; changed.write_bytes(b)
        r, _ = self.run_fake('stage-bootstrap', 'stage', image=changed)
        self.no_write(r)
        self.assertNotIn('VID:PID=', r.stdout)

    def test_probe_only_one_caps_no_queries(self):
        r, _ = self.run_fake('probe', 'probe')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.count('TEST_CONTROL='), 1)
        self.assertIn('TEST_CONTROL=c0/e0/454f/4943/12', r.stdout)
        self.assertNotIn('TEST_VENDOR_MUTATION=', r.stdout)
        r, _ = self.run_fake('probe', 'bad-probe', 'CAPS')
        self.assertNotEqual(r.returncode, 0)

    def test_parse_device_paths_rejects_bad_input(self):
        self.assertEqual(package.parse_devices('["/dev/bus/usb/001/002"]'), ['/dev/bus/usb/001/002'])
        for value in ('{}', '["/tmp/device"]', '["/dev/bus/usb/1/2", "/dev/bus/usb/1/2"]'):
            with self.assertRaises(ValueError):
                package.parse_devices(value)

    def test_recorded_backup_hash_required_before_usb(self):
        private = self.base / 'private'; private.mkdir()
        for name in ('stock_b.bin', 'flash-backup.bin', 'programmer3001sp.bin'):
            (private / name).symlink_to(self.private / name)
        text = (self.private / 'SHA256SUMS.txt').read_text()
        (private / 'SHA256SUMS.txt').write_text(text.replace(package.HASHES['flash-backup.bin'], '0' * 64))
        args = SimpleNamespace(private=private, image=self.image, helper=self.fake)
        with patch('package.subprocess.run', side_effect=AssertionError('USB must not be called')):
            with self.assertRaisesRegex(ValueError, 'recorded backup hash'):
                package.preflight(args)

    def test_failed_stage_readback_never_changes_flags(self):
        r, _ = self.run_fake('stage-bootstrap', 'stage', 'B-corrupt')
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual(r.stdout.count('TEST_WRITE=B'), 1)
        self.assertNotIn('TEST_ERASE=', r.stdout)
        self.assertNotIn('CAPS_PHASE_OK=', r.stdout)

    def test_sha256_padding_vectors(self):
        source = self.base / 'sha.c'
        source.write_text('#include "sha256.h"\nint test_sha(const unsigned char *p,size_t n,char *out){return caps_sha(p,n,out);}\n')
        lib = self.base / 'sha.so'
        subprocess.run(['clang', '-shared', '-fPIC', '-I' + str(package.SOURCE), str(source), '-o', str(lib)], check=True)
        fn = ctypes.CDLL(str(lib)).test_sha
        fn.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_void_p]
        for n in (0, 3, 55, 56, 63, 64, 65, 1000):
            b = bytes(i % 251 for i in range(n)); out = ctypes.create_string_buffer(65)
            self.assertEqual(fn(b, len(b), out), 0)
            self.assertEqual(out.value.decode(), hashlib.sha256(b).hexdigest())


if __name__ == '__main__':
    unittest.main()

"""Native offline guards/state tests. No USB enumeration or transfer."""
import json
import subprocess
import unittest
import tempfile
import os
from pathlib import Path
from build_macos import OUT,SOURCE,ROOT
from flash_state import analyze,BASELINE_SHA
from macos_package import preflight

class MacTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import shlex
        cls.output=OUT/'native-fixtures';cls.output.mkdir(parents=True,exist_ok=True);cls.fixture=cls.output/'fake-native'
        flags=shlex.split(subprocess.check_output(['pkg-config','--cflags','--libs','libusb-1.0'],text=True));parents=['-I'+str(Path(p[2:]).parent) for p in flags if p.startswith('-I')]
        subprocess.run(['clang','-O2','-std=c11','-D_DEFAULT_SOURCE','-Wall','-Wextra','-Werror','-Wno-unused-function',str(SOURCE/'offline_macos_test.c'),'-pthread',*parents,*flags,'-o',str(cls.fixture)],check=True)

    def native_fixture(self,phase,fault='none',base=None):
        if base is None:
            tmp=tempfile.TemporaryDirectory(dir=self.output);self.addCleanup(tmp.cleanup);base=Path(tmp.name)
            (base/'baseline.bin').write_bytes((OUT/'session-20261007/immediate/flash-current.bin').read_bytes())
        directory=base/phase;directory.mkdir()
        modes={'stage':'stage-running','activate':'activate-running','recover':'recover-running'}
        tokens={'stage':'STAGE-CAPS-B','activate':'ACTIVATE-CAPS-B','recover':'RECOVER-VERIFIED-A'}
        r=subprocess.run([str(self.fixture),modes[phase],str(ROOT/'firmware/private'),str(ROOT/'research/cache/custom-vendor/caps-only.bin'),str(directory),tokens[phase]],text=True,capture_output=True,env=dict(os.environ,CAPS_TEST_FAULT=fault))
        return r,base

    def test_native_stage_and_activation_flow_with_mocked_usb(self):
        r,base=self.native_fixture('stage');self.assertEqual(r.returncode,0,r.stderr);self.assertEqual(r.stdout.count('TEST_WRITE=B'),1);self.assertNotIn('TEST_ERASE=',r.stdout);self.assertIn('MACOS_FLASH_OUTSIDE_B_UNCHANGED=YES',r.stdout)
        r,_=self.native_fixture('activate',base=base);self.assertEqual(r.returncode,0,r.stderr);self.assertEqual(r.stdout.count('TEST_WRITE='),2);self.assertNotIn('TEST_WRITE=B',r.stdout);self.assertIn('CAPS_BOOT_SELECTION=B VERIFIED',r.stdout)

    def test_native_changed_baseline_stops_before_burn(self):
        r,_=self.native_fixture('stage','baseline');self.assertNotEqual(r.returncode,0);self.assertNotIn('TEST_WRITE=',r.stdout);self.assertNotIn('TEST_ERASE=',r.stdout)

    def test_native_post_stage_outside_b_change_stops_success(self):
        r,_=self.native_fixture('stage','post-stage-outside');self.assertNotEqual(r.returncode,0);self.assertIn('TEST_WRITE=B',r.stdout);self.assertNotIn('MACOS_PHASE_OK=',r.stdout);self.assertNotIn('TEST_ERASE=',r.stdout)

    def test_native_recovery_writes_only_active_selection(self):
        r,_=self.native_fixture('recover');self.assertEqual(r.returncode,0,r.stderr);self.assertEqual(r.stdout.count('TEST_WRITE='),1);self.assertIn('TEST_WRITE=3c004000',r.stdout);self.assertNotIn('TEST_WRITE=B',r.stdout)

    def test_native_manifest_preflight(self):
        private,image=preflight()
        self.assertEqual(private,ROOT/'firmware/private')
        self.assertEqual(image.name,'caps-only.bin')

    def test_readonly_cli_rejects_every_persistent_phase_before_usb(self):
        for mode,token in [('stage-running','STAGE-CAPS-B'),('activate-running','ACTIVATE-CAPS-B'),('recover-running','RECOVER-VERIFIED-A'),('probe','GET-EOIC-CAPS')]:
            r=subprocess.run([str(OUT/'caps_readonly'),mode,'missing-private','missing-image','missing-directory',token],text=True,capture_output=True)
            self.assertEqual(r.returncode,70)
            self.assertIn('read-only binary rejects',r.stderr)
            self.assertNotIn('VID:PID=',r.stdout)

    def test_native_writer_rejects_missing_or_wrong_authorization_before_usb(self):
        for mode in ('stage-running','activate-running','recover-running','probe'):
            for args in ([],['WRONG']):
                r=subprocess.run([str(OUT/'caps_native'),mode,'missing-private','missing-image','missing-directory',*args],text=True,capture_output=True)
                self.assertEqual(r.returncode,70)
                self.assertIn('explicit phase authorization',r.stderr)
                self.assertNotIn('VID:PID=',r.stdout)

    def test_bes_command_guard_blocks_write_commands_before_transport(self):
        out=ROOT/'research/cache/caps-macos/offline-tests';out.mkdir(parents=True,exist_ok=True)
        source=out/'guard.c'
        source.write_text('#define CAPS_READ_ONLY 1\n#include "sha256.h"\n#include "protocol.c"\nint main(void){unsigned char p[12]={0};unsigned char commands[]={0x61,0x62,0x64,0x65,0x99};for(unsigned i=0;i<sizeof(commands);i++)if(sendmsg(NULL,commands[i],0,p,12,NULL,0)!=-90)return 1;return 0;}\n')
        import shlex
        flags=shlex.split(subprocess.check_output(['pkg-config','--cflags','--libs','libusb-1.0'],text=True))
        includes=['-I'+str(Path(p[2:]).parent) for p in flags if p.startswith('-I')]
        binary=out/'guard'
        subprocess.run(['clang','-O2','-std=c11','-D_DEFAULT_SOURCE','-I'+str(SOURCE),str(source),'-pthread',*includes,*flags,'-o',str(binary)],check=True)
        r=subprocess.run([str(binary)],text=True,capture_output=True)
        self.assertEqual(r.returncode,0)
        self.assertEqual(r.stderr.count('blocked before transport'),5)

    def test_live_snapshot_comparison_offline(self):
        b=(OUT/'session-20261007/immediate/flash-current.bin').read_bytes()
        a=(ROOT/'firmware/private/flash-backup.bin').read_bytes()
        stock=(ROOT/'firmware/private/stock_b.bin').read_bytes()
        r=analyze(b,a,stock)
        self.assertEqual(r['current_sha256'],BASELINE_SHA)
        self.assertTrue(r['A_intact'] and r['A_header_valid'] and r['B_header_valid'] and r['B_is_known_diamond8'])
        self.assertEqual(r['active_flag'],'41 41 41 41 41 41 41 41')
        self.assertEqual(r['backup_flag'],'42 42 42 42 42 42 42 42')
        self.assertTrue(all(v['valid'] for v in r['nv_record_crc'].values()))
        self.assertEqual(r['regions']['after_B']['changed_bytes'],7)

    def test_corrupted_authority_and_a_are_detected(self):
        b=(OUT/'session-20261007/immediate/flash-current.bin').read_bytes();a=(ROOT/'firmware/private/flash-backup.bin').read_bytes();stock=(ROOT/'firmware/private/stock_b.bin').read_bytes()
        with self.assertRaises(ValueError):analyze(b,a[:-1],stock)
        bad=bytearray(b);bad[0x6010]^=1
        self.assertFalse(analyze(bad,a,stock)['A_intact'])

if __name__=='__main__':unittest.main()

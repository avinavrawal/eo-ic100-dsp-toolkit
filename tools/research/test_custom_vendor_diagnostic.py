"""Diagnostic firmware CPU tests; no host USB library or device operations."""
import json
import math
import struct
import unittest
from custom_vendor_patch import ROOT,OUT,ram_image,sha,changed_ranges
from custom_vendor_diagnostic_patch import build,BASE_SHA,OFFSET,STATE
from custom_vendor_emulate import Machine,FRAME
from unicorn.arm_const import UC_ARM_REG_R4
from eoic_eq_diagnostic_probe import decode

def read(m):
    r=m.setup(request=0xe2,length=32)
    assert (r['result'],r['state'],r['length'])==(1,4,32),r
    return struct.unpack('<4sHH6I',bytes.fromhex(r['payload']))

def set_gain(m,gain=-6):
    r=m.setup(bm=0x40,request=0xe1,length=4)
    assert (r['result'],r['state'],r['length'])==(1,3,4),r
    return m.receive(struct.pack('<f',gain),pointer=r['pointer'])

class DiagnosticTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw=(ROOT/'firmware/private/stock_b.bin').read_bytes()
        cls.image,cls.report=build(cls.raw)

    def test_deterministic_image_and_changes(self):
        image,report=build(self.raw)
        self.assertEqual(image,self.image)
        self.assertEqual(sha(image),report['output_sha256'])
        self.assertEqual(report['base_sha256'],BASE_SHA)
        self.assertEqual(report['changed_ranges'],[[hex(a),hex(b)] for a,b in changed_ranges(self.raw,image)])
        self.assertEqual(len(image),0x20004)
        self.assertEqual(image[-4:],self.raw[-4:])

    def test_ack_helpers_boot_eq_usb_hid_preserved(self):
        old=(OUT/'eq-test.bin').read_bytes()
        self.assertEqual(old[0x1f19c:0x1f21c],self.image[0x1f19c:0x1f21c])
        for a,b in [(0x1e4c4,0x1e550),(0x1ec8c,0x1edc4)]:
            self.assertEqual(self.image[a:b],self.raw[a:b])
        a,b=ram_image(self.raw),ram_image(self.image)
        for s,e in [(0x1506c,0x1509b),(0xc800,0xc9a0),(0x15bec,0x15c78)]:
            self.assertEqual(a[s:e],b[s:e])

    def test_unique_caps_and_original_caps_unchanged(self):
        for variant,flags in [('caps-only',0),('eq-test',0),('eq-diagnostic',1)]:
            m=Machine(variant)
            self.assertEqual(bytes.fromhex(m.setup()['payload']),struct.pack('<4sHHI',b'EOIC',1,8,flags))
            self.assertEqual(m.eq_args,[]);self.assertEqual(m.writes,[])

    def test_initial_diagnostics_and_no_mutation(self):
        m=Machine('eq-diagnostic')
        self.assertEqual(read(m),(b'EQDG',1,32,0,0,0,0xffffffff,0,20))
        m.activate_audio()
        self.assertEqual(read(m)[-1],31)
        self.assertEqual(m.eq_args,[]);self.assertEqual(m.writes,[])
        self.assertEqual(read(m)[3:8],(0,0,0,0xffffffff,0))

    def test_core_ep0_read_responses(self):
        m=Machine('eq-diagnostic')
        self.assertEqual(m.core_setup()['dma_payload'],'454f49430100080001000000')
        r=m.core_setup(request=0xe2,length=32)
        self.assertEqual(r['state'],4);self.assertEqual(r['length'],32)
        self.assertEqual(bytes.fromhex(r['dma_payload'])[:8],b'EQDG\x01\x00\x20\x00')

    def test_setup_rejections_recorded(self):
        for kw in [dict(bm=0xc0),dict(bm=0x41),dict(value=0),dict(index=0),dict(length=3),dict(length=241)]:
            m=Machine('eq-diagnostic');args=dict(bm=0x40,request=0xe1,length=4);args.update(kw)
            self.assertEqual(m.setup(**args)['result'],0)
            self.assertEqual(read(m)[3:8],(1,1,1,0xffffffff,0))
            self.assertEqual(m.eq_args,[])

    def test_runtime_guard_rejection(self):
        m=Machine('eq-diagnostic')
        self.assertEqual(set_gain(m),dict(result=0,state=3))
        self.assertEqual(read(m)[3:8],(1,15,2,0xffffffff,0))
        self.assertEqual(m.eq_args,[])

    def test_all_runtime_guards_before_setter(self):
        for addr,data in [(0x200162cd,b'\0'),(0x200162b8,b'\0'*4),
                          (0x200162b4,b'\1'),(0x200162c8,struct.pack('<I',8000)),
                          (0x20015bf4,struct.pack('<I',9))]:
            m=Machine('eq-diagnostic');m.activate_audio();m.uc.mem_write(addr,data)
            self.assertEqual(set_gain(m)['result'],0)
            self.assertEqual(read(m)[5],2);self.assertEqual(m.eq_args,[])

    def test_malformed_payloads_rejected(self):
        for payload in [b'',b'\0'*3,b'\0'*5]+[struct.pack('<f',x) for x in [math.nan,math.inf,-math.inf,1,-12.01]]:
            m=Machine('eq-diagnostic');m.activate_audio();m.setup(bm=0x40,request=0xe1,length=4)
            self.assertEqual(m.vendor(payload,length=4),1)
            self.assertEqual(read(m)[5],6);self.assertEqual(m.eq_args,[])

    def test_success_and_actual_status_completion(self):
        m=Machine('eq-diagnostic');m.activate_audio()
        self.assertEqual(set_gain(m),dict(result=1,state=6))
        state=bytes(m.uc.mem_read(STATE,32))
        self.assertEqual(struct.unpack('<4sHH6I',state)[3:8],(1,0x13f,3,0,0))
        # Invoke actual EP0 IN completion with the accepted frame. The hook
        # must replay the original state reset and hardware register loads.
        frame=bytes(m.uc.mem_read(FRAME,20));m.uc.mem_write(0x2001ac74,frame)
        m.call(0x206131,1,1)
        self.assertEqual(m.uc.mem_read(0x2001ac74,1),b'\0')
        self.assertEqual(read(m)[3:8],(1,0x33f,3,0,0))
        self.assertEqual(len(m.eq_args),1)
        self.assertEqual(struct.unpack_from('<f',bytes.fromhex(m.eq_args[0]['cfg']))[0],-6)

    def test_setter_error_preserved(self):
        m=Machine('eq-diagnostic');m.activate_audio();m.stubs[0x20a938]=7
        self.assertEqual(set_gain(m),dict(result=0,state=3))
        self.assertEqual(read(m)[3:8],(1,0x5f,4,7,0))

    def test_both_ack_timeouts_and_active_state_preservation(self):
        for mode,bank,control,mask,address in [('stuck-low',0,0,1,0x40302000),
                ('stuck-high',1,(1<<22)|(1<<24),2,0x40302200)]:
            m=Machine('eq-diagnostic',ack_mode=mode);m.activate_audio()
            m.call(0x20a939,0,0x20015bec,2)
            m.uc.mem_write(0x200162b4,b'\0');m.uc.mem_write(0x200162bc,bytes([bank]))
            m.uc.mem_write(0x403000e0,struct.pack('<I',control))
            before=bytes(m.uc.mem_read(address,0xa0));start=m.ack_reads
            self.assertEqual(set_gain(m),dict(result=0,state=3))
            self.assertLess(m.count,400000)
            self.assertGreaterEqual(m.ack_reads-start,65535)
            self.assertLessEqual(m.ack_reads-start,65540)
            self.assertEqual(read(m)[3:8],(1,0xdf,5,3,mask))
            self.assertEqual(m.uc.mem_read(0x200162bc,1),bytes([bank]))
            self.assertEqual(m.uc.mem_read(0x200162b4,1),b'\0')
            self.assertEqual(bytes(m.uc.mem_read(address,0xa0)),before)

    def test_storage_guard_and_out_dma_fence(self):
        m=Machine('eq-diagnostic')
        self.assertEqual(m.setup(bm=0x40,request=6,value=0,index=0,length=177)['result'],0)
        self.assertEqual(struct.unpack('<I',m.uc.mem_read(0x2001b164,4))[0],176)
        m.uc.mem_write(0x2001b160,struct.pack('<I',0x21000200))
        self.assertEqual(m.setup()['result'],0)

    def test_all_legacy_classifiers_and_check_reply(self):
        for n,cmd in enumerate(['QUERY_SW_VER','QUERY_SN','SYS_REBOOT','SYS_SHUTDOWN','PING_THROUGH_VENDOR','CHECK','FW_UPDATE'],1):
            m=Machine('eq-diagnostic');r=m.setup(bm=0x40,request=6,value=0,index=0,length=len(cmd))
            self.assertEqual(m.receive(cmd.encode(),pointer=r['pointer']),dict(result=1,state=6))
            self.assertEqual(m.uc.mem_read(0x200197f0,1)[0],n)
            self.assertEqual(m.eq_args,[])
        m=Machine('eq-diagnostic');m.vendor(b'CHECK',bm=0x40,request=6,value=0,index=0)
        read(m);m.setup()
        self.assertEqual(m.setup(request=12,value=0,index=0,length=3)['payload'],'312e31')

    def test_diagnostic_reads_preserve_previous_outcome(self):
        m=Machine('eq-diagnostic');set_gain(m)
        a=read(m);self.assertEqual(read(m),a)
        m.setup();self.assertEqual(read(m),a)
        self.assertEqual(m.eq_args,[])

    def test_original_setter_cpu_and_mmio_behavior_identical(self):
        machines=[]
        for variant in ['eq-test','eq-diagnostic']:
            m=Machine(variant);m.activate_audio()
            m.call(0x20a939,0,0x20015bec,2)
            m.uc.mem_write(0x200162b4,b'\0');m.writes.clear()
            self.assertEqual(set_gain(m),dict(result=1,state=6))
            machines.append(m)
        a,b=machines
        self.assertEqual(a.eq_args,b.eq_args)
        self.assertEqual(a.writes,b.writes)
        self.assertEqual(a.ack_reads,b.ack_reads)
        for addr,size in [(0x20015fa4,0x188),(0x40302000,0x400),(0x200162b4,0x20)]:
            self.assertEqual(a.uc.mem_read(addr,size),b.uc.mem_read(addr,size))

    def test_status_hook_replays_original_branch(self):
        machines=[]
        for variant in ['eq-test','eq-diagnostic']:
            m=Machine(variant);m.setup()
            m.uc.mem_write(0x2001ac74,b'\x06'+b'\0'*19)
            m.uc.mem_write(0x40180810,struct.pack('<I',0x12345678))
            m.uc.mem_write(0x40180814,struct.pack('<I',0x89abcdef))
            m.writes.clear();m.call(0x206131,1,1);machines.append(m)
        self.assertEqual(machines[0].writes,machines[1].writes)
        self.assertEqual(machines[0].uc.mem_read(0x2001ac74,20),machines[1].uc.mem_read(0x2001ac74,20))

    def test_host_decode_valid_and_malformed_reports(self):
        m=Machine('eq-diagnostic');r=m.setup(request=0xe2,length=32)
        raw=bytes.fromhex(r['payload']);self.assertEqual(decode(raw)['sequence'],0)
        for bad in [raw[:-1],b'FAIL'+raw[4:],raw[:12]+struct.pack('<I',0x400)+raw[16:]]:
            with self.assertRaises(ValueError):decode(bad)

if __name__=='__main__': unittest.main()

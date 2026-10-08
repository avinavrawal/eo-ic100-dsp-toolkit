import hashlib
import json
import math
import random
import struct
import unittest
from custom_vendor_patch import ROOT,OUT,HOOKS,SOURCE_SHA,FLASH_BASE,INJECT_CODE,build,changed_ranges,metadata,ram_image,validate_blob
from custom_vendor_emulate import Machine,FRAME,ARGS,PAYLOAD
from arm_elf import encode_branch,decode_branch,link
from eoic_caps_probe import decode_caps


class CustomVendorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw=(ROOT/'firmware/private/stock_b.bin').read_bytes()
        cls.caps,cls.caps_report=build(cls.raw,False)
        cls.eq,cls.eq_report=build(cls.raw,True)

    def test_known_input_hash_and_rejection(self):
        self.assertEqual(hashlib.sha256(self.raw).hexdigest(),SOURCE_SHA)
        bad=bytearray(self.raw);bad[100]^=1
        with self.assertRaises(ValueError):metadata(bytes(bad))
        with self.assertRaises(ValueError):metadata((ROOT/'firmware/private/stock_a.bin').read_bytes())

    def test_deterministic_images_and_output_hash(self):
        for enabled,old,report in [(False,self.caps,self.caps_report),(True,self.eq,self.eq_report)]:
            new,again=build(self.raw,enabled)
            self.assertEqual(new,old)
            self.assertEqual(hashlib.sha256(new).hexdigest(),report['output_sha256'])
            self.assertEqual(again['output_sha256'],report['output_sha256'])

    def test_exact_changes_and_footer_metadata(self):
        self.assertEqual(changed_ranges(self.raw,self.caps),[(0x1d384,0x1d388),(0x1d990,0x1d994),(0x1edc4,0x20004)])
        self.assertEqual(changed_ranges(self.raw,self.eq),[
            (0x12f86,0x12f87),(0x13042,0x1304a),(0x1304e,0x13054),
            (0x1311c,0x13128),(0x13239,0x1323a),(0x1d384,0x1d388),
            (0x1d990,0x1d994),(0x1edc4,0x20004)])
        for image in [self.caps,self.eq]:
            if image is self.caps:
                self.assertEqual(image[:0x1d384],self.raw[:0x1d384])
            self.assertEqual(struct.unpack_from('<I',image,len(image)-4)[0],FLASH_BASE)
            self.assertEqual(image[:16],self.raw[:16])
            self.assertEqual(image[0x1ec8c:0x1edc4],self.raw[0x1ec8c:0x1edc4])
            self.assertEqual(len(image)-4,4*32768)

    def test_stock_code_eq_and_descriptors_preserved(self):
        for image in [self.caps,self.eq]:
            oldram=ram_image(self.raw);newram=ram_image(image)
            for start,end in [(0xd998,0xdaf8),(0xdd10,0xe084),(0xe5fc,0xe7e0),
                              (0xc800,0xc9a0),
                              (0x15bec,0x15c78),(0x1506c,0x1509b)]:
                self.assertEqual(oldram[start:end],newram[start:end])
            if image is self.eq:
                for start,end in [(0xa6ae,0xa6b0),(0xa76a,0xa77c),(0xa844,0xa84e),(0xa960,0xa962)]:
                    self.assertNotEqual(oldram[start:end],newram[start:end])
            else:
                self.assertEqual(oldram[0xa178:0xa868],newram[0xa178:0xa868])
            differences=changed_ranges(oldram,newram)
            self.assertIn((0x14aac,0x14ab0),differences)
            self.assertIn((0x150b8,0x150bc),differences)

    def test_thumb_pointer_and_relocation_validation(self):
        for report in [self.caps_report,self.eq_report]:
            for hook in report['hooks'].values():
                target=int(hook['new'],16)
                self.assertEqual(target&1,1)
                self.assertTrue(INJECT_CODE<=target&~1<INJECT_CODE+report['blob_length'])
            d=json.loads((OUT/(report['variant']+'-decoded.json')).read_text())
            self.assertTrue(d['thumb']);self.assertEqual(d['unresolved_relocations'],0)
            starts={int(i['address'],16) for i in d['instructions']}
            for branch in d['branches']:self.assertIn(int(branch['target'],16),starts)
            for lit in d['literal_references']:
                self.assertTrue(INJECT_CODE<=int(lit['pool'],16)<INJECT_CODE+report['blob_length'])
        with self.assertRaises(ValueError):link(b'not ELF',INJECT_CODE)

    def test_branch_limits_and_roundtrip(self):
        rng=random.Random(100)
        for _ in range(500):
            pc=0x10000000;target=pc+4+rng.randrange(-(1<<23),(1<<23))*2
            self.assertEqual(decode_branch(encode_branch(pc,target),pc),target)
        for pc,target in [(0x20dd10,INJECT_CODE),(0x1000,0x1001),(0x1001,0x1000)]:
            with self.assertRaises(ValueError):encode_branch(pc,target)

    def test_injected_branch_into_literal_data_rejected(self):
        report=self.eq_report
        blob=bytearray((OUT/'eq-test-extension.bin').read_bytes())
        d=json.loads((OUT/'eq-test-decoded.json').read_text())
        call=next(i for i in d['instructions'] if i['mnemonic']=='bl')
        pc=int(call['address'],16);pool=int(d['literal_data_ranges'][0][0],16)
        blob[pc-INJECT_CODE:pc-INJECT_CODE+4]=encode_branch(pc,pool)
        with self.assertRaises(ValueError):validate_blob(bytes(blob),report['link'])

    def test_caps_full_stock_setup_response_no_dsp_write(self):
        for variant,flags in [('caps-only',0),('eq-test',0)]:
            m=Machine(variant);r=m.setup()
            self.assertEqual((r['result'],r['state'],r['length']),(1,4,12))
            raw=bytes.fromhex(r['payload'])
            self.assertEqual(raw,struct.pack('<4sHHI',b'EOIC',1,8,flags))
            self.assertEqual(decode_caps(raw,flags)['bands'],8)
            self.assertEqual(m.writes,[]);self.assertEqual(m.eq_args,[])
            self.assertIn('0x20dd10',m.calls)

    def test_guard_trace_variant_reports_busy_guard_at_branch_time(self):
        image=(OUT/'eq-diagnostic-guards.bin').read_bytes()
        report=json.loads((OUT/'eq-diagnostic-guards-report.json').read_text())
        self.assertEqual(hashlib.sha256(image).hexdigest(),report['output_sha256'])
        self.assertEqual(report['caps'],'454f49430100080003000000')
        m=Machine('eq-diagnostic-guards')
        self.assertEqual(bytes.fromhex(m.setup()['payload']),bytes.fromhex(report['caps']))
        m.activate_audio()
        m.uc.mem_write(0x200162b4,b'\x01')
        m.setup(bm=0x40,request=0xe1,length=4)
        self.assertEqual(m.vendor(struct.pack('<f',-6.0)),1)
        self.assertEqual(m.eq_args,[])
        # E2 returns the captured branch-time events; bit pairs 14/15 are
        # evaluated/pass for codec_update_not_busy. Later guards stay unset.
        self.assertEqual(m.vendor(b'',bm=0xc0,request=0xe2,length=32),0)
        args=bytes(m.uc.mem_read(ARGS,12))
        ptr=struct.unpack_from('<I',args,4)[0]
        n=struct.unpack_from('<H',args,8)[0]
        response=bytes(m.uc.mem_read(ptr,n))
        events=struct.unpack_from('<I',response,12)[0]
        self.assertTrue(events & (1<<14))
        self.assertFalse(events & (1<<15))
        self.assertFalse(events & sum(1<<bit for bit in range(16,22)))
        self.assertFalse(events & (1<<4))

    def test_caps_through_core_setup_dma_response(self):
        m=Machine('caps-only');r=m.core_setup()
        self.assertEqual((r['state'],r['length']),(4,12))
        self.assertEqual(decode_caps(bytes.fromhex(r['dma_payload']))['flags'],0)
        self.assertTrue(any(x['address']=='0x40180914' and x['value']=='0x2001abf4' for x in m.writes))
        self.assertFalse(any(0x40300000<=int(x['address'],16)<0x40310000 for x in m.writes))

    def test_setup_guard_rejects_before_stock_receive(self):
        cases=[dict(length=0),dict(length=11),dict(length=13),dict(length=65535),
               dict(value=0),dict(index=0),dict(bm=0x40),dict(bm=0xc1)]
        for case in cases:
            m=Machine();r=m.setup(**case)
            self.assertEqual((r['result'],r['state']),(0,0))
            self.assertNotIn('0x20dd10',m.calls)
        for length in [0,3,5,241,65535]:
            m=Machine();r=m.setup(bm=0x40,request=0xe1,length=length)
            self.assertEqual(r['result'],0);self.assertNotIn('0x20dd10',m.calls)

    def test_caps_only_rejects_mutation_at_setup(self):
        m=Machine('caps-only')
        self.assertEqual(m.setup(bm=0x40,request=0xe1,length=4)['result'],0)
        m.activate_audio();self.assertEqual(m.vendor(struct.pack('<f',-1)),1)
        self.assertEqual(m.eq_args,[])

    def test_bad_gain_lengths_and_floats_do_not_call_eq(self):
        cases=[b'',b'\0',b'\0'*3,b'\0'*5,b'\0'*140]
        cases += [struct.pack('<f',g) for g in [float('nan'),float('inf'),float('-inf'),1,-13]]
        for payload in cases:
            m=Machine();m.activate_audio();self.assertEqual(m.vendor(payload,length=4),1)
            self.assertEqual(m.eq_args,[]);self.assertEqual(m.writes,[])

    def test_audio_state_and_topology_guards(self):
        m=Machine();self.assertEqual(m.vendor(struct.pack('<f',-1)),1)
        for address,data in [(0x200162cd,b'\0'),(0x200162b8,struct.pack('<I',0)),
                             (0x200162b4,b'\1'),(0x200162c8,struct.pack('<I',16000)),
                             (0x20015bf4,struct.pack('<I',9))]:
            m=Machine();m.activate_audio();m.uc.mem_write(address,data)
            self.assertEqual(m.vendor(struct.pack('<f',-1)),1)
            self.assertEqual(m.eq_args,[])

    def test_eq_validator_frequencies_q_count_and_nonfinite(self):
        report=self.eq_report;entry=int(report['link']['symbols']['eoic_valid_eq']['address'],16)
        original=bytes(ram_image(self.raw)[0x15bec:0x15c78])
        m=Machine();m.uc.mem_write(PAYLOAD,original)
        self.assertEqual(m.call(entry,PAYLOAD,48000),1)
        for off,data in [(8,struct.pack('<I',9)),(8,struct.pack('<I',0)),
                         (12,struct.pack('<I',5)),(16,struct.pack('<f',float('nan'))),
                         (20,struct.pack('<f',0)),(20,struct.pack('<f',24000)),
                         (20,struct.pack('<f',float('inf'))),(24,struct.pack('<f',0)),
                         (24,struct.pack('<f',17)),(24,struct.pack('<f',float('nan')))]:
            bad=bytearray(original);bad[off:off+4]=data;m.uc.mem_write(PAYLOAD,bytes(bad))
            self.assertEqual(m.call(entry,PAYLOAD,48000),0)

    def test_full_out_setup_receive_eq_call_abi(self):
        m=Machine();m.activate_audio()
        r=m.setup(bm=0x40,request=0xe1,length=4)
        self.assertEqual((r['result'],r['state'],r['length']),(1,3,4))
        r=m.receive(struct.pack('<f',-1))
        self.assertEqual(r,dict(result=1,state=6))
        self.assertEqual(m.calls[-3:],['0x20a938','0x20a178','0x20a424'])
        a=m.eq_args[-1];self.assertEqual((a['r0'],a['r2']),(0,2))
        cfg=bytes.fromhex(a['cfg']);self.assertEqual(struct.unpack_from('<ffI',cfg),(-1,-1,2))
        original=ram_image(self.raw)[0x15bec:0x15c78]
        self.assertEqual(cfg[8:],original[8:])
        self.assertGreater(len(m.writes),0)

    def test_four_byte_vendor_out_reaches_ep0_status_accept_path(self):
        # Exercise setup callback -> stock OUT buffer setup -> received payload
        # -> stock UAUD data callback -> custom handler using registered buffer.
        m=Machine();m.activate_audio()
        payload=bytes.fromhex('00 00 c0 c0')
        setup=m.setup(bm=0x40,request=0xe1,value=0x454f,index=0x4943,length=4)
        self.assertEqual((setup['result'],setup['state'],setup['length']),(1,3,4))
        self.assertEqual(setup['pointer'],PAYLOAD)
        self.assertEqual(m.receive(payload,pointer=setup['pointer']),dict(result=1,state=6))
        self.assertEqual(len(m.eq_args),1)
        self.assertEqual(m.eq_args[0]['r2'],2)
        self.assertIn('0x20a938',m.calls)

    def test_four_byte_vendor_out_idle_state_takes_rejection_path(self):
        # Audio enumeration alone does not establish the EQ-live guards.
        m=Machine()
        setup=m.setup(bm=0x40,request=0xe1,value=0x454f,index=0x4943,length=4)
        self.assertEqual((setup['result'],setup['state'],setup['length']),(1,3,4))
        result=m.receive(bytes.fromhex('00 00 c0 c0'),pointer=setup['pointer'])
        self.assertEqual(result,dict(result=0,state=3))
        self.assertEqual(m.eq_args,[])
        self.assertNotIn('0x20a938',m.calls)

    def test_stock_vendor_out_uses_same_success_status_convention(self):
        m=Machine();payload=b'CHECK'
        setup=m.setup(bm=0x40,request=6,value=0,index=0,length=len(payload))
        self.assertEqual((setup['result'],setup['state'],setup['length']),(1,3,len(payload)))
        result=m.receive(payload,pointer=setup['pointer'])
        self.assertEqual(result,dict(result=1,state=6))
        self.assertEqual(m.uc.mem_read(0x200197f0,1),b'\x06')
        self.assertNotIn('0x20a938',m.calls)

    def test_coefficient_gain_change_and_restore(self):
        m=Machine();m.activate_audio()
        m.call(0x0020a939,0,0x20015bec,2)  # existing compiled boot EQ initialization
        before=bytes(m.uc.mem_read(0x20015fa4,0x188))
        # Initial topology setup can leave an update pending for the codec IRQ.
        # Model its completion before the next command; no real IRQ is emulated.
        m.uc.mem_write(0x200162b4,b'\0')
        m.writes.clear();self.assertEqual(m.vendor(struct.pack('<f',-1)),0)
        after=bytes(m.uc.mem_read(0x20015fa4,0x188))
        self.assertNotEqual(before,after)
        # First feedforward coefficient contains the common global-gain factor;
        # denominator terms and later band sections remain unchanged.
        for off in [4,8,12]:
            a=struct.unpack_from('<i',before,off)[0];b=struct.unpack_from('<i',after,off)[0]
            self.assertAlmostEqual(b/a,10**(-1/20),places=5)
        self.assertEqual(before[16:0xc4],after[16:0xc4])
        self.assertTrue(any(0x40302000<=int(x['address'],16)<0x40302400 for x in m.writes))
        m.uc.mem_write(0x200162b4,b'\0')
        self.assertEqual(m.vendor(struct.pack('<f',0)),0)
        self.assertEqual(bytes(m.uc.mem_read(0x20015fa4,0x188)),before)

    def test_ack_timeout_first_wait_is_bounded_and_rolls_back(self):
        m=Machine(ack_mode='stuck-low');m.activate_audio()
        m.call(0x0020a939,0,0x20015bec,2)
        m.uc.mem_write(0x200162b4,b'\0')
        m.uc.mem_write(0x200162bc,b'\0')
        m.uc.mem_write(0x403000e0,struct.pack('<I',0))
        previously_active=bytes(m.uc.mem_read(0x40302000,0xa0))
        setup=m.setup(bm=0x40,request=0xe1,length=4)
        self.assertEqual((setup['result'],setup['state']),(1,3))
        response=m.receive(struct.pack('<f',-1))
        self.assertEqual(response,dict(result=0,state=3))
        self.assertGreaterEqual(m.ack_reads,65535)
        self.assertLess(m.count,400000)
        self.assertEqual(m.uc.mem_read(0x200162bc,1),b'\0')
        self.assertEqual(m.uc.mem_read(0x200162b4,1),b'\0')
        self.assertEqual(bytes(m.uc.mem_read(0x40302000,0xa0)),previously_active)
        control=struct.unpack('<I',m.uc.mem_read(0x403000e0,4))[0]
        self.assertEqual((control>>22)&1,(control>>24)&1)

    def test_ack_timeout_second_wait_is_bounded_and_rolls_back(self):
        m=Machine(ack_mode='stuck-high');m.activate_audio()
        m.call(0x0020a939,0,0x20015bec,2)
        m.uc.mem_write(0x200162b4,b'\0')
        m.uc.mem_write(0x200162bc,b'\1')
        m.uc.mem_write(0x403000e0,struct.pack('<I',(1<<22)|(1<<24)))
        previously_active=bytes(m.uc.mem_read(0x40302200,0xa0))
        setup=m.setup(bm=0x40,request=0xe1,length=4)
        self.assertEqual((setup['result'],setup['state']),(1,3))
        response=m.receive(struct.pack('<f',-1))
        self.assertEqual(response,dict(result=0,state=3))
        self.assertGreaterEqual(m.ack_reads,65535)
        self.assertLess(m.count,400000)
        self.assertEqual(m.uc.mem_read(0x200162bc,1),b'\1')
        self.assertEqual(m.uc.mem_read(0x200162b4,1),b'\0')
        self.assertEqual(bytes(m.uc.mem_read(0x40302200,0xa0)),previously_active)
        control=struct.unpack('<I',m.uc.mem_read(0x403000e0,4))[0]
        self.assertEqual((control>>22)&1,(control>>24)&1)

    def test_all_legacy_commands_classify_through_original_dispatcher(self):
        commands=['QUERY_SW_VER','QUERY_SN','SYS_REBOOT','SYS_SHUTDOWN','PING_THROUGH_VENDOR','CHECK','FW_UPDATE']
        for number,command in enumerate(commands,1):
            m=Machine();self.assertEqual(m.vendor(command.encode(),bm=0x40,request=6,value=0,index=0),0)
            self.assertEqual(m.uc.mem_read(0x200197f0,1)[0],number)
            self.assertIn('0x20d998',m.calls)
            self.assertEqual(m.writes,[])  # only classifier, not action phase

    def test_caps_preserves_pending_legacy_check_response(self):
        m=Machine();m.vendor(b'CHECK',bm=0x40,request=6,value=0,index=0)
        self.assertEqual(m.setup()['result'],1)
        self.assertEqual(m.uc.mem_read(0x200197f0,1)[0],6)
        response=m.setup(bm=0xc0,request=12,value=0,index=0,length=3)
        self.assertEqual(bytes.fromhex(response['payload']),b'1.1')

    def test_probe_rejects_bad_caps(self):
        for p in [b'',b'EOIC',struct.pack('<4sHHI',b'EOIC',2,8,0),struct.pack('<4sHHI',b'EOIC',1,9,0)]:
            with self.assertRaises(ValueError):decode_caps(p)


if __name__=='__main__':unittest.main()

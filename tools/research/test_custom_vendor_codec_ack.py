import hashlib, json, struct, sys, unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools/research'))
sys.path.insert(0,str(ROOT/'research/cache/custom-vendor/deps'))
from custom_vendor_codec_ack_patch import (BASE_SHA,OFFICIAL_SHA,HOOKS,build,
    absolute_pc_veneer,source_offset)
from eoic_scheduler_telemetry_probe import decode_e4,decode_e5
from capstone import Cs,CS_ARCH_ARM,CS_MODE_THUMB,CS_MODE_MCLASS,CS_MODE_LITTLE_ENDIAN

class CodecAckDiagnosticTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base=(ROOT/'research/cache/custom-vendor/scheduler-telemetry.bin').read_bytes()
        cls.image,cls.report=build(cls.base)
        cls.cs=Cs(CS_ARCH_ARM,CS_MODE_THUMB|CS_MODE_MCLASS|CS_MODE_LITTLE_ENDIAN)
        cls.cs.detail=True

    def test_base_hash_and_output_are_deterministic(self):
        self.assertEqual(hashlib.sha256(self.base).hexdigest(),BASE_SHA)
        image,report=build(self.base)
        self.assertEqual(image,self.image)
        self.assertEqual(report['output_sha256'],hashlib.sha256(self.image).hexdigest())
        self.assertEqual(report['official_b_sha256'],OFFICIAL_SHA)

    def test_e4_abi_and_bit_decode(self):
        raw=struct.pack('<IHH9I8B',0x4b434145,1,52,*range(1,9),
                        0x01000000,2,1,0,1,5,0,0,0)
        decoded=decode_e4(raw)
        self.assertEqual(decoded['magic'],'EACK')
        self.assertEqual(decoded['transaction_entry'],1)
        self.assertEqual(decoded['ack_high'],3)
        self.assertEqual(decoded['register_snapshot'],'0x01000000')
        self.assertEqual(decoded['request_bit'],0)
        self.assertEqual(decoded['ack_bit'],1)
        self.assertEqual(decoded['software_busy'],1)
        self.assertEqual(decoded['last_result'],'success')
        with self.assertRaises(ValueError): decode_e4(raw[:-1])
        req=self.report['requests']['GET_CODEC_ACK_DIAGNOSTIC']
        self.assertEqual((req['bmRequestType'],req['bRequest'],req['wValue'],req['wIndex'],req['wLength']),
                         ('0xc0','0xe4','0x454f','0x4943',52))
        self.assertEqual(self.report['requests']['GET_EOIC_CAPS']['expected'],
                         '454f49430100080004000000')
        self.assertEqual(self.report['requests']['GET_SCHEDULER_TELEMETRY']['wLength'],52)

    def test_e5_checkpoint_abi_and_decode(self):
        reg=(1<<22)|(1<<24)|0x88
        raw=struct.pack('<IHH6B7B3xI',0x47525045,1,28,
            1,2,3,4,5,6, 4,7,7,1,2,1,1, reg)
        decoded=decode_e5(raw)
        self.assertEqual(decoded['magic'],'EPRG')
        self.assertEqual(decoded['checkpoint_counts']['configuration_changed_edge'],2)
        self.assertEqual(decoded['last_checkpoint'],'before_main_register_request')
        self.assertTrue(decoded['busy_branch_taken'])
        self.assertTrue(decoded['configuration_equal_path'])
        self.assertTrue(decoded['alternate_request_clear_seen'])
        self.assertEqual(decoded['coefficient_copy_progress'],7)
        self.assertEqual(decoded['register_snapshot'],f'0x{reg:08x}')
        with self.assertRaises(ValueError): decode_e5(raw[:-1])
        req=self.report['requests']['GET_CODEC_PROGRESS']
        self.assertEqual((req['bmRequestType'],req['bRequest'],req['wLength']),('0xc0','0xe5',28))
        self.assertEqual(self.report['telemetry_state']['progress_state_address'],'0x200198e9')
        self.assertEqual(self.report['telemetry_state']['total_reserved'],240)

    def test_hook_veneers_preserve_registers_and_target_thumb_stubs(self):
        for hook in self.report['hooks']:
            off=int(hook['file_offset'],16); site=int(hook['address'],16)
            actual=self.image[off:off+hook['size']]
            decoded=list(self.cs.disasm(actual[:4],site))
            self.assertEqual(len(decoded),1)
            self.assertTrue(decoded[0].mnemonic.startswith('ldr'))
            self.assertIn('pc',decoded[0].op_str)
            imm=decoded[0].operands[1].mem.disp
            literal=((site+4)&~3)+imm
            target=struct.unpack_from('<I',actual,literal-site)[0]
            self.assertEqual(target,int(hook['target'],16))
            self.assertTrue(target&1)

    def test_exact_hook_preimages_sizes_and_replayed_stock_operations(self):
        for addr,(symbol,prehex) in HOOKS.items():
            hook=next(x for x in self.report['hooks'] if int(x['address'],16)==addr)
            self.assertEqual(hook['before'],prehex)
            self.assertEqual(hook['size'],len(bytes.fromhex(prehex)))
            self.assertTrue(hook['symbol'].startswith('eoic_hook_'))
        asm=(ROOT/'tools/research/custom_vendor_codec_ack.S').read_text()
        for token in ['strb r0, [r3]','str r2, [r3]','bpl 1b','bmi 1b',
                      'bfi r1, r3, #28, #1','bfi r1, r3, #29, #1',
                      'stmdb sp!, {r0-r12,lr}','ldmia sp!, {r0-r12,lr}',
                      'msr APSR_nzcvqg, r0']:
            self.assertIn(token,asm)
        self.assertEqual(self.report['validation']['unresolved_relocations'],0)
        self.assertTrue(self.report['validation']['thumb'])
        self.assertEqual(self.report['validation']['instrumentation_additional_codec_mmio_writes'],0)
        self.assertEqual(self.report['validation']['instrumentation_additional_busy_writes'],0)
        self.assertTrue(self.report['validation']['stock_operations_replayed_from_verified_preimages'])
        self.assertCountEqual(self.report['validation']['verified_original_continuations'],
            ['0x20a435','0x20a437','0x20a437','0x20a46d','0x20a481','0x20a585',
             '0x20a6dd','0x20a771','0x20a771','0x20a781'])

    def test_no_new_setter_or_busy_or_codec_register_write(self):
        c=(ROOT/'tools/research/custom_vendor_codec_ack.c').read_text()
        self.assertNotIn('0x0020a424',c)
        self.assertNotIn('0x0020a938',c)
        self.assertNotIn('*(volatile u8 *)BUSY_BYTE=',c)
        self.assertNotIn('*(volatile u32 *)CODEC_REG=',c)
        self.assertTrue(self.report['validation']['no_setter_calls'])
        self.assertEqual(self.report['telemetry_state']['total_reserved'],240)
        self.assertEqual(self.report['requests']['GET_EOIC_CAPS']['wLength'],12)
        self.assertEqual(self.report['requests']['GET_SCHEDULER_TELEMETRY']['wLength'],52)
        self.assertEqual(self.report['requests']['GET_CODEC_ACK_DIAGNOSTIC']['wLength'],52)

if __name__=='__main__': unittest.main(verbosity=2)

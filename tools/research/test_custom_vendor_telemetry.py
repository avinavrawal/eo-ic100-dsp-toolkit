import hashlib, json, struct, unittest
from custom_vendor_patch import ROOT,SOURCE_SHA,build as build_caps
from custom_vendor_telemetry_patch import build,source_offset,APP_LOOP,QUEUE_PUSH,EVENT_SET,EVENT_CLEAR
from eoic_scheduler_telemetry_probe import decode,CAPS
from scheduler_telemetry_model import Ring,Telemetry,U32_MAX

class SchedulerTelemetryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw=(ROOT/'firmware/private/stock_b.bin').read_bytes()
        build_caps(cls.raw,False,False,'caps-only')
        cls.image,cls.report=build(cls.raw)

    def test_image_is_hash_locked_deterministic_and_exactly_patched(self):
        image,report=build(self.raw)
        self.assertEqual(hashlib.sha256(self.raw).hexdigest(),SOURCE_SHA)
        self.assertEqual(image,self.image);self.assertEqual(report['output_sha256'],self.report['output_sha256'])
        self.assertEqual(report['changed_ranges'],[
            ['0xd04c','0xd054'],['0xd090','0xd098'],['0x1335a','0x13364'],
            ['0x15e24','0x15e2c'],['0x1d384','0x1d388'],['0x1d990','0x1d994'],
            ['0x1edc4','0x20004']])
        self.assertEqual(len(image),0x20004)

    def test_hook_sites_and_injected_code_are_thumb_validated(self):
        decoded=json.loads((ROOT/'research/cache/custom-vendor/scheduler-telemetry-decoded.json').read_text())
        self.assertTrue(decoded['thumb']);self.assertEqual(decoded['unresolved_relocations'],0)
        self.assertGreater(len(decoded['instructions']),400)
        self.assertEqual(self.image[source_offset(APP_LOOP,10):source_offset(APP_LOOP,10)+10],
                         bytes.fromhex(self.report['runtime_hooks'][0]['after']))
        for hook in self.report['runtime_hooks'][1:]:
            off=int(hook['file_offset'],16)
            self.assertEqual(self.image[off:off+hook['size']],bytes.fromhex(hook['after']))
        self.assertNotIn('0x21229e',[x['address'] for x in self.report['runtime_hooks']])

    def test_caps_diagnostic_and_e3_wire_response_formats(self):
        self.assertEqual(CAPS,bytes.fromhex('454f49430100080004000000'))
        self.assertEqual(self.report['requests']['GET_SCHEDULER_TELEMETRY']['wLength'],52)
        sample=struct.pack('<IHH10I4B',0x4d544345,1,52,*([1,2,3,4,5,6,7,8,9,10]),11,12,7,0)
        parsed=decode(sample)
        self.assertEqual(parsed['magic'],'ECTM');self.assertEqual(parsed['consumer_calls'],2)
        self.assertEqual(parsed['queue_depth'],11);self.assertTrue(parsed['codec_busy_now'])
        self.assertTrue(parsed['event_bit3_pending_now']);self.assertTrue(parsed['queue_nonempty_now'])
        self.assertEqual(self.report['requests']['GET_EQ_DIAGNOSTIC']['expected'],
                         '4551444701002000000000000000000000000000ffffffff0000000000000000')
        self.assertFalse(self.report['requests']['SET_EQ_TEST']['enabled'])

    def test_counter_saturation_and_phase_sampling(self):
        t=Telemetry()
        for busy in [0,0,1,1,1]:t.loop_sample(busy)
        self.assertEqual((t.app_loops,t.consumer_calls),(5,5))
        self.assertEqual((t.busy_zero_samples,t.busy_nonzero_samples),(2,3))
        t.app_loops=U32_MAX;t.loop_sample(0);self.assertEqual(t.app_loops,U32_MAX)
        t.command_total_ticks=U32_MAX-2;t.record_consumer_ticks(10,15)
        self.assertEqual(t.command_total_ticks,U32_MAX);self.assertEqual(t.command_max_ticks,5)
        self.assertEqual(t.last_tick,15)

    def test_ring_queue_empty_mid_full_wrap_and_full_counter(self):
        t=Telemetry();ring=Ring(capacity=3,read=2,write=2,words=[0,0,0])
        self.assertEqual(t.push(ring,0x11),0);self.assertEqual((ring.write,ring.count,ring.highwater),(0,1,1))
        self.assertEqual(t.push(ring,0x22),0);self.assertEqual((ring.write,ring.count),(1,2))
        self.assertEqual(t.push(ring,0x33),0);self.assertEqual((ring.write,ring.count,ring.highwater),(2,3,3))
        self.assertEqual(t.push(ring,0x44),1);self.assertEqual(t.queue_full,1)
        other=Ring(capacity=0,words=[])
        self.assertEqual(t.push(other,1,ring_address=0x20025000),1);self.assertEqual(t.queue_full,1)
        self.assertEqual(ring.words,[0x22,0x33,0x11])

    def test_event_bit3_set_clear_and_invalid_id(self):
        t=Telemetry();word=0x80
        status,word=t.event_set(3,word);self.assertEqual((status,word),(0,0x88))
        status,word=t.event_clear(3,word);self.assertEqual((status,word),(0,0x80))
        self.assertEqual((t.event_signals,t.event_bit3_clears),(1,1))
        self.assertEqual(t.event_clear(3,word),(0,word));self.assertEqual(t.event_bit3_clears,1)
        self.assertEqual(t.event_set(32,word),(1,word));self.assertEqual(t.event_clear(32,word),(1,word))

    def test_source_has_no_mutation_or_busy_flag_write_path(self):
        source=(ROOT/'tools/research/custom_vendor_telemetry.c').read_text()
        self.assertNotIn('0x0020a939',source);self.assertNotIn('0x0020a938',source)
        self.assertNotIn('0x403000e0',source);self.assertNotIn('0x200162bc',source)
        self.assertNotIn('*(volatile u8 *)BUSY_BYTE =',source)
        self.assertTrue(self.report['safety']['no_eq_setter'])
        self.assertTrue(self.report['safety']['no_busy_flag_write'])
        self.assertTrue(self.report['safety']['no_codec_mmio_write'])
        self.assertTrue(self.report['safety']['no_af_thread_hook'])
        self.assertEqual(self.report['safety']['to'],176)

if __name__=='__main__': unittest.main(verbosity=2)

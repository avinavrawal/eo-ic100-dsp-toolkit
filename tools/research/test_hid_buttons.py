import unittest
import ctypes
import random
import shutil
import subprocess
import tempfile
from pathlib import Path
from hid_buttons import EXPANDED, PulseQueue, action, parse_descriptor


class HIDButtonsTests(unittest.TestCase):
    def test_descriptor_preserves_packet_and_expands_usages(self):
        d = parse_descriptor(EXPANDED)
        self.assertEqual((len(EXPANDED), d['report_id'], d['payload_bits']), (47, 1, 16))
        self.assertEqual([f['usages'][0] for f in d['fields'] if not f['constant']],
                         [0xe9, 0xea, 0xcd, 0xb5, 0xb6, 0xcf])
        self.assertEqual([f['bit'] for f in d['fields'] if not f['constant']], list(range(6)))
        self.assertTrue(all(f['page'] == 12 for f in d['fields']))
        self.assertEqual(d['fields'][-1]['count'], 10)

    def test_all_requested_mappings(self):
        for key, event, mask in [(2,7,4),(2,8,8),(2,9,16),(2,5,32),
                                 (4,7,1),(4,5,8),(8,7,2),(8,5,16)]:
            self.assertEqual(action(key,event), mask)

    def test_no_raw_press_release_or_repeat_action(self):
        for key in [2,4,8,0,0x200,6]:
            for event in [0,1,2,3,4,6,10,12]:
                self.assertIsNone(action(key,event))

    def test_double_does_not_emit_single(self):
        q = PulseQueue()
        for event in [1,2,4,1,3,4,8]: q.event(2,event)
        self.assertEqual(q.submit(), bytes([1,8,0]))
        self.assertIsNone(q.submit())
        q.complete(8)
        self.assertEqual(q.submit(), bytes([1,0,0]))
        q.complete(0)
        self.assertIsNone(q.submit())

    def test_long_release_and_very_long_do_not_add_single(self):
        q = PulseQueue()
        for event in [1,2,5,6,4]: q.event(4,event)
        self.assertEqual(q.pending,[8])

    def test_busy_queue_preserves_repeated_usage_edges(self):
        q = PulseQueue()
        q.event(4,7); q.event(4,7)
        observed=[]
        for mask in [1,0,1,0]:
            observed.append(q.submit())
            self.assertIsNone(q.submit())
            q.complete(mask)
        self.assertEqual(observed,[bytes([1,m,0]) for m in [1,0,1,0]])

    def test_full_queue_drops_whole_action(self):
        q = PulseQueue(capacity=1)
        self.assertTrue(q.event(2,5))
        q.submit()
        self.assertFalse(q.event(2,7))
        q.complete(32)
        self.assertEqual(q.submit(),bytes([1,0,0]))
        q.complete(0)
        self.assertEqual(q.dropped,1)

    def test_submission_rejection_retry_and_mismatched_ack(self):
        q=PulseQueue(); q.event(8,7)
        report=q.submit(); q.not_accepted()
        self.assertEqual(q.submit(),report)
        with self.assertRaises(ValueError): q.complete(1)
        q.complete(2)

    def test_ambiguous_transfer_fault_and_disconnect_reset(self):
        q=PulseQueue(); q.event(2,7); q.submit(); q.complete(4,error=1)
        self.assertIsNone(q.submit())
        self.assertFalse(q.event(2,7))
        q.reset()
        self.assertIsNone(q.submit())
        self.assertTrue(q.event(2,7))

    def test_truncated_descriptor_rejected(self):
        with self.assertRaises(ValueError): parse_descriptor(bytes([0x26,0]))

    @unittest.skipUnless(shutil.which('clang'), 'clang needed for C/reference parity')
    def test_compiled_c_matches_reference_under_backpressure(self):
        class State(ctypes.Structure):
            _fields_ = [('pending',ctypes.c_ubyte*8)] + [
                (name,ctypes.c_ubyte) for name in
                ['head','count','active','phase','inflight','valid','fault','dropped']]
        with tempfile.TemporaryDirectory() as tmp:
            library=Path(tmp)/'queue.so'
            subprocess.run(['clang','-shared','-fPIC','-Os','-Wall','-Wextra','-Werror',
                str(Path(__file__).with_name('hid_button_queue.c')),'-o',str(library)],
                check=True,capture_output=True)
            lib=ctypes.CDLL(str(library))
            state=State(); report=(ctypes.c_ubyte*3)(); q=PulseQueue()
            rng=random.Random(100)
            for _ in range(3000):
                choice=rng.randrange(5)
                if choice == 0:
                    key=rng.choice([2,4,8,0x200]); event=rng.randrange(1,13)
                    self.assertEqual(bool(lib.hid_queue_event(ctypes.byref(state),key,event)),q.event(key,event))
                elif choice == 1:
                    expected=q.submit()
                    actual=lib.hid_queue_submit(ctypes.byref(state),report)
                    self.assertEqual(bool(actual),expected is not None)
                    if actual: self.assertEqual(bytes(report),expected)
                elif choice == 2 and q.inflight is not None:
                    mask=q.inflight; error=int(rng.randrange(40)==0)
                    q.complete(mask,error)
                    self.assertEqual(lib.hid_queue_complete(ctypes.byref(state),mask,error),1)
                elif choice == 3 and q.inflight is not None:
                    q.not_accepted(); lib.hid_queue_not_accepted(ctypes.byref(state))
                elif choice == 4:
                    q.reset(); lib.hid_queue_reset(ctypes.byref(state))
                self.assertEqual(bool(state.fault),q.fault)
                self.assertEqual(bool(state.valid),q.inflight is not None)
                self.assertEqual(state.active,q.active)
                self.assertEqual(state.count,len(q.pending))


if __name__ == '__main__':
    unittest.main()

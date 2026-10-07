import struct
import unittest
from runtime_eq_audit import eq_config, classify_payload
from thumb_index import index


class OfflineParserTests(unittest.TestCase):
    def test_eq_roundtrip(self):
        raw=struct.pack('<ffIIfff',0.0,-1.0,1,1,-2.0,220.0,0.6)
        parsed=eq_config(raw,0)
        self.assertEqual(parsed['gain_r_db'],-1.0)
        self.assertEqual(parsed['filters'][0]['frequency_hz'],220.0)

    def test_reject_truncation_and_invalid_count(self):
        for raw in [b'\0'*11,struct.pack('<ffI',0,0,9),struct.pack('<ffI',0,0,1)]:
            with self.assertRaises(ValueError): eq_config(raw,0)

    def test_reject_nonfinite_and_invalid_parameters(self):
        raw=struct.pack('<ffIIfff',0,0,1,1,float('nan'),220,0.6)
        with self.assertRaises(ValueError): eq_config(raw,0)

    def test_command_prefix_is_not_eq_payload(self):
        commands=['QUERY_SW_VER','CHECK']
        self.assertEqual(classify_payload(b'CHECKanything',commands)['trailing_bytes'],8)
        self.assertIsNone(classify_payload(b'SET_EQ',commands)['command'])

    def test_thumb_call_and_tail_branch(self):
        # bl +0 / b.w +0 point to PC+4, validated ARM Thumb encodings.
        for raw,kind in [(bytes.fromhex('00 f0 00 f8'),'calls'),(bytes.fromhex('00 f0 00 b8'),'branches')]:
            self.assertEqual(index(raw,0x20000000)[kind][0]['target'],0x20000004)


if __name__=='__main__': unittest.main()

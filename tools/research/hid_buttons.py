#!/usr/bin/env python3
"""Offline HID descriptor audit and reference gesture/ACK model. No USB access."""
import hashlib
import json
import struct
from pathlib import Path
from runtime_eq_map import ROOT, PROFILES

# Authored HID short items, not firmware code. Preserve ID and total report size.
EXPANDED = bytes.fromhex(
    '05 0c 09 01 a1 01 85 01 15 00 25 01 75 01 95 01 05 0c '
    '09 e9 81 02 09 ea 81 02 09 cd 81 02 09 b5 81 02 '
    '09 b6 81 02 09 cf 81 02 95 0a 81 01 c0')
LAYOUTS = {
    'original004': dict(descriptor=0x16098, mapper=0xe338, mapper_end=0xe3b8,
                        callback=0xbb84, timer=0x47f4, adc=0x4748,
                        setter=0x10218, sender=0xed0c, cfg=0x15488),
    'official023': dict(descriptor=0x1506c, mapper=0xd174, mapper_end=0xd1c8,
                        callback=0xa9cc, timer=0x434c, adc=0x429c,
                        setter=0xef58, sender=0xdb20, cfg=0x14a80),
}


def parse_descriptor(data):
    """Decode the short-item subset in these Consumer Control descriptors."""
    page = size = count = report_id = bit = 0
    usages, fields = [], []
    i = 0
    while i < len(data):
        prefix = data[i]
        i += 1
        if prefix == 0xfe:
            raise ValueError('long items unsupported')
        length = (0, 1, 2, 4)[prefix & 3]
        if i + length > len(data):
            raise ValueError('truncated item')
        value = int.from_bytes(data[i:i+length], 'little')
        i += length
        kind, tag = (prefix >> 2) & 3, prefix >> 4
        if kind == 1:
            if tag == 0: page = value
            elif tag == 7: size = value
            elif tag == 8: report_id = value
            elif tag == 9: count = value
        elif kind == 2 and tag == 0:
            usages.append(value)
        elif kind == 0:
            if tag == 8:
                fields.append(dict(bit=bit, size=size, count=count,
                                   constant=bool(value & 1), page=page,
                                   usages=usages[:]))
                bit += size * count
            usages = []
    return dict(report_id=report_id, payload_bits=bit, fields=fields)


def action(key, event):
    # Event 5: first long threshold; 7/8/9: settled 1/2/3 clicks.
    return {
        (2, 7): 4, (2, 8): 8, (2, 9): 16, (2, 5): 32,
        (4, 7): 1, (4, 5): 8, (8, 7): 2, (8, 5): 16,
    }.get((key, event))


class PulseQueue:
    """Reference contract: report submissions advance only on matching ACKs.

    Firmware glue must serialize callbacks, defer USB work out of interrupts,
    handle submission failures and reset on disconnect. This is not that glue.
    """
    def __init__(self, capacity=8):
        self.capacity = capacity
        self.reset()

    def reset(self):
        self.pending = []
        self.inflight = None
        self.phase = 'idle'
        self.active = 0
        self.fault = False
        self.dropped = 0

    def event(self, key, event):
        mask = action(key, event)
        if mask is None or self.fault:
            return False
        if len(self.pending) + bool(self.active) >= self.capacity:
            self.dropped += 1  # Drop whole action, never its release.
            return False
        self.pending.append(mask)
        return True

    def submit(self):
        if self.fault or self.inflight is not None:
            return None
        if self.phase == 'idle':
            if not self.pending:
                return None
            self.active = self.pending.pop(0)
            self.phase = 'press'
        mask = self.active if self.phase == 'press' else 0
        self.inflight = mask
        return bytes((1, mask & 255, mask >> 8))

    def not_accepted(self):
        # Busy/submission rejection is not a completed USB transfer.
        self.inflight = None

    def complete(self, mask, error=0):
        if self.inflight is None or mask != self.inflight:
            raise ValueError('unexpected completion')
        self.inflight = None
        if error:
            # Delivery is ambiguous: no blind replay of an action. Reset/release
            # policy belongs to the adapter; do not advance pending actions.
            self.fault = True
            return
        if self.phase == 'press':
            self.phase = 'release'
        else:
            self.phase = 'idle'
            self.active = 0


def file_offset(profile, offset):
    for start, end, address in profile['segments']:
        destination = address - 0x20000000
        if destination <= offset < destination + end - start:
            return start + offset - destination
    raise ValueError('outside initialized mappings')


def audit():
    out = ROOT / 'research/cache/hid-buttons'
    out.mkdir(parents=True, exist_ok=True)
    reports = {}
    for name, profile in PROFILES.items():
        raw = (ROOT / 'firmware/private' / profile['file']).read_bytes()
        sha = hashlib.sha256(raw).hexdigest()
        if sha != profile['sha256']:
            raise ValueError('unexpected source hash: ' + name)
        ram = bytearray(0x20000)
        for start, end, destination in profile['segments']:
            off = destination - 0x20000000
            ram[off:off+end-start] = raw[start:end]
        layout = LAYOUTS[name]
        descriptor = bytes(ram[layout['descriptor']:layout['descriptor']+47])
        decoded = parse_descriptor(descriptor)
        if decoded['payload_bits'] != 16 or decoded['report_id'] != 1:
            raise ValueError('unexpected HID layout')
        reports[name] = dict(source_sha256=sha, layout=layout,
            file_offsets={k:file_offset(profile, layout[k]) for k in ('descriptor','mapper')},
            descriptor=decoded, proposed_descriptor=parse_descriptor(EXPANDED),
            completion_callback=hex(struct.unpack_from('<I', ram, layout['cfg']+0x28)[0]),
            mapper_bytes=layout['mapper_end']-layout['mapper'],
            classification='Static audit; patch strategy only, no image generated')
    # Slot B must be audited independently: XIP pointers differ from slot A.
    b = (ROOT / 'firmware/private/stock_b.bin').read_bytes()
    if hashlib.sha256(b).hexdigest() != '2f418d3a324ec4217c32c4bf98d43c3cd07d59d81f82974f29320d399fa769f3':
        raise ValueError('unexpected slot-B source hash')
    a = (ROOT / 'firmware/private/stock_a.bin').read_bytes()
    checks = {}
    for key, length in [('descriptor',47), ('mapper',84)]:
        off = file_offset(PROFILES['official023'], LAYOUTS['official023'][key])
        checks[key] = dict(offset=hex(off), length=length, identical=a[off:off+length] == b[off:off+length])
        if not checks[key]['identical']:
            raise ValueError('slot-B patch site differs')
    reports['official023_slot_b_patch_sites'] = checks
    (out/'audit.json').write_text(json.dumps(reports, indent=2)+'\n')
    print(json.dumps(dict(report='research/cache/hid-buttons/audit.json',
        descriptor_bytes=len(EXPANDED), report_bytes=3, b_sites=checks), indent=2))


if __name__ == '__main__':
    audit()

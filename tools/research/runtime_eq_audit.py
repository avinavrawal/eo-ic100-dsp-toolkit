#!/usr/bin/env python3
"""Offline parsers and reproducible evidence inventory; never opens USB devices."""
import argparse
import hashlib
import json
import math
import struct
import subprocess
from pathlib import Path
from runtime_eq_map import ROOT, PROFILES
from thumb_index import index

LAYOUTS = {
    "original004": {"usb_cfg": 0x15488, "commands": 0x15d90, "eq_list": 0x1718c, "set_eq": 0xda10, "open_eq": 0xda64,
                    "set_cfg": 0xbafc, "get_iir": 0xb360, "set_iir": 0xb5fc, "vendor": 0xeb8c,
                    "slices": [(0xda10, 0xda50), (0xda64, 0xdbb0), (0xbafc, 0xbb40), (0xb360, 0xb5dc), (0xb5fc, 0xba1c),
                               (0xeb8c, 0xecb0), (0xef30, 0xf2cc), (0xf824, 0xfa80), (0xfc50, 0xfd8c), (0xe214, 0xe2b0), (0xe3b8, 0xe778)]},
    "official023": {"usb_cfg": 0x14a80, "commands": 0x14c0c, "eq_list": 0x15c78, "set_eq": 0xc800, "open_eq": 0xc840,
                    "set_cfg": 0xa938, "get_iir": 0xa178, "set_iir": 0xa424, "vendor": 0xd998,
                    "slices": [(0xc800, 0xc834), (0xc840, 0xc9fc), (0xa938, 0xa988), (0xa178, 0xa410), (0xa424, 0xa864),
                               (0xd998, 0xdac4), (0xdd10, 0xe0f0), (0xe5fc, 0xe784), (0xcfb0, 0xd120), (0xd1c8, 0xd480)]},
}


def eq_config(data, offset):
    if offset < 0 or offset + 12 > len(data):
        raise ValueError("truncated EQ header")
    left, right, count = struct.unpack_from('<ffI', data, offset)
    if count > 8 or offset + 12 + count*16 > len(data):
        raise ValueError("invalid filter count or truncated EQ records")
    records = []
    for i in range(count):
        kind, gain, frequency, q = struct.unpack_from('<Ifff', data, offset+12+16*i)
        if kind > 4 or not all(math.isfinite(v) for v in (gain, frequency, q)) or frequency <= 0 or q <= 0:
            raise ValueError("invalid EQ record")
        records.append({'type': kind, 'gain_db': gain, 'frequency_hz': frequency, 'q': q})
    if not all(math.isfinite(v) for v in (left, right)):
        raise ValueError("invalid global gain")
    return {'gain_l_db': left, 'gain_r_db': right, 'count': count, 'filters': records}


def cstring(data, address):
    offset = address-0x20000000
    if not 0 <= offset < len(data):
        raise ValueError("pointer outside reconstructed RAM")
    end = data.find(b'\0', offset)
    if end < 0:
        raise ValueError("unterminated string")
    return data[offset:end].decode('ascii')


def classify_payload(payload, commands):
    # Offline model of prefix comparisons, NOT a transport or safety validator.
    # Firmware can read beyond a short payload; this model does not emulate that.
    for number, command in enumerate(commands, 1):
        if payload.startswith(command.encode()):
            return {'id': number, 'command': command, 'trailing_bytes': len(payload)-len(command),
                    'eq_configuration_command': False}
    return {'command': None, 'eq_configuration_command': False}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--disassemble', action='store_true', help='Cache selected r2 instruction ranges')
    args = p.parse_args()
    for name, layout in LAYOUTS.items():
        profile = PROFILES[name]
        folder = ROOT/'research/cache'/('runtime-eq-'+name+'-'+profile['sha256'][:16])
        image = folder/'initialized-ram.bin'
        data = image.read_bytes()
        idx = index(data, 0x20000000)
        commands = [cstring(data, struct.unpack_from('<I',data,layout['commands']+4*i)[0]) for i in range(7)]
        expected = ['QUERY_SW_VER','QUERY_SN','SYS_REBOOT','SYS_SHUTDOWN','PING_THROUGH_VENDOR','CHECK','FW_UPDATE']
        assert commands == expected
        callback = struct.unpack_from('<I', data, layout['usb_cfg']+0x2c)[0]
        assert callback == 0x00200001+layout['vendor']
        config_address = struct.unpack_from('<I', data, layout['eq_list'])[0]
        config = eq_config(data, config_address-0x20000000)
        functions = {}
        for label in ('set_eq','open_eq','set_cfg','get_iir','set_iir','vendor'):
            address = 0x20000000+layout[label]
            functions[label] = {'data_alias': hex(address), 'code_alias': hex(0x00200000+layout[label]),
                                'candidate_direct_callers': [hex(c['site']) for c in idx['calls'] if c['target']==address],
                                'candidate_tail_branches': [hex(c['site']) for c in idx['branches'] if c['target']==address]}
        result = {'profile': name, 'source_sha256': profile['sha256'], 'initialized_ram_sha256': hashlib.sha256(data).hexdigest(),
                  'usb_config_address': hex(0x20000000+layout['usb_cfg']), 'registered_vendor_callback': hex(callback),
                  'command_table': commands, 'eq_config_address': hex(config_address), 'eq_config': config,
                  'functions': functions, 'limits': 'Candidate linear call indexes require disassembly validation; no claim of exhaustive indirect-call recovery.'}
        report = folder/'audit.json'
        report.write_text(json.dumps(result,indent=2)+'\n')
        if args.disassemble:
            version = subprocess.check_output(['r2','-v'],text=True).strip()
            cmds = 'e scr.color=0;'+';'.join(f'pD {end-start} @ {0x00200000+start:#x}' for start,end in layout['slices'])
            key = hashlib.sha256((version+cmds+result['initialized_ram_sha256']).encode()).hexdigest()[:16]
            output = folder/('selected-disassembly-'+key+'.txt')
            if not output.exists():
                with output.open('w') as out, (folder/('selected-disassembly-'+key+'.stderr')).open('w') as err:
                    subprocess.run(['r2','-q','-a','arm','-b','16','-m','0x00200000','-c',cmds,str(image)],stdout=out,stderr=err,check=True)
        print(name, 'vendor callback',hex(callback),'commands',len(commands),'EQ filters',config['count'],'report',report)


if __name__ == '__main__':
    main()

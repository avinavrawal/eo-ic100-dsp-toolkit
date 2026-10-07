#!/usr/bin/env python3
"""Conservative candidate Thumb literal/call index; data can resemble instructions."""
import argparse
import hashlib
import json
import struct
from pathlib import Path

def index(data, base):
    literals, calls, branches, pushes = [], [], [], []
    for off in range(0, len(data)-3, 2):
        a, b = struct.unpack_from('<HH', data, off)
        pc = base + off
        if a & 0xfe00 == 0xb400 and a & 0x100:
            pushes.append(pc)
        if a == 0xe92d and b & 0x4000:
            pushes.append(pc)
        pool = None
        reg = None
        if a & 0xf800 == 0x4800:
            pool = ((pc+4)&~3) + (a & 255)*4
            reg = (a >> 8)&7
        elif a in (0xf8df, 0xf85f):
            pool = ((pc+4)&~3) + (1 if a==0xf8df else -1)*(b&4095)
            reg = b>>12
        if pool is not None and 0 <= pool-base <= len(data)-4:
            value = struct.unpack_from('<I', data, pool-base)[0]
            literals.append({'site': pc, 'pool': pool, 'value': value, 'register': reg})
        if a & 0xf800 == 0xf000 and b & 0xd000 in (0xd000, 0x9000):
            s = (a>>10)&1
            i1 = 1 ^ ((b>>13)&1) ^ s
            i2 = 1 ^ ((b>>11)&1) ^ s
            displacement = (s<<24)|(i1<<23)|(i2<<22)|((a&1023)<<12)|((b&2047)<<1)
            if s: displacement -= 1<<25
            (calls if b & 0xd000 == 0xd000 else branches).append({'site': pc, 'target': pc+4+displacement})
        if a & 0xf800 == 0xe000:
            displacement = (a & 2047)*2
            if displacement & 2048: displacement -= 4096
            branches.append({'site': pc, 'target': pc+4+displacement})
    return {'base': base, 'sha256': hashlib.sha256(data).hexdigest(), 'literals': literals, 'calls': calls, 'branches': branches, 'push_candidates': pushes,
            'warning': 'Linear candidates include data false positives; validate instruction boundaries and control flow before conclusions.'}

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('input',type=Path)
    p.add_argument('--base',type=lambda s:int(s,0),default=0x20000000)
    p.add_argument('--output',type=Path)
    args=p.parse_args()
    result=index(args.input.read_bytes(),args.base)
    out=args.output or args.input.parent/'thumb-index.json'
    out.write_text(json.dumps(result)+'\n')
    print(out, 'literal candidates',len(result['literals']),'call candidates',len(result['calls']))

if __name__=='__main__': main()

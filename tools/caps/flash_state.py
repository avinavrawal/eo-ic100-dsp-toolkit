#!/usr/bin/env python3
"""Offline, bounded flash-state comparison. No USB operations."""
import argparse
import hashlib
import json
import struct
import zlib
from pathlib import Path

BACKUP_SHA='6ee1089955817ac0deda01aab8eb7531f3bdd11dd1604fd8c143d6d1538eb0cd'
OFFICIAL_SHA='2f418d3a324ec4217c32c4bf98d43c3cd07d59d81f82974f29320d399fa769f3'
DIAMOND_B_SHA='a624d5771bfcefc68c40d77a745fbf82d8a60864f7f9d4bfddf29bdba95c1cc0'
BASELINE_SHA='077317b51d1df4b358603fafc690a92e8bc5a17f116c24d3edf9223c4ae150e2'
def sha(b):return hashlib.sha256(b).hexdigest()
def analyze(current,backup,official):
    if len(current)!=0x80000 or sha(backup)!=BACKUP_SHA or sha(official)!=OFFICIAL_SHA:
        raise ValueError('flash size or authority hashes differ')
    regions={}
    for name,start,end in [('before_flags',0,0x4000),('active_flag',0x4000,0x5000),('backup_flag',0x5000,0x6000),('A',0x6000,0x2e000),('B',0x2e000,0x4e000),('after_B',0x4e000,0x80000)]:
        regions[name]=dict(start=hex(start),end=hex(end),sha256=sha(current[start:end]),equal_backup=current[start:end]==backup[start:end],changed_bytes=sum(a!=b for a,b in zip(current[start:end],backup[start:end])))
    ranges=[];start=None
    for i,(a,b) in enumerate(zip(current,backup)):
        if a!=b and start is None:start=i
        if a==b and start is not None:ranges.append([hex(start),hex(i)]);start=None
    if start is not None:ranges.append([hex(start),hex(len(current))])
    image=current[0x2e000:0x2e000+len(official)-4]
    restored=b'\xff'*4+image[4:]+official[-4:]
    marker=bytes.fromhex('1c ec 57 be');marked=marker+official[4:-4]
    diffs=[i for i,(a,b) in enumerate(zip(image,marked)) if a!=b]
    nv={}
    for name,b in [('original',backup),('current',current)]:
        q=b[0x7d000:0x7e000];nv[name]=dict(crc32_saved=hex(struct.unpack_from('<I',q,4)[0]),crc32_calculated=hex(zlib.crc32(q[8:24])),valid=struct.unpack_from('<I',q,4)[0]==zlib.crc32(q[8:24]))
    return dict(current_sha256=sha(current),backup_sha256=sha(backup),full_match=current==backup,regions=regions,changed_ranges=ranges,
      A_intact=current[0x6000:0x2e000]==backup[0x6000:0x2e000],A_header_valid=current[0x6000:0x6004]==marker and struct.unpack_from('<I',current,0x600c)[0]==0x3c026394,
      B_header_valid=image[:4]==marker and struct.unpack_from('<I',image,12)[0]==0x3c04cc8c,
      B_installed_file_sha256=sha(restored),B_is_known_diamond8=sha(restored)==DIAMOND_B_SHA,B_vs_official_changed_bytes=len(diffs),B_vs_official_only_EQ=all(0x1e4c4<=i<0x1e4c4+140 for i in diffs),
      active_flag=current[0x4000:0x4008].hex(' '),backup_flag=current[0x5000:0x5008].hex(' '),
      active_sector_canonical=current[0x4008:0x5000]==b'\xff'*4088,backup_sector_canonical=current[0x5008:0x6000]==b'\xff'*4088,nv_record_crc=nv)
def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('current',type=Path);p.add_argument('--backup',type=Path,default=Path('firmware/private/flash-backup.bin'));p.add_argument('--official-b',type=Path,default=Path('firmware/private/stock_b.bin'));p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    r=analyze(a.current.read_bytes(),a.backup.read_bytes(),a.official_b.read_bytes());a.output.write_text(json.dumps(r,indent=2)+'\n')
    print(json.dumps({k:r[k] for k in ('current_sha256','full_match','A_intact','B_is_known_diamond8','active_flag','backup_flag')}));print('Full report:',a.output)
if __name__=='__main__':main()

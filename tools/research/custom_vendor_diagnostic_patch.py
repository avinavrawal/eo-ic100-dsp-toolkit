#!/usr/bin/env python3
"""Offline diagnostic overlay; preserves the hash-locked hardened EQ helpers."""
import json
import struct
import subprocess
from pathlib import Path
from arm_elf import link, set_mov_imm, mov_imm
from custom_vendor_patch import (ROOT, OUT, CODE_BASE, INJECT_OFFSET, INJECT_CODE,
    PAYLOAD_LIMIT, build as base_build, sha, changed_ranges, validate_blob,
    full_disassembly, patch_stock_timeout, ram_image)

BASE_SHA='5be2b81385fce7fa86876393b680e5d3b3bbbededf13aa893ab42cccf5c9b26b'
OFFSET=0x1f400
ADDRESS=CODE_BASE+OFFSET
STATUS_OFFSET=0xed12
STATUS_PREIMAGE=bytes.fromhex('124b1d4900202070d3f81428')
RX=0x20019804
STATE=RX+176

def build(raw,guard_trace=False):
    variant='eq-diagnostic-guards' if guard_trace else 'eq-diagnostic'
    base, previous=base_build(raw,True,guard_trace=guard_trace,
        output_variant=('eq-test-guards' if guard_trace else None))
    if not guard_trace and sha(base)!=BASE_SHA: raise ValueError('hardened base hash differs')
    # Reuse the existing hash-keyed Thumb index; do not rescan disassembly.
    xrefs=json.loads((OUT/'thumb-xrefs.json').read_text())
    if xrefs['sha256']!=sha(bytes(ram_image(raw))): raise ValueError('cached xrefs input differs')
    incoming=[x for x in xrefs['branches']+xrefs['calls'] if 0x20641e<x['target']<0x20642a]
    if incoming: raise ValueError('incoming branch into displaced EP0 instructions')
    if struct.unpack_from('<IH',raw,0x1d360)!=(RX,240): raise ValueError('RX registration differs')
    tail_refs=[]
    for off in range(len(raw)-3):
        value=struct.unpack_from('<I',raw,off)[0]
        if STATE<=value<RX+240: tail_refs.append(dict(offset=hex(off),value=hex(value)))
    if tail_refs: raise ValueError('absolute reference into reserved RX tail')
    source=Path(__file__).with_name('custom_vendor_diagnostic.c')
    obj=OUT/(variant+'.o')
    command=['clang','--target=arm-none-eabi','-mcpu=cortex-m4','-mthumb',
        '-mfpu=fpv4-sp-d16','-mfloat-abi=softfp','-ffreestanding','-fno-builtin',
        '-fno-strict-aliasing','-fno-unwind-tables','-fno-asynchronous-unwind-tables',
        '-fno-ident','-Os','-Wall','-Wextra','-Werror',f'-DGUARD_TRACE={int(guard_trace)}',
        '-c',str(source),'-o',str(obj)]
    compiler=subprocess.check_output(['clang','--version'],text=True).splitlines()[0]
    key=sha((compiler+sha(source.read_bytes())+json.dumps(command)).encode())
    identity=OUT/(variant+'.build-key')
    if not obj.exists() or not identity.exists() or identity.read_text()!=key:
        subprocess.run(command,check=True,capture_output=True); identity.write_text(key)
    blob, manifest=link(obj.read_bytes(),ADDRESS)
    decoded=validate_blob(blob,manifest)
    if OFFSET+len(blob)>PAYLOAD_LIMIT: raise ValueError('diagnostic allocation overflow')
    if previous['blob_length']>OFFSET-INJECT_OFFSET: raise ValueError('base overlap')
    def pointer(name):
        p=int(manifest['symbols'][name]['address'],16)
        if not p&1 or not ADDRESS<=p&~1<ADDRESS+len(blob): raise ValueError('bad diagnostic Thumb pointer')
        return p
    image=bytearray(base)
    image[OFFSET:OFFSET+len(blob)]=blob
    hooks={}
    for name,off,old,label in [('setup',0x1d990,0x20dd11,'eoic_diag_setup'),
                             ('vendor',0x1d384,0x20d999,'eoic_diag_vendor'),
                             ('data',0x1d994,0x20e5fd,'eoic_diag_data')]:
        if struct.unpack_from('<I',raw,off)[0]!=old: raise ValueError('callback preimage differs')
        target=pointer(label); struct.pack_into('<I',image,off,target)
        hooks[name]=dict(file_offset=hex(off),old=hex(old),new=hex(target))
    # Redirect only the authored vendor handler's existing setter call to a
    # transparent bookkeeping wrapper. Stock setter and its ABI are unchanged.
    target=pointer('eoic_diag_eq_call')
    setter_pairs=[]
    for relative in range(0,previous['blob_length']-10,2):
        off=INJECT_OFFSET+relative
        a,b=struct.unpack_from('<HH',image,off)
        c,d=struct.unpack_from('<HH',image,off+6)
        if mov_imm(a,b)==0xa939 and mov_imm(c,d)==0x20:
            setter_pairs.append(off)
    if len(setter_pairs)!=1: raise ValueError('expected one stock EQ setter address pair')
    off=setter_pairs[0]
    a,b=struct.unpack_from('<HH',image,off)
    c,d=struct.unpack_from('<HH',image,off+6)
    struct.pack_into('<HH',image,off,*set_mov_imm(a,b,target&0xffff))
    struct.pack_into('<HH',image,off+6,*set_mov_imm(c,d,target>>16))
    # Stock timeout trampolines now call logging wrappers, which call the exact
    # unchanged original finite helpers at their original addresses.
    stock,timeouts=patch_stock_timeout(raw,manifest)
    for a,b in [(0x13042,0x13054),(0x1311c,0x13128)]: image[a:b]=stock[a:b]
    if raw[STATUS_OFFSET:STATUS_OFFSET+12]!=STATUS_PREIMAGE: raise ValueError('EP0 preimage differs')
    status=struct.pack('<HHHIH',0x4b01,0x4798,0xe002,pointer('eoic_diag_status_hook'),0xbf00)
    image[STATUS_OFFSET:STATUS_OFFSET+12]=status
    image=bytes(image)
    # Every delta against hardened firmware must be accounted for.
    allowed=[(0x13042,0x13054),(0x1311c,0x13128),(0x1d384,0x1d388),
        (0x1d990,0x1d998),(STATUS_OFFSET,STATUS_OFFSET+12),
        (off,off+4),(off+6,off+10),
        (OFFSET,OFFSET+len(blob))]
    for a,b in changed_ranges(base,image):
        if not any(s<=a and b<=e for s,e in allowed): raise ValueError('unreviewed overlay delta')
    # Boot EQ, descriptors, metadata and the original bounded helpers unchanged.
    for a,b in [(0x1e4c4,0x1e550),(0x1ec8c,0x1edc4),(0x1f19c,0x1f21c)]:
        if image[a:b]!=base[a:b]: raise ValueError('preserved region changed')
    guard_bits={name:dict(evaluated_bit=10+2*i,passed_bit=11+2*i)
        for i,name in enumerate(['eq_subsystem_enabled','codec_initialized',
            'codec_update_not_busy','supported_sample_rate','stock_eq_configuration_valid',
            'stock_band_count_is_two'])} if guard_trace else None
    report=dict(variant=variant,input_sha256=sha(raw),base_sha256=sha(base),
        output_sha256=sha(image),expected_marked_payload_sha256=sha(b'\x1c\xec\x57\xbe'+image[4:-4]),
        output_length=len(image),payload_length=PAYLOAD_LIMIT,compiler=compiler,
        source_sha256=sha(source.read_bytes()),build_key=key,blob_length=len(blob),
        diagnostic_offset=hex(OFFSET),diagnostic_address=hex(ADDRESS),link=manifest,hooks=hooks,
        changed_ranges=[[hex(a),hex(b)] for a,b in changed_ranges(raw,image)],
        overlay_ranges=[[hex(a),hex(b)] for a,b in changed_ranges(base,image)],
        overlay_bytes=[dict(start=hex(a),end=hex(b),before=base[a:b].hex(),after=image[a:b].hex())
                       for a,b in changed_ranges(base,image)],
        timeout_patch=timeouts,unchanged_ack_helpers=['0xc04d19c-0xc04d21c'],
        status_hook=dict(file_offset=hex(STATUS_OFFSET),ram='0x20641e',
            before=STATUS_PREIMAGE.hex(),after=status.hex(),continuation='0x20642a'),
        storage=dict(buffer=hex(RX),original_capacity=240,receive_capacity=176,
            state=hex(STATE),reply=hex(STATE+32),size_each=32,
            registration_offset='0x1d360',absolute_tail_references=tail_refs,
            ownership_limit='absolute-reference screen cannot exclude computed aliases; owned RX-buffer partition enforced before every OUT receive',
            limit='all OUT setup requests over 176 bytes rejected before receive'),
        caps=('454f49430100080003000000' if guard_trace else '454f49430100080001000000'),
        diagnostic_setup='c0e24f4543492000',guard_trace=guard_bits,
        stock_boot_eq_preserved=True,dsp_setter_behavior_unchanged=True,
        ack_wait_bodies_byte_identical=True,physical_operations=False,
        limitations='Modeled CPU/MMIO; does not prove real USB status timing or audio/DSP response.')
    for suffix,data in [('.bin',image),('-extension.bin',blob)]: (OUT/(variant+suffix)).write_bytes(data)
    (OUT/(variant+'-report.json')).write_text(json.dumps(report,indent=2)+'\n')
    (OUT/(variant+'-decoded.json')).write_text(json.dumps(decoded,indent=2)+'\n')
    (OUT/(variant+'-handler-disassembly.txt')).write_text(full_disassembly(decoded,manifest))
    return image,report

if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser()
    parser.add_argument('--guard-trace',action='store_true')
    args=parser.parse_args()
    image,report=build((ROOT/'firmware/private/stock_b.bin').read_bytes(),args.guard_trace)
    print(json.dumps({k:report[k] for k in ['output_sha256','blob_length','changed_ranges','hooks']},indent=2))

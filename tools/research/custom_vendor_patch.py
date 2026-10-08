#!/usr/bin/env python3
"""Deterministic, hash-locked OFFLINE B-image extension builder. No USB code."""
import argparse
import hashlib
import json
import shutil
import struct
import subprocess
import sys
from pathlib import Path
from arm_elf import link, decode_branch
from runtime_eq_map import ROOT, PROFILES
from thumb_index import index

SOURCE_SHA='2f418d3a324ec4217c32c4bf98d43c3cd07d59d81f82974f29320d399fa769f3'
FLASH_BASE=0x3c02e000
CODE_BASE=0x0c02e000
ORIGINAL_LENGTH=0x1edc8
INJECT_OFFSET=0x1f000
INJECT_CODE=CODE_BASE+INJECT_OFFSET
PAYLOAD_LIMIT=0x20000  # extension uses no sectors beyond existing 4 x 32 KiB envelope
HOOKS={'setup':(0x1d990,0x0020dd11,'eoic_setup'),
       'vendor':(0x1d384,0x0020d999,'eoic_vendor')}
ACK_TIMEOUT_READS=65535
OUT=ROOT/'research/cache/custom-vendor'


def sha(data): return hashlib.sha256(data).hexdigest()


def changed_ranges(a,b):
    result=[]; start=None
    for i in range(max(len(a),len(b))):
        different=i>=len(a) or i>=len(b) or a[i]!=b[i]
        if different and start is None: start=i
        if not different and start is not None:
            result.append((start,i)); start=None
    if start is not None: result.append((start,max(len(a),len(b))))
    return result


def ram_image(raw):
    ram=bytearray(0x28000)
    for start,end,dest in PROFILES['official023']['segments']:
        at=dest-0x20000000; ram[at:at+end-start]=raw[start:end]
    return ram


def metadata(raw):
    if len(raw)!=ORIGINAL_LENGTH or sha(raw)!=SOURCE_SHA:
        raise ValueError('input must be exact official Samsung 0.23 B')
    if struct.unpack_from('<I',raw,len(raw)-4)[0]!=FLASH_BASE:
        raise ValueError('mapped-start footer mismatch')
    if raw[:4]!=b'\xff'*4 or struct.unpack_from('<I',raw,12)[0]!=FLASH_BASE+0x1ec8c:
        raise ValueError('validity placeholder/build metadata pointer mismatch')
    if not raw[0x1ec8c:len(raw)-4].startswith(b'CHIP=best3005\nKERNEL=RTX\nSW_VER=0.23_051101_ab\n'):
        raise ValueError('build metadata mismatch')
    for off,old,_ in HOOKS.values():
        if struct.unpack_from('<I',raw,off)[0]!=old: raise ValueError('hook preimage mismatch')


def ownership(raw):
    """Append allocation, not a zero/FF cave. Strict candidate reference screen.

    Absolute references are a bounded negative finding, not proof of absence of
    computed accesses. The existing initialized/XIP regions stay byte-identical.
    The extension owns newly added bytes after the build metadata and before the
    relocated host-only footer, within the established sector envelope.
    """
    refs=[]
    for off in range(len(raw)-3):
        value=struct.unpack_from('<I',raw,off)[0]
        if any(base+INJECT_OFFSET<=value<base+PAYLOAD_LIMIT for base in [FLASH_BASE,CODE_BASE]):
            refs.append(dict(file_offset=hex(off),value=hex(value)))
    if refs: raise ValueError('existing word points into extension allocation')
    segments=PROFILES['official023']['segments']
    if max(end for _,end,_ in segments)>=INJECT_OFFSET: raise ValueError('startup copy overlap')
    return dict(method='explicit appended allocation; not an existing code cave',
        file_range=[hex(INJECT_OFFSET),hex(PAYLOAD_LIMIT)],
        execution_range=[hex(INJECT_CODE),hex(CODE_BASE+PAYLOAD_LIMIT)],
        existing_absolute_references=refs, initialization_overlap=False,
        original_build_metadata=[hex(0x1ec8c),hex(len(raw)-4)],
        original_payload_bytes_preserved_except_hook_words=True,
        existing_staging_sector_envelope=[hex(FLASH_BASE),hex(FLASH_BASE+PAYLOAD_LIMIT)],
        limits='Computed flash access and physical fetch are not formally proven; see research report. '
               'First device validation must be CAPS-only. Not a deployment authorization.')


def patch_stock_timeout(raw,manifest):
    """Install finite ACK helpers into the hash-locked 0.23 stock call path."""
    image=bytearray(raw)
    preimages={0x13042:bytes.fromhex('1a68d101fcd5384b00221a70'),
               0x1311c:bytes.fromhex('1a68d201fcd491e7bc620120'),
               0x12f86:bytes.fromhex('674f'),0x13238:bytes.fromhex('0020')}
    for off,expected in preimages.items():
        if image[off:off+len(expected)]!=expected:
            raise ValueError('stock timeout patch preimage mismatch at '+hex(off))
    set_ptr=int(manifest['symbols']['eoic_wait_ack_set']['address'],16)
    clear_ptr=int(manifest['symbols']['eoic_wait_ack_clear']['address'],16)
    if not (set_ptr&1 and clear_ptr&1): raise ValueError('timeout helper is not Thumb')
    # 0x20a76a: LDR literal @0x20a778; BLX; branch to shared cleanup.
    # The helper's r3 result distinguishes success (busy-byte pointer) from
    # timeout (zero), so the shared cleanup reaches the existing status-3 exit.
    first=(struct.pack('<HHHHHHH',0x4b03,0x4798,0xe7ff,0xb163,0x2200,
                       0x701a,0xe003)+struct.pack('<I',set_ptr))
    image[0x13042:0x13042+len(first)]=first
    # 0x20a844: call the clear-ACK helper, then enter shared cleanup. Preserve
    # the duplicate 0x200162bc literal at 0x20a8fc by relocating its LDR.
    image[0x12f86:0x12f88]=struct.pack('<H',0x4f93)
    second=struct.pack('<HHHH',0x4b01,0x4798,0xe792,0xbf00)+struct.pack('<I',clear_ptr)
    image[0x1311c:0x1311c+len(second)]=second
    # audio_eq_set_cfg restores enabled state as before, but now preserves the
    # setter's status for the vendor handler instead of forcing success=0.
    image[0x13238:0x1323a]=struct.pack('<H',0xbf00)
    return bytes(image),dict(
        finite_poll_limit=ACK_TIMEOUT_READS,
        polling_unit='reads of codec register 0x403000e0',
        waits=[dict(code_address='0x0020a76a',file_offset='0x13042',
                    helper='eoic_wait_ack_set',expected_ack_bit24=1),
               dict(code_address='0x0020a844',file_offset='0x1311c',
                    helper='eoic_wait_ack_clear',expected_ack_bit24=0)],
        timeout_cleanup=dict(selection='set bit22 equal to last observed bit24',
                             software_bank_selector='unchanged',busy_flag='clear 0x200162b4',
                             setter_status=3,host_result='EP0 request rejection/stall path'),
        success_cleanup=dict(software_bank_selector='toggle 0x200162bc once',
                             busy_flag='stock cleanup at 0x0020a770'),
        status_propagation=dict(code_address='0x0020a960',file_offset='0x13238',
                                patch='movs r0,#0 -> nop'))


def validate_blob(blob,manifest):
    sys.path.insert(0,str(OUT/'deps'))
    from capstone import Cs,CS_ARCH_ARM,CS_MODE_THUMB,CS_MODE_MCLASS,CS_MODE_LITTLE_ENDIAN,CS_GRP_JUMP,CS_GRP_CALL
    cs=Cs(CS_ARCH_ARM,CS_MODE_THUMB|CS_MODE_MCLASS|CS_MODE_LITTLE_ENDIAN); cs.detail=True
    allocation_base=int(manifest.get("base",hex(INJECT_CODE)),16)
    instructions=[]; literals=[]; branches=[]; data_ranges=[]
    for section in manifest['sections']:
        if not section['executable']: continue
        base=int(section['address'],16); at=base-allocation_base; length=section['length']
        markers=sorted((int(x['address'],16),x['kind']) for x in manifest['mapping_symbols'] if x['section']==section['name'])
        markers.append((base+length,'end'))
        insns=[]
        for n,(start,kind) in enumerate(markers[:-1]):
            end=markers[n+1][0]
            if kind=='a': raise ValueError('ARM code in Thumb-only extension')
            if kind=='d':
                data_ranges.append([start,end]); continue
            decoded=list(cs.disasm(blob[start-allocation_base:end-allocation_base],start))
            if sum(i.size for i in decoded)!=end-start: raise ValueError('undecoded injected text')
            insns.extend(decoded)
        for i in insns:
            instructions.append(dict(address=hex(i.address),size=i.size,mnemonic=i.mnemonic,operands=i.op_str))
            if i.group(CS_GRP_JUMP) or i.group(CS_GRP_CALL):
                immediate=[op.imm for op in i.operands if op.type==2]
                if not immediate: continue  # register destinations tested in CPU harness
                target=immediate[-1]
                if not allocation_base<=target<allocation_base+len(blob): raise ValueError('out-of-allocation direct branch')
                if i.mnemonic in ['b.w','bl'] and decode_branch(i.bytes,i.address)!=target: raise ValueError('independent branch decoding differs')
                branches.append(dict(site=hex(i.address),target=hex(target)))
            for op in i.operands:
                if op.type==3 and cs.reg_name(op.mem.base)=='pc':
                    pool=((i.address+4)&~3)+op.mem.disp
                    if not allocation_base<=pool<allocation_base+len(blob): raise ValueError('out-of-allocation literal pool')
                    literals.append(dict(site=hex(i.address),pool=hex(pool)))
    starts={int(x['address'],16) for x in instructions}
    if any(int(x['target'],16) not in starts for x in branches): raise ValueError('branch into data or middle of instruction')
    if any(not any(a<=int(x['pool'],16)<b for a,b in data_ranges) for x in literals): raise ValueError('literal outside ELF-declared data')
    return dict(instructions=instructions,branches=branches,literal_references=literals,
                literal_data_ranges=[[hex(a),hex(b)] for a,b in data_ranges],
                thumb=True,unresolved_relocations=0)


def full_disassembly(decoded,manifest):
    labels={}
    for name,symbol in manifest['symbols'].items():
        address=int(symbol['address'],16)&~1
        if symbol.get('size'): labels.setdefault(address,[]).append(name)
    lines=['; Entire injected Thumb text, including setup/vendor handlers, validator,',
           '; and both bounded ACK helpers. Literal/data ranges are listed at end.']
    for ins in decoded['instructions']:
        address=int(ins['address'],16)
        for name in labels.get(address,[]): lines.append(name+':')
        lines.append(f"{address:08x}: {ins['mnemonic']:<10} {ins['operands']}")
    lines.append('; literal/data ranges: '+json.dumps(decoded['literal_data_ranges']))
    return '\n'.join(lines)+'\n'


def build(raw,enable_eq=False,guard_trace=False,output_variant=None):
    metadata(raw); proof=ownership(raw); OUT.mkdir(parents=True,exist_ok=True)
    if enable_eq:
        proof['original_payload_bytes_preserved_except_hook_words']=False
        proof['additional_hash_locked_stock_patch_sites']=['0x13042-0x13054','0x1311c-0x13128',
                                                           '0x12f86-0x12f88','0x13238-0x1323a']
    if guard_trace and not enable_eq: raise ValueError('guard trace requires EQ test')
    variant=output_variant or ('eq-test' if enable_eq else 'caps-only')
    source=Path(__file__).with_name('custom_vendor_eq.c')
    obj=OUT/(variant+'.o')
    command=['clang','--target=arm-none-eabi','-mcpu=cortex-m4','-mthumb',
        '-mfpu=fpv4-sp-d16','-mfloat-abi=softfp','-ffreestanding','-fno-builtin',
        '-fno-strict-aliasing','-fno-unwind-tables','-fno-asynchronous-unwind-tables',
        '-fno-ident','-Os','-Wall','-Wextra','-Werror',f'-DENABLE_EQ_TEST={int(enable_eq)}',
        f'-DGUARD_TRACE={int(guard_trace)}',
        '-c',str(source),'-o',str(obj)]
    if not shutil.which('clang'): raise ValueError('clang unavailable')
    compiler=subprocess.check_output(['clang','--version'],text=True).splitlines()[0]
    key=sha((compiler+'\n'+sha(source.read_bytes())+'\n'+json.dumps(command[:-4])).encode())
    identity=OUT/(variant+'.build-key')
    if not obj.exists() or not identity.exists() or identity.read_text()!=key:
        subprocess.run(command,check=True,capture_output=True); identity.write_text(key)
    blob,manifest=link(obj.read_bytes(),INJECT_CODE)
    if INJECT_OFFSET+len(blob)>PAYLOAD_LIMIT: raise ValueError('extension exceeds allocated envelope')
    decoded=validate_blob(blob,manifest)
    stock,timeout_report=(patch_stock_timeout(raw,manifest) if enable_eq else
                          (raw,dict(enabled=False)))
    image=bytearray(stock[:-4]); image.extend(b'\xff'*(PAYLOAD_LIMIT-len(image)))
    image[INJECT_OFFSET:INJECT_OFFSET+len(blob)]=blob
    hookreport={}
    for name,(off,old,label) in HOOKS.items():
        target=int(manifest['symbols'][label]['address'],16)
        if not target&1 or not INJECT_CODE<=target&~1<INJECT_CODE+len(blob):
            raise ValueError('invalid Thumb callback destination')
        struct.pack_into('<I',image,off,target)
        hookreport[name]=dict(file_offset=hex(off),old=hex(old),new=hex(target),
                             data_alias=hex(0x20000000+0x95d8+off-0x11eb0))
    image.extend(struct.pack('<I',FLASH_BASE)); image=bytes(image)
    # No existing functionality/data silently sacrificed to make space.
    allowed=[(off,off+4) for off,_,_ in HOOKS.values()]
    if enable_eq:
        allowed += [(0x13042,0x13042+18),(0x1311c,0x1311c+12),
                    (0x12f86,0x12f88),(0x13238,0x1323a)]
    for start,end in changed_ranges(raw[:-4],image[:len(raw)-4]):
        if not any(off<=start and end<=limit for off,limit in allowed):
            raise ValueError('unexpected change in original payload')
    if image[0x1e4c4:0x1e550]!=raw[0x1e4c4:0x1e550]: raise ValueError('boot EQ changed')
    report=dict(variant=variant,input_sha256=sha(raw),output_sha256=sha(image),
        input_length=len(raw),output_length=len(image),payload_length=PAYLOAD_LIMIT,
        compiler=compiler,source_sha256=sha(source.read_bytes()),build_key=key,
        blob_sha256=sha(blob),blob_length=len(blob),hooks=hookreport,allocation=proof,
        link=manifest,changed_ranges=[[hex(s),hex(e)] for s,e in changed_ranges(raw,image)],
        byte_change_semantics='exclusive ends; last range includes append and footer relocation',
        validity_marker='unchanged FF placeholder; physical writer must follow existing marker verification',
        expected_marked_payload_sha256=sha(b'\x1c\xec\x57\xbe'+image[4:-4]),
        footer=hex(FLASH_BASE),audio_hid_descriptors_preserved=True,
        boot_eq_preserved=True,legacy_vendor_callback_preserved=True,
        branch_validation=dict(direct_branches=len(decoded['branches']),
                               instructions=len(decoded['instructions']),literal_references=decoded['literal_references'],
                               literal_data_ranges=decoded['literal_data_ranges']),
        runtime_eq=dict(function='0x0020a938',thumb_pointer='0x0020a939',
                        arguments=dict(r0=0,r1='aligned transient <ffI> + 8 <Ifff> configuration',r2=2),
                        enabled=enable_eq,parameter='common L/R global gain, [-12,0] dB',
                        bank_wait=('bounded polling in both stock loops' if enable_eq else 'not exposed')),
        timeout_patch=timeout_report,
        requests=dict(GET_EOIC_CAPS=dict(bmRequestType=0xc0,bRequest=0xe0,wValue=0x454f,wIndex=0x4943,wLength=12),
                      SET_EQ_TEST=dict(bmRequestType=0x40,bRequest=0xe1,wValue=0x454f,wIndex=0x4943,wLength=4)),
        verification_limits='Offline handler/CPU tests are not physical USB/audio/DSP validation.')
    (OUT/(variant+'.bin')).write_bytes(image)
    (OUT/(variant+'-extension.bin')).write_bytes(blob)
    (OUT/(variant+'-report.json')).write_text(json.dumps(report,indent=2)+'\n')
    (OUT/(variant+'-decoded.json')).write_text(json.dumps(decoded,indent=2)+'\n')
    if enable_eq:
        (OUT/'eq-test-handler-disassembly.txt').write_text(full_disassembly(decoded,manifest))
    return image,report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input',type=Path,default=ROOT/'firmware/private/stock_b.bin')
    parser.add_argument('--enable-eq-test',action='store_true')
    args=parser.parse_args()
    _,report=build(args.input.read_bytes(),args.enable_eq_test)
    print(json.dumps({k:report[k] for k in ['variant','output_sha256','blob_length','hooks','changed_ranges']},indent=2))

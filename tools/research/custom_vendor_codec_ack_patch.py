#!/usr/bin/env python3
"""Build the passive codec-ACK diagnostic on the verified scheduler image."""
import argparse, hashlib, json, struct, subprocess
from collections import Counter
from pathlib import Path
from arm_elf import link
from custom_vendor_patch import ROOT, OUT, CODE_BASE, PAYLOAD_LIMIT, changed_ranges
from custom_vendor_telemetry_patch import (validate_blob, source_offset,
    APP_LOOP, QUEUE_PUSH, EVENT_SET, EVENT_CLEAR, entry_veneer)

BASE_SHA='9e626fe28abbff2905d618c626d78d6c3f1dc79157da39f22eb0de45bc1bdade'
OFFICIAL_SHA='2f418d3a324ec4217c32c4bf98d43c3cd07d59d81f82974f29320d399fa769f3'
VARIANT='codec-ack-progress'
OFFSET=0x1f400
ADDRESS=CODE_BASE+OFFSET
OUTDIR=OUT/'codec-ack'
HOOKS={
  0x20a478:('eoic_hook_transaction_entry','18701b78012bd9d1'),
  0x20a462:('eoic_hook_config_changed','7e4a6b80288071803780'),
  0x20a57a:('eoic_hook_config_equal','374eb4f8c61072882088'),
  0x20a6d4:('eoic_hook_coefficient_progress','dcf80430cef81030'),
  0x20a762:('eoic_hook_request_assert','1a6842f480021a601a68'),
  0x20a772:('eoic_hook_success_cleanup','00221a703a78c2f1010252b23a70'),
  0x20a842:('eoic_hook_request_clear','1a601a68d201fcd491e7'),
  0x20a5e2:('eoic_hook_error_first','116863f31c7111600320'),
  0x20a784:('eoic_hook_error_second','116863f35d711160'),
}
RUNTIME={APP_LOOP:'eoic_codec_app_loop',QUEUE_PUSH:'eoic_codec_queue_push',
         EVENT_SET:'eoic_codec_event_set',EVENT_CLEAR:'eoic_codec_event_clear'}
WORD_HOOKS={0x1d990:'eoic_codec_setup',0x1d384:'eoic_codec_vendor'}

def sha(b): return hashlib.sha256(b).hexdigest()

def absolute_pc_veneer(site,target,size):
    """LDR.W pc literal veneer, preserving all registers at the hook site."""
    if site&1 or not target&1: raise ValueError('hook site must be aligned and target must be Thumb')
    imm=0 if site%4==0 else 4
    code=struct.pack('<HH',0xf8df,0xf000|imm)
    pcbase=(site+4)&~3
    lit=pcbase+imm
    prefix=code+b'\x00\xbf'*( (lit-(site+4))//2 )
    if len(prefix)!=lit-site: raise ValueError('veneer literal alignment')
    result=prefix+struct.pack('<I',target)
    if len(result)>size: raise ValueError(f'veneer does not fit hook at {site:#x}')
    return result+b'\x00\xbf'*((size-len(result))//2)

def asm_as_c(source):
    lines=[]
    for line in source.splitlines():
        line=line.replace('\\','\\\\').replace('"','\\"')
        lines.append('"'+line+'\\n"')
    return '\n'.join(['__asm__(']+lines+[');'])

def compile_blob():
    cpath=ROOT/'tools/research/custom_vendor_codec_ack.c'
    spath=ROOT/'tools/research/custom_vendor_codec_ack.S'
    generated=OUTDIR/(VARIANT+'.combined.c'); obj=OUTDIR/(VARIANT+'.o')
    OUTDIR.mkdir(parents=True,exist_ok=True)
    generated.write_text(cpath.read_text()+'\n'+asm_as_c(spath.read_text())+'\n')
    clang=subprocess.check_output(['clang','--version'],text=True).splitlines()[0]
    cmd=['clang','--target=arm-none-eabi','-mcpu=cortex-m4','-mthumb',
      '-mfpu=fpv4-sp-d16','-mfloat-abi=softfp','-ffreestanding','-fno-builtin',
      '-fno-strict-aliasing','-fno-unwind-tables','-fno-asynchronous-unwind-tables',
      '-fno-ident','-Os','-Wall','-Wextra','-Werror','-c',str(generated),'-o',str(obj)]
    key=sha((clang+'\n'+sha(cpath.read_bytes())+'\n'+sha(spath.read_bytes())+'\n'+json.dumps(cmd[:-4])).encode())
    keypath=OUTDIR/(VARIANT+'.build-key')
    if not obj.exists() or not keypath.exists() or keypath.read_text()!=key:
        subprocess.run(cmd,check=True,capture_output=True); keypath.write_text(key)
    blob,manifest=link(obj.read_bytes(),ADDRESS)
    if OFFSET+len(blob)>PAYLOAD_LIMIT: raise ValueError('codec diagnostic exceeds allocated extension envelope')
    decoded=validate_blob(blob,manifest)
    expected=Counter([0x20a481,0x20a435,0x20a46d,0x20a585,0x20a6dd,
                      0x20a771,0x20a781,0x20a771,0x20a437,0x20a437])
    observed=[]
    for ins in decoded['instructions']:
        if ins['mnemonic'].startswith('ldr') and ins['operands'].startswith('pc, [pc'):
            site=int(ins['address'],16); pool=((site+4)&~3)
            if '#0x' in ins['operands']:
                disp=int(ins['operands'].split('#0x',1)[1].split(']',1)[0],16)
            elif '#' in ins['operands']:
                disp=int(ins['operands'].split('#',1)[1].split(']',1)[0],0)
            else: disp=0
            pool+=disp
            observed.append(struct.unpack_from('<I',blob,pool-ADDRESS)[0])
    if Counter(observed)!=expected: raise ValueError('Thumb PC-load continuation targets mismatch: '+repr(observed))
    decoded['verified_original_continuations']=[hex(x) for x in sorted(observed)]
    return cpath,spath,clang,key,blob,manifest,decoded

def build(base):
    if sha(base)!=BASE_SHA or len(base)!=0x20004: raise ValueError('input must be exact scheduler-telemetry.bin')
    sched_report=json.loads((OUT/'scheduler-telemetry-report.json').read_text())
    if sched_report.get('output_sha256')!=BASE_SHA or sched_report.get('official_b_sha256')!=OFFICIAL_SHA:
        raise ValueError('scheduler build report identity mismatch')
    source_b=(ROOT/'firmware/private/stock_b.bin').read_bytes()
    if sha(source_b)!=OFFICIAL_SHA: raise ValueError('official B input hash mismatch')
    cpath,spath,clang,key,blob,manifest,decoded=compile_blob()
    image=bytearray(base)
    image[OFFSET:PAYLOAD_LIMIT]=b'\xff'*(PAYLOAD_LIMIT-OFFSET)
    image[OFFSET:OFFSET+len(blob)]=blob
    symbols=manifest['symbols']
    hook_rows=[]
    for addr,(symbol,prehex) in HOOKS.items():
        pre=bytes.fromhex(prehex); off=source_offset(addr,len(pre))
        if bytes(source_b[off:off+len(pre)])!=pre or bytes(base[off:off+len(pre)])!=pre:
            raise ValueError(f'codec hook preimage mismatch at {addr:#x}')
        target=int(symbols[symbol]['address'],16)
        if not (target&1 and ADDRESS<=target&~1<ADDRESS+len(blob)): raise ValueError('invalid hook destination')
        veneer=absolute_pc_veneer(addr,target,len(pre))
        image[off:off+len(pre)]=veneer
        hook_rows.append(dict(address=hex(addr),file_offset=hex(off),symbol=symbol,
          size=len(pre),before=pre.hex(),after=veneer.hex(),target=hex(target)))
    runtime_rows=[]
    by_addr={int(x['address'],16):x for x in sched_report['runtime_hooks']}
    for addr,symbol in RUNTIME.items():
        row=by_addr[addr]; off=int(row['file_offset'],16); old=bytes.fromhex(row['after'])
        if bytes(base[off:off+len(old)])!=old: raise ValueError('scheduler runtime hook changed: '+hex(addr))
        target=int(symbols[symbol]['address'],16)
        new=(struct.pack('<HHHI',0x4b01,0x4718,0xbf00,target) if addr==APP_LOOP
             else entry_veneer(target))
        image[off:off+len(old)]=new
        runtime_rows.append(dict(address=hex(addr),file_offset=hex(off),symbol=symbol,before=old.hex(),after=new.hex()))
    word_rows=[]
    base_hooks=sched_report['hooks']
    for off,symbol in WORD_HOOKS.items():
        key='setup' if off==0x1d990 else 'vendor'
        old=int(base_hooks[key]['new'],16)
        if struct.unpack_from('<I',base,off)[0]!=old: raise ValueError('scheduler USB callback pointer mismatch')
        target=int(symbols[symbol]['address'],16)
        struct.pack_into('<I',image,off,target)
        word_rows.append(dict(file_offset=hex(off),symbol=symbol,before=hex(old),after=hex(target)))
    image[-4:]=base[-4:]
    image=bytes(image)
    # Only the injected extension, reviewed hook sites, and wrapper pointers may differ.
    allowed=[(OFFSET,PAYLOAD_LIMIT)]+[(int(r['file_offset'],16),int(r['file_offset'],16)+r['size']) for r in hook_rows]
    allowed += [(int(r['file_offset'],16),int(r['file_offset'],16)+4) for r in word_rows]
    allowed += [(int(r['file_offset'],16),int(r['file_offset'],16)+len(bytes.fromhex(r['after']))) for r in runtime_rows]
    diffs=[(a,b) for a,b in changed_ranges(base,image) if not any(x<=a and b<=y for x,y in allowed)]
    if diffs: raise ValueError('unexpected changed range '+repr(diffs[:4]))
    # Preserve the scheduler image's stock metadata, footer, and boot EQ bytes.
    for start,end in [(0x1e4c4,0x1e550),(0x1ec8c,0x1edc4),(0x20000,0x20004)]:
        if base[start:end]!=image[start:end]: raise ValueError('base metadata/boot-EQ/footer changed')
    RX_USED=128+52+52+8  # 11-byte progress state uses CODEC reserved[3] plus 8 spare bytes.
    if RX_USED>240: raise ValueError('diagnostic RAM exceeds original USB RX reservation')
    report=dict(variant=VARIANT,input_sha256=BASE_SHA,official_b_sha256=OFFICIAL_SHA,
      output_sha256=sha(image),output_length=len(image),compiler=clang,build_key=key,
      source_sha256=sha(cpath.read_bytes()),assembly_sha256=sha(spath.read_bytes()),
      extension_file_offset=hex(OFFSET),extension_address=hex(ADDRESS),extension_length=len(blob),
      extension_sha256=sha(blob),telemetry_state=dict(rx_buffer='0x20019804',rx_limit=128,
        e3_address='0x20019884',e3_length=52,e4_address='0x200198b8',e4_length=52,
        progress_state_address='0x200198e9',progress_state_length=11,
        total_reserved=RX_USED,original_reserved=240),
      hooks=hook_rows,runtime_hooks=runtime_rows,usb_callback_hooks=word_rows,
      event_ids=['transaction_entry','request_assert','ack_high','request_clear','ack_low','bank_toggle','busy_clear','error_exit'],
      progress_checkpoints=[
        dict(address='0x20a47e',id=0,name='busy_readback_branch',counts=0),
        dict(address='0x20a462',id=1,name='configuration_changed_edge',counts=1),
        dict(address='0x20a57a',id=2,name='configuration_equal_edge',counts=2),
        dict(address='0x20a6d4',id=3,name='coefficient_copy_progress',counts=3),
        dict(address='0x20a762',id=4,name='before_main_register_request',counts=4),
        dict(address='0x20a842',id=5,name='before_alternate_request_clear',counts=5)],
      ack_snapshot=dict(register='0x403000e0',request_bit=22,ack_bit=24,busy='0x200162b4',selector='0x200162bc'),
      instrumentation=dict(event_hook_calls='one fixed-cost call per reached event; no hook in ACK polling iterations',
        counter_updates='saturating 32-bit increments under a short PRIMASK-preserving critical section',
        e4_snapshot='fixed 13-word copy under PRIMASK into RX buffer; stable response payload',
        e4_reserved_bytes='remain zero on the wire; progress state uses those three bytes internally',
        e5_snapshot='28-byte read-only checkpoint, live busy/register/bank snapshot',
        extra_hook_stack_bytes=64,stock_ack_waits='unchanged semantics; still unbounded'),
      requests=dict(GET_EOIC_CAPS=dict(bmRequestType='0xc0',bRequest='0xe0',wValue='0x454f',wIndex='0x4943',wLength=12,expected='454f49430100080004000000'),
        GET_SCHEDULER_TELEMETRY=dict(bmRequestType='0xc0',bRequest='0xe3',wValue='0x454f',wIndex='0x4943',wLength=52),
        GET_CODEC_ACK_DIAGNOSTIC=dict(bmRequestType='0xc0',bRequest='0xe4',wValue='0x454f',wIndex='0x4943',wLength=52,magic='EACK',version=1),
        GET_CODEC_PROGRESS=dict(bmRequestType='0xc0',bRequest='0xe5',wValue='0x454f',wIndex='0x4943',wLength=28,magic='EPRG',version=1)),
      changed_ranges=[[hex(a),hex(b)] for a,b in changed_ranges(base,image)],
      validation=dict(thumb=decoded['thumb'],instruction_count=len(decoded['instructions']),
        direct_branches=len(decoded['branches']),literal_references=len(decoded['literal_references']),
        unresolved_relocations=0,all_hook_targets_thumb=True,all_original_hook_preimages_match=True,
        verified_original_continuations=decoded['verified_original_continuations'],
        instrumentation_additional_codec_mmio_writes=0,instrumentation_additional_busy_writes=0,
        stock_operations_replayed_from_verified_preimages=True,no_setter_calls=True,
        bounded_instrumentation=True))
    OUTDIR.mkdir(parents=True,exist_ok=True)
    (OUTDIR/(VARIANT+'.bin')).write_bytes(image)
    (OUTDIR/(VARIANT+'-decoded.json')).write_text(json.dumps(decoded,indent=2)+'\n')
    (OUTDIR/(VARIANT+'-report.json')).write_text(json.dumps(report,indent=2)+'\n')
    return image,report

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--build',action='store_true')
    args=ap.parse_args()
    if not args.build: ap.error('offline builder only; use --build')
    base=(OUT/'scheduler-telemetry.bin').read_bytes()
    image,report=build(base)
    print(json.dumps({k:report[k] for k in ('output_sha256','hooks','runtime_hooks','usb_callback_hooks','changed_ranges','validation')},indent=2))
if __name__=='__main__': main()

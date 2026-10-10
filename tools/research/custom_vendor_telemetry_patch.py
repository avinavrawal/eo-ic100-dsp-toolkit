#!/usr/bin/env python3
"""Build deterministic read-only scheduler telemetry firmware, offline only."""
import argparse, hashlib, json, shutil, struct, subprocess
from pathlib import Path
from arm_elf import link
from custom_vendor_patch import (ROOT, OUT, CODE_BASE, PAYLOAD_LIMIT, SOURCE_SHA,
                                 build as build_caps, changed_ranges, ram_image,
                                 validate_blob)
from runtime_eq_map import PROFILES

VARIANT='scheduler-telemetry'
OFFSET=0x1f400
ADDRESS=CODE_BASE+OFFSET
STATE=0x200198b4
RX=0x20019804
RX_LIMIT=176
QUEUE=0x200196ac
APP_LOOP=0x0020aa82
QUEUE_PUSH=0x0020d54c
EVENT_SET=0x00204758
EVENT_CLEAR=0x0020479c
ORIGINAL_SITES={
    APP_LOOP: bytes.fromhex('02f0a1fbfff701f8fae7'),
    QUEUE_PUSH: bytes.fromhex('10b4eff3108313f00102'),
    EVENT_SET: bytes.fromhex('1f281bd8eff31083'),
    EVENT_CLEAR: bytes.fromhex('1f281dd8eff31083'),
}
HOOK_WORDS={0x1d990:('eoic_telemetry_setup',0x0020dd11),
            0x1d384:('eoic_telemetry_vendor',0x0020d999)}

def sha(b): return hashlib.sha256(b).hexdigest()

def source_offset(address,size=1):
    """Map the 0x002xxxxx initialized-RAM alias back to exact stock file bytes."""
    ram=0x20000000+(address-0x00200000)
    for start,end,dest in PROFILES['official023']['segments']:
        if dest<=ram and ram+size<=dest+(end-start):
            return start+(ram-dest)
    raise ValueError('hook address outside initialized source segments: '+hex(address))

def entry_veneer(pointer):
    if pointer&1==0: raise ValueError('hook target is not Thumb')
    return struct.pack('<HHI',0x4b00,0x4718,pointer)

def compile_extension():
    OUT.mkdir(parents=True,exist_ok=True)
    source=Path(__file__).with_name('custom_vendor_telemetry.c')
    obj=OUT/(VARIANT+'.o')
    cmd=['clang','--target=arm-none-eabi','-mcpu=cortex-m4','-mthumb',
         '-mfpu=fpv4-sp-d16','-mfloat-abi=softfp','-ffreestanding','-fno-builtin',
         '-fno-strict-aliasing','-fno-unwind-tables','-fno-asynchronous-unwind-tables',
         '-fno-ident','-Os','-Wall','-Wextra','-Werror','-c',str(source),'-o',str(obj)]
    if not shutil.which('clang'): raise ValueError('clang unavailable')
    compiler=subprocess.check_output(['clang','--version'],text=True).splitlines()[0]
    key=sha((compiler+'\n'+sha(source.read_bytes())+'\n'+json.dumps(cmd[:-4])).encode())
    ident=OUT/(VARIANT+'.build-key')
    if not obj.exists() or not ident.exists() or ident.read_text()!=key:
        subprocess.run(cmd,check=True,capture_output=True); ident.write_text(key)
    blob,manifest=link(obj.read_bytes(),ADDRESS)
    if OFFSET+len(blob)>PAYLOAD_LIMIT: raise ValueError('telemetry extension allocation overflow')
    return source,compiler,key,blob,manifest,validate_blob(blob,manifest)

def build(raw):
    if sha(raw)!=SOURCE_SHA or len(raw)!=0x1edc8:
        raise ValueError('input must be exact official Samsung 0.23 B')
    caps_image,caps_report=build_caps(raw,False,False,'telemetry-base-caps')
    source,compiler,key,blob,manifest,decoded=compile_extension()
    if caps_report['blob_length']>OFFSET-0x1f000: raise ValueError('base CAPS extension overlaps telemetry')
    setter_refs=[r for r in caps_report['link']['relocations']+manifest['relocations']
                 if (int(r['target'],16)&~1)==0x0020a938]
    if setter_refs: raise ValueError('CAPS/telemetry image contains a DSP setter reference')
    image=bytearray(caps_image)
    image[OFFSET:OFFSET+len(blob)]=blob
    symbols=manifest['symbols']
    hook_report={}
    for off,(name,old) in HOOK_WORDS.items():
        target=int(symbols[name]['address'],16)
        if not target&1 or not ADDRESS<=target&~1<ADDRESS+len(blob):
            raise ValueError('invalid Thumb callback destination')
        if struct.unpack_from('<I',raw,off)[0]!=old: raise ValueError('callback preimage mismatch')
        struct.pack_into('<I',image,off,target)
        key='setup' if name.endswith('_setup') else 'vendor'
        hook_report[key]=dict(file_offset=hex(off),old=hex(old),new=hex(target),symbol=name)
    base_ram=ram_image(raw)
    code_alias=0x00200000
    sites={}
    for addr,preimage in ORIGINAL_SITES.items():
        off=source_offset(addr,len(preimage))
        ram_at=addr-code_alias
        actual=bytes(base_ram[ram_at:ram_at+len(preimage)])
        if actual!=preimage: raise ValueError(f'RAM hook preimage mismatch at {addr:#x}: {actual.hex()}')
        if raw[off:off+len(preimage)]!=preimage:
            raise ValueError(f'file hook preimage mismatch at {addr:#x}')
        sites[addr]=off
    app_target=int(symbols['eoic_telemetry_app_loop']['address'],16)
    push_target=int(symbols['eoic_telemetry_queue_push']['address'],16)
    set_target=int(symbols['eoic_telemetry_event_set']['address'],16)
    clear_target=int(symbols['eoic_telemetry_event_clear']['address'],16)
    # The loop veneer is a tail transfer. It preserves the 0x204d84 result in
    # r0, then the replacement loop calls consumer and event-service in order.
    app_veneer=struct.pack('<HHHI',0x4b01,0x4718,0xbf00,app_target)
    if len(app_veneer)!=10: raise AssertionError('app veneer size')
    # The literal at aa88 is word aligned; the NOP at aa86 is never executed.
    image[sites[APP_LOOP]:sites[APP_LOOP]+10]=app_veneer
    image[sites[QUEUE_PUSH]:sites[QUEUE_PUSH]+8]=entry_veneer(push_target)
    image[sites[EVENT_SET]:sites[EVENT_SET]+8]=entry_veneer(set_target)
    image[sites[EVENT_CLEAR]:sites[EVENT_CLEAR]+8]=entry_veneer(clear_target)
    # Rebuild final output with telemetry bytes and original footer.
    image[-4:]=struct.pack('<I',0x3c02e000)
    image=bytes(image)
    expected={
        source_offset(APP_LOOP,10):(app_veneer,'app-loop'),
        source_offset(QUEUE_PUSH,8):(entry_veneer(push_target),'queue-push'),
        source_offset(EVENT_SET,8):(entry_veneer(set_target),'event-set'),
        source_offset(EVENT_CLEAR,8):(entry_veneer(clear_target),'event-clear'),
    }
    for off,(new,_) in expected.items():
        if image[off:off+len(new)]!=new: raise ValueError('hook bytes failed readback '+hex(off))
    allowed=[(o,o+4) for o in HOOK_WORDS]
    allowed += [(o,o+len(v[0])) for o,v in expected.items()]
    for start,end in changed_ranges(raw[:-4],image[:len(raw)-4]):
        if not any(a<=start and end<=b for a,b in allowed) and start<0x1edc4:
            raise ValueError('unexpected original-image change '+hex(start)+'..'+hex(end))
    if image[0x1e4c4:0x1e550]!=raw[0x1e4c4:0x1e550]: raise ValueError('boot EQ changed')
    if image[0x1ec8c:0x1edc4]!=raw[0x1ec8c:0x1edc4]: raise ValueError('build metadata changed')
    report=dict(variant=VARIANT,input_sha256=sha(raw),output_sha256=sha(image),
        official_b_sha256=SOURCE_SHA,input_length=len(raw),output_length=len(image),
        compiler=compiler,source_sha256=sha(source.read_bytes()),build_key=key,
        base_caps_sha256=caps_report['output_sha256'],base_caps_blob_length=caps_report['blob_length'],
        extension_file_offset=hex(OFFSET),extension_address=hex(ADDRESS),extension_length=len(blob),
        extension_sha256=sha(blob),link=manifest,hooks=hook_report,
        runtime_hooks=[dict(address=hex(a),file_offset=hex(source_offset(a,len(ORIGINAL_SITES[a]))),
                            size=len(new),name=name,before=ORIGINAL_SITES[a].hex(),after=new.hex())
                       for a in ORIGINAL_SITES
                       for new,name in [expected[source_offset(a,len(ORIGINAL_SITES[a]))]]],
        changed_ranges=[[hex(a),hex(b)] for a,b in changed_ranges(raw,image)],
        telemetry_state=dict(address=hex(STATE),size=52,response_length=52,rx_buffer=hex(RX),
                             rx_limit=RX_LIMIT,magic='ECTM',protocol=1),
        requests=dict(GET_EOIC_CAPS=dict(bmRequestType=0xc0,bRequest=0xe0,wValue=0x454f,wIndex=0x4943,wLength=12,expected='454f49430100080004000000'),
                      GET_EQ_DIAGNOSTIC=dict(bmRequestType=0xc0,bRequest=0xe2,wValue=0x454f,wIndex=0x4943,wLength=32,expected='4551444701002000000000000000000000000000ffffffff0000000000000000'),
                      GET_SCHEDULER_TELEMETRY=dict(bmRequestType=0xc0,bRequest=0xe3,wValue=0x454f,wIndex=0x4943,wLength=52),
                      SET_EQ_TEST=dict(bmRequestType=0x40,bRequest=0xe1,wValue=0x454f,wIndex=0x4943,wLength=4,enabled=False)),
        counter_semantics=dict(app_loops='saturating application-loop iterations',consumer_calls='calls to stock 0x20d1c8',
          event_signals='bit-3 sets through shared 0x204758 helper',event_consumed='bit-3 clears through shared 0x20479c helper; includes all helper callers',
          busy_zero_samples='loop samples of 0x200162b4 == 0',busy_one_samples='loop samples of 0x200162b4 != 0',
          queue_full='failed raw pushes for queue 0x200196ac',queue_depth='instantaneous ring count',
          queue_highwater='ring high-water field',command_total_ticks='raw 0x201788 timer delta across consumer calls',
          command_max_ticks='maximum raw timer delta across a consumer call'),
        timing_overhead='per loop: three raw timer reads plus bounded snapshots/counters; consumer timing brackets two reads; queue/event wrappers add one short PRIMASK-preserving section; timer frequency uncalibrated',
        safety=dict(no_eq_setter=True,no_busy_flag_write=True,no_codec_mmio_write=True,no_af_thread_hook=True,
                    no_blocking_wait=True,stock_a_preserved=True,existing_stock_commands_delegated=True,
                    rx_size_reduced_from=240,to=176,known_legacy_payloads_max=18),
        validation=dict(thumb=True,instructions=len(decoded['instructions']),direct_branches=len(decoded['branches']),
                        literal_references=decoded['literal_references'],unresolved_relocations=0,
                        dsp_setter_references=setter_refs))
    OUT.mkdir(parents=True,exist_ok=True)
    (OUT/(VARIANT+'.bin')).write_bytes(image)
    (OUT/(VARIANT+'-extension.bin')).write_bytes(blob)
    (OUT/(VARIANT+'-decoded.json')).write_text(json.dumps(decoded,indent=2)+'\n')
    (OUT/(VARIANT+'-report.json')).write_text(json.dumps(report,indent=2)+'\n')
    return image,report

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--build',action='store_true')
    args=ap.parse_args()
    if not args.build: ap.error('use --build; this tool never accesses USB')
    raw=(ROOT/'firmware/private/stock_b.bin').read_bytes()
    image,report=build(raw)
    print(json.dumps({k:report[k] for k in ['output_sha256','changed_ranges','extension_length','hooks','runtime_hooks','validation']},indent=2))

if __name__=='__main__': main()

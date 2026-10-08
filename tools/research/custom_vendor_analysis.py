#!/usr/bin/env python3
"""Cached B-specific indexes, ABI maps, negative findings and focused disassembly."""
import hashlib
import json
import re
import struct
import subprocess
from pathlib import Path
from custom_vendor_patch import ROOT,OUT,SOURCE_SHA,FLASH_BASE,CODE_BASE,metadata,ownership,ram_image
from thumb_index import index

FUNCTIONS={
 'usb_irq':(0x6a50,0x6e80), 'usb_ep0_state_handler':(0x6130,0x6a50),
 'usb_ep0_send_packet':(0x5c9c,0x5cf8),
 'uaud_setuprecv':(0xdd10,0xe084), 'uaud_datarecv':(0xe5fc,0xe7e0),
 'vendor_dispatch':(0xd998,0xdaf8), 'usb_audio_set_eq':(0xc800,0xc840),
 'audio_eq_set_cfg':(0xa938,0xa994), 'hw_codec_iir_get_cfg':(0xa178,0xa424),
 'hw_codec_iir_set_cfg':(0xa424,0xa868), 'usb_audio_open_eq':(0xc840,0xc9a0),
 'usb_audio_open':(0xe93c,0xebd0), 'peq_type_dispatch':(0xa130,0xa178)}


def write(name,obj):
    (OUT/name).write_text(json.dumps(obj,indent=2)+'\n')


def main():
    raw=(ROOT/'firmware/private/stock_b.bin').read_bytes(); metadata(raw)
    OUT.mkdir(parents=True,exist_ok=True)
    ram=ram_image(raw); ramfile=OUT/'original-b-ram.bin'
    if not ramfile.exists() or ramfile.read_bytes()!=ram: ramfile.write_bytes(ram)
    ram_sha=hashlib.sha256(ram).hexdigest()
    version=subprocess.check_output(['r2','-v'],text=True).strip()
    dependencies=['custom_vendor_analysis.py','custom_vendor_patch.py','runtime_eq_map.py','thumb_index.py']
    identity_data=ram_sha+SOURCE_SHA+version+''.join(hashlib.sha256(Path(__file__).with_name(p).read_bytes()).hexdigest() for p in dependencies)
    key=hashlib.sha256(identity_data.encode()).hexdigest()
    identity=OUT/'analysis-key'
    if identity.exists() and identity.read_text()==key and (OUT/'negative-findings.json').exists():
        print('Reused B indexes/maps:',key[:16]); return
    idx=index(ram,0x00200000); flashidx=index(raw[:-4],CODE_BASE)
    write('thumb-xrefs.json',idx);write('flash-xrefs.json',flashidx)
    strings=[]
    for m in re.finditer(rb'[ -~]{5,}',ram):
        strings.append(dict(address=hex(0x20000000+m.start()),text=m.group().decode()))
    write('string-index.json',strings)
    functions={name:dict(start=hex(0x00200000+a),range_end=hex(0x00200000+b),
        confidence='reviewed entry; range may include literal pools',
        direct_callers=[hex(x['site']) for x in idx['calls'] if x['target']==0x00200000+a])
        for name,(a,b) in FUNCTIONS.items()}
    write('function-index.json',dict(reviewed=functions,candidate_entries=[hex(x) for x in idx['push_candidates']]))
    graph={name:[dict(site=hex(x['site']),target=hex(x['target']),kind=kind)
        for kind,entries in [('call',idx['calls']),('branch',idx['branches'])]
        for x in entries if 0x00200000+a<=x['site']<0x00200000+b]
        for name,(a,b) in FUNCTIONS.items()}
    write('call-graph.json',dict(scope='linear candidates inside reviewed function ranges; validate against focused disassembly',functions=graph))
    commands=[]
    for i in range(7):
        ptr=struct.unpack_from('<I',ram,0x14c0c+4*i)[0]-0x20000000
        commands.append(dict(id=i+1,prefix=ram[ptr:ram.index(0,ptr)].decode()))
    vendor=dict(source_sha256=SOURCE_SHA,usb_irq='0x00206a50',vector_offset='0x5c',external_irq=7,
        ep0_state_handler='0x00206130',ep0_frame='0x2001ac74',ep0_send_packet='0x00205c9c',
        ep0_transmit_dma='0x2001abf4',usb_controller='0x40180000',
        irq_registration='0x0020714a',hal_callback_table='0x2001ab9c',setup_callback_slot='0x2001aba8',
        setup_entry='0x0020dd10',data_entry='0x0020e5fc',
        callback='0x0020d998',runtime_callback_slot='0x2001b15c',
        calling_convention='AAPCS Thumb; r0 pointer to 12-byte vendor argument; r0 return 0 accept, nonzero reject',
        frame=dict(state=0,payload_pointer=4,payload_length_u16=8,setup_packet=12),
        callback_argument=dict(setup_pointer=0,payload_pointer=4,payload_length_u16=8),
        stock_transport=dict(command_out=dict(type=0x40,request=6,value=0,index=0),
            response_in=dict(type=0xc0,request=12,value=0,index=0),
            firmware_gating='vendor type bits; original callback ignores bRequest/value/index and parses prefixes',
            receive_limit=240,fallback_allocation_limit=64,oversize_behavior='setup logs excessive length then prepares that length; extension guards before receive'),
        commands=commands,response='zero-payload callback replaces argument payload pointer/length; setup copies these to EP0 frame state 4',
        error='callback nonzero -> setup/data handler returns 0; HAL nonstandard rejection follows 0x002064aa reset/re-arm path. Actual host stall vs timeout is unverified. Stock unknown command response is failure, distinct from rejection.',
        custom_caps=dict(type=0xc0,request=0xe0,value=0x454f,index=0x4943,length=12),
        custom_set=dict(type=0x40,request=0xe1,value=0x454f,index=0x4943,length=4,payload='LE float32 common L/R global gain, [-12,0] dB'))
    write('vendor-dispatcher-map.json',vendor)
    write('eq-call-graph.json',dict(source_sha256=SOURCE_SHA,functions={k:v for k,v in functions.items() if 'eq' in k or 'iir' in k},
        chain=['usb_audio_set_eq(2,0)','audio_eq_set_cfg(0,cfg,2)','hw_codec_iir_get_cfg(sample_rate,cfg)','hw_codec_iir_set_cfg(coeffs,sample_rate,1)'],
        config=dict(pointer='0x20015bec',file_offset='0x1e4c4',header='<ffI',band='<Ifff',max_bands=8),
        state=dict(sample_rate='0x200162c8',enabled_byte='0x200162cd',codec_initialized='0x200162b8',update_busy='0x200162b4'),
        coefficients='0x20015fa4',hardware='0x403000e0 swap/control; 0x40302000..0x40302340 coefficient banks',
        bank_update=dict(control='0x403000e0',selection_bit=22,acknowledgement_bit=24,
                         waits=['0x0020a76a','0x0020a844'],timeout='none in stock setter'),
        return_behavior='audio_eq_set_cfg returns 0 nominally and does not propagate all hardware setter errors; preflight guards required'))
    zero_runs=[]
    for byte in [b'\x00',b'\xff']:
        for m in re.finditer(re.escape(byte)+b'{64,}',raw):zero_runs.append(dict(start=hex(m.start()),end=hex(m.end()),byte=byte.hex(),length=len(m.group())))
    negatives=[dict(id='callback-only-out-hook',result='rejected',reason='oversize OUT preparation happens before vendor payload callback'),
        dict(id='zero-ff-caves',result='rejected',reason='runs are initialized data/unused EQ records/segment alignment; no executable ownership proof',runs=zero_runs),
        dict(id='unused-debug-replacement',result='rejected',reason='no unused function proven; logs and auxiliary handlers have callers or unresolved indirect reachability'),
        dict(id='direct-sram-to-flash-branch',result='rejected',reason='0x002... to 0x0c... exceeds Thumb B.W/BL signed 25-bit reach; use registered Thumb function pointers'),
        dict(id='existing-runtime-eq-request',result='absent',reason='reuse previous RUNTIME_EQ_CONTROL registered seven-command audit'),
        dict(id='full-vendor-libm-emulation',result='not reliable in current harness',reason='Unicorn path reached unmapped address 0x3ff921fb; use explicit pow/sqrt/sin/cos models and disclose scope'),
        dict(id='unicorn-sandbox-jit',result='blocked inside sandbox',reason='SIGILL on memory mapping; requires execution exception, no device transport'),
        dict(id='unicorn-2.1.2-wheel',result='unavailable',reason='source build required unavailable cmake; 2.1.4 ARM64 wheel works')]
    negatives.append(dict(id='bounded-stock-eq-update',result='not provided by stock setter',
        reason='two bank-switch loops wait for bit 24 to match bit 22 without timeout; EQ-test remains experimental and is disabled in first-validation CAPS-only image'))
    write('negative-findings.json',negatives)
    write('injection-candidates.json',dict(rejected=negatives[:4],selected=ownership(raw),
        required_validation='new appended allocation, unchanged old payload/metadata/descriptors, pointer hooks, modeled fetch and request execution'))
    commands='e scr.color=0;'+';'.join(f'pD {b-a} @ {0x00200000+a:#x}' for a,b in FUNCTIONS.values())
    cachekey=hashlib.sha256((key+version+commands).encode()).hexdigest()[:16]
    disasm=OUT/('focused-disassembly-'+cachekey+'.txt')
    if not disasm.exists():
        with disasm.open('w') as out,(OUT/'disassembly.stderr').open('w') as err:
            subprocess.run(['r2','-q','-a','arm','-b','16','-m','0x00200000','-c',commands,str(ramfile)],stdout=out,stderr=err,check=True)
    write('analysis-manifest.json',dict(source_sha256=SOURCE_SHA,ram_sha256=ram_sha,analysis_key=key,r2=version,commands=commands,disassembly=disasm.name))
    identity.write_text(key)
    print('Cached B indexes/maps, focused disassembly and negative findings:',key[:16])


if __name__=='__main__': main()

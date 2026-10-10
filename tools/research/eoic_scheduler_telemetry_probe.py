#!/usr/bin/env python3
"""Decode telemetry offline; physical E3 access requires explicit opt-in."""
import argparse, json, struct, sys

CAPS=bytes.fromhex('454f49430100080004000000')
CAPS_REQ=(0xc0,0xe0,0x454f,0x4943,12)
E3_REQ=(0xc0,0xe3,0x454f,0x4943,52)
E5_REQ=(0xc0,0xe5,0x454f,0x4943,28)
FIELDS=('app_loops','consumer_calls','event_signals','event_bit3_clears',
        'busy_zero_samples','busy_nonzero_samples','queue_full','command_total_ticks',
        'command_max_ticks','last_tick')

def decode(data):
    if len(data)!=52: raise ValueError(f'E3 response must be 52 bytes, got {len(data)}')
    magic,version,size=struct.unpack_from('<IHH',data)
    if magic!=0x4d544345 or version!=1 or size!=52:
        raise ValueError('telemetry identity/version/size mismatch')
    values=struct.unpack_from('<10I4B',data,8)
    result=dict(zip(FIELDS,values[:10]))
    result.update(queue_depth=values[10],queue_highwater=values[11],flags=values[12],reserved=values[13])
    result['magic']='ECTM'; result['protocol']=version; result['size']=size
    result['codec_busy_now']=bool(result['flags']&1)
    result['event_bit3_pending_now']=bool(result['flags']&2)
    result['queue_nonempty_now']=bool(result['flags']&4)
    result['timer_units']='raw 0x201788 timer counts; frequency not calibrated'
    return result

ACK_EVENTS=('transaction_entry','request_assert','ack_high','request_clear',
            'ack_low','bank_toggle','busy_clear','error_exit')
ACK_RESULTS={0:'none',1:'transaction-active',2:'ack-high',3:'request-cleared',
             4:'ack-low',5:'success',6:'error'}
def decode_e4(data):
    """Decode the 52-byte read-only codec transaction snapshot offline."""
    if len(data)!=52: raise ValueError(f'E4 response must be 52 bytes, got {len(data)}')
    magic,version,size=struct.unpack_from('<IHH',data)
    if magic!=0x4b434145 or version!=1 or size!=52:
        raise ValueError('codec diagnostic identity/version/size mismatch')
    values=struct.unpack_from('<9I8B',data,8)
    result=dict(zip(ACK_EVENTS,values[:8]))
    reg=values[8]
    selector,busy,request,ack,last_result=values[9:14]
    result.update(register_snapshot=f'0x{reg:08x}',request_bit=(reg>>22)&1,
        ack_bit=(reg>>24)&1,software_busy=busy,coefficient_bank_selector=selector,
        last_result_code=last_result,last_result=ACK_RESULTS.get(last_result,'unknown'),
        protocol=version,size=size,magic='EACK')
    if request!=result['request_bit'] or ack!=result['ack_bit']:
        raise ValueError('E4 bit snapshots disagree with register snapshot')
    result['reported_request_bit']=request; result['reported_ack_bit']=ack
    return result

PROGRESS_CHECKPOINTS=('busy_readback_branch','configuration_changed_edge',
    'configuration_equal_edge','coefficient_copy_progress',
    'before_main_register_request','before_alternate_request_clear')
def decode_e5(data):
    """Decode the 28-byte read-only pre-request progress snapshot offline."""
    if len(data)!=28: raise ValueError(f'E5 response must be 28 bytes, got {len(data)}')
    values=struct.unpack('<IHH6B7B3xI',data)
    magic,version,size=values[:3]
    if magic!=0x47525045 or version!=1 or size!=28:
        raise ValueError('progress diagnostic identity/version/size mismatch')
    counts=values[3:9]
    last,flags,copies,busy,selector,request,ack=values[9:16]
    reg=values[16]
    if last>5: raise ValueError(f'invalid last checkpoint {last}')
    if request!=((reg>>22)&1) or ack!=((reg>>24)&1):
        raise ValueError('E5 request/ack bits disagree with register snapshot')
    return dict(magic='EPRG',protocol=version,size=size,
        checkpoint_counts=dict(zip(PROGRESS_CHECKPOINTS,counts)),
        last_checkpoint=PROGRESS_CHECKPOINTS[last],last_checkpoint_id=last,
        busy_branch_taken=bool(flags&1),configuration_equal_path=bool(flags&2),
        alternate_request_clear_seen=bool(flags&4),branch_flags=flags,
        coefficient_copy_progress=copies,software_busy=busy,
        coefficient_bank_selector=selector,request_bit=request,ack_bit=ack,
        register_snapshot=f'0x{reg:08x}')

def run_usb():
    try: import usb.core
    except ImportError as exc: raise SystemExit('Install pyusb and a macOS libusb backend to use --send') from exc
    devices=list(usb.core.find(find_all=True,idVendor=0x04e8,idProduct=0xa05e) or [])
    if len(devices)!=1: raise SystemExit(f'Expected exactly one EO-IC100 04e8:a05e, found {len(devices)}')
    dev=devices[0]
    caps=bytes(dev.ctrl_transfer(*CAPS_REQ,timeout=1000))
    if caps!=CAPS: raise SystemExit('CAPS marker mismatch; E3 was not sent')
    data=bytes(dev.ctrl_transfer(*E3_REQ,timeout=1000))
    result=decode(data)
    print('CAPS_RAW='+caps.hex(' '))
    print('E3_RAW='+data.hex(' '))
    print(json.dumps(result,indent=2))

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--decode-hex',help='decode one 52-byte response without USB')
    ap.add_argument('--decode-e4-hex',help='decode one 52-byte E4 response without USB')
    ap.add_argument('--decode-e5-hex',help='decode one 28-byte E5 response without USB')
    ap.add_argument('--send',action='store_true',help='send proven CAPS then experimental read-only E3')
    ap.add_argument('--confirm-read-only-experimental-e3',action='store_true',
                    help='required explicit opt-in; no other custom request is sent')
    args=ap.parse_args()
    if args.decode_hex:
        raw=bytes.fromhex(args.decode_hex)
        print(json.dumps(decode(raw),indent=2)); return
    if args.decode_e4_hex:
        raw=bytes.fromhex(args.decode_e4_hex)
        print(json.dumps(decode_e4(raw),indent=2)); return
    if args.decode_e5_hex:
        raw=bytes.fromhex(args.decode_e5_hex)
        print(json.dumps(decode_e5(raw),indent=2)); return
    if args.send:
        if not args.confirm_read_only_experimental_e3:
            ap.error('--send also requires --confirm-read-only-experimental-e3')
        run_usb(); return
    ap.error('use --decode-hex for offline parsing or explicitly opt into --send')

if __name__=='__main__': main()

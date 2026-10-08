#!/usr/bin/env python3
"""Read-only E2 probe. Dry-run default; contains no E1 or device-transition path."""
import argparse
import json
import struct
from pathlib import Path

REQUEST=dict(bmRequestType=0xc0,bRequest=0xe2,wValue=0x454f,wIndex=0x4943,wLength=32)
EVENTS={1:'SET_SEEN',2:'SETUP_MATCHED',4:'CALLBACK_ENTERED',8:'PAYLOAD_ACCEPTED',
        16:'DSP_SETTER_CALLED',32:'SETTER_SUCCESS',64:'SETTER_ERROR',128:'ACK_TIMEOUT',
        256:'STATUS_ARMED',512:'STATUS_COMPLETE'}
OUTCOMES={0:'NO_OUTCOME',1:'SETUP_REJECTED',2:'RUNTIME_GUARD_REJECTED',
          3:'SETTER_SUCCESS',4:'SETTER_ERROR',5:'ACK_TIMEOUT',6:'PAYLOAD_REJECTED'}

def decode(payload):
    if len(payload)!=32: raise ValueError('diagnostics must be exactly 32 bytes')
    magic,protocol,size,seq,events,outcome,result,timeouts,ready=struct.unpack('<4sHH6I',payload)
    if (magic,protocol,size)!=(b'EQDG',1,32): raise ValueError('diagnostic signature mismatch')
    if events&~0x3ff or outcome not in OUTCOMES or timeouts&~3 or ready&~31:
        raise ValueError('unknown diagnostic values')
    return dict(magic='EQDG',protocol=protocol,size=size,sequence=seq,events=hex(events),
        event_names=[name for bit,name in EVENTS.items() if events&bit],
        outcome=OUTCOMES[outcome],setter_result=hex(result),timeout_mask=timeouts,
        current_readiness=hex(ready),raw=payload.hex(' '))

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--execute',action='store_true')
    p.add_argument('--confirm-diagnostic-b',action='store_true')
    p.add_argument('--evidence',type=Path)
    args=p.parse_args()
    if not args.execute:
        print(json.dumps(dict(mode='OFFLINE DRY RUN',vid='04e8',pid='a05e',request=REQUEST,
            setup_hex='c0 e2 4f 45 43 49 20 00',response_layout='<4sHH6I',
            precondition='Separately approved read-only request; diagnostic B marker independently verified'),indent=2))
        return
    if not args.confirm_diagnostic_b or not args.evidence:
        p.error('--execute requires --confirm-diagnostic-b and --evidence')
    if args.evidence.exists(): p.error('evidence path exists; refusing overwrite')
    # Imports/open only after the explicit execute gate. No configuration,
    # interface claim, driver detach, retry or OUT transfer.
    import usb.core
    import usb.util
    devices=list(usb.core.find(find_all=True,idVendor=0x04e8,idProduct=0xa05e))
    if len(devices)!=1: raise SystemExit('exactly one normal EO-IC100 required')
    dev=devices[0]
    report=dict(request=REQUEST,vid='04e8',pid='a05e',bus=dev.bus,address=dev.address)
    try:
        raw=bytes(dev.ctrl_transfer(0xc0,0xe2,0x454f,0x4943,32,timeout=1000))
        report['raw']=raw.hex(' ');report['decoded']=decode(raw)
    except Exception as error:
        report['error']=str(error)
        raise
    finally:
        args.evidence.parent.mkdir(parents=True,exist_ok=True)
        args.evidence.write_text(json.dumps(report,indent=2)+'\n')
        usb.util.dispose_resources(dev)
    print(json.dumps(report,indent=2))

if __name__=='__main__': main()

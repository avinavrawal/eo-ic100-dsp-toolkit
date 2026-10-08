#!/usr/bin/env python3
"""GET_EOIC_CAPS probe. Dry-run by default; never used during offline research."""
import argparse
import json
import struct

REQUEST=dict(bmRequestType=0xc0,bRequest=0xe0,wValue=0x454f,wIndex=0x4943,wLength=12)


def decode_caps(payload,expected_flags=0):
    if len(payload)!=12: raise ValueError('CAPS response must be exactly 12 bytes')
    magic,version,bands,flags=struct.unpack('<4sHHI',payload)
    if (magic,version,bands,flags)!=(b'EOIC',1,8,expected_flags):
        raise ValueError('unexpected CAPS signature/version/bands/variant')
    return dict(magic='EOIC',version=version,bands=bands,flags=flags)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute',action='store_true',help='Physical operation: requires separate explicit approval')
    parser.add_argument('--confirm-patched-b',action='store_true',help='Operator has independently verified the running patched B')
    parser.add_argument('--expected-flags',choices=[0,1],type=int,default=0)
    args=parser.parse_args()
    if not args.execute:
        print(json.dumps(dict(mode='OFFLINE DRY RUN',vid='04e8',pid='a05e',request=REQUEST,
            expected=dict(magic='EOIC',version=1,bands=8,flags=args.expected_flags),
            precondition='Separate approval and completely read-back-verified patched B already running'),indent=2))
        return
    if not args.confirm_patched_b: parser.error('--execute requires --confirm-patched-b')
    import usb.core
    import usb.util
    devices=list(usb.core.find(find_all=True,idVendor=0x04e8,idProduct=0xa05e))
    if len(devices)!=1: raise SystemExit('Exactly one normal EO-IC100 must be present')
    dev=devices[0]
    try:
        # No set_configuration, driver detach, OUT transfer, reboot or fallback.
        response=bytes(dev.ctrl_transfer(0xc0,0xe0,0x454f,0x4943,12,timeout=1000))
        print(json.dumps(decode_caps(response,args.expected_flags),indent=2))
    finally:
        usb.util.dispose_resources(dev)


if __name__=='__main__': main()

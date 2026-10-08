#!/usr/bin/env python3
"""Offline compact firmware byte-range diff; cache full range/hash report."""
import argparse
import json
from pathlib import Path
from custom_vendor_patch import ROOT,changed_ranges,sha


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('before',type=Path);parser.add_argument('after',type=Path)
    args=parser.parse_args();a=args.before.read_bytes();b=args.after.read_bytes()
    report=dict(before_sha256=sha(a),after_sha256=sha(b),before_length=len(a),after_length=len(b),
                ranges=[[hex(s),hex(e)] for s,e in changed_ranges(a,b)],end_convention='exclusive')
    out=ROOT/'research/cache'/('diff-'+sha(a)[:16]+'-'+sha(b)[:16]+'.json')
    out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(dict(report=str(out.relative_to(ROOT)),range_count=len(report['ranges']),
                         before_sha256=report['before_sha256'],after_sha256=report['after_sha256']),indent=2))


if __name__=='__main__':main()

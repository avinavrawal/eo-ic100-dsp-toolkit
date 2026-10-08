#!/usr/bin/env python3
"""Offline native macOS builds; performs no USB operations."""
import hashlib
import json
import shlex
import subprocess
from pathlib import Path

SOURCE=Path(__file__).resolve().parent
ROOT=SOURCE.parents[1]
OUT=ROOT/'research/cache/caps-macos'
def source_hashes():
    return {p:hashlib.sha256((SOURCE/p).read_bytes()).hexdigest() for p in ('macos_transport.c','caps_transport.c','protocol.c','sha256.h')}
def build():
    OUT.mkdir(parents=True,exist_ok=True)
    flags=shlex.split(subprocess.check_output(['pkg-config','--cflags','--libs','libusb-1.0'],text=True))
    includes=['-I'+str(Path(p[2:]).parent) for p in flags if p.startswith('-I')]
    manifest=dict(sources=source_hashes(),compiler=subprocess.check_output(['clang','--version'],text=True).splitlines()[0],binaries={})
    for name,extra in [('caps_readonly',['-DCAPS_READ_ONLY=1']),('caps_native',[]),('eq_native',['-DEQ_TUNER=1'])]:
      command=['clang','-O2','-std=c11','-D_DEFAULT_SOURCE','-Wall','-Wextra','-Werror','-Wno-unused-function',*extra,str(SOURCE/'macos_transport.c'),'-pthread',*includes,*flags,'-o',str(OUT/name)]
      subprocess.run(command,check=True)
      manifest['binaries'][name]=dict(sha256=hashlib.sha256((OUT/name).read_bytes()).hexdigest(),command=command)
    (OUT/'build.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print('MACOS_OFFLINE_BUILD_COMPLETE',OUT)
if __name__=='__main__':build()

#!/usr/bin/env python3
"""Compile the physical helper offline. This script performs no USB access."""
import json
import shlex
import subprocess
from package import CACHE, SOURCE, digest, source_hashes

if __name__ == '__main__':
    CACHE.mkdir(parents=True, exist_ok=True)
    binary = CACHE / 'caps_transport'
    flags = shlex.split(subprocess.check_output(['pkg-config', '--cflags', '--libs', 'libusb-1.0'], text=True))
    # protocol.c includes <libusb-1.0/libusb.h>; include its parent directory too.
    include_parents = ['-I' + str(__import__('pathlib').Path(f[2:]).parent) for f in flags if f.startswith('-I')]
    command = ['clang', '-O2', '-std=c11', '-D_DEFAULT_SOURCE', '-Wall', '-Wextra', '-Werror', '-Wno-unused-function',
               str(SOURCE / 'caps_transport.c'), '-pthread', *include_parents, *flags, '-o', str(binary)]
    subprocess.run(command, check=True)
    stamp = dict(sources=source_hashes(), binary_sha256=digest(binary), command=command,
                 compiler=subprocess.check_output(['clang', '--version'], text=True).splitlines()[0])
    (CACHE / 'build.json').write_text(json.dumps(stamp, indent=2) + '\n')
    print('OFFLINE_BUILD_COMPLETE; no USB operation; binary:', binary)

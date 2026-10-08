"""Strict Termux orchestration. Importing this module performs no USB operation."""
import argparse
import hashlib
import json
import re
import shlex
import shutil
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path(__file__).resolve().parent
CACHE = ROOT / 'research/cache/caps-physical'
HASHES = {
    'stock_b.bin': '2f418d3a324ec4217c32c4bf98d43c3cd07d59d81f82974f29320d399fa769f3',
    'flash-backup.bin': '6ee1089955817ac0deda01aab8eb7531f3bdd11dd1604fd8c143d6d1538eb0cd',
    'programmer3001sp.bin': '97443fb54fd75f71abbb5e3231a7f9abae26babe55c07c6b7302df0594236845',
    'caps-only.bin': 'afa5bb0570950030c7e36c3219fd93e0efc65c90f5355e02d4a3a091cb6bf356',
}
RESPONSE = bytes.fromhex('45 4f 49 43 01 00 08 00 00 00 00 00')


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(65536), b''):
            h.update(block)
    return h.hexdigest()


def source_hashes():
    return {p: digest(SOURCE / p) for p in ('caps_transport.c', 'protocol.c', 'sha256.h')}


def preflight(args):
    recorded = {}
    for line in (args.private / 'SHA256SUMS.txt').read_text().splitlines():
        match = re.fullmatch(r'([0-9a-f]{64})\s+\*?([^/\s]+)', line)
        if not match or match[2] in recorded:
            raise ValueError('invalid/duplicate recorded SHA256SUMS entry')
        recorded[match[2]] = match[1]
    if recorded.get('flash-backup.bin') != HASHES['flash-backup.bin']:
        raise ValueError('recorded backup hash differs from known original')
    for name in ('stock_b.bin', 'flash-backup.bin', 'programmer3001sp.bin'):
        if recorded.get(name) != HASHES[name] or digest(args.private / name) != HASHES[name]:
            raise ValueError(f'{name}: missing/incorrect recorded or actual hash')
    if digest(args.image) != HASHES['caps-only.bin']:
        raise ValueError('not the exact reviewed CAPS-only image')
    stamp = json.loads((args.helper.parent / 'build.json').read_text())
    if stamp['sources'] != source_hashes() or stamp['binary_sha256'] != digest(args.helper):
        raise ValueError('helper binary/source differs; rebuild offline')
    if not shutil.which('termux-usb'):
        raise ValueError('this package requires Termux + termux-usb USB FD access')
    print('LOCAL_PREFLIGHT=VERIFIED official B, CAPS-only B, programmer, recorded backup, helper')


def parse_devices(text):
    devices = json.loads(text)
    if not isinstance(devices, list) or len(devices) != len(set(devices)):
        raise ValueError('unexpected/duplicate USB list')
    if any(not isinstance(d, str) or not re.fullmatch(r'/dev/bus/usb/\d+/\d+', d) for d in devices):
        raise ValueError('unexpected USB device path')
    return devices


def invoke(args, mode, device, directory):
    command = shlex.join([str(args.helper), mode, str(args.private), str(args.image), str(directory)])
    result = subprocess.run(['termux-usb', '-r', '-e', command, device],
                            text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=1800)
    for line in result.stdout.splitlines():
        if line.startswith(('VID:PID=', 'FW=', 'CHECK=', 'CAPS_', 'BURN_INFO ')):
            print(line)
    path = directory / (mode + '.log')
    with path.open('x') as f:
        f.write(result.stdout)
    if result.returncode or f'CAPS_PHASE_OK={mode}\n' not in result.stdout or 'CAPS_ABORT=' in result.stdout:
        raise RuntimeError(f'{mode} failed: stop; do not continue or retry writes')
    return result.stdout


def find_device(args, identity, directory):
    matches = []
    listing = subprocess.run(['termux-usb', '-l'], check=True, text=True, capture_output=True, timeout=30)
    for device in parse_devices(listing.stdout):
        # Only descriptor identity, never a query to an unrelated device.
        child = directory / ('identity-' + device.replace('/', '_'))
        child.mkdir()
        output = invoke(args, 'identify', device, child)
        ids = re.findall(r'^VID:PID=([0-9a-f]{4}:[0-9a-f]{4})$', output, re.M)
        if len(ids) != 1:
            raise ValueError('USB descriptor identity ambiguous')
        if ids[0] == identity:
            matches.append(device)
    if len(matches) != 1:
        raise ValueError(f'exactly one {identity} required; found {len(matches)}')
    return matches[0]


def wait_programmer(args, directory):
    # Descriptor-only polling; no retries of any write or command.
    for i in range(20):
        check = directory / f'wait-{i}'
        check.mkdir()
        try:
            return find_device(args, 'be57:0101', check)
        except ValueError as e:
            if 'found 0' not in str(e):
                raise
        time.sleep(0.5)
    raise ValueError('be57:0101 did not appear; stop, no recovery guessed')


def receipt(path, value):
    with path.open('x') as f:
        json.dump(value, f, indent=2)
        f.write('\n')


def main(phase):
    parser = argparse.ArgumentParser(description=f'CAPS-only physical {phase}; never run without separate approval')
    parser.add_argument('--private', type=Path, default=ROOT / 'firmware/private')
    parser.add_argument('--image', type=Path, default=ROOT / 'research/cache/custom-vendor/caps-only.bin')
    parser.add_argument('--helper', type=Path, default=CACHE / 'caps_transport')
    parser.add_argument('--session', type=Path, required=True, help='ignored local evidence directory')
    if phase == 'recover':
        parser.add_argument('--from', dest='origin', choices=['normal-A', 'normal-B', 'programmer-running', 'programmer-bootstrap'], required=True)
    parser.add_argument('--confirm-patched-b', action='store_true', help='probe only: independent full-readback/activation established')
    args = parser.parse_args()
    for field in ('private', 'image', 'helper', 'session'):
        setattr(args, field, getattr(args, field).resolve())
    # Keep device readbacks/flags/logs in ignored cache, never tracked paths.
    args.session.relative_to((ROOT / 'research/cache').resolve())
    preflight(args)  # local files only; runs before any enumeration
    confirmations = {'stage': 'STAGE-CAPS-B', 'activate': 'ACTIVATE-CAPS-B', 'recover': 'RECOVER-VERIFIED-A', 'probe': 'GET-EOIC-CAPS'}
    print('This phase requires separate authorization; no automatic approval is inferred.')
    if phase == 'stage':
        print('Will query A, send FW_UPDATE/SYS_REBOOT, upload programmer, and write ONLY B. No flag change.')
    elif phase == 'activate':
        print('Requires the still-running programmer from successful staging. Writes backup and active flags; no reboot.')
    elif phase == 'recover':
        print('Verifies complete original A, writes ONLY active boot selection if needed. Normal origins include OTA/reboot.')
    else:
        if not args.confirm_patched_b:
            raise ValueError('probe requires --confirm-patched-b; version string alone is insufficient')
        print('Will send exactly one GET_EOIC_CAPS, no firmware query or OUT vendor request.')
    if input(f'Type {confirmations[phase]} exactly: ') != confirmations[phase]:
        raise ValueError('confirmation declined')
    if phase == 'stage':
        args.session.mkdir(parents=True, exist_ok=False)
    else:
        if not args.session.is_dir():
            raise ValueError('session directory does not exist')
    if phase == 'activate':
        previous = json.loads((args.session / 'stage/receipt.json').read_text())
        if previous != {'phase': 'stage', 'image_sha256': HASHES['caps-only.bin'], 'backup_sha256': HASHES['flash-backup.bin'], 'flags_sha256': digest(args.session / 'stage/flags-before.bin')}:
            raise ValueError('stage receipt differs or incomplete')
    directory = args.session / phase
    directory.mkdir(exist_ok=False)  # never overwrite a failed/successful run
    if phase == 'stage':
        normal = find_device(args, '04e8:a05e', directory)
        invoke(args, 'query-A', normal, directory)
        invoke(args, 'enter-A', normal, directory)  # re-query on same handle before transition
        programmer = wait_programmer(args, directory)
        invoke(args, 'stage-bootstrap', programmer, directory)
        receipt(directory / 'receipt.json', dict(phase='stage', image_sha256=HASHES['caps-only.bin'], backup_sha256=HASHES['flash-backup.bin'], flags_sha256=digest(directory / 'flags-before.bin')))
        print('STAGE_COMPLETE: B fully verified; A and both flags unchanged. Keep programmer connected for activation.')
    elif phase == 'activate':
        programmer = find_device(args, 'be57:0101', directory)
        invoke(args, 'activate-running', programmer, directory)
        receipt(directory / 'receipt.json', dict(phase='activate', image_sha256=HASHES['caps-only.bin']))
        print('ACTIVATION_COMPLETE: B selected and flags verified; NO software reboot. Stop here.')
    elif phase == 'recover':
        origin = args.origin
        if origin.startswith('normal-'):
            normal = find_device(args, '04e8:a05e', directory)
            invoke(args, 'enter-' + origin[-1], normal, directory)
            programmer = wait_programmer(args, directory)
            mode = 'recover-bootstrap-' + origin[-1]
        else:
            programmer = find_device(args, 'be57:0101', directory)
            mode = 'recover-running' if origin.endswith('running') else 'recover-bootstrap'
        invoke(args, mode, programmer, directory)
        receipt(directory / 'receipt.json', dict(phase='recover', target='A'))
        print('RECOVERY_COMPLETE: original A fully verified, selected; neither image or backup flag written. No final reboot.')
    else:
        if json.loads((args.session / 'activate/receipt.json').read_text()) != {'phase': 'activate', 'image_sha256': HASHES['caps-only.bin']}:
            raise ValueError('successful CAPS-only activation receipt required')
        normal = find_device(args, '04e8:a05e', directory)
        invoke(args, 'probe', normal, directory)
        print('CAPS_PROBE_COMPLETE: EOIC version=1 bands=8 flags=0')


def entry(phase):
    try:
        main(phase)
    except (OSError, ValueError, KeyError, RuntimeError, subprocess.SubprocessError) as e:
        raise SystemExit(f'ABORT: {e}. No automatic retry, activation or reboot.')

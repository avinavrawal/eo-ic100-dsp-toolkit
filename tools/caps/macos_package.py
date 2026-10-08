"""Native phase orchestration. Persistent phases require explicit confirmation."""
import argparse
import hashlib
import json
import shlex
import subprocess
import sys
from pathlib import Path
from build_macos import ROOT,OUT,source_hashes
from package import HASHES,digest
from flash_state import BASELINE_SHA,analyze

def preflight():
    private=ROOT/'firmware/private';image=ROOT/'research/cache/custom-vendor/caps-only.bin'
    entries={}
    for line in (private/'SHA256SUMS.txt').read_text().splitlines():
        h,name=line.split();
        if name in entries:raise ValueError('duplicate checksum entry')
        entries[name]=h
    for name in ('stock_b.bin','programmer3001sp.bin','flash-backup.bin'):
        if entries.get(name)!=HASHES[name] or digest(private/name)!=HASHES[name]:raise ValueError(name+' hash differs')
    if digest(image)!=HASHES['caps-only.bin']:raise ValueError('CAPS-only hash differs')
    stamp=json.loads((OUT/'build.json').read_text())
    if stamp['sources']!=source_hashes():raise ValueError('native source changed; rebuild offline')
    for name in ('caps_readonly','caps_native'):
        if digest(OUT/name)!=stamp['binaries'][name]['sha256']:raise ValueError(name+' binary differs')
    return private,image

def invoke(mode,directory,token=None,baseline=None):
    private,image=preflight()
    binary='caps_native' if token else 'caps_readonly'
    command=[str(OUT/binary),mode,str(private),str(image),str(directory)]
    if token:command.append(token)
    elif baseline:command.append(str(baseline))
    log=directory/(mode+'.log')
    with log.open('x') as f:
        f.write('USB_EXECUTION_CONTEXT=inherited from activation wrapper process; read-only preflight must pass in this process context\n')
        f.write('USB_CONTEXT_PREFIX=research/cache/caps-macos/caps_readonly (approved read-only stabilizer executable)\n')
        f.write('USB_COMMAND='+shlex.join(command)+'\n')
        result=subprocess.run(command,stdout=f,stderr=subprocess.STDOUT,timeout=1800)
    text=log.read_text()
    for line in text.splitlines():
        if line.startswith(('VID:PID=','FW=','CHECK=','CAPS_','MACOS_','NATIVE_','FLASH_','CURRENT_','PROGRAMMER_CAPTURE','BURN_INFO')):print(line)
    if result.returncode or f'MACOS_PHASE_OK={mode}\n' not in text or 'CAPS_ABORT=' in text:
        raise RuntimeError(f'{mode} failed; inspect {log}; no automatic retry/reboot')

def activation_usb_preflight(directory):
    private,image=preflight()
    command=[str(OUT/'caps_readonly'),'stable-programmer',str(private),str(image),str(directory)]
    log=directory/'usb-stabilization-preflight.log'
    with log.open('x') as f:
        f.write('USB_EXECUTION_CONTEXT=inherited from activation wrapper process\n')
        f.write('USB_CONTEXT_PREFIX=research/cache/caps-macos/caps_readonly (approved USB-capable read-only prefix)\n')
        f.write('WRAPPER_COMMAND='+shlex.join([sys.executable,*sys.argv])+'\n')
        f.write('USB_COMMAND='+shlex.join(command)+'\n')
        result=subprocess.run(command,stdout=f,stderr=subprocess.STDOUT,timeout=12)
    text=log.read_text()
    stable=[line for line in text.splitlines() if line.startswith('ENUM_STABLE=')]
    for line in text.splitlines():
        if line.startswith(('ENUM_POLL=','ENUM_USB=','ENUM_POLL_RESULT=','ENUM_STABLE=','CAPS_ABORT=','MACOS_PHASE_OK=')):
            print(line)
    if result.returncode or len(stable)!=1 or not stable[0].startswith('ENUM_STABLE=be57:0101 consecutive_polls='):
        raise RuntimeError(f'read-only programmer stabilization failed; inspect {log}; writer was not launched')
    with (directory/'activation-context.log').open('x') as f:
        f.write('WRAPPER_COMMAND='+shlex.join([sys.executable,*sys.argv])+'\n')
        f.write('USB_CONTEXT=verified in same wrapper process by approved read-only prefix research/cache/caps-macos/caps_readonly\n')
        f.write('READ_ONLY_PREFLIGHT_LOG='+str(log)+'\n')
        f.write(stable[0]+'\n')
    print('USB_EXECUTION_CONTEXT=VERIFIED_BY_READ_ONLY_PREFLIGHT')

def record(path,obj):
    with path.open('x') as f:json.dump(obj,f,indent=2);f.write('\n')

def main(phase):
    p=argparse.ArgumentParser(description='Native CAPS '+phase+'; no automatic persistent approval')
    p.add_argument('--session',type=Path,required=True)
    p.add_argument('--baseline',type=Path,help='stage: previously reviewed complete native flash capture')
    p.add_argument('--confirm-patched-b',action='store_true')
    p.add_argument('--usb-context',choices=['research/cache/caps-macos/caps_readonly'],help='required activation preflight execution context')
    if phase=='recover':p.add_argument('--from',dest='origin',choices=['programmer-running','programmer-bootstrap','normal-A','normal-B'],default='programmer-running')
    a=p.parse_args();session=a.session.resolve();session.relative_to((ROOT/'research/cache').resolve());preflight()
    if phase=='validate':
        session.mkdir(parents=True,exist_ok=False);directory=session/'validate';directory.mkdir()
        print('Authorized known OTA transition + programmer launch + full read only; persistent command guard enabled.')
        invoke('transition-read',directory)
        report=analyze((directory/'flash-current.bin').read_bytes(),(ROOT/'firmware/private/flash-backup.bin').read_bytes(),(ROOT/'firmware/private/stock_b.bin').read_bytes())
        record(directory/'comparison.json',report);print('READ_ONLY_VALIDATION_COMPLETE; no persistent command sent');return
    confirmations={'stage':'STAGE-CAPS-B','activate':'ACTIVATE-CAPS-B','recover':'RECOVER-VERIFIED-A','probe':'GET-EOIC-CAPS'}
    if phase=='stage':
        if not a.baseline or digest(a.baseline)!=BASELINE_SHA:raise ValueError('exact reviewed full native baseline required')
        session.mkdir(parents=True,exist_ok=False)
        with (session/'baseline.bin').open('xb') as f:f.write(a.baseline.read_bytes())
    elif not session.is_dir():raise ValueError('existing session required')
    if phase=='activate':
        r=json.loads((session/'stage/receipt.json').read_text())
        if r!=dict(phase='stage',image_sha256=HASHES['caps-only.bin'],baseline_sha256=BASELINE_SHA,flags_sha256=digest(session/'stage/flags-before.bin')):raise ValueError('stage receipt incomplete/different')
    if phase=='probe':
        if not a.confirm_patched_b:raise ValueError('independent patched-B verification required')
        if json.loads((session/'activate/receipt.json').read_text())!=dict(phase='activate',image_sha256=HASHES['caps-only.bin']):raise ValueError('CAPS activation receipt required')
    print('No phase is authorized by a previous read-only validation. Separate approval is required.')
    print({'stage':'Writes only CAPS B; no flag change. Requires already-running validated programmer.',
           'activate':'Writes backup and active boot flags only, after complete A/B verification. No reboot.',
           'recover':'Verifies full original A, writes active selection only if needed; normal origins include known OTA/reboot before recovery.',
           'probe':'Exactly one GET_EOIC_CAPS in normal mode; no firmware query/OUT/retry.'}[phase])
    if input('Type '+confirmations[phase]+' exactly: ')!=confirmations[phase]:raise ValueError('confirmation declined')
    if phase=='recover' and a.origin!='programmer-running':
        transport=session/'recover-transport';transport.mkdir(exist_ok=False)
        mode={'normal-A':'transition-read','normal-B':'transition-read-B','programmer-bootstrap':'read-bootstrap'}[a.origin]
        invoke(mode,transport)
    directory=session/phase;directory.mkdir(exist_ok=False)
    if phase=='activate':
        if a.usb_context!='research/cache/caps-macos/caps_readonly':
            raise ValueError('activation requires the approved read-only USB-capable execution context')
        activation_usb_preflight(directory)
    mode={'stage':'stage-running','activate':'activate-running','recover':'recover-running','probe':'probe'}[phase]
    invoke(mode,directory,token=confirmations[phase])
    if phase=='stage':record(directory/'receipt.json',dict(phase='stage',image_sha256=HASHES['caps-only.bin'],baseline_sha256=BASELINE_SHA,flags_sha256=digest(directory/'flags-before.bin')))
    elif phase=='activate':record(directory/'receipt.json',dict(phase='activate',image_sha256=HASHES['caps-only.bin']))
    else:record(directory/'receipt.json',dict(phase=phase))
    print('MACOS_'+phase.upper()+'_COMPLETE; no automatic reboot or next phase')

def entry(phase):
    try:main(phase)
    except (OSError,ValueError,KeyError,RuntimeError,subprocess.SubprocessError) as e:raise SystemExit('ABORT: '+str(e))

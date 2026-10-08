#!/usr/bin/env python3
"""Read-only device identity/version query for the macOS tuner UI."""
import argparse
import json
import subprocess
import time
from pathlib import Path

from build_macos import OUT, ROOT, source_hashes
from macos_package import digest
from tuner_package import CAPS_IMAGE, HASHES


def main():
    p = argparse.ArgumentParser()
    p.add_argument("operation", choices=("query", "wait-normal", "state"))
    p.add_argument("--private", type=Path, required=True)
    p.add_argument("--session", type=Path, required=True)
    p.add_argument("--expect-slot", choices=("A", "B"))
    p.add_argument("--timeout", type=float, default=30)
    a = p.parse_args()
    stamp = json.loads((OUT / "build.json").read_text())
    if stamp["sources"] != source_hashes() or digest(OUT / "caps_readonly") != stamp["binaries"]["caps_readonly"]["sha256"]:
        raise ValueError("read-only helper changed; rebuild before querying")
    if digest(CAPS_IMAGE) != HASHES["caps-only.bin"]:
        raise ValueError("known helper image asset failed local hash check")
    a.session.mkdir(parents=True, exist_ok=True)
    helper = OUT / "caps_readonly"
    if a.operation == "state":
        listing = subprocess.run([str(helper), "enumerate", str(a.private), str(CAPS_IMAGE), str(a.session)],
                                 text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=15)
        (a.session / "enumeration.log").write_text(listing.stdout)
        if listing.returncode:
            raise RuntimeError("read-only USB enumeration failed")
        ids = [line.split("USB_ID=", 1)[1].split()[0] for line in listing.stdout.splitlines() if line.startswith("USB_ID=")]
        normal = [v for v in ids if v == "04e8:a05e"]
        prog = [v for v in ids if v == "be57:0101"]
        if len(normal) + len(prog) != 1 or len(normal) > 1 or len(prog) > 1:
            raise ValueError("device is absent, duplicated, or has an unexpected identity")
        if normal:
            query = subprocess.run([str(helper), "identify-normal", str(a.private), str(CAPS_IMAGE), str(a.session)],
                                   text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=20)
            (a.session / "normal-query.log").write_text(query.stdout)
            if query.returncode or "CHECK=1.1" not in query.stdout:
                raise RuntimeError("normal device query failed")
            print("STATE=NORMAL\n" + "\n".join(line for line in query.stdout.splitlines()
                  if line.startswith(("FW=", "ACTIVE_SLOT=", "CHECK="))))
        else:
            stable = subprocess.run([str(helper), "stable-programmer", str(a.private), str(CAPS_IMAGE), str(a.session)],
                                    text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=12)
            (a.session / "stable-programmer.log").write_text(stable.stdout)
            if stable.returncode or "ENUM_STABLE=be57:0101" not in stable.stdout:
                raise RuntimeError("programmer identity did not stabilize")
            print("STATE=PROGRAMMER\nVID:PID=be57:0101")
        return
    deadline = time.monotonic() + (a.timeout if a.operation == "wait-normal" else 0)
    poll_log = a.session / "enumeration.log"
    while True:
        listing = subprocess.run([str(helper), "enumerate", str(a.private), str(CAPS_IMAGE), str(a.session)],
                                 text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=15)
        with poll_log.open("a") as stream:
            stream.write(f"POLL_MONOTONIC={time.monotonic():.3f}\n{listing.stdout}\n")
        if listing.returncode:
            raise RuntimeError("USB enumeration failed; see enumeration.log")
        identities = [line.split("USB_ID=", 1)[1].split()[0] for line in listing.stdout.splitlines() if line.startswith("USB_ID=")]
        matches = [identity for identity in identities if identity == "04e8:a05e"]
        if len(matches) > 1:
            raise ValueError(f"multiple EO-IC100 identities are visible ({len(matches)}); refusing ambiguity")
        if len(matches) == 1:
            break
        if a.operation == "query" or time.monotonic() >= deadline:
            raise ValueError(f"expected exactly one EO-IC100 04e8:a05e; found {len(matches)}")
        time.sleep(0.4)
    query = subprocess.run([str(helper), "normal-read-any", str(a.private), str(CAPS_IMAGE), str(a.session)],
                           text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=20)
    (a.session / "normal-query.log").write_text(query.stdout)
    if query.returncode or "CHECK=1.1" not in query.stdout or "AUDIO_INTERFACE=YES" not in query.stdout or "HID_INTERFACE=YES" not in query.stdout:
        raise RuntimeError("QUERY_SW_VER/CHECK failed; see normal-query.log")
    values = [line for line in query.stdout.splitlines() if line.startswith(("FW=", "ACTIVE_SLOT=", "CHECK="))]
    if "ACTIVE_SLOT=UNKNOWN" in query.stdout:
        raise ValueError("running firmware suffix is not a known A/B image")
    if a.expect_slot and f"ACTIVE_SLOT={a.expect_slot} " not in query.stdout:
        raise ValueError(f"normal mode returned the wrong firmware suffix; expected slot {a.expect_slot}")
    print("USB=04e8:a05e")
    print("\n".join(values))
    print("AUDIO_INTERFACE=YES")
    print("HID_INTERFACE=YES")
    print("NOTE=slot is inferred from the known Samsung firmware suffix")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError, RuntimeError, subprocess.SubprocessError) as exc:
        raise SystemExit("READ_ONLY_ABORT: " + str(exc))

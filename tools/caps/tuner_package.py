#!/usr/bin/env python3
"""Safety-gated macOS phase runner for the EOIC100 DSP Tuner UI."""
import argparse
import hashlib
import json
import shlex
import subprocess
import sys
from pathlib import Path

from build_macos import OUT, ROOT, source_hashes
from macos_package import HASHES, digest

PRIVATE_DEFAULT = ROOT / "firmware/private"
CAPS_IMAGE = ROOT / "research/cache/custom-vendor/caps-only.bin"
TOKENS = {"stage": "STAGE-EQ-B", "activate": "ACTIVATE-EQ-B", "recover": "RECOVER-VERIFIED-A"}
HASHES["stock_a.bin"] = "9ebc51140b17884a9b3fe97edc58f8b3861ec10dbc0a33499ea31200bdedba87"


def preflight(private: Path, image: Path):
    expected = {
        "stock_a.bin": HASHES["stock_a.bin"],
        "stock_b.bin": HASHES["stock_b.bin"],
        "flash-backup.bin": HASHES["flash-backup.bin"],
        "programmer3001sp.bin": HASHES["programmer3001sp.bin"],
    }
    records = {}
    for line in (private / "SHA256SUMS.txt").read_text().splitlines():
        h, name = line.split()
        if name in records:
            raise ValueError("duplicate private asset checksum")
        records[name] = h
    for name, h in expected.items():
        if records.get(name) != h or digest(private / name) != h:
            raise ValueError(f"{name}: recorded/actual SHA-256 differs")
    manifest_path = image.with_suffix(image.suffix + ".json")
    manifest = json.loads(manifest_path.read_text())
    if (manifest.get("format") != "eoic100-eq-b-image-v1" or
            Path(manifest.get("output", "")).resolve() != image.resolve() or
            manifest.get("output_sha256") != digest(image) or manifest.get("slot") != "B" or
            manifest.get("slot_address") != "0x3c02e000" or manifest.get("image_size") != 0x20004):
        raise ValueError("generated EQ image does not match its B-image manifest")
    if manifest.get("input_sha256") != HASHES["stock_b.bin"]:
        raise ValueError("image was not generated from official Samsung 0.23 B")
    stamp = json.loads((OUT / "build.json").read_text())
    if stamp["sources"] != source_hashes():
        raise ValueError("native source changed; rebuild offline before using tuner")
    for binary in ("caps_readonly", "eq_native"):
        if digest(OUT / binary) != stamp["binaries"][binary]["sha256"]:
            raise ValueError(f"{binary} does not match its local build manifest")
    return manifest


def call(binary: str, args, log: Path, expected_marker: str, timeout=1800):
    command = [str(binary), *map(str, args)]
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("x") as stream:
        stream.write("COMMAND=" + shlex.join(command) + "\n")
        result = subprocess.run(command, stdout=stream, stderr=subprocess.STDOUT, timeout=timeout)
    text = log.read_text()
    if result.returncode or expected_marker not in text or "CAPS_ABORT=" in text:
        raise RuntimeError(f"native phase failed; inspect {log}; no automatic retry")
    return text


def verify_prepared_flash(private: Path, phase_dir: Path):
    flash = (phase_dir / "flash-current.bin").read_bytes()
    authority = (private / "flash-backup.bin").read_bytes()
    if len(flash) != 0x80000 or len(authority) != 0x80000:
        raise ValueError("full 512 KiB flash capture or authority backup is missing")
    if flash[0x6000:0x2e000] != authority[0x6000:0x2e000]:
        raise ValueError("actual recovery slot A differs from the preserved complete backup")
    active = flash[0x4000:0x5000]
    if not (active[:8] == b"A" * 8 or active == authority[0x4000:0x5000]):
        raise ValueError("active boot flag does not select A")
    if active != authority[0x4000:0x5000] and active[8:] != b"\xff" * 4088:
        raise ValueError("active boot-flag sector is not canonical")
    backup = flash[0x5000:0x6000]
    if not (backup == authority[0x5000:0x6000] or backup[:8] in (b"A" * 8, b"B" * 8, b"\xff" * 8) and backup[8:] == b"\xff" * 4088):
        raise ValueError("backup boot-flag sector is unexpected")
    b = flash[0x2e000:0x4e000]
    if b[:4] != bytes.fromhex("1c ec 57 be") or int.from_bytes(b[12:16], "little") != 0x3c04cc8c:
        raise ValueError("inactive B slot validity marker/header differs")
    return {"flash_sha256": digest(phase_dir / "flash-current.bin"),
            "a_sha256": digest_bytes(flash[0x6000:0x2e000]),
            "flags_sha256": digest_bytes(flash[0x4000:0x6000]),
            "active": "A", "b_valid": True}


def digest_bytes(value: bytes):
    return hashlib.sha256(value).hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("phase", choices=("check", "prepare-stage", "stage", "activate", "recover"))
    ap.add_argument("--image", type=Path, required=True)
    ap.add_argument("--session", type=Path, required=True)
    ap.add_argument("--private", type=Path, default=PRIVATE_DEFAULT)
    ap.add_argument("--confirm")
    ap.add_argument("--origin", choices=("normal-B", "programmer"), default="normal-B")
    a = ap.parse_args()
    session = a.session.resolve()
    session.relative_to((ROOT / "research/cache").resolve())
    manifest = preflight(a.private, a.image)
    h = manifest["output_sha256"]
    if a.phase == "check":
        print(f"TUNER_PREFLIGHT=PASS image_sha256={h} stock_A=VERIFIED_LOCAL")
        return
    if a.phase == "prepare-stage":
        phase_dir = session / "prepare"
        if phase_dir.exists():
            raise ValueError("preparation already exists; inspect its receipt before continuing")
        phase_dir.mkdir(parents=True)
        call(OUT / "caps_readonly", ["transition-read", a.private, CAPS_IMAGE, phase_dir],
             phase_dir / "transition.log", "NATIVE_FULL_FLASH_READ=VERIFIED", timeout=600)
        captured = verify_prepared_flash(a.private, phase_dir)
        captured.update({"phase": "prepare-stage", "image_sha256": h})
        (phase_dir / "receipt.json").write_text(json.dumps(captured, indent=2) + "\n")
        print(f"TUNER_PREPARE_STAGE_COMPLETE active=A flash_sha256={captured['flash_sha256']}")
        return
    if a.confirm != TOKENS[a.phase]:
        raise ValueError("explicit GUI phase confirmation is required")
    if a.phase == "stage":
        prepared = json.loads((session / "prepare/receipt.json").read_text())
        if prepared.get("phase") != "prepare-stage" or prepared.get("image_sha256") != h or prepared.get("active") != "A":
            raise ValueError("verified recovery-A programmer preflight is required before staging")
        phase_dir = session / "stage"
        if phase_dir.exists():
            raise ValueError("stage phase already exists; inspect receipts and device state; refusing a retry")
        phase_dir.mkdir(parents=True)
        # prepare-stage deliberately leaves the device in programmer mode.
        # Re-entering from the staging phase would send FW_UPDATE a second time
        # and fail (or risk an unintended transition); the native writer opens
        # only the verified programmer identity and compares the complete live
        # flash against the saved preflight capture before erasing anything.
        call(OUT / "eq_native", ["stage-running", a.private, a.image, phase_dir,
                                 TOKENS["stage"], h], phase_dir / "stage.log",
             "MACOS_PHASE_OK=stage-running")
        receipt = {"phase": "stage", "image_sha256": h,
                   "input_sha256": manifest["input_sha256"],
                   "flash_before_sha256": digest(phase_dir / "flash-backup-before-stage.bin"),
                   "full_readback": True, "outside_B_unchanged": True}
        (phase_dir / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    elif a.phase == "activate":
        receipt_path = session / "stage/receipt.json"
        receipt = json.loads(receipt_path.read_text())
        if receipt.get("image_sha256") != h or receipt.get("full_readback") is not True:
            raise ValueError("complete matching staged-B receipt is required")
        phase_dir = session / "activate"
        if phase_dir.exists():
            raise ValueError("activation phase already exists; inspect boot flags; refusing a retry")
        phase_dir.mkdir()
        # Run the exact approved descriptor-only stability check before opening
        # the writer; the native phase then repeats A/B/flag verification.
        call(OUT / "caps_readonly", ["stable-programmer", a.private, CAPS_IMAGE, phase_dir],
             phase_dir / "usb-stabilization.log", "ENUM_STABLE=be57:0101", timeout=12)
        call(OUT / "eq_native", ["activate-running", a.private, a.image, phase_dir,
                                 TOKENS["activate"], h], phase_dir / "activate.log",
             "CAPS_BOOT_SELECTION=B VERIFIED")
        (phase_dir / "receipt.json").write_text(json.dumps(
            {"phase": "activate", "image_sha256": h, "active": "B", "backup": "A"}, indent=2) + "\n")
    else:
        phase_dir = session / "recover"
        if phase_dir.exists():
            raise ValueError("recovery phase already exists; inspect boot flags; refusing a retry")
        phase_dir.mkdir()
        if a.origin == "normal-B":
            transition = phase_dir / "programmer-entry"
            transition.mkdir()
            call(OUT / "caps_readonly", ["transition-read-B", a.private, CAPS_IMAGE, transition],
                 transition / "transition.log", "NATIVE_FULL_FLASH_READ=VERIFIED", timeout=600)
        native_mode = "recover-B-running" if a.origin == "normal-B" else "recover-running"
        call(OUT / "eq_native", [native_mode, a.private, a.image, phase_dir,
                                 TOKENS["recover"], h], phase_dir / "recover.log",
             "CAPS_SOFTWARE_REBOOT_SENT=NO")
        (phase_dir / "receipt.json").write_text(json.dumps({"phase": "recover", "target": "A"}, indent=2) + "\n")
    print(f"TUNER_{a.phase.upper()}_COMPLETE image_sha256={h}")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError, RuntimeError, subprocess.SubprocessError) as exc:
        raise SystemExit("ABORT: " + str(exc))

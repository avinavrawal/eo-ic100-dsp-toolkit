#!/usr/bin/env python3
"""Hash-locked Ghidra headless import/map/export for the two EO-IC100 images."""
import argparse
import hashlib
import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
GHIDRA_HOME = Path.home() / "Applications/ghidra_12.1.4_PUBLIC"
JAVA_HOME = Path.home() / "Library/Java/JavaVirtualMachines/temurin-21.jdk/Contents/Home"
SCRIPT_DIR = Path(__file__).resolve().parent
PROFILES = {
    "official023": {
        "image": "firmware/private/stock_a.bin",
        "sha256": "9ebc51140b17884a9b3fe97edc58f8b3861ec10dbc0a33499ea31200bdedba87",
        "flash_base": 0x3C006000,
        "segments": [(0x8A34, 0x11E68, 0x20000140), (0x11EB0, 0x1E7BC, 0x200095D8), (0x1EBEC, 0x1EC8C, 0x20015EE8)],
        "startup_seed_offsets": [0x10, 0x58, 0xEC, 0x4A8, 0x510],
        "extra_seeds": [
            (0x20AA20, "usb_audio_app_loop"), (0x20D1C8, "usb_audio_cmd_handler"),
            (0x20A868, "codec_enable"), (0x20A994, "codec_lifecycle_setup"),
            (0x20C840, "usb_audio_open_eq"), (0x20C800, "usb_audio_set_eq"),
            (0x20D54C, "queue_push"), (0x20D5B4, "queue_pop"),
            (0x21229E, "af_thread"),
        ],
    },
    "original004": {
        "image": "firmware/private/flash-backup.bin",
        "sha256": "6ee1089955817ac0deda01aab8eb7531f3bdd11dd1604fd8c143d6d1538eb0cd",
        "flash_base": 0x3C000000,
        "segments": [(0xEC5C, 0x19214, 0x20000140), (0x1925C, 0x25F04, 0x2000A75C), (0x262FC, 0x26394, 0x20017408)],
        "startup_seed_offsets": [0x6010, 0x6058, 0x6098, 0x60E4],
        "extra_seeds": [(0x00200140, "original_application_copy_entry")],
    },
}


def sha256(path):
    h = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", choices=(*PROFILES, "all"), default="all")
    parser.add_argument("--ghidra-home", type=Path, default=GHIDRA_HOME)
    parser.add_argument("--java-home", type=Path, default=JAVA_HOME)
    args = parser.parse_args()
    analyze_headless = args.ghidra_home / "support/analyzeHeadless"
    if not analyze_headless.is_file() or not (args.java_home / "bin/java").is_file():
        raise SystemExit("Ghidra or Java 21 is missing; see installation instructions in research log.")
    selected = PROFILES if args.profile == "all" else {args.profile: PROFILES[args.profile]}
    cache_root = ROOT / "research/cache/ghidra-runtime-eq"
    cache_root.mkdir(parents=True, exist_ok=True)
    audit_root = ROOT / "research/cache/runtime-eq-official023-9ebc51140b17884a"
    old_audit_root = ROOT / "research/cache/runtime-eq-original004-6ee1089955817ac0"

    for profile_name, profile in selected.items():
        image = ROOT / profile["image"]
        actual_hash = sha256(image)
        if actual_hash != profile["sha256"]:
            raise SystemExit(f"hash mismatch for {image}: {actual_hash}")
        audit_file = (audit_root if profile_name == "official023" else old_audit_root) / "audit.json"
        audit = json.loads(audit_file.read_text())
        startup_offsets = profile["startup_seed_offsets"]
        seeds = [(profile["flash_base"] + startup_offsets[0], "reset_copy_startup")]
        seeds.extend((profile["flash_base"] + offset, "startup_%04x" % offset)
                     for offset in startup_offsets[1:])
        for name, entry in audit["functions"].items():
            if name in {"set_eq", "open_eq", "set_cfg", "get_iir", "set_iir"}:
                seeds.append((int(entry["code_alias"], 16), name))
        seeds.extend(profile["extra_seeds"])
        # Stable de-duplication keeps exported seed order reproducible.
        seeds = list(dict(((address, name), None) for address, name in seeds))
        segments = ",".join(f"{a:#x}:{b:#x}:{c:#x}" for a, b, c in profile["segments"])
        seed_arg = ",".join(f"{address:#x}:{name}" for address, name in seeds)
        targets = {
            "official023": [0x20015BEC, 0x20015C78, 0x200162C0, 0x200162B4, 0x20015FA4, 0x403000E0],
            "original004": [0x20017100, 0x2001718C, 0x200177CC, 0x403000E0],
        }[profile_name]
        target_arg = ",".join(f"{target:#x}" for target in targets)
        out_dir = cache_root / profile_name
        out_dir.mkdir(parents=True, exist_ok=True)
        project_dir = out_dir / "project"
        project_dir.mkdir(parents=True, exist_ok=True)
        report_path = out_dir / "mapped-targeted-export.txt"
        log_path = out_dir / "headless.log"
        command = [
            str(analyze_headless), str(project_dir), "EOIC_" + profile_name,
            "-import", str(image), "-processor", "ARM:LE:32:v7",
            "-loader", "BinaryLoader", "-loader-baseAddr", hex(profile["flash_base"]),
            "-noanalysis", "-overwrite", "-scriptPath", str(SCRIPT_DIR),
            "-postScript", "EoicMapAndExport.java", hex(profile["flash_base"]),
            hex(0x20000000), hex(0x00200000), segments, seed_arg, str(report_path), target_arg,
        ]
        env = os.environ.copy()
        env["JAVA_HOME"] = str(args.java_home)
        env["PATH"] = str(args.java_home / "bin") + os.pathsep + env.get("PATH", "")
        print(f"RUN {profile_name} sha256={actual_hash}", flush=True)
        with log_path.open("w") as log:
            result = subprocess.run(command, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
        if result.returncode:
            tail = "\n".join(log_path.read_text(errors="replace").splitlines()[-35:])
            raise SystemExit(f"Ghidra failed for {profile_name}; see {log_path}\n{tail}")
        print(f"PASS {profile_name} report={report_path}", flush=True)


if __name__ == "__main__":
    main()

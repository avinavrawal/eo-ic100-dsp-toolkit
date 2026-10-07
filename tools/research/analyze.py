#!/usr/bin/env python3
"""Offline cached analysis; stdout contains only a bounded summary and paths."""
import argparse
import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / "research/cache"
VERSION = 1


def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="mode", required=True)
    strings = sub.add_parser("strings")
    strings.add_argument("input", type=Path)
    strings.add_argument("--min-length", type=int, default=6)
    diff = sub.add_parser("diff")
    diff.add_argument("input", type=Path)
    diff.add_argument("other", type=Path)
    summary = sub.add_parser("summary")
    summary.add_argument("input", type=Path)
    summary.add_argument("--pattern", default="verified|failed|error|FW=|CHECK=|complete")
    summary.add_argument("--limit", type=int, default=20)
    r2 = sub.add_parser("r2")
    r2.add_argument("input", type=Path)
    r2.add_argument("--commands", required=True, help="Explicit analysis/query commands, e.g. isj;izj")
    r2.add_argument("--arch", default="arm")
    r2.add_argument("--bits", type=int, default=16)
    r2.add_argument("--base", default="0")
    args = parser.parse_args()
    if getattr(args, "min_length", 1) < 1 or getattr(args, "limit", 1) < 1:
        parser.error("length and limit must be positive")
    settings = vars(args).copy()
    inputs = []
    for key in ("input", "other"):
        if key in settings:
            path = settings[key].resolve(strict=True)
            inputs.append({"path": str(path), "sha256": digest(path), "size": path.stat().st_size})
            settings[key] = str(path)
    settings["tool_version"] = VERSION
    if args.mode == "r2":
        if not shutil.which("r2"):
            parser.error("radare2 is not installed")
        settings["r2_version"] = subprocess.check_output(["r2", "-v"], text=True).strip()
    identity = {"inputs": inputs, "settings": settings}
    key = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()[:24]
    folder = CACHE / (args.mode + "-" + key)
    report = folder / "summary.json"
    if report.exists():
        print("Reused:", report)
        print(report.read_text(), end="")
        return
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "metadata.json").write_text(json.dumps(identity, indent=2) + "\n")
    result = {"mode": args.mode, "cache": str(folder)}
    if args.mode == "strings":
        # mmap lets regex scan binary data without copying the entire image.
        import mmap
        count = 0
        with args.input.open("rb") as stream, (folder / "strings.tsv").open("w") as out:
            if args.input.stat().st_size:
                with mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as data:
                    for match in re.finditer(rb"[ -~]{%d,}" % args.min_length, data):
                        out.write(f"0x{match.start():08x}\t{match.group().decode('ascii')}\n")
                        count += 1
        result.update(strings=count, index="strings.tsv", encoding="printable ASCII only")
    elif args.mode == "diff":
        changed = ranges = offset = 0
        start = None
        sample = []
        with args.input.open("rb") as left, args.other.open("rb") as right, (folder / "ranges.tsv").open("w") as out:
            while True:
                a, b = left.read(65536), right.read(65536)
                if not a and not b:
                    break
                for i in range(max(len(a), len(b))):
                    differs = i >= len(a) or i >= len(b) or a[i] != b[i]
                    if differs:
                        changed += 1
                        if start is None:
                            start = offset + i
                    elif start is not None:
                        end = offset + i
                        out.write(f"0x{start:x}\t0x{end:x}\t{end-start}\n")
                        ranges += 1
                        if len(sample) < 10:
                            sample.append([start, end])
                        start = None
                offset += max(len(a), len(b))
            if start is not None:
                out.write(f"0x{start:x}\t0x{offset:x}\t{offset-start}\n")
                ranges += 1
                if len(sample) < 10:
                    sample.append([start, offset])
        result.update(changed_bytes=changed, ranges=ranges, first_ranges=sample, range_end="exclusive", index="ranges.tsv")
    elif args.mode == "summary":
        pattern = re.compile(args.pattern, re.IGNORECASE)
        total = hits = 0
        sample = []
        with args.input.open(errors="replace") as stream, (folder / "matches.txt").open("w") as out:
            for total, line in enumerate(stream, 1):
                if pattern.search(line):
                    hits += 1
                    out.write(f"{total}: {line}")
                    if len(sample) < args.limit:
                        sample.append({"line": total, "text": line.rstrip()[:240]})
        result.update(lines=total, matches=hits, sample=sample, truncated=hits > len(sample), index="matches.txt", max_sample_characters=240)
    else:
        command = ["r2", "-q", "-a", args.arch, "-b", str(args.bits), "-m", args.base, "-c", args.commands, str(args.input.resolve())]
        with (folder / "output.txt").open("w") as out, (folder / "stderr.txt").open("w") as err:
            run = subprocess.run(command, stdout=out, stderr=err)
        if run.returncode:
            raise SystemExit(f"radare2 failed ({run.returncode}); inspect {folder}/stderr.txt")
        result.update(output="output.txt", output_bytes=(folder / "output.txt").stat().st_size, command=command)
    report.write_text(json.dumps(result, indent=2) + "\n")
    print("Created:", report)
    print(report.read_text(), end="")


if __name__ == "__main__":
    main()

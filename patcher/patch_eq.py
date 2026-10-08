#!/usr/bin/env python3
import argparse
import hashlib
import json
import struct
from pathlib import Path

EQ_OFFSET = 0x1E4C4
SLOT_CAPACITY = 8

KNOWN = {
    "a": {
        "stock": "9ebc51140b17884a9b3fe97edc58f8b3861ec10dbc0a33499ea31200bdedba87",
        "diamond8": "e1c4df83d197a7071b731256f6d6868083dc3de5ad0ec74996f0790423f38610",
    },
    "b": {
        "stock": "2f418d3a324ec4217c32c4bf98d43c3cd07d59d81f82974f29320d399fa769f3",
        "diamond8": "a624d5771bfcefc68c40d77a745fbf82d8a60864f7f9d4bfddf29bdba95c1cc0",
    },
}

def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def load_preset(path: Path):
    obj = json.loads(path.read_text())
    filters = obj["filters"]
    if not (1 <= len(filters) <= SLOT_CAPACITY):
        raise SystemExit(f"preset must contain 1..{SLOT_CAPACITY} filters")
    return obj

def patch_image(data: bytes, preset) -> bytes:
    b = bytearray(data)
    need = EQ_OFFSET + 12 + SLOT_CAPACITY * 16
    if len(b) < need:
        raise SystemExit("image is too small for the known EQ table")

    gain = float(preset["global_gain_db"])
    filters = preset["filters"]

    # header: L gain, R gain, filter count
    b[EQ_OFFSET:EQ_OFFSET+12] = struct.pack("<ffI", gain, gain, len(filters))

    off = EQ_OFFSET + 12
    for i in range(SLOT_CAPACITY):
        if i < len(filters):
            f = filters[i]
            rec = struct.pack(
                "<Ifff",
                int(f["type"]),
                float(f["gain_db"]),
                float(f["frequency_hz"]),
                float(f["q"]),
            )
        else:
            rec = b"\x00" * 16
        b[off+i*16:off+(i+1)*16] = rec

    return bytes(b)

def process(src: Path, slot: str, preset, out: Path, allow_unknown: bool):
    raw = src.read_bytes()
    h = sha256(raw)
    expected = KNOWN[slot]["stock"]
    if h != expected and not allow_unknown:
        raise SystemExit(
            f"{src}: SHA-256 does not match the tested Samsung 0.23 slot-{slot.upper()} image\n"
            f"got      {h}\nexpected {expected}\n"
            "Use --allow-unknown only for research after independently checking the layout."
        )

    patched = patch_image(raw, preset)
    out.write_bytes(patched)
    ph = sha256(patched)

    print(f"{slot.upper()}: {src}")
    print(f"  input  sha256 {h}")
    print(f"  output {out}")
    print(f"  output sha256 {ph}")

    if preset.get("name","").lower().startswith("diamond8") and h == expected:
        want = KNOWN[slot]["diamond8"]
        if ph != want:
            raise SystemExit(
                f"generated hash differs from the known tested Diamond8 image:\n"
                f"got      {ph}\nexpected {want}"
            )
        print("  verified against known tested Diamond8 hash")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("stock_a", type=Path)
    ap.add_argument("stock_b", type=Path)
    ap.add_argument("--preset", type=Path, required=True)
    ap.add_argument("--out-dir", type=Path, default=Path("patched"))
    ap.add_argument("--allow-unknown", action="store_true")
    args = ap.parse_args()

    preset = load_preset(args.preset)
    args.out_dir.mkdir(parents=True, exist_ok=True)

    process(args.stock_a, "a", preset, args.out_dir/"diamond_a.bin", args.allow_unknown)
    process(args.stock_b, "b", preset, args.out_dir/"diamond_b.bin", args.allow_unknown)

if __name__ == "__main__":
    main()

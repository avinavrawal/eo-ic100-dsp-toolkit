#!/usr/bin/env python3
"""Offline EQ image generation and validation for EOIC100 DSP Tuner."""
import argparse
import hashlib
import json
import math
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from patcher.patch_eq import EQ_OFFSET, KNOWN, patch_image

B_START = 0x3C02E000
IMAGE_SIZE = 0x20004


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def validate_preset(preset):
    gain = float(preset["global_gain_db"])
    filters = preset["filters"]
    if not math.isfinite(gain) or not -24.0 <= gain <= 12.0:
        raise ValueError("global preamp must be finite and between -24 and +12 dB")
    if len(filters) != 8:
        raise ValueError("exactly eight EQ bands are required")
    for i, band in enumerate(filters, 1):
        typ = int(band["type"])
        freq, amount, q = (float(band[k]) for k in ("frequency_hz", "gain_db", "q"))
        if typ not in range(5):
            raise ValueError(f"band {i}: unsupported filter type")
        if not math.isfinite(freq) or not 20 <= freq <= 20000:
            raise ValueError(f"band {i}: frequency must be 20..20000 Hz")
        if not math.isfinite(amount) or not -18 <= amount <= 18:
            raise ValueError(f"band {i}: gain must be -18..+18 dB")
        if not math.isfinite(q) or not 0.1 <= q <= 10:
            raise ValueError(f"band {i}: Q must be 0.1..10")


def build_image(stock_b: Path, preset_path: Path, out: Path):
    raw = stock_b.read_bytes()
    source_hash = digest(raw)
    if source_hash != KNOWN["b"]["stock"]:
        raise ValueError("official Samsung 0.23 slot-B image hash mismatch")
    if len(raw) != 0x1EDC8 or raw[:4] != b"\xff" * 4 or struct.unpack_from("<I", raw, len(raw) - 4)[0] != B_START:
        raise ValueError("official slot-B image header/footer differs from the known container")
    preset = json.loads(preset_path.read_text())
    validate_preset(preset)
    patched = patch_image(raw, preset)
    if preset.get("name", "").lower().startswith("diamond8") and digest(patched) != KNOWN["b"]["diamond8"]:
        raise ValueError("Diamond8 coefficient image differs from the known tested slot-B patch")
    # The native Samsung stage protocol takes a 0x20004 container: a four-byte
    # placeholder for the validity marker, the complete 128 KiB slot body, and
    # the slot address footer. Preserve the official image's in-place offsets.
    image = bytearray(b"\xff" * IMAGE_SIZE)
    image[:len(patched) - 4] = patched[:-4]
    image[-4:] = struct.pack("<I", B_START)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(image)
    report = {
        "format": "eoic100-eq-b-image-v1",
        "input": str(stock_b), "input_sha256": source_hash,
        "output": str(out), "output_sha256": digest(image),
        "preset": str(preset_path), "preset_sha256": digest(preset_path.read_bytes()),
        "slot": "B", "slot_address": f"0x{B_START:08x}",
        "image_size": len(image), "eq_table_offset": f"0x{EQ_OFFSET:x}",
        "changed_firmware_range": [f"0x{EQ_OFFSET:x}", f"0x{EQ_OFFSET + 12 + 8 * 16:x}"],
        "container_note": "4-byte validity placeholder + 128 KiB flash body + 4-byte B address footer",
    }
    report_path = out.with_suffix(out.suffix + ".json")
    report_path.write_text(json.dumps(report, indent=2) + "\n")
    return report


def main():
    p = argparse.ArgumentParser()
    p.add_argument("stock_b", type=Path)
    p.add_argument("preset", type=Path)
    p.add_argument("output", type=Path)
    a = p.parse_args()
    print(json.dumps(build_image(a.stock_b, a.preset, a.output), indent=2))


if __name__ == "__main__":
    main()

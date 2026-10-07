#!/usr/bin/env python3
"""Reconstruct initialized RAM from documented startup copy loops, offline only."""
import hashlib
import json
import struct
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PROFILES = {
    "official023": {"file": "stock_a.bin", "sha256": "9ebc51140b17884a9b3fe97edc58f8b3861ec10dbc0a33499ea31200bdedba87", "flash_base": 0x3c006000,
                    "segments": [(0x8a34, 0x11e68, 0x20000140), (0x11eb0, 0x1e7bc, 0x200095d8), (0x1ebec, 0x1ec8c, 0x20015ee8)]},
    "original004": {"file": "flash-backup.bin", "sha256": "6ee1089955817ac0deda01aab8eb7531f3bdd11dd1604fd8c143d6d1538eb0cd", "flash_base": 0x3c000000,
                    "segments": [(0xec5c, 0x19214, 0x20000140), (0x1925c, 0x25f04, 0x2000a75c), (0x262fc, 0x26394, 0x20017408)]},
}
TARGET = ("usb_audio_set_eq", "usb_audio_open_eq", "audio_eq_set_cfg", "hw_codec_iir_get_cfg", "hw_codec_iir_set_cfg", "cfg_hw_aud_eq_band_settings", "QUERY_SW_VER", "PING_THROUGH_VENDOR", "UAUD VENDOR", "audio_eq_type", "uaud_setuprecv")


def main():
    for name, profile in PROFILES.items():
        path = ROOT / "firmware/private" / profile["file"]
        data = path.read_bytes()
        sha = hashlib.sha256(data).hexdigest()
        assert sha == profile["sha256"], "Unexpected input: " + str(path)
        out = ROOT / "research/cache" / ("runtime-eq-" + name + "-" + sha[:16])
        out.mkdir(parents=True, exist_ok=True)
        ram = bytearray(0x20000)
        for start, end, destination in profile["segments"]:
            ram[destination-0x20000000:destination-0x20000000+end-start] = data[start:end]
        image = out / "initialized-ram.bin"
        if not image.exists() or image.read_bytes() != ram:
            image.write_bytes(ram)
        strings = []
        for target in TARGET:
            pos = ram.find(target.encode())
            while pos >= 0:
                end = ram.find(b"\0", pos)
                text = ram[pos:end].decode("ascii", "replace")
                address = 0x20000000 + pos
                refs = []
                needle = struct.pack("<I", address)
                at = ram.find(needle)
                while at >= 0:
                    refs.append(hex(0x20000000+at))
                    at = ram.find(needle, at+1)
                strings.append({"string": text, "address": hex(address), "pointer_locations": refs})
                pos = ram.find(target.encode(), pos+1)
        manifest = {"profile": name, "source": str(path), "sha256": sha, "ram_base": "0x20000000", "code_alias_base": "0x00200000", "segments": profile["segments"], "strings": strings,
                    "scope": "Initialized RAM reconstruction; excludes BSS runtime state, peripherals, flash-only code and live modifications."}
        (out / "mapping.json").write_text(json.dumps(manifest, indent=2)+"\n")
        print(name, out)
        for item in strings:
            print(item["address"], item["string"], item["pointer_locations"])


if __name__ == "__main__":
    main()

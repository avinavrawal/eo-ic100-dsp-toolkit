#!/usr/bin/env python3
"""Summarize cached 0.23 task/event/USB-audio command-dispatch evidence.

No USB I/O. Reads the hash-locked initialized-RAM cache and existing xrefs;
writes only an ignored JSON report under research/cache.
"""
import hashlib
import json
import struct
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / "research/cache/custom-vendor"
OUT = CACHE / "codec-queue-runtime-audit.json"
RAM = CACHE / "original-b-ram.bin"
RAM_BASE = 0x200000
APP = 0x20AA20
EVENT_WORD = 0x20019A0C
TABLE = 0x20D20A
TABLE_COUNT = 0x15


def main():
    manifest = json.loads((CACHE / "analysis-manifest.json").read_text())
    xrefs = json.loads((CACHE / "thumb-xrefs.json").read_text())
    flash_xrefs = json.loads((CACHE / "flash-xrefs.json").read_text())
    blob = RAM.read_bytes()
    digest = hashlib.sha256(blob).hexdigest()
    assert digest == manifest["ram_sha256"] == xrefs["sha256"]
    assert xrefs["base"] == RAM_BASE

    def sites(target):
        return sorted(
            hex(row["site"]) for row in xrefs["calls"]
            if row["target"] == target
        )

    def refs(value):
        return sorted(
            hex(row["site"]) for row in xrefs["literals"]
            if row["value"] == value
        )

    def words_at(address, count):
        offset = address - RAM_BASE
        return struct.unpack_from("<" + "H" * count, blob, offset)

    words = words_at(TABLE, TABLE_COUNT)
    dispatch = [
        {"command_id": command_id, "table_halfword": f"0x{word:04x}",
         "target": hex(TABLE + word * 2)}
        for command_id, word in enumerate(words)
    ]
    app_values = [APP, APP | 1]
    app_refs_ram = {
        hex(value): refs(value) for value in app_values
    }
    app_refs_flash = {
        hex(value): sorted(
            hex(row["site"]) for row in flash_xrefs["literals"]
            if row["value"] == value
        ) for value in app_values
    }
    app_calls = sorted(
        hex(row["site"]) for row in xrefs["calls"]
        if row["target"] in app_values
    )
    app_entry_bytes = {
        hex(value): [hex(RAM_BASE + offset) for offset in range(len(blob))
                     if blob[offset:offset + 4] == struct.pack("<I", value)]
        for value in app_values
    }
    fallback_ids = [row["command_id"] for row in dispatch
                    if int(row["target"], 16) == 0x20D418]
    assert fallback_ids == [0x13], fallback_ids
    out = {
        "official_input_sha256": manifest["source_sha256"],
        "initialized_ram_sha256": digest,
        "task_registration": {
            "app_loop": hex(APP),
            "direct_callers_in_cached_ram_xrefs": app_calls,
            "literal_refs_in_cached_ram_xrefs": app_refs_ram,
            "literal_refs_in_cached_flash_xrefs": app_refs_flash,
            "raw_pointer_occurrences_in_ram_cache": app_entry_bytes,
            "priority": "unresolved; no creation record or priority argument identified",
            "scope_note": "absence is limited to the existing hash-keyed indexes; indirect/runtime-built registration remains possible",
        },
        "event_bit_3": {
            "flag_word": hex(EVENT_WORD),
            "set_helper": "0x204758(3)",
            "set_helper_callers": sites(0x204758),
            "clear_helper": "0x20479c(3)",
            "clear_helper_callers": sites(0x20479C),
            "flag_word_literal_sites": refs(EVENT_WORD),
            "consumer": "usb_audio_cmd_handler clears bit 3 at entry, drains ring; app loop then calls 0x209a8c",
            "wake_semantics": "shared software flag; no direct RTOS wake primitive proven at producer",
        },
        "command_dispatch": {
            "consumer": "0x20d1c8",
            "id_source": "bits 0..7 of uint32 queue word",
            "dispatch_table_address": hex(TABLE),
            "table_entries": dispatch,
            "max_table_id": "0x14",
            "table_ids_routed_to_unhandled_logger": [hex(value) for value in fallback_ids],
            "available_eq_command_id": "0x13 (decimal 19; currently routes to generic unknown-command logger)",
            "unhandled_path": "0x20d418 logs the command ID and resumes queue drain",
            "safe_extension_candidate": "special-case 0x13 at 0x20d418 before the existing log; preserve the logger for IDs >0x14",
        },
    }
    OUT.write_text(json.dumps(out, indent=2, sort_keys=True) + "\n")
    print(OUT)
    print(hashlib.sha256(OUT.read_bytes()).hexdigest())


if __name__ == "__main__":
    main()

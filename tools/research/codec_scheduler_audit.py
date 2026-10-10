#!/usr/bin/env python3
"""Emit a compact deterministic scheduler/codec cross-reference audit.

Consumes only hash-keyed cached 0.23 analysis indexes. It performs no USB I/O
and does not disassemble or modify firmware images.
"""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / "research/cache/custom-vendor"
OUT = CACHE / "codec-scheduler-analysis.json"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    manifest = json.loads((CACHE / "analysis-manifest.json").read_text())
    xrefs = json.loads((CACHE / "thumb-xrefs.json").read_text())
    eq = json.loads((CACHE / "eq-call-graph.json").read_text())
    strings = json.loads((CACHE / "string-index.json").read_text())
    assert xrefs["sha256"] == manifest["ram_sha256"]
    assert eq["source_sha256"] == manifest["source_sha256"]

    calls = xrefs["calls"]
    literals = xrefs["literals"]

    def callers(target):
        return sorted(hex(row["site"]) for row in calls if row["target"] == target)

    def literal_refs(value):
        return sorted(
            [
                {"site": hex(row["site"]), "pool": hex(row["pool"])}
                for row in literals if row["value"] == value
            ],
            key=lambda row: (int(row["site"], 16), int(row["pool"], 16)),
        )

    def string_address(text):
        matches = [int(row["address"], 16) for row in strings if row["text"] == text]
        return matches

    busy_refs = literal_refs(0x200162B4)
    out = {
        "source_sha256": manifest["source_sha256"],
        "initialized_ram_sha256": manifest["ram_sha256"],
        "evidence_scope": "Cached Thumb literal/call candidates and reviewed disassembly; not a complete whole-image task-creation audit.",
        "scheduler": {
            "usb_audio_app_loop": {
                "entry": "0x20aa20 (candidate entry)",
                "calls_command_handler_at": "0x20aa82",
                "calls_after_handler": ["0x209a8c"],
                "back_edge": "0x20aa8a -> 0x20aa82",
                "task_creation_or_priority": "unresolved",
            },
            "usb_audio_cmd_handler": {
                "entry": "0x20d1c8",
                "callers": callers(0x20D1C8),
                "queue_pop_call_sites": ["0x20d1e2", "0x20d24a"],
                "direct_eq_open_call_sites": [
                    row for row in eq["functions"]["usb_audio_open_eq"]["direct_callers"]
                ],
            },
            "frame_audio_worker": {
                "entry": "0x21229e",
                "range": "0x21229e-0x2123bc",
                "classification": "frame-critical; handler dispatch and overrun/lost-signal reporting",
            },
        },
        "command_queue": {
            "object": "0x200196ac",
            "storage": "0x20019634",
            "initialize": "0x20d53c",
            "push": "0x20d54c",
            "pop": "0x20d5b4",
            "count_or_wait": "0x20d670",
            "enqueue_wrapper": "0x20ab28",
            "enqueue_wrapper_callers": callers(0x20AB28),
            "consumer_entry": "0x20d1c8",
            "item_width_bytes": 4,
            "observed_fields": {"read_index": "+0", "write_index": "+1", "count": "+2", "capacity": "+3", "data_pointer": "+8"},
            "capacity": 30,
            "entry_format": "uint32; command ID bits 0..7, observed arguments bits 8..23, bits 24..31 unused by reviewed dispatcher",
            "overflow": "raw push returns full immediately; wrapper enters queue-dump/status diagnostic loop on full and must not be called from EP0",
            "serialization": "commands are drained sequentially by the command handler; global serialization against every possible codec caller is not proven",
        },
        "codec_update": {
            "setter": "0x20a424",
            "busy_flag": "0x200162b4",
            "busy_literal_references": busy_refs,
            "iir_set_cfg_callers": callers(0x20A424),
            "eq_open_callers": eq["functions"]["usb_audio_open_eq"]["direct_callers"],
            "bank_control": "0x403000e0 bit 22 select / bit 24 acknowledgement",
            "confirmed_acks": ["0x20a76a", "0x20a844"],
        },
        "queue_related_strings": {
            name: [hex(address) for address in string_address(name)]
            for name in ["usb_audio_enqueue_cmd", "usb_audio_cmd_handler", "usb_audio_app_init", "usb_audio_cmd_set_playback_rate", "usb_audio_cmd_set_capture_rate"]
        },
        "classifications": {
            "confirmed": [
                "0x20d1c8 is the queue consumer named by its diagnostic string and has two calls to pop items.",
                "0x20aa82 invokes the consumer in a loop, then calls 0x209a8c and returns to the consumer.",
                "The queue stores 32-bit items in a bounded ring and uses short interrupt-masked index/count updates.",
                "The consumer dispatches USB-audio commands and several paths call usb_audio_open_eq.",
            ],
            "inferred": [
                "The 0x20aa20 software loop is a non-frame audio-control context distinct from af_thread; its task identity and priority are not proven.",
                "The queue is a plausible serialization point for USB-audio stream/configuration operations.",
            ],
            "unverified": [
                "Task creation API, priority, preemption relationship to af_thread, and exact blocking semantics of 0x20479c/0x209a8c.",
                "Whether any codec setter path bypasses the command loop under runtime conditions.",
                "Real EP0 caller context and mailbox synchronization contract for a custom producer.",
            ],
            "disproven": [
                "usb_audio_enqueue_cmd is not itself evidence of a general-purpose worker API; on full it loops through queue dump/status diagnostics.",
                "af_thread is not an acceptable synchronous EQ-setter drain point.",
            ],
        },
    }
    OUT.write_text(json.dumps(out, indent=2, sort_keys=True) + "\n")
    print(OUT)
    print(digest(OUT))


if __name__ == "__main__":
    main()

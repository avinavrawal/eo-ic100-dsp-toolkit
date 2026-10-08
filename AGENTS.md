# Project safety rules

These rules apply to all work in this repository. Treat approval as explicit user authorization for the specific operation; do not infer it from permission to analyze firmware or run read-only queries.

## Device and slot identity

- The normal EO-IC100 USB device is `04e8:a05e`.
- Slot A contains the original recovery firmware. Preserve it as the recovery path.
- Slot B contains the modified development firmware.

## Automatically allowed operations

- Known read-only USB queries, including `QUERY_SW_VER` and `CHECK`.
- Firmware analysis, disassembly, compilation, and tests.
- HID capture.

Automatic permission does not extend to tests or capture setup that perform an operation requiring approval below. An unknown USB control request requires approval even if it is suspected to be read-only.

## Operations requiring explicit approval

- Unknown USB control requests.
- `FW_UPDATE` or `SYS_REBOOT` during research.
- Any flash erase or write.
- `BURN_INFO` or `BURN_BIN` commands.
- Validity-marker writes.
- Boot-flag changes, including activation or slot selection.

Inspect scripts and command paths before running them. Approval for a read-only query does not authorize a wrapper that also changes device state.

## Mandatory preservation and verification

- Never overwrite both firmware slots.
- Never erase recovery slot A.
- Never alter or delete `flash-backup.bin`, wherever it is stored.
- Never activate an image unless the entire staged image has been read back from the device and verified byte-for-byte against the intended image. Partial reads or acknowledgements alone are insufficient.

## Research records

- Maintain `research/RESEARCH_LOG.md` with experiments, commands, observations, verification results, and relevant approvals.
- Check the existing research log, documentation, and findings before repeating an experiment. Record why repetition is necessary and what new evidence it is intended to collect.

## Low-token research workflow

- Read `research/KNOWN_FINDINGS.md` and search existing summaries before new analysis. Reuse previous results whenever their inputs and analysis settings match.
- Prefer targeted `rg`/`grep` searches, Python processing, radare2 automation, symbol/string indexes, xref extraction, binary diff scripts, and cached disassembly.
- Keep large machine-generated outputs in ignored `research/cache/`. Never load whole firmware binaries, huge disassemblies, or raw logs into model context. Redirect tool output to files, then search or summarize it.
- Use `tools/research/analyze.py` for cached string indexes, binary differences, bounded log summaries, and radare2 queries. Cache identity includes input SHA-256 and analysis settings; radare2 caches also include its version. Recompute when those change.
- Start with concise summaries; retrieve only relevant indexed rows, functions, addresses, or xrefs. Bound command output and report truncation rather than silently treating a sample as complete evidence.
- Preserve source paths, hashes, commands/settings, evidence offsets, and confidence labels in research records. Keep reusable conclusions in `KNOWN_FINDINGS.md`, not repeated raw transcripts.
- Do not commit caches, proprietary binary-derived dumps, or raw device captures. All device safety and approval rules above still apply.

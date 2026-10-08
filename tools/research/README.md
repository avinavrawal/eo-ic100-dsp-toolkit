# Offline research workflow

Search `research/KNOWN_FINDINGS.md` and `research/RESEARCH_LOG.md` first. Use targeted `rg -n -m 20 'pattern' paths` queries instead of reading entire files. Cache large output under ignored `research/cache/`; retain concise, reviewed conclusions in research documents.

The helper prints small JSON summaries and cache paths. Inputs are hashed in streaming blocks. Matching input hashes, paths, settings, helper version, and radare2 version reuse completed results. Originals are opened read-only. No USB operations are implemented.

```sh
python3 tools/research/analyze.py strings firmware/private/stock_b.bin
python3 tools/research/analyze.py diff firmware/private/stock_a.bin firmware/private/stock_b.bin
python3 tools/research/analyze.py summary path/to/stage-log.txt --limit 12
python3 tools/research/analyze.py r2 firmware/private/stock_b.bin --commands 'isj;izj'
```

Search the returned `strings.tsv`, `ranges.tsv`, or `output.txt` paths with `rg`. Diff ranges use an exclusive end offset. Strings index printable ASCII; absence there does not establish absence of UTF-16 or encoded strings.

For disassembly and xrefs, first establish architecture, bitness, mapped base, and function boundaries from existing findings. Pass those explicitly; the default ARM/16/base-0 settings are placeholders, not established firmware settings. Example commands (replace addresses):

```sh
python3 tools/research/analyze.py r2 image --arch arm --bits 16 --base 0xADDRESS --commands 'aaa;axtj @ 0xADDRESS'
python3 tools/research/analyze.py r2 image --arch arm --bits 16 --base 0xADDRESS --commands 'pdj 40 @ 0xADDRESS'
```

Cache analysis once and reuse extracted indexes. Avoid requesting full disassembly unless necessary; redirect it to cache and generate bounded function/address reports. Symbols may be absent in raw images. Never treat command success or an empty index as proof of a firmware behavior.

Keep raw logs/captures and binary-derived dumps local. Review summaries before placing them in tracked documentation; include evidence paths, offsets, and confidence labels. Do not run USB experiments through this workflow.

For the EO-IC100 runtime-EQ audit, use `runtime_eq_map.py` followed by `runtime_eq_audit.py --disassemble`. These reconstruct known startup mappings and report the compiled vendor command table, fixed EQ structure, callback registration, and candidate call graph. See `research/RUNTIME_EQ_CONTROL.md` for the evidence and input hashes. Run parser checks with `python3 -m unittest discover -s tools/research -p 'test_runtime_eq_audit.py'`. All tools are offline; no USB transport is implemented.

For button/HID research, run `hid_buttons.py` and `python3 -m unittest discover -s tools/research -p 'test_hid_buttons.py'`. The audit checks private source hashes and known patch sites; reports stay under `research/cache/hid-buttons/`. `hid_button_queue.c` is an authored freestanding queue core; the tests compile it on the host and compare it with the Python reference. See `research/HID_BUTTON_RESEARCH.md` for native event semantics, exact offsets, Thumb compilation and patch strategy limitations. These tools do not create a patched firmware image or implement USB transport. `thumb_index.py --output research/cache/name.json` keeps candidate indexes in cache when indexing a private input directly.

For the custom normal-mode extension, see `research/CUSTOM_VENDOR_EQ.md` before using the tools. `custom_vendor_analysis.py` generates reusable string/function indexes, candidate xrefs/call graphs, dispatcher/EQ maps, allocation/replacement reports, focused disassembly and negative findings. `custom_vendor_patch.py` builds hash-locked private B images; `arm_elf.py` validates relocations and Thumb branches. `firmware_diff.py` produces bounded changed-range reports. Outputs stay in ignored `research/cache/custom-vendor/`.

```sh
python3 tools/research/custom_vendor_analysis.py
python3 tools/research/custom_vendor_patch.py
python3 tools/research/custom_vendor_emulate.py --tests
python3 tools/research/eoic_caps_probe.py
```

The emulator needs the documented isolated Capstone/Unicorn dependencies and may require a sandbox execution exception for JIT. It models math/MMIO and does not prove physical boot or audio behavior. The probe defaults to an offline request description; its explicit execution flags require separately approved physical testing. Do not execute it against stock firmware. Record failed approaches in the negative-findings report rather than repeating them.

The separate future physical-test package is documented in `research/CAPS_PHYSICAL_TEST_PACKAGE.md`. Its four `tools/caps/*` physical entry scripts were prepared but never executed. They use the established Termux USB-FD workflow and require phase confirmations; do not run them as part of offline analysis. Only `python3 -m unittest discover -s tools/caps -p test_package.py` executes the RAM-only fake-device tests, with outputs under ignored `research/cache/caps-package-tests/`.

Native Mac read-only transport validation and subsequent approval-gated phases are in `tools/caps/*_macos.py`, `macos_package.py` and `macos_transport.c`. See `research/PHYSICAL_WRITE_READINESS.md` before device access. Reuse the completed full-read/protected-reopen caches; `flash_state.py` compares them offline. `build_macos.py` is an offline compiler, and `python3 -m unittest discover -s tools/caps -p 'test*.py'` runs fake-device/guard tests, not physical deployment. Do not run stage/activation/recovery/probe scripts without their distinct approvals.

The diagnostic overlay is built offline with `python3 tools/research/custom_vendor_diagnostic_patch.py`; it hash-locks the hardened EQ image, reuses `custom-vendor/thumb-xrefs.json`, and writes only ignored artifacts. See `research/EQ_DIAGNOSTIC_READINESS.md`. `eoic_eq_diagnostic_probe.py` describes the read-only E2 request by default; its execute mode requires separate physical authorization. It contains no E1 or transition path. Run the full offline research suite with `PYTHONPATH=tools/research python3 -m unittest discover -s tools/research -p 'test_*.py'` (Unicorn may need the CPU-emulation-capable context). Diagnostic output is `eq-diagnostic.bin`; do not confuse it with the unchanged `eq-test.bin` or CAPS-only image. Existing deployment wrappers remain pinned to their reviewed images.

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

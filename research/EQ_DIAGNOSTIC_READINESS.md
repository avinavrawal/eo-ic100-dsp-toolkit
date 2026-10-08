# Diagnostic EQ-test offline readiness

This build is prepared and verified **offline only**. No enumeration, physical USB request, stage, activation, or persistent write was performed. The earlier physical E1 STALL remains unexplained; these diagnostics are intended to identify its branch.

Image: `research/cache/custom-vendor/eq-diagnostic.bin` (131076 bytes: 131072-byte payload plus mapped-address footer).

SHA-256: `63826ca08bcb0687a1a620673526dd86792b24f4d470245fe536787be1bcd61a`.

Official B input: `firmware/private/stock_b.bin`, SHA-256 `2f418d3a324ec4217c32c4bf98d43c3cd07d59d81f82974f29320d399fa769f3`.

Hardened EQ base: `research/cache/custom-vendor/eq-test.bin`, SHA-256 `5be2b81385fce7fa86876393b680e5d3b3bbbededf13aa893ab42cccf5c9b26b`. The original CAPS-only and hardened images remain unchanged.

Expected staged payload hash after substituting the existing validity marker and omitting the four-byte file footer: `2ec62930e2368ce5a3cd8bb18fe84bc925d88cc81879a97ddc9fd928c8209183`. This differs deliberately from the image-file hash.

Rebuild: `python3 tools/research/custom_vendor_diagnostic_patch.py`. The builder checks the official hash, base output hash, callback/status preimages, cached-xref identity, branches, Thumb pointers, allocation size, changed-range whitelist, metadata, static boot EQ, and unchanged wait helpers. If the prior analysis cache is missing, generate it with `python3 tools/research/custom_vendor_analysis.py`; no USB is involved.

## Hooks and preservation

Authored diagnostics occupy file `[0x1f400,0x1f8b4)`, XIP execution `[0x0c04d400,0x0c04d8b4)`. This extends the already reviewed four-sector B envelope; it is not a guessed zero/FF code cave. The original hardened handler remains at `0x0c04d000`.

| Hook | File offset | Thumb destination |
| --- | --- | --- |
| setup | 0x1d990 | 0xc04d401 |
| vendor | 0x1d384 | 0xc04d59f |
| data | 0x1d994 | 0xc04d769 |
| EP0 state-6 IN completion | 0xed12 / RAM 0x0020641e | 0x0c04d881 |

The setup and vendor wrappers delegate to the unchanged hardened handlers. Only the authored setter-call address is redirected to bookkeeping at `0x0c04d727`; that wrapper invokes the same `audio_eq_set_cfg` Thumb pointer `0x0020a939`, with `r0=0`, `r1=140-byte transient EQ config`, `r2=2`, and propagates its return unchanged. No change was made to the DSP setter or global-gain validation.

Both original ACK helper bodies `[0x0c04d19c,0x0c04d21c)` are byte-identical. Their new wrappers at `0x0c04d7f1` and `0x0c04d811` record a timeout after the helper returns, preserve register results, and return to the same stock cleanup. Each bound remains 65535 polling reads, followed by one cleanup read on timeout; no millisecond bound is claimed. Both modeled stuck-ACK tests return status 3, clear busy, retain the old software bank and active coefficient bank, and take the existing EP0 rejection/STALL path. The diagnostic wrappers do not change this behavior.

The status trampoline is `01 4b 98 47 02 e0 81 d8 04 0c 00 bf`, replacing `12 4b 1d 49 00 20 20 70 d3 f8 14 28`. It logs the E1 completion branch, replays every displaced load/state-reset instruction, and returns to `0x0020642a`. Direct xrefs into the displaced instruction interiors were absent in the reused hash-keyed index. Register/MMIO parity is tested against the original completion branch.

Diagnostics reserve the final 64 bytes of the already owned 240-byte USB RX buffer: state at `0x200198b4`, response snapshot at `0x200198d4`, ending exactly at `0x200198f4`. OUT capacity becomes 176 bytes; the setup wrapper rejects **every OUT request over 176 bytes** before the stock oversized-receive behavior. Registration address/capacity must match the known case or the wrapper fails closed. The official image has no absolute pointer into the reserved tail; computed aliases cannot be excluded by this screen. The reviewed registration/setup path owns this buffer, and tested stock command payloads fit the reduced capacity. This intentionally changes oversized legacy OUT behavior and requires physical audio/class-request validation; it is not a claim of complete firmware alias proof.

The E2 snapshot is copied before EP0 sends it; it remains allocated throughout transfer completion. No new heap allocation or persistent storage exists. Telemetry initialization/updates and receive-capacity bookkeeping write RAM only; E0/E2 never invoke the DSP setter. Their requests do not clear the previous outcome. A new E1 increments sequence and replaces the previous trace.

## Exact changed ranges versus official B

End offsets are exclusive. The final range includes appended code/padding and footer relocation; it is not entirely executable code.

```
0xed12..0xed13
0xed14..0xed1e
0x12f86..0x12f87
0x13042..0x1304a
0x1304e..0x13054
0x1311c..0x13128
0x13239..0x1323a
0x1d384..0x1d388
0x1d990..0x1d998
0x1edc4..0x20004
```

Exact overlay ranges and before/after bytes versus the hardened EQ image are in `research/cache/custom-vendor/eq-diagnostic-report.json`. Complete diagnostic disassembly is in `eq-diagnostic-handler-disassembly.txt`; original bounded helper disassembly is in `eq-test-handler-disassembly.txt`. These binary-derived outputs remain ignored/private.

## Wire protocol

GET_EOIC_CAPS is unchanged in CAPS-only. In diagnostic EQ B it uses setup bytes `c0 e0 4f 45 43 49 0c 00` and returns exactly:

```text
45 4f 49 43 01 00 08 00 01 00 00 00
```

The last four bytes are little-endian flags=1, `EQ_TEST_ENABLED`. E2 additionally identifies diagnostic instrumentation with `EQDG`. Flags=1 alone is not a cryptographic runtime image hash.

GET_EQ_DIAGNOSTICS: `bmRequestType=0xc0`, `bRequest=0xe2`, `wValue=0x454f`, `wIndex=0x4943`, `wLength=32`; setup bytes `c0 e2 4f 45 43 49 20 00`. No OUT data stage. Reply uses `<4sHH6I>`, all little-endian:

| Offset | Meaning |
| --- | --- |
| 0 | magic EQDG (45 51 44 47) |
| 4 | protocol u16 = 1 |
| 6 | structure size u16 = 32 |
| 8 | E1 sequence count u32 |
| 12 | event mask u32 |
| 16 | last outcome u32 |
| 20 | raw setter return u32; FFFFFFFF means not returned/called |
| 24 | timeout mask: bit0 first/set-ACK wait; bit1 second/clear-ACK wait |
| 28 | current readiness mask, sampled during E2 |

Event bits: `0x001` SET seen by setup wrapper, `0x002` setup matched, `0x004` vendor callback entered, `0x008` four-byte finite/in-range payload accepted, `0x010` setter called, `0x020` setter success, `0x040` setter error, `0x080` ACK timeout, `0x100` status armed (data callback accepted, state 6), `0x200` actual EP0 state-6 IN-completion branch reached.

Outcome: 0 no outcome (events/sequence distinguish no SET from setup matched but callback not entered), 1 setup rejected, 2 runtime guard/config rejected, 3 setter success, 4 setter error, 5 ACK timeout, 6 payload rejected. The event mask retains intermediate stages. A packet discarded upstream of the registered setup callback cannot be observed here; “no SET seen” means no E1 reached that instrumented callback, not proof no host packet was attempted. Valid E1 follows the instrumented path.

Current readiness bits: enabled=1, codec initialized=2, not busy=4, sample rate 32000..192000=8, compiled stock band count=2 means bit16. All expected live guards produce `0x1f`. This field is a **current** snapshot, not a stored rejection-time cause; other runtime config validation can still reject. Enumeration alone does not establish readiness.

SET_EQ_TEST stays exactly `40 e1 4f 45 43 49 04 00`, payload `00 00 c0 c0` for -6.0 dB. Exactly four bytes, finite float32, [-12,0] dB, unchanged live/config guards. Successful OUT transfer reports four payload bytes transferred and a normal zero-length status ACK, not a new response payload. Rejections/errors still STALL; E2 supplies the reason afterward. No arbitrary memory command is exposed.

## Expected diagnostic byte fixtures

These are exact examples for the stated sequence/event/readiness assumptions. The readiness field is dynamic; initial idle readiness 0x14 is the modeled case, not a guaranteed physical value. Success before completion has event mask 0x13f; after completion 0x33f. A physical setter error may return another nonzero status; the raw value is preserved.

**no_set_idle**

`45 51 44 47 01 00 20 00 00 00 00 00 00 00 00 00 00 00 00 00 ff ff ff ff 00 00 00 00 14 00 00 00`

**no_set_audio_ready**

`45 51 44 47 01 00 20 00 00 00 00 00 00 00 00 00 00 00 00 00 ff ff ff ff 00 00 00 00 1f 00 00 00`

**setup_rejected_audio_ready**

`45 51 44 47 01 00 20 00 01 00 00 00 01 00 00 00 01 00 00 00 ff ff ff ff 00 00 00 00 1f 00 00 00`

**runtime_guard_rejected_idle**

`45 51 44 47 01 00 20 00 01 00 00 00 0f 00 00 00 02 00 00 00 ff ff ff ff 00 00 00 00 14 00 00 00`

**payload_rejected_audio_ready**

`45 51 44 47 01 00 20 00 01 00 00 00 07 00 00 00 06 00 00 00 ff ff ff ff 00 00 00 00 1f 00 00 00`

**setter_success_status_armed**

`45 51 44 47 01 00 20 00 01 00 00 00 3f 01 00 00 03 00 00 00 00 00 00 00 00 00 00 00 1f 00 00 00`

**setter_success_status_complete**

`45 51 44 47 01 00 20 00 01 00 00 00 3f 03 00 00 03 00 00 00 00 00 00 00 00 00 00 00 1f 00 00 00`

**setter_error_status3_audio_ready**

`45 51 44 47 01 00 20 00 01 00 00 00 5f 00 00 00 04 00 00 00 03 00 00 00 00 00 00 00 1f 00 00 00`

**first_ack_timeout_audio_ready**

`45 51 44 47 01 00 20 00 01 00 00 00 df 00 00 00 05 00 00 00 03 00 00 00 01 00 00 00 1f 00 00 00`

**second_ack_timeout_audio_ready**

`45 51 44 47 01 00 20 00 01 00 00 00 df 00 00 00 05 00 00 00 03 00 00 00 02 00 00 00 1f 00 00 00`

## Offline verification

**82 tests passed:** 58 research tests (including 18 diagnostic tests) and 24 deployment/guard tests. Logs and counts: `research/cache/custom-vendor/eq-diagnostic-{research-tests.log,deployment-tests.log,test-results.json}`.

Coverage includes deterministic rebuild and hashes, image lengths/footer/range accounting, preserved original ACK helper bytes, metadata/boot EQ/audio/HID bytes, Thumb decoding and branch/literal validation, distinct CAPS across three variants, E2 actual stock EP0 DMA response, setup/payload/live-guard rejection, successful actual setter call, actual EP0 completion instrumentation, raw error propagation, both forced timeout paths, active-bank preservation, reduced RX fence/address mismatch hard stop, legacy classifiers/CHECK parity, read-only outcome retention, decoder rejection, and original-versus-diagnostic setter coefficient/MMIO/poll parity.

The initial deployment-suite crash was isolated to the RAM-only macOS test facade: stabilization logging called real libusb bus/address accessors with the fake pointer. Added mocks for these two accessors in `tools/caps/offline_macos_test.c`; the suite then passed. No physical transport, activation semantics or deployment checks were changed.

Re-run commands (offline):

```sh
python3 tools/research/custom_vendor_diagnostic_patch.py
PYTHONPATH=tools/research python3 -m unittest discover -s tools/research -p 'test_*.py'
python3 -m unittest discover -s tools/caps -p 'test_*.py'
python3 tools/research/eoic_eq_diagnostic_probe.py
python3 tools/research/eoic_caps_probe.py --expected-flags 1
```

Unicorn requires the USB-free CPU-emulation-capable execution context on this Mac. The last two commands above are dry runs. CPU/MMIO emulation does not establish real boot/audio/USB timing, IRQ concurrency, analogue gain, or the cause of the prior physical STALL.

## Minimal future physical plan — not executed

A. **Separately review/approve deployment for this exact new hash.** Establish A active and B inactive, using complete A/flag verification. Last recorded selection is B; do not stage over active B. A return-to-A flag operation, known programmer transition, and manual power cycle need their own authorization as applicable. Never rewrite A. Existing CAPS-only deployment wrappers pin another hash and must not be pointed at this image without a reviewed diagnostic manifest/tooling update. Stage only inactive B, verify its complete readback, full unchanged A and unchanged flags; then use the reviewed activation procedure to select B and verify both flags. Stop before reboot.

B. User manually power-cycles. Confirm normal `04e8:a05e`, expected firmware version/CHECK, audio input/output and HID; stop on any mismatch.

C. One separately authorized E0 must return the exact flags=1 CAPS response above. A flags=0 response aborts; do not send E1.

D. One separately authorized E2 captures the initial 32-byte reply: EQDG/protocol1/size32, sequence0/events0/outcome0/resultFFFFFFFF/timeouts0. Preserve raw bytes and current readiness. Any prior E1 trace or malformed signature aborts.

E. Start actual continuous audio playback at a supported rate, conservative listening level, and verify audible output. Enumeration alone is insufficient. If audio is absent, stop. Playback should initialize the EQ/codec guards, but E1 can still reject safely; do not guess or bypass a guard.

F. Send **exactly one** E1 at -6.0 dB with the unchanged setup/payload above. Record transfer result/error and timing. No retry and no other gain (including no automatic 0 dB restore).

G. If the device remains accessible, one separately authorized E2 records the outcome even if E1 STALLs. Interpret events: no seen/matched indicates dispatch path; outcome2 indicates guard/config refusal; called plus timeout mask distinguishes bounded ACK failures; success without complete distinguishes setter success from USB status completion; success+complete is 0x33f. If USB disconnects or stops responding, stop without further requests.

H. **Stop.** Save raw request/response, logs, audio observations and hashes. Do not infer analogue DSP change merely from setter success. No restore, retry, flash, reboot or unrelated request is bundled with this experiment.

The future read-only probe commands, after approval, are:

```sh
python3 tools/research/eoic_caps_probe.py --expected-flags 1 --execute --confirm-patched-b
python3 tools/research/eoic_eq_diagnostic_probe.py --execute --confirm-diagnostic-b --evidence research/cache/eq-diagnostic-physical/before.json
# Start actual playback, then the separately approved single E1 transfer.
python3 tools/research/eoic_eq_diagnostic_probe.py --execute --confirm-diagnostic-b --evidence research/cache/eq-diagnostic-physical/after.json
```

These commands were **not run**. The E2 tool implements only one IN E2, with no retries/OUT/configuration/driver detach. Do not use the older combined physical EQ probe as-is: it expects flags=0 and may include additional checks/restore operations outside this minimal plan.

## Risk and recovery

The new status hook and RX partition increase diagnostic-build risk relative to the hardened image. Offline parity tests reduce ABI/status concerns but do not prove IRQ timing, buffer lifecycle during USB reinitialization, watchdog margin, or every class request. The original finite helpers are unchanged; instrumentation adds a bounded amount of CPU work, not a proven wall-clock timeout. Codec acknowledgement/analogue behavior remain unverified. Stack pushes are balanced and preserve the modeled ABI; physical stack headroom is not measured.

E1 can succeed in changing the transient gain even if a later USB status error occurs. Use the recorded setter/event bits; do not assume STALL means no DSP change. No persistent EQ configuration is changed. A subsequent user-approved manual power cycle is expected to reload the preserved stock boot EQ, but that physical recovery behavior has not been retested for this image.

If B does not enumerate or audio fails, stop and obtain approval for the reviewed recovery-to-A procedure: read/validate unchanged A, restore only active boot selection to A, read back the flag, then user power-cycles. Do not rewrite firmware or erase A. If recovery cannot safely reach the known programmer/flags path, stop instead of sending unknown requests. A programmer-mode device is not permission to upload, write flags, or retry. Keep the original flash backup unchanged.

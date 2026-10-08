# Offline custom vendor EQ extension — Samsung 0.23 B

## Result

Produced deterministic **CAPS-only** and **experimental EQ-test** B images, an authored Thumb handler, a strict offline patcher, a dry-run-first host CAPS probe, reusable analysis maps and 24 passing custom-vendor tests. The CAPS command runs through the stock EP0 state machine and transmit DMA-copy path in CPU emulation. The EQ-test command reaches the original coefficient generator/setter; modeled −1 dB gain changes coefficients and modeled 0 dB restores them. One physical E1 request was later attempted and returned libusb PIPE; the running image and failing firmware branch were not identified.

This report describes offline artifacts and verification within the explicitly described CPU/peripheral model. The EQ-test image's physical boot is not independently identified: its version and CAPS response are intentionally identical to CAPS-only B. The one physical SET attempt stalled; no successful physical SET response, uninterrupted real audio, acoustic gain, silicon acknowledgement, or timing has been demonstrated. This report is not deployment authorization.

Prior `RUNTIME_EQ_CONTROL.md` findings were reused: the stock firmware exposes no runtime EQ command, but contains a callable internal high-level EQ API. This work adds an explicit new protocol; it does not reinterpret an existing stock command as an EQ command.

## Artifacts and identity

Input is only `firmware/private/stock_b.bin`, SHA-256:
`2f418d3a324ec4217c32c4bf98d43c3cd07d59d81f82974f29320d399fa769f3`.
Stock A, unknown images and modified input bytes are rejected. No override is provided.

| Artifact under ignored `research/cache/custom-vendor/` | Whole-file SHA-256 |
| --- | --- |
| `caps-only.bin` | `afa5bb0570950030c7e36c3219fd93e0efc65c90f5355e02d4a3a091cb6bf356` |
| `eq-test.bin` | `5be2b81385fce7fa86876393b680e5d3b3bbbededf13aa893ab42cccf5c9b26b` |

Compiler: Apple clang 21.0.0 (`clang-2100.1.1.101`), target `arm-none-eabi`, Cortex-M4 Thumb, `fpv4-sp-d16`, softfp, `-Os`, freestanding/no builtins/no strict aliasing/no unwind tables/no compiler identification. Output is deterministic for the recorded compiler, flags and source. A different compiler is not assumed to produce these hashes: object caching keys the source, compiler and feature variant; the report always records actual output hashes.

Both output files are 131076 bytes (`0x20004`): 131072-byte payload plus four-byte host-only mapped-start footer `0x3c02e000`. Original payload was 126404 bytes. The original validity placeholder stays `ff ff ff ff`; it is **not** made boot-valid by this offline patcher. Expected completely staged payload hashes after substituting the established validity marker `1c ec 57 be` at bytes 0–3 and excluding the footer are:

- CAPS-only: `bf92856c12779f7bbbff1b80d75d0d5d866254c4bd01b44ee328608669ddb52c`.
- EQ-test: `c387a036c63ab65563aad62f0bccc5b179f07377cf63c1edff607cbfbb9ad269`.

Reports, objects, reconstructed RAM, disassembly, decoded instructions, third-party emulator packages and generated images remain ignored. None belongs in a source/documentation commit. The host probe is `tools/research/eoic_caps_probe.py`; firmware source is `tools/research/custom_vendor_eq.c`.

## Phase 1: normal-mode control path and ABI

**CONFIRMED static:** USB IRQ handler `0x00206a50` is registered at `0x0020714a` into vector-table offset `0x5c` (external IRQ 7). It services controller registers at `0x40180000` and calls endpoint-zero state handler `0x00206130`. That handler reconstructs the eight-byte setup packet in frame `0x2001ac74`, then calls the registered setup callback through HAL table `0x2001ab9c` + `0x0c` at `0x00206208`.

```text
USB IRQ 0x00206a50
  → EP0 state handler 0x00206130
  → registered setup callback (new guard → original 0x0020dd10)
  → vendor callback (new handler → original 0x0020d998 for stock traffic)
  → frame reply pointer/length, or OUT receive preparation
  → OUT completion: original uaud_datarecv 0x0020e5fc → vendor callback
  → IN reply: EP0 packet sender 0x00205c9c
       → memcpy 0x00200140 → RAM DMA buffer 0x2001abf4
       → USB DMA registers 0x40180910 / 0x40180914
```

Normal-mode USB audio setup receiver is `0x0020dd10` (Thumb function pointer `0x0020dd11`). Vendor callback is `0x0020d998` (pointer `0x0020d999`), installed in runtime global `0x2001b15c`. The constant registration structures at SRAM aliases `0x200150ac` and `0x20014a80` are copied/registered during existing USB initialization. The original callback word at configuration +`0x2c` is `0x20014aac`.

| Structure | Field offsets / calling convention |
| --- | --- |
| Setup packet, 8 bytes | +0 `bmRequestType` u8; +1 `bRequest` u8; +2 `wValue` LE16; +4 `wIndex` LE16; +6 `wLength` LE16 |
| EP0 frame | +0 state u8; +4 payload pointer; +8 payload length u16; +12 embedded setup packet |
| Vendor callback argument, 12 bytes | +0 setup pointer; +4 payload pointer; +8 payload length u16; final padding |
| Vendor callback | AAPCS Thumb: r0 argument pointer; r0=0 accept, nonzero reject; may replace pointer/length for IN |
| Setup/data callbacks | r0 frame pointer; r0=1 handled, r0=0 unhandled/rejected |

**CONFIRMED:** IN setup invokes the vendor callback with payload pointer null and length zero; reply pointer/length are copied to frame state 4. OUT with a payload prepares frame state 3, then the data callback passes received payload/length and, on acceptance, selects state 6 for status handling. A stock IN reply is clamped to the host length and a 64-byte EP0 packet. The packet sender copies bytes from the supplied pointer to its RAM DMA buffer; the extension's immutable flash response does not need writable static RAM. Existing flash descriptor getters also return XIP pointers, e.g. `0x0c035354` → `0x0c03554c`.

**CONFIRMED:** stock command selection is a prefix match followed by a later zero-payload response/action phase. The seven IDs remain 1 QUERY_SW_VER, 2 QUERY_SN, 3 SYS_REBOOT, 4 SYS_SHUTDOWN, 5 PING_THROUGH_VENDOR, 6 CHECK, 7 FW_UPDATE. Stock host transport uses OUT `40/06`, then IN `c0/0c`, with value/index zero. The original vendor callback does not gate these numbers or value/index; vendor-type setup routing is broader. The extension delegates all non-custom vendor traffic to the unchanged original callback and preserves its pending command byte `0x200197f0`.

**CONFIRMED:** normal registration supplies receive buffer `0x20019804` and size 240 from configuration +8/+12. A 64-byte fallback exists if a buffer/length is missing. Oversized stock OUT setup logs an error then still prepares the supplied length. Consequently a payload-stage hook alone cannot safely reject malformed custom lengths. The new setup guard rejects custom malformed requests **before** entering this preparation path.

Error behavior is layered: custom vendor rejection returns 1; setup/data wrappers return 0; the HAL nonstandard-rejection path at `0x002064aa` resets/re-arms EP0. A stock unknown command instead produces the ASCII `failure` response. **UNVERIFIED:** exact physical host-visible stall versus timeout on every rejected stage. The probe treats either as failure and performs no fallback/retry.

Machine-readable details are in `research/cache/custom-vendor/vendor-dispatcher-map.json`.

## Phase 2: runtime EQ API

| Function | Thumb code address | Inputs / output |
| --- | --- | --- |
| `usb_audio_set_eq` | `0x0020c800` | r0 type, r1 preset index; only type 2/index 0 selects the fixed stock table |
| **`audio_eq_set_cfg` — extension target** | **`0x0020a938`**, callable pointer **`0x0020a939`** | r0=0 as stock caller uses (overwritten/unused on this path), r1 high-level configuration pointer, r2=2 hardware-IIR type; r0 nominal status |
| `hw_codec_iir_get_cfg` | `0x0020a178` | r0 integer sample rate, r1 high-level config; r0 points to generated coefficient structure `0x20015fa4` |
| `hw_codec_iir_set_cfg` | `0x0020a424` | r0 coefficient structure, r1 sample rate, r2=1; writes codec coefficient banks/control; status in r0 |

**CONFIRMED:** `audio_eq_set_cfg` reads the current sample rate from `0x200162c8`, clears enabled byte `0x200162cd`, generates coefficients, calls the setter and restores enabled state. Configuration is high-level PEQ, not raw IIR: `<ffI>` gains L/R and count, followed by up to eight `<Ifff>` records (type, gain dB, frequency, Q), 140 bytes total. Stock pointer `0x20015bec` / file `0x1e4c4` contains two type-1 bands, −2 dB at 220 Hz/Q≈0.6 and −2 dB at 9000 Hz/Q8, gains 0 dB.

**CONFIRMED:** global gain is converted with `10^(gain/20)` and applied to first-section feedforward coefficients for each channel. Remaining section/denominator values are preserved by a common-gain-only update. The hardware setter uses banks in `0x40302000`–`0x40302340`. The same-topology path changes bank-select bit 22 at `0x403000e0`, waits for acknowledgement bit 24 to match, and toggles its software bank state. It contains waits at `0x0020a76a` and `0x0020a844` without a timeout.

**Stock behavior:** the high-level function does not propagate every hardware error and can return zero on paths that did not apply a valid hardware update. The EQ-test image changes its final status-clear instruction at `0x0020a960` to a NOP, so the restored-enabled path returns the codec setter status. The extension also checks initialized codec word `0x200162b8`, enabled byte, sample rate, and update-busy byte `0x200162b4` before calling. These checks are necessary, not a guarantee of physical acknowledgement timing or freedom from every IRQ/lifecycle race. Physical timing and audio continuity remain unverified.

The extension copies the stock table into an aligned stack-local structure, alters only its common L/R gain, calls the original API synchronously and never changes the original table. No configuration pointer outlives the call: coefficient generation produces the existing global coefficient structure. Stream reopening/reboot uses the unchanged stock boot EQ. No persistent state is changed.

## Phase 3: hooks and explicit extension allocation

| Hook word in official B file | SRAM data alias | Original pointer | CAPS-only pointer | EQ-test pointer |
| --- | --- | --- | --- | --- |
| `0x1d990`–`0x1d994` | `0x200150b8` | `0x0020dd11` | `0x0c04d001` | `0x0c04d001` |
| `0x1d384`–`0x1d388` | `0x20014aac` | `0x0020d999` | `0x0c04d175` | `0x0c04d21d` |

Injection starts at file `0x1f000`, mapped flash/data address **`0x3c04d000`**, Thumb execution address **`0x0c04d000`**. The latest EQ-test payload occupies 876 bytes (`.text` 864 bytes plus 12 bytes of read-only CAPS data), within the explicit `[0x1f000,0x20000)` allocation. The EQ-test callback is Thumb pointer `0x0c04d21d`.

This is an **appended segment**, not a claim that an old FF/00 cave is unused. Evidence/checks:

- CAPS-only preserves original flashed-payload bytes except the two callback words. EQ-test also applies only the hash-locked wait/status/literal patches listed below; it does not replace unrelated functions, tables, descriptors or metadata.
- Original initialized copy sources end before `0x1f000`. New flash bytes are not destinations of startup RAM clears/copies. The injected code has no writable/BSS allocation, initializer, constructor, exception table or unresolved symbol; writable configuration lives on the existing stack.
- Build metadata remains at `[0x1ec8c,0x1edc4)` with its original header pointer and bytes. The last four original file bytes are the established host-only mapped-start footer; only that footer moves to `0x20000`.
- Allocation ends before B address `0x3c04e000`, inside the same four 32-KiB sector envelope used by the earlier successful official B staging, and inside the known 512-KiB flash mapping. No extra sector or A/flag region is used. This is a layout argument, not evidence that a modified image has physically booted.
- An all-byte-offset LE32 scan of the original B file found no word into `[0x0c04d000,0x0c04e000)` or its `0x3c…` alias. Reviewed initialized/table spans end before this region. This negative scan is **not** a formal proof against every computed/ROM access; report this residual limitation rather than treating absence of pointers as sufficient ownership proof.
- Existing code already executes through the XIP alias; the generated code executes there in the CPU model. Actual silicon fetch/cache behavior in the extended image remains a bring-up risk.
- Registered pointers have Thumb bit set. Indirect calls avoid the ~200-MiB SRAM→flash displacement that cannot fit Thumb B.W/BL. All emitted direct branches are validated within injected instruction boundaries. ELF `$t/$d` mapping symbols exclude the 4-byte float literal pool from instruction targets. MOVW/MOVT and local-call relocations are linked explicitly by the fail-closed `arm_elf.py` helper.

**Rejected alternatives, recorded in `negative-findings.json`:** existing zero runs (initialized/EQ/alignment data); an unused/debug function replacement (none proved dispensable while preserving existing behavior); a direct SRAM→flash B.W hook (out of range); callback-only malformed-OUT validation (too late). If stronger layout/ROM evidence contradicts append ownership, stop deployment and redesign; the patcher is not an authorization to write flash.

CAPS-only changed ranges, exclusive ends:

```text
[0x1d384, 0x1d388)  vendor callback word
[0x1d990, 0x1d994)  setup callback word
[0x1edc4, 0x20004)  appended padding/code/data and relocated host-only footer
```

The current EQ-test image additionally changes these official-B file ranges:

```text
[0x12f86, 0x12f87)  relocate the software-bank-state literal load to its duplicate
[0x13042, 0x1304a)  first wait trampoline and local return path
[0x1304e, 0x13054)  bounded-wait cleanup and helper literal bytes
[0x1311c, 0x13128)  second wait trampoline and helper literal
[0x13239, 0x1323a)  preserve hw_codec_iir_set_cfg status through audio_eq_set_cfg
```

## Phases 4–5: custom request formats

| Command | bmRequestType | bRequest | wValue | wIndex | wLength |
| --- | --- | --- | --- | --- | --- |
| GET_EOIC_CAPS | `0xc0` device/vendor/IN | `0xe0` | `0x454f` | `0x4943` | **12** |
| SET_EQ_TEST | `0x40` device/vendor/OUT | `0xe1` | `0x454f` | `0x4943` | **4** |

CAPS response is LE `<4sHHI>`: magic `EOIC`, version 1, maximum bands 8, flags 0 in both images. The EQ-test build keeps the physically validated response byte-for-byte unchanged: `45 4f 49 43 01 00 08 00 00 00 00 00`. CAPS changes no EQ/persistent state and does not consume the saved stock command ID. No setup OUT transaction precedes it.

SET payload is one LE float32 common gain, inclusive −12 to 0 dB. The first image rejects this command at setup even if all fields are correct. The EQ-test image accepts it only after receiving exactly four bytes and passing the live-state/configuration checks. It exposes neither arbitrary memory nor caller-selected bands/count/types/frequencies/Q.

Validation rejects incorrect direction/recipient/tag/length, null/short/long payloads, NaN/infinities and gain outside bounds. The copied internal structure must have count 1–8, finite L/R gain in bounds, valid type 0–4, finite band gain −12 to +6, frequency ≥20 Hz and below Nyquist, finite Q 0.1–16, sample rate 32–192 kHz. The minimal setter additionally requires the original count 2 and preserves every original band byte. Extra host PEQ fields are rejected by exact payload length. There is no host-controlled memory address, persistence command or filter-topology change.

## Phases 6–7: deterministic build and offline verification

```sh
python3 tools/research/custom_vendor_analysis.py
python3 tools/research/custom_vendor_patch.py
python3 tools/research/custom_vendor_patch.py --enable-eq-test
python3 tools/research/custom_vendor_emulate.py --tests
python3 tools/research/eoic_caps_probe.py
python3 tools/research/firmware_diff.py firmware/private/stock_b.bin \
  research/cache/custom-vendor/caps-only.bin
```

Unicorn 2.1.4 and Capstone 5.0.3 were downloaded with approved network escalation into ignored `research/cache/custom-vendor/deps/`. No package/system install was performed. The sandbox terminates Unicorn while mapping JIT memory; CPU test execution required a sandbox exception. Neither the patcher nor emulator has physical USB code. Only the separately gated host probe implements a single IN transfer; its default dry run never imports PyUSB. Its physical path requires `--execute --confirm-patched-b` and independent prior approval, finds exactly one normal device, uses a 1000-ms timeout, and never sets configuration, detaches a driver, sends OUT, reboots, retries or logs a serial.

**24 custom-vendor tests and 40 total offline research tests passed.** Coverage includes input hash/rejection of A or altered B, deterministic hashes and exact changes, metadata, boot EQ/code/USB/HID preservation, Thumb pointers/relocations and branch reach, CAPS response parity, malformed request/payload rejection, disabled mutation, live-state guards, complete SET receive/API ABI, explicit four-byte OUT acceptance/rejection and stock OUT comparison, coefficient gain/restore, both forced acknowledgement timeouts, active-bank/selector/busy-state preservation on timeout, seven legacy command classifiers, CHECK response preservation, runtime audit and HID tests.

The linker/decoder checks 51 direct branches and 305 injected Thumb instructions for the current EQ-test image. The complete generated disassembly is `research/cache/custom-vendor/eq-test-handler-disassembly.txt`; machine-readable disassembly and branch/literal checks are in `eq-test-decoded.json` and `eq-test-report.json`.

**Emulation scope:** actual authored Thumb code, original setup/data/vendor dispatch, EP0 packet RAM copy, high-level EQ wrapper, coefficient generator and hardware setter execute as guest instructions. Registration, initial audio state, codec acknowledgement bit, IRQ completion and timer are modeled. Diagnostic calls are stubbed. Four pure libm entries (pow/sqrt/sin/cos) use explicit host math models; the full vendor libm path hit an unmapped address in this harness and is recorded as a negative finding. The modeled first-section gain ratio is approximately `10^(-1/20)` and restoring 0 reproduces coefficient bytes. This is CPU/coefficient/MMIO-model evidence, not a physical DSP measurement or bit-exact proof of every vendor libm rounding case.

Reusable cache outputs: `string-index.json`, `function-index.json`, `thumb-xrefs.json`, `flash-xrefs.json`, `call-graph.json`, `vendor-dispatcher-map.json`, `eq-call-graph.json`, `injection-candidates.json`, `negative-findings.json`, hash/tool-keyed focused disassembly, variant patch/decoded reports and `test-results.json`. `firmware_diff.py` writes compact hash/range reports. Reuse these before new analysis; report only bounded slices to model context.

## Risk assessment and first proposed physical test

The EQ-test image now bounds both stock codec acknowledgement waits at `0x0020a76a` and `0x0020a844` to 65,535 MMIO reads each. On timeout, the helper restores control bit 22 to the observed bit 24, clears update-busy `0x200162b4`, leaves software bank selector `0x200162bc` unchanged, and returns status 3 through the stock error epilogue. The high-level wrapper now propagates that status. Offline forced-timeout tests verify a finite return and unchanged active coefficient bank. The bound is a read-count limit, not a calibrated duration; actual silicon acknowledgement, delayed-ack races, audio continuity and rollback semantics remain unverified. Boot/fetch, metadata acceptance and physical recovery risks also remain. Do not deploy this image without a separate review and approval.

Proposed first test, **not performed or authorized by this offline goal**:

1. Separately approve any future deployment and activation work. Preserve recovery A and the complete backup. Use only the CAPS-only artifact, verify its whole-file hash, completely read back all 131072 staged payload bytes with validity-marker substitution, verify the marked-payload hash above, and satisfy AGENTS.md before any activation. Do not combine that work with this probe.
2. Once independently known to be running the verified patched B in normal `04e8:a05e`, establish its known `QUERY_SW_VER`/CHECK and audio/HID enumeration; confirm ordinary playback. No vendor-number search or programmer transition belongs in the probe.
3. After explicit approval for the new request, send **one** `c0/e0/454f/4943/12` IN transfer with a 1000-ms timeout. Expected bytes: `45 4f 49 43 01 00 08 00 00 00 00 00`. No OUT payload and no gain command.
4. Require exact response parsing, continued normal enumeration and audio/HID behavior. On short/wrong response, stall, timeout, reset or audio loss, stop; do not try alternative requests or the EQ-enabled image. Record the result and revisit offline evidence.

The planned future probe command is `python3 tools/research/eoic_caps_probe.py --execute --confirm-patched-b`; it was **not run**. Gain mutation requires a separate later plan and approval after CAPS bring-up, with codec wait/lifecycle risk addressed and independent DSP/acoustic validation. No staging, physical query, flash/flag operation, programmer entry, firmware reboot, commit or push occurred during this goal.

The separate diagnostic EQ-test overlay, unique E0 flags=1 marker, read-only E2 telemetry and bounded-wait preservation are documented in `EQ_DIAGNOSTIC_READINESS.md`. This third variant does not change the historical CAPS-only/hardened EQ images or their prior responses; no physical operation has been performed with the diagnostic image.

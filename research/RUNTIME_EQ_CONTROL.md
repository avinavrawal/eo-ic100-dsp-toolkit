# Normal-mode runtime EQ investigation

## Result

**INFERRED — strong static evidence:** the examined original Samsung 0.04 firmware and official Samsung 0.23 firmware do not expose a safe normal-mode USB mechanism for changing the internal EQ parameters. The internal EQ functions exist and apply coefficients to hardware, but the registered USB request paths do not supply a host-selected EQ configuration.

No runtime EQ change was demonstrated. No USB requests were sent during this investigation. The conclusion concerns the examined images and their normal USB interfaces; it is not a proof about every EO-IC100 revision, inaccessible ROM, memory-corruption exploits, or firmware that could be modified to add a new interface.

The last authorized live capture reported `0.04_051101_aa`, `CHECK=1.1`, and normal `04e8:a05e`. Thus the original A image, not only official 0.23, was analyzed.

## Inputs and mapping

| Input | SHA-256 | Scope |
| --- | --- | --- |
| `firmware/private/flash-backup.bin` | `6ee1089955817ac0deda01aab8eb7531f3bdd11dd1604fd8c143d6d1538eb0cd` | Preserved original flash; original 0.04 A region and startup initialization. |
| `firmware/private/stock_a.bin` | `9ebc51140b17884a9b3fe97edc58f8b3861ec10dbc0a33499ea31200bdedba87` | Official Samsung 0.23 A image. |
| `research/readonly-device-check-20261007.json` | Existing capture, not repeated | Current normal device/configuration/HID descriptors and known queries. |

**CONFIRMED (static bytes):** startup copies code and read-only data from flash into SRAM. Flash load addresses, SRAM data addresses, and SRAM execution aliases must be distinguished; treating the entire image as executing at its flash load address produces misleading xrefs.

`tools/research/runtime_eq_map.py` reconstructs initialized SRAM from the startup copy loops, verifies source hashes, and records segment mappings. Original 0.04 segments: flash file `[0xec5c,0x19214)` → SRAM `0x20000140`; `[0x1925c,0x25f04)` → `0x2000a75c`; initialized data `[0x262fc,0x26394)` → `0x20017408`. Official 0.23 file segments: `[0x8a34,0x11e68)` → `0x20000140`; `[0x11eb0,0x1e7bc)` → `0x200095d8`; `[0x1ebec,0x1ec8c)` → `0x20015ee8`.

**INFERRED from startup and stored callback addresses:** SRAM execution alias `0x00200000` corresponds to data alias `0x20000000`. Code addresses below use the execution alias, with the Thumb bit cleared. Data pointers retain `0x200...` addresses. Historical exploratory caches with `0x200...` instruction addresses identify the same reconstructed byte offsets, not a separate implementation.

## Internal EQ call graph

| Function identified through diagnostic strings and control flow | Original 0.04 | Official 0.23 |
| --- | --- | --- |
| `usb_audio_open_eq` | `0x0020da64` | `0x0020c840` (matched by its call to the EQ selector and initialization flow) |
| `usb_audio_set_eq` | `0x0020da10` | `0x0020c800` |
| `audio_eq_set_cfg` | `0x0020bafc` | `0x0020a938` |
| `hw_codec_iir_get_cfg` | `0x0020b360` | `0x0020a178` |
| `hw_codec_iir_set_cfg` | `0x0020b5fc` | `0x0020a424` |

**CONFIRMED (static control flow):** audio EQ opening calls `usb_audio_set_eq(type=2,index=0)`. The selector accepts hardware-IIR type 2 and only index 0; nonzero indexes return failure. Index 0 loads a fixed pointer from the one supported configuration list, then tail-calls `audio_eq_set_cfg`. That function invokes the coefficient-generation/configuration path and the hardware-IIR setter. The setter writes coefficient-related registers, including the `0x40302000` register region. These are internal hardware operations, not a host-addressable USB memory-write API.

```text
normal audio stream lifecycle
  → usb_audio_open_eq
  → usb_audio_set_eq(2, 0)
  → fixed compiled EQ configuration
  → audio_eq_set_cfg
  → hw_codec_iir_get_cfg
  → hw_codec_iir_set_cfg
  → hardware coefficient registers
```

**CONFIRMED (static data):** the configuration list is at original `0x2001718c`, pointing to `0x20017100`; official 0.23 list `0x20015c78` points to `0x20015bec`. Both decode as gains L/R 0 dB and two type-1 filters: -2 dB, 220 Hz, Q ≈0.6; -2 dB, 9000 Hz, Q 8. The original configuration is at flash-backup file offset `0x25c00`; official 0.23 configuration is at image file offset `0x1e4c4`.

**CONFIRMED:** serialized table structure is `<ffI` (left gain, right gain, count), followed by up to eight `<Ifff` records (type, gain, frequency, Q). **INFERRED:** named filter-type mapping remains as recorded in `KNOWN_FINDINGS.md`; this investigation does not independently establish every type.

**INFERRED — strong evidence:** `usb_audio_set_eq` is an internal fixed-preset selector, not evidence of an exposed USB EQ command. Direct-call and literal indexes alone are not exhaustive proofs of absence; the registered request handlers below provide the stronger reachability evidence.

## USB vendor and UAUD path

**CONFIRMED (static registration):** original USB audio configuration at `0x20015488` stores callback `0x0020eb8d` at offset `0x2c`; official configuration `0x20014a80` stores `0x0020d999`. Original registration at `0x0020e244` passes this configuration to the registration routine at `0x0020fc50`. Its load/store sequence installs the callback in `0x2001c69c`.

**CONFIRMED (static dispatch):** original UAUD setup receiver `0x0020ef30` routes vendor requests through that registered callback; original data receiver `0x0020f824` invokes it again after OUT payload reception. The setup receiver arranges a callback argument containing setup-packet pointer, payload pointer, and length. This generic routing is not an additional hidden EQ parser. The official image has corresponding UAUD setup/data paths at `0x0020dd10` / `0x0020e5fc`.

**CONFIRMED (static table and branches):** vendor callback `0x0020eb8c` (original) / `0x0020d998` (official) matches exactly these seven ASCII command prefixes:

| ID | Command | Observed/static role | EQ input |
| --- | --- | --- | --- |
| 1 | `QUERY_SW_VER` | Returns firmware version. | None |
| 2 | `QUERY_SN` | Returns serial information. | None |
| 3 | `SYS_REBOOT` | Reboot path; forbidden for this investigation. | None |
| 4 | `SYS_SHUTDOWN` | Shutdown path; not an EQ operation. | None |
| 5 | `PING_THROUGH_VENDOR` | Returns fixed `PING_THROUGH_VENDOR` string, not a tunneled command. | None |
| 6 | `CHECK` | Returns fixed profile/version string `1.1`. | None |
| 7 | `FW_UPDATE` | Firmware-update preparation; forbidden for this investigation. | None |

The command tables are at original `0x20015d90` and official `0x20014c0c`. A later zero-length callback consumes the saved command ID and selects the response/action. The default ID response is `failure`. Prefix matching and a generic vendor callback do not justify sending arbitrary request numbers or payloads; malformed-length behavior is not a safe runtime interface.

**INFERRED — strong evidence:** there is no host-supplied EQ record, coefficient payload, preset-index command, or normal-mode register/memory-write command in these registered vendor callbacks. `PING_THROUGH_VENDOR` is not an alternative tunnel to the DSP.

## Alternative normal-mode surfaces

- **CONFIRMED (static dispatch):** original audio-class controls handle Feature Units 2/5 with mute selector 1 and volume selector 2. The data-stage comparisons at `0x0020f8da`–`0x0020f914` reject other selectors; endpoint controls handle sample frequency. There is no implemented graphic-EQ payload branch in this path.
- **CONFIRMED (descriptor capture):** normal USB has audio control/streaming interfaces and HID interface 3; no bulk endpoint. HID endpoint `0x84` is interrupt IN with a 47-byte Consumer Control report descriptor, report ID 1, volume up/down and play/pause input bits. No HID Output or Feature main items are declared.
- **INFERRED — strong evidence:** normal mute/volume/sample-rate controls and internal stream-command queues are lifecycle/audio-level controls, not a route for writing EQ gain/frequency/Q records. Changing ordinary volume would not satisfy the target of changing one EQ parameter.
- **UNVERIFIED:** A/B HID-descriptor differences, undocumented silicon/ROM interfaces, and separate factory/UART debug capabilities. No such capability was demonstrated to be safely reachable through normal `04e8:a05e` USB. Strings or unregistered internal code alone do not establish reachability.

## Offline tools and reproducibility

```sh
python3 tools/research/runtime_eq_map.py > research/cache/runtime-eq-map-summary.txt
python3 tools/research/runtime_eq_audit.py --disassemble
python3 -m unittest discover -s tools/research -p 'test_runtime_eq_audit.py'
```

Run `mkdir -p research/cache` first on a fresh checkout. Mapping, pointer/string indexes, call candidates, decoded configuration, audit JSON, and selected disassembly remain under ignored `research/cache/runtime-eq-*`. Disassembly caches include tool version, commands, and input hash in their identity. `thumb_index.py` labels linear decoding as candidate evidence because data can resemble Thumb instructions. The audit parser is offline and implements no USB transport.

Five tests validate EQ parsing and invalid/truncated inputs, the command-prefix model, and Thumb call/tail-branch decoding. Both real input audits validate hashes, the seven-command table, registered callback address, and stock EQ structure. The parser is not a full firmware emulator and does not simulate physical DSP response.

## Smallest physical experiment decision

**INFERRED — no justified positive experiment:** no reviewed command/request accepts a known EQ parameter, so there is no supported minimal runtime-EQ write to propose. Guessing a vendor command or request would be brute-force research rather than a evidence-based experiment. An audio-class graphic-EQ request would follow a rejected selector branch, and a stall would not demonstrate that a change reaches the DSP. These requests were not sent.

If later evidence identifies a reachable runtime setter, the experiment must first specify its exact request fields, payload structure, one bounded parameter change, rollback, and an independent DSP read-back or controlled acoustic measurement. User approval is required before any previously unclassified USB request. Existing physical query/HID evidence was reused; no persistent writes, firmware patching, programmer entry, or device reboot were needed.

The requested stopping criterion **B** is met for the examined accessible firmware: multiple independent static paths and the normal descriptor surface support absence of a safe exposed runtime-EQ mechanism. Criterion **A** was not met.

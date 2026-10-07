# Research log

## 2026-10-07 — Consolidate existing evidence

- Reviewed repository documentation and source, historical Stage/Activation ZIP logs, and existing descriptor/CDC analysis notes in Downloads.
- Created `KNOWN_FINDINGS.md` with confidence labels, evidence references, and explicit gaps for raw post-boot and HID captures.
- Historical logs establish full-flash backup, complete staged-B verification, and verified activation flags; the repository documents the subsequent successful B boot.
- No USB operations, firmware writes, new device experiments, or binary imports were performed. Original logs and `flash-backup.bin` were unchanged.

## 2026-10-07 10:40 IST — Authorized read-only connected-device check

Purpose: establish the current running firmware and capture missing normal/HID descriptor evidence. Reviewed `AGENTS.md`, the existing findings, `eoic100.c`, and the historical Phase-1 query implementation first. This is a current-state check, not repetition of Stage/Activation experiments.

Authorization: user explicitly requested `lsusb`, `system_profiler SPAudioDataType`, normal/HID descriptors, `QUERY_SW_VER`, and `CHECK`; explicitly prohibited OTA entry, reboot, programmer entry, and unknown vendor requests. Sandbox enumeration initially returned no USB devices and an empty audio device list. Approved execution outside the sandbox supplied actual host visibility.

### OS observations — CONFIRMED

- `lsusb`: `Bus 001 Device 001: ID 04e8:a05e`.
- `system_profiler SPAudioDataType`: Samsung USB C Earphones input and output devices, each two channels at 48000 Hz, USB transport. Built-in microphone/speakers remain the default devices.
- `system_profiler SPUSBDataType` returned no output; do not interpret that alone as absence of the device.
- `ioreg -p IOUSB -l -w 0`: Samsung USB C Earphones, vendor Samsung, serial omitted from public notes, link speed 12000000 bits/s (Full Speed), one configuration, EP0 maximum packet 64, `bcdUSB=0x0200`, `bcdDevice=0x0100`.

### Direct descriptor observations — CONFIRMED

Capture: `readonly-device-check-20261007.json` contains timestamp, complete device/configuration/report descriptor bytes, parsed interface/endpoint entries, and raw query responses.

- Standard `GET_DESCRIPTOR` read the 18-byte device descriptor and complete 320-byte configuration descriptor. Four interfaces: 0 AudioControl, 1 audio input streaming, 2 audio output streaming, 3 HID. No bulk endpoints are advertised.
- Audio input endpoint `0x83` is isochronous; audio output endpoint `0x03` is isochronous with alternate settings for 16/24/32-bit formats.
- HID interface 3, alternate 0, class 3, subclass/protocol 0; HID version 1.11. HID descriptor: `09 21 11 01 00 01 22 2f 00`.
- HID interrupt-IN endpoint `0x84`, maximum packet 3 bytes, interval 4 (4 ms at Full Speed). No HID interrupt-OUT endpoint is advertised.
- Standard interface-recipient `GET_DESCRIPTOR` retrieved all 47 advertised HID report-descriptor bytes:

```text
05 0c 09 01 a1 01 85 01 15 00 25 01 75 01 95 01
05 0c 09 e9 81 02 09 ea 81 02 09 cd 81 02 95 06
81 01 95 01 81 01 95 04 81 01 95 02 81 01 c0
```

- Descriptor declares Consumer Control usage page `0x0c`, usage `0x01`, report ID 1, and one-bit input controls for Volume Increment (`0xe9`), Volume Decrement (`0xea`), and Play/Pause (`0xcd`). Thirteen constant padding bits follow these three bits, yielding two payload bytes plus the report-ID byte. No Output or Feature main items are present in this descriptor. These are descriptor declarations; actual button-event behavior was not captured.
- This capture resolves the earlier missing HID interface/endpoint/report-descriptor evidence in `KNOWN_FINDINGS.md` for the currently running A firmware. A/B descriptor differences and any DSP-control mechanism remain unverified.

### Firmware queries and current slot

Only known query pairs were sent: OUT `bmRequestType=0x40`, `bRequest=0x06`, value/index 0 with ASCII command; IN `bmRequestType=0xc0`, `bRequest=0x0c`, value/index 0, reading 14 bytes for `QUERY_SW_VER` or 3 for `CHECK`.

- **CONFIRMED**: `QUERY_SW_VER` returned `0.04_051101_aa` (14 bytes).
- **CONFIRMED**: `CHECK` returned `1.1` (3 bytes).
- **CONFIRMED using the established firmware-suffix mapping**: currently running original recovery **slot A**, not the previously documented modified B boot. No boot-flag read or change was performed.

No `FW_UPDATE`, `SYS_REBOOT`, programmer-mode commands, unknown vendor requests, interface claims/detaches, configuration changes, HID output/feature writes, or flash operations were performed. `flash-backup.bin` was untouched.

## 2026-10-07 — Reduce research context and reuse offline results

- Added mandatory low-token workflow rules to `AGENTS.md`: targeted searches, existing-findings reuse, bounded summaries, and ignored `research/cache/` output.
- Added `tools/research/analyze.py` for cached ASCII string indexes, streaming binary-diff ranges, bounded log summaries, and explicit radare2 automation. Cache keys include input hashes and settings; radare2 version is included for radare2 outputs.
- Added usage notes in `tools/research/README.md` and ignored generated caches in `.gitignore`.
- Synthetic checks passed for string indexing, changed-byte/range accounting, summary limits, cache reuse, and invalidation after input changes. No firmware or USB experiments were run; radare2 execution was not tested.

## 2026-10-07 — Offline normal-mode runtime EQ goal

Authorization: investigate normal-mode internal DSP EQ using existing findings, strings/xrefs, static disassembly, call graphs, input/path reconstruction, offline tools, then a minimal justified experiment. User required approval for unclassified USB requests and prohibited brute force and persistent writes. No additional physical-device request was sent.

1. Reused known findings and the last live normal-mode/HID/query capture (`0.04_051101_aa`, slot A, `CHECK=1.1`). Reviewed original and official firmware hashes. Did not rerun queries or Stage/Activation.
2. Cached ASCII indexes for official 0.23 and the original backup. Found the requested EQ strings and UAUD/vendor diagnostic strings in both versions. Reconstructed the startup SRAM sections because naive flash-base xrefs did not resolve the runtime string pointers.
3. Added deterministic `runtime_eq_map.py`, `thumb_index.py`, and `runtime_eq_audit.py`. Recorded flash→SRAM segments and the execution alias, candidate literals/calls/tail branches, compiled command tables, callback pointers, EQ structures, and targeted disassembly under ignored `research/cache/`. Exploratory automated function boundaries proved unreliable around pools/data; final conclusions use targeted instruction ranges and registered callback fields rather than automatic function naming alone.
4. Traced fixed-preset EQ initialization to coefficient generation and hardware register application. Examined the registered vendor callback, UAUD setup/data forwarding, normal audio-class selector handling, and previously captured HID surface. Vendor command tables contain seven named commands and no EQ-config command; ping is a fixed response. EQ selector supports only type 2/index 0.
5. Offline parsers decode the two stock filters from original and official images. Five tests passed for valid/invalid EQ structures, prefix parsing, and Thumb call/branch decoding. Real-image audits verify the seven-command tables and callback pointers against reconstructed inputs. Selected disassembly caches were generated with radare2 6.2.4; this supersedes the earlier note that radare2 execution was untested.
6. Alternative normal-mode paths considered: standard audio-class volume/mute/sample-frequency controls, HID output/feature possibilities, generic UAUD vendor forwarding, and `PING_THROUGH_VENDOR`. None provides a safe parameter-bearing EQ route in the examined firmware. Ordinary host volume or host-side EQ does not meet the requested internal-EQ target.
7. No positive minimal physical experiment is justified by the evidence. A guessed vendor payload or rejected audio-class EQ selector would not demonstrate DSP control. No approval request was needed because no new USB request was attempted. Future concrete runtime-setter evidence must define exact request/payload, bounded change, rollback, and independent verification before seeking approval.

Result: stopping criterion B is met for the examined accessible firmware through strong combined static evidence; criterion A is not met. See `RUNTIME_EQ_CONTROL.md` for addresses, call graph, provenance, interpretation limits, and reproduction commands. Updated `KNOWN_FINDINGS.md`, including previously unresolved HID details now supported by the existing capture.

Safety: original files and `flash-backup.bin` were only read; no firmware patch, persistent write, programmer entry, reboot, unknown request, or other USB operation was performed. Binary-derived outputs remain in ignored cache paths. Nothing was committed.

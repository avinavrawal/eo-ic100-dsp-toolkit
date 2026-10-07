# Known EO-IC100 findings

Compiled 2026-10-07 from existing documentation, source, and local historical logs. No USB operations or new experiments were performed. Findings apply to the tested unit and workflow, not every hardware revision.

Labels: **CONFIRMED** means explicitly supported by an existing observation or documented successful result; **INFERRED** means an interpretation or implementation detail without direct observation in the reviewed logs; **UNVERIFIED** means the reviewed evidence does not establish the claim. A documented finding is identified as such when its original capture is unavailable.

## Evidence index

- **R**: repository `README.md`, especially confirmed result, reverse-engineered components, flash layout, and status.
- **P**: `docs/protocol.md`; tested implementation in `tools/termux/eoic100.c` (functions named below).
- **E**: `docs/eq-format.md`, `patcher/patch_eq.py`, and `patcher/presets/diamond8.json`.
- **S**: `~/Downloads/eoic100-FINAL-stage-20261006-204616.zip`, members under `eoic100-FINAL-stage-20261006-204616/`: `enter-ota.txt`, `active-slot.txt`, `stage-log.txt`, `STAGE_SUCCESS.txt`, `flash-backup.sha256`, and `package-assets.sha256`.
- **A**: `~/Downloads/eoic100-FINAL-activate-20261006-205215.zip`, members under `eoic100-FINAL-activate-20261006-205215/`: `enter-ota.txt`, `active-slot.txt`, `activate-log.txt`, and `ACTIVATION_SUCCESS.txt`.
- **H**: `~/Downloads/EO-IC100_PHASE3_ANDROID_TERMUX_CDC_PROBE.zip!APK_FINDINGS.md` (historical analysis notes, not a raw descriptor capture).
- **D**: `~/Downloads/EO-IC100_A05E_PHASE2E_DESCRIPTOR_DIFF.zip!README.md` and `~/Downloads/EO-IC100_A05E_PHASE2E_DESCRIPTOR_DIFF_ROBUST.zip!README.md` (experiment instructions, not captured results).

## Identity and observed firmware

| Status | Finding | Evidence |
| --- | --- | --- |
| CONFIRMED | Normal USB VID:PID is `04e8:a05e`. | R; P; H documents normal A05E identity. |
| CONFIRMED | Transient CDC/programmer VID:PID is `be57:0101`. | P; H records exact updater VID/PID comparisons; S/A record successful programmer transport. |
| CONFIRMED | Original recovery firmware runs in slot A as `0.04_051101_aa`. | S and A `enter-ota.txt` and `active-slot.txt`. |
| CONFIRMED | Modified development firmware successfully booted in slot B as `0.23_051101_ab`. | R explicitly records successful post-activation result. No separate post-reboot capture was found in S/A; this is a documented result. |
| CONFIRMED | `CHECK=1.1` was returned before Stage and Activation. | S/A `enter-ota.txt`. |
| CONFIRMED | Post-activation `CHECK=1.1` is documented alongside the modified B firmware version. | R confirmed-result block; distinct from A's pre-reboot query. |
| INFERRED | Firmware suffix `_aa` identifies A and `_ab` identifies B in this workflow. | S/A active-slot records and R boot result; wrappers use this mapping. Not established for other revisions. |

## Flash layout

| Status | Finding | Evidence |
| --- | --- | --- |
| CONFIRMED | Mapped flash base is `0x3c000000`; complete backed-up range is `0x80000` bytes = 524288 bytes = 512 KiB. | R; S logs `BULK_READ complete addr=0x3c000000 len=524288`; archive member size is 524288. |
| CONFIRMED | Active boot flag is at `0x3c004000`. | R; A records 4096-byte sector read and verified flag change there. |
| CONFIRMED | Backup boot flag is at `0x3c005000`. | R; A records backup creation and identical flag read-back. |
| CONFIRMED | Slot A image starts at `0x3c006000`. | R documented layout; source `A_START`. No A rewrite was needed to establish this finding. |
| CONFIRMED | Slot B image starts at `0x3c02e000`. | R; S burn/read-back logs and `STAGED_START`; A read-back. |
| CONFIRMED | Initial raw eight-byte flag was `1c ec 57 be 41 41 41 41`, not eight ASCII A bytes. | S/A logs. Do not classify the original flag solely by expecting `AAAAAAAA`. |
| CONFIRMED | Activation copied those original bytes to the backup flag, then verified active flag `42 42 42 42 42 42 42 42` (`BBBBBBBB`). | A `activate-log.txt`. |
| UNVERIFIED | Automatic bootloader fallback from a broken selected slot. | `docs/recovery.md` explicitly says this has not been demonstrated. |

## BES transport and command IDs

| Status | ID / behavior | Evidence |
| --- | --- | --- |
| CONFIRMED | `0x01`: small memory read, used for eight-byte flags. | R; P `readmem`; S/A `be01` responses. |
| CONFIRMED | `0x03`: bulk memory read. | R; P `read_range`; S/A successful `be03` acknowledgements and complete reads. |
| CONFIRMED | `0x50`: initial handshake. | P `bootstrap_programmer`; S/A response `be500003020001eb`. |
| CONFIRMED | `0x53`: RAM-programmer metadata. | P `bootstrap_programmer`; S/A response `be53010100ec`. |
| CONFIRMED | `0x54`: RAM-programmer binary transfer. | P `bootstrap_programmer`; S/A response `be54a201202a`. |
| CONFIRMED | `0x55`: run RAM programmer; a separate success response need not arrive before `0x60`. | P `bootstrap_programmer`; S/A explicitly record BE60 without separate BE55 success. |
| CONFIRMED | `0x60`: running-programmer capabilities/status. | S/A response `be6000060001009000004a`, decoded as version 1.0 and reported sector 36864. |
| CONFIRMED | `0x61`: `BURN_INFO`. | R; P `stage_image`; S burn setup and acknowledgement. |
| CONFIRMED | `0x62`: `BURN_BIN` sector programming. | R; P `stage_image` / `burn_rx_thread`; S four sector acknowledgements. |
| CONFIRMED | `0x65`: flash/flag operations, including validity-marker and flag erase/write. | R; P `stage_image`, `erase_flag_at`, `write_flag_bytes_at`; A successful BE65 responses. |
| CONFIRMED | CDC endpoints are bulk OUT `0x02` and bulk IN `0x82`; setup is 921600 baud, 8-N-1 with control-line state 0, line coding, then control-line state 3. | R documented reverse engineering; P `cdc_setup`, bulk helpers; successful S/A transport. |
| CONFIRMED | BES frame layout is `BE`, command, sequence, one-byte payload length, payload, checksum; checksum makes the byte sum `0xff`. | P `sendmsg`, `chk`, `frame_checksum_ok`; recorded S/A frames conform. |

## Bulk reads and burn protocol

| Status | Finding | Evidence |
| --- | --- | --- |
| CONFIRMED | Bulk-read request payload is address LE32 plus total length LE32 (eight bytes). Success is `BE 03 <seq> 01 00 <checksum>`, followed by raw bytes on bulk IN. | P `read_range` and its preceding comment; S/A acknowledgements and completed lengths. |
| CONFIRMED | Reads consume chunks up to 4096 bytes. Every full 4096-byte chunk is followed by a USB zero-length packet, including a final full chunk. Partial final chunks do not require that boundary. | P `read_range`; S logs boundaries through 524288/524288; A explicitly consumes the ZLP for a 4096-byte flag-sector read. |
| CONFIRMED | Burn metadata is start address LE32, image-data length LE32, sector size LE32. | P `stage_image`; S `BURN_INFO start=3c02e000 data=126404 sector=32768`. |
| CONFIRMED | Sector metadata is length LE32, CRC32 LE32, sector index LE16, then `00`; raw sector bytes follow. Sequence is `(193 + sector_index) mod 256`. | P `stage_image`; S sector transmission/ACK records and successful verification support this tested format. |
| CONFIRMED | Burn services bulk IN concurrently with bulk OUT; success ACK status is `0x60` and echoes sector index. | P `burn_rx_thread`; `docs/protocol.md`; S concurrent-burn and ACK records. |
| CONFIRMED | Tested burn used 32768-byte sectors and four ACKs, ending at sector index 3. Reported programmer sector value 36864 differs from selected burn sector size. | S; P `stage_image` chooses 32768 when reported value exceeds 32768. |
| CONFIRMED | Final four image-file bytes are mapped-start metadata excluded from flashed/read-back payload. Verification substitutes validity marker `1c ec 57 be` for the first four image bytes. | `docs/firmware-layout.md`; P `stage_image` and `verify_candidate`; S/A verify 126404 payload bytes. |
| INFERRED | Error status meanings `0x63` no burn info, `0x64` incorrect length, `0x65` CRC error, `0x66` sequence error, `0x67` erase error, `0x68` burn error. | P `burn_rx_thread` decoding; these errors were not exercised in reviewed successful logs. |

## Successful Stage and Activation

| Status | Finding | Evidence |
| --- | --- | --- |
| CONFIRMED | Stage completed the full-flash backup before writing B. Backup SHA-256 is `6ee1089955817ac0deda01aab8eb7531f3bdd11dd1604fd8c143d6d1538eb0cd`. | S `stage-log.txt`, `flash-backup.sha256`. |
| CONFIRMED | Stage fully read back and verified the 126404-byte staged B payload; active slot remained A and boot flag was not erased/written. | S `STAGE_SUCCESS.txt`: `STAGE_VERIFIED=YES`, `ACTIVE_SLOT=A`, `STAGED_SLOT=B`, `BOOT_FLAG_UNCHANGED=YES`; log completion; P byte comparison. |
| CONFIRMED | Activation fully re-read and verified B before flag modification, preserved the 4096-byte pre-activation flag sector, verified the backup flag, and verified the new active flag. | A `activate-log.txt`; P `activate`, `verify_candidate`. |
| CONFIRMED | Activation result is `ACTIVATION_VERIFIED=YES`, previous A, new B, no software reboot sent after activation. | A `ACTIVATION_SUCCESS.txt`. The wrapper's earlier OTA-entry sequence did issue `SYS_REBOOT`; the no-reboot result applies to the subsequent activation helper. |

## EQ table

| Status | Finding | Evidence |
| --- | --- | --- |
| CONFIRMED | Known table file offset is `0x1e4c4` in tested Samsung 0.23 firmware. | R; E documented static analysis. |
| CONFIRMED | Little-endian header is float32 left gain, float32 right gain, uint32 filter count (12 bytes). Each filter is uint32 type, float32 gain dB, float32 frequency Hz, float32 Q (16 bytes); eight records fit the observed region. | E; patcher uses `<ffI` and `<Ifff`. |
| CONFIRMED | Documented stock table has L/R gain 0.0 dB and two filters: -2 dB at 220 Hz/Q 0.6 and -2 dB at 9000 Hz/Q 8.0. | E documented firmware analysis. |
| INFERRED | Type mapping: 0 low shelf, 1 peak, 2 high shelf, 3 low pass, 4 high pass. | E explicitly calls this mapping likely. |
| CONFIRMED | Tested Diamond8 preset uses eight filters and global gain -5.7 dB. | E preset; S `package-assets.sha256` records the known modified-image hashes. This confirms the tested configuration, not a universal acoustic target. |

## Current HID descriptor findings

| Status | Finding | Evidence |
| --- | --- | --- |
| CONFIRMED | Normal A05E exposes audio/HID interfaces and no bulk endpoints. | H; subsequently captured directly in `readonly-device-check-20261007.json`. |
| INFERRED | Normal-mode HID endpoints cannot substitute for the transient CDC bulk programmer transport. | H updater-driver analysis; successful S/A transport uses the separate programmer path. |
| CONFIRMED | Current original-A HID is interface 3, interrupt IN `0x84`, maximum packet 3 bytes, interval 4 ms; HID 1.11; 47-byte report descriptor; Consumer Control report ID 1 with Volume Increment, Volume Decrement, Play/Pause input bits and padding. No Output or Feature main items are declared. | `readonly-device-check-20261007.json`; read-only check entry in `RESEARCH_LOG.md`. Actual button events were not captured. |
| CONFIRMED | Examined original 0.04 and official 0.23 A/B image HID descriptors are byte-identical. | Offline `hid_buttons.py` audit; `HID_BUTTON_RESEARCH.md`. |
| UNVERIFIED | Live HID descriptor after OTA transition or from modified B; any HID mechanism for DSP/EQ control. | No new live B enumeration; static equality is distinct from a live capture. |
| UNVERIFIED | Earlier suggestion that `CHECK` after `QUERY_SW_VER` disturbed post-reboot state. | D phrases this as “may”; not a demonstrated causal result. Do not promote it to a confirmed finding. |

Consult this file and `RESEARCH_LOG.md` before repeating experiments. Missing captures are evidence gaps, not authorization to run new USB requests.

## Normal-mode runtime EQ investigation (2026-10-07)

Evidence and reproducible commands: `RUNTIME_EQ_CONTROL.md`; `tools/research/runtime_eq_map.py`, `runtime_eq_audit.py`, and cached hash-identified audit/disassembly outputs under `research/cache/runtime-eq-*`.

| Status | Finding | Evidence |
| --- | --- | --- |
| CONFIRMED | Most relevant code/data is copied to SRAM at startup; flash load offsets are not a sufficient execution map. | Decoded startup loops in original backup and official A; reconstruction manifests. |
| INFERRED | SRAM code alias `0x00200000` corresponds to data alias `0x20000000`. | Startup destinations and stored Thumb callback addresses; use the explicit mappings in the report. |
| CONFIRMED | Internal chain is `usb_audio_open_eq` → `usb_audio_set_eq` → `audio_eq_set_cfg` → `hw_codec_iir_get_cfg` → `hw_codec_iir_set_cfg`. Selector only supports hardware-IIR type 2, configuration index 0, and loads a fixed compiled table. | Targeted original 0.04 and official 0.23 disassembly; report address table. |
| CONFIRMED | Original 0.04 fixed EQ table is at backup file `0x25c00` / SRAM `0x20017100`; official 0.23 table is at image `0x1e4c4` / SRAM `0x20015bec`. Both contain the documented two stock filters. | Offline structure parser and configuration-list pointers. |
| CONFIRMED | Registered vendor callbacks are original `0x0020eb8d` and official `0x0020d999` (Thumb bit included). Both recognize only `QUERY_SW_VER`, `QUERY_SN`, `SYS_REBOOT`, `SYS_SHUTDOWN`, `PING_THROUGH_VENDOR`, `CHECK`, and `FW_UPDATE`. | USB configuration offset `0x2c`, callback registration, compiled command tables and dispatch branches. |
| CONFIRMED | `PING_THROUGH_VENDOR` returns a fixed string rather than forwarding a DSP command. No EQ-config input branch exists in the examined registered vendor callbacks. | Vendor switch cases in both images. |
| CONFIRMED | Examined original UAUD Feature Unit paths support mute and volume selectors; other selectors have no EQ-record branch. HID descriptor exposes input buttons and no Output/Feature report. | Original UAUD setup/data dispatch and live descriptor capture. |
| INFERRED | Strong technical evidence supports no safe exposed normal-mode runtime EQ mechanism in the examined original 0.04 and official 0.23 firmware. Ordinary volume changes are distinct from editing the EQ configuration. | Combined registered vendor dispatch, fixed-preset EQ call graph, audio-class path, and HID surface. Scope/limits in `RUNTIME_EQ_CONTROL.md`; not an exhaustive proof about inaccessible ROM or other revisions. |
| UNVERIFIED | Runtime alteration of one EQ parameter reaching the DSP without reflashing; other firmware revisions or independent factory/debug interfaces. | No supported request path found; no new device experiment performed. |

## Physical buttons and HID remapping

| Status | Finding | Evidence |
| --- | --- | --- |
| CONFIRMED | Original/official button sample callbacks and debounce timer feed a registered application callback, mapper, 16-bit HID setter, and three-byte interrupt report. | Address table and control flow in `HID_BUTTON_RESEARCH.md`. |
| INFERRED | Resistor-ladder/GPADC detection; key codes 2/4/8 are center/volume+/volume−. | Numeric sample thresholds and stock Consumer Control mappings; physical wiring not measured. |
| CONFIRMED | Both drivers distinguish event 1 down, 4 up, 5 first long hold, 6 very long hold, and settled single/double/triple click events 7/8/9. | Timer callback branches and click-counter+7 dispatch in both versions; report contains exact addresses. |
| CONFIRMED | Stock application mapper forwards only events 1/4 and discards native click/long events. | Original `0x0020e338`, official `0x0020d174`, event mask `0x12`. |
| CONFIRMED | A same-length 47-byte descriptor can declare six one-bit usages plus ten padding bits, retaining report ID 1 and three-byte packets. | Authored descriptor parser/tests in `hid_buttons.py`; standard usages E9/EA/CD/B5/B6/CF. |
| CONFIRMED | Official completion handler invokes application callback with sent mask/error before completing its own reconciliation; official application callback has additional Play/Pause mode behavior. | `0x0020dc70` / `0x0020c7dc`; integration cautions in report. |
| INFERRED | A firmware strategy can implement the requested eight mappings by retaining native detection, replacing the mapper, expanding descriptor usages, and serializing action press/zero reports. | `HID_BUTTON_RESEARCH.md`; authored C queue compiles for Thumb; eleven offline tests including compiled-C/reference parity passed. |
| UNVERIFIED | Linked patch placement/image integrity, firmware transport adapter, physical gesture timing/wiring, final device execution and host voice-assistant response. | Strategy is established; no patched image or physical experiment performed. |

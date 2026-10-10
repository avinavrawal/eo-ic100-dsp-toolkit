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
| CONFIRMED | Stage completed the full-flash backup before writing B. Backup SHA-256 is digest retained locally and omitted from the public release. | S `stage-log.txt`, `flash-backup.sha256`. |
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

## Final runtime EQ feasibility review (2026-10-08)

| Status | Finding | Evidence / limits |
|---|---|---|
| CONFIRMED | 0.23 config object is initialized at `0x20015bec` (file `0x1e4c4`), pointer table at `0x20015c78`; format supports 140 bytes/eight filters, with 44 meaningful bytes in the stock two-filter config. Setter materializes coefficients in `0x20015fa4` and stores a retained pointer at `0x200162c0`. | Hash-keyed maps, parser and setter disassembly; `research/RUNTIME_EQ_FEASIBILITY_FINAL.md`. |
| UNVERIFIED | Complete RAM ownership: BSS clear, stack/heap limits, allocator, MPU permissions, and exhaustive direct/indirect readers/writers of config/pointer. | Existing maps cover initialized segments only. No safe relocation/allocation or in-place mutation contract established. |
| CONFIRMED | Stock path `usb_audio_open_eq(0,2)` reaches codec lifecycle setup, fixed config selector, coefficient generation and ACK-controlled bank setter; successful path clears busy after ACK; error exits can leave it set. | `CODEC_RECONFIGURATION.md`, focused cached disassembly. |
| CONFIRMED | USB-audio consumer serializes reviewed stock command-path EQ calls; this is not proof that it is the sole codec owner or that its task can tolerate a bounded wait. | Queue/call graph; task registration/priority and complete cross-context ownership unresolved. |
| CONFIRMED | Saved E3/E4/E5 evidence shows busy becomes stuck after playback-associated transaction entry; no instrumented request, ACK, bank toggle, or clear was observed. E5 reaches changed-config edge but not late staging hook. | Timestamped E3 lifecycle capture, E4/E5 decoded snapshots. E5 coverage leaves earlier branches and runtime pointers unresolved. |
| DISPROVEN | A safe one-gain prototype is justified by present evidence. | Memory ownership, worker scheduling, pre-request path, completion and rollback are not proven; stock waits are unbounded and status propagation is incomplete. This is a safety/readiness conclusion, not proof that all runtime EQ architecture is impossible. |

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

## Offline custom vendor EQ extension

Evidence: `CUSTOM_VENDOR_EQ.md`, authored `tools/research/custom_vendor_*` tools, and hash-identified reports under ignored `research/cache/custom-vendor/`. CONFIRMED below refers to static or explicitly modeled offline evidence, not physical execution.

| Status | Finding | Evidence |
| --- | --- | --- |
| CONFIRMED | Official B setup callback word at file `0x1d990` / RAM `0x200150b8` points to Thumb `0x0020dd11`; vendor callback word at file `0x1d384` / RAM `0x20014aac` points to `0x0020d999`. | Registration and focused disassembly; dispatcher map. |
| CONFIRMED | Vendor-only callback interception is too late to reject oversized OUT transfers safely; setup must validate first. Stock configured receive limit is 240 bytes. | Setup/data control flow; malformed-request CPU tests. |
| CONFIRMED | CAPS-only hooks the two callback words and appends code at XIP `0x0c04d000` / file `0x1f000`. EQ-test additionally applies the hash-locked codec-timeout/status patches; both preserve metadata, descriptors and boot EQ. | Hash-locked patcher, diff report and deterministic tests. |
| INFERRED | Appended allocation is preferable to an unproven FF/00 cave or supposedly unused debug function. It lies outside the old payload/startup copies, within the established B staging envelope, and has no original literal references. | Candidate/ownership report; computed/ROM accesses and real execution remain unverified. |
| CONFIRMED | Internal high-level API is Thumb `audio_eq_set_cfg` at `0x0020a939`: r0=0, r1=aligned 140-byte PEQ configuration, r2=2. Global L/R gains precede count and eight 16-byte records. | Static callers; CPU execution into stock coefficient generator/setter with disclosed math/MMIO models. |
| CONFIRMED | Injected GET uses C0/E0, wValue=454f, wIndex=4943, length=12 and returns the physically validated EOIC/version1/bands8/zero-flags bytes in both variants. Experimental SET uses 40/E1 with the same tags and four-byte finite common gain in [-12,0] dB. | Authored handler; 24 custom-vendor tests including CAPS parity and EP0 receive/status conventions. |
| CONFIRMED | Modeled -1 dB updates generated coefficients by the expected gain factor; modeled 0 dB restores them. CAPS-only rejects SET and performs no DSP mutation. | CPU tests; vendor transcendental math and bank acknowledgement are modeled. |
| CONFIRMED | Stock codec bank-switch acknowledgement loops have no timeout. | Static setter loops `0x0020a76a` and `0x0020a844`; experimental EQ image risk. |
| CONFIRMED (offline patch) | The generated EQ-test B image bounds both stock acknowledgement loops to 65,535 reads, restores bit 22 to observed bit 24, clears busy, preserves the software selector and propagates status 3 to the EP0 rejection path. Offline tests verify both forced timeout directions and byte-identical active banks. | `research/EQ_TEST_READINESS.md`, hash-locked patcher and CPU emulator. Physical timing and host STALL-versus-timeout remain UNVERIFIED. |
| CONFIRMED (offline tests) | Malformed SET payloads reject; -1 dB coefficient gain and 0 dB restore are modeled; stock boot EQ and CAPS response remain unchanged in EQ-test build. | 24 custom-vendor / 40 total offline tests. |
| CONFIRMED | One physical `SET_EQ_TEST(-6 dB)` returned host `LIBUSB_ERROR_PIPE`; no retry or restore request followed. | `research/cache/caps-macos/eq-test-postboot/eq-test-sequence.log`; exact request was `40 e1 4f 45 43 49 04 00`, payload `00 00 c0 c0`. |
| CONFIRMED (static/offline) | Correct E1 setup format is `bm=40`, `wValue=454f`, `wIndex=4943`, `wLength=4`; setup arms stock OUT state 3, callback success is return 0, and UAUD maps it to accepted state 6. Same receive/status convention is exercised for E1 float payload and stock OUT CHECK. | `SET_EQ_STALL_DIAGNOSIS.md`; cached EP0/UAUD disassembly; 24 emulator tests. No physical stage trace. |
| INFERRED | Given the exact valid payload and static E1 path, the PIPE most likely reflects handler rejection: unproven EQ-test image identity, inactive/uninitialized/busy EQ state, or bounded codec ACK timeout. Physical data does not distinguish these. | CAPS flags/version are identical across CAPS-only/EQ-test; enumeration does not prove codec live flags; no device-side trace was captured. |
| UNVERIFIED | Whether E1 reached the data handler or DSP setter, whether active EQ changed, and physical ACK/status-stage behavior. | Host PIPE does not identify the control stage; the one request was not retried and no post-failure request was sent. |
| INFERRED | A physical power cycle should restore the compiled boot EQ because runtime setting is RAM/DSP state and the stock table is preserved. | Static initializer and patch preservation; physical restoration not checked after the stalled request. |
| CONFIRMED | CAPS-only B boots normally after activation and physical reconnect, returning `0.23_051101_ab` and `CHECK=1.1`; USB audio output, two-channel input, and HID interface/report descriptor are present. | 2026-10-07 post-boot read-only enumeration/query/descriptor and macOS audio inventory; `research/RESEARCH_LOG.md`. |
| CONFIRMED | One read-only `GET_EOIC_CAPS` returned exactly `45 4f 49 43 01 00 08 00 00 00 00 00` on normal `04e8:a05e`. | `research/cache/caps-macos/caps-activation-03/probe/probe.log`, raw 12-byte capture and `evidence.json`; one request, bytewise match. |
| UNVERIFIED | Runtime EQ mutation behavior and measured audio continuity during a custom request. The later EQ-test SET attempt stalled, so no successful mutation is confirmed. | The earlier CAPS-only probe sent no SET; the separate E1 attempt and diagnostic are recorded in `SET_EQ_STALL_DIAGNOSIS.md`. |

## CAPS-only deployment review limitations

| Status | Finding | Evidence |
| --- | --- | --- |
| CONFIRMED | Exact CAPS-only extension has no reachable SET_EQ_TEST mutation implementation; retained EQ validator has no calls from either hook and no DSP writes. | Full current-image disassembly in `CAPS_ONLY_DEPLOYMENT_REVIEW.md`. |
| CONFIRMED | Existing `--select-slot` checks only an eight-byte slot header/validity marker before flag writes; full-target verification must be added to a reviewed recovery workflow. | `tools/termux/eoic100.c`, `verify_slot_valid` / `run_select_slot`. |
| UNVERIFIED | Software recovery from nonenumerating B when neither normal USB nor BE57:0101 is accessible. | No demonstrated independent recovery entry or automatic rollback; deployment review. |

## Prepared CAPS-only physical-test package

| Status | Finding | Evidence |
| --- | --- | --- |
| CONFIRMED | Preserved factory active flag sector has data beyond its first eight bytes; assuming an FF remainder is incorrect. | Exact original backup; package tests and documentation. |
| INFERRED | Established erase/write should produce canonical A/B flag sectors with eight selection bytes followed by FF; the new package requires full-sector physical verification of this expected shape. | Erase/write source ordering and known flag values; earlier verification covered flag bytes, not a complete new-package after-sector test. |
| CONFIRMED | New package compares complete original A (163840 bytes) and complete marked CAPS B (131072 bytes), restricts stage writes to B, activation writes to flag sectors and recovery writes to active flag only. | Dedicated source, RAM-only fake-device tests; not a physical test. |
| UNVERIFIED | Termux execution of the new package, USB-FD permission/callback delivery, reopening the still-running programmer across stage/activation, physical bring-up/recovery. | Physical scripts/helper not executed; `CAPS_PHYSICAL_TEST_PACKAGE.md`. |

## Native macOS physical read-only validation

| Status | Finding | Evidence |
| --- | --- | --- |
| CONFIRMED | Native libusb1.0.30 queried original A `0.04_051101_aa`, CHECK1.1, and matching normal audio/HID descriptors before the authorized OTA transition. | `PHYSICAL_WRITE_READINESS.md`; cached normal result. |
| CONFIRMED | Immediate in-process known OTA capture, CDC data-interface claim, BES handshake and RAM-programmer launch work on this Mac. Interface0 ACCESS failure does not prevent the observed data-interface/known-control sequence. | Cached immediate trace: BE50/53/54/60, programmer1.0/sector36864. |
| INFERRED | Separated transition/detection process timing/context is unreliable; use the successful in-process path. Exact reason for the first failed capture is not isolated. | First separated attempt + direct normal descriptor, successful immediate capture; no alternate request. |
| CONFIRMED | Entire current flash read is 524288 bytes, SHA digest retained locally and omitted from the public release. Full recovery A is unchanged; B is exact known Diamond8 when placeholder/footer are restored. | Reviewed state JSON and full read cache. |
| CONFIRMED | Current active flag is eight A bytes, backup eight B bytes; complete sector remainders FF. Separate-process programmer reopening and protected-state readback work. | Current full capture and reopen trace/readbacks. |
| CONFIRMED | Historical backup differs in seven record-sector bytes at 0x3c07d000; both records have valid CRC32 over offsets8..24 and current sector is stable across readbacks. | Reusable `flash_state.py`, NV-header/reopen reports. |
| UNVERIFIED | Record semantics/time/cause; actual CAPS boot/probe/audio continuity, native persistent burn/activation/recovery operations, independent nonenumeration recovery/fallback. | Read-only authorization boundary; no persistent commands or custom probe executed. |

## Native macOS CAPS-only Stage

| Status | Finding | Evidence |
| --- | --- | --- |
| CONFIRMED | User-approved stage wrote only inactive B `[0x3c02e000,0x3c04e000)` and its validity marker; no A or flag write occurred. | `research/cache/caps-macos/caps-deploy-01/stage/stage.log`; pre/post full-flash byte comparison. |
| CONFIRMED | Full marked B readback is byte-identical to the approved CAPS-only image payload plus marker; SHA-256 `bf92856c12779f7bbbff1b80d75d0d5d866254c4bd01b44ee328608669ddb52c`. | Offline receipt `research/cache/caps-macos/caps-deploy-01/stage/verification.json`; saved `b-staged.bin`. |
| CONFIRMED | Full A remains identical to pre-stage and original backup, SHA-256 digest retained locally and omitted from the public release; active A and backup B flags and their complete sectors are unchanged. | Saved A/flag readbacks and full-flash snapshots; offline receipt. |
| CONFIRMED | Full flash outside B is unchanged; pre-stage SHA digest retained locally and omitted from the public release, post-stage SHA digest retained locally and omitted from the public release. | Offline comparison of full 512 KiB snapshots and stage log. |
| CONFIRMED | CAPS-only B booted in normal mode after the user's physical reconnect; firmware version, CHECK, audio input/output, and HID descriptors were read successfully. | 2026-10-07 read-only post-boot check; `research/RESEARCH_LOG.md`. |
| CONFIRMED | GET_EOIC_CAPS response is the expected 12-byte CAPS structure. | Single authorized probe; `research/cache/caps-macos/caps-activation-03/probe/evidence.json`. |
| UNVERIFIED | Audio continuity during a custom request and any runtime EQ mutation. | Only the read-only CAPS request was sent; no SET_EQ_TEST. |
| CONFIRMED | The separately approved activation attempt aborted during native USB identity enumeration before device open/CDC setup or any flag access; no persistent command was issued and no retry occurred. | `research/cache/caps-macos/caps-deploy-01/activate/activate-running.log`; reviewed `native_open` call ordering. |
| CONFIRMED | The initial activation attempt left flags unread because sandboxed libusb enumeration returned no devices; subsequent activation in the USB-capable wrapper context verified and changed selection as approved. | Abort and success logs under `research/cache/caps-macos/caps-activation-02/` and `caps-activation-03/`. |
| CONFIRMED | A later read-only enumeration sees exactly one EO-IC100-related device, `be57:0101` (bus 1/address 2), expected by the activation programmer path; no `04e8:a05e` or duplicate match is currently visible. | `caps_readonly enumerate` and read-only IORegistry descriptor inspection on 2026-10-07. |
| UNVERIFIED | Whether the earlier exact-count activation abort saw zero or multiple `be57:0101` devices. | The abort log records only the generic count failure; current enumeration cannot reconstruct prior USB state. |
| CONFIRMED | Revised read-only stabilization observed exactly one total USB device, `be57:0101`, on three consecutive polls over 209 ms. | Native read-only stable enumerator output; no device open, CDC, or USB transfer. |
| CONFIRMED | A subsequent activation-process enumeration saw zero devices on all 97 polls over 9.982 seconds and aborted before open/CDC/flags. | `research/cache/caps-macos/caps-activation-02/activate/activate-running.log`. |
| INFERRED | The discrepancy is caused by launch context: standalone `caps_readonly` used its approved unrestricted prefix, while Python activation and its child ran sandboxed, where libusb exposed an empty list. | Successful external read-only enumeration immediately before sandboxed zero-device poll sequence; no device operation intervened. |
| CONFIRMED | In the USB-capable context, wrapper preflight and native activation each observed one stable `be57:0101`, then activation reverified full A/B and both flags before changing flags. | `research/cache/caps-macos/caps-activation-03/activate/`. |
| CONFIRMED | Active flag now selects B (`BBBBBBBB`); backup flag stores previous A (`AAAAAAAA`). Both complete flag readbacks were verified. | `activate-running.log`, `backup-flag-after.bin`, `flags-after.bin`, `verification.json`. |
| CONFIRMED | Activation did not write firmware, send BURN commands, issue CAPS/SET_EQ_TEST, reboot, or power-cycle. | Reviewed activation code path and successful phase log (`CAPS_SOFTWARE_REBOOT_SENT=NO`). |

## Diagnostic EQ-test build — offline evidence only

| Status | Finding | Evidence |
| --- | --- | --- |
| CONFIRMED | Diagnostic EQ B file SHA-256 is `63826ca08bcb0687a1a620673526dd86792b24f4d470245fe536787be1bcd61a`; official input/base hashes are enforced and rebuild bytes match. | `EQ_DIAGNOSTIC_READINESS.md`; deterministic patcher/tests and ignored report. |
| CONFIRMED | Diagnostic E0 is `454f49430100080001000000` (EQ enabled flag1), while original CAPS-only and hardened EQ images remain unchanged. E2 is IN `c0/e2/454f/4943/32`, returns EQDG/protocol1 plus trace, status, timeout and readiness. | 18 diagnostic tests, wire decoder and response fixtures. |
| CONFIRMED | Both hardened ACK wait bodies are byte-identical; logging wrappers preserve modeled setter arguments/coefficient/MMIO/poll behavior. Forced set/clear ACK failures are bounded, preserve modeled active bank, return status3/STALL and identify timeout mask1/2. | Diagnostic timeout/parity tests; 82 total offline tests passed. |
| CONFIRMED | Actual EP0 state-6 IN-completion instrumentation at 0x0020641e distinguishes setter success/status armed (events0x13f) from completion (0x33f). | Stock EP0 branch execution and displaced-instruction/MMIO parity tests. |
| CONFIRMED | State/reply occupy owned RX tail [0x200198b4,0x200198f4); diagnostic OUT receive maximum is 176 bytes. Larger OUT requests fail before original receive setup. | Hash-locked registration and absolute-pointer screen; setup/storage tests. |
| UNVERIFIED | Physical diagnostic boot/audio/class-request compatibility, every computed RX alias, buffer reinitialization lifecycle, IRQ/stack/watchdog margin, E2 physical completion and actual E1 DSP effect. The previous physical STALL cause remains unresolved. | CPU/MMIO tests are offline; no physical operation performed for this build. |
| INFERRED | Manual power cycle should reload unchanged static boot EQ; a STALL alone does not establish whether a setter ran. | Preserved boot EQ and firmware callback/status separation; not retested physically. |

## Latest diagnostic deployment gate — 2026-10-07

| Status | Finding | Evidence |
| --- | --- | --- |
| CONFIRMED | After the user's reported power cycle, native normal read saw `04e8:a05e`, but the firmware reply failed exact recovery-A `0.04_051101_aa` comparison. CHECK was not sent; diagnostic deployment aborted before any transition or write. | `research/cache/caps-macos/diagnostic-deploy-20261007/normal/normal-read.log`; `result.json`. |
| UNVERIFIED | Exact currently running firmware version/suffix and CHECK after that power cycle. The helper aborts without logging the differing version bytes. | No retry/query after mismatch. |

## Latest normal-mode raw identification — 2026-10-07

| Status | Finding | Evidence |
| --- | --- | --- |
| CONFIRMED | Normal `04e8:a05e`, bus1/address1; QUERY_SW_VER raw14 bytes spells `0.23_051101_ab`; CHECK raw3 bytes is `1.1`. Stock recovery A is not currently running. | `research/cache/caps-macos/normal-identity-diagnosis-20261007/evidence.json`. |
| CONFIRMED | Exactly one authorized E0 returned `454f49430100080000000000`, protocol1/bands8/flags0. No E1/E2/OTA/persistent operation occurred. | Same raw evidence and fixed read-only helper. |
| UNVERIFIED | Whether the running patched B is CAPS-only or hardened EQ-test: their permitted version/CAPS responses are identical. Diagnostic flags1 B is not indicated. | Shared reply bytes in the two hash-locked builds; no discriminator requested. |

## Latest verified recovery selection — 2026-10-07

| Status | Finding | Evidence |
| --- | --- | --- |
| CONFIRMED | Approved known programmer-entry/full-flash read found intact original A; marked installed B matches exact CAPS-only payload SHA-256 `bf92856c12779f7bbbff1b80d75d0d5d866254c4bd01b44ee328608669ddb52c`, resolving the version/CAPS-only ambiguity. | `research/cache/caps-macos/recovery-a-approved-20261007/transport/flash-current.bin`; prewrite verification. |
| CONFIRMED | Approved recovery operation reverified complete A and flags, changed only active selection BBBBBBBB to AAAAAAAA, and verified both full flag sectors. Backup remains AAAAAAAA unchanged; neither firmware image was rewritten or staged. | Same session `recover/` readbacks/log and independent `verification.json`. |
| UNVERIFIED | Recovery A normal boot after this selection change; user physical power-cycle is required. No software reboot was sent after the write. | Stopped after verified flag readback; device left in programmer mode. |

## Latest diagnostic-B deployment — 2026-10-07

| Status | Finding | Evidence |
| --- | --- | --- |
| CONFIRMED | Recovery A booted after user's power cycle: normal04e8:a05e, version0.04_051101_aa, CHECK1.1. | `research/cache/caps-macos/diagnostic-deploy-after-A-20261007/normal/normal-read.log`. |
| CONFIRMED | User-approved diagnostic image `63826ca08bcb0687a1a620673526dd86792b24f4d470245fe536787be1bcd61a` was staged only in inactive B and full131072-byte marked B readback matched; marked hash `2ec62930e2368ce5a3cd8bb18fe84bc925d88cc81879a97ddc9fd928c8209183`. | Same session stage verification/readbacks. |
| CONFIRMED | Full recovery A and both flags were unchanged by Stage; all flash outside B unchanged. Activation reverified complete A/B/flags, used reviewed backup procedure and verified active BBBBBBBB/backup AAAAAAAA. No custom request/reboot followed. | Same session independent `verification.json`, stage/activation logs. |
| UNVERIFIED | Diagnostic B normal boot/audio/HID/CAPS/E2 and runtime mutation; user physical power-cycle and distinct later request authorization are still required. | Stopped after activation flag verification, device left in programmer mode. |

## Diagnostic runtime-EQ physical test — 2026-10-07

| Status | Finding | Evidence |
| --- | --- | --- |
| CONFIRMED | Diagnostic B booted in normal mode: 04e8:a05e, version0.23_051101_ab, CHECK1.1, stereo audio input/output and expected HID descriptor. Exactly one CAPS response matched flags1. | `research/cache/caps-macos/diagnostic-runtime-20261007/evidence.json`. |
| CONFIRMED | Exactly one -6.0dB E1 transfer returned four bytes (libusb result4). E2 records seen/matched/callback/payload events0x0f then runtime guard outcome2, setter resultFFFFFFFF, timeout mask0. DSP setter was not called. | Raw E2-before/after in physical evidence; after readiness snapshot0x1b. |
| CONFIRMED | USB remained responsive for one E2-after. CoreAudio device/queue reported running through observation; callbacks advanced83 to114 without error. User heard a continuous tone then it stopped and did not play again. | Same evidence and user observation. |
| UNVERIFIED | Exact runtime guard that rejected at E1, audible gain change, and why the user heard the tone stop. E2 readiness is sampled after the request; its missing not-busy bit is consistent with busy but is not proof of rejection-time state. | No further request/experiment authorized or performed after the one-shot test. |

## Runtime EQ guard details — offline follow-up, 2026-10-07

| Status | Finding | Evidence |
| --- | --- | --- |
| CONFIRMED | Old E2-after readiness `0x1b` means EQ enabled, codec initialized, supported rate, two-band stock preset, but “not busy” false. It is a post-E1 snapshot; exact rejecting predicate at the earlier branch is not historically provable from this E2 format. Busy at `0x200162b4` is the leading candidate only. | Saved physical E2 bytes plus readiness decoder. |
| CONFIRMED | Actual handler checks EQ-enabled `0x200162cd`, codec initialized `0x200162b8`, update-not-busy `0x200162b4`, rate `0x200162c8`, stock config at `0x20015bec`, and count `0x20015bf4` before calling `audio_eq_set_cfg`. No explicit audio-stream-active or bank-selector preguard exists. | Source and targeted 0.23 disassembly; `research/EQ_GUARD_DIAGNOSIS.md`. |
| CONFIRMED | Stock setter sets busy before bank programming and clears it after acknowledgement. This is a runtime transaction flag; normal safe condition is its natural clear after the existing codec update completes. | Disassembly at `0x20a478` and `0x20a774`; timeout cleanup in hardened extension. |
| CONFIRMED | Samsung’s stock call chain is USB-audio EQ open/configuration → fixed preset selector → high-level EQ setter → hardware IIR setter. Seven open/configuration call sites exist; static call graph does not establish whether any occurs during active streaming. | Cached EQ call graph and targeted 0.23 disassembly. |
| CONFIRMED | Offline guard-trace candidate has unique CAPS flags `03`, unchanged 32-byte E2 wire size, and per-predicate evaluated/pass event pairs in bits 10–21. It does not bypass guards or change DSP setter/ACK behavior. SHA-256 `fc0f8a27471c829f120d48cce700a4b3976aa8a887d6bb71314dade36260a531`. | Deterministic two-build comparison and offline patch report. |
| UNVERIFIED | Which predicate was false at the original E1 branch, whether the busy value later cleared naturally, and whether stock setters run while samples are streaming. | Requires separately authorized diagnostic deployment/read-only telemetry; no device access performed during follow-up. |

## EQ update-state byte lifecycle — offline follow-up, 2026-10-08

| Status | Finding | Evidence |
| --- | --- | --- |
| CONFIRMED | Physical guard-trace E1 evaluated `codec_update_not_busy` and failed at branch time. E1 returned USB success, the setter was not called, and audio continued. This supersedes the earlier E2-only inference. | `research/cache/caps-macos/diagnostic-runtime-guard-trace-20261008/evidence.json`. |
| CONFIRMED | In official 0.23, `hw_codec_iir_set_cfg` sets `0x200162b4=1` at `0x20a478`, normally clears it after ACK at `0x20a774`, and codec re-enable path clears it at `0x20a884`. Two post-set error exits (`0x20a5ea`, `0x20a78c`) return status 3 without cleanup; stock ACK waits are unbounded. | Targeted radare2 disassembly and pointer-literal scan documented in `research/EQ_BUSY_FLAG_LIFECYCLE.md`; offline, hash-locked inputs. |
| CONFIRMED | Modified diagnostic firmware adds two timeout-only clears at `0x0c04d1be` and `0x0c04d1fe`. They were not reached by the physical test because the busy guard rejected before setter entry. | Cached generated Thumb disassembly and saved E2 events. |
| CONFIRMED | `0x200162b4` is the correct busy byte for 0.23 modified B. Original 0.04 uses `0x200177cc` for its corresponding EQ update state. | Version-specific setter/lifecycle disassembly; 0.23 physical guard trace. |

## Codec reconfiguration and EQ RAM source — offline follow-up, 2026-10-08

| Status | Finding | Evidence / limits |
|---|---|---|
| CONFIRMED | 0.23 has seven `usb_audio_open_eq` callsites under the USB-audio command consumer or its helpers. On the `(0,2)` route, `0x20c840` calls `0x20a994(config,0x18,2)`, which invokes `0x20a868(config,1)`, followed by `usb_audio_set_eq(2,0)` at `0x20c8ec`. | `eq-call-graph.json` and selected disassembly; callsite presence does not establish execution count or active-playback timing. |
| CONFIRMED | If `codec_initialized` is already nonzero and enable argument is 1, `0x20a868` clears `0x200162b4` at `0x20a884` while updating lifecycle state. The subsequent stock open-EQ path invokes the EQ setter. The separate disable path `0x20a9b0 -> 0x20a900(1)` does not clear the busy byte. | Cached helper disassembly. This is lifecycle-coupled behavior, not a standalone transaction reset. |
| CONFIRMED | 0.23 selector table `0x20015c78` points to config `0x20015bec` (official image offset `0x1e4c4`); conversion scratch is at `0x20015fa4`. Original 0.04 uses config `0x20017100`, list `0x2001718c`, and busy byte `0x200177cc`. | Existing image mapping and EQ call graph. |
| CONFIRMED | The traced 0.23 EQ setter reads a RAM config pointer, generates coefficients and stages them to codec coefficient-bank registers when the hardware path succeeds; no runtime flash read appears in the traced setter chain. | Static disassembly. Exact startup copy instruction and exhaustive runtime writers to the config object were not audited here. |
| INFERRED | A validated RAM shadow could be applied through the existing configuration/setter chain without reflashing, if it is published and consumed in a serialized command context. | Requires atomic config publication, proven stream quiescence and rollback; none are yet established. |
| UNVERIFIED | Later `0x20b184(0)` and `0x211db8(0,0)` calls in `usb_audio_open_eq(0,2)` stop/resume audio; ordinary host format changes exercise the EQ path while streaming; old 0.04 has identical command branch conditions. | Call order is known, but semantic effects and old dispatcher parity were not fully reconstructed. |
| UNVERIFIED | A disable/re-enable without the full `usb_audio_open_eq(0,2)` path reloads or reapplies EQ. | Disable clears codec/peripheral state but not busy; no EQ setter call was established in that helper alone. |
| INFERRED | A stock error exit that failed to clear the flag, or an ACK wait that never completed, can strand the byte nonzero indefinitely. A transient overlap with a normal update remains possible. The physical trace identifies the nonzero value but not which writer produced it. | Control flow has unpaired post-set exits and unbounded waits; no writer-attribution telemetry was captured. |
| INFERRED | The safest design is to validate in the USB callback and queue the requested update to a codec/audio worker that serializes with existing updates. The static call graph does not establish that an existing queue is strictly required. | Setter is synchronous, shares transaction state, and polls hardware; callback scheduling/queue ABI is not fully established. |
| UNVERIFIED | Whether the physical busy byte later cleared, which stock setter branch last wrote it, whether the normal stream path can leave it stuck in the observed state, and the exact generic startup BSS-clear instruction affecting it. | No additional device reads were performed; reconstructed RAM excludes BSS. |

## Deferred runtime EQ integration — offline review, 2026-10-08

| Status | Finding | Evidence |
| --- | --- | --- |
| CONFIRMED | `af_thread` is a stream-handler loop with lost-signal and handler-overrun reporting; it is frame-critical. Calling the synchronous EQ setter there risks delaying audio work. | Cached focused radare2 windows `eq-audio-worker-loop.txt` / `eq-audio-worker-window.txt` and `af_thread` strings. |
| SUPERSEDED | Earlier indexes identified only the queue overflow diagnostic and did not resolve a consumer. | Updated by the targeted scheduler trace below. |
| CONFIRMED | A 32-bit USB-audio command ring at `0x200196ac` (`0x20019634` item storage) is initialized at `0x20d53c`, pushed at `0x20d54c`, popped at `0x20d5b4`, and consumed by `usb_audio_cmd_handler` at `0x20d1c8`. The application loop at `0x20aa20` calls that handler at `0x20aa82`. | Cached focused disassembly and `research/cache/custom-vendor/codec-scheduler-analysis.json`. |
| CONFIRMED | The consumer's stream/configuration routes call `usb_audio_open_eq`, so stock reviewed EQ reconfiguration passes through this command-dispatch context. | `eq-call-graph.json`; direct callsites resolve to the handler or helpers called from it. |
| UNVERIFIED | Exact RTOS task registration/priority, complete global codec serialization, and end-to-end EP0 caller/mailbox contract. The raw push itself is bounded and nonblocking. | Existing initialized-RAM call graph does not resolve task setup or every runtime path. |
| SUPERSEDED | The initial queue trace left raw insertion and queue-full behavior unresolved. | Updated by the focused queue-semantics trace below. |

## USB-audio command queue semantics — 2026-10-08

| Status | Finding | Evidence |
| --- | --- | --- |
| CONFIRMED | Ring capacity is 30 four-byte entries (120-byte backing store). Layout: read/head +0, write/tail +1, count +2, capacity +3, high-water +4, data pointer +8. Command ID is bits 0–7; observed arguments are bits 8–23; the reviewed dispatcher ignores bits 24–31. | `research/cache/custom-vendor/codec-queue-semantics.txt`, `codec-app-init.txt`; `0x20cf68` loads capacity `0x1e`. |
| CONFIRMED | Raw push `0x20d54c` performs one bounded PRIMASK-preserving try and returns full without waiting. The wrapper `0x20ab28` calls raw push once, then on full loops through queue dump/status diagnostics. | `research/cache/custom-vendor/codec-queue-semantics.txt`. |
| CONFIRMED | App loop `0x20aa20` invokes the queue consumer at `0x20aa82`, calls `0x209a8c`, then loops. It is distinct from frame-critical `af_thread`; task registration, RTOS priority, and preemption relation remain unknown. | Focused scheduler cache and `research/CODEC_SCHEDULER.md`. |
| CONFIRMED | Successful stock enqueue calls `0x204758(3)` after raw push; that helper sets bit 3 in event word `0x20019a0c` with a short PRIMASK-preserving update. | Enqueue wrapper and helper disassembly in `codec-queue-semantics.txt` and `codec-queue-scheduler-helpers.txt`. |
| INFERRED | EP0 can use the same nonblocking sequence (atomic mailbox publish, one raw push, then `0x204758(3)` on success) without calling an RTOS wait. Actual callback constraints, SVC/event wake semantics, and firmware mailbox contract still need validation. | Static push/wrapper/helper control flow; no runtime patch/test. |
| UNVERIFIED | Whether every codec update is serialized by the command consumer, and whether bounded ACK polling in the app task can affect audio at its actual priority. | Stock EQ call graph covers reviewed USB-audio reconfiguration paths only. |
| CONFIRMED | Busy may remain set indefinitely after stock missing-ACK/error paths; a queued request must defer only for a finite policy window and then fail without clearing/bypassing the flag. | `research/BUSY_FLAG_STATE_MACHINE.md`. |
| CONFIRMED | Offline queue/dispatcher model passes 14 tests for FIFO, capacity/full, EP0 queue-full handling, concurrent producer/consumer, immediate EP0 rejection on lock contention, busy/ready, busy timeout, ACK timeout rollback model, existing-command ordering, malformed gains, and no setter work on `af_thread`. | `tools/research/codec_queue_model.py`, `tools/research/test_codec_queue_model.py`. |
| UNVERIFIED | The Python model does not prove firmware scheduler timing, EP0 integration, mailbox ABI, hardware ACK behavior, or transactional EQ rollback in the stock setter. | Model scope. |
| UNVERIFIED | Task registration/priority for `0x20aa20` remains unresolved: no direct call, literal pointer, or raw 32-bit app-entry pointer was found in the hash-keyed initialized-RAM/flash indexes. Runtime-built or indirect registration remains possible. | `research/cache/custom-vendor/codec-queue-runtime-audit.json`. |
| CONFIRMED | E5 playback trace reached the changed-configuration edge and passed the busy check, but did not increment its late `0x20a6d4` copy checkpoint. This does not prove coefficient staging was bypassed: the setter has earlier coefficient-write blocks at `0x20a4d8` and `0x20a520`, outside E5 coverage. No specific Track A correction is supported by this trace. | `research/cache/caps-macos/codec-ack-progress-deploy-20261008/postboot/e5-decoded.json`; cached official 0.23 disassembly `focused-disassembly-d09806e4c6e6b599.txt`. |
| CONFIRMED | From changed edge `0x20a462`, the static path copies a fixed config header, tests count at `0x20a4c2` (`bls 0x20a5a8`), selector at `0x20a4d6` (`bne 0x20a5b6`), another count at `0x20a506` (`bls 0x20a5ee`), selector at `0x20a518` (`bne 0x20a600`), then consistency checks can retry `0x20a462`; a later state check at `0x20a6b4` can branch to `0x20a790` before the `0x20a6c0` loop containing `0x20a6d4`. E5 records none of those branch outcomes. The pointer-comparison copy loops are finite for valid source/end pointers, but their runtime pointer values are not captured. | Cached disassembly and `codec-ack-progress-report.json`; physical E5 response `e5-decoded.json`. |
| CONFIRMED | In the codec-ACK progress firmware, E5 live busy remained 1 with register snapshot `0x1f`, selector/request/ACK zero before playback, during controlled playback, immediately after the player was terminated/reaped, and 2 seconds after release. E4 retained one transaction entry and zero request/ACK/busy-clear/error events; its `0x88` register field is the last event-time snapshot, not the E5 live register. | `research/cache/caps-macos/pause-apply-20261008/pause-apply.log`. |
| UNVERIFIED | `codec_initialized` cannot be determined from the installed progress image's E4/E5; its E2 response is fixed empty diagnostic data. No pause-and-apply ready window was observed because busy remained set. | Probe ABI in `custom_vendor_codec_ack.c`; pause-and-apply capture, 2026-10-08. |
| UNVERIFIED | No cached finding establishes a USB PCM processing callback's sample format, channel/buffer layout, ownership, deadline budget, or atomic coefficient-update contract. The known `af_thread` is frame-critical; the app/command loop's task priority is unresolved. | Existing scheduler/lifecycle reports and targeted search of cached research, 2026-10-08. |
| CONFIRMED | Stock enqueue sets event bit 3 via `0x204758(3)` after a successful push. It ORs `1<<3` into `0x20019a0c`; `0x20d1d0` clears bit 3 at command-handler entry. Both set/clear helpers use short PRIMASK-preserving critical sections. | `codec-queue-semantics.txt`, `codec-event-bit-ops.txt`, `codec-command-dispatch-expanded.txt`. |
| INFERRED | Event bit 3 is a shared pending flag consumed by the software event service reached after the app loop drains the queue; no direct RTOS wake/scheduler call is present in the producer helper. Whether a task is blocked or promptly rescheduled is unverified. | `codec-event-service-expanded.txt`; caller flow at `0x20aa82`–`0x20aa8a`. |
| CONFIRMED | Command IDs `0x00`–`0x14` index the table at `0x20d20a`. ID `0x13` currently routes to generic unknown-command logging at `0x20d418`; it is the least disruptive candidate extension ID if special-cased there, preserving the `>0x14` fallback. | `codec-command-dispatch-expanded.txt`; generated ID map `codec-queue-runtime-audit.json`. |
| INFERRED | EP0 can perform one raw queue push and event-bit set without waiting: both primitives have fixed bounded work, no loop or scheduler call, and restore/preserve PRIMASK. This avoids the full-queue diagnostic wrapper. Actual callback integration and mailbox publication remain untested. | `codec-queue-semantics.txt`, `codec-event-bit-ops.txt`; no firmware patch. |
| CONFIRMED | If the busy byte never clears, a queued EQ command cannot safely reach the setter. The safe outcome is a finite pre-setter busy timeout/status, dropping the request and leaving the byte untouched; recovery requires natural codec lifecycle recovery. | Existing `BUSY_FLAG_STATE_MACHINE.md` plus deferred queue policy. |

## Recovery selection restored — 2026-10-08

| Status | Finding | Evidence |
| --- | --- | --- |
| CONFIRMED | From normal modified B, the authorized known transition exposed exactly one `be57:0101`; full 512 KiB flash read completed. A was active B (`BBBBBBBB`), backup selection A (`AAAAAAAA`). | `research/cache/caps-macos/recovery-guard-trace-A-20261008/transport/flash-current.bin` and phase log. |
| CONFIRMED | Before changing the boot flag, full A (163840 bytes) matched the preserved recovery image byte-for-byte, with valid header. | `recover/a-before.bin`; SHA-256 digest retained locally and omitted from the public release. |
| CONFIRMED | Only active boot selection changed B-to-A. Full readback verifies active `AAAAAAAA`; backup remains `AAAAAAAA` and its full sector is unchanged. No A/B firmware write, guard-image Stage, or software reboot occurred. | `recover/flags-before.bin`, `recover/flags-after.bin`, `recover/offline-verification.json`; reviewed native recovery log. |
| UNVERIFIED | Recovery A normal boot after the flag change. | User must physically unplug for 15 seconds and reconnect; no software reboot was sent. |

## Scheduler telemetry prototype — offline only, 2026-10-08

| Status | Finding | Evidence |
| --- | --- | --- |
| CONFIRMED | Deterministic experimental telemetry image derives from official Samsung 0.23 B hash `2f418d3a324ec4217c32c4bf98d43c3cd07d59d81f82974f29320d399fa769f3`; output is cached at `research/cache/custom-vendor/scheduler-telemetry.bin`, SHA-256 `9e626fe28abbff2905d618c626d78d6c3f1dc79157da39f22eb0de45bc1bdade`. | `custom_vendor_telemetry_patch.py`, deterministic report, seven focused tests. |
| CONFIRMED | The image uses E0 CAPS flags `04` and read-only E3 (`c0/e3/454f/4943`, 52 bytes). Counters cover app-loop calls, consumer calls, event-bit-3 set/clear, busy-zero/nonzero samples, queue-full, current/high-water depth, and raw timer totals/max. | `custom_vendor_telemetry.c`, `eoic_scheduler_telemetry_probe.py`, `SCHEDULER_TELEMETRY.md`. |
| CONFIRMED | E1 is rejected; the telemetry source has no EQ setter, busy-byte write, codec MMIO write, or `af_thread` hook. The stock boot EQ bytes and known descriptor bytes are preserved. | Hash-locked patch report and offline source/image invariants. |
| INFERRED | `consumer_calls` deltas taken during separately verified audio playback can establish that the software consumer is running during the playback interval; firmware telemetry does not itself prove stream-active state. | Existing candidate `0x20aa20` loop invokes `0x20d1c8`; no confirmed active-stream flag was identified. |
| UNVERIFIED | Live timing cost, timer frequency, task priority/stack alignment, actual USB callback behavior, and busy transitions across playback phases. The CPU emulator could not execute `MRS PRIMASK` in this environment (SIGILL), so wrapper equivalence is static/model-tested only. | Offline-only build and test scope; no device request was sent. |
| UNVERIFIED | RX capacity is lowered from 240 to 176 bytes to reserve a volatile state tail. Known stock command strings fit; compatibility with undocumented larger OUT payloads is not established. | Telemetry setup guard and existing stock RX buffer map. |

## Scheduler telemetry lifecycle capture — physical read-only, 2026-10-08

| Status | Finding | Evidence |
| --- | --- | --- |
| CONFIRMED | Device booted telemetry B as `04e8:a05e`, `0.23_051101_ab`, CHECK `1.1`; audio and HID interfaces were present. All E0 responses returned flags `04`. | `research/cache/caps-macos/scheduler-telemetry-lifecycle-20261008/lifecycle-full.log`. |
| CONFIRMED | Idle busy samples were 1,028 zero / 0 nonzero. In the first interval ending 2 seconds after playback began, 2,810 nonzero / 11 zero samples accrued (99.61%). Every later playback interval and all samples through 30 seconds after playback stopped were 100% nonzero; busy remained set at every snapshot. | `lifecycle-decoded.json`; raw timestamped E3 responses in `lifecycle-full.log`. |
| CONFIRMED | `consumer_calls` delta equaled app-loop delta in every interval. Calls ran at about 1,500/s during playback, then about 7–8/s after stop. Queue depth/full stayed 0; event bit-3 signals and clears remained paired, with no pending bit. | Interval counter deltas in `lifecycle-decoded.json`. |
| INFERRED | The busy state becomes set during audio startup/early playback and does not clear through the normal playback-stop path within 30 seconds. This is consistent with a transaction state remaining asserted or an ACK/recovery path that fails to complete; the capture does not identify the exact writer or hardware cause. | First E3 during playback; persistent nonzero samples after stop. Host audio playback alone does not prove codec/DSP activity. |

## Codec pre-request progress capture — physical read-only, 2026-10-08

| Status | Finding | Evidence |
| --- | --- | --- |
| CONFIRMED | The progress image booted as normal B: `04e8:a05e`, `0.23_051101_ab`, CHECK `1.1`; audio and HID interfaces enumerate. E0 returned flags `04`, and the read-only E5 response identified `EPRG` version 1, size 28. | `research/cache/caps-macos/codec-ack-progress-deploy-20261008/postboot/`. |
| CONFIRMED | At idle all six checkpoint counters were zero, software busy was 0, selector/request/ACK were 0, and register snapshot was `0x0000001f`. During the short tone, busy-check count became 1 with its BNE outcome false; changed-configuration count became 1 and equal-configuration count remained 0. | Raw E5 responses and `e5-decoded.json`. |
| CONFIRMED | No coefficient-copy checkpoint, main request checkpoint, or alternate request-clear checkpoint occurred during the sample. Immediately after playback, busy remained 1, selector/request/ACK remained 0, and register snapshot was `0x0000001f`. The host player was alive at the during-playback E5 sample. | `e5-playback.log`; before/during/after deltas in `e5-decoded.json`. |
| INFERRED | The observed transaction takes the changed-configuration path but stops before the first instrumented coefficient-copy point. The busy check itself did not take its BNE path in this sample. The diagnostic does not identify which intermediate decision prevented coefficient staging. | Sparse checkpoint deltas; no intermediate branch probes. |

## RAM-shadow runtime EQ prototype — offline model, 2026-10-08

| Status | Finding | Evidence / limits |
|---|---|---|
| CONFIRMED | Stock `usb_audio_open_eq(0,2)` order is lifecycle helper (`0x20a994 -> 0x20a868(config,1)`, conditional busy clear at `0x20a884`) followed by selector/setter (`0x20c8ec -> 0x20c800 -> 0x20a938 -> 0x20a424`). | Hash-keyed 0.23 disassembly; this does not prove stream stop/resume semantics. |
| CONFIRMED | Offline contract model validates E1 gain, stages a separate candidate config, queues command ID `0x13`, signals event bit 3, and only models pointer commit after acknowledged worker success. E6 status is read-only and E2 remains unchanged. | `tools/research/ram_shadow_eq_model.py`, `test_ram_shadow_eq_model.py`; no firmware image integration. |
| CONFIRMED | Busy deferral is finite in the model; timeout and setter/ACK failure do not clear busy and preserve the prior modeled active config/pointer. | Offline tests only; no proof of physical DSP bank rollback. |
| UNVERIFIED | Safe RAM reservation, command-dispatch hook safety, task timing, stream quiescence/resume, real setter completion status, and hardware rollback. | `research/RAM_SHADOW_EQ_PROTOTYPE.md`; these block firmware/physical readiness. |

## Runtime EQ RAM-allocation gate — offline, 2026-10-08

| Status | Finding | Evidence / limits |
|---|---|---|
| UNVERIFIED | No usable heap allocator ABI, bounds, initialization order, or ownership is established in the cached indexes. | Targeted searches over existing strings/function/call indexes found no allocator; absence of strings alone does not prove the firmware has no allocator. |
| CONFIRMED | The initialized-RAM reconstruction describes only three startup copy segments and explicitly excludes BSS; no BSS allocation/zeroing contract is recorded for the appended extension. | `runtime_eq_map.py`, `runtime-eq-official023-*/mapping.json`; this is insufficient to add a writable BSS range safely. |
| CONFIRMED | The deterministic extension linker accepts explicit read-only/executable sections and rejects writable/BSS allocated sections. Appended XIP bytes are not established as writable RAM. | `tools/research/arm_elf.py`, `custom_vendor_patch.py`. |
| CONFIRMED | The known 240-byte USB RX reservation is shared by EP0 and diagnostic state and is unavailable for EQ buffers. | Existing custom-vendor ABI and RAM-shadow prototype review. |
| INFERRED | Encoding a gain in the existing queue word could eliminate a separate pending-gain allocation, but applying it in the shared stock config cannot guarantee rollback without reliable setter completion and serialization. | Existing queue ABI and stock config pointer path; no safe fallback established. |

## In-place stock EQ configuration update — offline feasibility, 2026-10-08

| Status | Finding | Evidence / limits |
|---|---|---|
| CONFIRMED | 0.23 config at `0x20015bec` has a 12-byte `<ffI>` header plus two populated 16-byte `<Ifff>` filters (44 meaningful bytes; capacity eight bands/140 bytes). Band 0 gain is at `0x20015bfc`. | Hash-locked `audit.json`, binary parser and config layout. |
| CONFIRMED | The config is part of startup-copied SRAM. Conversion reads config values and writes generated coefficients to `0x20015fa4`; the hardware setter also stores the config pointer at `0x200162c0`. | Cached `0x20a938`, `0x20a178`, `0x20a424` disassembly. |
| INFERRED | CPU stores to the object are physically possible because its runtime address is SRAM. MPU write permissions and exhaustive runtime writers are not established, so this is not evidence that in-place edits are safe. | Startup mapping and bounded xrefs only. |
| CONFIRMED | Reviewed stock EQ-open routes serialize through the USB-audio command consumer, but serialization against every codec/config reader is not proven. | `eq-call-graph.json`, scheduler analysis. |
| CONFIRMED | The traced setter path consumes the existing RAM config and does not reload it from flash. No overwrite of the config by the traced stock reconfiguration path was found. | Selector/config/setter disassembly; not exhaustive whole-image writer proof. |
| CONFIRMED | Reliable rollback through the stock high-level path is unavailable: ACK waits are unbounded, and `audio_eq_set_cfg` does not propagate the low-level setter result to its caller. | Setter and caller disassembly / `eq-call-graph.json`. |
| UNVERIFIED | Whether the stored config pointer at `0x200162c0` is dereferenced by other runtime paths and whether the config has readers outside the serialized consumer. | Bounded EQ call graph does not recover every indirect/runtime access. |

## Ghidra headless runtime-EQ audit — 2026-10-08

| Status | Finding | Evidence |
|---|---|---|
| CONFIRMED | Official 0.23 reset/copy startup initializes source `[0x8a34,0x11e68)` at `0x20000140..0x20009574`, clears `0x20009574..0x200095d4`, copies `[0x11eb0,0x1e7bc)` to `0x200095d8..0x20015ee4`, clears `0x20015ee4..0x20015ee8`, and copies `[0x1ebec,0x1ec8c)` to `0x20015ee8..0x20015f88`. Initial MSP loaded is `0x20027ff0`. | Ghidra 12.1.4 headless `mapped-targeted-export.txt`, official input hash in export runner. |
| CONFIRMED | Original 0.04 startup copies `[0xec5c,0x19214)` to `0x20000140..0x2000a6f8`, clears `0x2000a6f8..0x2000a758`, copies `[0x1925c,0x25f04)` to `0x2000a75c..0x20017404`, clears `0x20017404..0x20017408`, and copies `[0x262fc,0x26394)` to `0x20017408..0x200174a0`. Initial MSP loaded is `0x20027ff0`. | Ghidra 12.1.4 headless `original004/mapped-targeted-export.txt`; original input hash in export runner. |
| CONFIRMED | Only four bytes separate the first 0.23 BSS clear end from the next initialized segment; it is not a usable subsystem allocation. | Startup loop bounds in Ghidra export. |
| CONFIRMED | Targeted Ghidra exports resolve official EQ config/table/pointer/busy/scratch and `0x403000e0` literal references; original 0.04 selected EQ functions resolve config `0x20017100`, table `0x2001718c`, busy `0x200177cc`, and peripheral references. | `research/cache/ghidra-runtime-eq/{official023,original004}/mapped-targeted-export.txt` (ignored). |
| UNVERIFIED | Total SRAM boundary, heap ABI/bounds, task stacks, MPU write policy, and exhaustive indirect readers/writers remain unknown. | The mapped startup regions and targeted function set are bounded, not a whole-program ownership proof. |

## Custom runtime-EQ architecture — offline design, 2026-10-09

| Status | Finding | Evidence |
|---|---|---|
| CONFIRMED | 0.23 first copy is `[0x8a34,0x11e68)` to `0x20000140..0x20009574`; zero-fill ends at `0x200095d4`; next copied data starts at `0x200095d8`, leaving only four bytes. | Ghidra startup LDR literals and copy/clear loops; corrected hash-locked map. |
| INFERRED | Reset MSP `0x20027ff0` may be the top of a 0x28000-byte SRAM window from `0x20000000`. | Reset literal only; physical SRAM boundary and task-stack allocation are not proven. |
| UNVERIFIED | No exact 0x400-byte exclusively owned writable address, heap bounds, task-stack map, or MPU write policy is established. | Startup map and scheduler artifacts do not describe runtime allocations. |
| CONFIRMED / SCOPED | Existing USB-audio command ring has 30 four-byte items; `0x20aa20`/`0x20d1c8` is distinct from frame-critical `af_thread`; `0x13` is a candidate unused dispatcher ID. | Focused 0.23 queue/dispatcher disassembly; task priority and full codec-owner scope remain unknown. |
| CONFIRMED / PARTIAL | Stock update uses register `0x403000e0`, request bit 22, ACK bit 24, and coefficient-write region `0x40302000..0x40302340`; stock waits are unbounded. | Ghidra export and prior physical diagnostic traces. Exact custom bank ABI and timeout recovery are unverified. |
| PROPOSED | E7/E8 custom SET_GAIN/status protocol and 0x400-byte logical pool are documented, with no physical RAM base assigned. | `research/CUSTOM_RUNTIME_EQ_ARCHITECTURE.md`; protocol IDs untested and collision audit incomplete. |
| UNVERIFIED | Safe coefficient-worker task, complete serialization with all stock codec paths, and a post-codec-init reapply hook. | Existing queue serializes reviewed commands only; task registration/priority and lifecycle completion callback unresolved. |

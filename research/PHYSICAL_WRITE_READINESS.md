# EO-IC100 CAPS-only macOS physical-write readiness

2026-10-07. **CAPS-only B staging and approved activation completed and verified.** The wrapper ran in the USB-capable context; read-only preflight and native activation each observed one stable `be57:0101` for three consecutive polls. Before any flag write, full recovery A, full staged CAPS B, and complete active/backup flag sectors matched their reviewed values. Active now selects B (`BBBBBBBB`); the backup flag stores previous A (`AAAAAAAA`). No firmware write, CAPS request, software reboot or power-cycle followed.

## What was physically validated

1. Native Homebrew libusb 1.0.30 opened exactly one normal `04e8:a05e` outside the filesystem/USB sandbox. The initial sandbox attempt saw no matching device; it was not evidence of physical absence.
2. Known QUERY_SW_VER and CHECK returned exact 14-byte `0.04_051101_aa` and three-byte `1.1`. Normal configuration is 320 bytes/four interfaces; audio endpoints and HID interface 3 / IN 84 / packet 3 / interval 4 match previous findings. The 47-byte HID report is identical to the prior capture. No driver detach or configuration change was used in normal mode.
3. The authorized known FW_UPDATE/ACK/SYS_REBOOT/final-IN sequence was sent. A separated-process detection attempt did not see BE57; a direct standard descriptor read still showed normal A05E. The cause was not proven. Rather than trying alternate requests, one justified repeat used immediate in-process capture; it successfully found `be57:0101`. The log reports 300 ms from a polling-count estimate, not a measured clock interval. Do not repeat the separated-process OTA/detect approach.
4. CDC configuration has two interfaces, interrupt 81 / packet 64 / interval 64 and bulk 02/82 / packet 64. On macOS interface 0 claim returned -3 (ACCESS), interface 1 claim succeeded. The established CDC control sequence and bulk transport worked despite interface 0 remaining unclaimed. No root privilege or guessed requests were required; execution outside the sandbox was approved.
5. The exact known programmer (43540 bytes, SHA-256 below) completed the established BE50/BE53/BE54/BE55→BE60 sequence. Uploaded data is 42484 bytes, boot address `0x200105dc`, CRC32 `0x6b6187e2`. BE60 reported version 1.0 and sector 36864. A separate BE55 success was absent, matching the previously documented behavior.
6. Known BULK_READ command 03 read `[0x3c000000,0x3c080000)`, exactly 524288 bytes. All 128 full 4096-byte chunk boundaries, including the last, consumed their required ZLPs. No short/error read was accepted.
7. The programmer was closed/reopened in a separate native process. The entire protected `[0x3c004000,0x3c04e000)` region (flags, full A, full B envelope) and 4096 bytes at `0x3c07d000` were read again and matched the just-captured state. This new check establishes handle/session continuity; it is not a redundant full-flash experiment.

The physical validation executable is built with `CAPS_READ_ONLY`: its CLI rejects all persistent modes and the custom probe, and its BES sender rejects every command except 01/03/50/53/54/55 before transport. The separate stage-running binary performed only the approved B erase/write, BURN_INFO/BURN_BIN and B validity-marker writes. It did not write A or either flag sector. Known normal OTA/reset and RAM upload were explicitly authorized for this goal. Firmware-side historical/autonomous effects cannot be attributed from a single before/after historical-backup comparison.

## Exact state and provenance

| Artifact/state | SHA-256 / value |
| --- | --- |
| Original `firmware/private/flash-backup.bin` | digest retained locally and omitted from the public release |
| New full `research/cache/caps-macos/session-20261007/immediate/flash-current.bin` | digest retained locally and omitted from the public release |
| Complete A `[0x3c006000,0x3c02e000)`, 163840 bytes | digest retained locally and omitted from the public release; byte-identical to original backup |
| Installed B reconstructed file, original FF placeholder/footer restored | `a624d5771bfcefc68c40d77a745fbf82d8a60864f7f9d4bfddf29bdba95c1cc0`; exact known Diamond8 B |
| Official B input | `2f418d3a324ec4217c32c4bf98d43c3cd07d59d81f82974f29320d399fa769f3` |
| CAPS-only future staged B file | `afa5bb0570950030c7e36c3219fd93e0efc65c90f5355e02d4a3a091cb6bf356` |
| Expected CAPS marked flash payload, 131072 bytes | `bf92856c12779f7bbbff1b80d75d0d5d866254c4bd01b44ee328608669ddb52c` |
| Known programmer | `97443fb54fd75f71abbb5e3231a7f9abae26babe55c07c6b7302df0594236845` |
| Active flag, `0x3c004000` | `41 41 41 41 41 41 41 41` (A) |
| Backup flag, `0x3c005000` | `42 42 42 42 42 42 42 42` (B) |

Both live flag sectors contain FF after their eight-byte selections: the canonical-sector expectation is now physically verified for this current state. A starts with validity `1c ec 57 be`, metadata pointer `0x3c026394`; B has the same validity marker and pointer `0x3c04cc8c`. Installed B differs from marked official 0.23 in 104 bytes, all inside the 140-byte EQ structure at file `0x1e4c4`; gain -5.7 dB, count 8. It is not the CAPS extension. The original backup was not altered or replaced by this new capture.

### Why the full flash is not identical to the historical backup

The complete comparison has seven exclusive-end changed ranges:

| Flash file range | Meaning/evidence |
| --- | --- |
| `[0x4000,0x4004)` | Factory magic prefix changed to canonical A selection. |
| `[0x4008,0x4ffc)` | Factory flag-sector remainder became FF, consistent with prior flag erase/selection. |
| `[0x5000,0x5008)` | Blank backup flag became BBBBBBBB. |
| `[0x2e000,0x2e004)` | Previously FF B validity became `1c ec 57 be`; B payload otherwise identical to the original backup. |
| `[0x7d004,0x7d008)` | Record CRC changed `0x059d5b4e` → `0xef197a21`. |
| `[0x7d010,0x7d011)` | One record payload byte changed. |
| `[0x7d014,0x7d016)` | Two record payload bytes changed. |

Seven bytes outside B/flag regions changed in the sector at `0x3c07d000`: four CRC bytes and three payload bytes. Both versions have a matching CRC32 over sector offsets `[8,24)`, and the current sector was stable across the separate-process read. **CONFIRMED:** these exact differences and valid CRCs. **INFERRED:** structured firmware-managed nonvolatile record. **UNVERIFIED:** field semantics, time/cause of update, whether any part arose during the authorized OTA transitions versus earlier boots. Do not silently normalize or restore it. Staging is pinned to the exact current full-flash hash and checks that this entire region remains unchanged.

## Native tooling and exact future commands

Run from the repository root. Dependencies are the existing clang, Python, pkg-config and Homebrew libusb; no Termux, Android USB-FD support or global Python package installation is needed. USB execution requires host access outside the sandbox. Offline compiler output/provenance is under ignored `research/cache/caps-macos/`.

```sh
python3 tools/caps/build_macos.py
```

This builds `caps_readonly` and separately gated `caps_native`. `build.json` records C source hashes, exact commands, compiler and binary hashes; scripts reject stale/mismatched builds. Local inputs must also match recorded and known hashes. The existing Termux ZIP is unchanged and is not a macOS package.

The existing read-only session has already been completed; **do not repeat it** merely to prepare staging. For a future fresh normal-A research session, the deterministic read-only wrapper is:

```sh
python3 tools/caps/validate_macos.py --session research/cache/caps-macos/new-readonly-session
```

It performs the already-known OTA/programmer/full-read sequence using the guarded binary. A fresh capture must be reviewed rather than automatically replacing the approved baseline. It will not work if normal A is absent because the device is already in programmer mode; choose known state explicitly.

### CAPS-only B staging result (2026-10-07)

The user approved the B-only Stage operation. It completed successfully and was independently checked offline from saved full readbacks. No activation, flag write, reboot, power-cycle, or CAPS probe followed.

The exact source CAPS-only image SHA-256 is `afa5bb0570950030c7e36c3219fd93e0efc65c90f5355e02d4a3a091cb6bf356`, derived from official B SHA-256 `2f418d3a324ec4217c32c4bf98d43c3cd07d59d81f82974f29320d399fa769f3`. The staged marked 131072-byte B readback SHA-256 is `bf92856c12779f7bbbff1b80d75d0d5d866254c4bd01b44ee328608669ddb52c`; it equals the expected image byte-for-byte, including validity marker `1c ec 57 be`.

Slot A was read back in full before and after: both matched the original backup range and each other (SHA-256 digest retained locally and omitted from the public release). The complete boot flag sectors were unchanged; active selection remains `AAAAAAAA` (A), backup selection remains `BBBBBBBB` (B). A full post-stage flash read matched the pre-stage snapshot at every byte outside B. No automatic retry or rollback occurred.

Owner-only evidence and the offline verification manifest are in `research/cache/caps-macos/caps-deploy-01/`; see `stage/stage.log` and `stage/verification.json`. The before-stage full flash SHA-256 remains digest retained locally and omitted from the public release; post-stage full flash SHA-256 is digest retained locally and omitted from the public release.

```sh
python3 tools/caps/stage_caps_macos.py \
  --session research/cache/caps-macos/caps-deploy-01 \
  --baseline research/cache/caps-macos/session-20261007/immediate/flash-current.bin
```

Confirmation: `STAGE-CAPS-B`. Requires the current already-running validated programmer. Before the first persistent command it completely verifies A, known flag sectors and a full live flash comparison with exact baseline hash `077317...`. It writes only B at `0x3c02e000`, data length `0x20000`, four 32768-byte burn records within `[0x3c02e000,0x3c04e000)`, and the B validity marker. It excludes the host-only footer. It then reads/comparisons every marked B byte, full A, both flag sectors, and full flash outside B. No boot flag changes. Expected success includes `CAPS_BOOT_FLAGS_UNCHANGED=YES`, `MACOS_FLASH_OUTSIDE_B_UNCHANGED=YES`, `MACOS_PHASE_OK=stage-running`, `MACOS_STAGE_COMPLETE`. Failures never trigger automatic activation, retry or rollback.

### Activation result

The first wrapper invocation ran sandboxed, saw no devices, and aborted before opening USB or accessing flags. The wrapper was then run in the USB-capable context. It logged and passed the read-only stable-device preflight before launching the writer. Native activation repeated stabilization and reverified full A, full B, and both full flag sectors before modifying flags. It preserved the old A selection in the backup flag, changed the active selection to B, and verified both readbacks. Evidence and receipt: `research/cache/caps-macos/caps-activation-03/activate/`. Active selection is B; backup selection is A. No reboot was sent.

### Post-boot read-only result

After the user physically disconnected power for 15 seconds and reconnected the earphones, read-only enumeration found normal `04e8:a05e`. QUERY_SW_VER returned `0.23_051101_ab`, CHECK returned `1.1`, and descriptors showed USB Audio Control/Streaming plus HID interface 3 and the known 47-byte Consumer Control report descriptor. macOS audio inventory listed Samsung USB C Earphones with two input and two output channels at 48 kHz. CAPS-only B therefore boots in normal mode with audio and HID enumerated. The single authorized GET_EOIC_CAPS request returned `45 4f 49 43 01 00 08 00 00 00 00 00`, matching all 12 expected bytes.

```sh
python3 tools/caps/activate_caps_macos.py --session research/cache/caps-macos/caps-deploy-01
```

Confirmation: `ACTIVATE-CAPS-B`. Re-reads full A and full staged B; requires exact staging receipt and unchanged flags. Saves entire old active/backup sectors locally; writes/verifies backup of old active selection, then B selection and complete flag sectors. Expected `CAPS_BOOT_SELECTION=B VERIFIED`, `CAPS_SOFTWARE_REBOOT_SENT=NO`, `MACOS_PHASE_OK=activate-running`. Neither image is written and no software reboot is sent. Original A is preserved.

### Read-only CAPS probe result

```sh
python3 tools/caps/probe_caps_macos.py \
  --session research/cache/caps-macos/caps-deploy-01 --confirm-patched-b
```

Exactly one `C0/E0/454F/4943/12` IN request was sent, with a 1000 ms timeout; no query/OUT/retry/detach/configuration change followed. The raw 12-byte capture and SHA-256 `16110c9f61d52f0f8987b0d7ebcd806edfde92ff229a66557f162f9d8f530a16` are saved in `research/cache/caps-macos/caps-activation-03/probe/`. The byte-for-byte response was:

```text
45 4f 49 43 01 00 08 00 00 00 00 00
```

### Future recovery to A

**NOT RUN. Any actual recovery flag write requires separate approval.** In a known running programmer session:

```sh
python3 tools/caps/recover_a_macos.py \
  --session research/cache/caps-macos/caps-deploy-01 --from programmer-running
```

Confirmation: `RECOVER-VERIFIED-A`. Reads/verifies full original A, saves full flag sectors, writes only active A selection if necessary, verifies flags, stops without software reboot. No firmware image or backup flag is written. If A is already selected, re-reads/verifies unchanged sectors and performs no write.

If normal B responds, `--from normal-B` uses the known immediate OTA/programmer/read-only path first; `--from normal-A` requires the exact original A version. Those normal origins send the known software reboot only for entry, never after flag selection. `--from programmer-bootstrap` is for independently established fresh ROM bootstrap state, not a guessed fallback. Wrong state aborts; no automatic state guessing or retries.

If B fails to enumerate and BE57:0101 is unreachable, there is **no demonstrated software recovery entry**. Intact A does not guarantee selectable recovery or automatic fallback. Do not guess requests or hardware button sequences. A separately authorized disconnect/reconnect may expose a known state; it is not a guaranteed rescue method. Independent hardware/service recovery remains an activation risk.

## Tests and verification scope

All repository offline suites passed: **59 tests total** — 24 CAPS package/native tests, 19 custom-vendor firmware/emulation tests, 11 HID tests, 5 runtime-EQ tests. Native tests exercise no-authorization and read-only-binary rejection before USB, BES command guard, RAM-only native stage/activation/recovery flows, exact baseline rejection before burn, detection of changes outside B after mock staging, full original-A/B parsing, checksums/CRC and inherited malformed-input/firmware tests. Modeled device I/O never reaches physical USB. Both native builds pass `-Wall -Wextra -Werror`; Python source syntax and git whitespace checks pass.

The custom-firmware CPU suite retains its documented math/MMIO simulation limits. Programmer launch/readback is physically validated; persistent burn/flag operations on this macOS port are **offline-tested only**. CAPS-only B normal boot and its fixed CAPS response are physically verified. Audio continuity during the custom request, extended USB/stack/watchdog behavior, and fallback remain unverified.

## Evidence caches and stop condition

- `research/cache/caps-macos/session-20261007/normal/result.json`
- `.../ota/trace.log` — separated detection attempt; no flash command.
- `.../immediate/trace.log`, `flash-current.bin`, `reviewed-state.json`, `nv-header-analysis.json`
- `.../reopen/trace.log`, `protected-readback.bin`, `nv-readback.bin`
- `.../READINESS_MANIFEST.json`
- `research/cache/caps-macos/build.json`, `offline-suite.log`
- Existing `research/cache/custom-vendor/test-results.json`

Raw traces/copies have owner-only permissions and remain ignored. No serial identifier is collected in this workflow. No asset, cache or device backup is staged for git; no commit or push occurred. Staging and activation are complete. The CAPS probe, reboot/power-cycle, and any recovery write remain unperformed and require separate authorization.

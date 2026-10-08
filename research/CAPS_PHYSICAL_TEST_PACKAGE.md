# CAPS-only physical-test package — prepared, not executed

This package uses the project's established **Android Termux USB-FD transport**. It does not run on macOS directly: absence of `termux-usb` is a hard stop. Offline compilation was checked on macOS, and RAM-only fake-device tests exercise the entry-point guards. Actual Android execution, USB permission delivery, programmer continuity after closing/reopening a handle, timing and hardware remain unverified. None of the physical scripts, build script or physical helper was executed while preparing this package. No USB operation occurred.

Read `CAPS_ONLY_DEPLOYMENT_REVIEW.md` first. Automatic rollback and an independent recovery entry from a nonenumerating B are unproven. This package is neither deployment authorization nor evidence that recovery will be accessible.

## Files and platform prerequisites

- `tools/caps/stage_caps.py`: normal-A checks, approved update/reboot entry, programmer upload, B-only staging/full verification; no flag writes.
- `tools/caps/activate_caps.py`: same still-running programmer session, full A/B verification, flag backup/selection/readback; no software reboot or image write.
- `tools/caps/recover_a.py`: explicit typed confirmation, complete original-A verification, active flag only; neither image nor backup flag is written.
- `tools/caps/probe_caps.py`: one GET_EOIC_CAPS; no firmware query, CHECK, OUT vendor transfer or retry.
- `tools/caps/package.py`: local hash/receipt checks, strict identity discovery and phase orchestration.
- `tools/caps/caps_transport.c`, `protocol.c`, `sha256.h`: dedicated hash-locked transport, snapshot of original project protocol with strict BE60 version 1.0/sector 36864, in-process buffer hashing. No legacy deployment CLI is included.
- `tools/caps/build.py`: offline helper build and source/binary provenance stamp.
- `tools/caps/test_package.py`, `offline_transport_test.c`: offline tests with a RAM-only fake device.

Future operator needs the official Termux:API companion app and Termux USB permission support, Python, clang, libusb, pkg-config and termux-api. Put this checkout and the exact private assets on that host through a separately chosen file-transfer method. Scripts do not download, copy or alter originals. Defaults are repository-relative and work after relocation. Required private files:

| File | Required SHA-256 |
| --- | --- |
| `firmware/private/stock_b.bin` | `2f418d3a324ec4217c32c4bf98d43c3cd07d59d81f82974f29320d399fa769f3` |
| `firmware/private/programmer3001sp.bin` | `97443fb54fd75f71abbb5e3231a7f9abae26babe55c07c6b7302df0594236845` |
| `firmware/private/flash-backup.bin` | digest retained locally and omitted from the public release |
| `research/cache/custom-vendor/caps-only.bin` | `afa5bb0570950030c7e36c3219fd93e0efc65c90f5355e02d4a3a091cb6bf356` |

`firmware/private/SHA256SUMS.txt` must record those three private hashes. Actual files, recorded entries and constants must agree. The official A download is not the installed original 0.04 A and is never used as the recovery authority. C hashes its own loaded buffers before device access; the programmer buffer is checked again immediately before upload. New files/logs/readbacks stay in ignored `research/cache/`; phase evidence files use exclusive creation and are flushed to disk. Never overwrite or delete the original backup.

## Exact future commands

Run from the relocated repository root in **Termux**, only after separate authorization for each physical phase. These commands were **not run** during preparation.

Offline build (no USB):

```sh
python3 tools/caps/build.py
```

Expected: `OFFLINE_BUILD_COMPLETE; no USB operation; binary: .../research/cache/caps-physical/caps_transport`. Compilation warnings fail the build; the stamp pins current C sources and compiled binary. Changing sources/binary requires rebuilding.

Stage, with an unused session name:

```sh
python3 tools/caps/stage_caps.py --session research/cache/caps-test-01
```

Type `STAGE-CAPS-B` when prompted. This phase includes **FW_UPDATE, SYS_REBOOT, programmer upload, BURN_INFO/BURN_BIN and B validity-marker write**; running it is a physical operation requiring approval. It starts with exactly one normal `04e8:a05e`, requires exactly `0.04_051101_aa` and `CHECK=1.1`, then re-queries A on the transition handle. Descriptor polling must find exactly one `be57:0101`. Full A/header/flag checks occur before the first **persistent flash write**; normal mode cannot supply this flash read, so the reviewed RAM-programmer transition/upload necessarily precedes it.

Expected concise output, omitting duplicate preflight/identity lines:

```text
LOCAL_PREFLIGHT=VERIFIED official B, CAPS-only B, programmer, recorded backup, helper
VID:PID=04e8:a05e
FW=0.04_051101_aa
CHECK=1.1
CAPS_OTA_ENTRY_SENT=YES
VID:PID=be57:0101
CAPS_A_FULL_READBACK=VERIFIED bytes=163840 address=0x3c006000
CAPS_TARGET=B ONLY address=0x3c02e000 length=131072
BURN_INFO start=3c02e000 data=131072 sector=32768
CAPS_B_FULL_READBACK=VERIFIED bytes=131072 address=0x3c02e000
CAPS_A_FULL_READBACK=VERIFIED bytes=163840 address=0x3c006000
CAPS_BOOT_FLAGS_UNCHANGED=YES
CAPS_PHASE_OK=stage-bootstrap
STAGE_COMPLETE: B fully verified; A and both flags unchanged. Keep programmer connected for activation.
```

Staging preserves all 8192 bytes of active/backup flag sectors, verified before/after. B comparison covers all 131072 bytes, with established marker `1c ec 57 be` substituted at offset zero and four-byte host footer excluded. The full A region `[0x3c006000,0x3c02e000)` must exactly match the known original backup both before and after staging. Header metadata pointer is pinned to `0x3c026394`.

Activation, **without unplugging/rebooting after successful staging**:

```sh
python3 tools/caps/activate_caps.py --session research/cache/caps-test-01
```

Type `ACTIVATE-CAPS-B`. This is separately authorized flag writing. It requires the successful staging receipt and live A-selected flags identical to the staged session. It does not run normal-mode entry, upload/restart the programmer or send any software reboot. Read commands must work on the still-running programmer; otherwise abort, do not automatically bootstrap or fall back.

Expected:

```text
VID:PID=be57:0101
CAPS_A_FULL_READBACK=VERIFIED bytes=163840 address=0x3c006000
CAPS_B_FULL_READBACK=VERIFIED bytes=131072 address=0x3c02e000
CAPS_BOOT_SELECTION=B VERIFIED
CAPS_SOFTWARE_REBOOT_SENT=NO
CAPS_PHASE_OK=activate-running
ACTIVATION_COMPLETE: B selected and flags verified; NO software reboot. Stop here.
```

The complete old active/backup flag sectors are saved locally before writing. Activation writes the old eight-byte active flag to backup `0x3c005000`, verifies the complete backup sector, then selects B at active `0x3c004000` and verifies both sectors. No image is written. Final active bytes are `42 42 42 42 42 42 42 42`.

**Flag-sector semantics:** the original factory active sector contains additional recorded data after its eight-byte flag. Acceptable active sectors are either the complete exact original factory sector or a canonical A/B sector with FF after the eight-byte selection. The established erase/write procedure creates a canonical sector and therefore erases that factory remainder; its complete previous contents are retained locally. Unknown extra data is an abort, not silently discarded. The backup sector must be blank or a known eight-byte flag followed by FF. This follows the previously successful Samsung-style flag operation; it does not claim byte preservation of the active sector during activation/recovery. The FF remainder is the expected erase result, not a new physical observation: prior successful checks verified the eight-byte flag, and this package now requires full-sector verification. Any other after-sector shape stops the phase.

Booting B requires a **separately authorized physical power cycle** after activation; no package script performs it. Establish normal enumeration and ordinary audio/HID behavior before approving the custom probe. Version string remains stock and cannot establish the patched hash.

Probe, only after independent deployment/boot verification:

```sh
python3 tools/caps/probe_caps.py --session research/cache/caps-test-01 --confirm-patched-b
```

Type `GET-EOIC-CAPS`. Requires a successful CAPS-only activation receipt and operator confirmation. Device identification reads descriptors; the **only vendor request** is one IN transfer `C0/E0/454F/4943/12`, timeout 1000 ms. No query, CHECK, OUT, SET, reset, driver detach, configuration change or retry occurs in this phase.

Expected exact response and output:

```text
45 4f 49 43 01 00 08 00 00 00 00 00
CAPS_RESPONSE=45 4f 49 43 01 00 08 00 00 00 00 00
CAPS_PHASE_OK=probe
CAPS_PROBE_COMPLETE: EOIC version=1 bands=8 flags=0
```

This CAPS-only image hash has no reachable custom DSP mutation implementation. The probe never sends SET_EQ_TEST. A valid response establishes only execution of the read-only handler, not safe EQ mutation or measured DSP behavior.

## Recovery commands and expected output

With normal B still responding, separately authorize the normal-mode update/reboot transition and A-selection writes:

```sh
python3 tools/caps/recover_a.py --session research/cache/caps-test-01 --from normal-B
```

Type `RECOVER-VERIFIED-A`. Exact normal B version `0.23_051101_ab`, CHECK 1.1 and matching B boot selection are required. `--from normal-A` is available only for exact original A and matching A selection. Normal origins include FW_UPDATE/SYS_REBOOT to reach programmer transport; recovery stops without a final software reboot. Neither image nor backup flag is written.

If already in the **known still-running programmer session**, use:

```sh
python3 tools/caps/recover_a.py --session research/cache/caps-test-01 --from programmer-running
```

For an **independently established fresh bootstrap transport**, rather than a running programmer:

```sh
python3 tools/caps/recover_a.py --session research/cache/caps-test-01 --from programmer-bootstrap
```

The operator must know which state is present; scripts never try both automatically. Bootstrap requires the established BE50/BE60 sequence and pinned programmer. A running state must respond to the known full-read command. Wrong state, timeout or malformed reply aborts. Programmer-only recovery has no normal firmware version to query; its authority is exact USB identity, known protocol state, full A comparison and known flag sectors, not a fabricated version result.

Expected successful recovery:

```text
CAPS_A_FULL_READBACK=VERIFIED bytes=163840 address=0x3c006000
CAPS_BOOT_SELECTION=A VERIFIED
CAPS_SOFTWARE_REBOOT_SENT=NO
CAPS_PHASE_OK=recover-running
RECOVERY_COMPLETE: original A fully verified, selected; neither image or backup flag written. No final reboot.
```

The phase marker varies with the chosen origin/bootstrap mode. Final active flag is `41 41 41 41 41 41 41 41`; backup sector is verified unchanged. If A is already selected, output is `CAPS_ALREADY_A=YES no write`; selection remains A and no flag write occurs; the original/canonical A encoding is retained and both sectors are re-read unchanged. Save full readbacks/flags before any later separately approved power cycle, then verify original-A enumeration/version/audio/HID.

## Abort conditions

- Missing/differing official image, CAPS image, programmer, full backup, recorded SHA256SUMS, helper source stamp or binary hash; wrong image length/header/footer.
- Unsupported host/USB-FD tools, malformed device list, missing/duplicate identity, changed identity on the opened handle, inaccessible descriptor/permission.
- Initial normal firmware not exact original A for staging, wrong version/slot for normal-origin recovery, nonexact 14-byte version response, or CHECK not exactly three-byte `1.1`.
- Missing/failed staging receipt, changed flags between staging/activation, reused phase/session evidence files, unexpected active/backup sector contents, mismatched slot selection.
- Wrong programmer state/handshake/version/sector, CDC claim/transfer failure, malformed ACK/checksum, read/ZLP failure, timeout or partial transfer.
- Any A header/metadata/full-region mismatch; any B byte mismatch across the complete marked payload; unexpected A/flag changes after staging; any flag readback mismatch.
- Readback/evidence file cannot be exclusively written and flushed; process interruption or helper failure; missing exact completion marker even if Termux exits zero.
- Probe has no activation receipt/attestation, wrong length or any of the 12 bytes differs, stall/timeout/backend error.

On failure there is no automatic retry, rollback, activation, bootstrap fallback or reboot. A staging failure can leave B partially written but leaves boot selection untouched. A flag failure may leave partial boot selection; stop and inspect saved sectors rather than issuing another erase/write. Do not interrupt a burn/flag operation deliberately; a host timeout/permission disconnect may leave device state uncertain. Termux session continuity and handle reopening still need physical validation.

## If B fails to enumerate

Do not invoke the probe or blindly invoke normal-origin recovery. No successful normal enumeration means no known FW_UPDATE path. With separate approval, a controlled disconnect/reconnect may expose A or `be57:0101`; automatic fallback is not guaranteed. If A boots, verify original A/audio and stop. If known programmer transport is reachable, choose the appropriate explicit recovery origin above and require complete A verification before selection. If neither normal nor programmer interface is accessible, **there is no demonstrated software recovery procedure**. No script invents USB requests, button combinations or ROM entry. Hardware/service recovery must be independently established before accepting this deployment risk.

## Offline verification performed

Only offline compilation and 14 passing `test_package.py` tests ran; the four physical scripts, build script and physical executable did not. The fake-device executable replaces setup/discovery, control transfers, programmer bootstrap, reads, burns and flag writes with RAM-only implementations. Tests cover B-only write ordering/full comparisons, flag-only activation, active-flag-only recovery, incorrect A/B/identity/flag/bootstrap/hash/version/CHECK rejection, probe-only transfer, recorded backup requirements, SHA padding and unchanged original input hashes. This is host control-flow verification, not device qualification. Large output and compiled fixtures remain ignored.

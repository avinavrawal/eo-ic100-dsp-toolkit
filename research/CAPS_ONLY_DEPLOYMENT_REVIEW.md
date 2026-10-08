# CAPS-only deployment review

Offline review, 2026-10-07. No USB operations or physical-device communication. This report is not deployment authorization and covers only CAPS-only.

## 1–2. Exact paths and hashes

Patched B: `research/cache/custom-vendor/caps-only.bin`

SHA-256: `afa5bb0570950030c7e36c3219fd93e0efc65c90f5355e02d4a3a091cb6bf356`.

Official B input: `firmware/private/stock_b.bin`

SHA-256: `2f418d3a324ec4217c32c4bf98d43c3cd07d59d81f82974f29320d399fa769f3`.

Both hashes were recalculated for this review. Output is 131076 bytes: 131072-byte flash payload plus a four-byte host-only footer. It retains the FF validity placeholder and is not boot-valid as-is. Future approved staging must substitute the established marker and exclude the footer. Expected marked payload hash: `bf92856c12779f7bbbff1b80d75d0d5d866254c4bd01b44ee328608669ddb52c`. No marker was written.

## 3–4. Exact changes and hook bytes

Exclusive-end ranges: `[0x1d384,0x1d388)`, `[0x1d990,0x1d994)`, `[0x1edc4,0x20004)`.

| Hook | File offset | RAM word | Before LE bytes | After LE bytes |
| --- | --- | --- | --- | --- |
| vendor | `0x1d384` | `0x20014aac` | `99 d9 20 00` | `75 d1 04 0c` |
| setup | `0x1d990` | `0x200150b8` | `11 dd 20 00` | `01 d0 04 0c` |

Old footer `[0x1edc4,0x1edc8)` is `00 e0 02 3c`, replaced by FF padding extending to `0x1f000`. Extension is `[0x1f000,0x1f1ec)`; FF padding follows to `0x20000`; footer `00 e0 02 3c` relocates to `[0x20000,0x20004)`. All other original payload bytes, including code, build metadata, USB/audio/HID descriptors and boot EQ, are unchanged.

## 5. Injection address

**There is no injected RAM code address.** Code executes in place from flash: file `0x1f000`, mapped data alias `0x3c04d000`, Thumb execution address `0x0c04d000`. Setup pointer is `0x0c04d001`; vendor pointer is `0x0c04d175`; immutable response is `0x0c04d1e0`. Startup copies only the patched callback words to the RAM addresses above. HAL setup table is `0x2001ab9c` + `0x0c`; registered vendor callback is held at `0x2001b15c`.

## 6. Complete injected disassembly

All 492 injected bytes follow: 160 Thumb instructions, four-byte literal pool, 12-byte response. Re-decoded from the current image with Capstone 5.0.3 in contiguous instruction spans, retaining IT-block context; matched the cached decoded report exactly. The retained pure EQ validator is not called by either hook.

```text

eoic_setup:
0c04d000  01 7b         ldrb      r1, [r0, #0xc]
0c04d002  01 f0 60 02   and       r2, r1, #0x60
0c04d006  40 2a         cmp       r2, #0x40
0c04d008  19 d1         bne       #0xc04d03e
0c04d00a  42 7b         ldrb      r2, [r0, #0xd]
0c04d00c  02 f0 fe 03   and       r3, r2, #0xfe
0c04d010  e0 2b         cmp       r3, #0xe0
0c04d012  14 d1         bne       #0xc04d03e
0c04d014  b0 f8 0e c0   ldrh.w    ip, [r0, #0xe]
0c04d018  44 f2 4f 53   movw      r3, #0x454f
0c04d01c  9c 45         cmp       ip, r3
0c04d01e  09 d1         bne       #0xc04d034
0c04d020  b0 f8 10 c0   ldrh.w    ip, [r0, #0x10]
0c04d024  44 f6 43 13   movw      r3, #0x4943
0c04d028  9c 45         cmp       ip, r3
0c04d02a  03 d1         bne       #0xc04d034
0c04d02c  c0 29         cmp       r1, #0xc0
0c04d02e  08 bf         it        eq
0c04d030  e0 2a         cmpeq     r2, #0xe0
0c04d032  01 d0         beq       #0xc04d038
0c04d034  00 20         movs      r0, #0
0c04d036  70 47         bx        lr
0c04d038  41 8a         ldrh      r1, [r0, #0x12]
0c04d03a  0c 29         cmp       r1, #0xc
0c04d03c  fa d1         bne       #0xc04d034
0c04d03e  4d f6 11 51   movw      r1, #0xdd11
0c04d042  c0 f2 20 01   movt      r1, #0x20
0c04d046  08 47         bx        r1

eoic_valid_eq (unreachable pure validator):
0c04d048  41 f2 ff 12   movw      r2, #0x11ff
0c04d04c  cf f6 fd 72   movt      r2, #0xfffd
0c04d050  8b 18         adds      r3, r1, r2
0c04d052  02 f5 fa 42   add.w     r2, r2, #0x7d00
0c04d056  93 42         cmp       r3, r2
0c04d058  18 d3         blo       #0xc04d08c
0c04d05a  83 68         ldr       r3, [r0, #8]
0c04d05c  02 46         mov       r2, r0
0c04d05e  a3 f1 09 00   sub.w     r0, r3, #9
0c04d062  10 f1 08 0f   cmn.w     r0, #8
0c04d066  11 d3         blo       #0xc04d08c
0c04d068  92 ed 00 2a   vldr      s4, [r2]
0c04d06c  12 ee 10 0a   vmov      r0, s4
0c04d070  20 f0 00 40   bic       r0, r0, #0x80000000
0c04d074  b0 f1 ff 4f   cmp.w     r0, #0x7f800000
0c04d078  08 da         bge       #0xc04d08c
0c04d07a  92 ed 01 1a   vldr      s2, [r2, #4]
0c04d07e  11 ee 10 0a   vmov      r0, s2
0c04d082  20 f0 00 40   bic       r0, r0, #0x80000000
0c04d086  b0 f1 ff 4f   cmp.w     r0, #0x7f800000
0c04d08a  01 db         blt       #0xc04d090
0c04d08c  00 20         movs      r0, #0
0c04d08e  70 47         bx        lr
0c04d090  ba ee 08 0a   vmov.f32  s0, #-1.200000e+01
0c04d094  b4 ee 40 2a   vcmp.f32  s4, s0
0c04d098  f1 ee 10 fa   vmrs      apsr_nzcv, fpscr
0c04d09c  4f f0 00 00   mov.w     r0, #0
0c04d0a0  f5 d4         bmi       #0xc04d08e
0c04d0a2  b5 ee 40 2a   vcmp.f32  s4, #0
0c04d0a6  f1 ee 10 fa   vmrs      apsr_nzcv, fpscr
0c04d0aa  f0 dc         bgt       #0xc04d08e
0c04d0ac  b4 ee 40 1a   vcmp.f32  s2, s0
0c04d0b0  f1 ee 10 fa   vmrs      apsr_nzcv, fpscr
0c04d0b4  eb d4         bmi       #0xc04d08e
0c04d0b6  b5 ee 40 1a   vcmp.f32  s2, #0
0c04d0ba  f1 ee 10 fa   vmrs      apsr_nzcv, fpscr
0c04d0be  e6 dc         bgt       #0xc04d08e
0c04d0c0  48 08         lsrs      r0, r1, #1
0c04d0c2  01 ee 10 0a   vmov      s2, r0
0c04d0c6  9f ed 2a 4a   vldr      s8, [pc, #0xa8]
0c04d0ca  0c 32         adds      r2, #0xc
0c04d0cc  b8 ee 41 1a   vcvt.f32.u32 s2, s2
0c04d0d0  b1 ee 08 2a   vmov.f32  s4, #6.000000e+00
0c04d0d4  b3 ee 04 3a   vmov.f32  s6, #2.000000e+01
0c04d0d8  b3 ee 00 5a   vmov.f32  s10, #1.600000e+01
0c04d0dc  10 68         ldr       r0, [r2]
0c04d0de  04 28         cmp       r0, #4
0c04d0e0  d4 d8         bhi       #0xc04d08c
0c04d0e2  92 ed 01 6a   vldr      s12, [r2, #4]
0c04d0e6  16 ee 10 0a   vmov      r0, s12
0c04d0ea  20 f0 00 40   bic       r0, r0, #0x80000000
0c04d0ee  b0 f1 ff 4f   cmp.w     r0, #0x7f800000
0c04d0f2  cb da         bge       #0xc04d08c
0c04d0f4  b4 ee 40 6a   vcmp.f32  s12, s0
0c04d0f8  f1 ee 10 fa   vmrs      apsr_nzcv, fpscr
0c04d0fc  4f f0 00 00   mov.w     r0, #0
0c04d100  c5 d4         bmi       #0xc04d08e
0c04d102  b4 ee 42 6a   vcmp.f32  s12, s4
0c04d106  f1 ee 10 fa   vmrs      apsr_nzcv, fpscr
0c04d10a  c0 dc         bgt       #0xc04d08e
0c04d10c  92 ed 02 6a   vldr      s12, [r2, #8]
0c04d110  16 ee 10 0a   vmov      r0, s12
0c04d114  20 f0 00 40   bic       r0, r0, #0x80000000
0c04d118  b0 f1 ff 4f   cmp.w     r0, #0x7f800000
0c04d11c  4f f0 00 00   mov.w     r0, #0
0c04d120  b5 da         bge       #0xc04d08e
0c04d122  b4 ee 43 6a   vcmp.f32  s12, s6
0c04d126  f1 ee 10 fa   vmrs      apsr_nzcv, fpscr
0c04d12a  b0 d4         bmi       #0xc04d08e
0c04d12c  b4 ee 41 6a   vcmp.f32  s12, s2
0c04d130  f1 ee 10 fa   vmrs      apsr_nzcv, fpscr
0c04d134  ab da         bge       #0xc04d08e
0c04d136  92 ed 03 6a   vldr      s12, [r2, #0xc]
0c04d13a  16 ee 10 0a   vmov      r0, s12
0c04d13e  20 f0 00 40   bic       r0, r0, #0x80000000
0c04d142  b0 f1 ff 4f   cmp.w     r0, #0x7f800000
0c04d146  a1 da         bge       #0xc04d08c
0c04d148  b4 ee 44 6a   vcmp.f32  s12, s8
0c04d14c  f1 ee 10 fa   vmrs      apsr_nzcv, fpscr
0c04d150  4f f0 00 00   mov.w     r0, #0
0c04d154  48 bf         it        mi
0c04d156  70 47         bxmi      lr
0c04d158  b4 ee 45 6a   vcmp.f32  s12, s10
0c04d15c  f1 ee 10 fa   vmrs      apsr_nzcv, fpscr
0c04d160  95 dc         bgt       #0xc04d08e
0c04d162  01 3b         subs      r3, #1
0c04d164  02 f1 10 02   add.w     r2, r2, #0x10
0c04d168  04 bf         itt       eq
0c04d16a  01 20         moveq     r0, #1
0c04d16c  70 47         bxeq      lr
0c04d16e  b5 e7         b         #0xc04d0dc
0c04d170  cd cc cc 3d  .word 0x3dcccccd ; validator float32 0.1 literal

eoic_vendor:
0c04d174  02 68         ldr       r2, [r0]
0c04d176  11 78         ldrb      r1, [r2]
0c04d178  01 f0 60 03   and       r3, r1, #0x60
0c04d17c  40 2b         cmp       r3, #0x40
0c04d17e  21 d1         bne       #0xc04d1c4
0c04d180  92 f8 01 c0   ldrb.w    ip, [r2, #1]
0c04d184  0c f0 fe 03   and       r3, ip, #0xfe
0c04d188  e0 2b         cmp       r3, #0xe0
0c04d18a  1b d1         bne       #0xc04d1c4
0c04d18c  80 b5         push      {r7, lr}
0c04d18e  b2 f8 02 e0   ldrh.w    lr, [r2, #2]
0c04d192  44 f2 4f 53   movw      r3, #0x454f
0c04d196  9e 45         cmp       lr, r3
0c04d198  11 d1         bne       #0xc04d1be
0c04d19a  b2 f8 04 e0   ldrh.w    lr, [r2, #4]
0c04d19e  44 f6 43 13   movw      r3, #0x4943
0c04d1a2  9e 45         cmp       lr, r3
0c04d1a4  0b d1         bne       #0xc04d1be
0c04d1a6  c0 29         cmp       r1, #0xc0
0c04d1a8  4f f0 01 01   mov.w     r1, #1
0c04d1ac  08 bf         it        eq
0c04d1ae  bc f1 e0 0f   cmpeq.w   ip, #0xe0
0c04d1b2  05 d1         bne       #0xc04d1c0
0c04d1b4  d1 88         ldrh      r1, [r2, #6]
0c04d1b6  0c 29         cmp       r1, #0xc
0c04d1b8  01 d1         bne       #0xc04d1be
0c04d1ba  01 89         ldrh      r1, [r0, #8]
0c04d1bc  39 b1         cbz       r1, #0xc04d1ce
0c04d1be  01 21         movs      r1, #1
0c04d1c0  08 46         mov       r0, r1
0c04d1c2  80 bd         pop       {r7, pc}
0c04d1c4  4d f6 99 11   movw      r1, #0xd999
0c04d1c8  c0 f2 20 01   movt      r1, #0x20
0c04d1cc  08 47         bx        r1
0c04d1ce  4d f2 e0 11   movw      r1, #0xd1e0
0c04d1d2  c0 f6 04 41   movt      r1, #0xc04
0c04d1d6  41 60         str       r1, [r0, #4]
0c04d1d8  0c 21         movs      r1, #0xc
0c04d1da  01 81         strh      r1, [r0, #8]
0c04d1dc  00 21         movs      r1, #0
0c04d1de  ef e7         b         #0xc04d1c0
0c04d1e0  45 4f 49 43 01 00 08 00 00 00 00 00  ; immutable CAPS response
```

## 7–8. Entry and return

Existing IRQ `0x00206a50` reaches EP0 handler `0x00206130`; setup call site `0x00206208` calls the registered pointer indirectly. The changed setup word reaches `eoic_setup`. It rejects malformed custom vendor E0/E1 requests before OUT preparation, including every E1 request. Valid CAPS and noncustom setup tail-branch via `bx r1` to original Thumb `0x0020dd11`, preserving r0 frame pointer and caller LR. Rejection returns r0=0 via `bx lr`.

Stock vendor dispatch calls the second registered pointer indirectly. `eoic_vendor` receives r0 pointing to a record with setup pointer at +0, payload pointer at +4, length u16 at +8. Exact CAPS with zero incoming payload length installs the immutable response pointer/length and returns r0=0 via `pop {r7,pc}`. Invalid custom requests return r0=1. Noncustom traffic tail-branches to original Thumb `0x0020d999`, preserving original r0 and LR. There is no added BL/BLX or far direct branch.

Original EP0 send `0x00205c9c` copies response through `0x00200140` into transmit RAM `0x2001abf4`, which supplies controller DMA. Prior CPU tests execute the stock EP0 response copy and confirm the exact bytes. There is no stack-local response pointer.

## 9. Preserved vendor commands

The original seven branches and command table are unchanged: QUERY_SW_VER, QUERY_SN, SYS_REBOOT, SYS_SHUTDOWN, PING_THROUGH_VENDOR, CHECK, FW_UPDATE. Known stock OUT `40/06` and IN `C0/0C` delegate unchanged. CAPS does not change the saved pending command ID; pending CHECK across CAPS was tested. Standard/class/HID and other noncustom requests delegate to original setup.

CAPS-only preserves potentially destructive stock commands; it is not a firewall disabling update/reboot. None was physically executed. E0/E1 vendor numbers are newly reserved, so their former unknown-request fallback behavior intentionally changes. Preservation means the known stock protocol, not every imaginable vendor request. Classifier tests do not execute destructive stock branches on a device.

## 10–11. Response and probe

Exact response: `45 4f 49 43 01 00 08 00 00 00 00 00`.

LE `<4sHHI>`: EOIC, version 1, bands 8, flags 0. This is a constant capability record, not a measurement of live audio state.

Script: `tools/research/eoic_caps_probe.py`.

Offline dry run from repository root:

```sh
python3 tools/research/eoic_caps_probe.py
```

Future physical probe, **not run; separate approval required**:

```sh
python3 tools/research/eoic_caps_probe.py --execute --confirm-patched-b --expected-flags 0
```

It requires exactly one 04e8:a05e and sends one `ctrl_transfer(0xc0,0xe0,0x454f,0x4943,12,timeout=1000)`. No OUT, retry, configuration change or driver detach. Confirmation is operator attestation, not an independent check of the running hash. PyUSB/libusb availability, permission and OS access can fail independently of firmware. The unchanged version string does not identify patched bytes.

## 12. Watchdog, stack, alignment, pools, lifetime

- Watchdog: reachable custom paths contain no loops/waits, DSP calls or watchdog changes. Actual XIP latency, interrupt timing and watchdog margin are unmeasured; delegated code retains stock behavior.
- Stack: setup/legacy tail calls use no additional stack. Custom vendor pushes/pops r7/LR, eight bytes; preserves existing 8-byte alignment if the caller meets AAPCS. No CAPS float/VFP execution, EQ stack copy or heap use. Real interrupt nesting, high-water headroom and caller alignment remain unmeasured.
- Alignment/Thumb: injection is 4-KiB aligned, instructions halfword-aligned, callback pointers Thumb-tagged, response/pool four-byte aligned. Struct offsets are statically asserted and modeled. Valid stock frame/record pointers remain assumptions; no host-selected memory address is exposed.
- Pool: `[0x0c04d170,0x0c04d174)` is validator-only data. Mapping-aware checks exclude it from branch targets. Response address is MOVW/MOVT-linked. All direct branches validate within instruction spans; indirect tails target checked original Thumb entries.
- EP0: immutable flash response has image lifetime and is copied into stock DMA RAM. Twelve bytes fit one EP0 packet; programmer 4096-byte/ZLP behavior is irrelevant. Real reset/abort/reentrancy, DMA/cache and USB timing remain untested. Exact physical reject manifestation, stall versus timeout, is unverified.

## 13. CAPS-only boot risk assessment

**Offline tests do not establish a physically safe boot.** A bounded patch can still prevent enumeration and remove the normal recovery entry path.

Risk reductions: known-input hash lock, two pointer changes only, explicit appended allocation rather than a guessed cave, unchanged original metadata/code/descriptors/EQ, no new RAM/BSS/init, correct Thumb indirect entry, immutable response, no new DSP/flash/reboot path, deterministic images, 19 passing offline tests and this complete local disassembly/byte review.

Remaining risks:

1. Bootloader acceptance/integrity/length policy and silicon XIP/cache behavior are not fully modeled. Unchanged metadata and prior B sector envelope do not prove extended-image acceptance.
2. Allocation `[0x3c04d000,0x3c04e000)` is outside old payload/startup copies, within the established B envelope and outside A/flags; literal-reference scans find no ownership conflict. Computed/ROM accesses and undocumented uses remain unexcluded.
3. Boot-to-registration execution, actual callback ABI/context, SRAM aliasing, stack margin and interrupt concurrency have static/model evidence rather than physical validation.
4. Setup hook runs on all requests. A fetch/ABI/integration error can break enumeration or audio before CAPS is sent. Descriptor preservation alone cannot establish working audio.
5. EP0 lifetime/reset/cache/timing errors could stall control or disturb audio even without DSP mutation.
6. Future deployment introduces flash erase/write, validity-marker and flag risks. Entire 131072-byte marked payload must be read back and verified before activation; footer must not be flashed.
7. Automatic rollback and recovery entry from nonenumerating B are unverified. Intact A is necessary but does not guarantee accessible recovery.

Do not call this image brick-proof. Establish a documented recovery transport independent of functioning B before accepting nonenumeration risk. No deployment approval is implied by this review.

## 14. Recovery plans — no operations performed

Common requirements: preserve recovery A and full original backup; never erase/rewrite A or both slots; retain failed-run records. All update/reboot/programmer uploads and flash/flag changes need separate approval. Before selecting A, completely read back its intended image region and compare byte-for-byte to the original device backup, respecting stored marker/footer semantics. Official 0.23 A is not the installed original 0.04 A.

**Tooling gap:** current `--select-slot` only reads eight header bytes and checks validity magic; it does not completely verify A. Its normal-mode shell wrapper also automatically sends OTA entry/reboot. Do not run `boot_stock_a.sh`/`select_slot.sh` as a sufficient or automatically authorized recovery process. A reviewed workflow must add full A verification before flag changes.

### a. B does not enumerate

Stop probing. In a separately approved recovery session, a controlled physical disconnect/reconnect may expose normal A or BE57:0101; it is not guaranteed to trigger fallback. If A boots, identify it with approved known queries and halt further deployment. If BE57:0101 is reachable, follow case d. If neither normal nor programmer transport is reachable, **no demonstrated software recovery exists in this repository**. Do not guess button sequences, requests or ROM/test-point entry methods. Hardware/service recovery requires independent evidence. This is the most severe unresolved deployment risk.

### b. B enumerates but audio fails

Do not send CAPS or deploy another image. Record audio/enumeration state with approved read-only methods. If established normal vendor transport works, separately authorize known OTA/reboot entry, state-appropriate programmer upload, and complete original-A readback verification. Preserve flags, then separately approve A selection using the existing backup/active-flag procedure: backup at `0x3c005000`, active at `0x3c004000`, verified target bytes `41 41 41 41 41 41 41 41`. Read back flags, then use an approved power cycle and verify original-A firmware/audio/HID. No firmware rewrite is needed. If control transport fails, use case a; enumeration alone does not establish functional OTA entry.

### c. CAPS fails while normal audio works

Stop after one attempt. Record exact response/error and host access/backend; no retries, alternate request numbers or EQ-test deployment. Verify local probe fields and independently documented staged/running image identity; suffix alone is insufficient. Investigate offline. CAPS failure alone need not force destructive recovery if audio is stable. If rollback is desired, follow the separately approved, fully A-verified selection in case b. Reset or audio loss is a failed bring-up, not authorization to broaden probing.

### d. Stuck in programmer mode

Do not blindly upload or send FW_UPDATE. BE57:0101 does not establish whether bootstrap or RAM programmer is running. Determine state using the documented, separately approved handshake sequence. With no incomplete write and approval, disconnect/reconnect may leave transient RAM mode but will boot the selected slot, which may still be bad B. If transport is reachable, authorize state-appropriate known programmer bootstrap, read/preserve flags, fully read/verify original A, then authorize/perform/verify A flag selection and approved power cycle. No A reflash. If an operation was interrupted or flags disagree, review captures before any further erase/write. If bootstrap/transport is unavailable, software recovery is unproven; investigate hardware/service access rather than guessing commands.

## DSP mutation exclusion

Confirmed for this exact image hash: E1 is rejected at setup and vendor stages. Neither hooked path calls audio_eq_set_cfg, codec IIR routines, or a new DSP/MMIO/flash writer. There is **no SET_EQ_TEST implementation capable of changing DSP state** in injected CAPS-only code. Retained `eoic_valid_eq` only reads configuration and computes a result; it has no stores or DSP calls and no incoming call from either hook. E1 recognition is a rejection guard. New reachable writes are the firmware-owned response pointer/length and ordinary eight-byte stack frame. Original firmware retains its existing boot EQ/audio behavior and vendor commands.

# EQ update-state byte lifecycle

This is an offline follow-up to the guard-trace physical test. No device
operation was performed. Sources are the cached initialized-RAM reconstructions
for official 0.23 (`stock_a.bin`, SHA-256
`9ebc51140b17884a9b3fe97edc58f8b3861ec10dbc0a33499ea31200bdedba87`) and
original 0.04 (`flash-backup.bin`, SHA-256
digest retained locally and omitted from the public release), plus
the saved guard-trace evidence at
`research/cache/caps-macos/diagnostic-runtime-guard-trace-20261008/evidence.json`.

## Writers found in 0.23

| Address / instruction | Effect and path |
|---|---|
| `0x0020a478: strb r0,[r3]`, with `r0=1` and `r3=&0x200162b4` | `hw_codec_iir_set_cfg` marks the coefficient-bank transaction in progress before it programs the bank. |
| `0x0020a774: strb r2,[r3]`, with `r2=0` and `r3=&0x200162b4` | Normal success cleanup, after the bit-24 hardware acknowledgement loop at `0x20a76a` (or after the second transaction's ACK loop at `0x20a844`). It then toggles the software bank selector. |
| `0x0020a884: strb r0,[r1]`, with `r0=0` and `r1=&0x200162b4` | Codec lifecycle helper's already-initialized, enable (`r1` argument equals 1) path. It clears stale update state while reapplying codec state. It is not in the disable path. |

The official 0.23 initialized-RAM image contains exactly three literal words
equal to `0x200162b4`, at `0x2000a660`, `0x2000a854`, and `0x2000a8e4`;
targeted disassembly resolves them to the setter's set/clear sites and the
lifecycle clear above. This covers address-based references in the copied
image. The reconstruction excludes BSS and generic startup zeroing, so it
cannot enumerate a bulk zero-fill instruction by its target address. Normal
startup does initialize runtime state; whether its generic fill spans this
byte was not independently traced here.

The hardened diagnostic image adds two more possible clears, only on its
bounded ACK-timeout branches: `strb r2,[r3]` at `0x0c04d1be` and
`0x0c04d1fe`. Those helper paths were not entered by the physical E1 test,
which was rejected before the setter. Successful helper paths return to the
unchanged stock cleanup at `0x20a774`.

## Lifecycle and interpretation

This is a codec IIR-update-in-progress flag, not an EQ enable bit: the setter
sets it before writing coefficients and normally clears it after hardware
acknowledgement. However, the stock 0.23 setter has two post-set error exits
that return status 3 without clearing it: `0x20a5ea` and `0x20a78c`. The stock
ACK loops at `0x20a76a` and `0x20a844` are also unbounded; if the required
acknowledgement never arrives, control never reaches the clear. Either case
can leave the byte nonzero indefinitely. The lifecycle helper's enable path
at `0x20a884` can clear it later; the disable path clears codec-initialized
state but does not clear this byte.

The guard-trace evidence proves the custom E1 preflight read a nonzero byte at
the rejection branch: `codec_update_not_busy` evaluated and failed, and the
setter was not called. It does not identify which earlier writer set the byte
or show whether it later cleared. A transient overlap with a normal codec
update, a stock error exit, and a stuck ACK wait remain possible origins.

The address is correct for modified 0.23: both the stock setter and the
diagnostic guard use `0x200162b4`, and the physical branch-time trace confirms
the guard observed its busy value. Original 0.04 uses a different EQ
transaction byte, `0x200177cc` (setter set at `0x20b650`, normal ACK clear at
`0x20b848`, lifecycle clear at `0x20ba48`). The original image's separate
reference to `0x200162b4` is outside that EQ setter and does not establish the
0.23 layout.

The static 0.23 call graph shows Samsung's setter reached from USB-audio
open/reconfiguration paths, but cannot establish whether all such calls occur
only before samples stream. Calling the synchronous setter directly from the
USB callback is not the safest design: it performs coefficient work and
hardware polling, shares the same transaction state as the normal audio path,
and can block control-request processing. Defer a validated request to a
codec/audio worker that serializes with existing updates. The current evidence
supports that as the safest design; it does not prove that a particular
existing queue is mandatory or identify its ABI.

The physical trace does not prove the byte was permanently stuck. The smallest
safe diagnostic is a read-only sequence of E2 snapshots that samples this bit
at idle, while audio is steady, and after waiting through any codec
reconfiguration. To identify provenance if it remains set, add diagnostic
event counters at the existing set, ACK-success, error-return, and lifecycle
clear sites, without changing their branches or writing the flag from the
diagnostic code. Any physical capture requires separate authorization.

## Reproduction

The targeted cached disassembly was produced with radare2 `pD` over
`0x20a424–0x20a864`, `0x20a868–0x20a938`, and original `0x20b5fc–0x20ba9c`.
A Python scan over each cached initialized-RAM image enumerated literal
references to the two version-specific addresses. The generated focused
disassembly is kept under ignored `research/cache/`; no full image or raw
device capture was loaded into the report.

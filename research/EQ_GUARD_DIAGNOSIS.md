# Runtime EQ guard diagnosis

## Result from the one-shot physical trace

The saved trace proves E1 matched, its four-byte payload was accepted, and the
request completed through EP0. The custom handler returned its runtime-guard
rejection before the `audio_eq_set_cfg` call. The setter-entry event is absent,
its result remains `0xffffffff`, and neither acknowledgement-timeout bit is
set. Thus the -6 dB request did not reach the DSP setter.

E2-before readiness was `0x14`; E2-after readiness was `0x1b`. The readiness
bits are: bit 0 EQ-enabled, bit 1 codec-initialized, bit 2 codec-not-busy, bit
3 supported rate, bit 4 stock band count equals two. So the later `0x1b`
snapshot says bits 0, 1, 3, and 4 passed, while bit 2 did not. It is strong
evidence that the update-busy guard was the cause, but the old E2 format sampled
readiness after E1. It cannot establish the exact value at the branch itself;
the exact historical rejecting guard remains unproven.

## Checks before the setter

The checks below preserve the implemented order. Request shape and gain checks
are represented by existing E1 events: `MATCHED`, `ENTERED`, and
`PAYLOAD_ACCEPTED`. Once `PAYLOAD_ACCEPTED` is recorded, those checks passed.

| Order | Predicate | Source/value | Normal owner or lifecycle | Current evidence |
|---|---|---|---|---|
| 1 | EQ subsystem enabled | nonzero byte at `0x200162cd` | `audio_eq_set_cfg` at `0x20a938` temporarily clears it at `0x20a948` while applying coefficients and restores it to 1 at `0x20a95c`; codec enable/disable wrappers also manage the related state | E2-after bit 0 set; likely passed at E1 |
| 2 | codec initialized | nonzero word at `0x200162b8` | codec setup/enable code around `0x20a868`–`0x20a8d8` sets the state; disable path around `0x20a900`–`0x20a920` clears it. `hw_codec_iir_set_cfg` also checks it at `0x20a43a` | E2-after bit 1 set; likely passed at E1 |
| 3 | no coefficient update already in progress | byte at `0x200162b4` must be zero | stock setter sets it to 1 at `0x20a478` before the bank transaction, clears it at `0x20a774` after the first acknowledgement; codec setup/enable code also clears it at `0x20a884`. The hardened timeout path clears it during timeout cleanup | E2-after “not busy” bit 2 clear; leading cause, not proven at E1 time |
| 4 | supported sample rate | `0x200162c8` in `[32000,192000]`, checked by the configuration validator | audio format/configuration state is written by the USB-audio setup path; value is runtime state | E2-after bit 3 set; likely passed |
| 5 | stock EQ configuration validates | copied compiled PEQ at `0x20015bec`; finite values, supported bands/frequency/Q and ranges | static Samsung stock preset; E1 changes only its global L/R gains in a transient copy | No failure evidence; new trace will report it directly |
| 6 | stock topology remains two bands | count word at `0x20015bf4` equals 2 | compiled stock preset, not request-controlled | E2-after bit 4 set; likely passed |

There is no separate “audio stream active” predicate in this custom handler.
The sample-rate check is a configuration prerequisite, not proof that an audio
stream is active. There is also no pre-setter bank-selector guard in the custom
handler. The stock setter checks the software bank selector at
`0x200162bc` after entry and can take its own error path; that path was not
reached during the physical E1.

The busy byte represents a codec coefficient-bank transaction, rather than a
persistent enable setting. Stock code sets and clears it around a transaction.
That makes a transient busy state the expected interpretation. Whether it was
transient or stuck during the physical attempt cannot be concluded from the
post-request snapshot alone. The reported tone stopping is not evidence that
E1 reached the DSP; the harness also stops its finite playback window.

## Legitimate Samsung setter path

The indexed 0.23 call graph has one caller of `hw_codec_iir_set_cfg`:
`audio_eq_set_cfg` at `0x20a958`. `usb_audio_set_eq(2,0)` at `0x20c800`
loads the compiled preset and branches to `audio_eq_set_cfg`. That selector is
reached from `usb_audio_open_eq` at `0x20c8ec`; the open/reconfiguration
function itself has seven indexed call sites (`0x20ca66`, `0x20cb76`,
`0x20cd48`, `0x20ce00`, `0x20ce6e`, `0x20d3a2`, `0x20d444`). These are USB
audio open/configuration paths. The static call graph does not prove whether
every such call occurs before audio samples start or during a live stream, so
it does not justify asserting that Samsung normally changes EQ during active
playback.

Immediately before the stock setter in the normal path, `audio_eq_set_cfg`
temporarily clears the EQ-enabled byte, reads the current codec EQ, generates
coefficients from the selected preset, and calls the low-level setter with an
initialized codec and its current sample rate. The low-level setter checks
codec initialization, marks the update busy, programs the inactive bank, and
waits for the hardware acknowledgement before clearing busy and switching the
bank selector. The custom request’s extra busy preflight is not present in the
Samsung high-level API; it was added to avoid overlapping that transaction.

## Diagnostic-only guard-trace build

Because the old E2 reply cannot identify the branch-time predicate, a new
offline-only diagnostic image was built at
`research/cache/custom-vendor/eq-diagnostic-guards.bin` (private ignored cache),
SHA-256 `fc0f8a27471c829f120d48cce700a4b3976aa8a887d6bb71314dade36260a531`.
It returns CAPS `45 4f 49 43 01 00 08 00 03 00 00 00`; flags `03` uniquely
distinguish guard tracing from the deployed diagnostic build’s flags `01`.
E2 remains 32 bytes. Bits 10–21 of its existing `events` word encode the
branch-time checks as evaluated/pass pairs:

| Predicate | Evaluated bit | Passed bit |
|---|---:|---:|
| EQ subsystem enabled | 10 | 11 |
| codec initialized | 12 | 13 |
| codec update not busy | 14 | 15 |
| supported sample rate | 16 | 17 |
| stock EQ configuration valid | 18 | 19 |
| stock band count equals two | 20 | 21 |

An unset evaluated bit means short-circuiting stopped before that check. The
trace is written at each existing branch using the same captured value, in the
same order; it does not re-read state, bypass a guard, call the DSP setter
directly, or alter the setter or bounded ACK waits. For a busy rejection with
the first two predicates passing, the expected guard portion of `events` is
`0x7c00` (evaluated/pass for guards 0 and 1, evaluated/fail for guard 2, and
guards 3–5 unevaluated); the full common event word is `0x00007c0f`.

The old diagnostic image still hashes to
`63826ca08bcb0687a1a620673526dd86792b24f4d470245fe536787be1bcd61a`. The new
image was built twice with identical reports and hashes. No USB operation,
deployment, E1, E2, flash write, or boot change was performed for this
offline build diagnosis. The guard-trace image was subsequently physically
validated on 2026-10-08: it recorded `codec_update_not_busy` evaluated/failed
at the E1 branch, with the earlier EQ-enabled and codec-initialized guards
passing. E1 returned USB success, the setter was not called, timeout mask
stayed zero, and audio continued. The flag lifecycle and remaining provenance
uncertainty are documented in `research/EQ_BUSY_FLAG_LIFECYCLE.md`.

## Safest natural condition

Do not bypass the busy guard or force its byte. The safe condition is the
normal codec state after any existing coefficient update has completed and
the stock acknowledgement path has cleared `0x200162b4`, while the codec is
initialized and the desired audio format is active. The guard-trace capture
has established which pre-setter predicate failed; it did not identify the
byte's last writer or whether it later cleared. See
`research/EQ_BUSY_FLAG_LIFECYCLE.md` for the offline lifecycle analysis and
the smallest proposed read-only discriminator.

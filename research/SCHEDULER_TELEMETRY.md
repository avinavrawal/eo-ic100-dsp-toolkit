# Scheduler telemetry prototype (offline only)

This experimental build adds volatile, read-only scheduler observations to the hash-locked official Samsung 0.23 B image. It is generated at `research/cache/custom-vendor/scheduler-telemetry.bin`; no device operation was performed. Recovery slot A remains a separate preserved image and is not part of this patch.

## Request protocol

The image returns a unique CAPS marker so a future test can distinguish it from CAPS-only and EQ-test variants:

```text
bmRequestType=0xc0 bRequest=0xe0 wValue=0x454f wIndex=0x4943 wLength=12
response: 45 4f 49 43 01 00 08 00 04 00 00 00
```

Scheduler telemetry is an experimental read-only E3 request:

```text
bmRequestType=0xc0 bRequest=0xe3 wValue=0x454f wIndex=0x4943 wLength=52
```

The 52-byte little-endian response is `<IHH10I4B>`:

| Offset | Field | Meaning |
| ---: | --- | --- |
| 0 | `magic = 0x4d544345` | ASCII `ECTM` |
| 4 | `protocol = 1` | Response version |
| 6 | `size = 52` | Response length |
| 8 | `app_loops` | Saturating visits to the existing USB-audio app loop |
| 12 | `consumer_calls` | Calls to stock `0x20d1c8` |
| 16 | `event_signals` | Calls that set event bit 3 through the shared helper |
| 20 | `event_bit3_clears` | Set bit-3 clears through the shared helper; this includes all helper callers |
| 24 | `busy_zero_samples` | Loop samples where `0x200162b4 == 0` |
| 28 | `busy_nonzero_samples` | Loop samples where `0x200162b4 != 0` |
| 32 | `queue_full` | Failed raw pushes to ring `0x200196ac` |
| 36 | `command_total_ticks` | Saturating total of consumer-call timer deltas |
| 40 | `command_max_ticks` | Largest consumer-call timer delta |
| 44 | `last_tick` | Last raw `0x201788` timer sample |
| 48 | `queue_depth` | Current ring count |
| 49 | `queue_highwater` | Ring high-water field |
| 50 | `flags` | bit 0 busy now, bit 1 event bit 3 pending, bit 2 queue nonempty |
| 51 | `reserved` | Zero |

E2 remains readable as the empty guard-diagnostic record. This image rejects E1 at setup and vendor callback; it contains no route to `audio_eq_set_cfg`, `hw_codec_iir_set_cfg`, or another DSP setter. `tools/research/eoic_scheduler_telemetry_probe.py` parses snapshots offline by default. USB use requires both `--send` and `--confirm-read-only-experimental-e3`; it first checks exactly one normal VID:PID and the telemetry CAPS marker, then sends one read-only E3 request. The probe was not run.

## Hook design and safety

The app-loop body at `0x20aa82` is replaced with a Thumb literal tail-transfer to an injected wrapper. The wrapper retains the input in `r0`, samples counters, calls the existing consumer `0x20d1c8`, measures it with the existing raw timer `0x201788`, calls the original `0x209a8c` event service, and repeats. It does not hook `af_thread` (`0x21229e`) or perform an EQ update.

The existing raw queue push `0x20d54c` is replaced at its function entry with a bounded clone. It preserves the ring layout, FIFO write, tail wrap, count/high-water updates, success/full return values, and PRIMASK-preserving critical section. A full result increments one saturating counter only for the known ring address. Event helpers `0x204758` and `0x20479c` are wrapped with the same bit range, flag word, return convention, and interrupt-mask preservation; bit-3 set/clear counters are updated inside that short critical section. The clear counter intentionally includes all callers of the shared helper, not only the USB-audio consumer.

The 52-byte state uses the already reserved tail of RX buffer `0x20019804` at `0x200198b4`; setup caps the receive length from 240 to 176 bytes, as the existing guard-diagnostic wrapper does. The known stock vendor strings are at most 18 bytes. Oversized or undocumented OUT payloads above 176 bytes are not covered by this compatibility claim and remain a risk.

## Offline evidence

The deterministic builder verifies the exact official B SHA-256, appends code in the previously allocated extension envelope, validates Thumb decoding/branches/relocations, checks hook preimages, and reports exact changed ranges. Seven Python tests pass for hash lock/determinism, wire formats, counter saturation, queue wrap/full behavior, event-bit behavior, no setter/busy/MMIO writes in the telemetry source, and hook/image invariants.

The existing Unicorn CPU harness cannot execute `MRS PRIMASK` in this environment: a focused instruction test terminates with SIGILL (exit 132). Therefore the queue/event implementation has source/model tests and static Thumb validation, but not CPU-emulated equivalence testing. No physical device access or firmware deployment was attempted.

## Limits before any physical validation

- The exact RTOS task registration, priority, and task-stack alignment for the app loop remain unresolved. The wrapper executes in the same app-loop context, but its added call depth and timing need live validation.
- No firmware flag proving active playback was identified. Correlate `consumer_calls` deltas with a separately verified active audio stream; do not interpret sample-rate configuration as proof of playback.
- The timer is reported in raw counter units; its frequency and cycle conversion are uncalibrated.
- Three timer reads occur per loop iteration. Consumer timing includes the start/end timer-read costs. Queue/event wrappers add a short PRIMASK-protected counter update; worst-case interrupt latency is not measured.
- Busy samples can miss transitions shorter than one app-loop period. Event clear counts include non-consumer callers.
- E3 is experimental and was not sent. Any physical request or deployment needs separate review and explicit approval under `AGENTS.md`.

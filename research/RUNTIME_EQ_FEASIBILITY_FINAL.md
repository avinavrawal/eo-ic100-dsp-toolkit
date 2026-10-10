# EO-IC100 runtime EQ feasibility — final evidence review

Date: 2026-10-08. Scope: static review of the hash-identified official
Samsung 0.23 image and preserved original 0.04 image, existing disassembly
and indexes, codec reports, and saved E3/E4/E5 captures. No firmware was
modified or built, and no USB/device operation was performed for this
review.

## Decision

**A one-gain runtime EQ extension is technically plausible, but is not
justified as a safe implementation from the available evidence.** The stock
firmware has a RAM-backed EQ description, a coefficient generator, a hardware
bank-update path, and a USB-audio command consumer that handles stock
reconfiguration. However, writable-memory ownership, complete serialization,
the runtime command path through the coefficient staging code, and successful
hardware transaction completion are not established. The physical diagnostic
trace contradicts the simple static expectation that the observed changed
configuration necessarily proceeds to the instrumented late staging point.
The current evidence does not prove an architectural impossibility; it proves
that editing the existing structure and invoking the stock setter cannot yet
be called safe or reliable.

Ghidra 12.1.4 headless is now installed user-locally and was run on both
hash-locked images using ARM:LE:32:v7, raw flash bases, Thumb context, and
startup-copied executable/data aliases. The reproducible command and script
are listed below. This materially confirms the startup mappings and targeted
codec references for both images. The 0.04 reset stub loads the same initial
MSP, `0x20027ff0`.

## 1. Firmware architecture and memory ownership

Both images execute copied code through the SRAM alias `0x00200000` and use
the corresponding data SRAM base `0x20000000`. Existing mapping manifests
identify only initialized flash-to-SRAM regions:

| Image | Flash range (half-open) | SRAM destination | End |
|---|---:|---:|---:|
| 0.23 | `0x8a34..0x11e68` | `0x20000140` | `0x20009574` |
| 0.23 | `0x11eb0..0x1e7bc` | `0x200095d8` | `0x20015ee4` |
| 0.23 | `0x1ebec..0x1ec8c` | `0x20015ee8` | `0x20015f88` |
| 0.04 | `0xec5c..0x19214` | `0x20000140` | `0x2000a6f8` |
| 0.04 | `0x1925c..0x25f04` | `0x2000a75c` | `0x20017404` |
| 0.04 | `0x262fc..0x26394` | `0x20017408` | `0x200174a0` |

Ghidra's reset/copy startup confirms the first source range
`[0x8a34,0x11e68)` to `0x20000140..0x20009574`, zeroes
`0x20009574..0x200095d4`, copies the next initialized range to
`0x200095d8..0x20015ee4`, zeroes `0x20015ee4..0x20015ee8`, and copies the
third initialized range to `0x20015ee8..0x20015f88`. The reset stub loads
initial MSP `0x20027ff0`. There is a separate startup copy into executable
alias `0x00227ff0`; it is not a normal data allocation. These are confirmed
startup actions, **not** a full memory map. The gap between the first 0.23
BSS clear and the next initialized segment is only four bytes
(`0x200095d4..0x200095d8`), too small for the proposed subsystem. Ghidra
confirms 0.04 copies
`[0xec5c,0x19214)` to `0x20000140..0x2000a6f8`, zeroes
`0x2000a6f8..0x2000a758`, copies `[0x1925c,0x25f04)` to
`0x2000a75c..0x20017404`, zeroes `0x20017404..0x20017408`, then copies
`[0x262fc,0x26394)` to `0x20017408..0x200174a0`. Heap bounds/ABI, total SRAM
end, MPU policy, and the relationship of MSP to usable task stacks remain
unresolved. No BSS extension or safe heap allocation is established. The
shared 240-byte USB RX reservation is already in use and is not available as
EQ storage.

The official 0.23 EQ object is initialized at `0x20015bec` (image file offset
`0x1e4c4`). Its pointer table at `0x20015c78` selects that object. The object
format is a 12-byte `<float left_gain, float right_gain, uint32 band_count>`
header followed by eight possible 16-byte `<uint32 type, float gain,
float frequency, float Q>` records: maximum format size 140 bytes. The stock
object has two populated filters, so its meaningful data is 44 bytes. The
first band's gain is at `0x20015bfc`. The 0.04 counterpart is at
`0x20017100`, with pointer list `0x2001718c`; the busy byte also moves from
`0x200162b4` (0.23) to `0x200177cc` (0.04).

`audio_eq_set_cfg` passes the selected pointer into coefficient generation,
which writes scratch at `0x20015fa4`; the lower-level setter also stores the
configuration pointer at `0x200162c0`. This confirms that the config is read
from RAM and that a pointer is retained. The exact complete set of readers and
writers of the object and retained pointer has **not** been established. The
traced path has no runtime flash read, but the object-wide writer audit is
incomplete. CPU-writable SRAM is likely; MPU/write permission and exclusive
ownership are not proven. Replacing, relocating, or editing this object is
therefore **UNRESOLVED**, not approved by its location alone.

| Memory requirement | Status | Evidence / limit |
|---|---|---|
| Initialized 0.23 EQ object and pointer-table target | **PROVEN** | Hash-keyed map, parser, and selector disassembly. |
| Config ABI, stock values, maximum 140-byte format | **PROVEN** | `<ffI>` + eight `<Ifff>` capacity; two records populated. |
| Setter consumes config and materializes coefficients in scratch | **PROVEN** | `0x20a938` → `0x20a178`; scratch `0x20015fa4`. |
| Setter retains config pointer in global `0x200162c0` | **PROVEN** | Store in `0x20a424` path. |
| All readers/writers and lifetime of retained pointer | **UNRESOLVED** | No exhaustive data-flow/alias audit. |
| Safe in-place edit while running | **UNRESOLVED** | Memory permission, exclusive ownership, and complete synchronization absent. |
| Verified relocation/allocation/BSS extension | **DISPROVEN for current patcher contract** | Linker rejects writable BSS; no evidenced allocator/heap bounds; RX reservation shared. This does not prove the silicon has no allocator. |
| Safe rollback after an in-place update fails | **DISPROVEN for current call contract** | Setter may hang in stock ACK waits; higher-level return does not reliably propagate lower-level error; hardware bank outcome may be unknown. |

## 2. Codec reconfiguration control flow

The confirmed 0.23 stock path is:

```text
USB-audio app loop 0x20aa20
  -> command consumer 0x20d1c8
  -> stock configuration branch / helper
  -> usb_audio_open_eq(0, 2) at 0x20c840
  -> 0x20a994(config, 0x18, 2)
  -> 0x20a868(config, 1)
  -> usb_audio_set_eq(2, 0) at 0x20c800
  -> audio_eq_set_cfg(0, config, 2) at 0x20a938
  -> hw_codec_iir_get_cfg at 0x20a178
  -> coefficient scratch 0x20015fa4
  -> hw_codec_iir_set_cfg at 0x20a424
  -> stage coefficient bank at 0x40302000..0x40302340
  -> request/ack via 0x403000e0 bit 22 / bit 24
  -> on observed success path: clear busy at 0x20a774 and update selector
```

`usb_audio_set_eq(2,0)` selects the fixed pointer-table entry. Other indexes
are rejected; stock USB command handlers do not provide arbitrary EQ payloads.
There are seven identified stock `usb_audio_open_eq` call sites in the
command consumer/helpers. This proves stock reconfiguration entry points,
not the number of invocations per boot/session or that each executes while
audio samples are flowing.

The lifecycle helper behavior is branch-dependent. For an already initialized
codec and enable argument 1, `0x20a868` updates lifecycle state and clears the
software byte at `0x200162b4` (`0x20a884`), then `usb_audio_open_eq` invokes
the EQ selector/setter. If initialization is absent, the alternate setup
branch runs and does not execute that clear. The separate disable path
`0x20a9b0 -> 0x20a900(1)` clears initialized/peripheral state but not the busy
byte. Later `0x20c8f2`/`0x20c8fa` calls are confirmed in order, but their
interpretation as a complete stream stop/resume contract is inferred, not
proven.

The lower-level setter sets busy at `0x20a478`. The successful path waits for
the hardware acknowledgement and clears it at `0x20a774`; stock waits are
unbounded. Error exits `0x20a5ea` and `0x20a78c` can return without that clear.
The alternate path contains a second acknowledgement sequence. Thus failure
may strand software state. A later lifecycle clear exists but is tied to a
specific initialized+enable branch, not a general transaction abort. Forcing
that branch or clearing the byte without proving hardware quiescence is not a
safe recovery method.

Ghidra mapped the 0.04 EQ functions and verified the selected RAM alias
references to config `0x20017100`, pointer table `0x2001718c`, busy byte
`0x200177cc`, and peripheral `0x403000e0`. Its startup copy/zero ranges are
confirmed above. Exact old-image dispatcher parity, runtime call frequency,
and lifecycle branch equivalence were not fully re-audited. No evidence shows
that 0.04 provides a missing runtime EQ facility.

## 3. Synchronization and scheduling contract

The 30-entry, 4-byte command ring is at backing address `0x20019634`, with
control object `0x200196ac`. Raw push/pop are `0x20d54c`/`0x20d5b4`; reviewed
push/pop mutations briefly preserve interrupt mask state. The software app
loop at `0x20aa20` calls consumer `0x20d1c8`, which drains commands
sequentially. The ordinary enqueue wrapper is unsuitable for EP0 because its
full-queue path performs diagnostics; a raw single try plus event-bit-3
signal is only a candidate design.

This gives **partial serialization**: the consumer serializes command work
that reaches it against other work in that consumer. It does not prove that
all codec control-register/configuration accesses use this queue. The task
creator/RTOS registration, priority, preemption relationship to the frame
worker, event-bit wake semantics, EP0 callback interrupt context, and whether
bounded ACK polling would delay audio/control tasks remain unresolved. The
`af_thread` path is frame-critical and is not a safe place for synchronous
coefficient programming. There is no demonstrated firmware-level atomic
mailbox contract between EP0 and the consumer.

| Synchronization requirement | Status | Evidence / limit |
|---|---|---|
| Stock EQ configuration can be reached from command consumer | **PROVEN** | Call sites and dispatcher disassembly. |
| Consumer processes queued commands sequentially | **PROVEN** | Ring pop/dispatch loop. |
| Queue serializes against reviewed stock EQ paths in that consumer | **PROVEN, scoped** | Same consumer flow; does not cover other contexts. |
| Queue is sole codec owner | **UNRESOLVED** | No exhaustive cross-context access audit. |
| EP0 can safely publish without blocking/deadlocking | **UNRESOLVED** | Raw push is bounded, but callback context and publication/wake contract unproven. |
| App task may tolerate bounded hardware wait | **UNRESOLVED** | Priority and scheduling/preemption contract absent. |
| Direct synchronous work in frame-critical audio callback is safe | **DISPROVEN** | Callback is timing-critical; no bounded execution budget supports the setter. |

## 4. Deterministic model versus physical captures

The evidence-driven model has states `idle`, `transaction-owned`,
`request-asserted`, `ack-high`, `request-cleared`, `ack-low`, and
`completed`; the observed static success transition clears busy and changes
the bank selector only after the acknowledgement sequence. Static error
edges can leave the transaction-owned state busy. Inputs needed to choose
the pre-request branches include live config/count/pointer/state values and
hardware state that are not present in the static image. They must remain
unknown in a model; assigning “valid” values would turn it into a speculative
simulation.

Saved physical evidence was compared as observations, not fitted to force the
model to pass:

| Capture | Observed | Consequence |
|---|---|---|
| E3 lifecycle | Idle: 1028/1028 busy-zero samples. During playback: first sampled interval 2810 busy-nonzero and 1039 cumulative zero samples (99.61% busy); subsequent playback and 30 seconds after stop remained busy. Consumer calls continued; queue depth/full stayed zero; event signals and clears paired. | Busy is not merely a continuously set boot flag. Host playback correlates with the transition, but does not prove continuous codec work or identify the writer. The consumer remains schedulable; queue emptiness does not show EQ command work. |
| E4 ACK diagnostic | One transaction entry; request assert, ACK high, request clear, ACK low, bank toggle, busy clear, error exit all zero. At diagnostic event snapshot register `0x403000e0=0x88`, software busy 1, selector 0. | No instrumented ACK phase was observed. This is inconsistent with a completed instrumented transaction; it cannot distinguish pre-request control flow from a missed/uninstrumented request path. |
| E5 pre-request trace | During playback: busy checkpoint +1 with busy-branch not taken (the setter's reject branch was not taken), changed-config edge +1, equal edge 0. Late coefficient-copy checkpoint `0x20a6d4`, main request, alternate request all remained zero; busy 1, selector 0, live register `0x1f`. | Contradicts the simple model that a changed configuration at entry necessarily reaches late coefficient staging/request. It does not prove coefficient staging was entirely bypassed: hooks do not cover every earlier instruction/branch, and runtime pointers/state were not captured. |
| Pause/apply E4/E5 | After stopping/releasing the stream, busy remained 1, request/ACK/selector stayed 0; E5 live register `0x1f`. E4 retained event-time `0x88`. | No natural ready window was observed. The two register values are from different snapshot semantics/times and are not interchangeable. |

Accordingly, the deterministic model reproduces the **known control-flow
contracts and observed telemetry**, but does not reproduce hidden internal
state from captures and is not evidence that the firmware would complete an
update. The unresolved E5 interval after changed-config branch and before
`0x20a6d4` is the strongest contradiction to a straightforward reuse plan.

## 5. Requirements decision and decisive evidence

| Requirement for runtime EQ | Classification | What is established / missing |
|---|---|---|
| Receive and validate a bounded gain request | **PROVEN as custom protocol behavior** | E1 was accepted and its payload validated in prior controlled diagnostic work. |
| Reach an existing coefficient-generation/setter chain | **PROVEN statically** | Fixed stock path exists; arbitrary host config is not stock behavior. |
| Change one config value in live RAM without a second buffer | **UNRESOLVED** | Object is RAM-backed, but complete ownership, permissions, all aliases/writers, and synchronization are unknown. |
| Safely allocate/relocate an inactive 140-byte config | **UNRESOLVED / no supported method found** | No proven heap/BSS allocator/range; current patcher disallows writable allocation. |
| Execute reconfiguration from a non-frame-critical serialized context | **UNRESOLVED** | Queue serializes reviewed commands only; task registration, priority, sole ownership, and EP0 contract missing. |
| Complete transaction and update bank on current device | **DISPROVEN for the observed tested path** | E4/E5 show transaction entry/busy but no instrumented request, ACK, bank toggle, or busy clear. This does not prove every state/path fails. |
| Bounded, rollback-safe failure using stock setter semantics | **DISPROVEN** | Stock ACK waits are unbounded; error exits may strand busy; higher-level status does not reliably propagate and hardware state may be ambiguous. |
| A one-gain prototype is safe to implement/deploy now | **DISPROVEN by current evidence threshold** | Memory, synchronization, path-to-staging, completion, and rollback preconditions are not established. |

The minimum evidence that could change this decision is:

1. Establish total SRAM/heap/task-stack ownership and exhaustive 0.23
   references/data-flow for `0x20015bec`, `0x20015c78`, and `0x200162c0`,
   including aliases and indirect accesses.
2. The actual RTOS task-registration record and priority for `0x20aa20`,
   plus proof of its preemption/wait behavior relative to `af_thread` and all
   codec-control callers; also prove the EP0 callback can publish a command
   with bounded nonblocking operations.
3. A narrowly instrumented diagnostic that captures the exact branch
   predicates, source/destination pointers, bounds/count, and progress at
   every edge from `0x20a462` through `0x20a6d4`, and resolves the E5 gap
   without changing codec behavior. A repeat test would require separate
   physical authorization; none is proposed or performed here.
4. A captured, naturally completed stock codec reconfiguration showing the
   request/ACK/bank-toggle/clear order and a proven quiescent failure path.
   Any later prototype must first bound waits and demonstrate rollback at
   the firmware/hardware level; a Python model alone is insufficient.

## Evidence index and reproducibility

Primary cached artifacts:

- `research/cache/runtime-eq-official023-9ebc51140b17884a/mapping.json`
  (official source SHA-256 `9ebc51140b17884a9b3fe97edc58f8b3861ec10dbc0a33499ea31200bdedba87`)
- `research/cache/runtime-eq-original004-6ee1089955817ac0/mapping.json`
  (preserved original SHA-256 `6ee1089955817ac0deda01aab8eb7531f3bdd11dd1604fd8c143d6d1538eb0cd`)
- `research/cache/custom-vendor/eq-call-graph.json`
- `research/cache/custom-vendor/codec-scheduler-analysis.json`
- `research/cache/custom-vendor/codec-command-dispatch-expanded.txt`
- `research/CODEC_RECONFIGURATION.md`, `research/EQ_RAM_LIFECYCLE.md`,
  `research/CODEC_SCHEDULER.md`, `research/BUSY_FLAG_STATE_MACHINE.md`,
  `research/DEFERRED_EQ_FEASIBILITY.md`
- `research/cache/caps-macos/scheduler-telemetry-lifecycle-20261008/lifecycle-decoded.json`
- `research/cache/caps-macos/codec-ack-deploy-20261008/postboot/e4-decoded.json`
- `research/cache/caps-macos/codec-ack-progress-deploy-20261008/postboot/e5-decoded.json`
- `research/cache/caps-macos/pause-apply-20261008/`

The Ghidra installation is user-local (Ghidra 12.1.4; Temurin Java 21.0.12)
and is not added to the repository. Reproduce both imports/exports with:

```sh
python3 tools/research/ghidra/run_runtime_eq_analysis.py --profile all
```

This verifies each input SHA-256 before running `analyzeHeadless`; the script
`tools/research/ghidra/EoicMapAndExport.java` creates the aliases, seeds only
the targeted functions, and writes bounded exports to ignored
`research/cache/ghidra-runtime-eq/{official023,original004}/`. Ghidra output
confirms both startup copy/zero sequences and targeted literal references;
it is not a whole-program proof of aliases or indirect writers. Mapping
generation is described by `tools/research/runtime_eq_map.py`; cached
analysis identity is tied to image hashes and settings. The physical capture
decoders and raw logs are retained in ignored `research/cache/`. Existing
queue/RAM-shadow unit models validate their explicitly modeled contracts only;
they do not model undocumented SRAM ownership, RTOS scheduling, codec silicon,
or the E5-unobserved branches. No new firmware, model result, or test is
presented as physical proof.

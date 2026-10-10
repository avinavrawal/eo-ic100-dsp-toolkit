# Custom EO-IC100 runtime-EQ architecture (offline design)

Date: 2026-10-09. Base: Samsung/BES 0.23. This document reuses the
hash-locked Ghidra exports, codec and scheduler reports, custom USB protocol,
and E3/E4/E5 physical evidence already in this repository. No USB/device
operation, firmware modification, or deployable image build was performed.

## Decision

The custom subsystem is **architecturally plausible**, and avoids the stock
high-level EQ configuration API, but the smallest single-gain prototype is
**not technically implementable safely from current evidence**. The missing
items are not general reverse-engineering work: no address range has proven
exclusive writable ownership; the USB-audio loop's task registration and
priority are unknown; the complete hardware coefficient-bank ABI and a safe
owner lock are incomplete; and codec reinitialization has no proven
post-initialization callback for replaying the custom gain. The custom model
tests validate a proposed contract only.

The strongest confirmed RAM facts are the 0.23 reset stack value
`0x20027ff0`, initialized copies through `0x20015f88`, and BSS clearing of
`0x20009574..0x200095d4` plus `0x20015ee4..0x20015ee8`. These facts do not
establish the physical SRAM end, heap bounds, task stacks, or MPU policy. The
value `0x20027ff0` is an inferred top-of-RAM stack value, not proof that the
device contains exactly 160 KiB of SRAM.

## Memory layout proposal and allocation method

The exact **logical** pool layout for the one-gain prototype is 0x400 bytes,
aligned to 16 bytes. The base is intentionally symbolic because choosing a
physical address would be guessing:

| Pool offset | Size | Contents | Ownership status |
|---:|---:|---|---|
| `+0x000..+0x020` | 32 B | Two gain/config generations, active/pending indices, version and guards | Required, address unassigned |
| `+0x020..+0x360` | 832 B | Candidate coefficient staging image, sized to observed MMIO span `0x40302000..0x40302340` | Upper-bound proposal only; exact hardware image size/layout unverified |
| `+0x360..+0x3e0` | 128 B | Worker state, queue result, status snapshot and counters | Required, address unassigned |
| `+0x3e0..+0x400` | 32 B | Canary/red zone | Required, address unassigned |

The 0.23 image's first data copy ends at `0x20009574`; startup clears through
`0x200095d4`, and the next copied range begins at `0x200095d8`. The four-byte
gap is too small. The memory above the last copied byte `0x20015f88` and below
the loaded MSP `0x20027ff0` is not demonstrated free; it may hold heap, RTOS
objects, task stacks, DMA buffers, or reserved memory. The shared 240-byte
USB receive area is owned and excluded. **There is no safe absolute pool
address in the current evidence.**

Reproducible allocation method once a linker map/ownership proof is obtained:

1. Add an explicitly named `.eoic_runtime` `NOLOAD` section of exactly
   `0x400` bytes, alignment 16, to the extension linker. Require a verified
   `RAM_ORIGIN`/`RAM_END`, heap bounds, static object map, task-stack bounds,
   and DMA reservations. Linker `ASSERT`s must prove the whole section lies
   in a writable region and overlaps none of those owners.
2. Add a reset-time zero-initializer for the section after Samsung's existing
   data copies and BSS clears, before normal application tasks can access it.
   The startup routine ends at image offset `0x1aa` (`pop {r3,pc}` in the
   0.23 A-base export). That is a *candidate integration point*, not a
   validated patch site: the adjacent literal pool and relocated B-slot
   addresses mean a trampoline/relocation must be proven before patching.
3. Emit and hash the linker map, initializer disassembly, overlap checks and
   post-link zero-range validation as build outputs. A RAM region must not be
   accepted merely because it is between known initialized sections.

Current patcher `tools/research/arm_elf.py` rejects writable/BSS allocations.
No extension has been made to it because neither RAM boundary nor pool
ownership is established.

## Minimal USB protocol proposal

Keep existing E0 CAPS and E1–E6 diagnostic behavior byte-for-byte. The new
commands are firmware-extension-only proposals; they have not been sent to a
device and their numbers still require a whole-dispatcher collision audit.

### `SET_GLOBAL_GAIN` — proposed E7

| Field | Value |
|---|---|
| `bmRequestType` | `0x40` (vendor, device, OUT) |
| `bRequest` | `0xE7` (candidate; unverified collision-free) |
| `wValue` | `0x454F` |
| `wIndex` | `0x4943` |
| `wLength` | exactly 4 |
| payload | IEEE-754 float32 little-endian, dB, finite range `[-12.0, 0.0]` |

The USB callback validates the complete setup tuple, exact length, finite
float and range. It quantizes to signed centi-dB (`-1200..0`) and performs one
bounded raw enqueue of command ID `0x13`; the reviewed table routes `0x13` to
the unknown-command logger, making it a candidate dispatch hook. No callback
may touch coefficient registers or wait for the codec. Queue full/contended
returns a defined rejected-control result with no partial publication. The
slow `usb_audio_enqueue_cmd` wrapper is prohibited because its full path runs
diagnostics. The raw push/event-bit setter are short and bounded in static
code, but their complete EP0 integration and wake semantics remain
unverified.

### `GET_RUNTIME_EQ_STATUS` — proposed E8

| Field | Value |
|---|---|
| `bmRequestType` | `0xC0` (vendor, device, IN) |
| `bRequest` | `0xE8` (candidate; unverified collision-free) |
| `wValue` | `0x454F` |
| `wIndex` | `0x4943` |
| `wLength` | exactly 20 |
| response | fixed little-endian structure below |

Response offsets: `0..3` magic `EOEQ`; `4` protocol version 1; `5` worker
state; `6` result; `7` flags (bit 0 hardware state known, bit 1 reapply
pending); `8..9` generation; `10..11` applied gain centi-dB; `12..13`
requested gain centi-dB; `14` active bank (`0`, `1`, or `0xff` unknown); `15`
request/ACK snapshot (bit 0 request, bit 1 ACK); `16..17` completed count;
`18..19` error count. The worker owns status updates. EP0 copies an atomic
snapshot using a short bounded critical section; it does not mutate DSP or
persistent state.

Proposed results: `0 NONE`, `1 ACCEPTED`, `2 APPLIED`, `3 BAD_REQUEST`,
`4 BAD_PAYLOAD`, `5 QUEUE_FULL`, `6 READY_TIMEOUT`, `7 ACK_HIGH_TIMEOUT`,
`8 ACK_LOW_TIMEOUT`, `9 REINIT_PENDING`. Proposed states: `IDLE`, `QUEUED`,
`WAIT_READY`, `WRITE_INACTIVE`, `WAIT_ACK_HIGH`, `WAIT_ACK_LOW`, `COMPLETE`,
`ERROR`, `HARDWARE_UNKNOWN`.

The existing custom handler uses E0–E6 for capabilities, mutation test,
diagnostics, scheduler telemetry, ACK/pre-request telemetry and E6 status.
The base stock callback's request-number behavior was not exhaustively
audited for E7/E8, so the extension must first prove exact interception and
preservation of all stock requests offline. No unknown request may be sent
to hardware for collision testing.

## Worker and queue

Use the existing USB-audio ring: 30 entries, four bytes each, at backing
`0x20019634`, control object `0x200196ac`; push `0x20d54c`, pop `0x20d5b4`,
consumer `0x20d1c8`, app loop `0x20aa20`. Command ID `0x13` is the candidate
unused ID. A signed centi-dB value fits the two currently dispatched argument
bytes. Preserve all existing command IDs and FIFO order. EP0 must make one
nonblocking enqueue attempt; it must never spin or call the diagnostic wrapper.

The candidate worker is a nonblocking state machine advanced by the
USB-audio app/command loop, not `af_thread`. Each loop turn performs one
bounded step, and never waits in a polling loop. The existing loop is
confirmed distinct from frame-critical `af_thread` and observed running
during playback. Its RTOS task registration, priority, response cadence and
preemption contract are unknown; therefore it is not yet approved as a
hardware writer. A new RTOS task is less defensible until the task-creation
ABI and priorities are recovered. All stock codec-bank operations must share
one owner/serialization contract with the custom worker; current evidence
only proves serialization for the reviewed commands inside this consumer.

## Custom coefficient-bank state machine

Confirmed stock facts: coefficient writes address the region
`0x40302000..0x40302340`; control/request register is `0x403000e0`; bit 22 is
the request/select operation and bit 24 is the acknowledgement. The stock
setter has a path that asserts bit 22 and polls for bit 24 high, and an
alternate path that clears bit 22 and polls for bit 24 low. Both stock waits
are unbounded. The software selector is at `0x200162bc`; stock changes it
only on its success path. Diagnostic E4/E5 observations show that earlier
E1 attempts did not reach the instrumented request point. No physical sample
has validated custom register writes or a successful custom bank change.

Proposed custom worker transaction:

1. `WAIT_READY`: require codec initialized, no custom transaction, stock
   codec owner released, and hardware request/ACK bits in a recognized idle
   combination. Never clear or bypass Samsung's busy byte. If the stock
   busy byte remains set and ownership cannot prove it stale, defer then
   time out without MMIO writes.
2. `WRITE_INACTIVE`: compute coefficients in extension-owned staging RAM and
   write only the inactive bank, preserving the active bank. Bound writes per
   worker turn.
3. `WAIT_ACK_HIGH`: assert request once, record a deadline, then sample once
   per worker turn. On high, proceed; on deadline, do not retry. Report
   `HARDWARE_UNKNOWN` because a late hardware transition cannot be excluded.
4. `WAIT_ACK_LOW`: clear request once and sample once per worker turn. Only
   after the ACK-low transition may the software active-bank/config
   generation commit. On timeout, leave logical active config unchanged,
   mark hardware unknown, and stop accepting gain updates until a proven
   reinitialization.
5. `COMMIT`: publish applied gain/bank/status atomically. The previous
   configuration remains in the other RAM slot. If failure occurs before
   request assertion, discard staging and retain prior active state. After
   request assertion, rollback is not claimed unless hardware bank state can
   be observed and re-synchronized; no blind second swap is allowed.

The bit names and stock success ordering are confirmed; the exact physical
bank geometry, which words are channel/global gain versus per-band IIR,
inactive-bank address mapping, reset values, and a recoverable timeout
sequence are not fully established. Thus this state machine is a design
contract, not permission to write `0x4030xxxx` or an implementable register
driver yet. A custom coefficient generator must be independently validated
against the stock 0.23 conversion for supported sample rates. Scaling a
coefficient mathematically is not evidence that the codec interprets the
custom words as intended.

## Codec reinitialization and A/B meanings

“A/B configuration” here means two volatile runtime configurations and two
hardware coefficient banks; firmware slot A remains immutable recovery and
slot B remains the only experimental image. Runtime config generations live
in the owned pool and survive codec disable/enable while power remains. They
do not survive a reset or unplug; no NVM persistence is proposed.

After a codec reset, mark the active hardware bank unknown but retain the
last desired gain in RAM. Wait for a proven codec-ready/stock-EQ-complete
event, establish the stock baseline bank, and reapply the saved custom gain
before reporting it applied. `usb_audio_open_eq(0,2)` calls lifecycle setup
then stock EQ application, but the exact stream-quiescence and post-init
completion callback are not proven. Hooking only the enable bit or observing
`codec_initialized` is insufficient to prove the coefficient engine is
ready. If reset occurs during a custom transaction, report hardware state
unknown and require baseline initialization before accepting another update.

## Patch points and gates

| Patch point | Purpose | Evidence/status |
|---|---|---|
| Normal USB callback for exact E7/E8 tuple | Validate/write status protocol | Existing custom request framework works; E7/E8 collision audit and receive ABI tests required |
| Raw queue push + event bit 3 | Publish command without EP0 blocking | Helpers are bounded in static code; complete integration is not proven |
| `0x20d1c8` ID `0x13` fallback | Dispatch to worker state | Candidate unused table ID; preserve unknown IDs and stock commands |
| `0x20aa20` loop after consumer | One bounded worker step | Non-frame candidate; priority/cadence/codec-owner contract unresolved |
| Startup copy/zero tail near image offset `0x1aa` | Zero the extension pool | Candidate only; trampoline and slot relocation not validated |
| All stock codec update entry paths + custom worker | Shared serialization/ownership | Only reviewed queue paths proven; exhaustive ownership unresolved |
| Codec init completion path | Mark baseline ready and reapply gain | No confirmed post-init callback or readiness predicate |

No patch point is approved for implementation until the gates below pass.

## Offline model and tests

Added `tools/research/custom_runtime_eq_model.py` and
`tools/research/test_custom_runtime_eq_model.py`. They deterministically test
the proposed E7 parser, exact length/setup checks, finite gain range,
centi-dB queue packing, bounded queue-full behavior, deferred state
transitions, ACK-high/low commit ordering, ready timeout without writes,
ambiguous ACK timeout reporting, E8 status length, and desired-gain retention
across a modeled codec reinitialization. These are protocol/model tests only;
they do not execute firmware instructions, MMIO, USB, timing, or DSP code.

Commands and results:

```sh
cd tools/research
python3 -m unittest -v test_custom_runtime_eq_model.py
```

Result: 9 model tests passed. The full offline research suite also passed:
`python3 -m unittest discover -s tools/research -p 'test_*.py'` — 105 tests.
No patched image was generated.

## Explicit blockers and feasibility decision

| Requirement | Classification | Reason |
|---|---|---|
| Exact physical SRAM bounds | **UNRESOLVED** | Reset provides MSP `0x20027ff0`, not SRAM size/end; no chip map or linker map available. |
| 0x400-byte exclusively owned writable pool | **UNRESOLVED** | No heap/task-stack/DMA/MPU ownership map; all observed gaps are too small or potentially allocated. |
| Reproducible BSS allocation | **DESIGN ONLY** | Linker can add a named/asserted section only after a verified RAM region; startup zero-hook ABI/relocation is not validated. |
| Existing 30×4 queue and candidate ID `0x13` | **CONFIRMED / scoped** | Static consumer/table findings; not proof of RTOS scheduling. |
| Safe worker task/context | **UNRESOLVED** | `0x20aa20` is non-frame and active, but priority, cadence, and all codec owners are unknown. |
| Basic register handshake signals | **CONFIRMED / partial** | Request bit 22, ACK bit 24, two stock edges; actual custom transaction, full bank map and timeout recovery are unverified. |
| Rollback after request timeout | **UNRESOLVED** | Hardware may switch after a missed/late ACK; no safe observed bank-readback exists. |
| Runtime gain survives codec reinitialization | **DESIGN ONLY** | RAM retention is straightforward; ready event and safe reapply point are unproven. Power-cycle persistence is explicitly out of scope. |
| One-gain prototype implementable now | **NO** | It cannot be assigned memory or execution ownership without guessing, and coefficient/bank/rollback semantics are incomplete. |

The next decisive work is narrow and offline: obtain the BEST3005 SRAM map or
SDK linker/map artifacts for the exact SoC revision; recover heap and RTOS
task/stack allocation bounds; verify the slot-B startup trampoline/zero
initializer against the current linker; and complete the hardware coefficient
bank register map from existing setter disassembly. Only after these establish
an owned pool and a serialized non-frame context should an implementation
branch begin. Any physical register experiment would require separate explicit
approval and is not part of this work.

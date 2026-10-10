# Deferred runtime EQ feasibility

Status: **candidate architecture identified; execution-context proof incomplete**.
Offline only; no firmware patch, tuner changes, E1/E2, or USB operations.

## CONFIRMED

- `usb_audio_enqueue_cmd` is implemented at `0x20ab28`; callers at `0x20b1ca` and `0x20b588` enqueue 32-bit command words. The ring is at `0x200196ac`, payload storage at `0x20019634`, and the generic bounded push/pop routines are `0x20d54c`/`0x20d5b4`.
- Consumer `usb_audio_cmd_handler` starts at `0x20d1c8`, drains queue entries, dispatches by command byte, and is called from the software loop at `0x20aa82`. The loop calls `0x209a8c` and repeats.
- Several command-handler paths call `usb_audio_open_eq` and the existing EQ setter chain. Therefore the command loop is where Samsung already processes reviewed stream-related EQ reconfiguration.
- The ring contains 30 uint32 entries (120 bytes) at `0x20019634`; object `0x200196ac` stores head/read at +0, tail/write at +1, count at +2, capacity at +3, high-water at +4, and data pointer at +8. The command ID is bits 0–7 and observed arguments are bits 8–23; the reviewed dispatcher does not consume the top byte.
- Raw push `0x20d54c` is a single bounded try and returns full immediately. After successful insertion, wrapper `0x20ab28` calls `0x204758(3)`, which atomically sets event bit 3 at `0x20019a0c`; on full it loops through queue-dump/status diagnostics. A candidate EP0 path can call raw push once and signal event 3 only on success, subject to callback-context and mailbox-publication proof.
- `0x204758(3)` only ORs the shared software event word; it does not call an RTOS wake/scheduler API. The consumer clears bit 3 at `0x20d1d0`, drains the ring, then the app loop calls `0x209a8c`, whose event-service body reads the shared word. Whether this is a blocking wait or a wakeable task event is unresolved.
- Dispatch table `0x20d20a` covers command IDs `0x00`–`0x14`. ID `0x13` is the only table entry directed to generic unknown-command logging at `0x20d418`; it is the safest available extension ID if only that fallback case is intercepted. IDs above `0x14` must keep their existing generic log path.
- Neither cached RAM/flash xrefs nor a raw scan of initialized RAM contains a pointer/reference to `0x20aa20` or Thumb address `0x20aa21`. No task registration record or priority was recovered; runtime-built/indirect registration remains possible.
- All reviewed stock EQ-open routes pass through `usb_audio_cmd_handler`, which dispatches sequentially. This serializes with those paths only, not every possible codec owner.
- `af_thread` at `0x21229e` is frame-critical and is rejected as a synchronous setter worker.
- Setter completion is tied to hardware acknowledgement and bank-selector update. The stock failure paths can strand the busy flag; do not clear or bypass it.

## INFERRED

Candidate architecture: validate/copy one request in EP0, perform exactly one
raw ring push, and return an explicit full/contended error if admission fails.
The consumer would retrieve an associated single-slot mailbox and process it
in FIFO order. It must check codec/busy state, never force-clear the byte, and
use the bounded setter path. The offline harness in
`tools/research/codec_queue_model.py` validates this proposed contract only;
it does not prove a firmware mailbox can be published atomically from EP0.

## UNVERIFIED

- The exact RTOS task that invokes the `0x20aa20` loop, its priority and preemption relationship to `af_thread`; bounded ACK polling may affect audio depending on these unknown scheduling facts. Interrupts can preempt the setter's polling loop, but lower-priority task service is not guaranteed during it.
- Whether all runtime codec operations serialize through this queue.
- Whether a finite ACK loop can starve audio processing at that task's actual priority.
- A firmware-level mailbox publication/ownership protocol for EP0 and the command loop. Direct raw push plus event-bit set has fixed bounded work and no blocking call, but event-driven task wake semantics and the actual EP0 callback integration are not proven.
- Whether audio remains continuous through a bounded setter timeout on real silicon.

## DISPROVEN

- Direct setter call from EP0: synchronous coefficient work/ACK polling can block control completion.
- `af_thread` as worker: frame-critical dispatch and overrun/lost-signal warnings.
- Blind busy-flag clear, direct bank writes, or using the diagnostic-loop `usb_audio_enqueue_cmd` wrapper from EP0 as a presumed nonblocking operation.

## Stop condition and next decisive offline analysis

The ring ABI, raw push, event-bit set/clear, and free command-ID fallback are
reconstructed. The offline model passes queue and candidate-dispatch cases,
but it does not establish task registration/priority, scheduler response to
event bit 3, global codec serialization, or actual firmware mailbox
ownership. A bounded codec ACK wait therefore cannot yet be approved in this
loop.

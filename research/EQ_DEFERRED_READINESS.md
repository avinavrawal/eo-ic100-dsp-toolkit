# Deferred EQ prototype readiness

**Status: BLOCKED before firmware implementation.** No firmware source, host
utility, or binary was changed or generated for this request. No USB operation
was performed.

The known E1 handler currently validates and calls `audio_eq_set_cfg`
synchronously from `eoic_vendor`; that path must be replaced by a copied,
validated request in a queue. The queue cannot safely be drained from the only
identified worker candidate: the `af_thread` loop around `0x0021229e`–
`0x002123bc` dispatches stream handlers through a function pointer and tracks
lost signals / handler overrun. The setter performs coefficient generation
and synchronous codec-register waits (bounded to 65,535 reads in the modified
image). Running that operation in this frame-critical loop can delay audio
processing and is not an acceptable “safe worker” hook.

The cached function index identifies `usb_audio_enqueue_cmd` only through its
diagnostic string and local queue-overflow path near `0x0020ab28`. It does not
identify a command-consumer task, its command ABI, a codec serialization lock,
or a safe deferred callback. No reviewed queue API is currently available to
the extension. Guessing a queue layout or repurposing an audio callback would
not meet the requirement to serialize with stock codec updates.

Existing stock EQ setter state remains unchanged: set `0x200162b4` at
`0x0020a478`; ordinary ACK cleanup at `0x0020a774`; two post-set status-3
returns can miss that cleanup. The diagnostic image's timeout helpers clear
only after their bounded timeout recovery. The implementation must not add a
direct write to this flag. `GET_EOIC_CAPS` and E2 remain unchanged in all
existing reviewed images.

**Minimum blocker to resolve:** establish a proven non-frame-critical codec
or audio-control worker and its enqueue/dequeue ABI, including how it
serializes with `usb_audio_open_eq` and the stock setter. Then implement a
single-slot/latest-value queue with explicit queued/running/success/error/
timeout diagnostic states, reuse the existing bounded ACK helpers, and test
that every error path leaves the previous bank selected. Until that worker is
identified, there is no defensible worker hook or deterministic patched
firmware to report.

Evidence reused: hash-locked `eq-diagnostic-guards-report.json`,
`eq-call-graph.json`, `function-index.json`, `thumb-xrefs.json`,
`eq-audio-worker-loop.txt`, and `eq-audio-worker-window.txt` under ignored
`research/cache/custom-vendor/`; detailed flag sites are in
`research/EQ_BUSY_FLAG_LIFECYCLE.md`. No whole image or new disassembly was
loaded into model context.

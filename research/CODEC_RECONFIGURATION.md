# EO-IC100 codec reconfiguration paths (static reconstruction)

Scope: official Samsung 0.23 and preserved original 0.04 disassembly already
cached in this repository. This pass used those indexes and focused windows;
it performed no USB operation, firmware build, or device access. Addresses
below are the reconstructed SRAM execution aliases.

## 0.23 stock USB-audio route

The command consumer is `usb_audio_cmd_handler` at `0x20d1c8`, called from
the USB-audio app loop at `0x20aa20`. Its command table covers IDs `0x00` to
`0x14`; the queued configuration branches and their helper calls contain the
seven direct `usb_audio_open_eq` callsites:

| Callsite | Evidence / route | Classification |
|---|---|---|
| `0x20ca66`, `0x20cb76`, `0x20cd48`, `0x20ce00`, `0x20ce6e` | Within helpers dispatched by the consumer; these are part of the same serialized command path. | CONFIRMED reachability; exact triggering USB command is not fully decoded here. |
| `0x20d3a2` | Consumer configuration branch, arguments `r0=1`, `r1=2`. | CONFIRMED call and arguments. |
| `0x20d444` | Consumer configuration branch, arguments `r0=0`, `r1=2`; selected when the state byte at `0x200196c8+1` is nonzero. | CONFIRMED call and branch source. |

`usb_audio_open_eq` is at `0x20c840`. Its relevant `r0=0`, `r1=2` route is:

```text
0x20c862: r0 == 0 -> 0x20c8b2
0x20c8e4: audio/lifecycle setup -> 0x20a994(config, 0x18, 2)
0x20a994: writes descriptor at 0x200162c4, then calls 0x20a868(config, 1)
0x20a868: if codec_initialized != 0 and enable == 1, update lifecycle state
          and clear 0x200162b4 at 0x20a884
0x20c8ec: usb_audio_set_eq(2, 0)
0x20c800: selects fixed config through 0x20015c78
0x20a938: audio_eq_set_cfg(0, config, 2)
0x20a424: hw_codec_iir_set_cfg(...), including coefficient-bank transaction
0x20c8f2 / 0x20c8fa: later calls 0x20b184(0), then 0x211db8(0, 0)
```

The source disassembly confirms that the setter call precedes the later
`0x20b184` and `0x211db8` calls. It does not, by itself, establish that those
later routines stop and resume the physical USB audio stream. Their names and
the surrounding control flow suggest stream management, but that semantic
interpretation is INFERRED. The `r0=1`, `r1=2` route skips the EQ setter and
returns through the other branch. The seven callsites prove stock code can
reach the EQ setter during configuration; they do not prove how many times it
runs in a normal session or that it is called while samples are streaming.

The command handler also has distinct stop/disable behavior: a branch at
`0x20d362` reads state bytes at `0x200196c8+3` and `+1`. If `+3` is nonzero,
control goes to `0x20d474` (sets bit 1 in `0x200196c5`; the cached expanded
window ends before its call completes). Otherwise, if `+1` is nonzero,
control goes to `0x20d45c`, sets bit 0, calls `0x212558(0)`, then calls
`0x20a9b0`. That helper marks the descriptor disabled and calls
`0x20a900(1)`, which clears codec-initialized state and peripheral enable
bits. This confirmed disable route does not clear the update byte and is not
the initialized+enable branch at `0x20a884`. The exact completion behavior
of the `+3` route is **UNVERIFIED** from the bounded cached window.

The handler also logs the capture-rate and playback-rate state through
`0x205534` at `0x20d3c4` and `0x20d3dc`; these logging branches alone do not
call the EQ setter. The seven listed open-EQ callsites remain the concrete
stock callers reaching coefficient reconfiguration. No direct setter call
was found in the bounded sample-rate logging blocks.

### Entry-path status

- **CONFIRMED:** configuration commands reach `usb_audio_open_eq` through
  the command consumer; the `r0=0,r1=2` route invokes lifecycle setup before
  selecting and applying EQ.
- **INFERRED:** the adjacent calls implement a stop/configure/reopen or
  equivalent stream transition. The exact stream-quiescence guarantee is
  not demonstrated by this static slice.
- **UNVERIFIED:** whether a normal host format/rate change exercises the
  `r0=0` branch during active playback, and whether every branch preserves
  stream continuity.
- **UNREACHABLE:** no stock host command in the documented command table
  supplies arbitrary EQ coefficients. The fixed selector always obtains the
  compiled Samsung configuration.

## Re-enable helper and busy-byte clear

`0x20a868(config, enable)` first reads the initialized word at
`0x200162b8`.

1. If it is zero, control branches to `0x20a890` and performs register setup
   through `0x202ac4`, writing codec control registers and software state.
   That branch does not execute the `0x20a884` clear.
2. If initialized is nonzero but `enable != 1`, it returns at `0x20a88c`
   without clearing the update byte.
3. If initialized is nonzero and `enable == 1`, it stores lifecycle state,
   clears byte `0x200162b4` at `0x20a884`, updates enable/initialized state,
   stores the config pointer at `0x200162c0`, and returns success.

The stock `usb_audio_open_eq(0,2)` route supplies `enable=1`, then invokes
`usb_audio_set_eq(2,0)` after the helper returns. Therefore the order
“lifecycle helper clear, then setter transaction” is **CONFIRMED** for this
route. This clear is coupled to codec lifecycle state updates; it is not a
general transaction-abort function. The stop/disable path through
`0x20a9b0 -> 0x20a900(1)` clears initialized/peripheral state but leaves
`0x200162b4` alone.

It is **CONFIRMED** that the helper can clear busy while its entry-time
`codec_initialized` value is nonzero, because that is the predicate for the
clear branch. It is **UNVERIFIED** whether all hardware-side transaction
state is quiescent when that lifecycle branch runs. Calling the helper only
to clear a stale byte is not justified.

## Bounded control-flow graph

```text
USB-audio configuration event
  -> 0x20d1c8 command consumer
  -> one of seven open-EQ callsites
  -> 0x20c840 usb_audio_open_eq
       [r0=0 route]
       -> 0x20a994 config/lifecycle descriptor
       -> 0x20a868(config, 1)
            [initialized && enable==1] -> update state; clear busy
       -> 0x20c800 usb_audio_set_eq(2,0)
       -> 0x20a938 audio_eq_set_cfg(fixed_config)
       -> 0x20a178 coefficient generation
       -> 0x20a424 hw_codec_iir_set_cfg
            -> stage coefficients in hardware bank
            -> request bank operation; wait for ACK
            -> success clears busy / toggles selector
            -> stock errors or missing ACK can leave busy set
       -> 0x20b184(0), 0x211db8(0,0) [stream semantics inferred]
```

The path from the USB-audio command to the fixed configuration and hardware
setter is **CONFIRMED**. The lifecycle clear is **CONFIRMED** for the
initialized+enable branch. Actual stream pause/resume and safety under an
in-flight hardware transaction remain **UNVERIFIED**. A host-provided EQ
configuration is **UNREACHABLE** through stock commands; a firmware extension
could introduce a validated RAM-backed configuration, but would need to
serialize it with this command path and retain the setter's ACK protocol.

## 0.04 comparison

The original 0.04 image has the corresponding EQ path and lifecycle state at
different addresses: setter state byte `0x200177cc`, fixed configuration at
`0x20017100`, and configuration list at `0x2001718c`. The preserved config
has the same two-filter shape. This supports a shared design pattern, not an
exact one-to-one proof of every 0.23 command branch. The current callsite and
argument reconstruction is strongest for 0.23; a full old-image command
dispatcher mapping was not repeated.

## Feasibility decision

One firmware patch could plausibly accept validated values into a RAM shadow,
then schedule the stock `usb_audio_open_eq(0,2)`/setter route from the
USB-audio command consumer. The fixed stock configuration pointer currently
resolves to `0x20015bec` (pointer table `0x20015c78`), so a patch would need to
provide the new RAM structure to the selector or update a protected shadow at
a serialized point. No runtime flash read is visible in the setter path.

This is a **plausible architecture, not a safe-ready implementation**. The
stock ACK waits are unbounded, known error exits can leave busy set, task
priority/preemption constraints are unresolved, and the exact stream
quiescence/resume contract has not been proven. Any implementation must fail
boundedly without forcing busy clear or changing the current active bank on
an unacknowledged update. No firmware or physical validation is authorized
by this report.

## Evidence reused

- `research/cache/custom-vendor/eq-call-graph.json`
- `research/cache/custom-vendor/codec-command-dispatch-expanded.txt`
- `research/cache/runtime-eq-official023-9ebc51140b17884a/selected-disassembly-2b62705c6a9c1341.txt`
- `research/cache/runtime-eq-official023-9ebc51140b17884a/eq-adjacent-0x20a868-0x20a938.txt`
- `research/CODEC_LIFECYCLE.md`, `research/CODEC_SCHEDULER.md`,
  `research/BUSY_FLAG_STATE_MACHINE.md`, `research/RUNTIME_EQ_CONTROL.md`

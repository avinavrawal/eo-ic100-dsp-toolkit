# RAM-shadow EQ prototype — offline contract model

This prototype validates the command/state contract only. It does not patch
or emulate the firmware and does not access USB or the device. The model and
tests are `tools/research/ram_shadow_eq_model.py` and
`tools/research/test_ram_shadow_eq_model.py`.

## Verified stock call order

The `usb_audio_open_eq` Thumb entry is `0x20c841`; normal C arguments are
`r0=0`, `r1=2` for the route that applies EQ. At `0x20c8e4` it calls
`0x20a994(config, 0x18, 2)`. That helper writes the descriptor at
`0x200162c4`, sets its lifecycle mode, and calls `0x20a868(config, 1)`.
If `codec_initialized` at `0x200162b8` is nonzero, the enable argument is 1,
and execution reaches the initialized branch, `0x20a868` updates lifecycle
state and clears the update byte at `0x200162b4` at `0x20a884`. It then
returns to `usb_audio_open_eq`, which calls `usb_audio_set_eq(2,0)` at
`0x20c8ec`. That selector reads the config pointer through `0x20015c78`,
then calls `audio_eq_set_cfg` at `0x20a938`, whose hardware setter is
`0x20a424`. Thus the busy clear precedes, and is not itself, the EQ update.

Later calls at `0x20c8f2` and `0x20c8fa` occur after the setter. Their exact
stop/resume guarantee is not proven, so this prototype does not claim audio
continuity. The independent disable path also does not prove that an EQ
setter will run on re-enable.

## Proposed protocol and state model

- **SET_EQ_TEST (E1):** `bmRequestType=0x40`, `bRequest=0xe1`,
  `wValue=0x454f`, `wIndex=0x4943`, `wLength=4`; little-endian IEEE-754 gain
  in `[-12,0]` dB. It modifies band 0 gain in the modeled stock config.
- EP0 validates and copies a complete candidate config to a private inactive
  shadow, then pushes reserved queue ID `0x13` and sets event bit 3. It never
  calls the codec lifecycle function or setter.
- The existing USB-audio consumer is the candidate worker. It requires the
  supported context, initialized/enabled codec, valid rate, and clear busy
  state. Busy is retried for a finite four worker visits; expiry reports
  `BUSY_TIMEOUT`, leaves the busy byte untouched, and does not select the
  candidate.
- With readiness satisfied, the worker models this order:
  lifecycle enable, select the candidate pointer at the stock EQ selector,
  invoke the stock setter. It changes the active software pointer only after
  an acknowledged-success result. A second shadow buffer protects the
  currently selected config while the next candidate is built.
- **GET_EQ_STATUS (E6):** read-only IN request `c0/e6/454f/4943/32`; the model
  returns 32 bytes: `EQSR`, protocol version, status code, active shadow slot
  (`ff` means stock), pending flag, requested gain, applied gain, queue depth,
  worker calls, reconfiguration calls, and failure count. Existing E2
  diagnostics are left unchanged.

The model preserves the original stock config object. Its failure tests
restore the software-selected pointer and retain the prior modeled active
config. This is not proof that a real hardware transaction which times out
has left the previous DSP bank active; hardware rollback must be proven using
the actual bounded setter path before firmware can claim that guarantee.

## Offline validation

The ten model tests cover exact request validation, finite/range checks,
EP0 staging without setter calls, queue full without mailbox leakage, event
bit-3 signaling, readiness guards, busy deferral and bounded expiry,
wrong-context rejection, worker lifecycle/setter ordering, status-read
side-effect freedom, repeated updates using the inactive shadow, and
ACK/setter failure preserving the prior modeled selection. These are contract
tests, not instruction-level or target-firmware tests.

## Firmware integration blockers

No firmware image was emitted. Before integrating the model, resolve all of
these from address-specific evidence:

1. Reserve and prove writable RAM for two independent 140-byte config
   structures (or another scheme with equivalent rollback and atomicity).
   The known 240-byte USB RX reservation is already partly consumed by
   telemetry/diagnostic state and is not assumed available.
2. Intercept queue command `0x13` before its stock unknown-command logger,
   preserve all neighboring dispatch cases, and prove the callback can push
   and notify without blocking.
3. Establish the consumer's task registration/priority and prove that running
   `usb_audio_open_eq(0,2)` there is safe relative to stream and codec work.
4. Publish the config pointer without racing any of the seven stock callsites.
5. Obtain reliable setter completion. `audio_eq_set_cfg` does not propagate
   every low-level error; stock ACK waits are unbounded and known error exits
   can retain busy. A modelled ACK result is not available as a demonstrated
   stock callback/status.
6. Prove failure keeps the old DSP bank active, and establish the actual
   audio stop/resume behavior around `usb_audio_open_eq`.

Until these blockers are resolved, the prototype is **not ready for a
firmware image or physical test**. No busy flag is forcibly changed and no
stock coefficient scratch at `0x20015fa4` is used.

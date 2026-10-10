# EO-IC100 EQ configuration and coefficient RAM lifecycle

Offline static reconstruction from the existing official 0.23 and original
0.04 images and cached indexes. No physical device, USB, or firmware build
was used.

## Configuration source

### Official 0.23

- **CONFIRMED:** `usb_audio_set_eq` at `0x20c800` accepts EQ type 2 and index
  0. Index 0 loads the pointer table at `0x20015c78` and tail-branches to
  `audio_eq_set_cfg(0, config, 2)` at `0x20a938`. Nonzero indexes return
  failure.
- **CONFIRMED:** the table points to the fixed configuration at
  `0x20015bec`, corresponding to official image file offset `0x1e4c4`.
  It is decoded as `<ffI>` (left gain, right gain, band count), followed by
  `<Ifff>` filter records, with a maximum of eight bands. The stock record
  has 0 dB left/right gain and two type-1 filters: -2 dB at 220 Hz, Q about
  0.6; and -2 dB at 9000 Hz, Q 8.
- **CONFIRMED:** `audio_eq_set_cfg` invokes `hw_codec_iir_get_cfg` to derive
  hardware coefficients and stores the generated coefficient scratch at
  `0x20015fa4`; it then calls the hardware setter at `0x20a424`.
- **CONFIRMED:** when the hardware setter reaches its programming path, it
  writes coefficient data into the codec coefficient-bank register region
  `0x40302000..0x40302340`, requests the hardware bank/swap operation through
  `0x403000e0`, and only updates software selector state after the ACK path.
  The setter therefore programs coefficient registers on invocation; it is
  not restricted in code to cold boot.
- **INFERRED:** the fixed EQ structure resides in initialized SRAM populated
  as part of firmware startup. The setter's path shows no runtime flash read.
  The exact startup copy instruction for this object was not isolated in this
  focused pass.

### Original 0.04

- **CONFIRMED:** the corresponding old-image fixed configuration is at
  `0x20017100` with list `0x2001718c`, file offset `0x25c00` in the preserved
  flash image; it has the same two-filter layout and values.
- **CONFIRMED:** the old setter uses busy state at `0x200177cc`; RAM addresses
  differ from 0.23.
- **INFERRED:** both releases use the same broad fixed-preset-to-coefficient
  generation pattern. Exact old-image runtime call frequency and every
  re-enable branch were not re-audited here.

## Lifecycle and mutation points

1. Firmware startup provides the static config in the initialized RAM image.
   **CONFIRMED** as mapped initialized data; the exact copy routine for this
   individual object is **UNVERIFIED** in this pass.
2. Stock selector `usb_audio_set_eq(2,0)` reads the pointer from
   `0x20015c78`. **CONFIRMED.**
3. `audio_eq_set_cfg` consumes that pointer, derives coefficients, and uses
   scratch RAM at `0x20015fa4`. **CONFIRMED.**
4. `hw_codec_iir_set_cfg` stages coefficient words in codec hardware bank
   RAM and performs the ACK-controlled bank operation. **CONFIRMED.**
5. A later stock reconfiguration that reaches the same selector reuses the
   current pointer/config values unless some earlier writer changed them.
   No runtime flash reload is in this setter route. Reuse is **INFERRED** from
   the pointer load and call graph; exhaustive writes to the config object
   were not established by this pass.

The `0x20a868` lifecycle helper is called from `0x20a994`, which is reached by
`usb_audio_open_eq(0,2)`. For an already-initialized codec and enable argument
1, it clears the transaction byte at `0x200162b4` and stores the config
pointer before the selector/setter call. That branch order is **CONFIRMED**.
The separate disable route through `0x20a9b0 -> 0x20a900(1)` clears codec
initialized/peripheral state but not the transaction byte. Thus “disable then
enable always reloads the EQ” is **UNVERIFIED**; the demonstrated route that
both enables and reapplies EQ is the complete `usb_audio_open_eq(0,2)` path.

## Could validated host parameters replace RAM config?

**INFERRED — technically feasible in a firmware extension:** the config is
addressed through a writable RAM pointer and the coefficient generator takes
that config pointer as an argument. A custom USB handler could validate a
bounded parameter set into a separate RAM shadow; a serialized worker could
then pass that shadow into the existing conversion/setter chain or safely
switch the selector's pointer. This avoids a flash write and retains the
stock coefficient-generation and bank-ACK protocol.

However, merely overwriting `0x20015bec` while audio/configuration code may be
reading it risks a torn structure. Mutating the shared pointer table can
race callers. A safe patch would need a single-owner command context, atomic
publication (for example, build a complete inactive config buffer, then
publish its pointer under the same serialization used by stock codec
configuration), and rollback semantics that keep the previous config active
if coefficient generation or hardware ACK fails. Those synchronization and
rollback guarantees are not yet proven.

## Status summary

| Question | Finding |
|---|---|
| Does stock EQ configuration come from flash on each update? | **UNVERIFIED / no evidence found:** setter reads a RAM pointer; no runtime flash read occurs in the traced call path. |
| Are coefficient scratch and hardware banks rewritten on invocation? | **CONFIRMED:** generator writes scratch and setter stages hardware coefficient-bank data when its path succeeds. |
| Does stock reconfiguration reload config from flash? | **UNVERIFIED:** no flash read in the traced route; object-wide writer audit was not part of this pass. |
| Can a patched host command stage a new config in RAM? | **INFERRED feasible**, if validated and published only in serialized context. |
| Can stock codec lifecycle apply it without a flash rewrite? | **INFERRED plausible** through `usb_audio_open_eq(0,2)` and the existing setter; active-stream stop/resume semantics and task timing remain unverified. |
| Is this safe to implement/deploy now? | **NO:** stock ACK waits are unbounded, error exits can leave busy set, and no complete pause/resume and rollback contract is established. |

## Evidence reused

- `research/cache/custom-vendor/eq-call-graph.json`
- `research/cache/runtime-eq-official023-9ebc51140b17884a/mapping.json`
- `research/cache/runtime-eq-official023-9ebc51140b17884a/selected-disassembly-2b62705c6a9c1341.txt`
- `research/cache/runtime-eq-original004-6ee1089955817ac0/mapping.json`
- `research/RUNTIME_EQ_CONTROL.md`, `research/CODEC_LIFECYCLE.md`,
  `research/BUSY_FLAG_STATE_MACHINE.md`

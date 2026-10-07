# EO-IC100 physical buttons → USB HID

## Outcome and scope

**INFERRED: a technically sound firmware patch strategy exists for all eight requested mappings.** Both examined key drivers already distinguish settled single/double/triple clicks and long holds. The application mapper drops these events. The HID transport carries a 16-bit bitmap, with enough currently constant bits for three additional Consumer Control usages. No new physical detector or USB vendor request is needed.

This establishes the requested strategy stopping criterion, **not a deployable or device-tested patch**. The authored queue core compiles for Thumb Cortex-M4 and passes offline tests, but its transport adapter, final linker placement, image packaging, and device validation remain to be implemented. No image was patched, USB operation performed, or original modified. Physical wiring, actual timing, and host handling of Voice Command remain unverified.

Inputs are hash checked by `tools/research/hid_buttons.py`: original 0.04 from the complete backup; official 0.23 slot A; official 0.23 slot B. Source SHA-256 values and startup copy mappings are in `runtime_eq_map.py` and the ignored `research/cache/hid-buttons/audit.json`. Do not use the slot-A image as a slot-B image: numerous XIP pointers differ. The two proposed descriptor/mapper patch sites alone are byte-identical in the official A/B files.

## Code path

Addresses below are code execution addresses (`0x002…` SRAM alias or `0x0c…` XIP alias); data is accessed through `0x200…`. Do not confuse code addresses with file offsets.

| Function / data | Original 0.04 | Official 0.23 | Confidence |
| --- | --- | --- | --- |
| Key open / callback registration implementation | `0x0c00650c` | `0x0c0065dc` | CONFIRMED static |
| Registered sample/event callback | `0x00204748` | `0x0020429c` | CONFIRMED static |
| Key debounce/state timer | `0x002047f4` | `0x0020434c` | CONFIRMED static |
| Application `key_event_process` | `0x0020bb84` | `0x0020a9cc` | CONFIRMED static |
| Application button → HID mapper | `0x0020e338` | `0x0020d174` | CONFIRMED static |
| HID mask setter | `0x00210218` | `0x0020ef58` | CONFIRMED static |
| HID send worker | `0x0020ed0c` | `0x0020db20` | CONFIRMED static |
| Registered application HID completion callback | `0x0020bd7c` | `0x0020c7dc` | CONFIRMED static |
| Report descriptor data | `0x20016098` | `0x2001506c` | CONFIRMED static |

Flow: analog/button status sample → threshold lookup and sampled key mask → debounce/state timer → registered application callback `(key_mask, event)` → mapper → desired HID bitmap → send worker → interrupt IN endpoint `0x84` → transfer completion.

**CONFIRMED:** application initialization registers the callback at original `0x0020bcb8` / official `0x0020aafc`; key-open stores it at `0x2001af3c` / `0x200199f0`. Key-open initializes the sampled state, creates the debounce timer, and registers the sample callback. Official sample registration goes through `0x0c00d508` → `0x00203fd4`.

**CONFIRMED:** original sample callback uses its second argument as a numeric sample, checks status bits in its first argument, and scans nine upper thresholds initialized as 220, 310, 400, 490, 580, 670, 760, 850, 1000. Its corresponding key-code table at `0x200170ec` is `0x200, 0x100, 0x80, 0x40, 0x20, 0x10, 8, 4, 2`. The sample path and timer therefore support more key codes than the three exposed by this product mapper.

**INFERRED:** this is the GPADC/resistor-ladder physical detector. Code 2 denotes center, 4 volume+, 8 volume− because the application maps them to Play/Pause, Volume Increment, Volume Decrement. The exact resistor voltages, peripheral wiring and analog units have not been measured; do not label these threshold numbers millivolts. Preserve this entire layer in the patch.

## Event/state logic

| Event | Meaning from control flow | Confidence |
| --- | --- | --- |
| 1 | Newly detected individual key down | CONFIRMED static |
| 2 | Initial down in idle gesture state | CONFIRMED static |
| 3 | Subsequent down while gesture state exists | CONFIRMED static |
| 4 | Individual key up | CONFIRMED static |
| 5 | First long-hold threshold crossed | CONFIRMED static |
| 6 | Further, very-long-hold threshold crossed | CONFIRMED static |
| 7 | Settled single click | CONFIRMED static |
| 8 | Settled double click | CONFIRMED static |
| 9 | Settled triple click | CONFIRMED static |
| Other values | Additional count/repeat paths exist; meanings not fully classified | UNVERIFIED |

The original state struct at `0x2001af40` tracks held mask at +0, gesture key mask at +2, pending click key at +4, state at +6, held timestamp at +8, click timestamp at +12, repeat counter at +16, extra-click counter at +17. Official uses `0x200199f4` with the same relevant state structure.

**CONFIRMED:** release starts a pending click sequence. Matching subsequent releases increment the extra-click counter. The driver emits `7 + counter` when the click window expires or the key sequence changes, then clears pending click state. Native long state 5/6 follows a separate release branch, so normal long release does not also generate a settled single click. The long path emits event 5 once before advancing to state 5; later repeat/very-long events must be ignored by this mapping.

Original evidence anchors: release callback `0x00204854`; down `0x002048a4`; further down `0x002049fe`; long `0x00204a5e`; very long `0x002049e2`; count+7 dispatch `0x00204a20` / `0x00204af6`. Official equivalents include `0x002043ac`, `0x002043fc`, `0x00204554`, `0x002045bc`, `0x0020453c`, `0x00204576` / `0x00204670`.

**CONFIRMED:** comparisons use 640 ticks for timer/debounce scheduling, 1280 ticks in one sample qualification path, 6400 ticks for pending clicks, >23999 ticks for first long hold, >79999 ticks for very long. Original timer reader `0x0020174c` reads and negates the peripheral counter at `0x40004004`. **UNVERIFIED:** exact milliseconds and actual gesture UX; converting with an assumed 16 kHz clock is not a measurement.

**CONFIRMED:** the stock mapper accepts `(1 << event) & 0x12`, meaning only events 1 and 4. It sets or clears HID masks 4/1/2 for keys 2/4/8. Thus stock click discrimination is discarded after detection, and raw presses can reach the host before a later double/triple decision. Replacing the mapper must suppress raw 1/4 events; merely adding an event-8 branch would emit unwanted Play/Pause first.

## Descriptor and transport

**CONFIRMED:** the original and official firmware descriptors are identical. Existing capture confirms original normal mode: interface 3, HID 1.11, report ID 1, 47 descriptor bytes, interrupt IN `0x84`, maximum packet 3 bytes, interval 4 ms. Input bits 0/1/2 mean Volume Increment/Decrement/Play-Pause; 13 remaining bits are Constant padding; no Output or Feature main items. Official live enumeration was not repeated.

**CONFIRMED:** send worker formats `[1, mask_low, mask_high]`, submits length 3 to endpoint index 4, and tracks desired and last-submitted masks. Official desired mask is `0x2001ad2c`, last-submitted `0x2001ad28`, report buffer `0x2001ad30`; original counterparts are `0x2001c270`, `0x2001c26c`, `0x2001c274`.

Official transport completion handler `0x0020dc70` obtains the sent mask, invokes the registered callback with `(sent_mask, error)` at `0x0020dc80`, then reconciles desired state. The callback is stored in configuration field +`0x28` (`0x20014aa8`). **Important:** application completion runs before the rest of the transport completion handler. Queue advancement should record completion there and defer submission until the transport finishes; blindly sending a new report inside that callback is unsafe.

Original application completion logs only. Official `0x0020c7dc` conditionally clears Play/Pause and calls `0x0020c788` when state byte `0x20019776` equals 1 and error is zero. **UNVERIFIED:** the full purpose of that auxiliary mode. Preserve its lifecycle and isolate it from custom button queue completion; do not blindly replace or chain this callback without auditing that interaction.

## Reproducible patch strategy

1. **Target official slot B only.** Verify its known SHA-256; independently verify all hook bytes and mapped sections. Preserve original A, backup, flags and existing EQ configuration. No writer is included in the research tools.
2. Replace the descriptor at file offset `0x1d944` with the authored 47-byte `EXPANDED` descriptor in `hid_buttons.py`. It exposes bits 0–5 as `E9 EA CD B5 B6 CF` and leaves ten Constant bits, preserving report ID, packet size, interface and descriptor length. No USB configuration length change is required.
3. Redirect mapper entry at file offset `0x15a4c` / runtime `0x0020d174` to a Thumb shim with the same `(key,event)` ABI. Original mapper occupies 84 bytes through `0x0020d1c8`; do not overwrite the next function. Return handled for known product keys, pass unknown keys back to the existing wrapper. Keep diagnostic key `0x200` behavior separate. Existing callback registration can remain intact.
4. Use event 7 for singles; center event 8/9 for double/triple; event 5 for long. Ignore raw down/up and repeat/very-long events. Desired masks are below. Single-click delivery waits for the native click window. If immediate volume singles are required, a different gesture policy is needed; an immediate single cannot later be withdrawn after a long hold.
5. Use the authored `hid_button_queue.c` core as a bounded action queue. Reserve stable writable storage and a three-byte report buffer. It needs 16 bytes of state; at most 32 bytes are budgeted. A possible scratch reservation is the retired mapper body after an aligned entry trampoline, through the existing initialized-RAM mapping. This requires proving there are no other entries/data references into that body before use. It is not approved merely because those bytes exist.
6. Emit one nonzero report per queued action, wait for successful completion of that exact mask, then emit zero and wait for its completion before dequeuing another action. Drop a whole new action on overflow; never drop a release. A rejected/busy submission is retried without advancing. An ambiguous transfer error faults the queue; the adapter must arrange a neutral report when transport is viable and reconcile disconnect/reset before accepting new actions. Serialize key/timer/completion access and defer endpoint work to an appropriate firmware context.
7. Integrate with the established HID setter/send/completion path, preserving suspend/resume, USB lifecycle, existing timer and auxiliary-mode behavior. Do not introduce host-to-device requests. Do not let other HID producers or the auxiliary Play/Pause path race with the queued bitmap. A completion adapter must distinguish its own submissions from unrelated HID traffic.
8. Link the shim into explicitly reserved executable storage; resolve all symbols/Thumb bits for **B**, not A. XIP veneers prove flash execution is already used. Appending XIP code beyond the original image is an allocation option, **not yet a verified patch placement**: establish the B region limit, absence of tail data/references, image length/integrity rules and staging extent first. Zero runs in the current file are tiny and include live EQ/initialized data; they are not safe code caves. No image growth or flash-tail assumption is needed to understand the mapping algorithm, but a finished image requires resolving placement.
9. Before any deployment proposal, generate a patch manifest with input/output hashes, exact old/new spans, linked symbols, reserved memory ranges, no unresolved relocations, validated image length/integrity and diff limited to the agreed B changes. Validate descriptor parsing, instruction decoding, hook ABI, queue tests and non-overlap. Physical staging/activation would be separate, explicitly approved work with complete read-back verification. It is outside this goal's authorization.

| Gesture | Native event | HID mask | Consumer usage |
| --- | --- | --- | --- |
| Center single | 7 | `0x04` | Play/Pause `0xCD` |
| Center double | 8 | `0x08` | Scan Next Track `0xB5` |
| Center triple | 9 | `0x10` | Scan Previous Track `0xB6` |
| Center long | 5 | `0x20` | Voice Command `0xCF` |
| Volume+ single | 7 | `0x01` | Volume Increment `0xE9` |
| Volume+ long | 5 | `0x08` | Scan Next Track `0xB5` |
| Volume− single | 7 | `0x02` | Volume Decrement `0xEA` |
| Volume− long | 5 | `0x10` | Scan Previous Track `0xB6` |

These usage definitions are standardized in [USB HID Usage Tables](https://www.usb.org/sites/default/files/hut1_3_0.pdf). Voice Command requests listening; **UNVERIFIED:** whether a particular host invokes its voice assistant for this usage. Firmware can emit it, but that host outcome is not guaranteed.

## Reproduction and verification

```sh
python3 tools/research/runtime_eq_map.py
python3 tools/research/hid_buttons.py
python3 -m unittest discover -s tools/research -p 'test_hid_buttons.py'
clang --target=arm-none-eabi -mcpu=cortex-m4 -mthumb -ffreestanding \
  -fno-builtin -Os -Wall -Wextra -Werror -c tools/research/hid_button_queue.c \
  -o research/cache/hid-buttons/hid_button_queue.o
```

Eleven tests passed: descriptor bit layout/size; all requested mappings; ignored raw/repeat events; no single action from double or long traces; repeated same-usage press/zero edges; queue overflow; submission retry; ACK mismatch; transfer fault/reset; truncated descriptor; 3000 seeded operations comparing compiled C against the Python reference under backpressure. These validate the authored core, not execution of the actual firmware detector or USB glue. Thumb compilation passed; no final firmware executable was linked.

Targeted disassembly is reproducible using `analyze.py r2` with `--base 0x00200000`, `e scr.color=0`, and the RAM images under `research/cache/runtime-eq-{profile}-{hashprefix}/initialized-ram.bin`. Key evidence commands: original `pD 180 @ 0x00204748;pD 1180 @ 0x002047f4`, official `pD 1036 @ 0x0020434c;pD 152 @ 0x0020d174;pD 240 @ 0x0020ef58`; completion `pD 228 @ 0x0020dc70`. Flash key-open: original backup `--base 0x0c000000`, `pD 160 @ 0x0c00650c`; official stock A `--base 0x0c006000`, `pD 160 @ 0x0c0065dc`.

Large disassemblies, raw Thumb indexes, reconstructed binaries and compiled outputs remain under ignored `research/cache/`. The compact audit checks source hashes, descriptor parsing, file/runtime patch offsets and A/B patch-site equality. Event semantics are reviewed control-flow findings, not assertions derived merely from string names or unvalidated linear xrefs.

An alternative is host-side gesture remapping of captured stock HID press/release timing. It can support similar host actions without flashing, but is host-specific, must suppress original actions, and has not been built here. It does not change the firmware pipeline. No evidence suggests these mappings are intrinsically impractical in the examined firmware.

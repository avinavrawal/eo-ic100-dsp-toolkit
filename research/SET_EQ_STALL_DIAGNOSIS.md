# SET_EQ_TEST STALL diagnosis (offline/read-only)

## Conclusion

The host's `LIBUSB_ERROR_PIPE` proves that the control transfer stalled, but does not identify which control-transfer stage stalled. The saved capture contains no device-side trace or return code. The statically valid `40 e1 4f 45 43 49 04 00` setup and `00 00 c0 c0` data match the EQ-test handler's exact format, and new CPU tests show that the stock setup/data callbacks can accept this four-byte OUT request and reach EP0 frame state 6 without rejection.

Therefore the evidence does **not** prove one unique physical root cause. Assuming the EQ-test image was actually running, the strongest candidate is the handler's intentional live-state guard: it requires EQ enabled, initialized codec state, and no update already busy. The preceding physical check established that audio endpoints were enumerated, but did not start an audio stream or prove these runtime flags. A second candidate is either bounded codec ACK wait timing out; that also intentionally returns a rejection. A third possibility is that the active B still contains the CAPS-only image: CAPS-only's setup hook deliberately rejects E1. The recorded physical GET response and firmware version do not distinguish the two images because both report the same CAPS bytes and firmware version. No flash read was authorized or performed to identify the running image.

## E0 and E1 path comparison

1. EP0 handler `0x00206130` parses the eight setup bytes into frame `0x2001ac74`, then calls setup callback slot `0x2001aba8`. The EQ-test hook is `eoic_setup` at `0x0c04d000`; it preserves the original `uaud_setup` at `0x0020dd10` for valid requests.
2. Both E0 and E1 match the custom family: `(bmRequestType & 0x60) == 0x40` and request `0xe0` or `0xe1`. Shared tags are `wValue=0x454f`, `wIndex=0x4943`.
3. E0 is accepted only as `C0 E0 ... 0c 00`: device/vendor IN, 12 bytes. E1 is accepted only in the EQ-test build as `40 E1 ... 04 00`: device/vendor OUT, four bytes. `format()` rejects other direction/type, tag, or length. In the generated `format` routine at `0x0c04d034`, E0's branch checks `bm=0xc0`/length 12; E1's branch checks `bm=0x40`/length 4. No endianness discrepancy exists for the stated libusb values.
4. For valid E0, `eoic_vendor` at `0x0c04d21c` sees a null setup payload and zero length, supplies the 12-byte immutable CAPS structure, and returns 0. The stock EP0 path sends it through the IN/DMA response path. The saved physical CAPS reply matches exactly.
5. For valid E1, setup delegates to `uaud_setup`, which arms the configured OUT receive buffer (normal registration records `0x20019804`, capacity 240) and frame state 3. The four host bytes are received there. `uaud_datarecv` at `0x0020e5fc` constructs its 12-byte callback argument on stack: setup pointer at +0, received payload pointer at +4, received length at +8; it calls the registered vendor callback at `0x2001b15c`.
6. The EQ-test vendor handler requires non-null payload and exact length 4, decodes a little-endian float, validates finite `[-12,0]`, then checks runtime EQ enabled (`0x200162cd`), codec initialized (`0x200162b8`), update-busy clear (`0x200162b4`), sample rate/configuration, and stock band count 2. `-6.0` itself is a valid finite value.
7. Handler return 0 means **accept**. `uaud_datarecv` tests this at `0x0020e634`; on zero it returns 1 and writes frame state 6 at `0x0020e63e`. The EP0 handler treats the nonzero callback result as accepted, then follows its state-6 completion path at `0x0020639c`–`0x002063e2`. This is the stock zero-length status-stage completion convention.
8. Handler return nonzero means **reject**. `uaud_datarecv` returns 0 without changing state 3; the EP0 handler takes its nonstandard-request rejection/re-arm path at `0x002064aa`. On hardware this can be reported by libusb as PIPE/STALL. It intentionally makes malformed input, runtime-state refusal, setter error, and codec timeout indistinguishable to the host.

Stock OUT vendor commands use the same receive buffer, `uaud_datarecv`, and return convention. The registered original callback handles `bRequest=0x06` and its command bytes (for example `CHECK`); return 0 likewise produces frame state 6. The new handler delegates non-E0/E1 requests to that original callback. E0/E1 do not collide with the stock command byte `0x06` or stock ASCII command payloads.

## Assessment of the ten proposed causes

| Cause | Offline/read-only finding |
|---|---|
| EP0 dispatch rejects E1 | The EQ-test build's setup matcher accepts the exact E1 tuple. The CAPS-only build intentionally rejects E1 at setup. Physical image identity remains unproven because the CAPS response is identical in both builds. |
| Wrong request type/direction/recipient | No: `0x40` is device/vendor/OUT as required; E0 uses `0xc0` device/vendor/IN. Exact tags are LE-correct. |
| Wrong `wLength` | No: the E1 handler requires exactly 4 and the host sent 4. |
| OUT data not consumed | Static path and CPU test show setup state 3, registered receive buffer, data callback, and four-byte payload. Physical stage timing is not captured. |
| Wrong handler success status | No static mismatch: E1 success returns 0; stock data callback maps 0 to return 1/state 6. New positive test verifies it. Nonzero intentionally rejects. |
| Setup matches but payload does not | The payload bytes are valid `-6.0f`; emulator accepts them when live-state guards are active. If those guards fail, the exact payload path returns rejection before the setter. |
| Status-stage logic | Static success path proceeds from state 6 into EP0 completion. The offline harness models state 6, not electrical ACK timing, so a physical status-stage fault is not absolutely excluded. |
| Collision with stock request | No known collision. Stock command requests use `bRequest=0x06`; all unrelated callbacks are delegated. |
| Deliberate firmware stall | Yes, for setup-format rejection, disabled EQ-test build, inactive/uninitialized/busy runtime state, invalid internal config, or setter/ACK error. All collapse to the same EP0 rejection. |
| Bad stack/register state | No evidence: generated Thumb disassembly follows AAPCS (`r0` callback pointer; runtime setter receives `r0=0,r1=cfg,r2=2`), and the emulator reaches the setter with the expected arguments. Four-byte local payload/config alignment and stack bounds are valid. |

## Offline test

`test_four_byte_vendor_out_reaches_ep0_status_accept_path` executes the exact valid E1 setup hook, verifies state 3/length 4/registered buffer pointer, supplies `00 00 c0 c0`, then runs the original `uaud_datarecv` and EQ-test handler. With initialized/live modeled codec state it reaches `audio_eq_set_cfg`, returns accepted, and sets state 6. `test_four_byte_vendor_out_idle_state_takes_rejection_path` proves the same accepted setup and payload are rejected before the setter if live state is absent. `test_stock_vendor_out_uses_same_success_status_convention` exercises OUT `CHECK` through the original command callback and reaches state 6.

All 24 custom-vendor tests and all 40 offline research tests pass. This is instruction/data-flow emulation; it cannot reveal which runtime guard or setter branch the physical device took.

## Required change and next-test proposal

No change to the USB direction, `wLength`, payload encoding, receive callback ABI, or DSP setter is justified by this evidence. The firmware's error reporting **does** need a diagnostic improvement before another E1 test: identify the EQ-test image in a read-only response (the current CAPS flags are zero in both variants), and expose a read-only last-rejection code covering image/build, EQ-enabled, codec-ready, busy, config validation, and setter/ACK timeout. Preserve the current refusal/stall behavior; do not turn an error into success or issue an EQ call when a guard is false. Build and test that diagnostic offline first. This requires a new offline image and, before another physical request, separate review/approval of staging/activation as needed.

If later authorized, the exact next physical sequence should be: first establish that the diagnostic identifies the EQ-test image; start a real audio stream; read the diagnostic state and require EQ-enabled/codec-ready/not-busy; only then send one E1 `-6 dB` and, on successful status ACK with continuing audio, immediately restore 0 dB. Any stall stops the sequence. This report performs no such physical operation and does not authorize one.

The runtime update does not write flash or the compiled boot EQ table. A physical power cycle should reload the static boot EQ when the selected image boots normally, but that restoration has not been verified on this EQ-test image. If the setter timed out, offline tests show the old bank remains selected; if it completed and only a later status stage stalled, live EQ may have changed until reboot. The present live EQ state is therefore **unknown**.

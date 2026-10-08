# Runtime EQ test readiness — offline only

**Status: first physical E1 attempt stalled; do not retry yet.** One request was sent after read-only checks and the host reported `LIBUSB_ERROR_PIPE`; see [SET_EQ_STALL_DIAGNOSIS.md](SET_EQ_STALL_DIAGNOSIS.md). The active image was not identified and no restore request followed.

The CAPS-only source image remains byte-identical to the physically staged and boot-validated CAPS image, SHA-256 `afa5bb0570950030c7e36c3219fd93e0efc65c90f5355e02d4a3a091cb6bf356`; its physically validated GET response remains unchanged.

The image is `research/cache/custom-vendor/eq-test.bin`, SHA-256 `5be2b81385fce7fa86876393b680e5d3b3bbbededf13aa893ab42cccf5c9b26b`. Its input is `firmware/private/stock_b.bin`, SHA-256 `2f418d3a324ec4217c32c4bf98d43c3cd07d59d81f82974f29320d399fa769f3`. Two consecutive patcher builds and the deterministic-output unit test produced the same image hash. The image is ignored under `research/cache/`, not a tracked firmware asset.

The exact changed file ranges use exclusive ends:

```text
[0x12f86, 0x12f87)  repoint bank-state literal load to duplicate value
[0x13042, 0x1304a)  first ACK wait trampoline
[0x1304e, 0x13054)  shared timeout check/cleanup and local helper literal
[0x1311c, 0x13128)  second ACK wait trampoline and helper literal
[0x13239, 0x1323a)  preserve setter result through audio_eq_set_cfg
[0x1d384, 0x1d388)  vendor callback pointer
[0x1d990, 0x1d994)  setup callback pointer
[0x1edc4, 0x20004)  appended payload, padding and relocated host-only footer
```

The complete injected Thumb text disassembly, including `eoic_setup`, `eoic_vendor`, validator and both bounded wait helpers, is `research/cache/custom-vendor/eq-test-handler-disassembly.txt`. Machine-readable branch, instruction and literal-pool validation is in `eq-test-decoded.json`; build and timeout details are in `eq-test-report.json`.

The unbounded stock waits at code addresses `0x0020a76a` and `0x0020a844` now call helpers that perform at most **65,535 reads** of codec register `0x403000e0` each. The first waits for acknowledgement bit 24 to become 1; the second waits for it to become 0. The bound is an iteration count, not a measured wall-clock timeout. No retry occurs after exhaustion. Timeout restores control bit 22 to the last observed bit 24, clears update-busy byte `0x200162b4`, does not toggle software bank selector `0x200162bc`, and reaches the stock setter's status-3 error exit. The high-level wrapper preserves that status for the custom request handler. Offline tests forced both acknowledgement states to remain stuck and verified bounded return, unchanged selector, cleared busy state and byte-identical previously active coefficient bank. The candidate coefficients may have been written to the inactive bank before timeout; they are not selected as active.

`GET_EOIC_CAPS` remains byte-for-byte compatible with the validated CAPS-only image: one 12-byte response, `45 4f 49 43 01 00 08 00 00 00 00 00`. The exact test mutation request is device/vendor OUT, `bmRequestType=0x40`, `bRequest=0xe1`, `wValue=0x454f`, `wIndex=0x4943`, `wLength=4`; setup bytes are `40 e1 4f 45 43 49 04 00`. The data stage is one little-endian IEEE-754 float32. NaN, infinities, wrong lengths and values outside inclusive `[-12.0, 0.0]` dB are rejected. There is no read/write-memory operation or caller-controlled filter structure.

For the proposed `-6.0 dB` test, send payload `00 00 c0 c0`. It changes the common left/right global gain while retaining both stock EQ bands and their bytes. The generated first-section feedforward coefficient factor is expected to be `10^(-6/20) ≈ 0.501187`; modeled audio behavior is not physical DSP evidence.

On success, the OUT control transfer completes with a zero-length status ACK; the CPU harness reports the receive frame at state 6. There is no response data payload. On a firmware-side timeout, the vendor callback rejects the command; the offline endpoint-zero model returns result 0 and leaves receive state 3, corresponding to the existing EP0 rejection/re-arm path. The host-visible distinction between STALL and timeout has not been measured on hardware and must be treated as unverified.

To restore the pre-test gain after a successful test, send the same request with the previously recorded float. On a fresh boot using the stock compiled table, the global gain is 0 dB, so the restore payload is `00 00 00 00`. There is no GET-current-gain command; preserve the known pre-test value rather than assuming it if runtime state was changed earlier. The change is RAM/DSP runtime state only and is not persistent.

If audio remains healthy and the request succeeds, restore the baseline gain immediately and verify ordinary playback, input, HID and `QUERY_SW_VER`/`CHECK` using already classified read-only checks. If the request rejects or times out, do not retry automatically; the prior active coefficient bank is preserved by the tested rollback path. If normal-mode B becomes unusable, use the separately reviewed recovery-to-A procedure only after confirming A remains valid/readable; it changes boot selection only and does not rewrite either image. Any future staging/activation of this EQ-test image needs its own review and explicit authorization.

Offline verification completed:

- 24 custom-vendor emulator/unit tests passed, including deterministic image comparison, exact changed ranges, original boot EQ preservation, exact CAPS bytes in both variants, malformed SET payload rejection, normal gain change/restore, both forced ACK timeout paths, and E1 OUT setup/data completion conventions.
- 40 total offline research tests passed across custom-vendor firmware, runtime-EQ audit and HID analysis.
- The emitted EQ-test image SHA-256 matched the patcher report and an independent `shasum -a 256` result.
- The boot EQ table, USB audio/HID descriptor bytes, prior CAPS path and legacy vendor-command classifier remain unchanged under the offline checks.

The physical E1 transfer returned PIPE. The exact failing EP0 stage, whether the EQ handler or DSP setter ran, current live gain, physical ACK duration, audio continuity after the attempt, and acoustic/DSP response remain unverified. No retry was made.

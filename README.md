# EO-IC100 DSP Toolkit v0.1.0

An experimental research and tuning toolkit for Samsung/AKG EO-IC100 USB-C earphones. It includes an eight-band macOS DSP tuner, a hash-locked slot-B EQ patcher, USB transport/recovery tools for macOS and Termux, offline diagnostics, and research notes.

## Project status

The tuner builds EQ firmware images for persistent installation in slot B. Live runtime EQ changes while audio is playing are not supported: the custom command path receives and validates a gain, but the stock codec update path rejects it in the observed runtime state. The diagnostic firmware and device-specific captures are excluded from Git. Rebuilding the application and running its offline tests do not require earphones or firmware assets. Device microphone and audio performance must be verified on the individual device; offline checks cannot establish them.

**Use at your own risk.** Firmware installation can make a device unbootable. Preserve the complete device backup and original slot-A image. Never write the active slot or erase recovery A. Read [the recovery guide](docs/recovery.md) and the in-app phase description before any physical operation. Build and test commands below do not access USB.

## macOS tuner

Requirements: macOS 13 or later, Swift 5.10/Xcode Command Line Tools, Python 3, Clang, `pkg-config`, and libusb 1.0. On Homebrew systems, install the native dependencies with `brew install pkg-config libusb`.

Build and launch the app from the repository root:

```sh
python3 tools/caps/build_tuner_app.py
open "research/cache/macos-app/EOIC100 DSP Tuner.app"
```

The build creates ignored native helpers and an unsigned local `.app` under `research/cache/`. It performs no USB operation and does not require firmware assets.

The app edits and previews an eight-band parametric EQ, loads/saves JSON presets, and builds a slot-B image from the verified official Samsung 0.23 B image. Before image generation or installation, place the four locally obtained assets in `firmware/private/`:

```text
stock_a.bin                 verified original recovery image
stock_b.bin                 official Samsung 0.23 slot-B image
programmer3001sp.bin        Samsung RAM programmer
flash-backup.bin            complete original 512 KiB device backup
SHA256SUMS.txt              recorded SHA-256 values for those assets
```

Create the local checksum file after obtaining and reviewing the assets:

```sh
cd firmware/private
shasum -a 256 stock_a.bin stock_b.bin programmer3001sp.bin flash-backup.bin > SHA256SUMS.txt
```

These assets are proprietary/device-specific and are intentionally excluded from Git. The app checks recorded and actual hashes against this release's verified asset set; a different backup or firmware variant is rejected. Select **Install EQ** to start the resumable A/B workflow. It detects the running slot, verifies recovery A from flash before any boot-flag change, asks separately before switching to A, staging B, and activating B, and requires physical unplug/reconnect steps between firmware boots. Stage writes inactive B only and requires complete byte-for-byte readback before activation. Success appears only after normal B, `CHECK=1.1`, USB Audio, and HID verification. Recovery to A is a separate confirmed action. A requested physical reconnect is never performed by a software reboot.

The install helper also requires a locally generated CAPS-only transition image. With the private official B image and documented analysis tools available, create it offline first:

```sh
python3 tools/research/custom_vendor_analysis.py
python3 tools/research/custom_vendor_patch.py
```

These commands create ignored outputs under `research/cache/custom-vendor/` and do not access USB. See [custom vendor analysis notes](research/CUSTOM_VENDOR_EQ.md) for tool dependencies and image limitations.

The patcher can also be run without the GUI once the private stock B image is present:

```sh
python3 tools/caps/tuner_firmware.py \
  firmware/private/stock_b.bin \
  patcher/presets/diamond8.json \
  research/cache/tuner/eq-b.bin
```

## Termux tooling

The Android/Termux helper is original source under `tools/termux/`. It requires Termux, Termux:API, Clang, libusb and coreutils. Review the scripts and [recovery guide](docs/recovery.md) before use. Build from the Termux shell:

```sh
cd tools/termux
bash build_termux.sh
```

Stage, activation, and recovery/slot selection are separate operations. The wrappers require explicit confirmations and enforce the known device identity and slot checks; they still perform real USB operations when invoked. No physical operation is run by the build or test commands.

## Offline validation

Run the available unit, patcher, transport-mock, and research tests:

```sh
PYTHONPATH=patcher:tools/caps:tools/research python3 -m unittest \
  test_tuner_firmware test_macos test_package
PYTHONPATH=tools/research python3 -m unittest discover \
  -s tools/research -p 'test_*.py'
```

The tests may need the locally supplied private assets and documented analysis dependencies. They use offline fixtures/mocks and do not communicate with earphones. Rebuild all macOS helpers and the app with `python3 tools/caps/build_tuner_app.py`.

## Research and formats

- [Known findings](research/KNOWN_FINDINGS.md) summarizes confirmed, inferred, and unverified results.
- [Research log](research/RESEARCH_LOG.md) records experiments and approvals.
- [Firmware layout](docs/firmware-layout.md), [EQ format](docs/eq-format.md), [USB protocol](docs/protocol.md), and [asset policy](docs/assets.md) document the implementation.
- [HID button research](research/HID_BUTTON_RESEARCH.md) and [custom vendor EQ notes](research/CUSTOM_VENDOR_EQ.md) describe offline analysis and its limits.
- `tools/research/` contains deterministic indexes, patch generators, emulators, analysis utilities, and tests. Generated binaries, reports, caches, app bundles, and device captures belong under ignored `research/cache/`.

## Safety model

The normal device identity is `04e8:a05e`; the transient programmer identity is `be57:0101`. Slot A is the recovery image and slot B is the development image. The tools reject unknown identities and unexpected hashes, protect A, and require complete readback before activation. Read [AGENTS.md](AGENTS.md) for repository-wide rules. Never bypass a failed check or repeat a failed flash operation automatically.

## License

Original source and documentation are released under the MIT License. Samsung firmware, updater APKs, programmer binaries, and other third-party materials remain the property of their respective owners and are not redistributed.

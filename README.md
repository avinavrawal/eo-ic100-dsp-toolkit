# EO-IC100 DSP Toolkit

Reverse-engineering and recovery-oriented tooling for the Samsung/AKG EO-IC100 USB-C earphones.

This repository documents a successful persistent internal DSP EQ modification and the associated A/B firmware staging, verification, recovery, and slot-switching workflow.

> Warning: experimental firmware tooling can render hardware unbootable. The project is designed around full-device backup, inactive-slot staging, complete read-back verification, and separate activation.

## Confirmed result

On the tested EO-IC100 unit:

```text
original slot A: 0.04_051101_aa
modified slot B: 0.23_051101_ab
post-activation query:
FW=0.23_051101_ab
CHECK=1.1
```

## Reverse-engineered components

- normal USB device: `04E8:A05E`
- transient BES programmer: `BE57:0101`
- CDC bulk OUT `0x02`, bulk IN `0x82`
- Samsung CDC initialization at 921600 8N1
- BES handshake and RAM-programmer upload
- small read `0x01`
- bulk read `0x03`
- burn setup `0x61`
- sector programming `0x62`
- flash/flag operations `0x65`
- A/B boot flag and backup-flag locations
- static internal EQ table at file offset `0x1E4C4`

## Flash layout

```text
0x3C000000  flash mapping base
0x3C004000  active A/B boot flag
0x3C005000  Samsung backup boot flag
0x3C006000  slot A image start
0x3C02E000  slot B image start
0x00080000  total flash size (512 KiB)
```

## Repository policy

Samsung firmware, updater APKs, and proprietary programmer binaries are intentionally not redistributed here. The repository contains original code, protocol notes, hashes, and tooling so users can prepare required assets locally.

## Workflow

1. Obtain the Samsung updater/programmer and official 0.23 A/B firmware images yourself.
2. Use the included patcher to generate the tested EQ-modified images locally.
3. Build the Termux helper.
4. Run Stage to make a complete 512 KiB backup and write only the inactive slot.
5. Require complete byte-for-byte verification.
6. Run Activation separately to change the A/B boot selection.
7. Use the selector scripts afterward to switch between known-good stock A and modified B without reflashing either slot.

## Status

Confirmed on one physical EO-IC100 unit:

- full flash backup: working
- inactive-slot staging: working
- complete read-back verification: working
- boot-flag activation: working
- modified B slot boot: working
- A/B selector: implemented

Hardware and firmware revisions may differ. Treat unsupported revisions as research targets.

## License

Original code and documentation are released under the MIT License. Third-party firmware and Samsung/AKG materials remain the property of their respective owners.

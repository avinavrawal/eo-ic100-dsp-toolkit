# Protocol overview

This project reverse engineered the EO-IC100 firmware-update path used by Samsung's Android updater.

## USB states

The normal earphone enumerates as `04E8:A05E`. Entering update mode temporarily re-enumerates the device as `BE57:0101`, where the updater communicates with a BES RAM programmer over a CDC-style bulk transport.

## Confirmed building blocks

The research identified:

- Samsung's CDC initialization sequence and serial parameters;
- the initial synchronization/handshake exchange;
- RAM-programmer metadata upload and execution;
- small and bulk memory-read commands;
- burn-information and sector-programming commands;
- boot-flag erase/write operations;
- the need for simultaneous input and output servicing while programming sectors;
- zero-length-packet boundaries during large memory reads.

The implementation under `tools/termux/` contains the tested wire-level details. This document intentionally keeps the overview readable and focuses on the state machine rather than reproducing every byte sequence.

## Bulk reads

The RAM programmer provides a dedicated large-read operation separate from the small boot-flag read. Large reads return a framed success acknowledgement followed by raw memory data on the bulk-IN endpoint. The programmer internally chunks transfers and uses USB zero-length packets at specific full-chunk boundaries; the host implementation accounts for those boundaries.

## Firmware burn flow

Samsung's updater first supplies burn metadata, then transmits sector records with CRC32 protection. The programmer acknowledges sectors asynchronously. The working host implementation therefore services bulk-IN and bulk-OUT concurrently during the burn phase.

See `tools/termux/eoic100.c` for the tested implementation and `docs/recovery.md` for the safety model.

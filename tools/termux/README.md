# Termux tooling

The device-side helper used during this project was built with clang and libusb in Termux and paired with Termux:API for Android USB permission handling.

The working development package contains:

- a libusb-based EO-IC100 helper;
- a recovery-first Stage wrapper;
- a separate Activation wrapper;
- A/B selector wrappers for known-good slots;
- scripts for detecting the normal and transient USB states.

This public repository intentionally does not include Samsung's updater APK, firmware images, or `programmer3001sp.bin`.

Build dependencies used during development:

```text
termux-api
clang
libusb
zip
coreutils
```

Before any write operation, read `../../docs/recovery.md` and preserve the first successful full-flash backup outside the phone.

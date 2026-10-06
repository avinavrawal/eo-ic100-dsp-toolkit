# Required third-party assets

This repository does not ship Samsung binaries.

## Samsung updater APK

The research used Samsung's USB-C Earphone firmware updater package:

```text
package: com.samsung.android.app.earphonetypec
observed version: 1.2.62
```

Extract:

```text
assets/bes/programmer3001sp.bin
```

Known SHA-256 from the tested updater:

```text
97443fb54fd75f71abbb5e3231a7f9abae26babe55c07c6b7302df0594236845
```

Example:

```bash
unzip -p samsung-earphone-updater.apk \
  assets/bes/programmer3001sp.bin \
  > programmer3001sp.bin

sha256sum programmer3001sp.bin
```

## Official Samsung firmware 0.23

The tested package was named:

```text
PID_A05E_sw0.23.zip
```

Observed Samsung model key:

```text
EO-BES3001_sp_a05e
```

The ZIP contained:

```text
ss_s11_3001sp_boot_a_sw0.23_220513.bin
ss_s11_3001sp_boot_b_sw0.23_220513.bin
```

Known stock hashes:

```text
A SHA-256
9ebc51140b17884a9b3fe97edc58f8b3861ec10dbc0a33499ea31200bdedba87

B SHA-256
2f418d3a324ec4217c32c4bf98d43c3cd07d59d81f82974f29320d399fa769f3
```

Known official ZIP SHA-256:

```text
26d1617e6e3d38e71846f125691b8e0586a9833d9f12d86ce846a0f2b64bce30
```

Use the patcher in this repository to generate `diamond_a.bin` and `diamond_b.bin` locally.

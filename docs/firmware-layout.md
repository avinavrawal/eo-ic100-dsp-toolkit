# Firmware layout notes

The tested EO-IC100 uses an A/B firmware arrangement. The research identified a 512 KiB mapped flash region, separate A and B image starts, an active-selection flag, and a backup flag area used by Samsung's updater.

The tested unit originally booted firmware `0.04_051101_aa` from slot A. A modified Samsung 0.23 image was staged into slot B and later booted successfully as `0.23_051101_ab`.

The final four bytes of each official firmware image encode the mapped image start address. Samsung's updater also writes a four-byte validity marker at the image start after a successful burn.

For exact addresses and the tested implementation, see the project source history and recovery notes. Do not assume other hardware or firmware revisions share the same layout without verifying them first.

# Recovery and safety model

The central rule is:

> Never make the first destructive firmware write before an exact backup of the physical device exists.

## Stage safety sequence

```text
normal firmware query
        ↓
identify active A/B side
        ↓
enter RAM programmer
        ↓
preserve raw boot flag
        ↓
bulk-read full 512 KiB flash
        ↓
save flash-backup.bin
        ↓
only then write inactive slot
        ↓
write validity marker
        ↓
bulk-read staged slot
        ↓
byte-for-byte verification
        ↓
stop without changing boot selection
```

## Activation

Activation is separate. It re-verifies the staged inactive image, backs up the current boot flag using Samsung's own backup location, writes the target A/B flag, reads it back, and stops without issuing a software reboot.

## Keep these files

After the first successful Stage, preserve outside the phone:

```text
flash-backup.bin
flash-backup.sha256
original-boot-flag.bin
stage-log.txt
```

The original full flash dump is more valuable than a generic stock download because it is the exact pre-modification state of the physical unit.

## Important limitation

A/B storage does not prove automatic rollback. Do not assume the boot ROM will select the other slot if the selected image is unbootable.

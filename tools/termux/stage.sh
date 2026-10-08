#!/data/data/com.termux/files/usr/bin/bash
set -euo pipefail
source ./common.sh
OUT="$HOME/eoic100-FINAL-stage-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$OUT"

echo "EO-IC100 FINAL RUN 1/2 — BACKUP + INACTIVE-SLOT DIAMOND STAGE"
echo
echo "This run WILL write the inactive firmware slot only after an exact command-0x03 BULK READ backup of all 512 KiB succeeds."
echo "It will NOT erase or write the boot-flag sector."
echo
read -r -p "Type STAGE-DIAMOND exactly to continue: " C
[ "$C" = "STAGE-DIAMOND" ] || exit 1

DEV="$(find_normal || true)"
if [ -z "$DEV" ]; then
  echo "Normal 04e8:a05e not found. Unplug 15 seconds, reconnect, retry."; exit 2
fi
echo "Normal device: $DEV"
termux-usb -r -e "./eoic100 --enter-ota-confirmed" "$DEV" >"$OUT/enter-ota.txt" 2>&1 || true

FW="$(sed -n 's/^FW=//p' "$OUT/enter-ota.txt" | tail -1 | tr -d '\r\n')"
case "$FW" in
  *_aa) ACTIVE=A ;;
  *_ab) ACTIVE=B ;;
  *)
    echo "Could not determine active slot from pre-reboot firmware version: '$FW'"
    echo "Refusing to stage."
    exit 3
    ;;
esac
echo "Pre-reboot firmware: $FW -> active slot $ACTIVE" | tee "$OUT/active-slot.txt"

CDC="$(wait_cdc "$DEV" || true)"
if [ -z "$CDC" ]; then echo "BE57:0101 not captured."; exit 4; fi
echo "CDC programmer device: $CDC"

set +e
termux-usb -r -e "./eoic100 --stage programmer3001sp.bin diamond_a.bin diamond_b.bin $OUT $ACTIVE" "$CDC" \
  >"$OUT/stage-log.txt" 2>&1
RC=$?
set -e

if [ $RC -ne 0 ]; then
  echo
  echo "STAGE FAILED rc=$RC. Boot flag was not intentionally changed."
  echo "Last 30 log lines:"
  tail -30 "$OUT/stage-log.txt" || true
  cd "$HOME"
  zip -qr "$(basename "$OUT")-FAILED.zip" "$(basename "$OUT")" || true
  cp "$(basename "$OUT")-FAILED.zip" /storage/emulated/0/Download/ 2>/dev/null || true
  echo "Failure ZIP copied to Downloads when possible."
  exit $RC
fi

sha256sum "$OUT/flash-backup.bin" >"$OUT/flash-backup.sha256"
sha256sum programmer3001sp.bin diamond_a.bin diamond_b.bin >"$OUT/package-assets.sha256"
cd "$HOME"
zip -qr "$(basename "$OUT").zip" "$(basename "$OUT")"
cp "$(basename "$OUT").zip" /storage/emulated/0/Download/ 2>/dev/null || true

echo
echo "RUN 1 COMPLETE: inactive Diamond slot staged and read-back verified."
echo "The boot flag was not changed."
echo "Backup ZIP copied to Downloads: $(basename "$OUT").zip"
echo
echo "NOW physically unplug the earphones for 15 seconds, reconnect, and confirm normal audio still works."
echo "Then RUN 2 (activate.sh) when ready."

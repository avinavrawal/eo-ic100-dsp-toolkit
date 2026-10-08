#!/data/data/com.termux/files/usr/bin/bash
set -euo pipefail
source ./common.sh

TARGET="${1:-}"
case "$TARGET" in
  A) NAME="Stock A" ;;
  B) NAME="Diamond B" ;;
  *) echo "Usage: $0 A|B"; exit 2 ;;
esac

OUT="$HOME/eoic100-slot-switch-${TARGET}-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$OUT"

echo "EO-IC100 A/B SLOT SELECTOR"
echo "Target: $NAME (slot $TARGET)"
echo
echo "This does NOT rewrite either firmware image."
echo "It only verifies the target slot and updates Samsung's A/B boot flag."
echo

read -r -p "Type BOOT-${TARGET} exactly to continue: " C
[ "$C" = "BOOT-${TARGET}" ] || { echo "Cancelled."; exit 1; }

DEV="$(find_normal || true)"
if [ -z "$DEV" ]; then
  echo "Normal 04e8:a05e not found. Physically unplug for 15 seconds, reconnect, and retry."
  exit 3
fi

echo "Normal device: $DEV"
termux-usb -r -e "./eoic100 --enter-ota-confirmed" "$DEV" \
  >"$OUT/enter-ota.txt" 2>&1 || true

FW="$(sed -n 's/^FW=//p' "$OUT/enter-ota.txt" | tail -1 | tr -d '\r\n')"
echo "Current firmware before switch: $FW" | tee "$OUT/current-firmware.txt"

case "$FW" in
  *_aa) CURRENT=A ;;
  *_ab) CURRENT=B ;;
  *) CURRENT="?" ;;
esac

if [ "$CURRENT" = "$TARGET" ]; then
  echo
  echo "Already running slot $TARGET. No boot-flag change is necessary."
  echo "The OTA-entry transition was sent, so physically unplug for 15 seconds and reconnect normally."
  exit 0
fi

CDC="$(wait_cdc "$DEV" || true)"
if [ -z "$CDC" ]; then
  echo "BE57:0101 programmer device not captured."
  exit 4
fi
echo "CDC programmer device: $CDC"

set +e
termux-usb -r -e "./eoic100 --select-slot programmer3001sp.bin $OUT $TARGET" "$CDC" \
  >"$OUT/slot-switch-log.txt" 2>&1
RC=$?
set -e

cd "$HOME"
zip -qr "$(basename "$OUT").zip" "$(basename "$OUT")" || true
cp "$(basename "$OUT").zip" /storage/emulated/0/Download/ 2>/dev/null || true

if [ $RC -ne 0 ]; then
  echo
  echo "SLOT SWITCH FAILED rc=$RC."
  tail -40 "$OUT/slot-switch-log.txt" || true
  echo "Result ZIP copied to Downloads when possible."
  exit $RC
fi

echo
echo "SUCCESS: next boot will use slot $TARGET ($NAME)."
echo "No firmware image was reflashed."
echo "Result ZIP copied to Downloads: $(basename "$OUT").zip"
echo
echo "Physically unplug the earphones for 15 seconds, then reconnect."

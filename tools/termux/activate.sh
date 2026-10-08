#!/data/data/com.termux/files/usr/bin/bash
set -euo pipefail
source ./common.sh
OUT="$HOME/eoic100-FINAL-activate-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$OUT"

echo "EO-IC100 FINAL RUN 2/2 — VERIFY STAGED SLOT + SWITCH BOOT FLAG"
echo
echo "This run re-verifies the entire staged Diamond image before touching the boot flag."
echo "If verification succeeds, it backs up the 4 KiB flag sector, switches the A/B boot flag, verifies it, and stops."
echo
read -r -p "Type ACTIVATE-DIAMOND exactly to continue: " C
[ "$C" = "ACTIVATE-DIAMOND" ] || exit 1

DEV="$(find_normal || true)"
if [ -z "$DEV" ]; then
  echo "Normal 04e8:a05e not found. Do NOT continue."; exit 2
fi
termux-usb -r -e "./eoic100 --enter-ota-confirmed" "$DEV" >"$OUT/enter-ota.txt" 2>&1 || true

FW="$(sed -n 's/^FW=//p' "$OUT/enter-ota.txt" | tail -1 | tr -d '\r\n')"
case "$FW" in
  *_aa) ACTIVE=A ;;
  *_ab) ACTIVE=B ;;
  *)
    echo "Could not determine active slot from pre-reboot firmware version: '$FW'"
    echo "Refusing activation."
    exit 3
    ;;
esac
echo "Pre-reboot firmware: $FW -> active slot $ACTIVE" | tee "$OUT/active-slot.txt"

CDC="$(wait_cdc "$DEV" || true)"
if [ -z "$CDC" ]; then echo "BE57:0101 not captured."; exit 4; fi

set +e
termux-usb -r -e "./eoic100 --activate programmer3001sp.bin diamond_a.bin diamond_b.bin $OUT $ACTIVE" "$CDC" \
  >"$OUT/activate-log.txt" 2>&1
RC=$?
set -e

cd "$HOME"
zip -qr "$(basename "$OUT").zip" "$(basename "$OUT")"
cp "$(basename "$OUT").zip" /storage/emulated/0/Download/ 2>/dev/null || true

if [ $RC -ne 0 ]; then
  echo "ACTIVATION ABORTED/FAILED rc=$RC. Read $OUT/activate-log.txt"
  exit $RC
fi

echo
echo "BOOT FLAG SWITCH VERIFIED."
echo "No software reboot was sent."
echo "Physically unplug the earphones for 15 seconds, then reconnect."
echo "The newly selected Diamond slot should boot."
echo "Result ZIP copied to Downloads: $(basename "$OUT").zip"

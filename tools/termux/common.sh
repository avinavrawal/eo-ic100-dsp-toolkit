find_normal() {
  for D in $(termux-usb -l 2>/dev/null | grep -o '/dev/bus/usb/[0-9]*/[0-9]*'); do
    termux-usb -r -e "./eoic100 --identify" "$D" > .identify-tmp.txt 2>&1 || true
    if grep -qi 'VID:PID=04e8:a05e' .identify-tmp.txt; then echo "$D"; return 0; fi
  done
  return 1
}
wait_cdc() {
  OLD="$1"; END=$((SECONDS+10)); SEEN=""
  while [ $SECONDS -lt $END ]; do
    for D in $(termux-usb -l 2>/dev/null | grep -o '/dev/bus/usb/[0-9]*/[0-9]*'); do
      [ "$D" = "$OLD" ] && continue
      case " $SEEN " in *" $D "*) continue;; esac
      SEEN="$SEEN $D"
      termux-usb -r -e "./eoic100 --identify" "$D" > .identify-cdc.txt 2>&1 || true
      if grep -qi 'VID:PID=be57:0101' .identify-cdc.txt; then echo "$D"; return 0; fi
    done
    usleep 25000 2>/dev/null || sleep 0.03
  done
  return 1
}

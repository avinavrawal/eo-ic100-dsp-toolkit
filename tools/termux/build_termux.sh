#!/data/data/com.termux/files/usr/bin/bash
set -eu
pkg install -y termux-api clang libusb zip coreutils
clang -O2 -Wall -Wextra eoic100.c -lusb-1.0 -pthread -o eoic100
echo "Built: $(pwd)/eoic100"

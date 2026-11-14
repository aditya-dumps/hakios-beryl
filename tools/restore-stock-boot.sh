#!/bin/bash
# Restore the stock boot_a image
set -e
S=${HAKIOS_SERIAL:-ZHT4IB59XSUKAELR}
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
STOCK="$ROOT/stock_boot_a.img"

if [ ! -f "$STOCK" ]; then
    echo "Error: $STOCK not found"
    exit 1
fi

echo "== Restoring stock boot_a image ($S) =="
if [ "$(adb -s $S get-state 2>/dev/null)" = device ]; then
    "$ROOT/tools/flash-boot-a.sh" "$STOCK"
else
    echo "Device in fastboot mode, flashing via fastboot..."
    fastboot -s $S flash boot_a "$STOCK"
    fastboot -s $S reboot
fi
echo "== Stock boot_a restored =="

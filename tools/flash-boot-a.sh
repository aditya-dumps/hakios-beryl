#!/bin/bash
# Flash an image to boot_a on the Redmi Note 14 5G (beryl)
set -e
S=${HAKIOS_SERIAL:-ZHT4IB59XSUKAELR}
IMG=${1:?Usage: flash-boot-a.sh <image.img>}

if [ ! -f "$IMG" ]; then
    echo "Error: $IMG not found"
    exit 1
fi

echo "== Flashing $IMG to boot_a ($S) =="

# Check if device is in fastboot
FB_DEV=$(fastboot devices | grep "$S" || true)
if [ -n "$FB_DEV" ]; then
    echo "Device detected in fastboot mode."
    fastboot -s "$S" -S 32M flash boot_a "$IMG"
    echo "== boot_a flashed successfully via fastboot =="
    exit 0
fi

# Check if device is in ADB
ADB_STATE=$(adb -s "$S" get-state 2>/dev/null || true)
if [ "$ADB_STATE" = "device" ]; then
    echo "Device detected in ADB mode."
    adb -s "$S" push "$IMG" /data/local/tmp/target_boot.img
    adb -s "$S" shell "su -c 'dd if=/data/local/tmp/target_boot.img of=/dev/block/by-name/boot_a bs=4096 && sync'"
    adb -s "$S" shell rm /data/local/tmp/target_boot.img
    echo "== boot_a flashed successfully via ADB =="
    exit 0
fi

echo "Error: Device $S not found in either ADB or fastboot mode."
exit 1

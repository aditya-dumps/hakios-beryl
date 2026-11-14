#!/bin/bash
S="ZHT4IB59XSUKAELR"
IMG="/home/aditya/beryl/mtkloader/mtkloader.img"
echo "Waiting for device $S in fastboot..."
for i in $(seq 1 600); do
    if fastboot devices | grep -q "$S"; then
        echo "Device detected in Fastboot! Flashing boot_a..."
        fastboot -s "$S" flash boot_a "$IMG"
        echo "Rebooting device..."
        fastboot -s "$S" reboot
        echo "Flashing complete and reboot issued!"
        exit 0
    fi
    sleep 1
done
echo "Timeout waiting for fastboot."
exit 1

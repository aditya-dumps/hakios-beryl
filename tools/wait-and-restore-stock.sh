#!/bin/bash
S="ZHT4IB59XSUKAELR"
STOCK="/home/aditya/beryl/stock_boot_a.img"
echo "Waiting for device $S in fastboot to restore stock Android..."
for i in $(seq 1 600); do
    if fastboot devices | grep -q "$S"; then
        echo "Device detected in Fastboot! Flashing stock_boot_a.img..."
        fastboot -s "$S" flash boot_a "$STOCK"
        echo "Rebooting into stock Android..."
        fastboot -s "$S" reboot
        echo "Stock Android restored and reboot issued!"
        exit 0
    fi
    sleep 1
done
echo "Timeout waiting for fastboot."
exit 1

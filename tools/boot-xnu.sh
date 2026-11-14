#!/bin/bash
# One-shot USB test runner for Darwin / XNU on Redmi Note 14 5G (beryl)
# Zero manual button presses or UI needed.
# Writes trigger to misc partition, reboots to Darwin, Darwin tests and resets back to Android.
set -e

S=${HAKIOS_SERIAL:-ZHT4IB59XSUKAELR}
mkdir -p logs

echo "=========================================================="
echo " [1/4] Arming single Darwin XNU boot trigger over USB"
echo "=========================================================="
adb -s "$S" wait-for-device
echo "[+] Writing boot-xnu flag to /dev/block/by-name/misc (LBA 8)..."
adb -s "$S" shell "su -c 'echo -n boot-xnu > /dev/block/by-name/misc; sync'"
adb -s "$S" shell "su -c 'printf DARWIN-BERYL:BOOT-XNU > /dev/pmsg0 2>/dev/null; sync'"
echo "[+] Flag verified in misc:"
adb -s "$S" shell "su -c 'xxd -l 16 /dev/block/by-name/misc'"

echo ""
echo "=========================================================="
echo " [2/4] Rebooting into Darwin / XNU..."
echo "=========================================================="
adb -s "$S" shell "su -c 'reboot'" 2>/dev/null || adb -s "$S" reboot 2>/dev/null || true

echo ""
echo "=========================================================="
echo " [3/4] Darwin is executing! PMIC watchdog will auto-reset."
echo "       Waiting for Android ADB reconnection (~15-20s)..."
echo "=========================================================="
adb -s "$S" wait-for-device

echo ""
echo "=========================================================="
echo " [4/4] Android is back online! Pulling pstore logs..."
echo "=========================================================="
RUN_TAG="run_$(date +%Y%m%d_%H%M%S)"
adb -s "$S" shell "su -c 'cat /sys/fs/pstore/console-ramoops-0 2>/dev/null'" > "logs/${RUN_TAG}_console.txt" || true
adb -s "$S" shell "su -c 'cat /sys/fs/pstore/pmsg-ramoops-0 2>/dev/null'" > "logs/${RUN_TAG}_pmsg.txt" || true

echo "[+] Logs extracted:"
ls -lh "logs/${RUN_TAG}_console.txt" "logs/${RUN_TAG}_pmsg.txt"
echo "=========================================================="

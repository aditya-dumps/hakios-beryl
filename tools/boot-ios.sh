#!/bin/bash
# Trigger persistent interactive iOS / Darwin session on Redmi Note 14 5G (beryl)
# Watchdog is completely disabled so the phone stays in iOS on screen.
# Hold Power button for 8s to return to Android.
set -e

S=${HAKIOS_SERIAL:-ZHT4IB59XSUKAELR}

echo "=========================================================="
echo " [1/2] Arming Interactive iOS Boot Trigger over USB"
echo "=========================================================="
adb -s "$S" wait-for-device
echo "[+] Writing 'boot-ios' flag to /dev/block/by-name/misc (LBA 8)..."
adb -s "$S" shell "su -c 'echo -n boot-ios > /dev/block/by-name/misc; sync'"
adb -s "$S" shell "su -c 'printf DARWIN-BERYL:BOOT-IOS > /dev/pmsg0 2>/dev/null; sync'"
echo "[+] Flag verified in misc:"
adb -s "$S" shell "su -c 'xxd -l 16 /dev/block/by-name/misc'"

echo ""
echo "=========================================================="
echo " [2/2] Rebooting into iOS / Darwin (Interactive Mode)..."
echo "       Watchdog is DISABLED. The screen will stay on iOS!"
echo "       To return to Android later, hold Power for 8 seconds."
echo "=========================================================="
adb -s "$S" shell "su -c 'reboot'" 2>/dev/null || adb -s "$S" reboot 2>/dev/null || true
echo "[+] Device is now booting iOS!"

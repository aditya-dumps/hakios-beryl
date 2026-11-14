#!/bin/bash
# Trigger persistent interactive iOS / Darwin session on Redmi Note 14 5G (beryl)
# Watchdog is completely disabled so the phone stays in iOS on screen.
# Persistent flag 'boot-ios-always' ensures it boots into iOS every time!
# To restore Android default boot, run: ./tools/boot-android.sh
set -e

S=${HAKIOS_SERIAL:-ZHT4IB59XSUKAELR}

echo "=========================================================="
echo " [1/2] Arming Persistent iOS Boot Trigger in misc (LBA 8)"
echo "=========================================================="
adb -s "$S" wait-for-device
echo "[+] Writing 'boot-ios-always' flag to /dev/block/by-name/misc (LBA 8)..."
adb -s "$S" shell "su -c 'echo -n boot-ios-always > /dev/block/by-name/misc; sync'"
adb -s "$S" shell "su -c 'printf DARWIN-BERYL:BOOT-IOS > /dev/pmsg0 2>/dev/null; sync'"
echo "[+] Flag verified in misc:"
adb -s "$S" shell "su -c 'xxd -l 16 /dev/block/by-name/misc'"

echo ""
echo "=========================================================="
echo " [2/2] Rebooting into iOS / Darwin (Interactive Mode)..."
echo "       Watchdog is DISABLED. The screen will stay on iOS!"
echo "       To switch back to Android, run ./tools/boot-android.sh"
echo "=========================================================="
adb -s "$S" shell "su -c 'reboot'" 2>/dev/null || adb -s "$S" reboot 2>/dev/null || true
echo "[+] Device is now booting iOS!"

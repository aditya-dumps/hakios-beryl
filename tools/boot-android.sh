#!/bin/bash
# Reset boot trigger to default Android boot on Redmi Note 14 5G (beryl)
set -e

S=${HAKIOS_SERIAL:-ZHT4IB59XSUKAELR}

echo "=========================================================="
echo " Clearing iOS boot trigger in misc (restores Android default)"
echo "=========================================================="
adb -s "$S" wait-for-device
adb -s "$S" shell "su -c 'dd if=/dev/zero of=/dev/block/by-name/misc bs=4096 count=1 conv=notrunc 2>/dev/null; sync'"
echo "[+] Cleared misc LBA 8. Phone will boot Android by default."

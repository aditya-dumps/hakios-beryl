#!/bin/bash
# One test run of mtkloader on the Redmi Note 14 5G (beryl):
# 1. Build mtkloader.img (with TIMER_PROBE=1)
# 2. Flash to boot_a
# 3. Reboot into mtkloader
# 4. Wait for phone to run timer probe and chain to Android
# 5. Read back /sys/fs/pstore/console-ramoops-0
set -e
S=${HAKIOS_SERIAL:-ZHT4IB59XSUKAELR}
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LOG_DIR="$ROOT/logs"
OUT="$LOG_DIR/mtkloader-run.log"

mkdir -p "$LOG_DIR"

echo "== [1/5] Building mtkloader.img =="
"$ROOT/mtkloader/build.sh"

echo "== [2/5] Flashing mtkloader.img to boot_a ($S) =="
"$ROOT/tools/flash-boot-a.sh" "$ROOT/mtkloader/mtkloader.img"

echo "== [3/5] Rebooting device into mtkloader =="
adb -s $S reboot

echo "== [4/5] Waiting for phone to run mtkloader and return to Android (up to 120s) =="
DEVICE_UP=0
for i in $(seq 1 40); do
    sleep 3
    STATE=$(adb -s $S get-state 2>/dev/null || true)
    if [ "$STATE" = "device" ]; then
        echo "Phone is back online in Android ($((i * 3))s)!"
        DEVICE_UP=1
        break
    fi
    echo -n "."
done
echo

if [ $DEVICE_UP -ne 1 ]; then
    echo "Warning: phone did not return within 120s. Checking fastboot..."
    fastboot devices
    exit 1
fi

sleep 4
echo "== [5/5] Pulling ramoops log =="
adb -s $S shell "su -c 'ls -la /sys/fs/pstore/; cat /sys/fs/pstore/console-ramoops-0 2>/dev/null || cat /proc/last_kmsg'" > "$OUT" 2>/dev/null || true
echo "Log saved to $OUT ($(wc -c < "$OUT") bytes)"
head -n 40 "$OUT"

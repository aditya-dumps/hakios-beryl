#!/bin/bash
# One fbdiag run on the Redmi Note 14 5G (beryl):
# 1. Build fbdiag
# 2. Flash to boot_a
# 3. Reboot
# 4. Wait for phone to run fbdiag and return to Android
# 5. Read back /sys/fs/pstore/console-ramoops-0
set -e
S=${HAKIOS_SERIAL:-ZHT4IB59XSUKAELR}
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LOG_DIR="$ROOT/logs"
OUT="$LOG_DIR/fbdiag-run.log"

mkdir -p "$LOG_DIR"

echo "== [1/5] Building fbdiag.img =="
"$ROOT/mtkloader/build_fbdiag.sh"

echo "== [2/5] Flashing fbdiag.img to boot_a =="
"$ROOT/tools/flash-boot-a.sh" "$ROOT/mtkloader/fbdiag.img"

echo "== [3/5] Rebooting device into fbdiag =="
adb -s $S reboot

echo "== [4/5] Waiting for phone to run fbdiag and return to Android (up to 90s) =="
DEVICE_UP=0
for i in $(seq 1 30); do
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
    echo "Warning: phone did not return within 90s. Checking fastboot..."
    fastboot devices
    exit 1
fi

sleep 3
echo "== [5/5] Reading /sys/fs/pstore/console-ramoops-0 =="
for i in $(seq 1 15); do
    if adb -s $S shell "cat /sys/fs/pstore/console-ramoops-0 2>/dev/null || su -c 'cat /sys/fs/pstore/console-ramoops-0' 2>/dev/null" > "$OUT" && [ -s "$OUT" ]; then
        break
    fi
    echo "Waiting for pstore read access (unlock screen if needed)... ($i/15)"
    sleep 2
done

if [ -s "$OUT" ]; then
    echo "=== fbdiag log ($(wc -c < "$OUT") bytes) ==="
    cat "$OUT"
    echo "=== End of log ==="
else
    echo "Error: console-ramoops-0 is empty or unreadable"
    exit 1
fi

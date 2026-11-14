#!/bin/bash
# Redmi Note 14 5G (beryl, MT6855) firmware extraction tool
# Pulls firmware out of the phone's Android vendor tree into fw-*/ (git ignored).
#
#   fw-touch/    FocalTech FT3519T touch firmware
#   fw-connsys/  MediaTek Connectivity Subsystem (Wi-Fi, Bluetooth, WMT)
#   fw-gpu/      PowerVR Rogue RGX GPU firmware
#
# Read only on the device; safe for testing.
set -e
S=${HAKIOS_SERIAL:-ZHT4IB59XSUKAELR}
HERE="$(cd "$(dirname "$0")" && pwd)"
OUT="${1:-$HERE}"
TMP=/data/local/tmp/hakios-fw

TOUCH_FW="focaltech_ts_fw_samsung_ft3519t.bin Conf_MultipleTest_ft3519t.ini"
CONNSYS_FW="WIFI_RAM_CODE_soc2_2_1b_1.bin WIFI_RAM_CODE_soc2_2_1c_1.bin BT_FW.cfg WMT_SOC.cfg connfem.cfg"
GPU_FW="rgx.fw rgx.sh"

echo "[+] Preparing firmware pull from beryl ($S)..."
adb -s "$S" shell "su -c 'rm -rf $TMP; mkdir -p $TMP; \
	for f in $TOUCH_FW $CONNSYS_FW $GPU_FW; do \
		[ -f /vendor/firmware/\$f ] && cp /vendor/firmware/\$f $TMP/; \
	done; \
	chmod 644 $TMP/*'"

mkdir -p "$OUT/fw-touch" "$OUT/fw-connsys" "$OUT/fw-gpu"

for f in $TOUCH_FW; do
	adb -s "$S" pull "$TMP/$f" "$OUT/fw-touch/" 2>/dev/null || true
done

for f in $CONNSYS_FW; do
	adb -s "$S" pull "$TMP/$f" "$OUT/fw-connsys/" 2>/dev/null || true
done

for f in $GPU_FW; do
	adb -s "$S" pull "$TMP/$f" "$OUT/fw-gpu/" 2>/dev/null || true
done

adb -s "$S" shell "su -c 'rm -rf $TMP'"
echo "[+] Firmware pulled successfully to $OUT/fw-*/"
ls -la "$OUT/fw-touch" "$OUT/fw-connsys" "$OUT/fw-gpu"

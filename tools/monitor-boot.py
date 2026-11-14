#!/usr/bin/env python3
import subprocess
import time
import sys

SERIAL = "ZHT4IB59XSUKAELR"
STOCK = "/home/aditya/beryl/stock_boot_a.img"

print(f"[monitor] Monitoring reboot for {SERIAL}...")
start_time = time.time()
while time.time() - start_time < 90:
    # Check fastboot
    res_fb = subprocess.run(["fastboot", "devices"], capture_output=True, text=True).stdout
    if SERIAL in res_fb:
        print("[monitor] Fastboot detected! Restoring stock Android for safety...")
        subprocess.run(["fastboot", "-s", SERIAL, "-S", "32M", "flash", "boot_a", STOCK], check=True)
        subprocess.run(["fastboot", "-s", SERIAL, "reboot"], check=True)
        print("[monitor] Stock Android restored. Fastboot drop occurred.")
        sys.exit(2)

    # Check ADB
    res_adb = subprocess.run(["adb", "devices"], capture_output=True, text=True).stdout
    for line in res_adb.splitlines():
        if SERIAL in line and "device" in line:
            print("[monitor] Android booted and ADB is online!")
            sys.exit(0)

    time.sleep(1)

print("[monitor] Timeout waiting for device.")
sys.exit(1)

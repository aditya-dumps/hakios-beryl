#!/usr/bin/env python3
"""
Trigger iOS Boot on Redmi Note 14 5G (beryl) and wait for recovery via ADB.
Logs are rescued immediately into logs/run_<timestamp>/.
"""
import os
import sys
import time
import subprocess
import datetime

SERIAL = os.environ.get("HAKIOS_SERIAL", "ZHT4IB59XSUKAELR")
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOGS_DIR = os.path.join(BASE_DIR, "logs")

def run(cmd, check=True):
    return subprocess.run(cmd, shell=True, check=check, capture_output=True, text=True)

def main():
    trigger = sys.argv[1] if len(sys.argv) > 1 else "boot-xnu"
    print(f"[*] Checking ADB connection for {SERIAL}...")
    run(f"adb -s {SERIAL} wait-for-device")

    print(f"[+] Arming '{trigger}' trigger in misc partition (LBA 8)...")
    run(f"adb -s {SERIAL} shell \"su -c 'echo -n {trigger} > /dev/block/by-name/misc && sync'\"")

    print("[+] Verified misc flag:")
    res = run(f"adb -s {SERIAL} shell \"su -c 'xxd -l 16 /dev/block/by-name/misc'\"")
    print(res.stdout.strip())

    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = os.path.join(LOGS_DIR, f"run_{ts}")
    os.makedirs(out_dir, exist_ok=True)

    print(f"[+] Rebooting into iOS / Darwin (trigger: {trigger})...")
    subprocess.run(f"adb -s {SERIAL} shell \"su -c 'reboot'\" 2>/dev/null || adb -s {SERIAL} reboot 2>/dev/null || true", shell=True)

    print(f"[*] Device disconnected. iOS boot active! Listening for Android reboot on {SERIAL}...")
    subprocess.run(f"adb -s {SERIAL} wait-for-device", shell=True)

    print(f"[+] Device reconnected to ADB! Rescuing crash/warm-reset logs to {out_dir}...")
    time.sleep(2) # Allow pstore filesystem to settle

    console_path = os.path.join(out_dir, "console.txt")
    pmsg_path = os.path.join(out_dir, "pmsg.txt")
    dmesg_path = os.path.join(out_dir, "dmesg.txt")

    subprocess.run(f"adb -s {SERIAL} shell \"su -c 'cat /sys/fs/pstore/console-ramoops-0 2>/dev/null'\" > {console_path}", shell=True)
    subprocess.run(f"adb -s {SERIAL} shell \"su -c 'cat /sys/fs/pstore/pmsg-ramoops-0 2>/dev/null'\" > {pmsg_path}", shell=True)
    subprocess.run(f"adb -s {SERIAL} shell \"su -c 'dmesg'\" > {dmesg_path}", shell=True)
    subprocess.run(f"adb -s {SERIAL} shell \"su -c 'ls -la /sys/fs/pstore/'\" > {os.path.join(out_dir, 'pstore_ls.txt')}", shell=True)

    c_sz = os.path.getsize(console_path) if os.path.exists(console_path) else 0
    p_sz = os.path.getsize(pmsg_path) if os.path.exists(pmsg_path) else 0
    print(f"[+] Rescued logs: console.txt ({c_sz} bytes), pmsg.txt ({p_sz} bytes)")
    print(f"RUN_DIR={out_dir}")

if __name__ == '__main__':
    main()

#!/usr/bin/env python3
"""
Autonomous Bootloop & Crash Rescue Watchdog for Redmi Note 14 5G (beryl)
Monitors the device while it runs iOS/Darwin. If a crash, panic, or watchdog
triggers a reboot back to Android:
1. Detects ADB reconnection immediately.
2. Extracts ramoops (console + pmsg) and AEE crash dumps.
3. Isolates kernel panic strings, registers (ESR, FAR, ELR), and userland aborts.
4. Saves high-priority report to logs/latest_crash_report.txt.
"""
import os
import sys
import time
import subprocess
import datetime
import re

SERIAL = os.environ.get("HAKIOS_SERIAL", "ZHT4IB59XSUKAELR")
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOGS_DIR = os.path.join(BASE_DIR, "logs")
os.makedirs(LOGS_DIR, exist_ok=True)

def log(msg):
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)

def wait_for_reboot_to_android():
    log(f"Waiting for device {SERIAL} to reboot into iOS (disconnect)...")
    subprocess.run(["adb", "-s", SERIAL, "wait-for-disconnect"])
    log(f"Device disconnected from ADB. iOS/Darwin is now running on {SERIAL}!")
    log("Monitoring active iOS session... Waiting for reboot or bootloop...")
    subprocess.run(["adb", "-s", SERIAL, "wait-for-device"])
    log("Device connected to ADB! System rebooted out of iOS (crash / watchdog / panic detected).")

def rescue_logs():
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    console_file = os.path.join(LOGS_DIR, f"crash_{ts}_console.txt")
    pmsg_file = os.path.join(LOGS_DIR, f"crash_{ts}_pmsg.txt")
    aee_file = os.path.join(LOGS_DIR, f"crash_{ts}_aee.txt")
    pl_lk_file = os.path.join(LOGS_DIR, f"crash_{ts}_pl_lk.txt")
    dmesg_file = os.path.join(LOGS_DIR, f"crash_{ts}_dmesg.txt")
    
    log(f"Rescuing pstore and AEE logs for timestamp {ts}...")
    subprocess.run(f"adb -s {SERIAL} shell su -c 'cat /sys/fs/pstore/console-ramoops-0 2>/dev/null' > {console_file}", shell=True)
    subprocess.run(f"adb -s {SERIAL} shell su -c 'cat /sys/fs/pstore/pmsg-ramoops-0 2>/dev/null' > {pmsg_file}", shell=True)
    subprocess.run(f"adb -s {SERIAL} shell su -c 'dmesg | grep -iE \"bootinfo|pureason|ramoops|panic|hang|aee\"' > {dmesg_file}", shell=True)
    subprocess.run(f"adb -s {SERIAL} shell su -c 'cat /data/vendor/aee_exp/db_history 2>/dev/null | tail -n 30' > {aee_file}", shell=True)
    
    # Also grab latest boot log from /data/aee_exp
    res = subprocess.run(f"adb -s {SERIAL} shell su -c 'ls -t /data/aee_exp/boot_log_*.gz 2>/dev/null | head -n 1'", shell=True, capture_output=True, text=True)
    latest_gz = res.stdout.strip()
    if latest_gz:
        log(f"Extracting latest LK / boot log from {latest_gz}...")
        subprocess.run(f"adb -s {SERIAL} exec-out su -c 'cat {latest_gz}' | gunzip | tar -x -O ./pl_lk 2>/dev/null > {pl_lk_file}", shell=True)

    c_size = os.path.getsize(console_file) if os.path.exists(console_file) else 0
    p_size = os.path.getsize(pmsg_file) if os.path.exists(pmsg_file) else 0
    l_size = os.path.getsize(pl_lk_file) if os.path.exists(pl_lk_file) else 0
    log(f"Extracted console: {c_size} bytes, pmsg: {p_size} bytes, pl_lk: {l_size} bytes.")
    
    return console_file, pmsg_file, aee_file, pl_lk_file, dmesg_file, ts

def analyze_crash(console_file, pmsg_file, aee_file, pl_lk_file, dmesg_file, ts):
    report_lines = []
    report_lines.append(f"=== CRASH ANALYSIS REPORT: {ts} ===")
    
    content = ""
    for f in [console_file, pmsg_file, aee_file, pl_lk_file, dmesg_file]:
        if os.path.exists(f):
            with open(f, "rb") as fp:
                content += fp.read().decode("latin1", "ignore") + "\n"
                
    # Search for panics, aborts, asserts, and exit reasons
    panics = re.findall(r"panic\(cpu.*?\):.*", content)
    aborts = re.findall(r"Kernel.*abort.*", content, re.IGNORECASE)
    asserts = re.findall(r"Assertion failed:.*", content)
    exit_reasons = re.findall(r"exit reason.*", content, re.IGNORECASE)
    xnu_logs = []
    
    start = content.find("=== XNU log")
    end = content.find("=== end of XNU log")
    if start != -1 and end != -1:
        xnu_logs = content[start:end+len("=== end of XNU log")].splitlines()
    
    if panics:
        report_lines.append("[!] PANIC DETECTED:")
        for p in panics[:10]:
            report_lines.append(f"    {p}")
    if aborts:
        report_lines.append("[!] ABORTS DETECTED:")
        for a in aborts[:10]:
            report_lines.append(f"    {a}")
    if asserts:
        report_lines.append("[!] ASSERTIONS FAILED:")
        for a in asserts[:10]:
            report_lines.append(f"    {a}")
    if exit_reasons:
        report_lines.append("[!] USERLAND EXIT REASONS:")
        for e in exit_reasons[:10]:
            report_lines.append(f"    {e}")
            
    if xnu_logs:
        report_lines.append(f"[i] Rescued {len(xnu_logs)} lines from XNU DRAM buffer.")
        report_lines.append("--- Last 20 lines of XNU DRAM log ---")
        for line in xnu_logs[-20:]:
            report_lines.append(f"    {line}")

    if not (panics or aborts or asserts or exit_reasons):
        report_lines.append("[i] No explicit panic string found; likely clean reboot or watchdog timeout.")
        
    report_text = "\n".join(report_lines)
    print(report_text, flush=True)
    
    latest_report = os.path.join(LOGS_DIR, "latest_crash_report.txt")
    with open(latest_report, "w") as fp:
        fp.write(report_text)
        
    return latest_report

def main():
    wait_for_reboot_to_android()
    c_file, p_file, a_file, pl_file, d_file, ts = rescue_logs()
    report = analyze_crash(c_file, p_file, a_file, pl_file, d_file, ts)
    log(f"Analysis complete. Full report written to {report}")

if __name__ == "__main__":
    main()

#!/usr/bin/env python3
import struct
import sys

KERNEL_PATH = "mtkloader/kernel_patched"
PAYLOAD_PATH = "mtkloader/payload.bin"

# 1. Patch kernel_patched
with open(KERNEL_PATH, "rb") as f:
    kdata = bytearray(f.read())

# Check offset 0x7c20d4 (cbz w22, panic)
inst1 = struct.unpack_from("<I", kdata, 0x7c20d4)[0]
assert inst1 in (0x34000516, 0xd503201f), f"Unexpected instruction at 0x7c20d4: {hex(inst1)}"
if inst1 == 0x34000516:
    struct.pack_into("<I", kdata, 0x7c20d4, 0xd503201f)
    print("[+] Patched 0x7c20d4 (kern_exit assertion cbz -> nop)")
else:
    print("[*] 0x7c20d4 already patched (nop)")

# Check offset 0x7c2150 (b.ne panic)
inst2 = struct.unpack_from("<I", kdata, 0x7c2150)[0]
assert inst2 in (0x540001e1, 0xd503201f), f"Unexpected instruction at 0x7c2150: {hex(inst2)}"
if inst2 == 0x540001e1:
    struct.pack_into("<I", kdata, 0x7c2150, 0xd503201f)
    print("[+] Patched 0x7c2150 (kern_exit assertion b.ne -> nop)")
else:
    print("[*] 0x7c2150 already patched (nop)")

with open(KERNEL_PATH, "wb") as f:
    f.write(kdata)
print(f"[+] Saved patched kernel to {KERNEL_PATH}")

# 2. Re-pack payload.bin
with open(PAYLOAD_PATH, "rb") as f:
    pdata = bytearray(f.read())

# Verify header
ph_magic, ph_size = struct.unpack_from("<II", pdata, 0)
assert ph_magic == 0x50554e58, "Invalid payload magic"

# Find kernel entry (starts at offset 8)
kname = pdata[8:24].split(b'\x00')[0].decode('latin1')
assert kname == "kernel", f"First payload entry is {kname}, expected kernel"
ksize, = struct.unpack_from("<I", pdata, 24)
assert ksize == len(kdata), f"Size mismatch: entry size {ksize} vs kernel size {len(kdata)}"

# Replace kernel bytes in payload
pdata[32:32 + len(kdata)] = kdata

with open(PAYLOAD_PATH, "wb") as f:
    f.write(pdata)
print(f"[+] Successfully updated {PAYLOAD_PATH} with patched kernel ({len(kdata)} bytes)")

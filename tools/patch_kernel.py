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

# Check offset 0x79f3bc (_cs_invalid_page entry)
# Patch with:
#   mov w0, #0 (0x52800000)
#   ret        (0xd65f03c0)
# This prevents clearing CS_VALID and prevents dyld abort (namespace 2 subcode 0xa)
inst3 = struct.unpack_from("<I", kdata, 0x79f3bc)[0]
if inst3 != 0x52800000:
    struct.pack_into("<II", kdata, 0x79f3bc, 0x52800000, 0xd65f03c0)
    print("[+] Patched 0x79f3bc (_cs_invalid_page -> mov w0, #0; ret)")
else:
    print("[*] 0x79f3bc already patched (_cs_invalid_page)")

# Check offset 0x7dd3c0 (_psignal_internal panic on unexpected SIGKILL of init)
inst4 = struct.unpack_from("<I", kdata, 0x7dd3c0)[0]
if inst4 == 0x940b9f12:
    struct.pack_into("<I", kdata, 0x7dd3c0, 0xd503201f)
    print("[+] Patched 0x7dd3c0 (_psignal_internal unexpected SIGKILL panic -> nop)")
else:
    print("[*] 0x7dd3c0 already patched (nop)")

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

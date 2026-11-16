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

# Check offsets for pmap_enter over-unwire / over-release panic assertions:
# 0x43d65c: b.le #0xfffffff007441948 (over-release assertion) -> nop
inst_pm1 = struct.unpack_from("<I", kdata, 0x43d65c)[0]
if inst_pm1 == 0x5400176d:
    struct.pack_into("<I", kdata, 0x43d65c, 0xd503201f)
    print("[+] Patched 0x43d65c (pmap_enter over-release b.le -> nop)")
else:
    print("[*] 0x43d65c already patched")

# 0x43d67c: b.le #0xfffffff007441920 (over-unwire assertion) -> nop
inst_pm2 = struct.unpack_from("<I", kdata, 0x43d67c)[0]
if inst_pm2 == 0x5400152d:
    struct.pack_into("<I", kdata, 0x43d67c, 0xd503201f)
    print("[+] Patched 0x43d67c (pmap_enter over-unwire b.le -> nop)")
else:
    print("[*] 0x43d67c already patched")

# 0x43d944: bl _panic (pmap_enter over-unwire panic call) -> nop
inst_pm3 = struct.unpack_from("<I", kdata, 0x43d944)[0]
if inst_pm3 == 0x941a1db1:
    struct.pack_into("<I", kdata, 0x43d944, 0xd503201f)
    print("[+] Patched 0x43d944 (pmap_enter over-unwire bl _panic -> nop)")
else:
    print("[*] 0x43d944 already patched")

# 0x43d96c: bl _panic (pmap_enter over-release panic call) -> nop
inst_pm4 = struct.unpack_from("<I", kdata, 0x43d96c)[0]
if inst_pm4 == 0x941a1da7:
    struct.pack_into("<I", kdata, 0x43d96c, 0xd503201f)
    print("[+] Patched 0x43d96c (pmap_enter over-release bl _panic -> nop)")
else:
    print("[*] 0x43d96c already patched")

# Check offsets for kern_sig.c:2341 assertion (signal_reason == NULL panic):
# 0x7dcec0: cbnz x21, #0x7dd3c4 -> nop
inst_sig1 = struct.unpack_from("<I", kdata, 0x7dcec0)[0]
if inst_sig1 == 0xb5002835:
    struct.pack_into("<I", kdata, 0x7dcec0, 0xd503201f)
    print("[+] Patched 0x7dcec0 (kern_sig signal_reason == NULL assertion cbnz -> nop)")
else:
    print(f"[*] 0x7dcec0 check: {hex(inst_sig1)}")

# 0x7dd14c: cbnz x21, #0x7dd3dc -> nop
inst_sig2 = struct.unpack_from("<I", kdata, 0x7dd14c)[0]
if inst_sig2 == 0xb5001495:
    struct.pack_into("<I", kdata, 0x7dd14c, 0xd503201f)
    print("[+] Patched 0x7dd14c (kern_sig signal_reason == NULL assertion cbnz -> nop)")
else:
    print(f"[*] 0x7dd14c check: {hex(inst_sig2)}")

# Zone Allocator Use-After-Free / Element Modified After Free Panic Bypasses:
# 0x346954: cbnz x0, 0xfffffff00734ac04 -> nop
inst_z1 = struct.unpack_from("<I", kdata, 0x346954)[0]
if inst_z1 == 0xb5001580:
    struct.pack_into("<I", kdata, 0x346954, 0xd503201f)
    print("[+] Patched 0x346954 (zalloc element modified after free cbnz -> nop)")
else:
    print(f"[*] 0x346954 check: {hex(inst_z1)}")

# 0x346280: cbnz x0, 0xfffffff00734a554 -> nop
inst_z2 = struct.unpack_from("<I", kdata, 0x346280)[0]
if inst_z2 == 0xb50016a0:
    struct.pack_into("<I", kdata, 0x346280, 0xd503201f)
    print("[+] Patched 0x346280 (zalloc element modified after free cbnz -> nop)")
else:
    print(f"[*] 0x346280 check: {hex(inst_z2)}")

# 0x3462f4: cbz x0, 0xfffffff00734a2dc -> b 0xfffffff00734a2dc
inst_z3 = struct.unpack_from("<I", kdata, 0x3462f4)[0]
if inst_z3 == 0xb4ffff40:
    struct.pack_into("<I", kdata, 0x3462f4, 0x14fffff6)
    print("[+] Patched 0x3462f4 (zalloc element modified after free loop cbz -> b)")
else:
    print(f"[*] 0x3462f4 check: {hex(inst_z3)}")

# 0x3469cc: cbz x0, 0xfffffff00734a9b4 -> b 0xfffffff00734a9b4
inst_z4 = struct.unpack_from("<I", kdata, 0x3469cc)[0]
if inst_z4 == 0xb4ffff40:
    struct.pack_into("<I", kdata, 0x3469cc, 0x14fffff4)
    print("[+] Patched 0x3469cc (zalloc element modified after free loop cbz -> b)")
else:
    print(f"[*] 0x3469cc check: {hex(inst_z4)}")

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

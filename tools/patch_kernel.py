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
# Replace with b +0x34 (0x1400000d) to jump over line 2341/2455 assertion panics to normal path at 0x7dd3f4
inst4 = struct.unpack_from("<I", kdata, 0x7dd3c0)[0]
if inst4 != 0x1400000d:
    struct.pack_into("<I", kdata, 0x7dd3c0, 0x1400000d)
    print("[+] Patched 0x7dd3c0 (_psignal_internal unexpected SIGKILL panic -> b +0x34 to 0x7dd3f4)")
else:
    print("[*] 0x7dd3c0 already patched (b +0x34)")

# Nop assertion panics in kern_sig.c (0x7dd3d8 and 0x7dd3f0: signal_reason == NULL)
struct.pack_into("<I", kdata, 0x7dd3d8, 0xd503201f)
struct.pack_into("<I", kdata, 0x7dd3f0, 0xd503201f)
print("[+] Patched 0x7dd3d8 & 0x7dd3f0 (kern_sig.c assertion panics -> nop)")

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
# 0x346270 (_zalloc_ext): tbnz w20, #0xe, +0x18 -> b +0x18 (0xfffffff00734a288)
inst_ze = struct.unpack_from("<I", kdata, 0x346270)[0]
if inst_ze == 0x377000d4:
    struct.pack_into("<I", kdata, 0x346270, 0x14000006)
    print("[+] Patched 0x346270 (_zalloc_ext bypass poison check -> b +0x18)")
else:
    print(f"[*] 0x346270 check: {hex(inst_ze)}")

# 0x346944 (_zalloc_item): tbnz w24, #0xe, +0x18 -> b +0x18 (0xfffffff00734a95c)
inst_zi = struct.unpack_from("<I", kdata, 0x346944)[0]
if inst_zi == 0x377000d8:
    struct.pack_into("<I", kdata, 0x346944, 0x14000006)
    print("[+] Patched 0x346944 (_zalloc_item bypass poison check -> b +0x18)")
else:
    print(f"[*] 0x346944 check: {hex(inst_zi)}")

# Code Signing Page Validation Bypass:
# 0x8214d8 (_cs_validate_page):
#   mov w8, #0xf (0x528001e8)  ; *validated_p = 0xf (all 4 4KB subpages valid)
#   str w8, [x4] (0xb9000088)
#   str wzr, [x5] (0xb90000bf) ; *tainted_p = 0
#   str wzr, [x6] (0xb90000df) ; *nx_p = 0
#   mov w0, #0 (0x52800000)    ; return KERN_SUCCESS
#   ret (0xd65f03c0)
inst_cs = struct.unpack_from("<I", kdata, 0x8214d8)[0]
if inst_cs != 0x528001e8:
    struct.pack_into("<6I", kdata, 0x8214d8,
                     0x528001e8, 0xb9000088, 0xb90000bf, 0xb90000df, 0x52800000, 0xd65f03c0)
    print("[+] Patched 0x8214d8 (_cs_validate_page -> mark valid, untainted, non-nx, KERN_SUCCESS)")
else:
    print("[*] 0x8214d8 already patched (_cs_validate_page)")

# Exception Triage Verbose Logging:
# 0x2d1d6c (exception_triage_thread b.hi -> nop)
inst_et = struct.unpack_from("<I", kdata, 0x2d1d6c)[0]
if inst_et == 0x54000328:
    struct.pack_into("<I", kdata, 0x2d1d6c, 0xd503201f)
    print("[+] Patched 0x2d1d6c (exception_triage_thread b.hi -> nop, log all exceptions)")
else:
    print(f"[*] 0x2d1d6c check: {hex(inst_et)}")

# Disable Core Dump in exit_with_reason:
# 0x7c3ce8 (bl coredump -> nop)
inst_cd = struct.unpack_from("<I", kdata, 0x7c3ce8)[0]
if inst_cd == 0x9400079a:
    struct.pack_into("<I", kdata, 0x7c3ce8, 0xd503201f)
    print("[+] Patched 0x7c3ce8 (exit_with_reason bl coredump -> nop)")
else:
    print(f"[*] 0x7c3ce8 check: {hex(inst_cd)}")

# Enable full usertrap diagnostic printing:
# 0x47234c (cbz w8, ... -> nop)
inst_ut = struct.unpack_from("<I", kdata, 0x47234c)[0]
if inst_ut == 0x34000108:
    struct.pack_into("<I", kdata, 0x47234c, 0xd503201f)
    print("[+] Patched 0x47234c (usertrap trace cbz -> nop, print full user trap registers and PC)")
else:
    print(f"[*] 0x47234c check: {hex(inst_ut)}")

# Ensure PID 1 exit outputs full panic report to pmsg instead of infinite hang:
# 0x7c3d94 (bl _panic_with_options: 0x940c04b2)
struct.pack_into("<I", kdata, 0x7c3d94, 0x940c04b2)
print("[+] Restored 0x7c3d94 (bl _panic_with_options for full diagnostic panic dump)")

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

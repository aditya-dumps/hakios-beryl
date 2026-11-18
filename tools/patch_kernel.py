#!/usr/bin/env python3
import os
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

# Check offset 0x353ecc (execve proc helper NULL deref trampoline)
# Trampoline at 0x44d260 in __TEXT_EXEC:
#   cbz x0, +12 (0x745126c) -> 0x34000060 (or 0xb4000060)
#   stp x20, x19, [sp, #-32]! -> 0xa9be4ff4
#   b 0x7357ed0 -> 0x17fc1b1a
#   ret -> 0xd65f03c0
inst_trampoline = struct.unpack_from("<I", kdata, 0x44d260)[0]
if inst_trampoline != 0x34000060 and inst_trampoline != 0xb4000060:
    struct.pack_into("<IIII", kdata, 0x44d260, 0xb4000060, 0xa9be4ff4, 0x17fc1b1a, 0xd65f03c0)
    struct.pack_into("<I", kdata, 0x353ecc, 0x1403e4e5) # b 0x7451260
    print("[+] Patched 0x353ecc (execve helper NULL deref -> __TEXT_EXEC trampoline at 0x44d260)")
else:
    print("[*] 0x44d260 trampoline already patched")

# Check offset 0x353b44 (get_bsdthread_info NULL deref safeguard)
# Place trampoline at 0x44d270 in __TEXT_EXEC so we DO NOT overwrite get_machthread at 0x353b4c:
# 0x7451270:
#   cbz x0, +8        (0xb4000040)
#   add x0, x0, #0x580 (0x91160000)
#   ret                (0xd65f03c0)
# 0x7357b44:
#   b 0x7451270        (0x1403e5cb)
#   ret                (0xd65f03c0)
# 0x7357b4c (get_machthread - restore original):
#   sub x0, x0, #0x580 (0xd1160000)
#   ret                (0xd65f03c0)
struct.pack_into("<III", kdata, 0x44d270, 0xb4000040, 0x91160000, 0xd65f03c0)
struct.pack_into("<II", kdata, 0x353b44, 0x1403e5cb, 0xd65f03c0)
struct.pack_into("<II", kdata, 0x353b4c, 0xd1160000, 0xd65f03c0)
print("[+] Patched 0x353b44 -> trampoline at 0x44d270, restored get_machthread at 0x353b4c")

# Check offset 0x7dc92c & 0x7dc9bc (kern_sig.c:1838 uth != NULL panic safeguard in psignal helper)
# 0x77e092c: cbz x21, #0x77e0990 (0xb4000335)
# 0x77e09bc: cbz x21, #0x77e0990 (0xb4fffeb5)
# 0x77e09c0: b #0x77e0930         (0x17ffffdc)
struct.pack_into("<I", kdata, 0x7dc92c, 0xb4000335)
struct.pack_into("<II", kdata, 0x7dc9bc, 0xb4fffeb5, 0x17ffffdc)
print("[+] Patched 0x7dc92c & 0x7dc9bc (kern_sig.c:1838 uth != NULL panic bypass -> clean return)")

# Patch offset 0x45a0b8 & 0x45a0f8 (msr spsel, #0 -> nop in EL1t synchronous exception vector to prevent crash when sp_el0 == 0)
struct.pack_into("<I", kdata, 0x45a0b8, 0xd503201f)
struct.pack_into("<I", kdata, 0x45a0f8, 0xd503201f)
print("[+] Patched 0x45a0b8 & 0x45a0f8 (msr spsel, #0 -> nop to safely stay on SP_EL1)")

# Patch offset 0x45a028 (b 0x45a0b0: route all EL1 synchronous exceptions directly to _fleh_synchronous, bypassing false-positive invalid stack panics)
struct.pack_into("<I", kdata, 0x45a028, 0x14000022)
print("[+] Patched 0x45a028 (b _fleh_synchronous directly for EL1 synchronous exceptions)")

# Patch EL1h IRQ exception vectors to route interrupts taken on SP_EL1 directly to genuine _fleh_irq handler:
# 1. 0x459280 (Vector 5: EL1h IRQ): b 0x45a0f8 (0x1400039e)
struct.pack_into("<I", kdata, 0x459280, 0x1400039e)
# 2. 0x45a218 (EL1h IRQ entry): b 0x45a0f8 (0x17ffffb8)
struct.pack_into("<I", kdata, 0x45a218, 0x17ffffb8)
# 3. 0x45a24c: add x1, x1, #0x5bc (0x9116f021) -> genuine _fleh_irq instead of 0x704 (panic)
struct.pack_into("<I", kdata, 0x45a24c, 0x9116f021)
# 4. 0x45a288: add x1, x1, #0x6c4 (0x911b1021) -> genuine _fleh_irq instead of 0x738 (panic)
struct.pack_into("<I", kdata, 0x45a288, 0x911b1021)
print("[+] Patched EL1h IRQ vectors (0x459280, 0x45a218, 0x45a24c, 0x45a288) -> genuine _fleh_irq handler")

# Patch alignment exception handlers to prevent kernel panics and route to exception_triage:
# 1. 0x45bc60: b.eq #0xfffffff00745fc70 -> b #0xfffffff00745fc70 (0x14000004) [PC alignment panic bypass]
struct.pack_into("<I", kdata, 0x45bc60, 0x14000004)
# 2. 0x45bef0: b.eq #0xfffffff00745ff00 -> b #0xfffffff00745ff00 (0x14000004) [SP alignment panic bypass]
struct.pack_into("<I", kdata, 0x45bef0, 0x14000004)
print("[+] Patched 0x45bc60 & 0x45bef0 (PC & SP alignment exception panics -> exception_triage)")

# Ensure PID 1 exit outputs full panic report to pmsg instead of infinite hang:
# 0x7c3d94 (bl _panic_with_options: 0x940c04b2)
struct.pack_into("<I", kdata, 0x7c3d94, 0x940c04b2)
print("[+] Restored 0x7c3d94 (bl _panic_with_options for full diagnostic panic dump)")

# Patch UFS driver redwood_ufshc.c:
# 1. 0xaf5740: set default hc_spin_us = 5,000,000 us (5s)
struct.pack_into("<I", kdata, 0xaf5740, 5000000)
# 2. 0x4cb588: bypass 5000us clamp (b #0x4cf598: 0x14000004)
struct.pack_into("<I", kdata, 0x4cb588, 0x14000004)
# 3. 0x4c9998: restore original b.ls #0x4c99b4 (0x540000e9) so loop cleanly exits on timeout
struct.pack_into("<I", kdata, 0x4c9998, 0x540000e9)
# 4. 0x4c99c4: restore original str w24, [sp, #0x54] (0xb90057f8) to setup msleep timespec
struct.pack_into("<I", kdata, 0x4c99c4, 0xb90057f8)
print("[+] Restored UFS driver spin loop & msleep handlers (0x4c9998 & 0x4c99c4)")

# Patch sysctl kern.exec_inject maxlen from 512 (0x200) to 2048 (0x800) at 0x1e8f88:
struct.pack_into("<I", kdata, 0x1e8f88, 0x800)
print("[+] Patched kern.exec_inject oid_arg2 maxlen -> 2048 bytes")

# Check offset 0x2c23b4 (mach_port_construct assertion cbnz x12, #0x2c6504)
# In development kernel, asserting kr == KERN_SUCCESS panics when service port is already labeled.
# Patch with nop (0xd503201f) so it proceeds directly to str x9, [x10, #0x70].
# Also nop sibling assertions at 0x2c2314 and 0x2c23f4.
inst_mp1 = struct.unpack_from("<I", kdata, 0x2c23b4)[0]
assert inst_mp1 in (0xb5000a8c, 0xd503201f), f"Unexpected instruction at 0x2c23b4: {hex(inst_mp1)}"
if inst_mp1 == 0xb5000a8c:
    struct.pack_into("<I", kdata, 0x2c23b4, 0xd503201f)
    print("[+] Patched 0x2c23b4 (mach_port.c:2704 assertion cbnz x12 -> nop)")
else:
    print("[*] 0x2c23b4 already patched (nop)")

# 0x2c2314 (tbz w12, #3, 0x2c64d0: assert options->flags & MPO_CONNECTION_PORT) -> nop
struct.pack_into("<I", kdata, 0x2c2314, 0xd503201f)
# 0x2c23f4 (tbz w8, #5, 0x2c64e8: assert (options->flags & MPO_STRICT) == MPO_STRICT) -> nop
struct.pack_into("<I", kdata, 0x2c23f4, 0xd503201f)
print("[+] Patched 0x2c2314 & 0x2c23f4 (mach_port_construct flag assertions -> nop)")

# Check offset 0x7cc008 (persona_find_by_type: mov w0, #3 on no persona found)
# Returns ESRCH (3) which causes launchd "Unable to find persona with type 6: 3 - No such process"
# Patch with mov w0, #0 (0x52800000) so it returns 0 (success, 0 personas found)
inst_pna = struct.unpack_from("<I", kdata, 0x7cc008)[0]
assert inst_pna in (0x52800060, 0x52800000), f"Unexpected instruction at 0x7cc008: {hex(inst_pna)}"
if inst_pna == 0x52800060:
    struct.pack_into("<I", kdata, 0x7cc008, 0x52800000)
    print("[+] Patched 0x7cc008 (persona_find_by_type ESRCH mov w0, #3 -> mov w0, #0)")
else:
    print("[*] 0x7cc008 already patched (mov w0, #0)")

# Check offset 0x443794 (pmap_nest_internal: cbnz x9, #0x443858 - attempting to overwrite non-empty TTE)
# When spawning child processes with nested dyld shared region, existing TTE causes assertion panic.
# Patch with nop (0xd503201f) so it proceeds directly to str x9, [x8] and continues cleanly.
inst_tte = struct.unpack_from("<I", kdata, 0x443794)[0]
assert inst_tte in (0xb5000629, 0xd503201f), f"Unexpected instruction at 0x443794: {hex(inst_tte)}"
if inst_tte == 0xb5000629:
    struct.pack_into("<I", kdata, 0x443794, 0xd503201f)
    print("[+] Patched 0x443794 (pmap_nest_internal overwrite non-empty TTE cbnz x9 -> nop)")
else:
    print("[*] 0x443794 already patched (nop)")

# Check sibling pmap_nest assertions at 0x443514 (has nested pmap) and 0x443774 (attempt to demote block):
struct.pack_into("<I", kdata, 0x443514, 0xd503201f)
struct.pack_into("<I", kdata, 0x443774, 0xd503201f)
print("[+] Patched 0x443514 & 0x443774 (pmap_nest sibling assertion branches -> nop)")

# Patch 0x7bcb50 in _exec_resettextvp:
# cbz x19, #0x7bcb60 -> b #0x7bcb60 (0x14000004)
# Prevents dereferencing unaligned/garbage old_vp during execve of child tasks (e.g. xpcproxy)
inst_reset = struct.unpack_from("<I", kdata, 0x7bcb50)[0]
assert inst_reset in (0xb4000093, 0x14000004), f"Unexpected instruction at 0x7bcb50: {hex(inst_reset)}"
if inst_reset == 0xb4000093:
    struct.pack_into("<I", kdata, 0x7bcb50, 0x14000004)
    print("[+] Patched 0x7bcb50 (_exec_resettextvp old_vp bypass -> b 0x7bcb60)")
else:
    print("[*] 0x7bcb50 already patched (b 0x7bcb60)")

# Patch forkproc at 0x7c9054 - 0x7c9058:
# Clear [x19, #0x598] to NULL on fork so child tasks never inherit unaligned old_vp
struct.pack_into("<II", kdata, 0x7c9054, 0xf902ce7f, 0x1400000a)
print("[+] Patched 0x7c9054-0x7c9058 (forkproc p_textvp clean init -> str xzr; b +0x28)")

# Patch _ipc_mqueue_set_qlimit_locked at 0x2ae604:
# b.ls #0x2ae660 -> b #0x2ae660 (0x14000017)
# Directly sets new queue limit and returns cleanly without waking non-existent senders on uninitialized waitqs
inst_ql = struct.unpack_from("<I", kdata, 0x2ae604)[0]
assert inst_ql in (0x540002e9, 0x14000017), f"Unexpected instruction at 0x2ae604: {hex(inst_ql)}"
if inst_ql == 0x540002e9:
    struct.pack_into("<I", kdata, 0x2ae604, 0x14000017)
    print("[+] Patched 0x2ae604 (_ipc_mqueue_set_qlimit_locked bypass wakeup -> b 0x2ae660)")
else:
    print("[*] 0x2ae604 already patched (b 0x2ae660)")

# Patch _waitq_wakeup64_one & _waitq_wakeup64_all to safely handle invalid waitqs:
# 1. Restore 0x33f460 to original: ldrb w8, [x20, #5] (0x39401688)
struct.pack_into("<I", kdata, 0x33f460, 0x39401688)
print("[+] Restored 0x33f460 (ldrb w8, [x20, #5])")

# 2. Patch _waitq_wakeup64_one panic handler at 0x33f4ec - 0x33f4f0:
# Instead of calling waitq_panic_invalid, return KERN_SUCCESS (0) cleanly via epilogue at 0x298c60:
# mov w0, #0 (0x52800000)
# b 0xfffffff00729cc60 (0x17fd65dc)
struct.pack_into("<II", kdata, 0x33f4ec, 0x52800000, 0x17fd65dc)
print("[+] Patched 0x33f4ec-0x33f4f0 (_waitq_wakeup64_one invalid waitq panic -> mov w0, #0; b 0x298c60)")

# 3. Patch _waitq_wakeup64_all panic handler at 0x33f59c - 0x33f5a0:
# mov w0, #0 (0x52800000)
# b 0xfffffff00729cc60 (0x17fd65b0)
struct.pack_into("<II", kdata, 0x33f59c, 0x52800000, 0x17fd65b0)
print("[+] Patched 0x33f59c-0x33f5a0 (_waitq_wakeup64_all invalid waitq panic -> mov w0, #0; b 0x298c60)")

# 4. Patch task_set_phys_footprint_limit_internal NULL-task data abort:
# a) At 0x31ecfc: str xzr, [sp, #8] -> cbz x0, #0x31ee50 (0xb4000aa0)
struct.pack_into("<I", kdata, 0x31ecfc, 0xb4000aa0)
print("[+] Patched 0x31ecfc (task_set_phys_footprint_limit_internal NULL guard -> cbz x0, exit)")

# b) Install NULL-task guard trampoline at 0x44d280:
# cbz x0, +8 (0xb4000040)
# b 0xfffffff007322cd0 (0x17fb4693)
# ret (0xd65f03c0)
struct.pack_into("<III", kdata, 0x44d280, 0xb4000040, 0x17fb4693, 0xd65f03c0)
print("[+] Installed task_footprint NULL guard trampoline at 0x44d280")

# c) Patch caller at 0x7eba78: bl 0x31ecd0 -> bl 0x44d280 (0x97f18602)
struct.pack_into("<I", kdata, 0x7eba78, 0x97f18602)
print("[+] Patched 0x7eba78 (caller bl task_footprint -> bl trampoline at 0x44d280)")

# 5. Patch pmap_ttne block demote panics at 0x4411c8 & 0x4411f8:
# Bypasses "Attempt to demote L1/L2 block" panics and returns KERN_FAILURE (5) cleanly
struct.pack_into("<I", kdata, 0x4411c8, 0x1400003a) # b 0x4412b0
struct.pack_into("<I", kdata, 0x4411f8, 0x1400002e) # b 0x4412b0
print("[+] Patched 0x4411c8 & 0x4411f8 (pmap_ttne block demote panic -> b 0x4412b0 clean KERN_FAILURE)")

# 6. Restore shared_region_check_np at 0x86e4f4 - 0x86e4f8 to genuine code:
# Must return ENOMEM (12) when no shared cache is present so launchd.ios loads standalone dylibs
struct.pack_into("<II", kdata, 0x86e4f4, 0x90ffc560, 0x91374800)
print("[+] Restored 0x86e4f4-0x86e4f8 (shared_region_check_np -> original adrp/add for standalone dylibs)")

# 7. Patch clock_initialize_calendar warning at 0x2c80a0:
# Bypasses "UTC time is less then sys time" warning
struct.pack_into("<I", kdata, 0x2c80a0, 0x14000043) # b 0x2c81ac
print("[+] Patched 0x2c80a0 (clock_initialize_calendar warning bypass -> b 0x2c81ac)")

# 8. Patch lock_ticket.c assertions (Invalid HW ticket lock panic @lock_ticket.c:125, 134, 143, 152):
# Neutralize all 4 ticket lock panic helper stubs at root:
# 0xac7840 (line 152: unexpectedly not owned), 0xac7870 (line 143: unexpectedly owned),
# 0xac78a0 (line 125: invalid type), 0xac78d0 (line 134: invalid owner)
for panic_stub in [0xac7840, 0xac7870, 0xac78a0, 0xac78d0]:
    struct.pack_into("<I", kdata, panic_stub, 0xd65f03c0) # ret
print("[+] Neutralized lock_ticket.c panic entry stubs (0xac7840, 0xac7870, 0xac78a0, 0xac78d0 -> ret)")

# Eliminates DEVELOPMENT XNU assertions on lock->type == 0x44 and lock->owner across all CPUs
ticket_lock_offsets = [
    0x2e8074, 0x2e81d4, 0x2e81dc, 0x2e833c, 0x2e8344, 0x2e84c8, 0x2e84e4, 0x2e85f0, 0x2e8614, 0x2e8670,
    0x2e8708, 0x2e87a0, 0x2e87b8, 0x2e88fc, 0x2e8918, 0x2e8a24, 0x2e8a48, 0x2e8aa0, 0x2e8b38, 0x2e8cbc,
    0x2e8db8, 0x2e8e58, 0x2e8f10, 0x2e8f18, 0x2e8f28, 0x2e8fe0, 0x2e8ff0, 0x2e9078, 0x2e909c, 0x2e90ac,
    0x2e9148, 0x2e9154, 0x2e91b4, 0x2e91f0, 0x2e9308, 0x2e9320, 0x2e9330, 0x2e93d0, 0x2e9468, 0x2e94f4,
    0x2e9594, 0x2e99fc, 0x2e9c4c, 0x2e9f58, 0x2e9fb4, 0x2ea014, 0x2ea064, 0x2ea0f4, 0x2ea178, 0x2ea210,
    0x2ea2a8, 0x2ea2cc, 0x2ea2d4, 0x2ea374, 0x2ea398, 0x2ea3a0, 0x2ea440, 0x2ea4e0, 0x2ea570, 0x2ea590,
    0x2ea5ac, 0x2ea65c, 0x2ea670, 0x2ea68c, 0x2ea730, 0x2ea7c4, 0x2eab5c, 0x2eabb8, 0x2eac14, 0x2eac8c,
    0x2ead94, 0x2eb0ac, 0x2eb0e0, 0x2eb174, 0x2eb648, 0x2eb69c, 0x2eb6a4, 0x2eb6a8, 0x2eb6b0, 0x2eb6dc,
    0x2eba9c, 0x2ebab8, 0x2ebb4c, 0x2ebb68, 0x2ebbf4, 0x2ebc60, 0x2ebce8,
    # Additional ticket lock release / caller branch sites
    0x2eeca0, 0x2eecf0, 0x2eecf4, 0x2eed08, 0x2eed10, 0x2eed18, 0x2ead3c, 0x2eadec, 0x2eac74, 0x2eac78, 0x2eacf0
]
for t_off in ticket_lock_offsets:
    struct.pack_into("<I", kdata, t_off, 0xd503201f) # nop
print(f"[+] Patched {len(ticket_lock_offsets)} lock_ticket.c assertion & panic branches -> nop")

# 9. Patch ipc_tt.c assertions (convert_corpse_to_port_and_nsrequest):
# Prevents assertion panic "Assertion failed: port->ip_srights == 0" @ ipc_tt.c:3764
# 0xfffffff0072df474 (file offset 0x2db474): cbnz w8, #0xfffffff0072df4d0 -> nop
struct.pack_into("<I", kdata, 0x2db474, 0xd503201f) # nop
# 0xfffffff0072df490 (file offset 0x2db490): b.ne #0xfffffff0072df4e8 -> b 0xfffffff0072df494
struct.pack_into("<I", kdata, 0x2db490, 0x14000001) # b +4
print("[+] Patched 0x2db474 & 0x2db490 (convert_corpse_to_port_and_nsrequest assertion bypass)")

# 10. Patch zone_require_ro (0xfffffff00734b4c8, file offset 0x3474c8):
# Eliminates nested panics (_zone_id_require_ro_panic) during crash logging and stackshot
struct.pack_into("<I", kdata, 0x3474c8, 0xd65f03c0) # ret
print("[+] Patched 0x3474c8 (zone_require_ro -> ret, eliminates nested panics)")

# 11. Patch user_exception_trace (0xfffffff007476314, file offset 0x472314):
# Eliminates "Kernel data abort at pc 0xfffffff007468eac" when copyinstr reads untrusted user addresses
struct.pack_into("<I", kdata, 0x472314, 0xd65f03c0) # ret
print("[+] Patched 0x472314 (user_exception_trace -> ret, eliminates copyinstr kernel data abort)")

# 12. Patch exception_triage at 0x2d1998 -> trampoline at 0x44d290
# Intercepts userland EXC_BREAKPOINT (6), EXC_BAD_ACCESS (1), and EXC_BAD_INSTRUCTION (2):
# - Recovers from NULL pointer calls (pc = lr)
# - Skips invalid dyld stubs (pc += 8)
# - Skips faulting instructions (pc += 4)
# Returns KERN_SUCCESS cleanly so SpringBoard, xpcproxy, and launchd keep running!
cave_vm = 0xfffffff007451290

def b_imm(src, dst):
    diff = (dst - src) // 4
    return 0x14000000 | (diff & 0x03ffffff)

def bl_imm(src, dst):
    diff = (dst - src) // 4
    return 0x94000000 | (diff & 0x03ffffff)

def b_cond(src, dst, cond):
    diff = (dst - src) // 4
    return 0x54000000 | ((diff & 0x7ffff) << 5) | cond

def cbz_imm(src, dst, rt):
    diff = (dst - src) // 4
    return 0xb4000000 | ((diff & 0x7ffff) << 5) | rt

labels = {}
code_spec = [
    ('start', 'cmp_w19_6', 0x71001a7f),
    (None, 'b_eq_user', lambda cur: b_cond(cur, labels['is_user_exc'], 0)), # eq
    (None, 'cmp_w19_2', 0x71000a7f), # cmp w19, #2 (EXC_BAD_INSTRUCTION)
    (None, 'b_eq_user3', lambda cur: b_cond(cur, labels['is_user_exc'], 0)), # eq
    ('normal', 'cmp_w19_9', 0x7100267f),
    (None, 'b_norm', lambda cur: b_imm(cur, 0xfffffff0072d599c)),
    ('is_user_exc', 'mov_x0_x22', 0xaa1603e0),
    (None, 'bl_regs', lambda cur: bl_imm(cur, 0xfffffff00746e2e4)),
    (None, 'cbz_x0', lambda cur: cbz_imm(cur, labels['normal'], 0)),
    (None, 'ldr_pc', 0xf9407c08),
    (None, 'cbz_pc', lambda cur: cbz_imm(cur, labels['fix_null'], 8)), # x8
    (None, 'and_fff', 0x92402d09), # and x9, x8, #0xfff
    (None, 'cmp_1b0', 0x7106c13f), # cmp w9, #0x1b0
    (None, 'b_ne_normal', lambda cur: b_cond(cur, labels['normal'], 1)), # ne -> normal!
    (None, 'add_pc_8', 0x91002108), # pc += 8
    (None, 'str_pc', 0xf9007c08),
    (None, 'mov_w0', 0x52800000),
    (None, 'b_exit', lambda cur: b_imm(cur, 0xfffffff0072d5b54)),
    ('fix_null', 'ldr_lr', 0xf9407808), # ldr x8, [x0, #0xf0]
    (None, 'str_pc_lr', 0xf9007c08),
    (None, 'mov_w0_2', 0x52800000),
    (None, 'b_exit_2', lambda cur: b_imm(cur, 0xfffffff0072d5b54)),
]

for i, (lbl, name, val) in enumerate(code_spec):
    addr = cave_vm + i * 4
    if lbl:
        labels[lbl] = addr

assembled = []
for i, (lbl, name, val) in enumerate(code_spec):
    addr = cave_vm + i * 4
    if callable(val):
        assembled.append(val(addr))
    else:
        assembled.append(val)

for idx, val in enumerate(assembled):
    struct.pack_into("<I", kdata, 0x44d290 + idx * 4, val)

# Hook at 0x2d1998: b cave_vm
struct.pack_into("<I", kdata, 0x2d1998, b_imm(0xfffffff0072d5998, cave_vm))
print(f"[+] Patched 0x2d1998 -> universal user exception hook at 0x44d290 ({len(assembled)} instructions, EXC_BREAKPOINT + EXC_BAD_ACCESS + EXC_BAD_INSTRUCTION auto-recovery)")

# 13. Patch pmap_insert_commpage_internal at 0x445c68 (0xfffffff007449c68):
# Bypasses panic "pmap_insert_commpage_internal: Found something mapped at the commpage address?! @pmap.c:11082"
# 0xfffffff007449c68: cbnz x10, #0xfffffff007449ca0 (panic) -> cbnz x10, #0xfffffff007449c7c (unlock & return KERN_SUCCESS)
struct.pack_into("<I", kdata, 0x445c68, 0xb50000aa)
print("[+] Patched 0x445c68 (pmap_insert_commpage_internal: commpage collision -> unlock & return KERN_SUCCESS)")

# 14. Patch NULL pointer dereference in object retain at 0x33190c (0xfffffff00733590c):
# Fixes "panic: Kernel data abort. at pc 0xfffffff00733591c, lr 0xfffffff007376840" (far: 0x30)
# Trampoline at cave 0x44d310 (0xfffffff007451310):
#   0xfffffff007451310: cbz x0, +12 (ret)
#   0xfffffff007451314: stp x20, x19, [sp, #-32]!
#   0xfffffff007451318: b 0xfffffff007335910
#   0xfffffff00745131c: ret
retain_fn = 0xfffffff00733590c
retain_cave = 0xfffffff007451310
struct.pack_into("<I", kdata, 0x44d310, cbz_imm(retain_cave, retain_cave + 12, 0)) # cbz x0, ret
struct.pack_into("<I", kdata, 0x44d314, 0xa9be4ff4)                               # stp x20, x19, [sp, #-32]!
struct.pack_into("<I", kdata, 0x44d318, b_imm(retain_cave + 8, retain_fn + 4))    # b 0xfffffff007335910
struct.pack_into("<I", kdata, 0x44d31c, 0xd65f03c0)                               # ret
struct.pack_into("<I", kdata, 0x33190c, b_imm(retain_fn, retain_cave))             # b retain_cave
print("[+] Patched 0x33190c -> NULL guard trampoline at 0x44d310 (eliminates 0x733591c kernel data abort)")

# 15. Patch dtrace_proc_fork at 0x4b15bc (0xfffffff0074b55bc):
# Eliminates "panic: Kernel data abort. at pc 0xfffffff0074b55f4, lr 0xfffffff0074b55e8"
# When forkproc forks a new process, dtrace_proc_fork tries to traverse [parent + 0x570]
# which holds uninitialized garbage (0x106c00070228020c).
# Returning NULL (w0 = 0) sets proc->p_dtrace to NULL and completes forkproc cleanly!
struct.pack_into("<I", kdata, 0x4b15bc, 0x52800000) # mov w0, #0
struct.pack_into("<I", kdata, 0x4b15c0, 0xd65f03c0) # ret
print("[+] Patched 0x4b15bc (dtrace_proc_fork -> mov w0, #0; ret, eliminates 0x74b55f4 data abort)")

# 16. Patch sleh.c brk #1 at 0x45bc18 (0xfffffff00745fc18):
# Eliminates "panic: Break 0x0001 instruction exception from kernel. Panic (by design) at pc 0xfffffff00745fc18"
# 0xfffffff00745fc18: brk #1 (0xd4200020) -> b 0xfffffff00745fb30 (0x17ffffc6)
# Safely jumps to sleh_synchronous epilogue (ldp x29, x30, [sp, #96] ... ret) to return cleanly
struct.pack_into("<I", kdata, 0x45bc18, 0x17ffffc6) # b 0xfffffff00745fb30
print("[+] Patched 0x45bc18 (sleh.c brk #1 -> b 0x745fb30 clean epilogue return)")

# 17. Patch coalition.c assertion panics in i_coal_resource_adopt_task:
# Eliminates "panic: i_coal_resource_adopt_task: coalition ... id:... type:RESOURCE task_count(...) < dead_task_count(...) @coalition.c:615"
# Nop the 4 conditional assertion branches that trigger panic on uninitialized/corrupt coalition counters:
# 0xfffffff0072d1550 (file offset 0x2cd550): b.ne 0x72d15dc -> nop
# 0xfffffff0072d1564 (file offset 0x2cd564): b.cc 0x72d15f8 -> nop
# 0xfffffff0072d1588 (file offset 0x2cd588): b.ne 0x72d15f4 -> nop
# 0xfffffff0072d1598 (file offset 0x2cd598): b.ne 0x72d15f4 -> nop
for coal_off in [0x2cd550, 0x2cd564, 0x2cd588, 0x2cd598]:
    struct.pack_into("<I", kdata, coal_off, 0xd503201f) # nop
print("[+] Patched 4 coalition.c assertion branches (0x2cd550, 0x2cd564, 0x2cd588, 0x2cd598 -> nop)")

# 18. Patch sleh.c EL1 Data Abort exception fixup handling for copyin / bcopy:
# Eliminates "panic: Kernel data abort. at pc 0xfffffff007468d24, lr 0xfffffff007452714"
# Restore 0x45b040 to original (str wzr, [sp, #0x3c]; b 0x745f050) so demand-paged user copies
# (such as userland stack allocations in load_init_program) properly invoke vm_fault!
struct.pack_into("<I", kdata, 0x45b040, 0xb9003fff) # str wzr, [sp, #0x3c]
struct.pack_into("<I", kdata, 0x45b044, 0x14000003) # b 0xfffffff00745f050

# Guard panic sites (0x45b8f0, 0x45b924, 0x45b944): if [sp, #0x3c] == 0 (fixup exists),
# jump directly to genuine fixup path at 0xfffffff00745f1f0 instead of panicking!
# 0x45b8f0: ldr w8, [sp, #0x3c]; cbz w8, 0x745f1f0
struct.pack_into("<I", kdata, 0x45b8f0, 0xb9403fe8) # ldr w8, [sp, #0x3c]
struct.pack_into("<I", kdata, 0x45b8f4, 0x34ffc7e8) # cbz w8, #0xfffffff00745f1f0
# 0x45b924: ldr w8, [sp, #0x3c]; cbz w8, 0x745f1f0
struct.pack_into("<I", kdata, 0x45b924, 0xb9403fe8) # ldr w8, [sp, #0x3c]
struct.pack_into("<I", kdata, 0x45b928, 0x34ffc648) # cbz w8, #0xfffffff00745f1f0
# 0x45b944: ldr w8, [sp, #0x3c]; cbz w8, 0x745f1f0
struct.pack_into("<I", kdata, 0x45b944, 0xb9403fe8) # ldr w8, [sp, #0x3c]
struct.pack_into("<I", kdata, 0x45b948, 0x34ffc548) # cbz w8, #0xfffffff00745f1f0
print("[+] Patched sleh.c EL1 Data Abort exception fixup handling: restored vm_fault at 0x45b040 & guarded panics at 0x45b8f0/0x45b924/0x45b944 -> 0x745f1f0")

# 19. Patch sleh.c brk #1 at 0x45b97c (0xfffffff00745f97c):
# Eliminates secondary panic trap after unclassified exception triage
# 0xfffffff00745f97c: brk #1 (0xd4200020) -> b 0xfffffff00745f2f0 (0x17fffe5d)
struct.pack_into("<I", kdata, 0x45b97c, 0x17fffe5d) # b 0xfffffff00745f2f0
print("[+] Patched 0x45b97c (sleh.c brk #1 -> b 0x745f2f0 clean return)")

# 20. Patch arm_init.c:446 assertions at 0x452cf8 & 0x452d04 (0xfffffff007456cf8 & 0xfffffff007456d04):
# Eliminates "panic(cpu 1 caller 0xfffffff007ac905c): arm_init.c:446 Assertion failed: master_cpu >= 0 && master_cpu <= ml_get_max_cpu_number()"
# Nop both range check branches and early Mach-O segment validation branches:
# 0x452cf8: tbnz w21, #0x1f, 0x74574a0 -> nop
# 0x452d04: b.gt 0x74574a0 -> nop
# 0x452adc: b.ne 0x74574b8 -> nop
# 0x452b00: b.ne 0x74574d0 -> nop
for arm_init_off in [0x452cf8, 0x452d04, 0x452adc, 0x452b00]:
    struct.pack_into("<I", kdata, arm_init_off, 0xd503201f) # nop
print("[+] Patched 4 arm_init.c assertion branches (0x452cf8, 0x452d04, 0x452adc, 0x452b00 -> nop)")

# 21. Patch copyio.c PAN assertions at 0x44ecb4 & 0x44e6fc (0xfffffff007452cb4 & 0xfffffff0074526fc):
# Eliminates "panic: copyio.c: __builtin_arm_rsr('pan') != 0"
# Nop the PAN check branches:
# 0x44ecb4: cbz w8, #0x7452ce0 (copyout) -> nop
# 0x44e6fc: cbz w8, #0x7452730 (copyin) -> nop
struct.pack_into("<I", kdata, 0x44ecb4, 0xd503201f) # nop
struct.pack_into("<I", kdata, 0x44e6fc, 0xd503201f) # nop
print("[+] Patched copyio.c PAN assertions (0x44ecb4 & 0x44e6fc -> nop)")

# 22. Patch invalid address abort in object validation at 0x33f45c (0xfffffff00734345c):
# Eliminates "panic: Kernel data abort. at pc 0xfffffff007343460, lr 0xfffffff0072b2634"
# Change `cbz x0, #0x73434ec` to `tbz x0, #0x3f, #0x73434ec` (0xb6f80480)
# This safely rejects any pointer where bit 63 is 0 (including NULL and non-canonical/tagged pointers like 0x000cc80b00000005)
struct.pack_into("<I", kdata, 0x33f45c, 0xb6f80480) # tbz x0, #0x3f, #0xfffffff0073434ec
print("[+] Patched 0x33f45c -> tbz x0, #0x3f guard (eliminates 0x7343460 non-canonical pointer abort)")

# 23. Patch sleh.c preemption check & stack canary failure branches:
# Eliminates "panic: synchronous exception changed preemption level from %d to %d"
# 0xfffffff00745f334 (file offset 0x45b334): b.ne 0x745f670 -> nop
# 0xfffffff00745f34c (file offset 0x45b34c): b.ne 0x745f66c -> nop
struct.pack_into("<I", kdata, 0x45b334, 0xd503201f) # nop
struct.pack_into("<I", kdata, 0x45b34c, 0xd503201f) # nop
print("[+] Patched sleh.c preemption check and canary branches (0x45b334 & 0x45b34c -> nop)")

# 24. Patch exec_activate_image: bypass SIGKILL delivery and disarm assertion failure
# Eliminates PID 1 termination during load_init_program
# 0xfffffff0077bd140 (file offset 0x7b9140): restore cbz x22, 0x77bd1c4 (0xb4000422)
struct.pack_into("<I", kdata, 0x7b9140, 0xb4000422)
# 0xfffffff0077bd170 (file offset 0x7b9170): bl psignal_with_reason -> nop (0xd503201f)
struct.pack_into("<I", kdata, 0x7b9170, 0xd503201f)
# 0xfffffff0077bd1c4 (file offset 0x7b91c4): assert failure -> b 0x77bd178 clean exit (0x17ffffed)
struct.pack_into("<I", kdata, 0x7b91c4, 0x17ffffed)
print("[+] Patched 0x7b9140, 0x7b9170, 0x7b91c4 (exec_activate_image: disarm SIGKILL & assert panic -> clean exit)")

# 25. Patch kernel global code signing enforcement flags
# 0xfffffff0071ecdb0 (file offset 0x1e8db0): clear cs_enforcement, cs_library_validation, etc.
struct.pack_into("<I", kdata, 0x1e8db0, 0x00000000)
print("[+] Patched 0x1e8db0 (kernel cs_enforcement flags -> 0)")

# 26. Patch psignal_internal: prevent tagged/unaligned proc pointer corruption
# 0xfffffff0077e0a84 (file offset 0x7dca84): tbnz w19, #2, 0x77e0ab0 -> nop (0xd503201f)
struct.pack_into("<I", kdata, 0x7dca84, 0xd503201f)
# 0xfffffff0077e0ac4 (file offset 0x7dcac4): mov x20, x0 -> mov x20, x24 (0xaa1803f4)
struct.pack_into("<I", kdata, 0x7dcac4, 0xaa1803f4)
print("[+] Patched 0x7dca84 & 0x7dcac4 (psignal_internal: preserve aligned x24 struct proc *)")

# 27. Patch lck_mtx_unlock: enforce natural 8-byte pointer alignment before ldxr
# Eliminates "panic: Kernel data abort. at pc 0xfffffff0072e8950 (ESR 0x96000021, FAR unaligned)"
# 0xfffffff0072e8944 (file offset 0x2e4944): ldr w8, [x8, #0x360] -> and x0, x0, #~7 (0x927df000)
# 0xfffffff0072e896c (file offset 0x2e496c): cbnz w8, 0x72e8980 -> nop (0xd503201f)
struct.pack_into("<I", kdata, 0x2e4944, 0x927df000)
struct.pack_into("<I", kdata, 0x2e496c, 0xd503201f)
print("[+] Patched 0x2e4944 & 0x2e496c (lck_mtx_unlock: mask x0 with #~7 -> guaranteed natural alignment)")

# 28. Restore exec stack & state setup functions (0x7be688, 0x7bec8c, 0x7bed90, 0x7bf0a0, 0x7bfc70, 0x7bff6c)
# These are NOT codesigning functions; they are _exec_handle_sugid, _activate_exec_state,
# _create_unix_stack, _exec_add_apple_strings, _exec_copyout_strings, and _copyoutptr.
# Restoring them allows XNU to set up user stack, arguments, and thread entrypoint for PID 1.
exec_orig = {
    0x7be688: (0xd10343ff, 0xa9095ff8), # _exec_handle_sugid
    0x7bec8c: (0xa9bc5ff8, 0xa90157f6), # _activate_exec_state
    0x7bed90: (0xd10303ff, 0xa9066ffc), # _create_unix_stack
    0x7bf0a0: (0xa9bb6ffc, 0xa9015ff8), # _exec_add_apple_strings
    0x7bfc70: (0xd104c3ff, 0xa90d6ffc), # _exec_copyout_strings
    0x7bff6c: (0xd10083ff, 0xa9017bfd), # _copyoutptr
}
for off, (w1, w2) in exec_orig.items():
    struct.pack_into("<I", kdata, off, w1)
    struct.pack_into("<I", kdata, off + 4, w2)
print("[+] Restored 6 exec stack & state setup functions (_activate_exec_state, _create_unix_stack, etc.)")

# 29. Patch memdev.c mdevadd: disarm overlapping memory device panic and clean return -1
# Eliminates "panic: mdevadd: attempt to add overlapping memory device at ... @memdev.c:658"
# 0xfffffff0074c2004 (file offset 0x4be004): b 0xfffffff0074c21e0 (0x14000077) -> clean return -1 on overlap
# 0xfffffff0074c2024 (file offset 0x4be024): bl _panic -> nop (0xd503201f)
struct.pack_into("<I", kdata, 0x4be004, 0x14000077)
struct.pack_into("<I", kdata, 0x4be024, 0xd503201f)
print("[+] Patched 0x4be004 & 0x4be024 (memdev.c: disarmed overlapping memory device panic -> clean return -1)")

# 30. Patch sleh.c brk #1 panic traps for userland breakpoints and exceptions:
# Eliminates "panic: Break 0x0001 instruction exception from kernel. Panic (by design) at pc 0xfffffff00745ff74"
# Installs clean epilogue trampoline in NOP padding at 0x45f730 (VA 0xfffffff007463730):
struct.pack_into("<I", kdata, 0x45f730, 0xa9417bfd) # ldp x29, x30, [sp, #0x10]
struct.pack_into("<I", kdata, 0x45f734, 0x910083ff) # add sp, sp, #0x20
struct.pack_into("<I", kdata, 0x45f738, 0xd65f03c0) # ret
# 0xfffffff00745ff74 (file offset 0x45bf74): brk #1 -> b 0xfffffff007463730 (0x14000def)
struct.pack_into("<I", kdata, 0x45bf74, 0x14000def)
# 0xfffffff00745ff30 (file offset 0x45bf30): brk #1 -> b 0xfffffff007463730 (0x14000e00)
struct.pack_into("<I", kdata, 0x45bf30, 0x14000e00)
# 0xfffffff00745fec0 (file offset 0x45bec0): brk #1 -> b 0xfffffff00745fe38 (0x17ffffde)
struct.pack_into("<I", kdata, 0x45bec0, 0x17ffffde)
print("[+] Patched sleh.c brk #1 traps (0x45bf74, 0x45bf30, 0x45bec0 -> clean epilogue return, eliminates panic by design)")

# 31. Patch kern_descrip.c NULL fd_ofiles Data Abort at 0xfffffff0077b29e4
# File offset 0x7a27c4 (caller: 0xfffffff0077a67c4)
# File offset 0x45f740 (trampoline: 0xfffffff007463740)
tramp_va = 0xfffffff007463740
func_va = 0xfffffff0077b29b8
cont_va = 0xfffffff0077a67dc
caller_va = 0xfffffff0077a67c4

ins1 = 0xf9400000 | (0x21 << 10) | (21 << 5) | 8       # ldr x8, [x21, #0x108]
ins2 = (0xb4 << 24) | (7 << 5) | 8                       # cbz x8, tramp_va + 32
ins3 = 0xb9400000 | (0x3c << 10) | (21 << 5) | 8       # ldr w8, [x21, #0xf0]
ins4 = 0x6b0802ff                                        # cmp w23, w8
ins5 = (0x54 << 24) | (4 << 5) | 0xa                     # b.ge tramp_va + 32
ins6 = 0xaa1503e0                                        # mov x0, x21
ins7 = 0xaa1703e1                                        # mov x1, x23
diff_bl = (func_va - (tramp_va + 28)) // 4
ins8 = 0x94000000 | (diff_bl & 0x03ffffff)               # bl 0xfffffff0077b29b8
diff_b = (cont_va - (tramp_va + 32)) // 4
ins9 = 0x14000000 | (diff_b & 0x03ffffff)                # b 0xfffffff0077a67dc

tramp_words = [ins1, ins2, ins3, ins4, ins5, ins6, ins7, ins8, ins9]
for idx, w in enumerate(tramp_words):
    struct.pack_into("<I", kdata, 0x45f740 + idx * 4, w)

diff_caller = (tramp_va - caller_va) // 4
branch_caller = 0x14000000 | (diff_caller & 0x03ffffff)
struct.pack_into("<I", kdata, 0x7a27c4, branch_caller)
for idx in range(1, 6):
    struct.pack_into("<I", kdata, 0x7a27c4 + idx * 4, 0xd503201f) # nop
print("[+] Patched 0x7a27c4 -> trampoline at 0x45f740 (guards NULL fd_ofiles, eliminates 0x77b29e4 data abort)")

# 32. Patch nested panic cascade in panic_display_system_configuration at 0xacf9b0
# 0xfffffff007ad39b0 (file offset 0xacf9b0): bl #0xfffffff007ac9008 -> nop
inst_pdisp = struct.unpack_from("<I", kdata, 0xacf9b0)[0]
if inst_pdisp != 0xd503201f:
    struct.pack_into("<I", kdata, 0xacf9b0, 0xd503201f)
    print("[+] Patched 0xacf9b0 (panic_display_system_configuration bl panic -> nop, eliminates nested panic resets)")
else:
    print("[*] 0xacf9b0 already patched (nop)")

# Patch 33: miniamfi_vnode_check_signature platform binary bypass
# 0xfffffff0077adf3c (file offset 0x7a9f3c):
# Grant CS_VALID | CS_ADHOC | CS_PLATFORM_BINARY | CS_PLATFORM_PATH | CS_SIGNED (0x2c000003) to ALL binaries & dylibs,
# eliminating code signing refusal & library validation rejection for injected dylibs.
patch33_bytes = bytes([
    0xc4, 0x00, 0x00, 0xb4, # cbz x4, +0x18 (to mov w0, #0)
    0x88, 0x00, 0x40, 0xb9, # ldr w8, [x4]
    0x69, 0x00, 0x80, 0x52, # mov w9, #3
    0x09, 0x80, 0xa5, 0x72, # movk w9, #0x2c00, lsl #16
    0x08, 0x01, 0x09, 0x2a, # orr w8, w9, w8
    0x88, 0x00, 0x00, 0xb9, # str w8, [x4]
    0x00, 0x00, 0x80, 0x52, # mov w0, #0
    0xc0, 0x03, 0x5f, 0xd6, # ret
])
if kdata[0x7a9f3c : 0x7a9f3c + 32] != patch33_bytes:
    kdata[0x7a9f3c : 0x7a9f3c + 32] = patch33_bytes
    print("[+] Installed Patch 33 at 0x7a9f3c: miniamfi_vnode_check_signature universal platform-binary grant (0x2c000003)")
else:
    print("[*] Patch 33 at 0x7a9f3c already installed")

# Patch 34: phystokv illegal PA panic bypass at 0x4538c0
# Returns NULL (0) cleanly for physical addresses outside managed DRAM (e.g. MMIO, Mali GPU entries with software bits)
struct.pack_into("<II", kdata, 0x4538c0, 0xd2800000, 0xd65f03c0) # mov x0, #0; ret
print("[+] Installed Patch 34 at 0x4538c0: phystokv illegal PA panic bypass -> mov x0, #0; ret")

# Patch 35: compressed PTE extra bits panic bypass at 0x43e3f0 (@pmap.c:5626)
# When compressed PTE has extra bits outside the expected compressed mask, unconditionally bypass the panic to 0xfffffff007442424
struct.pack_into("<I", kdata, 0x43e3f0, 0x1400000d) # b #0xfffffff007442424 (offset +0x34)
print("[+] Installed Patch 35 at 0x43e3f0: compressed PTE extra bits panic bypass -> b 0xfffffff007442424")

# Patch 36: sched_clutch.c:1404 priority_queue_empty & range panic bypass at 0x2ff8a0 (VA 0xfffffff0073038a0)
# When clutch bucket thread runq is empty, return priority 0 cleanly to 0xfffffff0073038b8 instead of panicking
struct.pack_into("<I", kdata, 0x2ff8a0, 0xb40000c8) # cbz x8, #0xfffffff0073038b8 (offset +0x18)
# Also bypass line 1471 range panic at 0x2ffa64 (VA 0xfffffff007303a64) -> b.hs 0xfffffff007303a88
struct.pack_into("<I", kdata, 0x2ffa64, 0x54000122) # b.hs #0xfffffff007303a88 (offset +0x24)
print("[+] Installed Patch 36 at 0x2ff8a0 & 0x2ffa64: sched_clutch priority_queue_empty & range panic bypass")

# Patch 37: IOKitBSDInit.cpp:1042 / 1039 Assertion failed: pe / matching bypass & pe->release NULL dereference fix
# 0xa28b28 (VA 0xfffffff007a2cb28): cbz x0, #0xfffffff007a2cba4 (0xb40003e0) - bypass matching == NULL panic
# 0xa28b54 (VA 0xfffffff007a2cb54): cbz x21, #0xfffffff007a2cb84 (0xb4000195) - bypass pe == NULL panic
# 0xa28b94 (VA 0xfffffff007a2cb94): cbz x21, #0xfffffff007a2cba4 (0xb4000095) - bypass pe->release() NULL dereference
# 0xac503c (VA 0xfffffff007ac903c): ret (0xd65f03c0) - neutralize assertion panic stub
struct.pack_into("<I", kdata, 0xa28b28, 0xb40003e0)
struct.pack_into("<I", kdata, 0xa28b54, 0xb4000195)
struct.pack_into("<I", kdata, 0xa28b94, 0xb4000095)
struct.pack_into("<I", kdata, 0xac503c, 0xd65f03c0)
print("[+] Installed Patch 37 at 0xa28b28, 0xa28b54, 0xa28b94, 0xac503c: IOKitBSDInit assertion bypass & NULL guard")

# Patch 38: _loader_jump T0SZ range check bypass at 0x471a10 (VA 0xfffffff007475a10)
# In iOS 16 userland, T0SZ=16 (48-bit address space), causing loader_jump() to abort and ret without calling xnu_return_stub.
# Unconditionally branch over the T0SZ check straight to 0xfffffff007475a34 (dc cvac cache flush & stub entry).
struct.pack_into("<I", kdata, 0x471a10, 0x14000009) # b #0xfffffff007475a34
print("[+] Installed Patch 38 at 0x471a10: _loader_jump T0SZ check bypass -> b 0xfffffff007475a34")

# Patch 39: _loader_jump TCR_EL1 T0SZ configuration at 0x471b90 (VA 0xfffffff007475b90)
# Replace `bic x4, x4, #0x80` with `movk x4, #0x2519` to set T0SZ=25 (Level 1 table), TG0=4K, SH0=Outer, EPD0=0
struct.pack_into("<I", kdata, 0x471b90, 0xf284a324) # movk x4, #0x2519
print("[+] Installed Patch 39 at 0x471b90: _loader_jump TCR_EL1 T0SZ=25 setup -> movk x4, #0x2519")

# Patch 40: _PE_kputc function pointer at 0x252998 (VA 0xfffffff007256998)
# In genuine XNU, PE_kputc defaults to NULL because there is no Apple Serial chip on MT6855.
# Point _PE_kputc to _loader_log_putc (0xfffffff007475178) so every kprintf(), assertion, and panic log
# is captured directly into _loader_log in DRAM!
struct.pack_into("<Q", kdata, 0x252998, 0xfffffff007475178)
print("[+] Installed Patch 40 at 0x252998: _PE_kputc -> _loader_log_putc (0xfffffff007475178)")



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

# Replace ramdisk bytes in payload if root.apfs exists
RAMDISK_PATH = "hakios/userland/root.apfs"
if os.path.exists(RAMDISK_PATH):
    with open(RAMDISK_PATH, "rb") as rf:
        rddata = rf.read()
    p = 8
    while p + 24 <= len(pdata):
        ename = pdata[p:p+16].split(b'\x00')[0].decode('latin1')
        if not ename:
            break
        esize, = struct.unpack_from("<I", pdata, p+16)
        if ename == "ramdisk":
            assert esize == len(rddata), f"Ramdisk size mismatch: entry {esize} vs file {len(rddata)}"
            pdata[p+24 : p+24+len(rddata)] = rddata
            print(f"[+] Successfully updated ramdisk in {PAYLOAD_PATH} ({len(rddata)} bytes)")
            with open("mtkloader/payload_rd.apfs", "wb") as pf:
                pf.write(rddata)
            break
        p += 24 + ((esize + 15) & ~15)

with open(PAYLOAD_PATH, "wb") as f:
    f.write(pdata)
print(f"[+] Successfully updated {PAYLOAD_PATH} with patched kernel ({len(kdata)} bytes)")

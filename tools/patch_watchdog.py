#!/usr/bin/env python3
"""
Patch Apple XNU kernel (kernel_patched) and payload.bin:
1. In _hv_wdt_pet_init: Map MediaTek TOPRGU watchdog registers (0x1c007000) via _ml_io_map.
2. In _gic_irq_handler (VTIMER interrupt, intid 27): Hook rtclock_intr to pet TOPRGU on every timer tick!
3. In _hv_wdt_pet: Also write TOPRGU_RESTART_KEY (0x1971) to TOPRGU_RESTART (0x1c007008).
4. In _hv_wdt_pet: Reduce pet interval from 10s to 2s.
"""
import struct
import os

KERNEL_PATH = "mtkloader/kernel_patched"
PAYLOAD_PATH = "mtkloader/payload.bin"

with open(KERNEL_PATH, "rb") as f:
    kdata = bytearray(f.read())

off = 32
ncmds = struct.unpack("<I", kdata[16:20])[0]

def vm_to_foff(target_va):
    p = 32
    for _ in range(ncmds):
        cmd, cmdsize = struct.unpack("<II", kdata[p:p+8])
        if cmd == 0x19:
            segname, vmaddr, vmsize, fileoff, filesize = struct.unpack("<16sQQQQ", kdata[p+8:p+56])
            if vmaddr <= target_va < vmaddr + vmsize:
                return fileoff + (target_va - vmaddr)
        p += cmdsize
    return None

foff_pet_init = vm_to_foff(0xfffffff007ad3d2c)
foff_pet = vm_to_foff(0xfffffff00747609c)
foff_gic_irq = vm_to_foff(0xfffffff0074779d4)
foff_stub = vm_to_foff(0xfffffff007463704)

assert foff_pet_init is not None, "foff_pet_init not found"
assert foff_pet is not None, "foff_pet not found"
assert foff_gic_irq is not None, "foff_gic_irq not found"
assert foff_stub is not None, "foff_stub not found"

print(f"[+] Found _hv_wdt_pet_init at file offset {hex(foff_pet_init)}")
print(f"[+] Found _hv_wdt_pet at file offset {hex(foff_pet)}")
print(f"[+] Found _gic_irq_handler at file offset {hex(foff_gic_irq)}")
print(f"[+] Found stub location at file offset {hex(foff_stub)}")

# 1. Patch _hv_wdt_pet_init to map 0x1c007000 and store in _hv_wdt_enabled
init_patch = struct.pack("<6I",
    0xd28e0000, # mov x0, #0x7000
    0xf2a38000, # movk x0, #0x1c00, lsl #16 -> x0 = 0x1c007000
    0xd2820001, # mov x1, #0x1000
    0x97e64d1e, # bl _ml_io_map
    0x90001521, # adrp x1, _hv_wdt_enabled
    0xf9000c20, # str x0, [x1, #0x18]
)
kdata[foff_pet_init + 0x08 : foff_pet_init + 0x08 + len(init_patch)] = init_patch
print("[+] Patched _hv_wdt_pet_init with _ml_io_map(0x1c007000, 0x1000)")

# 2. Patch _gic_irq_handler (+0xc0, 0xfffffff007477a94) to call our vtimer_pet_and_reset stub
# This guarantees that on EVERY VTIMER tick, TOPRGU watchdog is fed,
# and after 4096 ticks (~41s), hardware warm-reset to Android is automatically executed!
va_gic_hook = 0xfffffff0074779d4 + 0xc0
va_stub = 0xfffffff007463704
diff_gic = va_stub - va_gic_hook
imm26_gic = (diff_gic >> 2) & 0x03ffffff
ins_gic = 0x94000000 | imm26_gic
gic_patch = struct.pack("<I", ins_gic)
kdata[foff_gic_irq + 0xc0 : foff_gic_irq + 0xc4] = gic_patch
print(f"[+] Patched _gic_irq_handler VTIMER at {hex(foff_gic_irq + 0xc0)} to bl {hex(va_stub)} (ins: {hex(ins_gic)})")

# 3. Patch interval from 10s to 2s
kdata[foff_pet + 0x1f0 : foff_pet + 0x1f4] = struct.pack("<I", 0x52800040) # mov w0, #2
print("[+] Patched _hv_wdt_pet interval from 10s to 2s")

# 4. Install vtimer_pet_and_reset stub at 0xfffffff007463704
# AAPCS64 compliant leaf stub:
# - PRESERVES x0 (regs pointer) so _rtclock_intr does not crash!
# - Uses scratch w10 for TOPRGU_RESTART_KEY (0x1971)
# - Pets TOPRGU hardware watchdog on every VTIMER tick
# - Calls original _rtclock_intr (0xfffffff00746c828) with pristine x0
# - At 4096 ticks (~41s), triggers TOPRGU_MODE (0x22000043) + TOPRGU_SWRST (0x1209) for clean warm-reset
# - toprgu_warm_reset entry at 0xfffffff007463754 (hooked by _PE_halt_restart)
# - If TOPRGU unmapped (x9 == 0), falls back to PSCI SYSTEM_RESET (smc #0)
pc_bl = 0xfffffff007463704 + 16 * 4
offset = 0xfffffff00746c828 - pc_bl
ins_bl = 0x94000000 | ((offset >> 2) & 0x03ffffff)

stub_code = struct.pack("<33I",
    0xa9be7bfd, # 0:  stp  x29, x30, [sp, #-32]!
    0xf9000bf3, # 1:  str  x19, [sp, #16]
    0xf90007e0, # 2:  str  x0, [sp, #8] (PRESERVE x0: arm_saved_state_t pointer!)
    0x910003fd, # 3:  mov  x29, sp
    # Pet logic
    0x900048a8, # 4:  adrp x8, _hv_wdt_enabled (page 0xfffffff007d77000)
    0xf9400d09, # 5:  ldr  x9, [x8, #0x18] (TOPRGU base 0x1c007000 mapped by _hv_wdt_pet_init)
    0xb4000129, # 6:  cbz  x9, 2f (if not mapped yet, skip to call _rtclock_intr (+9 ins = +36 bytes))
    0xb9400d02, # 7:  ldr  w2, [x8, #0x0c] (pet counter at safe unused padding offset 0x0c)
    0x11000442, # 8:  add  w2, w2, #1 (counter++)
    0xb9000d02, # 9:  str  w2, [x8, #0x0c] (save updated counter)
    0x7140045f, # 10: cmp  w2, #4096 (4096 ticks @ ~100Hz = ~41s session window)
    0x54000122, # 11: b.hs 1f (jump to 1: toprgu_warm_reset (+9 ins = +36 bytes))
    0x52832e2a, # 12: mov  w10, #0x1971 (TOPRGU_RESTART_KEY in scratch w10!)
    0xb900092a, # 13: str  w10, [x9, #8] (PET HARDWARE WATCHDOG: feeds TOPRGU_RESTART!)
    0xd5033f9f, # 14: dsb  sy
    # 2: Call original _rtclock_intr with restored x0 and return
    0xf94007e0, # 15: ldr  x0, [sp, #8] (RESTORE x0: pristine regs pointer!)
    ins_bl,     # 16: bl   _rtclock_intr (0xfffffff00746c828)
    0xf9400bf3, # 17: ldr  x19, [sp, #16]
    0xa8c27bfd, # 18: ldp  x29, x30, [sp], #32
    0xd65f03c0, # 19: ret
    # 1: toprgu_warm_reset function at 0xfffffff007463754 (called by PE_halt_restart or timed VTIMER)
    0x900048a8, # 20: adrp x8, 0xfffffff007d77000
    0xf9400d09, # 21: ldr  x9, [x8, #0x18] (TOPRGU base)
    0xb40000e9, # 22: cbz  x9, 3f (jump to PSCI fallback if unmapped (+7 ins = +28 bytes))
    0x52800860, # 23: mov  w0, #0x0043
    0x72a44000, # 24: movk w0, #0x2200, lsl #16 (TOPRGU_MODE_KEY | 0x43)
    0xb9000120, # 25: str  w0, [x9, #0x00] (arm TOPRGU_MODE with reset enable!)
    0x52824120, # 26: mov  w0, #0x1209 (TOPRGU_SWRST_KEY)
    0xb9001520, # 27: str  w0, [x9, #0x14] (TOPRGU_SWRST: instant warm reset!)
    0x14000004, # 28: b    4f (spin until hardware resets)
    # 3: PSCI SYSTEM_RESET fallback if TOPRGU base was unmapped
    0xd2800120, # 29: mov  x0, #9
    0xf2b08000, # 30: movk x0, #0x8400, lsl #16 (0x84000009 PSCI SYSTEM_RESET)
    0xd4000003, # 31: smc  #0
    0x14000000  # 32: 4: b 4b (spin)
)
kdata[foff_stub : foff_stub + len(stub_code)] = stub_code
print(f"[+] Installed vtimer_pet_and_reset stub + PE_halt_restart hook at {hex(foff_stub)} (0xfffffff007463704)")

with open(KERNEL_PATH, "wb") as f:
    f.write(kdata)
print(f"[+] Successfully wrote {KERNEL_PATH}")

# 6. Update payload.bin
with open(PAYLOAD_PATH, "rb") as f:
    pdata = bytearray(f.read())

ph_magic, ph_size = struct.unpack_from("<II", pdata, 0)
assert ph_magic == 0x50554e58, "Invalid payload magic"
kname = pdata[8:24].split(b'\x00')[0].decode('latin1')
assert kname == "kernel", f"First entry {kname} != kernel"
ksize, = struct.unpack_from("<I", pdata, 24)
assert ksize == len(kdata), f"Size mismatch: {ksize} vs {len(kdata)}"

pdata[32:32 + len(kdata)] = kdata
with open(PAYLOAD_PATH, "wb") as f:
    f.write(pdata)
print(f"[+] Successfully updated {PAYLOAD_PATH} ({len(pdata)} bytes)")

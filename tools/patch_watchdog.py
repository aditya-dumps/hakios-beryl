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

# 2. Patch _hv_wdt_pet to call our toprgu_pet_and_reset stub
# This feeds TOPRGU_RESTART (0x1971) on EVERY 2s tick to keep MT6855 hardware watchdog alive!
# At 80s (40 pets @ 2s), it writes TOPRGU_SWRST (0x1209) to trigger automated warm-reset to Android.
# Branch to foff_stub (0xfffffff007463704) from foff_pet + 0x20:
pet_patch = struct.pack("<10I",
    0x97ffb592, # bl 0xfffffff007463704 (toprgu_pet_and_reset stub)
    0xd503201f, # nop
    0xd503201f, # nop
    0xd503201f, # nop
    0xd503201f, # nop
    0xd503201f, # nop
    0xd503201f, # nop
    0xd503201f, # nop
    0xd503201f, # nop
    0xd503201f  # nop
)
kdata[foff_pet + 0x20 : foff_pet + 0x20 + len(pet_patch)] = pet_patch
print("[+] Patched _hv_wdt_pet: calls toprgu_pet_and_reset stub (automated 80s reset)")

# 3. Patch interval from 10s to 2s
kdata[foff_pet + 0x1f0 : foff_pet + 0x1f4] = struct.pack("<I", 0x52800040) # mov w0, #2
print("[+] Patched _hv_wdt_pet interval from 10s to 2s")

# 4. Install toprgu_pet_and_reset stub at 0xfffffff007463704
# AAPCS64 compliant leaf stub:
# - Hooks _PE_halt_restart to toprgu_warm_reset so any panic(), reboot(), or auto_reboot warm-resets!
# - Pets TOPRGU hardware watchdog (0x1971) on every 2s tick to keep MT6855 alive
# - At 80s (40 pets @ 2s), triggers TOPRGU_SWRST (0x1209) for clean warm-reset to Android
stub_code = struct.pack("<34I",
    0xa9be7bfd, # 0:  stp  x29, x30, [sp, #-32]!
    0xf9000be3, # 1:  str  x19, [sp, #16]
    0x910003fd, # 2:  mov  x29, sp
    # Hook _PE_halt_restart (0xfffffff007d4dac0) -> toprgu_warm_reset (0xfffffff00746376c)
    0xd000474a, # 3:  adrp x10, 0xfffffff007d4d000
    0x9000000b, # 4:  adrp x11, 0xfffffff007463000
    0x911db16b, # 5:  add  x11, x11, #0x76c (toprgu_warm_reset entry)
    0xf905614b, # 6:  str  x11, [x10, #0xac0] (hook _PE_halt_restart!)
    # Pet TOPRGU
    0x900048a8, # 7:  adrp x8, _hv_wdt_enabled (page 0xfffffff007d77000)
    0xf9400d09, # 8:  ldr  x9, [x8, #0x18] (TOPRGU base 0x1c007000 mapped by _hv_wdt_pet_init)
    0xb40001c9, # 9:  cbz  x9, 2f (if not mapped yet, skip to 2: exit (+14 ins = +56 bytes))
    0xb9400d02, # 10: ldr  w2, [x8, #0x0c] (pet counter at safe unused padding offset 0x0c)
    0x11000442, # 11: add  w2, w2, #1 (counter++)
    0xb9000d02, # 12: str  w2, [x8, #0x0c] (save updated counter)
    0x7100a05f, # 13: cmp  w2, #40 (40 pets @ 2s = 80s)
    0x540000a2, # 14: b.hs 1f (jump to 1: reset if >= 40 (+5 ins = +20 bytes))
    0x52832e20, # 15: mov  w0, #0x1971 (TOPRGU_RESTART_KEY)
    0xb9000920, # 16: str  w0, [x9, #8] (PET HARDWARE WATCHDOG: feeds TOPRGU_RESTART!)
    0xd5033fdf, # 17: dsb  sy
    0x14000005, # 18: b    2f (skip reset to 2: exit (+5 ins = +20 bytes))
    # 1: Timed Warm Reset (at 80s)
    0x52824120, # 19: mov  w0, #0x1209 (TOPRGU_SWRST_KEY for clean hardware warm reset)
    0xb9001520, # 20: str  w0, [x9, #0x14] (TOPRGU_SWRST: triggers immediate warm reset to Android)
    0xd5033fdf, # 21: dsb  sy
    0xd5033f3f, # 22: isb
    # 2: Exit
    0xf9400be3, # 23: ldr  x19, [sp, #16]
    0xa8c27bfd, # 24: ldp  x29, x30, [sp], #32
    0xd65f03c0, # 25: ret
    # toprgu_warm_reset function at 0xfffffff00746376c (called by PE_halt_restart on any panic/reboot)
    0x900048a8, # 26: adrp x8, 0xfffffff007d77000
    0xf9400d09, # 27: ldr  x9, [x8, #0x18] (TOPRGU base)
    0xb40000a9, # 28: cbz  x9, 3f (wait if not mapped)
    0x52824120, # 29: mov  w0, #0x1209 (TOPRGU_SWRST_KEY)
    0xb9001520, # 30: str  w0, [x9, #0x14] (TOPRGU_SWRST: warm reset!)
    0xd5033fdf, # 31: dsb  sy
    0xd5033f3f, # 32: isb
    0x14000000, # 33: 3: b 3b (spin until hardware resets)
)
kdata[foff_stub : foff_stub + len(stub_code)] = stub_code
print(f"[+] Installed toprgu_pet_and_reset stub + PE_halt_restart hook at {hex(foff_stub)} (0xfffffff007463704)")

# 5. Restore original _gic_irq_handler (+0xc0): bl _rtclock_intr (0x97ffd365)
# DO NOT pet TOPRGU in the timer interrupt! Otherwise, any hang/freeze on the Apple logo
# will never trigger the 15-second hardware watchdog reset.
kdata[foff_gic_irq + 0xc0 : foff_gic_irq + 0xc4] = struct.pack("<I", 0x97ffd365) # bl _rtclock_intr
print(f"[+] Restored _gic_irq_handler VTIMER at {hex(foff_gic_irq + 0xc0)} to original bl _rtclock_intr")

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

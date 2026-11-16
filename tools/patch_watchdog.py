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

# 2. Patch _hv_wdt_pet to restart TOPRGU
pet_patch = struct.pack("<10I",
    0xb0004808, # adrp x8, _hv_wdt_enabled
    0xf9400d08, # ldr x8, [x8, #0x18]
    0xb40000e8, # cbz x8, +0x1c (skip to +48)
    0x52832e20, # mov w0, #0x1971 (TOPRGU_RESTART_KEY)
    0xb9000900, # str w0, [x8, #8] (TOPRGU_RESTART)
    0xd5033fdf, # dsb sy
    0xd503201f, # nop
    0xd503201f, # nop
    0xd503201f, # nop
    0xd503201f, # nop
)
kdata[foff_pet + 0x20 : foff_pet + 0x20 + len(pet_patch)] = pet_patch
print("[+] Patched _hv_wdt_pet to pet MediaTek TOPRGU (0x1971 -> 0x1c007008)")

# 3. Patch interval from 10s to 2s
kdata[foff_pet + 0x1f0 : foff_pet + 0x1f4] = struct.pack("<I", 0x52800040) # mov w0, #2
print("[+] Patched _hv_wdt_pet interval from 10s to 2s")

# 4. Install toprgu_pet_and_rtclock stub at 0xfffffff007463704
stub_code = struct.pack("<11I",
    0xa9bf7bfd, # stp x29, x30, [sp, #-16]!
    0x910003fd, # mov x29, sp
    0x94002447, # bl _rtclock_intr
    0x900048a8, # adrp x8, _hv_wdt_enabled
    0xf9400d08, # ldr x8, [x8, #0x18]
    0xb4000088, # cbz x8, 1f (branch to ldp)
    0x52832e20, # mov w0, #0x1971
    0xb9000900, # str w0, [x8, #8]
    0xd5033fdf, # dsb sy
    0xa8c17bfd, # 1: ldp x29, x30, [sp], #16
    0xd65f03c0, # ret
)
kdata[foff_stub : foff_stub + len(stub_code)] = stub_code
print(f"[+] Installed toprgu_pet_and_rtclock at {hex(foff_stub)} (0xfffffff007463704)")

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

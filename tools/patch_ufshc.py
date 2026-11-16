#!/usr/bin/env python3
import struct
import sys

KERNEL_PATH = "mtkloader/kernel_patched"
PAYLOAD_PATH = "mtkloader/payload.bin"

with open(KERNEL_PATH, "rb") as f:
    kdata = bytearray(f.read())

# Check offset 0x4caee8 (mov w21, 0x1d84000)
old_pat1 = struct.pack("<II", 0x52880015, 0x72a03b15)
new_pat1 = struct.pack("<II", 0x52800015, 0x72a22575)

assert kdata[0x4caee8:0x4caee8 + 8] in (old_pat1, new_pat1), f"Unexpected bytes at 0x4caee8: {kdata[0x4caee8:0x4caee8+8].hex()}"
if kdata[0x4caee8:0x4caee8 + 8] == old_pat1:
    kdata[0x4caee8:0x4caee8 + 8] = new_pat1
    print("[+] Patched 0x4caee8 (UFSHC_PHYS check 0x1d84000 -> 0x112b0000)")
else:
    print("[*] 0x4caee8 already patched")

# Check offset 0x4cb01c (mov w0, 0x1d84000 for ml_io_map)
old_pat2 = struct.pack("<II", 0x52880000, 0x72a03b00)
new_pat2 = struct.pack("<II", 0x52800000, 0x72a22560)

assert kdata[0x4cb01c:0x4cb01c + 8] in (old_pat2, new_pat2), f"Unexpected bytes at 0x4cb01c: {kdata[0x4cb01c:0x4cb01c+8].hex()}"
if kdata[0x4cb01c:0x4cb01c + 8] == old_pat2:
    kdata[0x4cb01c:0x4cb01c + 8] = new_pat2
    print("[+] Patched 0x4cb01c (UFSHC_PHYS map 0x1d84000 -> 0x112b0000)")
else:
    print("[*] 0x4cb01c already patched")

with open(KERNEL_PATH, "wb") as f:
    f.write(kdata)
print(f"[+] Saved patched kernel to {KERNEL_PATH}")

# Update payload.bin
with open(PAYLOAD_PATH, "rb") as f:
    pdata = bytearray(f.read())

ph_magic, ph_size = struct.unpack_from("<II", pdata, 0)
assert ph_magic == 0x50554e58, "Invalid payload magic"

kname = pdata[8:24].split(b'\x00')[0].decode('latin1')
assert kname == "kernel", f"First entry is {kname}, expected kernel"
ksize, = struct.unpack_from("<I", pdata, 24)
assert ksize == len(kdata), f"Size mismatch: {ksize} vs {len(kdata)}"

pdata[32:32 + len(kdata)] = kdata

with open(PAYLOAD_PATH, "wb") as f:
    f.write(pdata)
print(f"[+] Successfully updated {PAYLOAD_PATH} with MTK UFSHC patched kernel ({len(kdata)} bytes)")

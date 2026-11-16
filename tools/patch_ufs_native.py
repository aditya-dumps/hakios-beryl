#!/usr/bin/env python3
import struct
import sys

KERNEL_PATH = "mtkloader/kernel_patched"
PAYLOAD_PATH = "mtkloader/payload.bin"

with open(KERNEL_PATH, "rb") as f:
    kdata = bytearray(f.read())

NOP = struct.pack("<I", 0xd503201f)

# 1. Patch off1 (0x4c63c4): eliminate _ufs_read_mailbox and EFI PART check
off1 = 0x4c63c4
expected_off1 = bytes.fromhex("14060094200a0035e00318aa21dfffb02130019102018052a151fd9760090035")
if kdata[off1:off1+32] == expected_off1:
    kdata[off1:off1+32] = NOP * 8
    print("[+] Patched 0x4c63c4: replaced _ufs_read_mailbox and memcmp with 8 NOPs")
elif kdata[off1:off1+32] == NOP * 8:
    print("[*] 0x4c63c4 already patched")
else:
    raise RuntimeError(f"Unexpected bytes at 0x4c63c4: {kdata[off1:off1+32].hex()}")

# 2. Patch off2 (0x4c64e0): eliminate memcmp comparing native read with mailbox buffer
off2 = 0x4c64e0
expected_off2 = bytes.fromhex("6051fd97c00b0035")
if kdata[off2:off2+8] == expected_off2:
    kdata[off2:off2+8] = NOP * 2
    print("[+] Patched 0x4c64e0: replaced compare memcmp with 2 NOPs")
elif kdata[off2:off2+8] == NOP * 2:
    print("[*] 0x4c64e0 already patched")
else:
    raise RuntimeError(f"Unexpected bytes at 0x4c64e0: {kdata[off2:off2+8].hex()}")

with open(KERNEL_PATH, "wb") as f:
    f.write(kdata)
print(f"[+] Saved patched kernel to {KERNEL_PATH}")

# 3. Update payload.bin
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
print(f"[+] Successfully updated {PAYLOAD_PATH} with native UFS direct mapping kernel ({len(kdata)} bytes)")

#!/usr/bin/env python3
"""
Patch prebuilt init binary:
1. 0x4a40: cbz w0 -> b #0x100004aac (0x1400001b) [cryptex success]
2. 0x1498: cbz w0 -> nop (0xd503201f) [LaunchDaemons bind bypass]
3. 0x14bc: cbz w0 -> nop (0xd503201f) [NanoLaunchDaemons bind bypass]
4. 0x14e0: cbz w0 -> nop (0xd503201f) [LaunchAngels bind bypass]
5. 0x1510: cbz w0 -> nop (0xd503201f) [xpc bind bypass]
6. 0x4530: adr x0, #0x100006b1c -> adr x0, #0x100006b0a (0x50012ec0) [execute patched launchd.ios]
7. 0x6b0a: write "/redwood/sbin/launchd.ios\0" [path to patched launchd.ios in redwood APFS]
"""
import struct
import os

INIT_PATHS = [
    "hakios/prebuilt/userland/init",
    "hakios/userland/root/sbin/init",
    "hakios/userland/root/sbin/launchd"
]

def patch_init(path):
    if not os.path.exists(path):
        return
    with open(path, "rb") as f:
        idata = bytearray(f.read())

    # 1. Cryptex bypass at 0x4a40
    val_4a40, = struct.unpack_from("<I", idata, 0x4a40)
    if val_4a40 == 0x34000360:
        struct.pack_into("<I", idata, 0x4a40, 0x1400001b)
        print(f"[+] {path}: Patched 0x4a40 (cryptex cbz -> b success)")

    # 1b. Synthetic /redwood and synthetic_dir bypass (0x1448 & 0x488c)
    val_1448, = struct.unpack_from("<I", idata, 0x1448)
    if val_1448 == 0x350000c0:
        struct.pack_into("<I", idata, 0x1448, 0x14000006) # b #0x100001460 (always succeed synthetic /redwood)
        print(f"[+] {path}: Patched 0x1448 (synthetic /redwood check -> b success)")

    val_488c, = struct.unpack_from("<I", idata, 0x488c)
    if val_488c == 0x34000120:
        struct.pack_into("<I", idata, 0x488c, 0x14000009) # b #0x1000048b0 (always return success from synthetic_dir)
        print(f"[+] {path}: Patched 0x488c (synthetic_dir -> b clean success)")

    # 2. LaunchDaemons bypass at 0x1498
    val_1498, = struct.unpack_from("<I", idata, 0x1498)
    if val_1498 == 0x34000440:
        struct.pack_into("<I", idata, 0x1498, 0xd503201f)
        print(f"[+] {path}: Patched 0x1498 (LaunchDaemons cbz -> nop)")

    # 3. NanoLaunchDaemons bypass at 0x14bc
    val_14bc, = struct.unpack_from("<I", idata, 0x14bc)
    if val_14bc == 0x34000320:
        struct.pack_into("<I", idata, 0x14bc, 0xd503201f)
        print(f"[+] {path}: Patched 0x14bc (NanoLaunchDaemons cbz -> nop)")

    # 4. LaunchAngels bypass at 0x14e0
    val_14e0, = struct.unpack_from("<I", idata, 0x14e0)
    if val_14e0 == 0x34000200:
        struct.pack_into("<I", idata, 0x14e0, 0xd503201f)
        print(f"[+] {path}: Patched 0x14e0 (LaunchAngels cbz -> nop)")

    # 5. xpc bypass at 0x1510
    val_1510, = struct.unpack_from("<I", idata, 0x1510)
    if val_1510 == 0x340000e0:
        struct.pack_into("<I", idata, 0x1510, 0xd503201f)
        print(f"[+] {path}: Patched 0x1510 (xpc cbz -> nop)")

    # 6. launchd executable selection at 0x4530
    val_4530, = struct.unpack_from("<I", idata, 0x4530)
    if val_4530 == 0x10012f60:
        struct.pack_into("<I", idata, 0x4530, 0x50012ec0)
        print(f"[+] {path}: Patched 0x4530 (adr x0, #0x100006b0a)")

    # 7. launchd path string at 0x6b0a
    new_str = b"/redwood/sbin/launchd.ios\x00"
    if idata[0x6b0a:0x6b0a + len(new_str)] != new_str:
        idata[0x6b0a:0x6b0a + len(new_str)] = new_str
        print(f"[+] {path}: Patched string at 0x6b0a -> {new_str.decode('latin1')}")

    with open(path, "wb") as f:
        f.write(idata)

for p in INIT_PATHS:
    patch_init(p)

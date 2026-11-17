#!/usr/bin/env python3
"""
Patch genuine Apple iOS 16.5 launchd.ios binary:
1. Offset 0x2025c: Neutralize state transition assertion (b.ne 0x100020278 -> b 0x100020278: 0x14000007).
   When POSIXSpawnType is set to App (to elide xpcproxy and prevent dynamic linker PC alignment crashes),
   launchd speculatively transitions the job state directly from state 2 (spawning) to state 5 (running).
   The stock sanity check at 0x100020258-0x100020274 asserts that state 2 can only transition to state 3 or 0.
   Failing this assertion invokes abort(), terminating PID 1 and triggering a kernel panic.
   Patching 0x2025c unconditionally jumps to 0x100020278, storing the new state cleanly without aborting.

2. Embedded Job Search Paths (offset ~0x60c3b):
   Redirect /System/Library/LaunchDaemons -> /redwood/LaunchDaemons///////
   and empty out LaunchAngels, NanoLaunchDaemons, DeveloperModeLaunchDaemons.
   This ensures launchd reads our sanitized jobs from /redwood/LaunchDaemons/ and never loads broken/crashing jobs.
"""
import struct
import os

LAUNCHD_PATHS = [
    "hakios/userland/root/sbin/launchd.ios",
    "hakios/userland/sysroot/sbin/launchd.ios"
]

REPLACEMENTS = [
    (b'<string>/System/Library/LaunchDaemons</string>', b'<string>/redwood/LaunchDaemons///////</string>'),
    (b'<string>/System/Library/LaunchAngels</string>', b'<string>/redwood/empty//////////////</string>'),
    (b'<string>/System/Library/NanoLaunchDaemons</string>', b'<string>/redwood/empty///////////////////</string>'),
    (b'<string>/AppleInternal/Library/LaunchDaemons</string>', b'<string>/redwood/empty//////////////////////</string>'),
    (b'<string>/AppleInternal/Library/LaunchAngels</string>', b'<string>/redwood/empty/////////////////////</string>'),
    (b'<string>/System/Library/NanoLaunchDaemonsAltAccount</string>', b'<string>/redwood/empty/////////////////////////////</string>'),
    (b'<string>/System/Library/DeveloperModeLaunchDaemons</string>', b'<string>/redwood/empty////////////////////////////</string>')
]

def patch_file(path):
    if not os.path.exists(path):
        return
    with open(path, "rb") as f:
        data = bytearray(f.read())

    # 1. State transition assertion bypass (0x2025c)
    val_2025c, = struct.unpack_from("<I", data, 0x2025c)
    if val_2025c == 0x540000e1: # b.ne #0x100020278
        struct.pack_into("<I", data, 0x2025c, 0x14000007) # b #0x100020278
        print(f"[+] Patched {path} at 0x2025c (b.ne -> b #0x100020278: neutralized state transition assert)")
    elif val_2025c == 0x14000007:
        print(f"[*] {path} at 0x2025c already patched (0x14000007)")
    else:
        print(f"[!] Warning: {path} at 0x2025c unexpected value: {hex(val_2025c)}")

    # 2. Environment variable filter bypass (0x167dc & 0x53a8)
    # 0x167dc: is_env_variable_restricted() -> return 0 (not restricted)
    struct.pack_into("<II", data, 0x167dc, 0x52800000, 0xd65f03c0) # mov w0, #0; ret
    print(f"[+] Patched {path} at 0x167dc (mov w0, #0; ret: allow DYLD_INSERT_LIBRARIES)")
    # 0x53a8: cbz w0, #0x53bc -> b #0x53bc
    struct.pack_into("<I", data, 0x53a8, 0x14000005) # b #0x1000053bc
    print(f"[+] Patched {path} at 0x53a8 (b #0x1000053bc: bypass disallow logging)")

    # 3. Persona lookup bypass (0x2a758)
    # 0x2a758: kpersona_find_by_type wrapper -> return 0 (default system persona)
    struct.pack_into("<II", data, 0x2a758, 0x52800000, 0xd65f03c0) # mov w0, #0; ret
    print(f"[+] Patched {path} at 0x2a758 (mov w0, #0; ret: default persona 0, bypass No matching personas error)")

    # 4. Spawn precondition bypass (0x26154)
    # 0x26154: job_can_spawn() -> return 0 (immediate spawn authorized, bypasses 'domain in on-demand-only mode')
    struct.pack_into("<II", data, 0x26154, 0x52800000, 0xd65f03c0) # mov w0, #0; ret
    print(f"[+] Patched {path} at 0x26154 (mov w0, #0; ret: authorize immediate daemon spawn, eliminate on-demand hold)")

    # 5. Neutralize all 'will-spawn received on active service' / out-of-order aborts
    # 0x25db0: cbnz w8, #0x1000260c0 -> nop (0xd503201f)
    struct.pack_into("<I", data, 0x25db0, 0xd503201f)
    print(f"[+] Patched {path} at 0x25db0 (nop: eliminate active service will-spawn branch)")

    # 0x25db8: tbnz w8, #0, #0x1000260cc -> nop (0xd503201f)
    struct.pack_into("<I", data, 0x25db8, 0xd503201f)
    print(f"[+] Patched {path} at 0x25db8 (nop: eliminate multiple will-spawn branch)")

    # 0x25fe0: cbz w0, #0x1000260bc -> b #0x100025ff4 (0x14000005)
    struct.pack_into("<I", data, 0x25fe0, 0x14000005)
    print(f"[+] Patched {path} at 0x25fe0 (b #0x100025ff4: bypass will-spawn on active service abort)")

    # 0x260bc, 0x260c0, 0x260cc, 0x260d8: Redirect all crash entry points to epilogue (0x1000260a8)
    struct.pack_into("<I", data, 0x260bc, 0x17fffffb) # b #0x1000260a8
    struct.pack_into("<I", data, 0x260c0, 0x17fffffa) # b #0x1000260a8
    struct.pack_into("<I", data, 0x260cc, 0x17fffff7) # b #0x1000260a8
    struct.pack_into("<I", data, 0x260d8, 0x17fffff4) # b #0x1000260a8
    print(f"[+] Patched {path} at 0x260bc-0x260d8 (redirect crash block to clean epilogue ret)")

    # 6. Neutralize socket watch & ignore aborts (0x18af8-0x18b08, 0x18c68-0x18c78, 0x18c98-0x18c9c, 0x18d18-0x18d2c)
    # Socket Watch: epilogue at 0x100018c44
    struct.pack_into("<I", data, 0x18af8, 0x37400a68) # tbnz w8, #8 -> 0x100018c44
    struct.pack_into("<I", data, 0x18afc, 0x37380a48) # tbnz w8, #7 -> 0x100018c44
    struct.pack_into("<I", data, 0x18c68, 0x17fffff7) # b #0x100018c44
    struct.pack_into("<I", data, 0x18c6c, 0x17fffff6) # b #0x100018c44
    struct.pack_into("<I", data, 0x18c78, 0x17fffff3) # b #0x100018c44

    # Socket Ignore: epilogue at 0x100018d0c
    struct.pack_into("<I", data, 0x18c98, 0x364003a8) # tbz w8, #8 -> 0x100018d0c (neutralize attempt to ignore socket already ignored)
    struct.pack_into("<I", data, 0x18c9c, 0x37380388) # tbnz w8, #7 -> 0x100018d0c (neutralize attempt to ignore canceled socket)
    struct.pack_into("<I", data, 0x18d18, 0x17fffffd) # b #0x100018d0c
    struct.pack_into("<I", data, 0x18d20, 0x17fffffb) # b #0x100018d0c
    struct.pack_into("<I", data, 0x18d2c, 0x17fffff8) # b #0x100018d0c
    print(f"[+] Patched {path} at 0x18af8-0x18d2c (neutralize socket watch & ignore aborts -> clean ret)")

    # 7. Neutralize endpoint watch & ignore aborts (0x40b9c-0x40c3c, 0x40dfc & 0x40e38-0x40e5c)
    # Endpoint Watch: epilogue at 0x100040c0c
    struct.pack_into("<I", data, 0x40b9c, 0x37180388) # tbnz w8, #3 -> 0x100040c0c
    struct.pack_into("<I", data, 0x40ba0, 0x37080368) # tbnz w8, #1 -> 0x100040c0c
    struct.pack_into("<I", data, 0x40ba4, 0x37000348) # tbnz w8, #0 -> 0x100040c0c
    struct.pack_into("<I", data, 0x40c18, 0x17fffffd) # b #0x100040c0c
    struct.pack_into("<I", data, 0x40c24, 0x17fffffa) # b #0x100040c0c
    struct.pack_into("<I", data, 0x40c30, 0x17fffff7) # b #0x100040c0c
    struct.pack_into("<I", data, 0x40c3c, 0x17fffff4) # b #0x100040c0c

    # Endpoint Ignore: epilogue at 0x100040e28
    struct.pack_into("<I", data, 0x40dfc, 0x36080168) # tbz w8, #1 -> 0x100040e28
    struct.pack_into("<I", data, 0x40e38, 0x17fffffc) # b #0x100040e28
    struct.pack_into("<I", data, 0x40e44, 0x17fffff9) # b #0x100040e28
    struct.pack_into("<I", data, 0x40e50, 0x17fffff6) # b #0x100040e28 (attempt to ignore endpoint that is already ignored)
    struct.pack_into("<I", data, 0x40e5c, 0x17fffff3) # b #0x100040e28
    print(f"[+] Patched {path} at 0x40b9c-0x40e5c (neutralize endpoint watch & ignore aborts -> clean ret)")

    # 8. Neutralize memorystatus_control assertion at offset 55700 (0xd97c)
    # 0xd97c: cbnz w0, #0x10000d98c -> nop (0xd503201f)
    struct.pack_into("<I", data, 0xd97c, 0xd503201f)
    print(f"[+] Patched {path} at 0xd97c (nop: eliminate memorystatus_control assertion failure)")

    # 9. Neutralize 'Unable to record system event' error spam (0x3b42c)
    # 0x3b42c: cbz w0, #0x10003b458 -> b #0x10003b458 (0x1400000b)
    struct.pack_into("<I", data, 0x3b42c, 0x1400000b)
    print(f"[+] Patched {path} at 0x3b42c (b #0x10003b458: suppress record_system_event error spam)")

    # 10. Redirect embedded search paths
    for src, dst in REPLACEMENTS:
        assert len(src) == len(dst)
        idx = data.find(src)
        if idx != -1:
            data[idx:idx + len(dst)] = dst
            print(f"[+] {path}: Redirected {src[8:28]}... -> {dst[8:28]}...")

    with open(path, "wb") as f:
        f.write(data)

for p in LAUNCHD_PATHS:
    patch_file(p)

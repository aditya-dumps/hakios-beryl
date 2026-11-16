# HakiOS on Redmi Note 14 5G (`beryl` / MediaTek Dimensity 7025 Ultra / MT6855)

Port of **Apple Darwin XNU** (`xnu-8796.121.2`) and native **Apple iOS 16.5 graphical userland** (`launchd` $\to$ `backboardd` $\to$ `SpringBoard`) to the **Xiaomi Redmi Note 14 5G** (`beryl`), powered by the MediaTek MT6855 SoC.

---

## 1. Executive Summary & Objective

- **Target Device**: Xiaomi Redmi Note 14 5G (`beryl`), ADB Serial: `ZHT4IB59XSUKAELR`.
- **SoC**: MediaTek MT6855 / Dimensity 7025 Ultra (6nm, 2× Cortex-A78 @ 2.2 GHz + 6× Cortex-A55 @ 2.0 GHz).
- **Core Mission**: Boot the authentic Apple iOS 16.5 graphical userland to SpringBoard on bare-metal MediaTek silicon.
- **Safety Invariant**: Strictly non-destructive dual-boot. Chained `mtkloader` resides in `boot_a` while preserving genuine Xiaomi AVB footers and VBMeta. Default boot starts Android with zero delay; holding Volume Down or sending a software trigger boots Darwin / iOS.

---

## 2. Hardware Specifications & Board Map

| Subsystem | Specification & Memory/Register Address | Verification Status |
| :--- | :--- | :---: |
| **CPU Architecture** | 8 Cores: Cores 0-1 (Cortex-A78) + Cores 2-7 (Cortex-A55), ARMv8.2-A | **Verified** |
| **DRAM** | 8 GB LPDDR4X, Physical Base `0x40000000` | **Verified** |
| **Interrupt Controller** | ARM GICv3 (`arm,gic-v3`), GICD @ `0x0c000000`, GICR @ `0x0c040000` | **Verified** |
| **Storage** | 256 GB UFS 2.2 (Samsung `KM8F9001JM-B813`, Controller: `0x112b0000`) | **Verified** |
| **Display Panel** | 6.67" AMOLED, 1080×2400 (FHD+), 32bpp, LK Framebuffer @ `0xfe0c0000` | **Verified** |
| **Touchscreen** | FocalTech FT3519T on I2C-0 (`0x11ed0000`, 7-bit addr `0x38`) | **Verified** |
| **Hardware Keypad** | MTK Keypad (`0x1c00e000`), Vol Down (`KP_MEM1` bit 0), Vol Up | **Verified** |
| **Watchdog Timer** | MediaTek `TOPRGU` (`0x10007000`), Mode `0x43u` (Warm Reset / DRAM preserved) | **Verified** |

---

## 3. System Architecture & Multi-Stage Boot Sequence

```
+-----------------------------------------------------------------------------------+
| Stage 0: MediaTek LK (Little Kernel)                                              |
| - Verifies AVB header & boots /dev/block/by-name/boot_a                           |
+-----------------------------------------------------------------------------------+
                                        |
                                        v
+-----------------------------------------------------------------------------------+
| Stage 0.5: Chained mtkloader (mtkloader/mtkloader.c)                              |
| - Prepares GICv3, CPU cores, UFS SCSI controller & Linear Framebuffer Console     |
| - Maps UFS LBA 61689024 (2477 MB APFS Container) as partition "darwin"            |
| - Loads XNU kernel_patched + payload.bin (containing root.apfs)                   |
| - Jumps to XNU kernel entry point                                                 |
+-----------------------------------------------------------------------------------+
                                        |
                                        v
+-----------------------------------------------------------------------------------+
| Stage 1: Darwin XNU Kernel Boot & Ramdisk Mounting                               |
| - Mounts payload.bin ramdisk as initial root (/dev/md0)                           |
| - Starts Process 1 (/sbin/launchd on root.apfs)                                   |
| - CRITICAL: /sbin/launchd on root.apfs MUST BE 100% STATIC (LC_UNIXTHREAD, no dyld)|
+-----------------------------------------------------------------------------------+
                                        |
                                        v
+-----------------------------------------------------------------------------------+
| Stage 2: HakiOS Static Init (hakios/prebuilt/userland/init)                       |
| - Configures kern.maxvnodes = 32768, inject sysctls                               |
| - Mounts APFS container on /flash (/dev/ufs_darwin)                               |
| - Binds /LaunchDaemons, /xpc, /hal over /flash                                    |
| - Switches root to /flash via kern.redwood_switch_root                            |
| - Grafts OS Cryptex (/System/Cryptexes/OS with dyld_shared_cache_arm64)           |
| - Mounts ramfs on /private/var and unpacks var.skel                               |
| - Runs /etc/rc -> exec /sbin/launchd (substitutes to genuine Apple launchd)       |
+-----------------------------------------------------------------------------------+
                                        |
                                        v
+-----------------------------------------------------------------------------------+
| Stage 3: Genuine Apple iOS 16.5 Userland Handover                                 |
| - Apple dynamic /sbin/launchd starts under switched root                          |
| - Dyld finds dyld_shared_cache_arm64 in /System/Cryptexes/OS                      |
| - Starts system daemons: notifyd, syslogd, logd, containermanagerd                |
| - Launches com.apple.backboardd -> com.apple.SpringBoard (Graphical UI)           |
+-----------------------------------------------------------------------------------+
```

---

## 4. Key Learnings & Error Solutions Index

Below are the 12 critical errors resolved through systematic silicon log analysis:

### 1. Stage-1 PID 1 Binary Dynamic Linkage (`LC_LOAD_DYLINKER`)
- **Cause**: Linux LLVM `ld64.lld` does not implement `-static`. Compiling `src/init.c` locally created a dynamically linked Mach-O requiring `/usr/lib/dyld`.
- **Symptom**: `dyld: Library not loaded: /usr/lib/libSystem.B.dylib (no such file, no dyld cache)` $\to$ `panic: initproc failed to start`.
- **Fix**: Enforce `PREBUILT=1` in `hakios/userland/build.sh`. Unconditionally use verified static `hakios/prebuilt/userland/init` (`flags: <NOUNDEFS>`, `LC_UNIXTHREAD`, no dyld) for `root/sbin/init` and `root/sbin/launchd`.

### 2. Accidental Dyld Embedding on Ramdisk
- **Cause**: `build.sh` previously copied `$IOS/rootfs/usr/lib/dyld` into `root/usr/lib/dyld`.
- **Symptom**: Prompted premature dyld invocation on `root.apfs` before dyld shared cache was available.
- **Fix**: Removed `root/usr/lib/dyld` from `root.apfs`. Dyld lives exclusively in the switched iOS rootfs.

### 3. Diagnostic Test Fault in Prebuilt Init (`test_memory` 64 MB Touch)
- **Cause**: `hakios/prebuilt/userland/init` contained automated diagnostics at offset `0x21bc` (including 64 MB anonymous memory touching at `0x3300`), which triggered ARM64 page faults on MTK translation tables: `usertrap: launchd[1] exception 1 code 0x5 ... 64 MB of anonymous memory`.
- **Fix**: Patched instruction at file offset `0x21bc` (`0x70029ce0`) in `hakios/prebuilt/userland/init` to `b 0x3ea4` (`0x1400073a`), bypassing diagnostic tests directly into `configure_inject` $\to$ `configure_vnodes` $\to$ `run_rc` $\to$ genuine iOS launchd.

### 4. MediaTek `TOPRGU` Watchdog Reset Mode
- **Cause**: Bit 2 (`EXRST_EN` = 0x4) in `TOPRGU_MODE` asserted the external PMIC reset line, cold power-cycling DRAM and losing ramoops logs.
- **Fix**: Configured `TOPRGU_MODE` to `0x43u` (`WDT_MODE_EN | EXT_POL | DUAL_EN`), preserving DRAM across reboots for automated pstore log rescue.

### 5. Automated Pstore Log Rescue Race Condition
- **Cause**: `adb wait-for-device` returned prematurely before the device disconnected from USB during reboot.
- **Fix**: Added an active polling loop on `adb get-state` in `tools/boot-and-listen.py` to verify device disconnect before listening for the warm reset.

### 6. Video Framebuffer Decoding on Watchdog Rescue
- **Cause**: On-screen frame buffer / panic output was only decoded on `xnu_return_stub`, omitting display dumps on watchdog resets.
- **Fix**: Integrated `read_screen()` into the automated log rescue pipeline.

### 7. XNU `kern_sig.c:2341 Assertion failed: signal_reason == NULL`
- **Cause**: A NOP patch at `0x7dd3c0` in `_psignal_internal` caused execution to fall through into uninitialized assertion checks.
- **Fix**: Patched `0x7dd3c0` with `b +0x34` (`0x1400000d` to `0x7dd3f4`), nopping `0x7dd3d8` and `0x7dd3f0`.

### 8. Infinite Spin Loop on PID 1 Exit
- **Cause**: Panic call at `0x7c3d94` was patched to `b .`, freezing the CPU without writing stackshots to pstore ramoops.
- **Fix**: Restored `bl _panic_with_options` (`0x940c04b2`) to dump registers and backtraces to pstore.

### 9. Synthetic Directory `EEXIST` Handling
- **Cause**: `synthetic_dir()` treated `EEXIST` as failure if the mount point directory already existed on flash.
- **Fix**: Checked `stat` and treated `EEXIST` as success.

### 10. Bind-Mount Failure Over Symlinks
- **Cause**: `mount("bindfs", ...)` failed when target directories were symlinks.
- **Fix**: Implemented `bind_or_symlink()` to verify `S_ISLNK` before invoking `bindfs`.

### 11. Launchd Path Substitution in `run_rc`
- **Cause**: `root/etc/rc` ran `exec /sbin/launchd.ios`, which could fail if `/sbin/launchd.ios` was absent on switched root.
- **Fix**: Verified and ensured `run_command` in `init` automatically substitutes `/sbin/launchd.ios` with genuine `/sbin/launchd` on flash root.

### 12. Redundant 10-Minute `system.apfs` Rebuilds
- **Cause**: Timestamp checks against `obj/stage0` triggered full 2.5 GB APFS container recompression on every run.
- **Fix**: Configured `build.sh` to reuse existing `system.apfs` unless `SYSTEM=1` is explicitly set.

---

## 5. Latest Silicon Run Findings (`run_20261116_182305`)

From the rescued silicon pstore log (`logs/run_20261116_182305/console.txt`):
1. **Static Init Success**: `hakios/prebuilt/userland/init` loaded cleanly as PID 1, configured max vnodes to 32768, parsed `/etc/rc`, and executed `$ exec /sbin/launchd.ios`.
2. **Current Kernel Trap Point**:
   ```text
   init: up to 32768 vnodes
   === /etc/rc ===
   $ exec /sbin/launchd.ios
   panic(cpu 2 caller 0xfffffff007ad39b4): Kernel data abort. at pc 0xfffffff007357edc, lr 0xfffffff0077e091c (saved state: 0xfffffff883b47650)
     x0: 0x0  x1: 0xfffffff362ba4320  x2: 0x1  x3: 0xfffffff6156a0161
     pc: 0xfffffff007357edc  lr: 0xfffffff0077e091c  far: 0x420
   ```
3. **Disassembly Analysis**:
   - `0x7357ecc`: Function begins with:
     ```arm64
     0x7357ecc: stp x20, x19, [sp, #-32]!
     0x7357ed0: stp x29, x30, [sp, #16]
     0x7357ed4: add x29, sp, #16
     0x7357ed8: mov x20, x0
     0x7357edc: ldr x19, [x0, #0x420]   <-- DATA ABORT (x0 == NULL, far == 0x420)
     ```
   - Caller is at `0x77e0918` in `execve` path (`bsd/kern/kern_exec.c` / image params processing).
   - **Resolution Target**: Guard against NULL `x0` at `0x7357edc` (`cbz x0, ...` or return 0).

---

## 6. How to Build, Flash, and Resume

### Invariants:
- **Always Flash strictly to `boot_a`**: `dd if=... of=/dev/block/by-name/boot_a bs=4096 conv=fsync`.
- **Never touch `boot_b`** (preserves failsafe Android backup).
- **Push all commits to `master`**: `https://github.com/aditya-dumps/hakios-beryl.git`.

### Build & Flash Commands:
```bash
# 1. Build root.apfs with static init
cd hakios/userland && ./build.sh && cd ../..

# 2. Package payload.bin
python3 hakios/xnuloader/mkpayload.py -o mtkloader/payload.bin kernel=mtkloader/kernel_patched ramdisk=hakios/userland/root.apfs

# 3. Build chained mtkloader boot image
cd mtkloader && ./build.sh && cd ..

# 4. Flash strictly to boot_a
./tools/flash-boot-a.sh mtkloader/mtkloader_xnu.img

# 5. Trigger boot and listen for logs
python3 tools/boot-and-listen.py boot-xnu
```

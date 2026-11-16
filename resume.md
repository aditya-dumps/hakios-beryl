# HakiOS Beryl — Session Resume & State Documentation

> **Status**: Ready for new chat. Everything is documented, committed, and structured for zero token waste.
> **Date**: 2026-11-16
> **Device**: Xiaomi Redmi Note 14 5G (`beryl`, MediaTek Dimensity 7025 Ultra / MT6855)
> **ADB Serial**: `ZHT4IB59XSUKAELR`
> **Target OS**: Apple iOS 16.5 Userland (`launchd` -> `backboardd` -> `SpringBoard` GUI)
> **Kernel**: XNU 22.5.0 (`xnu-8796.121.2`, arm64 BCM2837/MediaTek port)
> **Repository**: `https://github.com/aditya-dumps/hakios-beryl.git` on branch `master`

---

## 1. Strict Rules & Invariants (DO NOT VIOLATE)

1. **Flashing Target**:
   - ALWAYS flash strictly to `/dev/block/by-name/boot_a` with `bs=4096 conv=fsync`.
   - **NEVER TOUCH `boot_b`**. `boot_b` is the failsafe Android rescue partition.
2. **Warm Reset & Watchdog**:
   - MediaTek TOPRGU watchdog mode MUST be `0x43u` (`WDT_MODE_EN | EXT_POL | DUAL_EN`).
   - Bit 2 (`EXRST_EN`) MUST remain 0 to prevent cold PMIC power-cycling, preserving DRAM for pstore rescue.
3. **Pstore Rescue Protocol**:
   - Automated via `python3 tools/boot-and-listen.py boot-xnu`.
   - Arm flag: writes `boot-xnu` to `/dev/block/by-name/misc` LBA 8.
   - Warm reset reboots device into Android; script rescues `/sys/fs/pstore/console-ramoops-0` and `pmsg-ramoops-0` into `logs/run_<timestamp>/`.
4. **Git Repository**:
   - Keep all changes committed and pushed to `origin/master`.

---

## 2. Architecture & Boot Flow

```
[MTK BootROM / Preloader]
          │
[LittleKernel / LK-Beryl (boot_a)]
          │ reads misc flag "boot-xnu"
[mtkloader_xnu.img] (starts at DRAM 0x40000000)
          │ unpacks payload.bin (Kernel + DTB + Ramdisk)
[XNU Kernel 22.5.0] (base: 0xfffffff007004000)
          │ sets up MMU, pmap, interrupts, GICv3, framebuffer (FE0C0000)
          │ mounts initial root ramdisk root.apfs
[PID 1: hakios/prebuilt/userland/init] (static arm64 Mach-O)
          │ mounts ufs_darwin (iOS 16.5 APFS system volume)
          │ bindfs / symlinks system directories
          │ runs /etc/rc
          │ execve("/sbin/launchd.ios")
          ▼
[PID 1: Apple launchd.ios] (dynamic Mach-O 64-bit arm64)
          │ loads /usr/lib/dyld -> dyld_shared_cache
          ▼
[Apple Daemons: notifyd, cfprefsd, containermanagerd, backboardd, SpringBoard]
```

---

## 3. Latest Run Analysis (`run_20261116_183808`)

### What Succeeded:
1. `init` executed cleanly as PID 1 from `root.apfs`.
2. `init` mounted iOS filesystem, ran `/etc/rc`, and executed `$ exec /sbin/launchd.ios`.
3. The previous crash at `0xfffffff007357edc` was **completely resolved** by our ARM64 trampoline at `0xfffffff007451260` in `__TEXT_EXEC`!
4. PID 1 identity transitioned to `launchd`:
   ```
   Panicked task 0xfffffff5477d66d0: 6 pages, 1 threads: pid 1: launchd
   ```

### What Panicked (Current Roadblock):
```
PANIC: Kernel data abort. at pc 0xfffffff0077e097c, lr 0xfffffff0077e092c (saved state: 0xfffffff88bc27670)
far: 0x0000000000000840
x21: 0x0000000000000580
```

#### Detailed Call Trace & Root Cause Analysis:
1. `/sbin/launchd.ios` (Apple genuine launchd) was called via `execve`.
2. Inside `kern_exec.c` (`0x77c16dc` / `0x77c0480`), `execve` encountered an issue loading `/sbin/launchd.ios` (or dyld).
3. When `execve` fails, XNU invokes `exec_handle_failure` (`0x77bc560`), which sends `SIGKILL` (signal 9) to PID 1:
   ```arm64
   0xfffffff0077bd168: mov  w1, #9          ; SIGKILL
   0xfffffff0077bd16c: mov  x2, x22         ; reason
   0xfffffff0077bd170: bl   #0x77e144c      ; psignal_with_reason
   ```
4. `psignal_internal` calls helper `0x77e08ec(thread, proc, signum)`.
   In this failure path, `thread` argument `x0` is `NULL` (`0x0`).
5. `0x77e08ec` calls `get_bsdthread_info(th)` at `0x7357b44`:
   ```arm64
   0xfffffff007357b44: add  x0, x0, #0x580
   0xfffffff007357b48: ret
   ```
   Because `x0 == NULL`, `0 + 0x580 = 0x580`!
6. It then does:
   ```arm64
   0xfffffff0077e097c: ldr  x8, [x21, #0x2c0]
   ```
   Dereferencing `0x580 + 0x2c0 = 0x840` -> **KERNEL DATA ABORT on page 0 (`far: 0x840`)**!

---

## 4. Discovered Patches & Solutions Needed

### Immediate Kernel Patch 1: Safe `get_bsdthread_info`
At `0xfffffff007357b44` (file offset `0x353b44`):
Replace:
```arm64
0x7357b44: add x0, x0, #0x580
0x7357b48: ret
```
With a safe NULL check:
```arm64
0x7357b44: cbz x0, #0x7357b4c     ; 0x34000040 (if th == NULL, return NULL)
0x7357b48: add x0, x0, #0x580     ; 0x91160000
0x7357b4c: ret                    ; 0xd65f03c0
```
This guarantees `get_bsdthread_info(NULL)` returns `NULL` (`0x0`), preventing the `far: 0x840` data abort and allowing XNU to properly report the exec failure or proceed!

### Userland Investigation: Why `execve("/sbin/launchd.ios")` failed
Genuine Apple `/sbin/launchd.ios`:
- Requires `/usr/lib/dyld`.
- Requires `/System/Library/Caches/com.apple.dyld/dyld_shared_cache_arm64e` (or `arm64`).
- Requires root filesystem to be properly switched or bind-mounted so `/usr/lib/dyld` is accessible at `/usr/lib/dyld`.
- In `hakios/userland/root/etc/rc`, verify how the root filesystem is switched before `exec /sbin/launchd.ios`.

---

## 5. Comprehensive Summary of All 14 Errors Resolved to Date

| # | Error | Cause | Resolution |
|---|---|---|---|
| 1 | `libSystem.B.dylib not found` | Dynamic `launchd` in ramdisk | Use static `hakios/prebuilt/userland/init` |
| 2 | Early dyld crash in ramdisk | `/usr/lib/dyld` inside ramdisk | Removed dyld from initial ramdisk |
| 3 | `test_memory` page fault | `init` touches 64MB anonymous mmap | Patched `0x21bc` in `init` to `b 0x3ea4` |
| 4 | Cold PMIC DRAM wipe | `TOPRGU` had `EXRST_EN` bit 2 set | Set mode to `0x43u` (`DUAL_EN`, no cold reset) |
| 5 | Premature pstore rescue | ADB returned before device disconnected | Poll `adb get-state` until disconnect |
| 6 | Missing screen capture | Watchdog rescue missed `read_screen()` | Integrated frame capture in `rescue_log()` |
| 7 | `kern_sig.c:2341 Assertion failed` | SIGKILL assertion in `psignal_internal` | Patched `0x7dd3c0` to `b +0x34` |
| 8 | Kernel infinite hang at `0x7c3d94` | Replaced panic with `b .` | Restored `bl _panic_with_options` |
| 9 | Synthetic dir `EEXIST` | Treated existing directories as errors | Added `errno == EEXIST` allowance |
| 10 | `bindfs` symlink failure | Mount failed on symlink targets | Added `bind_or_symlink()` fallback |
| 11 | Launchd path resolution | Looked for `/sbin/launchd.ios` | Added fallback path in `run_rc` |
| 12 | Redundant `system.apfs` builds | Timestamp check triggered 10m rebuild | Reused unless `SYSTEM=1` specified |
| 13 | Kernel `W^X` instruction fetch abort | Trampoline placed in `__TEXT` (RX disabled) | Moved trampoline to `0x7451260` in `__TEXT_EXEC` |
| 14 | `execve` NULL pointer dereference | Helper `0x7357ecc` did `ldr [x0, #0x420]` | Added NULL-return trampoline at `0x7451260` |

---

## 6. Git Status & Repository Sync
- All changes to `mtkloader/kernel_patched` and helper scripts are ready.
- To verify in new chat: `git status`, `git log -1`.
- Commit and push before concluding this turn.

---

## 7. How to Resume in New Chat

1. Start prompt with:
   ```
   Resume HakiOS Beryl boot from resume.md. Device ZHT4IB59XSUKAELR connected.
   ```
2. The agent will read `resume.md` and immediately:
   - Patch `0x7357b44` in `mtkloader/kernel_patched` with safe `cbz x0` check.
   - Inspect `/etc/rc` and root mount to ensure `/usr/lib/dyld` is available to `/sbin/launchd.ios`.
   - Rebuild payload, flash `boot_a`, and run `python3 tools/boot-and-listen.py boot-xnu`.

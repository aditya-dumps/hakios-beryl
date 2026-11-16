# Hardware & Architecture Reference: Redmi Note 14 5G (`beryl`, MT6855)

## 1. Safety & Device Rules
* **Device**: Xiaomi Redmi Note 14 5G (`beryl`), MediaTek Dimensity 7025 Ultra (MT6855), Serial `ZHT4IB59XSUKAELR`.
* **Flash Invariant**: Flash strictly to `/dev/block/by-name/boot_a` with `bs=4096 conv=fsync`. NEVER flash or modify `boot_b` (Android fallback) or firmware partitions.
* **Restore Image**: `./stock_boot_a.img` (SHA256: `abbae1821884e0048493517637e6f2f9a676f33dbf107d4d56286670c10df7e0`).
* **Trigger Mechanism**: Write `boot-ios` to `/dev/block/by-name/misc` (LBA 8). `mtkloader` detects and clears it automatically before entering XNU.

## 2. Hardware Memory Map & Peripherals
| Subsystem | Physical Address Range / Value | Details |
| :--- | :--- | :--- |
| **DRAM Base** | `0x40000000` (8 GB total) | LK enters `_start` at `0x40000000`, DTB at `0x47c80000`. |
| **XNU Memory** | `0x80000000` .. `0xfe0c0000` (~2016 MB) | `KERNEL_VIRT_BASE` = `0xfffffff004000000`, `XNU_SLIDE = (XNU_PHYS_BASE - KERNEL_VIRT_BASE)`. |
| **Ramoops (pstore)** | `0x48090000` (896 KB) | Console: `0x480b0000` (256 KB) -> `console-ramoops-0`. Pmsg: `0x480f0000` (512 KB). |
| **Marker** | `0x480a0000` (`MARKER_PA`) | `0x4e52584e` (`MARK_RUNNING`), `0x4e44584e` (`MARK_DONE`). |
| **TOPRGU Watchdog**| Base `0x1c007000` | MODE `0x00`, LENGTH `0x04`, RESTART `0x08`, SWRST `0x14`. |
| **AMOLED Display** | Base `0xfe0c0000` (`LK_FB_BASE`) | 1080x2400 FHD+, 32bpp, Pitch = 4352 bytes (`4352 * 2400 = 10,444,800` bytes). |
| **UFS Storage** | Base `0x112b0000` (Samsung UFS 2.2) | UTRD: `0x60000000`, UCD: `0x60000800`, Shared LoaderBlock: `0x60004000`. |
| **APFS Container** | LBA `61,689,024` (2,477 MB) | Verified superblock `NXSB` at LBA `61,689,024`. Device node `/dev/ufs_darwin`. |
| **GICv3** | Distributor `0x0c000000`, Redist `0x0c040000` | Clear `ICC_CTLR_EL1.EOImode` to allow PPI timer interrupts to repeat. |
| **CPUs (8 cores)** | Boot `{ 0x000, 0x600, 0x700, 0x100..0x500 }` | Cluster 0: 6x A55 (2.0 GHz), Cluster 1: 2x A78 (2.2 GHz). Method: PSCI 1.0. |

## 3. MediaTek Watchdog (TOPRGU) Invariants
* **Hardware Register Formula**: `wr32(TOPRGU_LENGTH, (t << 5) | 0x8u);` where `t` is direct whole seconds (from Linux `drivers/watchdog/mtk_wdt.c` `WDT_LENGTH_TIMEOUT(t) | WDT_LENGTH_KEY`). Setting `(180 << 5) | 0x8` = exactly 180 seconds.
* **Keys**: Mode key `0x22000000`, Reload key `0x1971` (`TOPRGU_RESTART`), SWRST key `0x1209`.
* **Hardware Warm Reset Mode**: `wr32(TOPRGU_MODE, TOPRGU_MODE_KEY | 0x43u);` (`0x43 = WDT_MODE_EN | EXT_POL | DUAL_EN`).
  * Bit 2 (`EXRST_EN`) MUST BE CLEARED: if bit 2 is set (0x47), PMIC performs a cold external reset that zeros DRAM. With 0x43, TOPRGU resets the SoC while DRAM maintains self-refresh power, preserving `/sys/fs/pstore/console-ramoops-0`.
  * Cold power-cut (holding Power button 8s) zeros DRAM. Always rely on TOPRGU warm reset.

## 4. Userland & Graphical Boot Pipeline
1. `mtkloader` draws Apple logo to `LK_FB_BASE` (`0xfe0c0000`), maps APFS container LBA `61,689,024` as partition `darwin` (`/dev/ufs_darwin`), flushes cache, and jumps to XNU.
2. Kernel initializes memory, mounts ramdisk root (`rd=md0`), and starts `init` (PID 1).
   - Invariant: `/sbin/launchd` on `root.apfs` MUST be 100% static (`LC_UNIXTHREAD`, no dyld).
   - `hakios/prebuilt/userland/init` has offset `0x21bc` patched to `b 0x3ea4` (`0x1400073a`) to bypass diagnostic faults directly into `run_rc`.
3. `init` executes `flash_root("ufs_darwin")`:
   - Mounts `/dev/ufs_darwin` on `/flash`.
   - Binds `/LaunchDaemons` to `/flash/System/Library/LaunchDaemons`.
   - Swaps root to `/flash` (`kern.redwood_switch_root`).
   - Grafts OS & App cryptexes for dynamic linker shared cache (`dyld_shared_cache_arm64`).
   - Mounts ramfs on `/private/var` and unpacks `var.skel`.
4. Executes `exec /sbin/launchd` on `/flash` root.
5. `launchd` spawns `com.apple.backboardd` and `com.apple.SpringBoard` with AMOLED display rasterization.

## 5. Current Silicon Status & Immediate Next Step
* **Status**: Verified in `logs/run_20261116_182305/console.txt`:
  - Static `init` ran successfully as PID 1!
  - `init: up to 32768 vnodes`
  - `=== /etc/rc ===`
  - `$ exec /sbin/launchd.ios`
  - Trapped at kernel `execve` path:
    `panic: Kernel data abort. at pc 0xfffffff007357edc, lr 0xfffffff0077e091c (far: 0x420)`.
  - Disassembly at `0x7357edc`: `ldr x19, [x0, #0x420]` where `x0 == NULL`.
* **Immediate Fix**: Patch `0x7357edc` with a NULL check (`cbz x0, ...`) or guard `0x77e0918` in kernel `kern_exec.c`.

## 5. Reference Stack & Porting Base
* **Reference**: `hakios-mt6768/AGENTS.md` and `hakios/mtk/README.md`.
* **Zero Qualcomm Assumptions**: Pure MediaTek LK framebuffer, GICv3, and UFSHCI.
* **Logging**: Rescued via automated script `tools/boot-and-listen.py` into `logs/run_<timestamp>/`.

# Project Memory & Hardware Reference: Redmi Note 14 5G (beryl)

## 1. Safety & Device Rules
* **Device Serial**: `ZHT4IB59XSUKAELR` (Always specify `adb -s` / `fastboot -s`).
* **Partition Rule**: ONLY flash `boot_a`. NEVER touch slot B (`boot_b`), never touch vendor/modem/persist/system partitions directly.
* **Restore Point**: Stock `boot_a` backup is saved at `./stock_boot_a.img` (SHA256: `abbae1821884e0048493517637e6f2f9a676f33dbf107d4d56286670c10df7e0`).
* **One Run At a Time**: 200–600s with watchdog auto-reboot back to Android.
* **Multi-Factor Audit Rule (CRITICAL)**: NEVER guess or declare a single error as the sole cause of a boot failure. Always audit and check ALL errors across the full hardware, firmware, cache, MMU, memory layout, register handover, and display pipeline before drawing conclusions.

## 2. Exhaustive Error Catalog & Root Causes Audit
1. **Display Hardware Mutex Held in Reset (`display_alpha_off()`) [PRIMARY ROOT CAUSE FOR ARTIFACTS & HANDOVER FREEZE]**:
   - `display_alpha_off()` in `mtkloader.c` wrote `wr32(DISP_MUTEX_RUN, 1)` at address `0x14001024`.
   - On MediaTek SoCs, offset `+0x24` of `DISP_MUTEX` is `DISP_MUTEX_RST` (Hardware Reset), NOT `RUN`!
   - Writing 1 asserted and held Mutex 0 in hardware reset.
   - Dual impact:
     a) Display scanout pipeline desynchronized and torn mid-frame, rendering text as fragmented "artifacts".
     b) When Android kernel's `mediatek_drm_v1` driver initialized during handover, it attempted to acquire Mutex 0, hung indefinitely waiting for reset release, and was killed ~30s later by the SPM/TOPRGU hardware watchdog (`bootinfo.poffreason=AP_WDT`).
   - Fix: Completely eliminated `display_alpha_off()`. Display controller registers are treated as strictly read-only, matching proven `fbdiag.c`.
2. **Framebuffer Address Pointer Inconsistency (`display_find()`)**:
   - `display_find()` attempted to read `rd32(OVL0_BASE + OVL_L0_ADDR)` at `0x14002f40`.
   - On MT6855, LK allocates triple buffering within `0xfe0c0000..0xfffeffff`. Reading unverified offsets could return secondary buffers or non-active planes.
   - Fix: Directly pinned `fb_base = LK_FB_BASE` (`0xfe0c0000`), matching `pl_lk` log evidence (`fb_pa: 0xfe0c0000`, `mblock-12-framebuffer`).
3. **Display Glyph Mirroring / Panel Coordinates**:
   - `touchscreen@38` has `panel-orien-array: 3`, which was mistakenly applied to the display framebuffer in `fb_px` (`(PANEL_W - 1) - x`, `(PANEL_H - 1) - y`).
   - The display panel itself scans standard top-to-bottom (`atag,videolfb`). The inversion caused text to flip upside down at the bottom of the screen.
   - Fix: Use native framebuffer coordinates `px = x`, `py = y`.
4. **Residual Framebuffer Memory ("Green Line")**:
   - LK only paints the central logo and leaves the remaining uninitialized DRAM intact.
   - Fix: Cleared active framebuffer (1080x2400 ARGB8888 = 10,368,000 bytes) to black (`0xff000000`). Confirmed fixed on hardware.
5. **Excessive Uncached Cache Operations During Handover (`chain_stub`)**:
   - `chain_stub` previously executed 662,312 `dc civac` and 662,312 `ic ivau` instructions across all 42 MB with MMU disabled.
   - On uncached Device memory, 1.3 million line-by-line operations flood the interconnect bus and can trigger AXI bus timeouts.
   - The Linux kernel's `stext` (`0x218b778` and `0x216e098`) cleans its own page tables and arguments upon entry.
   - Fix: Flushed entry region (256 KB where `mtkloader` ran) and stub, followed by `dsb ish; isb`.
6. **Exception Vector Table Exposure During Copy**:
   - `vbar_el1` previously pointed to `mtk_vectors` inside `0x40000000` while `chain_stub` was overwriting `0x40000000` with the 42 MB kernel image.
   - Fix: Immediately masked all exceptions (`msr daifset, #0xf`) in `chain_stub` and set `vbar_el1` to a safe local loop before copying.
7. **Dynamic Code Execution Coherency (`chain_stub` at `stub_pa`)**:
   - `chain_stub` is dynamically copied to `stub_pa` (`0x428ada00`). Executing it without flushing D-cache and invalidating I-cache causes unpredictable prefetch aborts.
   - Fix: Explicit `flush_idcache_range(stub_pa, stub_len)` before jumping to `stub_pa`.
8. **Register Handover Compliance**:
   - Linux ARM64 boot protocol strictly requires `x0 = dtb_pa`, `x1 = 0`, `x2 = 0`, `x3 = 0`.
   - Fix: Verified and explicitly zeroed `x1..x3` in `chain_stub`, and passed genuine FDT pointer `0x47c80000`.
9. **Stack Pointer Underflow (`0x3fff8000`)**:
   - Original code subtracted stack pointer below DRAM base `0x40000000`.
   - Fix: Allocated dedicated 32 KB stack in `.bss` in DRAM (`mtkloader/link.ld`).
10. **Linker Base Offset Mismatch**:
    - Original code linked at `0x40080000`, while LK enters at `0x40000000`.
    - Fix: `. = 0x40000000;` in `link.ld` and `.quad 0x0` for `text_offset` in `start.S`.
11. **Fastboot Raw 128 MB Download Timeout**:
    - USB FIFO buffer limit causes stall when sending 128 MB raw image.
    - Fix: Always pass `-S 32M` to chunk transfers.
12. **TOPRGU / SPM Hardware Watchdog Reset**:
    - SPM / TOPRGU triggers hardware reboot (`bootinfo.poffreason=AP_WDT`) if the application processor halts or hangs for ~30 seconds without petting the watchdog.
    - Dropping into fastboot is the consequence of kernel hang, resolved by addressing factors 1 through 8.
13. **UFSHCI 2.0 Command Type (CT) & Unit Attention Handling (Run 40-42)**:
    - UFSHCI 2.0/2.1 host controller requires `command_type = 1` (`1u << 28`, `UTP_CMD_TYPE_UFS_STORAGE`) for both Query Requests (`fDeviceInit`) and SCSI commands (`INQUIRY`, `READ(10)`, `WRITE(10)`). Using `2u << 28` (`DEV_MANAGE`) results in immediate `OCS = 0x7` (Fatal Error / invalid descriptor).
    - UTRD DW 7 PRDT field encoding: `((PRDTO << 16) | PRDTL)` where PRDTO is in 4-byte Dwords (`(1024 / 4) << 16 | 1u`).
    - Post-Reset SCSI `UNIT ATTENTION` (Sense `0x6`, ASC `0x29` "Power On, Reset, or Bus Device Reset Occurred"): First access to LUN 2 returns `SCSI_STA = 0x2` (`CHECK CONDITION`). Issue a `TEST UNIT READY` to acknowledge and clear condition before reading GPT.
    - Verified: Read/write to `misc` partition (LBA 8), GPT partition table scan (74 partitions) on Samsung `KM8F9001JM-B813` UFS 2.2 storage fully functional.

## 3. Core Architecture & Hardware Map
* **SoC**: MediaTek MT6855 (Dimensity 7025 Ultra), compatible `"mediatek,MT6855"`.
* **RAM**: 8 GB LPDDR4X at physical base `0x40000000`.
* **Kernel Load PA**: `0x40000000` (LK decompresses kernel and jumps to `0x40000000`, DTB at `0x47c80000`).
* **CPUs (8 cores)**:
  * Cluster 0 (A55 @ 2.0 GHz): MPIDR `0x000, 0x100, 0x200, 0x300, 0x400, 0x500`
  * Cluster 1 (A78 @ 2.2 GHz): MPIDR `0x600, 0x700`
  * Bring-up order: `{ 0x000, 0x600, 0x700, 0x100, 0x200, 0x300, 0x400, 0x500 }`
  * Method: PSCI 1.0 via SMC.
* **GICv3**:
  * Distributor (GICD): `0x0c000000` (256 KB)
  * Redistributors (GICR): `0x0c040000` (2 MB)
  * Critical: Clear `ICC_CTLR_EL1.EOImode` so PPI timer interrupts can repeat.
* **Ramoops (pstore logging)**:
  * Total window: `0x48090000` (size `0xe0000`)
  * Oops/panic records: `0x48090000` (size `0x20000`)
  * Console buffer: `0x480b0000` (size `0x40000`) -> `/sys/fs/pstore/console-ramoops-0`
  * Pmsg buffer: `0x480f0000` (size `0x80000`) -> `/sys/fs/pstore/pmsg-ramoops-0`
  * Marker trigger: `DARWIN-BERYL:BOOT-XNU` written to `/dev/pmsg0`
* **Watchdog (TOPRGU)**:
  * Base: `0x1c007000`
  * Keys: MODE `0x22000000`, RESTART `0x1971`, SWRST `0x1209` (warm reset preserving pstore).
* **Display & Framebuffer**:
  * Panel: 1080 x 2400 FHD+, 32bpp, pitch = 4320 bytes.
  * LK Framebuffer: `0xfe0c0000` (size `0x1f30000` = 31.18 MB).
  * MMSYS: `0x14000000`, Mutex: `0x14001000`, OVL0: `0x14002000`.
  * Scanning: Standard top-to-bottom (`px = x, py = y`).
* **Storage**:
  * Controller: `ufshci@112b0000` (UFS 2.2, base `0x112b0000`, IRQ SPI 393).
  * Flash Chip: Samsung KM8F9001JM-B813 (256 GB).
* **GPU**:
  * Model: Imagination PowerVR B-Series BXM-8-256 (Architecture: Rogue `RGX`, BVNC: `35.3.408.101`).
* **Touchscreen**:
  * Controller: FocalTech FTS over I2C (`i2c@11ed0000`, chip addr `0x38`).

## 4. Boot Image & Kernel Packaging (AOSP v4 / MT6855)
* **Boot Image Version**: Android Boot Image Header Version 4 (`hver == 4`).
* **Header Size**: 1584 bytes (aligned to 4096-byte page boundary).
* **Kernel Size in stock_boot_a**: 19,790,630 bytes.
* **Kernel Compression**: LZ4 legacy format (`0x184c2102` magic). Decompresses to 42,387,968 bytes uncompressed ARM64 Linux Image.
* **LK Decompression**: MediaTek LK supports both `gunzip` and `unlz4`.
* **Chainboot Requirements**: `tools/chainboot.py` must support header v4 and unpack LZ4 legacy / gzip.

## 5. Host Toolchain
* Clang 20: `/home/aditya/crDroid/prebuilts/clang/host/linux-x86/clang-r547379/bin/clang`
* LLD: `/home/aditya/crDroid/prebuilts/clang/host/linux-x86/clang-r547379/bin/ld.lld`
* DTC: `/home/aditya/crDroid/prebuilts/misc/linux-x86/dtc/dtc`

## 6. Hardware Bring-up, Subsystems & Diagnostic Audits (Verified Nov 13, 2026)

### A. Boot Contract & Automation (Zero Manual Interaction)
* **Default Boot**: 100% Android (`chain_android()`) with 0s delay when no trigger is armed. Device reboots directly to normal Android without user interaction.
* **USB One-Shot Trigger**:
  - Test runner writes `boot-xnu` to `/dev/block/by-name/misc` (LBA 8).
  - `mtkloader` detects `boot-xnu` in `misc` buffer, clears `misc` immediately in DRAM/storage so it is strictly one-shot, and executes Darwin/XNU.
  - Zero manual button presses or UI required.

### B. Hardware Watchdog & PMIC Warm Reset (TOPRGU Subsystem)
* **Base Address**: `0x1c007000` (`TOPRGU`)
* **Mode Register (`TOPRGU_MODE` at `0x1c007000`)**:
  - **CRITICAL LESSON**: Setting bit 3 (`WDT_MODE_IRQ_EN` = `0x08`) converts expiration into an unhandled CPU interrupt rather than a system reset, freezing the core on a black screen.
  - **Correct Setting**: `TOPRGU_MODE_KEY | 0x47u` (`0x22000047`), explicitly disabling IRQ mode and enabling:
    - Bit 0: `WDT_MODE_ENABLE` (`0x01`)
    - Bit 1: `WDT_MODE_EXT_POL` (`0x02`)
    - Bit 2: `WDT_MODE_EXRST_EN` (`0x04`)
    - Bit 6: `WDT_MODE_DUAL_EN` (`0x40`)
* **Timeout Register (`TOPRGU_LENGTH` at `0x1c007004`)**:
  - **Formula**: `(seconds << 5) | 0x8u`. (Previous buggy shift caused >6 min wait; fixed to exact 5-6s).
* **Reset Reason**: LK reads `bootinfo.pureason=HW_reboot`, proving clean PMIC warm reset preserving DRAM.

### C. Preserved Hardware Reserved Memory & State Handover
* **Memory Map (`devicetree/reserved-memory/`)**:
  - `0x48080000 - 0x48090000` (64 KB): `mblock-1-aee_debug_kinfo` — Used by LK for `RAM_CONSOLE` (`mrdump_addr:0x11E000`). LK clears/formats header here on every boot, so do NOT use as marker.
  - `0x48090000 - 0x48170000` (896 KB): `mblock-2-pstore` (ramoops: dump 128 KB, console 256 KB, pmsg 512 KB) — PRESERVED across warm reboot and NEVER touched by LK.
  - `0x48170000 - 0x48180000` (64 KB): `mblock-3-minirdump` — PRESERVED.
* **Marker Register**: `#define MARKER_PA 0x480a0000ULL` (offset +64 KB into `pstore` dump region `0x48090000 - 0x480b0000`).
  - Values: `MARK_RUNNING (0x4e52584e / "NXRN")`, `MARK_DONE (0x4e44584e / "NXDN")`.
  - Verified surviving warm reset across runs: `mark: 0x4e52584e` reliably captured.

### D. Darwin XNU Kernel & iOS Userland Execution (VERIFIED Run 32)
* **Kernel & Subsystem Bringup**:
  - `pmap_bootstrap`: Translation tables initialized, TTBR1_EL1 at `0x8427d020`.
  - `GenericARMPE`: All 8 CPU cores active and running (`8 of 8 processors are running`).
  - `AppleMobileFramebuffer`: Display online at 1080x2400 FHD+ (`4352` bytes pitch).
  - `BSD root`: Embedded ramdisk mounted successfully (`BSD root: md0, major 1, minor 0`).
  - `Process 1 Launch`: Userland binary `/sbin/launchd` (`init_loop`) executed as PID 1!
  - `IOKit Support`: Configured and active.
* **Watchdog & Timing Execution Window**:
  - `XNU_WDT_SECONDS = 15`: 15s execution window allows complete kernel init, driver matching, root filesystem mount, and userland test execution before PMIC warm reset.
  - Omitted `loader_return_after`: Prevents early abort fault in `_loader_jump`.

### E. UFS 2.2 Host Controller & SCSI Descriptors (`0x112b0000`)
* **Multi-Factor Error Audit**:
  - **Factor 1: Descriptor Field Inversion (`ufs_utrd[7]`)**: `prd_table_offset` (high 16 bits) and `prd_table_length` (low 16 bits) were accidentally swapped as `(1u << 16) | (1024 / 4)`. The controller interpreted this as offset 4 bytes (inside Command UPIU) with length 256 entries, attempting DMA across invalid memory addresses and triggering `OCS = 0x7` (`SYSTEM_BUS_ERR`) with `IS = 0x5` (`SBFES`). Fixed to `(((1024 / 4) << 16) | 1u)`.
  - **Factor 2: DMA Memory Region (`0x60000000`)**: `0x48000000 - 0x50000000` is protected by EMI MPU against peripheral bus master DMA. Relocated UFS descriptors to `0x60000000ULL` (inside the completely unreserved 465 MB system DRAM window between `0x50f00000` and `0x7e000000`), completely eliminating `SBFES` bus errors.
  - **Factor 3: UniPro PA Layer Error (`UECPA = 0x80000010`) & DME Opcodes**:
    - `UECPA = 0x80000010` is `PA_INIT_ERROR` (Physical Adapter initialization failure).
    - MediaTek vendor attributes: LK leaves UniPro in Low Power Mode (`VS_UNIPROPOWERDOWNCONTROL = 0xD0A8`) with clock gating enabled (`VS_SAVEPOWERCONTROL = 0xD0A6`).
    - Opcode & Argument Packing: `DME_SET` opcode is `0x02` (not `0x01` which is `DME_GET`), and attribute IDs must be shifted to bits 31..16 via `UIC_ARG_MIB(attr) = ((attr & 0xffff) << 16)`.
    - Fix: Issue `DME_SET(VS_UNIPROPOWERDOWNCONTROL = 0)`, `DME_SET(VS_SAVEPOWERCONTROL = 0)`, and `DME_SET(PA_Local_TX_LCC_Enable = 0)` prior to `DME_LINKSTARTUP (0x16)`.

### F. Darwin Framebuffer Console & Log Extraction
* **Multi-Factor Error Audit**:
  - **Factor 1: Screen Wiping Prior to Rescue**: `display_find()` was called before `if (mark == MARK_RUNNING)` and filled `LK_FB_BASE` with black pixels (`0xff000000ff000000ULL`), wiping whatever Darwin had rendered before reset. Fixed to `display_find(mark != MARK_RUNNING)`.
  - **Factor 2: Screen Buffer Contamination by Bootloader Logs**: `dbg_puts()` in `rescue_log()` drew text via `fbcon_putc()` at `scale = 2` using `font8x16` before `read_screen()` was called, leading to `12444 cells lit, 0 read as characters`. Fixed by isolating screen capture to execute before any logging and keeping `fbc.base = 0` during log extraction.
  - **Factor 3: Console Decoding**: `read_screen()` uses MSB-first pixel order (`0x80u >> x`) with normal, inverted, and bit-reversed hashing against pristine Mach-O `_iso_font` (offset `0xae7e10`).
  - **Factor 4: DRAM Bit Preservation & Pointer Sanitization**: `sanitize_kva()` restores canonical 64-bit kernel prefix `0xfffffff0` if upper bits experience charge decay across reset.
  - **Factor 5: Cache Invalidation**: `dcache_inval_range` across `LK_FB_BASE` (10.44 MB), `s.log` (1.25 MB), `_msgbufp`, and message buffer before reading.

# Project Memory & Hardware Reference: Redmi Note 14 5G (beryl)

## 1. Safety & Device Rules
* **Device Serial**: `ZHT4IB59XSUKAELR` (Always specify `adb -s` / `fastboot -s`).
* **Partition Rule**: ONLY flash `boot_a`. NEVER touch slot B (`boot_b`), never touch vendor/modem/persist/system partitions directly.
* **Restore Point**: Stock `boot_a` backup is saved at `./stock_boot_a.img` (SHA256: `abbae1821884e0048493517637e6f2f9a676f33dbf107d4d56286670c10df7e0`).
* **One Run At a Time**: 200–600s with watchdog auto-reboot back to Android.

## 2. Core Architecture & Hardware Map
* **SoC**: MediaTek MT6855 (Dimensity 7025 Ultra), compatible `"mediatek,MT6855"`.
* **RAM**: 8 GB LPDDR4X at physical base `0x40000000`.
* **Kernel Load PA**: `0x40080000` (Standard arm64 Linux entry).
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
  * LK Framebuffer: `0xfe0c0000` (size `0x1df0000` = ~30 MB).
  * MMSYS: `0x14000000`, Mutex: `0x14001000`, OVL0: `0x14002000`.
* **Storage**:
  * Controller: `ufshci@112b0000` (UFS 2.2, base `0x112b0000`, IRQ SPI 393).
  * Flash Chip: Samsung KM8F9001JM-B813 (256 GB).
* **GPU**:
  * Model: Imagination PowerVR B-Series BXM-8-256 (Architecture: Rogue `RGX`, BVNC: `35.3.408.101`).
  * Note: NOT Mali. Graphics bring-up uses linear framebuffer (`simplefb`) first.
* **Touchscreen**:
  * Controller: FocalTech FTS over I2C (`i2c@11ed0000`, chip addr `0x38`).

## 3. Boot Image & Kernel Packaging (AOSP v4 / MT6855)
* **Boot Image Version**: Android Boot Image Header Version 4 (`hver == 4`).
* **Header Size**: 1584 bytes (aligned to 4096-byte page boundary).
* **Kernel Size in stock_boot_a**: 19,790,630 bytes.
* **Kernel Compression**: LZ4 legacy format (`0x184c2102` magic). Decompresses to 42,387,968 bytes uncompressed ARM64 Linux Image.
* **LK Decompression**: MediaTek LK supports both `gunzip` and `unlz4`.
* **Chainboot Requirements**: `tools/chainboot.py` must support header v4 and unpack LZ4 legacy / gzip.

## 4. Host Toolchain
* Clang 20: `/home/aditya/crDroid/prebuilts/clang/host/linux-x86/clang-r547379/bin/clang`
* LLD: `/home/aditya/crDroid/prebuilts/clang/host/linux-x86/clang-r547379/bin/ld.lld`
* DTC: `/home/aditya/crDroid/prebuilts/misc/linux-x86/dtc/dtc`

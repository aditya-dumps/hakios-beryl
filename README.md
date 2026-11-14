# hakios-beryl: Redmi Note 14 5G (MT6855 / Dimensity 7025 Ultra)

Port of **HakiOS** (Apple Darwin XNU kernel `xnu-8796.121.2` and native iOS user space) to the **Redmi Note 14 5G** (`beryl`), powered by the MediaTek Dimensity 7025 Ultra (**MT6855**).

This port runs Apple's open-source XNU kernel bare-metal on MediaTek silicon with custom low-level drivers, an authentic framebuffer console on the 1080×2400 panel, Samsung UFS 2.2 flash storage enumeration, FocalTech I2C touch support, and full 8-core SMP.

Nothing on the device is permanently replaced: `mtkloader` is chained in `boot_a` in front of Android's genuine kernel. By default, Android boots normally with 0s delay. Holding **Volume Down** or sending a USB trigger boots iOS / Darwin.

---

## Hardware Specifications

| Component | Hardware Specification |
| :--- | :--- |
| **Phone Model** | Xiaomi Redmi Note 14 5G (`beryl`) |
| **SoC** | MediaTek MT6855 (Dimensity 7025 Ultra, 6nm) |
| **CPU Architecture** | 8 Cores: 2× Cortex-A78 @ 2.2 GHz + 6× Cortex-A55 @ 2.0 GHz |
| **Interrupt Controller** | ARM GICv3 (`arm,gic-v3`), GICD @ `0x0c000000`, GICR @ `0x0c040000` |
| **RAM** | 8 GB LPDDR4X (DRAM Base: `0x40000000`) |
| **Storage** | 256 GB UFS 2.2 (Samsung `KM8F9001JM-B813`, Controller: `ufshci@112b0000`) |
| **Display Panel** | 6.67" AMOLED, 1080×2400 (FHD+), 32bpp, LK Framebuffer @ `0xfe0c0000` |
| **Touchscreen** | FocalTech FT3519T on I2C-0 (`0x11ed0000`, 7-bit addr `0x38`) |
| **Keypad** | MediaTek Hardware Keypad (`0x1c00e000`), Volume Down / Up |
| **GPU** | Imagination PowerVR B-Series BXM-8-256 (Rogue RGX Architecture) |

---

## Hardware Support Status

| Subsystem | Status | Technical Implementation & Silicon Evidence |
| :--- | :---: | :--- |
| **Chained Bootloader** | **WORKS** | `mtkloader` runs from LK inside `boot_a`, preserving genuine Xiaomi AVB footers and VBMeta. Default boot to Android has 0s delay. |
| **Hardware Dual-Boot** | **WORKS** | Hold **Volume Down** or **Volume Up** at power-on to boot iOS/Darwin. Power on normally without buttons to boot Android. |
| **Display & Console** | **WORKS** | LK linear framebuffer console lit at `0xfe0c0000` (pitch 4320). Apple boot logo and text console rendered on 1080×2400 panel (1304 cells lit, 774 decoded glyphs). |
| **CPU & SMP** | **WORKS** | Multi-core SMP brings up all 8 cores via PSCI SMC (`GenericARMPE: 8 of 8 processors are running`). |
| **Interrupts (GICv3)** | **WORKS** | GICv3 Distributor and Redistributors initialized; `ICC_CTLR_EL1.EOImode` cleared across all 8 cores. |
| **Storage (UFS 2.2)** | **WORKS** | UniPro linkup (`HCS=0xf`), `fDeviceInit` cleared in 5ms, SCSI `INQUIRY` reads Samsung MCP, Unit Attention cleared via `TEST UNIT READY`. Multi-block GPT parsed, all 74 partitions mapped to XNU via `struct loader_block` (`ufs_shared_pa=0x60004000`). |
| **Touchscreen** | **WORKS** | FocalTech FT3519T probed over I2C bus `0x11ed0000` (slave address `0x38`). Low-level I2C transactions verified on silicon (`FW_VER=0x70`). |
| **Buttons** | **WORKS** | MTK Keypad (`0x1c00e000`) Volume Down (`KP_MEM1` bit 0) and Volume Up operational. |
| **One-Shot USB Runner** | **WORKS** | `tools/boot-xnu.sh` arms trigger in `misc` partition (LBA 8), boots Darwin, and safely auto-resets back to Android via PMIC watchdog, pulling ramoops logs. |
| **GPU Acceleration** | *In Progress* | Imagination PowerVR BXM-8-256 Rogue RGX (firmware `rgx.fw`). Display currently runs on high-performance CPU framebuffer. |
| **Wi-Fi & Bluetooth** | *In Progress* | MT6855 CONNSYS at `0x18002000`. Firmware extracted to `fw-connsys/` via `pull-firmware.sh`. |
| **Sensors & Audio** | *Missing* | SCP sensor hub at `0x1c700000` and audio codec to be mapped in future milestones. |

---

## Repository Structure

* `mtkloader/` — Bare-metal chained bootloader source code (`mtkloader.c`, `start.S`, `link.ld`, `build.sh`) containing GICv3, SMP, Framebuffer, UFS, GPT, and I2C touch drivers.
* `configs/` — Kernel defconfig fragments (`beryl_defconfig` and `beryl.config`).
* `device.conf` — Authoritative device capabilities record (`works` / `partial` / `missing`).
* `docs/` — Comprehensive hardware documentation:
  * `docs/beryl-facts.md`: Board constants, register maps, and partition tables extracted from the device tree.
  * `docs/beryl-plan.md`: Step-by-step bring-up plan and silicon verification log.
* `tools/` — Automated flashing and testing utilities:
  * `tools/boot-xnu.sh`: One-shot USB test runner.
  * `tools/flash-boot-a.sh`: Safe chunked flasher strictly targeting `boot_a`.
  * `tools/restore-stock-boot.sh`: Restores genuine stock Android boot image.
* `pull-firmware.sh` — Extracts touch, connsys, and GPU vendor firmware from the device into `fw-*/` (git-ignored).
* `logs/` — Verified silicon run logs preserved across warm resets (`last_run_pmsg.txt`, `last_run_console.txt`).

---

## How to Boot

### 1. Hardware Dual-Boot (On Phone)
* **To Boot Android**: Turn on or restart the phone without pressing any buttons. Android loads immediately.
* **To Boot iOS / Darwin**: Turn on or restart the phone and hold **Volume Down** (or **Volume Up**). `mtkloader` will detect the button press, light up the Apple logo & text console, and boot XNU with all 8 cores running continuously.

### 2. Automated USB Test Cycle (From PC)
To run an automated test cycle with auto-reset and log extraction over USB:
```bash
./tools/boot-xnu.sh
```

---

## Building from Source

### Prerequisites
* Clang / LLVM (`clang`, `ld.lld`, `llvm-objcopy`)
* Python 3
* Android SDK Platform Tools (`adb`, `fastboot`)
* Device with unlocked bootloader and root access

### Build and Flash
```bash
# Build mtkloader and chain with Android kernel
cd mtkloader && ./build.sh && cd ..

# Flash to boot_a only (never touches boot_b or other partitions)
./tools/flash-boot-a.sh mtkloader/mtkloader_xnu.img
```

---

## Silicon Verification Evidence

Excerpts from the live silicon ramoops log ([logs/last_run_pmsg.txt](logs/last_run_pmsg.txt)):

```text
== mtkloader MT6855 ==
UFS: post-linkup: HCS=0xf res=0x0
UFS: Device Present! Initializing SCSI subsystem...
UFS: fDeviceInit cleared (device ready) in 5 ms
UFS: Storage Device: [SAMSUNG.KM8F9001JM-B813.0700]
UFS: >>> GPT VERIFIED! <<< total_parts=74 part_lba=2
UFS: Partitions on Flash:
  [misc] LBA 8..135 (0 MB)
  ...
  [boot_a] LBA 181504..214271 (128 MB)
  [super] LBA 460800..2689023 (8704 MB)
  [userdata] LBA 2689024..62476279 (233543 MB)
Touch I2C @ 0x11ed0000: CTRL 0x0 TIMING 0x20 FIFO_STAT 0x8000 IO_CFG 0x3
Touch FT3519T: FW_VER=0x0x70

[+] Booting Darwin / XNU...
XNU kernel 15607928 bytes, ramdisk 52224 bytes
gic_v3_irq_cpu_init: cleared EOImode on all cores
boot-args: debug=0x8 serial=3 rd=md0 -v cpus=8 small_cores_after=0 ufs=2 ufs_shared_pa=0x60004000

=== SCREEN CAPTURE (decoded via iso_font) ===
[screen: 1304 cells lit, 774 read as characters, last text row 150]
=== END OF SCREEN CAPTURE ===
=== XNU log (from DRAM) ===
GenericARMPE: 8 of 8 processors are running
Darwin Kernel Version 22.5.0: xnu-8796.121.2
```

---

## License

* `mtkloader/` and tooling: MIT License
* `kernel/` and XNU components: Apple Public Source License (APSL 2.0)
* No proprietary Apple binaries, vendor firmware, or user data are stored in this repository.

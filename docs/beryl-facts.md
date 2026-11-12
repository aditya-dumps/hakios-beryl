# Hardware Facts: Redmi Note 14 5G (beryl, MT6855)

All facts and numbers below are extracted directly from the live device (`ZHT4IB59XSUKAELR`), `/sys/firmware/fdt` (decompiled to DTS), `/proc/iomem`, `/proc/cpuinfo`, and sysfs.

## 1. Identity & SoC
* **Codename**: `beryl`
* **Marketing Name**: Redmi Note 14 5G / Dimensity 7025 Ultra
* **SoC Model**: `MT6855` (`MT6855V_A/ATZA`)
* **DT Compatible**: `"mediatek,MT6855"`
* **Root Address Cells**: `#address-cells = <0x2>;`
* **Root Size Cells**: `#size-cells = <0x2>;`
* **Source**: `/sys/devices/soc0/soc_id`, `fdt.dts` root node (`model`, `compatible`)

## 2. Memory (DRAM) & Reserved Zones
* **Physical DRAM Base**: `0x40000000` (1 GB physical mark)
* **Physical DRAM Size**: 8 GB LPDDR4X (`0x200000000` bytes, range `0x40000000` - `0x23fffffff`)
* **LK Kernel Load Address (KERNEL_PA)**: `0x40080000` (boot image header & `/proc/iomem`)
* **Free Safe DRAM Range for XNU**: `0x80000000` to `0xf0000000` (or `0x140000000` upper window)
* **Source**: `/proc/iomem`, `/proc/meminfo`, `fdt.dts` `/memory`

## 3. Ramoops & Console Zones (pstore)
* **Ramoops Total Range**: `0x48090000` - `0x48170000` (size `0xe0000` = 896 KB, node `mblock-2-pstore`)
* **Dump / Oops Zone**: `0x48090000`, size `0x20000` (128 KB)
* **Console Log Zone (`RAMOOPS_CONSOLE`)**: `0x480b0000`, size `0x40000` (256 KB)
  * Accessible on Android as `/sys/fs/pstore/console-ramoops-0`
* **Pmsg Zone (`RAMOOPS_PMSG`)**: `0x480f0000`, size `0x80000` (512 KB)
  * Accessible on Android as `/sys/fs/pstore/pmsg-ramoops-0` and `/dev/pmsg0`
* **Request Marker**: `DARWIN-BERYL:BOOT-XNU`
* **Source**: `fdt.dts` `bootargs` (`ramoops.mem_address=0x48090000 ramoops.mem_size=0xe0000 ramoops.pmsg_size=0x80000 ramoops.console_size=0x40000`), `/sys/fs/pstore`

## 4. CPUs & MPIDR Mapping
* **Total Cores**: 8 cores (Heterogeneous Big.LITTLE)
* **Enable Method**: `"psci"` (`arm,psci-1.0` via SMC)
* **Cluster 0 (Little Cores, 6x Cortex-A55)**:
  * `cpu@000`: MPIDR `0x000`, clock `2000 MHz` (`0x77359400` Hz)
  * `cpu@001`: MPIDR `0x100`, clock `2000 MHz`
  * `cpu@002`: MPIDR `0x200`, clock `2000 MHz`
  * `cpu@003`: MPIDR `0x300`, clock `2000 MHz`
  * `cpu@004`: MPIDR `0x400`, clock `2000 MHz`
  * `cpu@005`: MPIDR `0x500`, clock `2000 MHz`
* **Cluster 1 (Big Cores, 2x Cortex-A78)**:
  * `cpu@100`: MPIDR `0x600`, clock `2200 MHz` (`0x83215600` Hz)
  * `cpu@101`: MPIDR `0x700`, clock `2200 MHz`
* **Core Order for XNU (Boot core first, then bigs, then littles)**:
  * `{ 0x0, 0x600, 0x700, 0x100, 0x200, 0x300, 0x400, 0x500 }`
* **Source**: `fdt.dts` `/cpus`, `/proc/cpuinfo`

## 5. Interrupt Controller (GIC)
* **Architecture**: ARM GICv3 (`arm,gic-v3`)
* **GICD (Distributor) Base**: `0x0c000000`, size `0x40000` (256 KB)
* **GICR (Redistributors) Base**: `0x0c040000`, size `0x200000` (2 MB)
* **Redistributor Regions**: 1 region containing all 8 redistributors
* **Source**: `fdt.dts` `/interrupt-controller`, `/proc/iomem`

## 6. Storage (UFS)
* **Storage Type**: Universal Flash Storage (UFS 2.2)
* **Device**: Samsung UFS MCP `KM8F9001JM-B813` (256 GB)
* **UFS Host Controller Node**: `ufshci@112b0000`
* **UFS Controller Base**: `0x112b0000`, size `0x2300`
* **UFS Compatible**: `"mediatek,mt8183-ufshci"`
* **IRQ**: SPI 393 (`<0x0 0x189 0x4 0x0>`)
* **Boot Partition**: `/dev/block/by-name/boot_a` -> `/dev/block/sdc31` (134,217,728 bytes = 128 MB)
* **Source**: `fdt.dts` `/soc/ufshci@112b0000`, `/sys/block/sda/device/model`, `/dev/block/by-name/`

## 7. Display Engine & Panel
* **MMSYS / DISPSYS Base**: `0x14000000`, size `0x1000` (`mediatek,mt6855-mmsys`)
* **Mutex Base**: `0x14001000`, size `0x1000` (`disp_mutex0`)
* **Overlay Layer 0 (OVL0)**: `0x14002000`, size `0x1000` (`disp_ovl0`)
* **Overlay Layer 1 (OVL1_2L)**: `0x14004000`, size `0x1000` (`disp_ovl1_2l`)
* **RDMA0 Base**: `0x14006000`, size `0x1000` (`disp_rdma0`)
* **DSI Controller**: `0x14017000`, size `0x1000` (`dsi0`)
* **PWM Backlight**: `0x1100e000`, size `0x1000` (`disp_pwm0`)
* **Panel Name / LCM**: `dsi_panel_o17_38_0c_0a_fhdp_vdo_lcm_drv`
* **Resolution**: 1080 x 2400 (FHD+), 32-bit BGRA/ARGB (Pitch = 4320 bytes)
* **LK Framebuffer (atag,videolfb)**:
  * Base: `0xfe0c0000`
  * Size: `0x1df0000` (31,391,744 bytes ~ 30 MB, triple-buffered)
* **Source**: `fdt.dts` `/soc/dispsys_config@14000000`, `atag,videolfb`, `/proc/iomem`

## 8. Console UART
* **UART0 (Debug Serial)**: `0x11001000`, size `0x1000` (`serial@11001000`)
* **UART1**: `0x11002000`, size `0x1000` (`serial@11002000`)
* **Compatible**: `"mediatek,mt6577-uart"`
* **Baud rate**: 921600 / 115200
* **Source**: `fdt.dts` `/soc/serial@11001000`, `/proc/iomem`

## 9. Watchdog (TOPRGU)
* **Node**: `watchdog@1c007000`
* **Base (`TOPRGU_BASE`)**: `0x1c007000`, size `0x100`
* **Compatible**: `"mediatek,mt6855-wdt"`, `"mediatek,mt6589-wdt"`
* **Registers**:
  * `TOPRGU_MODE`: `0x1c007000`
  * `TOPRGU_LENGTH`: `0x1c007004`
  * `TOPRGU_RESTART`: `0x1c007008`
  * `TOPRGU_SWRST`: `0x1c007014`
* **Keys**:
  * `TOPRGU_MODE_KEY`: `0x22000000`
  * `TOPRGU_RESTART_KEY`: `0x1971`
  * `TOPRGU_SWRST_KEY`: `0x1209`
* **Source**: `fdt.dts` `/soc/watchdog@1c007000`, Linux `drivers/watchdog/mtk_wdt.c`

## 10. Touchscreen Controller
* **Chip**: FocalTech Touch IC (`focaltech@38`)
* **Compatible**: `"focaltech,fts"`
* **Bus**: I2C (`i2c@11ed0000`)
* **Reset GPIO**: GPIO 3 (`<0xc 0x3 0x1>`)
* **IRQ GPIO**: GPIO 22 (`<0xc 0x16 0x2>`)
* **Max Touch Points**: 10
* **Coordinates Range**: 0x0 - 0x437f x 0x0 - 0x95ff (scaled to 1080 x 2400)
* **Source**: `fdt.dts` `/i2c@11ed0000/focaltech@38`

## 11. Co-processors (SCP & CONNSYS)
* **SCP (System Companion Processor)**: `0x1c700000` (`scp@1c700000`)
* **CONNSYS (Connectivity Subsystem - Wi-Fi/BT)**: `0x18002000` (`consys@18002000`, compatible `"mediatek,mt6855-consys"`)
* **Source**: `fdt.dts` `/soc/scp@1c700000`, `/soc/consys@18002000`

## 12. GPU Subsystem
* **GPU**: Imagination PowerVR B-Series BXM-8-256 (Architecture: Rogue `RGX`, BVNC: `35.3.408.101`)
* **Driver DDK**: Rogue DDK Android 25.1@6715691 (`pvrsrvkm`)
* **Power & Clocks**: `clk_mt6855_img`, `gpueb` at `0x13c40000`
* **Note**: Not ARM Mali; Metal bringup requires PowerVR driver or CPU rendering.
* **Source**: `/proc/pvr/version`, `/sys/module/pvrsrvkm`

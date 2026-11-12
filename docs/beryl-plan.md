# Bring-up Plan: Redmi Note 14 5G (beryl, MT6855)

This document defines the strict, ordered bring-up steps for HakiOS / XNU on `beryl`, following the evidence rules (no step begins until the previous step's evidence is verified in `/sys/fs/pstore/console-ramoops-0`).

---

## Phase 0: Facts & Environmental Integrity (COMPLETED)
* **Goal**: Establish board constants from live hardware without guesswork.
* **Evidence Verified**:
  * Root ADB functional (`uid=0`), unlocked bootloader.
  * Stock `boot_a` backed up to `stock_boot_a.img` (SHA256 verified match).
  * FDT pulled from `/sys/firmware/fdt` and decompiled to DTS.
  * Complete facts documented in `docs/beryl-facts.md`.

---

## Phase 1: Execution & Logging Proof (`fbdiag`)
* **Goal**: Prove arbitrary bare-metal code executed from LK in `boot_a` runs, survives, and logs into ramoops across warm reset.
* **Mechanism**:
  * Build `fbdiag` configured with `beryl` constants:
    * `KERNEL_PA = 0x40080000`
    * `RAMOOPS_CONSOLE = 0x480b0000`
    * `RAMOOPS_CONSOLE_SIZE = 0x40000`
    * `LK_FB_BASE = 0xfe0c0000`, `LK_FB_PITCH = 4320`, `PANEL_W = 1080`, `PANEL_H = 2400`
    * `TOPRGU_BASE = 0x1c007000`
  * Chain in front of Android kernel using `chainboot.py`.
  * Flash `boot_a` only.
  * Phone executes `fbdiag`, draws diagnostic bars, writes register state (CurrentEL, SCTLR, CPACR, MPIDR, CNTFRQ) to ramoops, and chains back into Android.
* **Evidence Required**:
  * `/sys/fs/pstore/console-ramoops-0` begins with `fbdiag: phase 1` and prints CPU registers.

---

## Phase 2: Chained Loader (`mtkloader`) & PMSG Trigger
* **Goal**: Prove the bare-metal loader chains safely into Android by default and triggers only when `DARWIN-BERYL:BOOT-XNU` is written to `/dev/pmsg0`.
* **Mechanism**:
  * Fork `mtkloader` into `beryl/mtkloader/`.
  * Replace platform constants with `beryl` facts.
  * Test with `-DTEST_MODE=1` (no kernel started yet, logs to ramoops, warm reset back to Android).
* **Evidence Required**:
  * Loader banner and diagnostic memory/register dump in `console-ramoops-0`.

---

## Phase 3: Hardware Timers & GICv3 Configuration
* **Goal**: Initialize ARM GICv3 distributor (`0x0c000000`) and redistributors (`0x0c040000`) without lockup.
* **Mechanism**:
  * Verify `ICC_CTLR_EL1.EOImode` is cleared so timer interrupts don't hang.
  * Arm virtual timer (PPI 27) and confirm CNTVCT/CNTPCT progression.
* **Evidence Required**:
  * Log prints timer ticks and interrupt handling before kernel handoff.

---

## Phase 4: First Kernel Boot (Minimal XNU)
* **Goal**: Boot Apple XNU kernel (`xnu-8796.121.2`) on 1 core (`cpus=1`).
* **Mechanism**:
  * Build XNU kernel targeting MediaTek platform with minimal config.
  * Loader constructs Apple device tree (`chosen`, `cpus`, `memory`, `arm-io`).
  * Loader hooks kernel console output into memory log buffer.
  * Run limited duration (`XNU_SECS=60`).
  * Watchdog / loader returns back to Android.
* **Evidence Required**:
  * Darwin kernel version string in `console-ramoops-0`.
  * Launchd PID 1 or early Mach subsystem initialization.

---

## Phase 5: Multi-core SMP (All 8 Cores)
* **Goal**: Bring up remaining 7 cores via PSCI SMC calls (`psci_smp.c`).
* **Core Sequence**:
  * Core 0: MPIDR 0x000 (Boot, A55)
  * Core 1: MPIDR 0x600 (Big, A78)
  * Core 2: MPIDR 0x700 (Big, A78)
  * Cores 3-7: MPIDR 0x100 - 0x500 (Little, A55)
* **Evidence Required**:
  * "Started CPU x" for all cores 0 through 7 in the log.

---

## Phase 6: Framebuffer Console & Visual Output
* **Goal**: CPU rendering on the 1080x2400 panel.
* **Mechanism**:
  * Disable per-pixel alpha on LK's OVL0 layer.
  * Set up `simplefb` / EFI linear framebuffer console at `0xfe0c0000`.
* **Evidence Required**:
  * Text console and Apple boot logo visible on physical phone screen.

---

## Phase 7: UFS Storage Driver & Userland Root
* **Goal**: Read-only mount of `xnusys` partition from Samsung UFS.
* **Mechanism**:
  * Implement UFS read driver for `ufshci@112b0000` (LK leaves controller active).
  * Flash small root (`root.apfs`) or carve `xnusys` partition.
* **Evidence Required**:
  * XNU root mount succeeds from flash; launchd starts iOS services.

---

## Phase 8: Input & Peripherals (Touch, Buttons, Sensors)
* **Order**:
  1. Buttons: Power and volume keys (PMIC wrapper).
  2. Touch: FocalTech FTS over I2C (`i2c@11ed0000`).
  3. SCP sensor hub.
  4. Radio / CONNSYS (MT6855).

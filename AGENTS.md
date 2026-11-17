# AGENTS.md - Project Rules for Redmi Note 14 5G (beryl, MT6855)

Guidelines and invariants for AI agents working on booting genuine Apple iOS 16.5 (Darwin 22.5.0) on Redmi Note 14 5G (`beryl`, MediaTek MT6855).

## Core Directives & Quality Gates

1. **No Task Polling / Zero Token Waste**:
   - NEVER call `manage_task` in a loop to check background command status or poll running tasks.
   - Run short commands synchronously with adequate `WaitMsBeforeAsync` (e.g. 10000ms). For long background tasks, finish the turn and rely purely on reactive wakeup.

2. **Batch Diagnostic Enforcement (>= 12 Errors Per Iteration)**:
   - On EVERY iteration, thoroughly inspect kernel logs, pstore, userland plists, loader code, and device tree properties to identify at least **12 errors** simultaneously.
   - Never stop at 1 error or blame a single failure. Group and resolve or bypass 12+ issues in every turnaround.

3. **Bypass Over Blocking (Fast-Path Progress to Broken GUI)**:
   - If an error or subsystem fix is complex, time-consuming, or blocks the boot progress, implement a clean non-blocking stub or bypass (e.g. `mov w0, #0; ret`, relaxed assertions, or non-fatal fallbacks) rather than getting stalled.
   - Goal is to display the GUI (even if broken / partial / missing non-essential daemons) as fast as possible.

4. **Strict Partition Safety**:
   - Always flash strictly to `/dev/block/by-name/boot_a` with `bs=4096 conv=fsync`.
   - **NEVER TOUCH `/dev/block/by-name/boot_b`** under any circumstance. It is the fail-safe Android recovery partition.

5. **Guaranteed DRAM Survival & Two-Step Warm Reset Invariant**:
   - Never allow userland or kernel to trigger PSCI cold system resets (`0x84000009`), which power off DRAM banks and destroy pstore ramoops.
   - MediaTek MT6855 requires a mandatory two-step sequence: first write `TOPRGU_MODE_KEY | 0x43` (`0x22000043`) to `0x1c007000`, then write `TOPRGU_SWRST_KEY` (`0x1209`) to `0x1c007014`. Writing `0x1209` alone without arming `TOPRGU_MODE` is ignored by hardware.

6. **Reliable Boot Trigger Arming**:
   - To trigger iOS boot from Android, always write `boot-ios` using root-safe pipes:
     `adb shell "su -c 'printf \"boot-ios\" | dd of=/dev/block/by-name/misc bs=8 count=1 conv=fsync'"`
   - Never use direct unescaped shell redirection (`> /dev/block/...`), which gets evaluated by the unprivileged shell before `su` executes.

7. **Ramoops & PStore Log Recovery**:
   - When Android boots after an iOS run, always inspect `/data/debuglogger/console-ramoops-0` and `/data/mqsas/temp/pstore/` in addition to `/sys/fs/pstore/`, as Xiaomi MIUI/HyperOS daemon sweeps ramoops into these vendor directories.

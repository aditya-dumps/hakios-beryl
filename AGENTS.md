# AGENTS.md - Project Rules for Redmi Note 14 5G (beryl, MT6855)

Guidelines and invariants for AI agents working on booting genuine Apple iOS 16.5 (Darwin 22.5.0) on Redmi Note 14 5G (`beryl`, MediaTek MT6855).

## Core Directives & Quality Gates

1. **Batch Diagnostic Enforcement (>= 12 Errors Per Iteration)**:
   - On EVERY iteration, thoroughly inspect kernel logs, pstore, userland plists, loader code, and device tree properties to identify at least **12 errors** simultaneously.
   - Never stop at 1 error or blame a single failure. Group and resolve or bypass 12+ issues in every turnaround.

2. **Bypass Over Blocking (Fast-Path Progress to Broken GUI)**:
   - If an error or subsystem fix is complex, time-consuming, or blocks the boot progress, implement a clean non-blocking stub or bypass (e.g. `mov w0, #0; ret`, relaxed assertions, or non-fatal fallbacks) rather than getting stalled.
   - Goal is to display the GUI (even if broken / partial / missing non-essential daemons) as fast as possible.

3. **Strict Partition Safety**:
   - Always flash strictly to `/dev/block/by-name/boot_a` with `bs=4096 conv=fsync`.
   - **NEVER TOUCH `/dev/block/by-name/boot_b`** under any circumstance. It is the fail-safe Android recovery partition.

4. **Guaranteed DRAM Survival & Warm Reset Invariant**:
   - Never allow userland or kernel to trigger PSCI cold system resets (`0x84000009`), which power off DRAM banks and destroy pstore ramoops.
   - Always route reboots and panics through MediaTek `TOPRGU_SWRST` (`0x1c007014 = 0x1209`) with `TOPRGU_MODE` configured, guaranteeing clean DRAM survival and instant ramoops rescue across resets.

5. **Ramoops & PStore Log Recovery**:
   - When Android boots after an iOS run, always inspect `/data/debuglogger/console-ramoops-0` and `/data/mqsas/temp/pstore/` in addition to `/sys/fs/pstore/`, as Xiaomi MIUI/HyperOS daemon sweeps ramoops into these vendor directories.

6. **XNU W^X Executable Section Enforcement**:
   - In XNU 22.5.0, `__TEXT` is mapped read-only (`R--`, `NX` bit enabled).
   - NEVER place executable code, trampolines, or hooks in `__TEXT` or data segments.
   - All code patches and trampolines MUST reside in `__TEXT_EXEC` (`RX`) (e.g. using verified NOP/padding ranges such as `0xfffffff007451260`).

7. **Null-Safe Struct Offset Getters**:
   - Helper functions that compute member addresses via offsets (such as `get_bsdthread_info(th)` adding `0x580`) MUST check for NULL first (`cbz x0, ret; add x0, x0, #offset; ret`).
   - Never allow `NULL + offset` to produce non-zero pseudo-pointers that trick `assert(ptr != NULL)` and crash later on page 0 data aborts.

8. **Zero-Token-Waste Session Hand-Off (`resume.md`)**:
   - Before completing major turnaround milestones, context compression, or chat migration, maintain and update `resume.md` and `README.md`.
   - Include exact run timestamps, PC/LR crash vectors, file offsets, backtraces, active binary patches, and immediate next steps so that subsequent sessions require minimal context reading.

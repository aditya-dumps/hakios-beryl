/*
 * mtkloader entry for Redmi Note 14 5G (beryl, MT6855).
 * LK starts this as a Linux arm64 Image at 0x40000000, MMU and caches off, x0 = dtb.
 * All memory is device memory until XNU turns MMU on, so built with strict alignment.
 */
.global _start
.global jump_to_kernel
.global chain_stub
.global chain_stub_end
.global xnu_return_stub
.global psci_system_reset
.global psci_cpu_on
.global watcher_entry
.global mmu_on
.global dcache_clean_all
.global dcache_clean_range
.global flush_idcache_range
.global irq_wait
.global ic_invalidate_all
.section .text.boot

_start:
    /* Linux ARM64 Image header (64 bytes); chainboot.py fills image_size, res2, res3 */
    b       primary_entry       /* code0 */
    .word   0                   /* code1 */
    .quad   0x0                 /* text_offset: 0x0 on MT6855 (matches stock kernel) */
    .quad   0x02000000          /* image_size */
    .quad   0x0a                /* flags: little-endian, 4K pages, anywhere */
    .quad   0                   /* res2: length of Android's Image (at CHAIN_OFFSET) */
    .quad   0                   /* res3: offset of the XNU payload ("XNUP") from _start */
    .quad   0                   /* res4 */
    .ascii  "ARM\x64"
    .word   0

primary_entry:
    msr     daifset, #0xf
    mov     x19, x0

    mrs     x1, CurrentEL
    lsr     x1, x1, #2
    adrp    x2, mtk_vectors
    add     x2, x2, :lo12:mtk_vectors
    cmp     x1, #2
    b.ne    10f
    msr     vbar_el2, x2
    b       20f
10: msr     vbar_el1, x2
20:
    /* Clear BSS first */
    ldr     x0, =__bss_start
    ldr     x1, =__bss_end
1:  cmp     x0, x1
    b.ge    2f
    str     xzr, [x0], #8
    b       1b
2:
    /* Stack in BSS (safely inside DRAM at 0x40000000+) */
    ldr     x0, =__stack_top
    mov     sp, x0

    mov     x0, x19
    bl      mtkloader_main
3:  wfe
    b       3b

/* jump_to_kernel(entry_pa, boot_args_pa): enter XNU at EL1h, MMU and caches off */
jump_to_kernel:
    msr     daifset, #0xf
    mov     x16, x0
    mov     x0, x1
    mrs     x2, CurrentEL
    lsr     x2, x2, #2
    cmp     x2, #2
    b.ne    1f
    mov     x2, #(1 << 31)      /* HCR_EL2.RW: EL1 is AArch64 */
    msr     hcr_el2, x2
    mov     x2, #0x3c5          /* EL1h, DAIF masked */
    msr     spsr_el2, x2
    msr     elr_el2, x16
    dsb     sy
    ic      iallu
    dsb     sy
    isb
    eret
1:  mrs     x2, sctlr_el1
    bic     x2, x2, #0x1
    bic     x2, x2, #0x4
    bic     x2, x2, #0x1000
    msr     sctlr_el1, x2
    isb
    dsb     sy
    ic      iallu
    dsb     sy
    isb
    br      x16

/*
 * chain_stub(dtb, dst, src, len, entry): copy Android's Image down over this program
 * and enter it as LK would have. C copies the stub out of the way first. Position independent.
 */
chain_stub:
    msr     daifset, #0xf       /* Immediately mask all interrupts and aborts */
    mov     x19, x0             /* x19 = dtb */
    mov     x20, x1             /* x20 = dst start (0x40000000) */
    mov     x21, x3             /* x21 = len (image_size) */
    mov     x22, x4             /* x22 = entry (0x40000000) */

    /* Copy loop: 32 bytes per iteration using standard integer registers */
    mov     x10, x20            /* x10 = write pointer */
    mov     x11, x2             /* x11 = read pointer */
    mov     x12, x21            /* x12 = remaining bytes */

1:  ldp     x6, x7, [x11], #16
    ldp     x8, x9, [x11], #16
    stp     x6, x7, [x10], #16
    stp     x8, x9, [x10], #16
    subs    x12, x12, #32
    b.hi    1b

    dsb     sy
    ic      iallu
    dsb     sy
    isb

    /* Register handover strictly matching Linux ARM64 boot protocol */
    mov     x0, x19             /* x0 = dtb */
    mov     x1, xzr             /* x1 = 0 */
    mov     x2, xzr             /* x2 = 0 */
    mov     x3, xzr             /* x3 = 0 */
    br      x22

9:  wfe
    b       9b
chain_stub_end:

/*
 * XNU return stub: when XNU ends or panics, comes back here.
 */
xnu_return_stub:
    msr     daifset, #0xf
    mov     x19, x0
    mov     x20, x1
    mov     x21, x2
    mov     x22, x3
    mov     x23, x4
    mov     x24, x5
    mov     x25, x29
    mov     x26, x30
    bl      dcache_clean_all
    mrs     x9, sctlr_el1
    bic     x9, x9, #0x1
    bic     x9, x9, #0x4
    bic     x9, x9, #0x1000
    msr     sctlr_el1, x9
    isb
    dsb     sy
    ic      iallu
    dsb     sy
    isb
    tlbi    vmalle1
    dsb     sy
    isb
    adrp    x9, mtk_vectors
    add     x9, x9, :lo12:mtk_vectors
    msr     vbar_el1, x9
    adrp    x9, xnu_fp
    add     x9, x9, :lo12:xnu_fp
    str     x25, [x9]
    str     x26, [x9, #8]
    mrs     x10, tcr_el1
    str     x10, [x9, #16]
    mrs     x10, ttbr1_el1
    str     x10, [x9, #24]
    ldr     x9, =__stack_top
    mov     sp, x9
    mov     x0, x19
    mov     x1, x20
    mov     x2, x21
    mov     x3, x22
    mov     x4, x23
    mov     x5, x24
    bl      xnu_returned
1:  wfe
    b       1b

/* Clean and invalidate all caches by set/way */
dcache_clean_all:
    mrs     x0, clidr_el1
    and     w3, w0, #0x07000000
    lsr     w3, w3, #23          /* LoC * 2 */
    cbz     w3, 5f
    mov     w10, #0              /* level * 2 */
1:  add     w2, w10, w10, lsr #1 /* level * 3 */
    lsr     w1, w0, w2
    and     w1, w1, #7
    cmp     w1, #2
    b.lt    4f
    msr     csselr_el1, x10
    isb
    mrs     x1, ccsidr_el1
    and     w2, w1, #7
    add     w2, w2, #4           /* log2(line size) */
    ubfx    w4, w1, #3, #10      /* ways - 1 */
    clz     w5, w4
    ubfx    w7, w1, #13, #15     /* sets - 1 */
2:  mov     w9, w4
3:  lsl     w6, w9, w5
    orr     w11, w10, w6
    lsl     w6, w7, w2
    orr     w11, w11, w6
    dc      cisw, x11
    subs    w9, w9, #1
    b.ge    3b
    subs    w7, w7, #1
    b.ge    2b
4:  add     w10, w10, #2
    cmp     w3, w10
    b.gt    1b
5:  dsb     sy
    isb
    ret

/* PSCI SYSTEM_RESET */
psci_system_reset:
    ldr     x0, =0x84000009
    smc     #0
    ret

/* psci_cpu_on(mpidr, entry_pa, context) */
psci_cpu_on:
    mov     x3, x2
    mov     x2, x1
    mov     x1, x0
    ldr     x0, =0xc4000003
    smc     #0
    ret

.global smc_call
smc_call:
    smc     #0
    ret

/* Watcher core entry */
watcher_entry:
    msr     daifset, #0xf
    adrp    x9, mtk_vectors
    add     x9, x9, :lo12:mtk_vectors
    msr     vbar_el1, x9
    ldr     x9, =__watcher_stack_top
    mov     sp, x9
    bl      watcher_main
1:  wfe
    b       1b

/* mmu_on(l1_table_pa) */
mmu_on:
    ldr     x1, =0xff00
    msr     mair_el1, x1
    ldr     x1, =0x200803519     /* IPS 40 bit, EPD1, SH0 inner, ORGN0/IRGN0 WB, T0SZ 25 */
    msr     tcr_el1, x1
    msr     ttbr0_el1, x0
    isb
    tlbi    vmalle1
    dsb     sy
    isb
    mrs     x1, sctlr_el1
    orr     x1, x1, #0x1
    orr     x1, x1, #0x4
    orr     x1, x1, #0x1000
    msr     sctlr_el1, x1
    isb
    ret

/* dcache_clean_range(va, len) */
dcache_clean_range:
    add     x1, x0, x1
    bic     x0, x0, #63
1:  dc      civac, x0
    add     x0, x0, #64
    cmp     x0, x1
    b.lo    1b
    dsb     sy
    ret

/* dcache_inval_range(va, len) */
.global dcache_inval_range
dcache_inval_range:
    add     x1, x0, x1
    bic     x0, x0, #63
1:  dc      ivac, x0
    add     x0, x0, #64
    cmp     x0, x1
    b.lo    1b
    dsb     sy
    ret

/*
 * flush_idcache_range(va, len)
 * Cleans D-cache and invalidates I-cache across [va, va + len).
 * Architectural EL1-safe sequence for newly placed code.
 */
flush_idcache_range:
    cbz     x1, 9f
    add     x2, x0, x1          /* x2 = end */
    bic     x3, x0, #63         /* align start to 64-byte */
1:  dc      civac, x3
    add     x3, x3, #64
    cmp     x3, x2
    b.lo    1b
    dsb     ish

    bic     x3, x0, #63
2:  ic      ivau, x3
    add     x3, x3, #64
    cmp     x3, x2
    b.lo    2b
    dsb     ish
    isb
9:  ret

/*
 * irq_wait(ticks): unmask IRQs and wait for timer interrupt.
 * Uses cntvct_el0 (virtual counter) because cntpct_el0 is trapped at EL1 on MT6855.
 */
irq_wait:
    mov     x19, x0
    msr     daifclr, #0x3        /* IRQ and FIQ on */
    isb
1:  isb
    mrs     x0, cntvct_el0       /* virtual counter (does NOT trap to EL2) */
    cmp     x0, x19
    b.lo    1b
    msr     daifset, #0xf
    isb
    adrp    x0, irq_count
    add     x0, x0, :lo12:irq_count
    ldr     x0, [x0]
    ret

/* IRQ at EL1 */
irq_entry:
    sub     sp, sp, #0x60
    stp     x0, x1, [sp, #0x00]
    stp     x2, x3, [sp, #0x10]
    stp     x4, x5, [sp, #0x20]
    mrs     x0, ICC_IAR1_EL1
    adrp    x1, irq_count
    add     x1, x1, :lo12:irq_count
    ldr     x2, [x1]
    add     x2, x2, #1
    str     x2, [x1]
    adrp    x1, irq_intid
    add     x1, x1, :lo12:irq_intid
    str     x0, [x1]
    mov     x3, #2               /* IMASK: stop timer from repeating */
    msr     cntv_ctl_el0, x3
    msr     cntp_ctl_el0, x3
    isb
    cmp     x0, #1020
    b.hs    1f
    msr     ICC_EOIR1_EL1, x0
    isb
1:  ldp     x0, x1, [sp, #0x00]
    ldp     x2, x3, [sp, #0x10]
    ldp     x4, x5, [sp, #0x20]
    add     sp, sp, #0x60
    eret

.macro vec off
    .balign 0x80
    mov     x0, #\off
    b       fault_common
.endm

fault_common:
    mrs     x4, CurrentEL
    lsr     x4, x4, #2
    cmp     x4, #2
    b.ne    1f
    mrs     x1, esr_el2
    mrs     x2, elr_el2
    mrs     x3, far_el2
    b       2f
1:  mrs     x1, esr_el1
    mrs     x2, elr_el1
    mrs     x3, far_el1
2:  ldr     x5, =__fault_stack_top
    mov     sp, x5
    bl      loader_fault
3:  wfe
    b       3b

    .balign 0x800
mtk_vectors:
    vec 0x000
    .balign 0x80
    b       irq_entry
    vec 0x100
    vec 0x180
    vec 0x200
    .balign 0x80
    b       irq_entry
    vec 0x300
    vec 0x380
    vec 0x400
    vec 0x480
    vec 0x500
    vec 0x580
    vec 0x600
    vec 0x680
    vec 0x700
    vec 0x780

/* Safe instruction cache invalidation at EL1 and EL2 */
ic_invalidate_all:
    mrs     x0, CurrentEL
    lsr     x0, x0, #2
    cmp     x0, #2
    b.lo    1f
    ic      iallu
    isb
    ret
1:  dsb     sy
    isb
    ret

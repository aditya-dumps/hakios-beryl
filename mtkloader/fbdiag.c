/*
 * fbdiag: does code that LK boots run, where is the framebuffer the panel shows, and how is
 * OVL0 set up? Packed in front of Android's kernel (tools/chainboot.py). Read-only on the display
 * hardware. Results go on the screen and into the ramoops console; after FBDIAG_SECONDS it
 * starts Android's kernel, and the report is /sys/fs/pstore/console-ramoops-0.
 */
#include <stdint.h>
#include "mtkdbg.h"

#define FBDIAG_SECONDS 3

#define CHAIN_OFFSET  0x40000u
#define KERNEL_PA     0x40080000ULL
#define STUB_PA       0x40070000ULL

extern char _start[];
extern char chain_stub[], chain_stub_end[];
static uint64_t chain_dtb;

static uint64_t sysreg_el(void)
{
	uint64_t v;
	__asm__ volatile("mrs %0, CurrentEL" : "=r"(v));
	return (v >> 2) & 3;
}

static void report_sysregs(void)
{
	uint64_t el = sysreg_el(), sctlr = 0, cpacr = 0, mpidr = 0;

	if (el == 2) {
		__asm__ volatile("mrs %0, sctlr_el2" : "=r"(sctlr));
	} else if (el == 1) {
		__asm__ volatile("mrs %0, sctlr_el1" : "=r"(sctlr));
	}
	__asm__ volatile("mrs %0, cpacr_el1" : "=r"(cpacr));
	__asm__ volatile("mrs %0, mpidr_el1" : "=r"(mpidr));
	dbg_puts("EL");
	dbg_dec(el);
	dbg_puts(" SCTLR=");
	dbg_hex(sctlr, 8);
	dbg_puts(" CPACR=");
	dbg_hex(cpacr, 8);
	dbg_puts(" MPIDR=");
	dbg_hex(mpidr, 8);
	dbg_puts(" CNTFRQ=");
	dbg_dec(dbg_freq());
	dbg_putc('\n');
}

static void bar(uint32_t y, uint32_t color, const char *label)
{
	fb_rect(0, y, PANEL_W, 48, color);
	uint32_t saved_y = fbc.y, saved_x = fbc.x, saved_bg = fbc.bg, saved_fg = fbc.fg;
	uint64_t saved_base = fbc.base;
	fbc.x = 24;
	fbc.y = y + 8;
	fbc.bg = 0xff000000u;
	fbc.fg = 0xffffffffu;
	while (*label) {
		fbcon_putc(*label++);
	}
	fbc.x = saved_x;
	fbc.y = saved_y;
	fbc.bg = saved_bg;
	fbc.fg = saved_fg;
	fbc.base = saved_base;
}

static void __attribute__((noreturn)) chain_android(void)
{
	const volatile uint32_t *img = (const volatile uint32_t *)((uint64_t)_start + CHAIN_OFFSET);
	const volatile uint64_t *hdr = (const volatile uint64_t *)_start;
	uint64_t image_size = (hdr[5] + 15) & ~15ULL;

	if (img[14] != 0x644d5241u) { /* "ARM\x64" */
		dbg_puts("no Linux Image: warm reset\n");
		dbg_delay_ms(2000);
		wdt_reset();
	}

	dbg_puts("chaining to Android kernel, ");
	dbg_dec(image_size);
	dbg_puts(" bytes at ");
	dbg_hex(KERNEL_PA, 10);
	dbg_puts("...\n");
	dbg_delay_ms(2000);

	volatile uint32_t *dst = (volatile uint32_t *)STUB_PA;
	const volatile uint32_t *src = (const volatile uint32_t *)chain_stub;
	for (uint64_t i = 0; i < (uint64_t)(chain_stub_end - chain_stub + 3) / 4; i++) {
		dst[i] = src[i];
	}
	__asm__ volatile("dsb sy; ic iallu; dsb sy; isb" ::: "memory");
	void (*stub)(uint64_t, uint64_t, uint64_t, uint64_t, uint64_t) = (void *)STUB_PA;
	stub(chain_dtb, KERNEL_PA, (uint64_t)img, image_size, KERNEL_PA);
	__builtin_unreachable();
}

static int in_fault = 0;
void fbdiag_fault(uint64_t vec, uint64_t esr, uint64_t elr, uint64_t far)
{
	if (in_fault++) {
		wdt_reset();
	}
	fbc.fg = 0xffff4040u;
	dbg_puts("\n*** FAULT vec=");
	dbg_hex(vec, 3);
	dbg_puts(" ESR=");
	dbg_hex(esr, 8);
	dbg_puts(" ELR=");
	dbg_hex(elr, 10);
	dbg_puts(" FAR=");
	dbg_hex(far, 10);
	dbg_puts("\n");
	dbg_delay_ms(10000);
	chain_android();
}

void fbdiag_main(uint64_t dtb)
{
	wdt_disable();
	plog_reset();
	chain_dtb = dtb;

	uint64_t fb = LK_FB_BASE;
	uint32_t pitch = LK_FB_PITCH;

	/* Leave the logo's top part; the report goes below a band of test bars. */
	fbcon_init(fb, pitch, 420, 2);
	fb_rect(0, 0, PANEL_W, 420, 0xff000000u);
	bar(0,   0xffff0000u, "A: red   alpha=ff");
	bar(60,  0xff00ff00u, "B: green alpha=ff");
	bar(120, 0xff0000ffu, "C: blue  alpha=ff");
	bar(180, 0x00ffffffu, "D: white alpha=00");
	bar(240, 0x80ffffffu, "E: white alpha=80");
	bar(300, 0xffffffffu, "F: white alpha=ff");

	fbc.scale = 2;
	fbc.y = 380;
	fbc.x = 0;
	fbc.fg = 0xff40ff40u;
	dbg_puts("fbdiag: phase 1 (Redmi Note 14 5G MT6855)\n");

	fbc.scale = 2;
	fbc.y = 420;
	fbc.x = 0;
	fbc.fg = 0xffffffffu;

	dbg_puts("== fbdiag (beryl MT6855) ==\nx0(dtb)=");
	dbg_hex(dtb, 10);
	dbg_putc('\n');
	report_sysregs();

	uint32_t wdt_status = rd32(TOPRGU_BASE + 0x0c);
	dbg_puts("WDT STATUS=");
	dbg_hex(wdt_status, 8);
	dbg_puts(" MODE=");
	dbg_hex(rd32(TOPRGU_MODE), 8);
	dbg_puts(" LENGTH=");
	dbg_hex(rd32(TOPRGU_LENGTH), 8);
	dbg_putc('\n');

	dbg_puts("LK Framebuffer: base=");
	dbg_hex(fb, 10);
	dbg_puts(" pitch=");
	dbg_dec(pitch);
	dbg_puts(" (1080x2400)\n");

	for (int s = FBDIAG_SECONDS; s > 0; s--) {
		dbg_puts("Booting Android in ");
		dbg_dec(s);
		dbg_puts(" s...\n");
		dbg_delay_ms(1000);
	}

	chain_android();
}

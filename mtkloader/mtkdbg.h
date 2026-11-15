/*
 * Debug output for bare-metal code on the Redmi Note 14 5G (beryl, MT6855):
 *
 *  - plog_*: the ramoops console zone that Android's pstore keeps across a warm reset. What is
 *    written here shows up after the next Android boot as /sys/fs/pstore/console-ramoops-0.
 *    Zone layout from Android's ramoops (mem 0x48090000 size 0xe0000, dump 0x20000, console 0x40000):
 *    dump records first, then console at 0x480b0000. Header: sig "DBGC" (0x43474244), start, size.
 *  - fbcon_*: text on the panel (FHD+ 1080x2400). OVL0 layer 0 scans LK's framebuffer continuously,
 *    so pixels written there appear on the next frame.
 *
 * Everything here is device memory (MMU off): no unaligned accesses, no SIMD, no dc zva.
 * Build with -mgeneral-regs-only -mstrict-align -fno-builtin.
 */
#ifndef MTKDBG_H
#define MTKDBG_H

#include <stdint.h>
#include "font8x16.h"

#define RAMOOPS_CONSOLE      0x480b0000ULL
#define RAMOOPS_CONSOLE_SIZE 0x40000u
#define RAMOOPS_SIG          0x43474244u

/* the pmsg zone: Android's request for one XNU boot comes in it (boot-xnu.sh), the kernel's lines for the
 * host go out in it (kern.hakios.host_keep) */
#define RAMOOPS_PMSG         0x480f0000ULL
#define RAMOOPS_PMSG_SIZE    0x80000u

#define TOPRGU_BASE          0x1c007000ULL
#define TOPRGU_MODE          (TOPRGU_BASE + 0x00)
#define TOPRGU_LENGTH        (TOPRGU_BASE + 0x04)
#define TOPRGU_RESTART       (TOPRGU_BASE + 0x08)
#define TOPRGU_SWRST         (TOPRGU_BASE + 0x14)
#define TOPRGU_MODE_KEY      0x22000000u
#define TOPRGU_RESTART_KEY   0x1971u
#define TOPRGU_SWRST_KEY     0x1209u

/* LK's framebuffer (atag,videolfb), the layer LK shows the logo on. */
#define LK_FB_BASE           0xfe0c0000ULL
#define LK_FB_PITCH          4352u       /* 1080 pixels * 4 bytes rounded to 64-byte alignment (DDP hardware) */
#define PANEL_W              1080u
#define PANEL_H              2400u
#define FB_SCREEN_SIZE       (LK_FB_PITCH * PANEL_H) /* 10,444,800 bytes per buffer */
#define FB_TOTAL_CLEAR_SIZE  (FB_SCREEN_SIZE * 3)    /* 31,334,400 bytes: all 3 buffers, ends at 0xffea2000 (safe) */

#define DISP_MUTEX_EN        0x14001020ULL
#define DISP_MUTEX_RUN       0x14001024ULL

#define OVL0_BASE            0x14002000ULL
#define OVL_SRC_CON          0x02c      /* a bit per layer the hardware composes */
#define OVL_L0_CON           0x030
#define OVL_L0_PITCH         0x044
#define OVL_L0_ADDR          0xf40

static inline uint32_t rd32(uint64_t a) { return *(volatile uint32_t *)a; }
static inline void wr32(uint64_t a, uint32_t v) { *(volatile uint32_t *)a = v; }

/* ---- time (pure instruction delay loops, safe from EL1 timer traps) ---- */

static inline void dbg_delay_us(uint32_t us)
{
	for (volatile uint64_t i = 0; i < (uint64_t)us * 10ULL; i++) {
		__asm__ volatile("yield");
	}
}

static inline void dbg_delay_ms(uint32_t ms)
{
	for (volatile uint64_t i = 0; i < (uint64_t)ms * 10000ULL; i++) {
		__asm__ volatile("yield");
	}
}

/* ---- watchdog ---- */

static inline void wdt_disable(void)
{
	wr32(TOPRGU_RESTART, TOPRGU_RESTART_KEY);
	wr32(TOPRGU_MODE, TOPRGU_MODE_KEY);
}

/* A warm reset, as Linux's mtk_wdt_restart does it: DRAM (and so pstore) survives. */
static inline void __attribute__((noreturn)) wdt_reset(void)
{
	wr32(TOPRGU_MODE, TOPRGU_MODE_KEY | 0x47u);
	wr32(TOPRGU_SWRST, TOPRGU_SWRST_KEY);
	for (;;) {
		__asm__ volatile("wfe");
	}
}

/* ---- ramoops console ---- */

struct ramoops_hdr {
	uint32_t sig;
	uint32_t start;
	uint32_t size;
};

#define PLOG_HDR  ((volatile struct ramoops_hdr *)RAMOOPS_CONSOLE)
#define PLOG_DATA ((volatile char *)(RAMOOPS_CONSOLE + sizeof(struct ramoops_hdr)))
#define PLOG_CAP  (RAMOOPS_CONSOLE_SIZE - sizeof(struct ramoops_hdr))

#define PMSG_HDR  ((volatile struct ramoops_hdr *)RAMOOPS_PMSG)
#define PMSG_DATA ((volatile char *)(RAMOOPS_PMSG + sizeof(struct ramoops_hdr)))
#define PMSG_CAP  (RAMOOPS_PMSG_SIZE - sizeof(struct ramoops_hdr))

extern void dcache_clean_all(void);

static inline void plog_reset(void)
{
	PLOG_HDR->sig = RAMOOPS_SIG;
	PLOG_HDR->start = 0;
	PLOG_HDR->size = 0;
	PMSG_HDR->sig = RAMOOPS_SIG;
	PMSG_HDR->start = 0;
	PMSG_HDR->size = 0;
	__asm__ volatile("dsb sy");
}

static inline void plog_flush(void)
{
	__asm__ volatile("dsb sy");
	dcache_clean_all();
	__asm__ volatile("dsb sy; isb");
}

static inline void plog_putc(char c)
{
	uint32_t at = PLOG_HDR->start, size = PLOG_HDR->size;

	if (PLOG_HDR->sig != RAMOOPS_SIG || at >= PLOG_CAP || size > PLOG_CAP) {
		PLOG_HDR->sig = RAMOOPS_SIG;
		at = size = 0;
	}
	PLOG_DATA[at] = c;
	if (++at == PLOG_CAP) {
		at = 0;
	}
	if (size < PLOG_CAP) {
		size++;
	}
	PLOG_HDR->start = at;
	PLOG_HDR->size = size;

	/* Mirror into PMSG */
	uint32_t pat = PMSG_HDR->start, psize = PMSG_HDR->size;
	if (PMSG_HDR->sig != RAMOOPS_SIG || pat >= PMSG_CAP || psize > PMSG_CAP) {
		PMSG_HDR->sig = RAMOOPS_SIG;
		pat = psize = 0;
	}
	PMSG_DATA[pat] = c;
	if (++pat == PMSG_CAP) {
		pat = 0;
	}
	if (psize < PMSG_CAP) {
		psize++;
	}
	PMSG_HDR->start = pat;
	PMSG_HDR->size = psize;
	__asm__ volatile("dsb sy");
}

/* ---- framebuffer text ---- */

struct fbcon {
	uint64_t base;
	uint32_t pitch, w, h;
	uint32_t x, y, top, scale;
	uint32_t fg, bg;
} __attribute__((aligned(8)));

extern volatile struct fbcon fbc;

static inline void fb_px(uint32_t x, uint32_t y, uint32_t c)
{
	if (x >= PANEL_W || y >= PANEL_H) {
		return;
	}
	uint64_t off = (uint64_t)y * (uint64_t)fbc.pitch + (uint64_t)x * 4;
	*(volatile uint32_t *)(fbc.base + off) = c;
}

static inline void fb_rect(uint32_t x0, uint32_t y0, uint32_t w, uint32_t h, uint32_t c)
{
	if (!fbc.base) {
		return;
	}
	for (uint32_t y = y0; y < y0 + h && y < fbc.h; y++) {
		for (uint32_t x = x0; x < x0 + w && x < fbc.w; x++) {
			fb_px(x, y, c);
		}
	}
	__asm__ volatile("dsb sy");
}

static inline void fbcon_init(uint64_t base, uint32_t pitch, uint32_t top, uint32_t scale)
{
	fbc.base = base;
	fbc.pitch = pitch;
	fbc.w = PANEL_W;
	fbc.h = PANEL_H;
	fbc.x = 24;
	fbc.y = fbc.top = top;
	fbc.scale = scale;
	fbc.fg = 0xffffffffu;
	fbc.bg = 0xff000000u;
}

static inline void fbcon_newline(void)
{
	uint32_t lh = 16 * fbc.scale;

	fbc.x = 24;
	fbc.y += lh;
	if (fbc.y + lh > fbc.h) {
		fbc.y = fbc.top;
	}
}

static inline void fbcon_putc(char c)
{
	uint32_t cw = 8 * fbc.scale;

	if (!fbc.base) {
		return;
	}
	if (c == '\n') {
		fbcon_newline();
		return;
	}
	if (c == '\r') {
		fbc.x = 24;
		return;
	}
	if ((unsigned char)c < 0x20 || (unsigned char)c > 0x7e) {
		c = '?';
	}
	if (fbc.x + cw > fbc.w) {
		fbcon_newline();
	}
	const unsigned char *g = font8x16[(unsigned char)c - 0x20];
	for (uint32_t row = 0; row < 16 * fbc.scale; row++) {
		unsigned char bits = g[row / fbc.scale];
		for (uint32_t col = 0; col < cw; col++) {
			fb_px(fbc.x + col, fbc.y + row, (bits & (0x80 >> (col / fbc.scale))) ? fbc.fg : fbc.bg);
		}
	}
	__asm__ volatile("dsb sy");
	fbc.x += cw;
}

/* ---- both ---- */

static inline void dbg_putc(char c)
{
	plog_putc(c);
	fbcon_putc(c);
}

static inline void dbg_puts(const char *s)
{
	while (*s) {
		dbg_putc(*s++);
	}
}

static inline void dbg_hex(uint64_t v, int digits)
{
	static const char hex[] = "0123456789abcdef";
	for (int i = (digits - 1) * 4; i >= 0; i -= 4) {
		dbg_putc(hex[(v >> i) & 0xf]);
	}
}

static inline void dbg_dec(uint64_t v)
{
	char buf[21];
	int n = 0;
	do {
		buf[n++] = (char)('0' + v % 10);
		v /= 10;
	} while (v);
	while (n) {
		dbg_putc(buf[--n]);
	}
}

#endif /* MTKDBG_H */

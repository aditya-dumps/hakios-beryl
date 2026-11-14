/*
 * mtkloader for Redmi Note 14 5G (beryl, MT6855):
 * Boots Darwin / XNU on MediaTek MT6855 from boot_a, and brings Android back
 * afterwards with XNU's log preserved in ramoops pstore.
 *
 * Boot flow:
 * 1. LK loads boot_a at 0x40080000 as arm64 Linux Image.
 * 2. mtkloader checks /dev/pmsg0 in RAM for trigger flag: "DARWIN-BERYL:BOOT-XNU".
 * 3. Default: if no trigger flag is set, chain to stock Android kernel in 2s.
 * 4. If triggered: prepare GICv3 (clear EOImode), arm TOPRGU watchdog, and jump to XNU.
 */
#include <stdint.h>
#include <stddef.h>
#include "mtkdbg.h"
#include "identity.h"

/* XNU physical DRAM range on MT6855:
 * Physical DRAM starts at 0x40000000 (8 GB total).
 * We place XNU at 0x80000000 (above low DRAM reservations).
 * Safe 32-bit window extends up to LK framebuffer at 0xfe0c0000.
 */
#define XNU_PHYS_BASE       0x80000000ULL
#define XNU_MEM_SIZE        (LK_FB_BASE - XNU_PHYS_BASE) /* ~2016 MB */

#define SYSTEM_PA           (XNU_PHYS_BASE + 0x08000000ULL)
#define SYSTEM_PART         "xnusys"

#define KERNEL_VIRT_BASE    0xfffffff004000000ULL
#define XNU_SLIDE           (XNU_PHYS_BASE - KERNEL_VIRT_BASE)
#define PAGE_SIZE_MAX       0x4000ULL

#ifndef XNU_WDT_SECONDS
#define XNU_WDT_SECONDS     20
#endif

#ifndef XNU_CORES
#define XNU_CORES           8
#endif

/* MT6855 (8 cores):
 * Cluster 0 (Cortex-A55 @ 2.0 GHz): MPIDR 0x000, 0x100, 0x200, 0x300, 0x400, 0x500
 * Cluster 1 (Cortex-A78 @ 2.2 GHz): MPIDR 0x600, 0x700
 * Bring-up order: { 0x000, 0x600, 0x700, 0x100, 0x200, 0x300, 0x400, 0x500 }
 */
static const uint16_t core_order[8] = { 0x000, 0x600, 0x700, 0x100, 0x200, 0x300, 0x400, 0x500 };

#ifndef XNU_CHECKPOINT
#define XNU_CHECKPOINT      0
#endif

#ifndef XNU_RETURN_AFTER
#define XNU_RETURN_AFTER    "5"
#endif

#ifndef TIMER_PROBE
#define TIMER_PROBE         0
#endif

#ifndef MENU_DEFAULT_XNU
#define MENU_DEFAULT_XNU    0
#endif

#ifndef XNU_VERBOSE
#define XNU_VERBOSE         1
#endif

#ifndef XNU_SERIAL
#define XNU_SERIAL          "HAKIOSBERYL0000"
#endif

#ifndef XNU_EXTRA_ARGS
#define XNU_EXTRA_ARGS      "cpus=8 small_cores_after=0 loader_return_after=6 ufs=2 ufs_shared_pa=0x60004000"
#endif

#define XNU_ROOT_ARG        "rd=md0"

#if XNU_VERBOSE
#define XNU_BOOT_ARGS       "debug=0x8 serial=3 " XNU_ROOT_ARG " -v " XNU_EXTRA_ARGS
#else
#define XNU_BOOT_ARGS       "debug=0x8 serial=3 " XNU_ROOT_ARG " " XNU_EXTRA_ARGS
#endif

static char s_boot_args[256];

#define CHAIN_OFFSET        0x40000u
#define KERNEL_PA           0x40000000ULL
#define CHAIN_STUB_PA       0x80001000ULL

/* Run state in DRAM surviving warm reset (mblock-2 pstore reserved memory: 0x480a0000) */
#define MARKER_PA           0x480a0000ULL
#define MARK_RUNNING        0x4e52584eu /* "NXRN" */
#define MARK_DONE           0x4e44584eu /* "NXDN" */

#define PANIC_LOG_BASE      0x80100000ULL
#define PANIC_LOG_SIZE      0x40000u

#define MH_MAGIC_64         0xfeedfacfu
#define LC_SEGMENT_64       0x19
#define LC_SYMTAB           0x2
#define LC_UNIXTHREAD       0x5
#define PAYLOAD_MAGIC       0x50554e58u /* "XNUP" */

#define MT6855_UART0_BASE   0x11001000ULL

static const char boot_xnu_flag[] = "DARWIN-BERYL:BOOT-XNU";

struct boot_video {
	uint64_t v_baseAddr, v_display, v_rowBytes, v_width, v_height, v_depth;
};

#define BOOT_LINE_LENGTH 608

struct boot_args {
	uint16_t revision;
	uint16_t version;
	uint64_t virtBase;
	uint64_t physBase;
	uint64_t memSize;
	uint64_t topOfKernelData;
	struct boot_video video;
	uint32_t machineType;
	uint64_t deviceTreeP;
	uint32_t deviceTreeLength;
	char commandLine[BOOT_LINE_LENGTH];
	uint64_t bootFlags;
	uint64_t memSizeActual;
};

_Static_assert(__builtin_offsetof(struct boot_args, virtBase) == 8, "boot_args");
_Static_assert(__builtin_offsetof(struct boot_args, physBase) == 16, "boot_args");
_Static_assert(__builtin_offsetof(struct boot_args, video) == 40, "boot_args");
_Static_assert(__builtin_offsetof(struct boot_args, deviceTreeP) == 96, "boot_args");
_Static_assert(__builtin_offsetof(struct boot_args, commandLine) == 108, "boot_args");
_Static_assert(__builtin_offsetof(struct boot_args, bootFlags) == 720, "boot_args");

#define BLOCK_MAGIC        0x4b434f4c42574452ULL       /* "RDWBLOCK" */
#define BLOCK_VERSION      3
#define BLOCK_MAX_PARTS    160

struct loader_block_part {
	char name[36];
	uint32_t block_size;
	uint64_t blocks;
	uint64_t start_lba;
	uint16_t unit;
	uint8_t lun;
	uint8_t flags;
	uint32_t reserved;
};

struct loader_block {
	uint64_t magic;
	uint32_t version, size;
	uint32_t parts, buffer_size;
	uint64_t buffer_pa;
	uint32_t write_part_plus_one;
	uint32_t write_reserved;
	uint64_t write_first;
	struct {
		volatile uint32_t request;
		uint32_t part;
		uint64_t lba, count;
		uint32_t op;
		uint32_t reserved;
	} ask __attribute__((aligned(128)));
	struct {
		volatile uint32_t answered;
		uint32_t reserved;
		int64_t status;
		uint64_t served, failed, bytes, ticks;
	} answer __attribute__((aligned(128)));
	struct loader_block_part part[BLOCK_MAX_PARTS] __attribute__((aligned(128)));
	uint8_t native_pad[384];
};

_Static_assert(__builtin_offsetof(struct loader_block, ask) == 128, "loader_block ask offset");
_Static_assert(__builtin_offsetof(struct loader_block, answer) == 256, "loader_block answer offset");
_Static_assert(__builtin_offsetof(struct loader_block, part) == 384, "loader_block part offset");
_Static_assert(sizeof(struct loader_block) == 0x2b00, "loader_block size must be 0x2b00");

struct mach_header_64 {
	uint32_t magic, cputype, cpusubtype, filetype, ncmds, sizeofcmds, flags, reserved;
};

struct load_command {
	uint32_t cmd, cmdsize;
};

struct segment_command_64 {
	uint32_t cmd, cmdsize;
	char segname[16];
	uint64_t vmaddr, vmsize, fileoff, filesize;
	uint32_t maxprot, initprot, nsects, flags;
};

struct symtab_command {
	uint32_t cmd, cmdsize, symoff, nsyms, stroff, strsize;
};

struct nlist_64 {
	uint32_t n_strx;
	uint8_t n_type, n_sect;
	uint16_t n_desc;
	uint64_t n_value;
};

struct payload_header {
	uint32_t magic;
	uint32_t size;
};

struct payload_entry {
	char name[16];
	uint32_t size;
	uint32_t reserved;
};

struct payload_info {
	const uint8_t *kernel;
	uint32_t kernel_size;
	const uint8_t *ramdisk;
	uint32_t ramdisk_size;
};

struct xnu_syms {
	uint64_t stub_slot, vc_colors, log, log_len, log_ring_at, log_wrapped, panic_str, panic_args, iso_font,
	    msgbufp, msgbuf, cpu_ttep, live, uart_tx_ready, uart_tx_data, uart_rx_ready, uart_putc, uart_putc_options, log_putc,
	    nprocs, tasks_count, initproc, gic_cpu_init,
	    gic_unhandled_count, gic_last_unhandled, gic_active_iar, host_keep, host_keep_len, host_keep_dropped,
	    hk_keep, hk_keep_len, hk_keep_dropped, cpu_init;
};

static struct xnu_syms xsyms;
static const uint8_t *xkernel;
uint64_t xnu_fp[4];

struct dt_writer {
	uint8_t *base, *cur;
	uint32_t *counts[16];
	int depth;
};

extern char _start[];
extern char chain_stub[], chain_stub_end[];
extern char xnu_return_stub[];
extern void jump_to_kernel(uint64_t entry_pa, uint64_t boot_args_pa);
extern void psci_system_reset(void);
extern int64_t psci_cpu_on(uint64_t mpidr, uint64_t entry, uint64_t context);
extern uint64_t smc_call(uint64_t x0, uint64_t x1, uint64_t x2, uint64_t x3);
extern void watcher_entry(void);
extern void mmu_on(uint64_t l1_table);
extern void dcache_clean_all(void);
extern void dcache_clean_range(uint64_t va, uint64_t len);
extern void dcache_inval_range(uint64_t va, uint64_t len);
extern void flush_idcache_range(uint64_t va, uint64_t len);
extern uint64_t irq_wait(uint64_t until_ticks);
extern void ic_invalidate_all(void);

uint64_t irq_count, irq_intid;
static uint64_t lk_dtb;

/* ---- libc primitives for device memory ---- */

void *memset(void *dst, int c, size_t n)
{
	uint8_t *d = dst;
	if (c == 0 && !((uintptr_t)d & 7)) {
		for (; n >= 8; n -= 8, d += 8) {
			*(volatile uint64_t *)d = 0;
		}
	}
	while (n--) {
		*(volatile uint8_t *)d++ = (uint8_t)c;
	}
	return dst;
}

void *memcpy(void *dst, const void *src, size_t n)
{
	uint8_t *d = dst;
	const uint8_t *s = src;
	if (!(((uintptr_t)d | (uintptr_t)s) & 7)) {
		for (; n >= 8; n -= 8, d += 8, s += 8) {
			*(volatile uint64_t *)d = *(const volatile uint64_t *)s;
		}
	}
	while (n--) {
		*(volatile uint8_t *)d++ = *(const volatile uint8_t *)s++;
	}
	return dst;
}

size_t strlen(const char *s)
{
	size_t len = 0;
	while (*s++) {
		len++;
	}
	return len;
}


int strcmp(const char *s1, const char *s2)
{
	while (*s1 && *s1 == *s2) {
		s1++;
		s2++;
	}
	return *(const unsigned char *)s1 - *(const unsigned char *)s2;
}

int memcmp(const void *s1, const void *s2, size_t n)
{
	const uint8_t *p1 = s1;
	const uint8_t *p2 = s2;
	while (n--) {
		if (*p1 != *p2) {
			return *p1 - *p2;
		}
		p1++;
		p2++;
	}
	return 0;
}

/* ---- Output: Screen + Ramoops (safe, no unclocked UART) ---- */

static void out_putc(char c)
{
	dbg_putc(c);
}

static void out(const char *s)
{
	while (*s) {
		out_putc(*s++);
	}
}

static void out_hex(uint64_t v)
{
	static const char hex[] = "0123456789abcdef";
	int i = 60;
	out("0x");
	while (i > 0 && !((v >> i) & 0xf)) {
		i -= 4;
	}
	for (; i >= 0; i -= 4) {
		out_putc(hex[(v >> i) & 0xf]);
	}
}

static void out_dec(uint64_t v)
{
	char buf[21];
	int n = 0;
	do {
		buf[n++] = (char)('0' + v % 10);
		v /= 10;
	} while (v);
	while (n) {
		out_putc(buf[--n]);
	}
}

/* ---- DRAM Run State Marker ---- */

static void marker_set(uint32_t v)
{
	*(volatile uint32_t *)MARKER_PA = v;
	dcache_clean_range(MARKER_PA, 64);
	__asm__ volatile("dsb sy; isb");
}

static uint32_t marker_get(void)
{
	return *(volatile uint32_t *)MARKER_PA;
}

/* ---- Display ---- */

volatile struct fbcon fbc __attribute__((aligned(8)));

static void display_find(int clear)
{
	if (!clear) return;
	/* Clear primary screen buffer (10.44 MB) to black */
	volatile uint64_t *p = (volatile uint64_t *)LK_FB_BASE;
	for (uint64_t i = 0; i < FB_SCREEN_SIZE / 8; i++) {
		p[i] = 0xff000000ff000000ULL;
	}
	__asm__ volatile("dsb sy");
}

/* ---- Payload & Symbols ---- */

static const struct payload_header *payload_find(void)
{
	const volatile uint64_t *hdr = (const volatile uint64_t *)_start;
	uint64_t off = hdr[6]; /* res3 */
	const struct payload_header *ph = (const struct payload_header *)((uint64_t)_start + off);

	if (off == 0 || (off & 15) || ph->magic != PAYLOAD_MAGIC) {
		return NULL;
	}
	return ph;
}

static int parse_payload(struct payload_info *pi)
{
	const struct payload_header *ph = payload_find();

	memset(pi, 0, sizeof(*pi));
	if (!ph) {
		return 0;
	}
	const uint8_t *p = (const uint8_t *)(ph + 1), *pend = p + ph->size;
	while (p + sizeof(struct payload_entry) <= pend) {
		const struct payload_entry *e = (const struct payload_entry *)p;
		if (e->name[0] == 0) {
			break;
		}
		if (strcmp(e->name, "kernel") == 0) {
			pi->kernel = p + sizeof(*e);
			pi->kernel_size = e->size;
		} else if (strcmp(e->name, "ramdisk") == 0) {
			pi->ramdisk = p + sizeof(*e);
			pi->ramdisk_size = e->size;
		}
		p += sizeof(*e) + ((e->size + 15) & ~15u);
	}
	return pi->kernel != NULL && ((const struct mach_header_64 *)pi->kernel)->magic == MH_MAGIC_64;
}

static void find_syms(const uint8_t *kernel, struct xnu_syms *s)
{
	static const char *const names[] = {
		"_loader_stub_slot", "_vc_colors", "_loader_log", "_loader_log_len", "_loader_log_ring_at",
		"_loader_log_wrapped", "_debugger_panic_str", "_debugger_panic_args", "_iso_font",
		"_msgbufp", "_msgbuf", "_cpu_ttep", "_loader_live",
		"_vmapple_uart_transmit_ready", "_vmapple_uart_transmit_data",
		"_vmapple_uart_receive_ready", "_uart_putc", "_uart_putc_options", "_loader_log_putc",
		"_nprocs", "_tasks_count", "_initproc", "_gic_v3_irq_cpu_init",
		"_gic_unhandled_count", "_gic_last_unhandled", "_gic_active_iar",
		"_redwood_host_keep", "_redwood_host_keep_len", "_redwood_host_keep_dropped",
		"_hakios_host_keep", "_hakios_host_keep_len", "_hakios_host_keep_dropped",
		"_cpu_init",
	};
	uint64_t *slots = (uint64_t *)s;
	const struct mach_header_64 *mh = (const struct mach_header_64 *)kernel;
	const struct load_command *lc = (const struct load_command *)(mh + 1);
	const struct symtab_command *st = NULL;

	memset(s, 0, sizeof(*s));
	for (uint32_t i = 0; i < mh->ncmds; i++, lc = (const void *)((const uint8_t *)lc + lc->cmdsize)) {
		if (lc->cmd == LC_SYMTAB) {
			st = (const void *)lc;
		}
	}
	if (!st) {
		return;
	}
	const struct nlist_64 *sym = (const struct nlist_64 *)(kernel + st->symoff);
	const char *strs = (const char *)(kernel + st->stroff);
	for (uint32_t i = 0; i < st->nsyms; i++) {
		const char *n = strs + sym[i].n_strx;
		if (n[0] != '_' || (n[1] != 'l' && n[1] != 'v' && n[1] != 'd' && n[1] != 'i' && n[1] != 'm' && n[1] != 'c' && n[1] != 'g' && n[1] != 'n' && n[1] != 't' && n[1] != 'r' && n[1] != 'h')) {
			continue;
		}
		for (unsigned k = 0; k < sizeof(names) / sizeof(names[0]); k++) {
			if (!slots[k] && strcmp(n, names[k]) == 0) {
				slots[k] = sym[i].n_value;
			}
		}
	}
}

static uint64_t kva_to_pa(uint64_t va)
{
	return va + XNU_SLIDE;
}

/* ---- Apple Device Tree Builder ---- */

static void dt_prop(struct dt_writer *w, const char *name, const void *data, uint32_t len)
{
	memset(w->cur, 0, 32);
	memcpy(w->cur, name, strlen(name));
	*(volatile uint32_t *)(w->cur + 32) = len;
	memset(w->cur + 36, 0, (len + 3) & ~3u);
	memcpy(w->cur + 36, data, len);
	w->cur += 36 + ((len + 3) & ~3u);
	w->counts[w->depth - 1][0]++;
}

static void dt_prop_str(struct dt_writer *w, const char *name, const char *value)
{
	dt_prop(w, name, value, (uint32_t)strlen(value) + 1);
}

static void dt_prop_u32(struct dt_writer *w, const char *name, uint32_t value)
{
	dt_prop(w, name, &value, sizeof(value));
}

static void dt_prop_u64(struct dt_writer *w, const char *name, uint64_t value)
{
	dt_prop(w, name, &value, sizeof(value));
}

static void dt_prop_padded(struct dt_writer *w, const char *name, const char *value, uint32_t size)
{
	uint8_t field[64];
	memset(field, 0, sizeof(field));
	memcpy(field, value, strlen(value));
	dt_prop(w, name, field, size);
}

static void dt_begin(struct dt_writer *w, const char *name)
{
	if (w->depth > 0) {
		w->counts[w->depth - 1][1]++;
	}
	w->counts[w->depth++] = (uint32_t *)w->cur;
	memset(w->cur, 0, 8);
	w->cur += 8;
	dt_prop_str(w, "name", name);
}

static void dt_end(struct dt_writer *w)
{
	w->depth--;
}

static void dt_identity(struct dt_writer *w, const struct identity_prop *props, uint32_t count, const unsigned char *data)
{
	for (uint32_t i = 0; i < count; i++) {
		if (strcmp(props[i].name, "artwork-display-gamut") == 0) {
			dt_prop(w, props[i].name, "sRGB", 5);
			continue;
		}
		if (strcmp(props[i].name, "artwork-device-subtype") == 0) {
			static const uint32_t subtype = 2436;
			dt_prop(w, props[i].name, &subtype, sizeof(subtype));
			continue;
		}
		dt_prop(w, props[i].name, data + props[i].offset, props[i].length);
	}
}

#define NVRAM_BANK_SIZE 0x2000u
static uint8_t nvram_image[NVRAM_BANK_SIZE];

static void nvram_chrp_header(uint8_t *h, uint8_t sig, uint32_t bytes, const char *name)
{
	uint16_t blocks = (uint16_t)(bytes / 16), sum;
	memset(h, 0, 16);
	h[0] = sig;
	h[2] = (uint8_t)blocks;
	h[3] = (uint8_t)(blocks >> 8);
	memcpy(h + 4, name, strlen(name));
	sum = h[0];
	for (int i = 2; i < 16; i++) {
		sum += h[i];
	}
	while (sum > 0xff) {
		sum = (sum & 0xff) + (sum >> 8);
	}
	h[1] = (uint8_t)sum;
}

static void build_nvram_image(uint8_t *image)
{
	uint32_t lo = 1, hi = 0, generation = 1;
	memset(image, 0, NVRAM_BANK_SIZE);
	nvram_chrp_header(image, 0x5a, 0x20, "nvram");
	nvram_chrp_header(image + 0x20, 0x70, NVRAM_BANK_SIZE - 0x20, "common");
	memcpy(image + 20, &generation, 4);
	for (uint32_t i = 20; i < NVRAM_BANK_SIZE; i++) {
		lo = (lo + image[i]) % 65521;
		hi = (hi + lo) % 65521;
	}
	uint32_t adler = (hi << 16) | lo;
	memcpy(image + 16, &adler, 4);
}

static uint32_t build_device_tree(uint64_t dt_pa, uint64_t rd_pa, uint64_t rd_size,
    uint64_t sys_pa, uint64_t sys_size)
{
	struct dt_writer w = { .base = (uint8_t *)dt_pa, .cur = (uint8_t *)dt_pa, .depth = 0 };
	uint64_t cntfrq = 13000000ULL; /* 13 MHz MT6855 system timer */
	uint8_t seed[64];

	for (unsigned i = 0; i < sizeof(seed); i++) {
		seed[i] = (uint8_t)(i * 37) ^ 0xa5;
	}

	dt_begin(&w, "device-tree");
	dt_identity(&w, identity_root, sizeof(identity_root) / sizeof(identity_root[0]), identity_root_data);
	dt_prop_str(&w, "platform-name", "t8015");
	dt_prop_padded(&w, "serial-number", XNU_SERIAL, 32);
	dt_prop_padded(&w, "mlb-serial-number", XNU_SERIAL "MLB", 32);
	dt_prop_padded(&w, "model-number", "MQAC2", 32);
	dt_prop_padded(&w, "region-info", "LL/A", 32);
	dt_prop_padded(&w, "regulatory-model-number", "A1865", 32);
	dt_prop_u32(&w, "#address-cells", 2);
	dt_prop_u32(&w, "#size-cells", 2);

	dt_begin(&w, "chosen");
	dt_prop_str(&w, "darwin-board", "beryl");
	dt_prop(&w, "random-seed", seed, sizeof(seed));
	dt_prop_u64(&w, "dram-base", XNU_PHYS_BASE);
	dt_prop_u64(&w, "dram-size", XNU_MEM_SIZE);
	dt_prop_u32(&w, "debug-enabled", 1);
	dt_prop_u32(&w, "display-scale", 2);
	dt_prop_u32(&w, "display-rotation", 0);
	dt_prop_str(&w, "psci-method", "smc");
	static const uint8_t wifi_address[6] = { 0x02, 0x52, 0x44, 0x57, 0x00, 0x01 };
	static const uint8_t bluetooth_address[6] = { 0x02, 0x52, 0x44, 0x57, 0x00, 0x02 };
	static const uint8_t manifest_hash[48] = { 0x72, 0x65, 0x64, 0x77, 0x6f, 0x6f, 0x64 };
	static const uint8_t no_behavior[16] = { 0 };
	dt_prop_u64(&w, "unique-chip-id", 0x000052445730001ULL);
	dt_prop_u32(&w, "chip-id", 0x8015);
	dt_prop_u32(&w, "board-id", 0x06);
	dt_prop_str(&w, "boot-args", s_boot_args[0] ? s_boot_args : XNU_BOOT_ARGS);
	dt_prop(&w, "mac-address", wifi_address, sizeof(wifi_address));
	dt_prop(&w, "mac-address-wifi0", wifi_address, sizeof(wifi_address));
	dt_prop(&w, "bluetooth-address", bluetooth_address, sizeof(bluetooth_address));
	dt_prop(&w, "mac-address-bluetooth0", bluetooth_address, sizeof(bluetooth_address));
	dt_prop(&w, "crypto-hash-method", "sha2-384", 9);
	dt_prop(&w, "manifest-hash", manifest_hash, sizeof(manifest_hash));
	dt_prop(&w, "boot-manifest-hash", manifest_hash, sizeof(manifest_hash));
	dt_prop(&w, "no-behavior", no_behavior, sizeof(no_behavior));
	dt_prop(&w, "software-behavior", no_behavior, sizeof(no_behavior));
	dt_prop_str(&w, "firmware-version", "iBoot-8422.100.650");
	dt_prop_u32(&w, "certificate-production-status", 1);
	dt_prop_u32(&w, "certificate-security-mode", 1);
	dt_prop_u32(&w, "effective-production-status-ap", 1);
	dt_prop_u32(&w, "effective-security-mode-ap", 1);
	dt_prop_u32(&w, "secure-boot", 1);
	dt_prop_u32(&w, "production-cert", 1);
	dt_prop_u32(&w, "development-cert", 0);
	dt_prop_u32(&w, "embedded-panic-log-size", PANIC_LOG_SIZE);
	dt_prop_u32(&w, "security-domain", 0);
	build_nvram_image(nvram_image);
	dt_prop_u32(&w, "nvram-bank-size", NVRAM_BANK_SIZE);
	dt_prop_u32(&w, "nvram-bank-count", 1);
	dt_prop_u32(&w, "nvram-current-bank", 0);
	dt_prop(&w, "nvram-proxy-data", nvram_image, sizeof(nvram_image));

	dt_begin(&w, "memory-map");
	if (rd_size != 0) {
		uint64_t rd_reg[2] = { rd_pa, rd_size };
		dt_prop(&w, "RAMDisk", rd_reg, sizeof(rd_reg));
	}
	if (sys_size != 0) {
		uint64_t sys_reg[2] = { sys_pa, sys_size };
		dt_prop(&w, "SystemDisk", sys_reg, sizeof(sys_reg));
	}
	dt_end(&w);
	dt_end(&w); /* chosen */

	dt_begin(&w, "defaults");
	dt_prop_u32(&w, "kern.vm_compressor", 2);
	dt_prop_str(&w, "no-effaceable-storage", "");
	dt_end(&w);

	dt_begin(&w, "product");
	dt_identity(&w, identity_product, sizeof(identity_product) / sizeof(identity_product[0]), identity_product_data);
	dt_begin(&w, "haptics");
	dt_identity(&w, identity_haptics, sizeof(identity_haptics) / sizeof(identity_haptics[0]), identity_haptics_data);
	dt_end(&w);
	dt_end(&w);

	dt_begin(&w, "options");
	dt_end(&w);

	uint64_t pram_reg[2] = { PANIC_LOG_BASE, PANIC_LOG_SIZE };
	memset((void *)PANIC_LOG_BASE, 0, PANIC_LOG_SIZE);
	dt_begin(&w, "pram");
	dt_prop(&w, "reg", pram_reg, sizeof(pram_reg));
	dt_end(&w);

	dt_begin(&w, "cpus");
	for (int i = 0; i < XNU_CORES; i++) {
		char name[5] = { 'c', 'p', 'u', (char)('0' + i), 0 };
		uint16_t mpidr = core_order[i];

		dt_begin(&w, name);
		dt_prop_str(&w, "device_type", "cpu");
		dt_prop_str(&w, "state", i == 0 ? "running" : "waiting");
		dt_prop_u32(&w, "reg", (uint32_t)mpidr);
		dt_prop_u32(&w, "cpu-id", (uint32_t)i);
		dt_prop_u64(&w, "timebase-frequency", cntfrq);
		dt_prop_u64(&w, "fixed-frequency", cntfrq);
		dt_prop_u64(&w, "clock-frequency", (mpidr == 0x600 || mpidr == 0x700) ? 2200000000ULL : 2000000000ULL);
		dt_prop_u64(&w, "bus-frequency", 100000000ULL);
		dt_prop_u64(&w, "memory-frequency", 100000000ULL);
		dt_prop_u64(&w, "peripheral-frequency", 26000000ULL);
		if (mpidr != 0x600 && mpidr != 0x700) {
			dt_prop_u32(&w, "small-core", 1);
		}
		dt_end(&w);
	}
	dt_end(&w);

	dt_begin(&w, "arm-io");
	dt_prop_str(&w, "device_type", "beryl");
	uint64_t ranges[3] = { 0, 0x0c000000, 0x14000000 };
	dt_prop(&w, "ranges", ranges, sizeof(ranges));
	dt_prop_u32(&w, "#address-cells", 2);
	dt_prop_u32(&w, "#size-cells", 2);

	dt_begin(&w, "gic");
	dt_prop_str(&w, "device_type", "interrupt-controller");
	dt_prop_str(&w, "compatible", "arm,gic-v3");
	uint64_t gic_reg[4] = { 0x0c000000 - 0x0c000000, 0x10000, 0x0c040000 - 0x0c000000, 0x200000 };
	dt_prop(&w, "reg", gic_reg, sizeof(gic_reg));
	dt_end(&w);

	dt_begin(&w, "uart0");
	dt_prop_str(&w, "device_type", "uart");
	dt_prop_str(&w, "compatible", "mediatek,mt6577-uart");
	uint64_t uart_reg[2] = { MT6855_UART0_BASE - 0x0c000000, 0x1000 };
	dt_prop(&w, "reg", uart_reg, sizeof(uart_reg));
	dt_prop_u32(&w, "boot-console", 1);
	dt_end(&w);

	dt_end(&w); /* arm-io */
	dt_end(&w); /* device-tree */
	return (uint32_t)(w.cur - w.base);
}

/* ---- Leaving to Android or Reset ---- */

static void __attribute__((noreturn)) reset_board(void)
{
	wdt_reset();
}

static void __attribute__((noreturn)) chain_android(void)
{
	const volatile uint64_t *hdr = (const volatile uint64_t *)_start;
	const volatile uint32_t *img = (const volatile uint32_t *)((uint64_t)_start + CHAIN_OFFSET);
	uint64_t image_size = (hdr[5] + 15) & ~15ULL; /* res2 */

	marker_set(0);
	if (image_size == 0 || img[14] != 0x644d5241u) { /* "ARM\x64" */
		out("\n[SUCCESS] mtkloader running on MT6855 bare-metal!\n");
		out("Holding screen for 15s before reset...\n");
		dbg_delay_ms(15000);
		reset_board();
	}
	out("chaining to Android kernel, ");
	out_dec(image_size);
	out(" bytes at ");
	out_hex(KERNEL_PA);
	out("...\n");
	dbg_delay_ms(2000);

	uint64_t stub_pa = ((uint64_t)img + image_size + 0x1000 + 15) & ~15ULL;
	volatile uint32_t *dst = (volatile uint32_t *)stub_pa;
	const volatile uint32_t *src = (const volatile uint32_t *)chain_stub;
	uint64_t stub_len = (uint64_t)(chain_stub_end - chain_stub);
	for (uint64_t i = 0; i < (stub_len + 3) / 4; i++) {
		dst[i] = src[i];
	}
	/* Synchronize newly written stub into instruction pipeline */
	__asm__ volatile("dsb sy; ic iallu; dsb sy; isb" ::: "memory");
	void (*stub)(uint64_t, uint64_t, uint64_t, uint64_t, uint64_t) = (void *)stub_pa;
	stub(lk_dtb, KERNEL_PA, (uint64_t)img, image_size, KERNEL_PA);
	__builtin_unreachable();
}

void loader_fault(uint64_t vec, uint64_t esr, uint64_t elr, uint64_t far)
{
	fbc.fg = 0xffff4040u;
	out("\n*** LOADER FAULT vec=");
	out_hex(vec);
	out(" ESR=");
	out_hex(esr);
	out(" ELR=");
	out_hex(elr);
	out(" FAR=");
	out_hex(far);
	out("\n");
	dbg_delay_ms(5000);
	chain_android();
}

static inline uint64_t sanitize_kva(uint64_t va)
{
	/* Canonical Darwin kernel VA: bits 63..40 are always 0xfffffff0 */
	if ((va & 0x000000f000000000ULL) == 0x000000f000000000ULL) {
		return 0xfffffff000000000ULL | (va & 0xffffffffffULL);
	}
	return va;
}

/* Walk ARM64 page tables using TTBR1_EL1 */
static uint64_t xnu_va_to_pa(uint64_t va)
{
	va = sanitize_kva(va);
	uint64_t tcr = xnu_fp[2], ttbr1 = xnu_fp[3];
	uint32_t t1sz = (tcr >> 16) & 0x3f, tg1 = (tcr >> 30) & 3;
	uint32_t g = tg1 == 2 ? 12 : tg1 == 1 ? 14 : 0;
	if (g && t1sz >= 16 && ttbr1) {
		uint32_t vabits = 64 - t1sz, per = g - 3;
		uint32_t levels = (vabits - g + per - 1) / per;
		uint64_t table = ttbr1 & 0x0000fffffffffffeULL & ~((1ULL << g) - 1);
		for (uint32_t l = 0; l < levels; l++) {
			if (table < 0x40000000ULL || table >= 0x240000000ULL) {
				break;
			}
			uint32_t shift = g + per * (levels - 1 - l);
			uint64_t idx = (va >> shift) & ((1ULL << per) - 1);
			if (l == 0) {
				idx &= (1ULL << (vabits - shift)) - 1;
			}
			uint64_t pte_addr = table + idx * 8;
			if (pte_addr < 0x40000000ULL || pte_addr >= 0x240000000ULL) {
				break;
			}
			uint64_t d = *(volatile uint64_t *)pte_addr;
			if (!(d & 1)) {
				break;
			}
			uint64_t oa = d & 0x0000ffffffffffffULL & ~((1ULL << g) - 1);
			if (l == levels - 1 || !(d & 2)) { /* page, or block */
				uint64_t span = 1ULL << shift;
				return (oa & ~(span - 1)) | (va & (span - 1));
			}
			table = oa;
		}
	}
	/* Fallback: if within static kernel image slide */
	if (va >= KERNEL_VIRT_BASE && va < KERNEL_VIRT_BASE + XNU_MEM_SIZE) {
		return kva_to_pa(va);
	}
	return 0;
}

static uint64_t xnu_rd64(uint64_t va)
{
	uint64_t pa = xnu_va_to_pa(va);
	return (pa >= 0x40000000ULL && pa < 0x240000000ULL && !(pa & 7)) ? *(volatile uint64_t *)pa : 0;
}

static char xnu_rd8(uint64_t va)
{
	uint64_t pa = xnu_va_to_pa(va);
	return (pa >= 0x40000000ULL && pa < 0x240000000ULL) ? *(volatile char *)pa : 0;
}

static void out_xnu_str(uint64_t va, int max)
{
	char c;
	for (int i = 0; i < max && (c = xnu_rd8(va + i)) != 0; i++) {
		out_putc(c);
	}
}

/* AAPCS64 va_list, as debugger_panic_args points at it */
struct xnu_va_list {
	uint64_t stack, gr_top, vr_top;
	int32_t gr_offs, vr_offs;
};

static uint64_t va_next(struct xnu_va_list *ap)
{
	uint64_t v;
	if (ap->gr_offs < 0) {
		v = xnu_rd64(ap->gr_top + (int64_t)ap->gr_offs);
		ap->gr_offs += 8;
	} else {
		v = xnu_rd64(ap->stack);
		ap->stack += 8;
	}
	return v;
}

static void show_panic_string(const struct xnu_syms *x)
{
	uint64_t fmt = x->panic_str ? xnu_rd64(x->panic_str) : 0;
	uint64_t argp = x->panic_args ? xnu_rd64(x->panic_args) : 0;
	struct xnu_va_list ap = { 0 };

	if (!fmt) {
		out("(no panic string in debugger_panic_str)\n");
		return;
	}
	if (argp) {
		ap.stack = xnu_rd64(argp);
		ap.gr_top = xnu_rd64(argp + 8);
		ap.vr_top = xnu_rd64(argp + 16);
		uint64_t offs = xnu_rd64(argp + 24);
		ap.gr_offs = (int32_t)offs;
		ap.vr_offs = (int32_t)(offs >> 32);
	}
	out("PANIC: ");
	for (int i = 0; i < 1024; i++) {
		char c = xnu_rd8(fmt + i);
		if (!c) {
			break;
		}
		if (c != '%') {
			out_putc(c);
			continue;
		}
		do {
			c = xnu_rd8(fmt + ++i);
		} while (c && ((c >= '0' && c <= '9') || c == '-' || c == '+' || c == ' ' || c == '#' || c == '.' ||
		    c == 'l' || c == 'h' || c == 'z' || c == 'j' || c == 't' || c == 'q' || c == '*'));
		if (!argp && c != '%') {
			out("<?>");
			continue;
		}
		switch (c) {
		case '%':
			out_putc('%');
			break;
		case 's':
			out_xnu_str(va_next(&ap), 200);
			break;
		case 'c':
			out_putc((char)va_next(&ap));
			break;
		case 'd':
		case 'i':
		case 'u': {
			uint64_t v = va_next(&ap);
			out_dec(v);
			out("(");
			out_hex(v);
			out(")");
			break;
		}
		case 0:
			i = 1024;
			break;
		default:
			out_hex(va_next(&ap));
			break;
		}
	}
	out("\n");
}

/* The symbol at or below a kernel address, from the Mach-O symbol table: "name+0xoff". */
static void out_sym(uint64_t addr)
{
	const struct mach_header_64 *mh = (const struct mach_header_64 *)xkernel;
	const struct load_command *lc;
	const struct symtab_command *st = NULL;
	uint64_t best = 0;
	const char *best_name = NULL;

	out_hex(addr);
	if (!xkernel) {
		return;
	}
	lc = (const struct load_command *)(mh + 1);
	for (uint32_t i = 0; i < mh->ncmds; i++, lc = (const void *)((const uint8_t *)lc + lc->cmdsize)) {
		if (lc->cmd == LC_SYMTAB) {
			st = (const void *)lc;
		}
	}
	if (!st) {
		return;
	}
	const struct nlist_64 *sym = (const struct nlist_64 *)(xkernel + st->symoff);
	const char *strs = (const char *)(xkernel + st->stroff);
	for (uint32_t i = 0; i < st->nsyms; i++) {
		if ((sym[i].n_type & 0x0e) == 0x0e && sym[i].n_value <= addr && sym[i].n_value > best) { /* N_SECT */
			best = sym[i].n_value;
			best_name = strs + sym[i].n_strx;
		}
	}
	if (best_name && addr - best < 0x100000) {
		out(" ");
		out(best_name);
		out("+");
		out_hex(addr - best);
	}
}

static void show_backtrace(void)
{
	uint64_t fp = xnu_fp[0];

	out("TCR_EL1 ");
	out_hex(xnu_fp[2]);
	out(" TTBR1_EL1 ");
	out_hex(xnu_fp[3]);
	out(" FP ");
	out_hex(fp);
	out(" LR ");
	out_sym(xnu_fp[1]);
	out("\nbacktrace:\n");
	for (int i = 0; i < 24 && fp; i++) {
		uint64_t lr = xnu_rd64(fp + 8);
		if (!lr) {
			break;
		}
		out("  ["); out_dec(i); out("] ");
		out_sym(lr);
		out("\n");
		uint64_t next_fp = xnu_rd64(fp);
		if (next_fp <= fp) {
			break;
		}
		fp = next_fp;
	}
}

struct span {
	const volatile char *p;
	uint64_t n;
};

static void save_log(const struct span *sp, int nsp)
{
	uint64_t total = 0, room, head, tail, skip_to, at = 0;

	for (int i = 0; i < nsp; i++) {
		total += sp[i].n;
	}
	room = PLOG_CAP - PLOG_HDR->size;
	room = room > 1024 ? room - 1024 : 0;
	head = total <= room ? total : room / 4;
	tail = total <= room ? 0 : room - head;
	skip_to = total - tail;

	uint64_t fb = fbc.base;
	fbc.base = 0;
	for (int i = 0; i < nsp; i++) {
		for (uint64_t k = 0; k < sp[i].n; k++, at++) {
			if (at < head || at >= skip_to) {
				char c = sp[i].p[k];
				plog_putc(c ? c : ' ');
			} else if (at == head) {
				dbg_puts("\n\n[... ");
				dbg_dec(skip_to - head);
				dbg_puts(" bytes of the XNU log left out here ...]\n\n");
			}
		}
	}
	fbc.base = fb;
}

static void show_log_tail(uint32_t lines)
{
	uint32_t size = PLOG_HDR->size, start = PLOG_HDR->start, n = 0;
	uint32_t top = PANEL_H - (lines + 1) * 16;
	uint64_t i;

	if (!fbc.base || size == 0 || size != start) {
		return;
	}
	for (i = size; i > 0 && n <= lines; i--) {
		n += PLOG_DATA[i - 1] == '\n';
	}
	fb_rect(0, top - 4, PANEL_W, PANEL_H - top + 4, 0xff000000u);
	fb_rect(0, top - 4, PANEL_W, 2, 0xffff3030u);
	fbc.top = fbc.y = top;
	fbc.x = 0;
	fbc.scale = 1;
	for (; i < size; i++) {
		fbcon_putc(PLOG_DATA[i]);
	}
}

static void save_host_keep(const struct xnu_syms *s)
{
	static const char head[] = "=== kept for the host by the kernel: ";
	volatile struct ramoops_hdr *h = (volatile struct ramoops_hdr *)RAMOOPS_PMSG;
	volatile char *d = (volatile char *)(RAMOOPS_PMSG + sizeof(struct ramoops_hdr));
	uint32_t at = 0, len, dropped;
	char num[12];
	int n;

	uint64_t keep_va = s->host_keep ? s->host_keep : s->hk_keep;
	uint64_t len_va = s->host_keep ? s->host_keep_len : s->hk_keep_len;
	uint64_t dropped_va = s->host_keep ? s->host_keep_dropped : s->hk_keep_dropped;

	if (!keep_va || !len_va) {
		return;
	}
	len = rd32(kva_to_pa(len_va));
	dropped = dropped_va ? rd32(kva_to_pa(dropped_va)) : 0;
	for (const char *c = head; *c; c++) {
		d[at++] = *c;
	}
	for (int part = 0; part < 2; part++) {
		uint32_t v = part ? dropped : len;
		n = 0;
		do {
			num[n++] = (char)('0' + v % 10);
			v /= 10;
		} while (v);
		while (n) {
			d[at++] = num[--n];
		}
		const char *tail = part ? " dropped) ===\n" : " bytes (";
		for (const char *c = tail; *c; c++) {
			d[at++] = *c;
		}
	}
	uint64_t keep_pa = kva_to_pa(keep_va);
	const volatile char *src = (const volatile char *)keep_pa;
	for (uint32_t i = 0; i < len && at < PMSG_CAP; i++) {
		d[at++] = src[i];
	}
	h->sig = RAMOOPS_SIG;
	h->start = at;
	h->size = at;
	__asm__ volatile("dsb sy");
}

static inline uint8_t bit_rev8(uint8_t b)
{
	b = ((b & 0xf0) >> 4) | ((b & 0x0f) << 4);
	b = ((b & 0xcc) >> 2) | ((b & 0x33) << 2);
	b = ((b & 0xaa) >> 1) | ((b & 0x55) << 1);
	return b;
}

static const void *macho_va_to_ptr(const uint8_t *kernel, uint64_t va)
{
	if (!kernel || !va) return NULL;
	const struct mach_header_64 *mh = (const struct mach_header_64 *)kernel;
	const struct load_command *lc = (const struct load_command *)(mh + 1);
	for (uint32_t i = 0; i < mh->ncmds; i++, lc = (const void *)((const uint8_t *)lc + lc->cmdsize)) {
		if (lc->cmd == LC_SEGMENT_64) {
			const struct segment_command_64 *seg = (const void *)lc;
			if (va >= seg->vmaddr && va < seg->vmaddr + seg->vmsize) {
				return kernel + seg->fileoff + (va - seg->vmaddr);
			}
		}
	}
	return NULL;
}

static void read_screen(void)
{
	static uint32_t font_hash[256];
	const uint8_t *font = (const uint8_t *)macho_va_to_ptr(xkernel, xsyms.iso_font);
	const uint32_t cols = PANEL_W / 8, rows = PANEL_H / 16;
	uint32_t lit_cells = 0, known = 0, last_row = 0;
	static char line[PANEL_W / 8 + 1];
	const uint64_t fb_base = LK_FB_BASE;
	const uint32_t pitch = LK_FB_PITCH;

	if (!font || !fb_base) {
		return;
	}
	for (int ch = 0; ch < 256; ch++) {
		uint32_t h = 0;
		for (int r = 0; r < 16; r++) {
			h = h * 0x01000193u ^ font[ch * 16 + r];
		}
		font_hash[ch] = h;
	}
	dbg_puts("\n=== SCREEN CAPTURE (decoded via iso_font) ===\n");
	for (uint32_t row = 0; row < rows; row++) {
		for (uint32_t col = 0; col < cols; col++) {
			uint8_t bits[16];
			uint32_t any = 0;
			for (uint32_t r = 0; r < 16; r++) {
				const volatile uint32_t *px = (const volatile uint32_t *)(fb_base + (uint64_t)(row * 16 + r) * pitch) + col * 8;
				uint8_t b = 0;
				for (uint32_t x = 0; x < 8; x++) {
					uint32_t p = px[x];
					uint32_t lum = ((p >> 16) & 0xff) + ((p >> 8) & 0xff) + (p & 0xff);
					if (lum > 3 * 0x60) {
						b |= (uint8_t)(0x80u >> x);
					}
				}
				bits[r] = b;
				any |= b;
			}
			char out_c = ' ';
			if (any) {
				lit_cells++;
				if (lit_cells == 1) {
					dbg_puts("[sample cell raw: ");
					for (int r = 0; r < 16; r++) { dbg_hex(bits[r], 2); dbg_putc(' '); }
					dbg_puts("]\n");
				}
				for (int inv = 0; inv < 4 && out_c == ' '; inv++) {
					uint32_t h = 0;
					for (int r = 0; r < 16; r++) {
						uint8_t b = bits[r];
						if (inv == 1) b = ~b;
						else if (inv == 2) b = bit_rev8(b);
						else if (inv == 3) b = ~bit_rev8(b);
						h = h * 0x01000193u ^ b;
					}
					for (int ch = 0x20; ch < 0x7f; ch++) {
						if (font_hash[ch] == h) {
							out_c = (char)ch;
							known++;
							break;
						}
					}
				}
				if (out_c == ' ') {
					out_c = '#';
				}
			}
			line[col] = out_c;
		}
		line[cols] = 0;
		int n = (int)cols;
		while (n > 0 && line[n - 1] == ' ') {
			n--;
		}
		line[n] = 0;
		if (n) {
			last_row = row + 1;
			dbg_puts(line);
			dbg_putc('\n');
		}
	}
	dbg_puts("[screen: ");
	dbg_dec(lit_cells);
	dbg_puts(" cells lit, ");
	dbg_dec(known);
	dbg_puts(" read as characters, last text row ");
	dbg_dec(last_row);
	dbg_puts("]\n");

	if (known == 0 && lit_cells > 50) {
		dbg_puts("[attempting 2x scaled font decode...]\n");
		const uint32_t cols2 = PANEL_W / 16, rows2 = PANEL_H / 32;
		static char line2[PANEL_W / 16 + 1];
		uint32_t known2 = 0;
		for (uint32_t row = 0; row < rows2; row++) {
			for (uint32_t col = 0; col < cols2; col++) {
				uint8_t bits[16];
				uint32_t any = 0;
				for (uint32_t r = 0; r < 16; r++) {
					const volatile uint32_t *px = (const volatile uint32_t *)(fb_base + (uint64_t)(row * 32 + r * 2) * pitch) + col * 16;
					uint8_t b = 0;
					for (uint32_t x = 0; x < 8; x++) {
						uint32_t p = px[x * 2];
						uint32_t lum = ((p >> 16) & 0xff) + ((p >> 8) & 0xff) + (p & 0xff);
						if (lum > 3 * 0x60) {
							b |= (uint8_t)(0x80u >> x);
						}
					}
					bits[r] = b;
					any |= b;
				}
				char out_c = ' ';
				if (any) {
					for (int inv = 0; inv < 4 && out_c == ' '; inv++) {
						uint32_t h = 0;
						for (int r = 0; r < 16; r++) {
							uint8_t b = bits[r];
							if (inv == 1) b = ~b;
							else if (inv == 2) b = bit_rev8(b);
							else if (inv == 3) b = ~bit_rev8(b);
							h = h * 0x01000193u ^ b;
						}
						for (int ch = 0x20; ch < 0x7f; ch++) {
							if (font_hash[ch] == h) {
								out_c = (char)ch;
								known2++;
								break;
							}
						}
					}
					if (out_c == ' ') out_c = '#';
				}
				line2[col] = out_c;
			}
			line2[cols2] = 0;
			int n = (int)cols2;
			while (n > 0 && line2[n - 1] == ' ') n--;
			line2[n] = 0;
			if (n) {
				dbg_puts(line2);
				dbg_putc('\n');
			}
		}
		dbg_puts("[screen 2x: ");
		dbg_dec(known2);
		dbg_puts(" decoded]\n");
	}

	dbg_puts("=== END OF SCREEN CAPTURE ===\n");
}

static void rescue_state(void)
{
	if (xsyms.cpu_ttep) {
		xnu_fp[3] = rd32(kva_to_pa(xsyms.cpu_ttep)) | (uint64_t)rd32(kva_to_pa(xsyms.cpu_ttep) + 4) << 32;
		xnu_fp[2] = 0x22a51a251aULL;
	}
	out("cpu_ttep ");
	out_hex(xnu_fp[3]);
	if (xsyms.live) {
		out(" heartbeat ");
		out_dec(*(volatile uint64_t *)kva_to_pa(xsyms.live + 8));
	}
	out("\n");
	show_panic_string(&xsyms);

	uint64_t mb_va = xsyms.msgbuf ? xsyms.msgbuf : (xsyms.msgbufp ? xsyms.msgbufp - 0x18 : 0);
	if (!mb_va) {
		mb_va = 0xfffffff007b17e00ULL;
	}
	uint64_t mb_pa = kva_to_pa(mb_va);
	dcache_inval_range(mb_pa, 64);

	uint32_t magic = rd32(mb_pa);
	uint32_t size = rd32(mb_pa + 4);
	uint32_t bufx = rd32(mb_pa + 8);
	uint32_t bufr = rd32(mb_pa + 12);
	uint64_t bufc = sanitize_kva(*(volatile uint64_t *)(mb_pa + 16));

	out("msgbuf "); out_hex(mb_va);
	out(" (PA="); out_hex(mb_pa);
	out(") magic="); out_hex(magic);
	out(" size="); out_dec(size);
	out(" bufx="); out_dec(bufx);
	out(" bufr="); out_dec(bufr);
	out(" bufc="); out_hex(bufc);
	out("\n");

	uint64_t bufc_pa = bufc ? kva_to_pa(bufc) : 0;
	if (bufc_pa < 0x80000000ULL || bufc_pa >= 0x90000000ULL) {
		bufc_pa = 0x83d2b77cULL;
	}
	if (size == 0 || size > 256 * 1024) {
		size = 131072;
	}
	out("bufc PA="); out_hex(bufc_pa); out("\n");
	dcache_inval_range(bufc_pa, size);
	out("--- kernel message buffer (from DRAM) ---\n");
	uint64_t fbsave = fbc.base;
	fbc.base = 0;
	uint32_t start_pos = (bufx < size) ? bufx : 0;
	for (int pass = 0; pass < 2; pass++) {
		uint32_t from = (pass == 0) ? start_pos : 0;
		uint32_t to = (pass == 0) ? size : start_pos;
		for (uint32_t i = from; i < to; i++) {
			char c = *(volatile char *)(bufc_pa + i);
			if (c >= 32 && c <= 126) dbg_putc(c);
			else if (c == '\n' || c == '\t' || c == '\r') dbg_putc(c);
		}
	}
	fbc.base = fbsave;
	dbg_puts("\n--- end of message buffer ---\n");
}

static void rescue_log(void)
{
	struct payload_info pi;
	struct xnu_syms s;

	out("\n=== mtkloader: XNU ran until the watchdog reset ===\n");
	if (!parse_payload(&pi)) {
		out("no XNU payload\n");
		return;
	}
	find_syms(pi.kernel, &s);
	xsyms = s;
	xkernel = pi.kernel;

	/* 1. Capture pristine Darwin framebuffer before anything overwrites or draws to it */
	dcache_inval_range(LK_FB_BASE, FB_SCREEN_SIZE);
	uint64_t fb_save = fbc.base;
	fbc.base = 0; /* Keep fbc disabled so logs go exclusively to plog/ramoops */
	read_screen();

	if (s.log && s.log_len && s.log_ring_at && s.log_wrapped) {
		const uint64_t head_sz = 256 * 1024, ring_sz = 1024 * 1024;
		uint64_t log_pa = kva_to_pa(s.log);
		dcache_inval_range(log_pa, head_sz + ring_sz);
		dcache_inval_range(kva_to_pa(s.log_len), 64);
		dcache_inval_range(kva_to_pa(s.log_ring_at), 64);
		dcache_inval_range(kva_to_pa(s.log_wrapped), 64);
		const volatile char *log = (const volatile char *)log_pa;
		uint32_t len = rd32(kva_to_pa(s.log_len));
		uint32_t ring_at = rd32(kva_to_pa(s.log_ring_at));
		uint8_t wrapped = *(const volatile uint8_t *)kva_to_pa(s.log_wrapped);
		struct span sp[3];
		int n = 0;

		out("loader_log_len ");
		out_dec(len);
		out(" ring_at ");
		out_dec(ring_at);
		out(" wrapped ");
		out_dec(wrapped);
		out("\n");
		if (ring_at > ring_sz) {
			ring_at = 0;
		}
		if (!wrapped) {
			if (len > head_sz + ring_sz) {
				len = head_sz + ring_sz;
			}
			sp[n++] = (struct span){ log, len };
		} else {
			sp[n++] = (struct span){ log, head_sz };
			sp[n++] = (struct span){ log + head_sz + ring_at, ring_sz - ring_at };
			sp[n++] = (struct span){ log + head_sz, ring_at };
		}
		dbg_puts("=== XNU log (from DRAM) ===\n");
		save_log(sp, n);
		dbg_puts("=== end of XNU log ===\n");
	}
	save_host_keep(&s);
	rescue_state();
	fbc.base = fb_save;
	show_log_tail(40);
}

void xnu_returned(uint64_t log_pa, uint64_t log_len, uint64_t reason,
    uint64_t esr, uint64_t elr, uint64_t far)
{
	struct span sp = { (const volatile char *)log_pa, log_len };

	wdt_disable();
	marker_set(MARK_DONE);

	uint64_t screen = fbc.base;
	fbc.base = 0;
	dbg_puts("\n=== what the screen showed when XNU came back ===\n");
	read_screen();
	fbc.base = screen;
	fbc.fg = 0xffffff40u;

	out("\n*** XNU RETURNED reason=");
	out_dec(reason);
	out(reason == 0 ? " (orderly end)" : reason == 1 ? " (early exception)" : reason == 2 ? " (checkpoint)" : "");
	out(" ESR=");
	out_hex(esr);
	out(" ELR=");
	out_hex(elr);
	out(" FAR=");
	out_hex(far);
	out(" log_pa=");
	out_hex(log_pa);
	out(" log_len=");
	out_dec(log_len);
	out("\n");

	if (xsyms.tasks_count) {
		uint64_t tc_pa = kva_to_pa(xsyms.tasks_count);
		if (tc_pa >= XNU_PHYS_BASE && tc_pa < XNU_PHYS_BASE + XNU_MEM_SIZE) {
			out("tasks: ");
			out_dec(rd32(tc_pa));
		}
		if (xsyms.nprocs) {
			uint64_t np_pa = kva_to_pa(xsyms.nprocs);
			if (np_pa >= XNU_PHYS_BASE && np_pa < XNU_PHYS_BASE + XNU_MEM_SIZE) {
				out(" processes: ");
				out_dec(rd32(np_pa));
			}
		}
		if (xsyms.initproc) {
			uint64_t ip_pa = kva_to_pa(xsyms.initproc);
			if (ip_pa >= XNU_PHYS_BASE && ip_pa < XNU_PHYS_BASE + XNU_MEM_SIZE) {
				out(" initproc: ");
				out_hex(*(volatile uint64_t *)ip_pa);
			}
		}
		out("\n");
	}

	show_panic_string(&xsyms);
	show_backtrace();

	if (log_pa && log_len) {
		out("=== XNU LOG START ===\n");
		save_log(&sp, 1);
		out("\n=== XNU LOG END ===\n");
	}
	save_host_keep(&xsyms);
	rescue_state();
	show_log_tail(40);

	out("\nHolding screen for 3s, then warm resetting to boot Android and read pstore...\n");
	dbg_delay_ms(3000);
	plog_flush();
	reset_board();
}

void watcher_main(void)
{
	/* Secondary watcher core: loops until needed */
	for (;;) {
		__asm__ volatile("wfe");
	}
}

/* ---- GIC & Timers ---- */

#define GICD_BASE   0x0c000000ULL
#define GICR_SGI    (0x0c040000ULL + 0x10000)

static void gic_fix_eoimode(void)
{
	uint64_t ctlr;
	__asm__ volatile("mrs %0, ICC_CTLR_EL1" : "=r"(ctlr));
	out("ICC_CTLR_EL1 ");
	out_hex(ctlr);
	out(ctlr & 2 ? " (EOImode set: clearing)" : " (EOImode clear)");
	if (ctlr & 2) {
		__asm__ volatile("msr ICC_CTLR_EL1, %0; isb" : : "r"(ctlr & ~2ULL));
		__asm__ volatile("mrs %0, ICC_CTLR_EL1" : "=r"(ctlr));
		out(" -> ");
		out_hex(ctlr);
	}
	out("\n");
}

#if TIMER_PROBE
static void gic_cpu_prepare(void)
{
	uint64_t sre, ctlr;
	__asm__ volatile("mrs %0, ICC_CTLR_EL1" : "=r"(ctlr));
	out("  ICC_CTLR_EL1 ");
	out_hex(ctlr);
	out(ctlr & 2 ? " (EOImode=1: clearing)" : " (EOImode=0)");
	__asm__ volatile("msr ICC_CTLR_EL1, %0; isb" : : "r"(ctlr & ~2ULL));
	__asm__ volatile("mrs %0, ICC_CTLR_EL1" : "=r"(ctlr));
	out(" -> ");
	out_hex(ctlr);
	out("\n");

	__asm__ volatile("mrs %0, ICC_SRE_EL1" : "=r"(sre));
	__asm__ volatile("msr ICC_SRE_EL1, %0; isb" : : "r"(sre | 1));
	__asm__ volatile("msr ICC_AP1R0_EL1, xzr");
	__asm__ volatile("msr ICC_PMR_EL1, %0" : : "r"(0xffUL));
	__asm__ volatile("msr ICC_BPR1_EL1, xzr");
	__asm__ volatile("msr ICC_IGRPEN1_EL1, %0; isb" : : "r"(1UL));
}

static int timer_try(int ppi, int virt)
{
	uint64_t f = dbg_freq(), now, grp;
	uint32_t before;

	wr32(GICR_SGI + 0x080, rd32(GICR_SGI + 0x080) | (1u << ppi));
	wr32(GICR_SGI + 0xd00, rd32(GICR_SGI + 0xd00) & ~(1u << ppi));
	*(volatile uint8_t *)(GICR_SGI + 0x400 + ppi) = 0xa0;
	wr32(GICR_SGI + 0x100, 1u << ppi);
	grp = rd32(GICR_SGI + 0x080);
	wr32(GICR_SGI + 0x380, 1u << ppi);
	irq_count = 0;
	irq_intid = 0;

	__asm__ volatile("isb; mrs %0, cntvct_el0" : "=r"(now));
	if (virt) {
		__asm__ volatile("msr cntv_cval_el0, %0; msr cntv_ctl_el0, %1; isb" : : "r"(now + f / 10), "r"(1UL));
	} else {
		__asm__ volatile("msr cntp_cval_el0, %0; msr cntp_ctl_el0, %1; isb" : : "r"(now + f / 10), "r"(1UL));
	}
	before = rd32(GICR_SGI + 0x200);
	irq_wait(now + f / 2);

	out(virt ? "  virtual timer  PPI " : "  physical timer PPI ");
	out_dec((uint64_t)ppi);
	out(": IGROUPR0 ");
	out_hex(grp);
	out(grp & (1u << ppi) ? " (group 1)" : " (GROUP 0: not ours)");
	out(", ISPENDR0 ");
	out_hex(before);
	out("->");
	out_hex(rd32(GICR_SGI + 0x200));
	out(", ISACTIVER0 after EOI ");
	out_hex(rd32(GICR_SGI + 0x300));
	out(", irqs ");
	out_dec(irq_count);
	if (irq_count) {
		out(" intid ");
		out_dec(irq_intid);
	}
	out(irq_count ? "  <- TIMER RECEIVED\n" : "  (none)\n");
	return irq_count > 0;
}

static void timer_probe(void)
{
	out("\n== Timer & GICv3 Probe ==\n");
	gic_cpu_prepare();
	timer_try(27, 1); /* virtual timer (XNU's timer, PPI 27) */
}
#endif /* TIMER_PROBE */

/* ---- Boot Choice / PMSG Check ---- */

static int pmsg_take(const char *flag, uint32_t n)
{
	volatile char *d = (volatile char *)0x480f0000ULL;
	uint32_t cap = 0x80000u; /* 512 KB pmsg range */
	int found = 0;

	for (uint32_t at = 0; at + n <= cap; at++) {
		uint32_t k = 0;
		while (k < n && d[at + k] == flag[k]) {
			k++;
		}
		if (k == n) {
			out("pmsg: found trigger at ");
			out_hex(0x480f0000ULL + at);
			out("\n");
			for (k = 0; k < n; k++) {
				d[at + k] = '-';
			}
			found = 1;
			break;
		}
	}
	if (!found) {
		out("pmsg: trigger not found in 0x480f0000-0x48170000\n");
	}
	return found;
}

static int xnu_requested(void)
{
	return pmsg_take(boot_xnu_flag, sizeof(boot_xnu_flag) - 1);
}

#define UIC_CMD_DME_GET       0x01u
#define UIC_CMD_DME_SET       0x02u
#define UIC_ARG_MIB(attr)     (((uint32_t)(attr) & 0xffffu) << 16)

static int ufs_uic_cmd(uint32_t cmd, uint32_t arg1, uint32_t arg2, uint32_t arg3)
{
	for (int i = 0; i < 1000; i++) {
		if (rd32(0x112b0000ULL + 0x30) & 8) break;
		dbg_delay_ms(1);
	}
	wr32(0x112b0000ULL + 0x20, 1 << 10);
	wr32(0x112b0000ULL + 0x94, arg1);
	wr32(0x112b0000ULL + 0x98, arg2);
	wr32(0x112b0000ULL + 0x9C, arg3);
	wr32(0x112b0000ULL + 0x90, cmd);

	for (int i = 0; i < 2000; i++) {
		uint32_t is = rd32(0x112b0000ULL + 0x20);
		if (is & (1 << 10)) {
			wr32(0x112b0000ULL + 0x20, 1 << 10);
			return (int)(rd32(0x112b0000ULL + 0x98) & 0xff);
		}
		dbg_delay_ms(1);
	}
	return -1;
}

static int s_usb_xnu_trigger = 0;

static void hw_probes(void)
{
	uint64_t midr, mpidr;
	__asm__ volatile("mrs %0, midr_el1" : "=r"(midr));
	__asm__ volatile("mrs %0, mpidr_el1" : "=r"(mpidr));
	out("\n== Hardware Probes (Step 3) ==\n");
	out("CPU Boot Core: MIDR ");
	out_hex(midr);
	uint32_t part = (midr >> 4) & 0xfff;
	if (part == 0xd05) out(" (Cortex-A55)");
	else if (part == 0xd41) out(" (Cortex-A78)");
	out(", MPIDR ");
	out_hex(mpidr);
	out("\n");

	/* Keypad (0x1c00e000) */
	uint32_t kp_sta = rd32(0x1c00e000ULL + 0x00);
	uint32_t kp_mem1 = rd32(0x1c00e000ULL + 0x04);
	uint32_t kp_mem2 = rd32(0x1c00e000ULL + 0x08);
	uint32_t kp_deb = rd32(0x1c00e000ULL + 0x18);
	out("Keypad @ 0x1c00e000: STA ");
	out_hex(kp_sta);
	out(" MEM1 ");
	out_hex(kp_mem1);
	if (!(kp_mem1 & 1)) {
		out(" (VOL_DOWN PRESSED)");
	} else {
		out(" (VOL_DOWN IDLE)");
	}
	out(" MEM2 ");
	out_hex(kp_mem2);
	out(" DEB ");
	out_hex(kp_deb);
	out("\n");

	/* UFS 2.2 Host Controller (0x112b0000) */
	uint32_t ufs_cap = rd32(0x112b0000ULL + 0x00);
	uint32_t ufs_ver = rd32(0x112b0000ULL + 0x08);
	uint32_t ufs_hcpmid = rd32(0x112b0000ULL + 0x14);
	uint32_t ufs_is = rd32(0x112b0000ULL + 0x20);
	uint32_t ufs_hcs = rd32(0x112b0000ULL + 0x30);
	uint32_t ufs_hce = rd32(0x112b0000ULL + 0x34);
	uint32_t ufs_utrlba = rd32(0x112b0000ULL + 0x50);
	uint32_t ufs_utrlbau = rd32(0x112b0000ULL + 0x54);
	uint32_t ufs_utrldbr = rd32(0x112b0000ULL + 0x58);
	uint32_t ufs_utrlrsr = rd32(0x112b0000ULL + 0x60);
	out("UFS @ 0x112b0000: CAP ");
	out_hex(ufs_cap);
	out(" VER ");
	out_hex(ufs_ver);
	out(" HCPMID ");
	out_hex(ufs_hcpmid);
	out(" IS ");
	out_hex(ufs_is);
	out(" HCS ");
	out_hex(ufs_hcs);
	if (ufs_hcs & 1) out(" (DP=1)");
	if (ufs_hcs & 2) out(" (UTRLRDY=1)");
	if (ufs_hcs & 8) out(" (UCRDY=1)");
	out(" HCE ");
	out_hex(ufs_hce);
	out(" UTRLBA ");
	out_hex(((uint64_t)ufs_utrlbau << 32) | ufs_utrlba);
	out(" DBR ");
	out_hex(ufs_utrldbr);
	out(" RSR ");
	out_hex(ufs_utrlrsr);
	out("\n");

	/* MediaTek SiP Hardware Sequence for UFS:
	 * 1. Power rail VA09: smc(0x82000276, 0x1, 1, 0)
	 * 2. Unreset UFS chip: smc(0x82000276, 0x2, 1, 0)
	 * 3. Reference clock notify pre-change: smc(0x82000276, 0x8, 1, 0)
	 * 4. Request REFCLK in register 0x144
	 * 5. Reference clock notify post-change: smc(0x82000276, 0x8, 1, 1)
	 */
	uint64_t r_va09 = smc_call(0x82000276ULL, 0x1, 1, 0);
	uint64_t r_rst0 = smc_call(0x82000276ULL, 0x2, 0, 0); /* assert RST_n low */
	dbg_delay_ms(1);
	uint64_t r_rst1 = smc_call(0x82000276ULL, 0x2, 1, 0); /* deassert RST_n high */
	dbg_delay_ms(15);                                      /* 15ms recovery delay */
	uint64_t r_clk0 = smc_call(0x82000276ULL, 0x8, 1, 0);
	uint64_t r_cryp = smc_call(0x82000276ULL, 0x4, 0, 0); /* UFS_MTK_SIP_CRYPTO_CTRL: 0 = disable crypto */

	/* Check and assert REFCLK_CTRL (0x144) */
	uint32_t refclk = rd32(0x112b0000ULL + 0x144);
	out("UFS: REFCLK_CTRL=");
	out_hex(refclk);
	wr32(0x112b0000ULL + 0x144, 1); /* REFCLK_REQUEST */
	for (int i = 0; i < 1000; i++) {
		refclk = rd32(0x112b0000ULL + 0x144);
		if (refclk & 2) break; /* REFCLK_ACK */
		dbg_delay_ms(1);
	}
	uint64_t r_clk1 = smc_call(0x82000276ULL, 0x8, 1, 1);
	out(" post-refclk=");
	out_hex(refclk);
	out(" (SMC va09=");
	out_hex(r_va09);
	out(" rst=");
	out_hex(r_rst0);
	out(",");
	out_hex(r_rst1);
	out(" clk=");
	out_hex(r_clk0);
	out(",");
	out_hex(r_clk1);
	out(" cryp=");
	out_hex(r_cryp);
	out(")\n");

	if ((ufs_hce & 1) == 0) {
		out("UFS: HCE=0, attempting HCE enable...\n");
		wr32(0x112b0000ULL + 0x34, 1);
		for (int i = 0; i < 1000; i++) {
			ufs_hce = rd32(0x112b0000ULL + 0x34);
			if (ufs_hce & 1) break;
			dbg_delay_ms(1);
		}
		ufs_hcs = rd32(0x112b0000ULL + 0x30);
		out("UFS: post-HCE: HCE=");
		out_hex(ufs_hce);
		out(" HCS=");
		out_hex(ufs_hcs);
		out("\n");
	}

	if ((ufs_hcs & 1) == 0) {
		out("UFS: DP=0 (link down), preparing UniPro power & clock...\n");
		ufs_uic_cmd(UIC_CMD_DME_SET, UIC_ARG_MIB(0xD0A8), 0, 0); /* Exit LPM (VS_UNIPROPOWERDOWNCONTROL = 0) */
		ufs_uic_cmd(UIC_CMD_DME_SET, UIC_ARG_MIB(0xD0A6), 0, 0); /* Disable clock gating (VS_SAVEPOWERCONTROL = 0) */
		int lcc_res = ufs_uic_cmd(UIC_CMD_DME_SET, UIC_ARG_MIB(0x155E), 0, 0); /* Disable TX LCC */
		out("UFS: DME_SET(0x155E)= ");
		out_hex(lcc_res);
		out(", attempting DME_LINKSTARTUP (0x16)...\n");
		wr32(0x112b0000ULL + 0x20, 1 << 10); /* clear UIC completion */
		wr32(0x112b0000ULL + 0x90, 0x16);   /* UICCMD: DME_LINKSTARTUP */
		for (int i = 0; i < 1000; i++) {
			uint32_t is = rd32(0x112b0000ULL + 0x20);
			if (is & (1 << 10)) {
				wr32(0x112b0000ULL + 0x20, 1 << 10);
				break;
			}
			dbg_delay_ms(1);
		}
		ufs_hcs = rd32(0x112b0000ULL + 0x30);
		uint32_t res = rd32(0x112b0000ULL + 0x98); /* UICCMDARG2 */
		out("UFS: post-linkup: HCS=");
		out_hex(ufs_hcs);
		out(" res=");
		out_hex(res);
		out("\n");
	}

	if (ufs_hcs & 1) {
		out("UFS: Device Present! Initializing SCSI subsystem...\n");
		/* DMA buffers in general DRAM (0x60000000ULL) */
		uint32_t *ufs_utrd = (uint32_t *)0x60000000ULL;
		uint8_t *ufs_ucd   = (uint8_t *)0x60001000ULL;
		uint8_t *ufs_buf   = (uint8_t *)0x60010000ULL;

		/* Stop UTRL */
		wr32(0x112b0000ULL + 0x60, 0);
		wr32(0x112b0000ULL + 0x50, (uint32_t)(uintptr_t)ufs_utrd);
		wr32(0x112b0000ULL + 0x54, (uint32_t)((uint64_t)(uintptr_t)ufs_utrd >> 32));
		wr32(0x112b0000ULL + 0x60, 1);

		/* Wait for UTRLRDY */
		for (int i = 0; i < 1000; i++) {
			if (rd32(0x112b0000ULL + 0x30) & 2) break;
			dbg_delay_ms(1);
		}

		/* Helper to run SCSI commands on slot 0 */
		#define RUN_SCSI(name, lun, cdb_ptr, cdb_sz, buf_ptr, buf_sz, is_read) do { \
			memset(ufs_utrd, 0, 1024); \
			memset(ufs_ucd, 0, 2048); \
			if (buf_ptr && buf_sz) memset((void *)(buf_ptr), 0, (buf_sz)); \
			ufs_ucd[0] = 0x01; /* UPIU_COMMAND */ \
			ufs_ucd[1] = (buf_sz > 0 && is_read) ? 0x40 : ((buf_sz > 0 && !is_read) ? 0x20 : 0x00); \
			ufs_ucd[2] = (lun); \
			ufs_ucd[3] = 0; \
			ufs_ucd[12] = (uint8_t)((buf_sz) >> 24); \
			ufs_ucd[13] = (uint8_t)((buf_sz) >> 16); \
			ufs_ucd[14] = (uint8_t)((buf_sz) >> 8); \
			ufs_ucd[15] = (uint8_t)(buf_sz); \
			memcpy(&ufs_ucd[16], (cdb_ptr), (cdb_sz)); \
			if (buf_ptr && buf_sz) { \
				uint32_t *p = (uint32_t *)(ufs_ucd + 1024); \
				p[0] = (uint32_t)(uintptr_t)(buf_ptr); \
				p[1] = (uint32_t)((uint64_t)(uintptr_t)(buf_ptr) >> 32); \
				p[2] = 0; \
				p[3] = (buf_sz) - 1; \
			} \
			ufs_utrd[0] = (1u << 28) | (1u << 24) | ((buf_sz > 0 ? (is_read ? 2u : 1u) : 0u) << 25); /* 1 = UTP_CMD_TYPE_UFS_STORAGE */ \
			ufs_utrd[1] = 0; \
			ufs_utrd[2] = 0x0f; \
			ufs_utrd[3] = 0; \
			ufs_utrd[4] = (uint32_t)(uintptr_t)ufs_ucd; \
			ufs_utrd[5] = (uint32_t)((uint64_t)(uintptr_t)ufs_ucd >> 32); \
			ufs_utrd[6] = ((512 / 4) << 16) | (512 / 4); /* RuO=128 DW, RuL=128 DW */ \
			ufs_utrd[7] = (buf_ptr && buf_sz) ? (((1024 / 4) << 16) | 1u) : 0u; /* PrdtO=256 DW, PrdtL=1 */ \
			dcache_clean_range((uint64_t)(uintptr_t)ufs_utrd, 1024); \
			dcache_clean_range((uint64_t)(uintptr_t)ufs_ucd, 2048); \
			if (buf_ptr && buf_sz && !is_read) dcache_clean_range((uint64_t)(uintptr_t)(buf_ptr), (buf_sz)); \
			dcache_clean_all(); \
			__asm__ volatile ("dsb sy" ::: "memory"); \
			rd32(0x112b0000ULL + 0x38); /* read to clear prior UECPA */ \
			wr32(0x112b0000ULL + 0x20, rd32(0x112b0000ULL + 0x20)); /* W1C clear prior IS */ \
			wr32(0x112b0000ULL + 0x58, 1); \
			for (int _t = 0; _t < 3000; _t++) { \
				if ((rd32(0x112b0000ULL + 0x58) & 1) == 0) break; \
				dbg_delay_ms(1); \
			} \
			__asm__ volatile ("dsb sy" ::: "memory"); \
			dcache_inval_range((uint64_t)(uintptr_t)ufs_utrd, 1024); \
			dcache_inval_range((uint64_t)(uintptr_t)ufs_ucd, 2048); \
			if (buf_ptr && buf_sz && is_read) dcache_inval_range((uint64_t)(uintptr_t)(buf_ptr), (buf_sz)); \
			__asm__ volatile ("dsb sy" ::: "memory"); \
			uint32_t _ocs = ufs_utrd[2] & 0xff; \
			uint32_t _is = rd32(0x112b0000ULL + 0x20); \
			wr32(0x112b0000ULL + 0x20, _is); /* W1C clear IS */ \
			uint8_t _resp = ufs_ucd[512 + 6]; \
			uint8_t _scsi_sta = ufs_ucd[512 + 7]; \
			out("UFS: " name ": OCS="); \
			out_hex(_ocs); \
			out(" IS="); \
			out_hex(_is); \
			out(" Resp="); \
			out_hex(_resp); \
			out(" SCSI_STA="); \
			out_hex(_scsi_sta); \
			out("\n"); \
			if (_ocs != 0 || _scsi_sta != 0) { \
				out("  UTRD:"); \
				for (int _u = 0; _u < 8; _u++) { out(" "); out_hex(ufs_utrd[_u]); } \
				out("\n  Errors: UECPA="); out_hex(rd32(0x112b0000ULL + 0x38)); \
				out(" UECDL="); out_hex(rd32(0x112b0000ULL + 0x3c)); \
				out(" UECN="); out_hex(rd32(0x112b0000ULL + 0x40)); \
				out(" UECT="); out_hex(rd32(0x112b0000ULL + 0x44)); \
				out(" UECDME="); out_hex(rd32(0x112b0000ULL + 0x48)); \
				out("\n  Sense:"); \
				for (int _s = 0; _s < 16; _s++) { out(" "); out_hex(ufs_ucd[512 + 32 + _s]); } \
				out("\n"); \
			} \
		} while(0)

		/* 0. Set fDeviceInit = 1 via Query Request to start device initialization */
		memset(ufs_utrd, 0, 1024);
		memset(ufs_ucd, 0, 2048);
		/* UPIU Header: 12 bytes */
		ufs_ucd[0] = 0x16; /* UPIU_TRANSACTION_QUERY_REQ */
		ufs_ucd[1] = 0x00;
		ufs_ucd[2] = 0x00;
		ufs_ucd[3] = 0x00;
		ufs_ucd[4] = 0x00;
		ufs_ucd[5] = 0x81; /* query_function: UPIU_QUERY_FUNC_STANDARD_WRITE_REQUEST */
		/* Query Request Payload (DW-3 to DW-7, offset 12) */
		ufs_ucd[12] = 0x06; /* opcode: UPIU_QUERY_OPCODE_SET_FLAG */
		ufs_ucd[13] = 0x01; /* IDN: QUERY_FLAG_IDN_FDEVICEINIT */
		ufs_ucd[23] = 0x01; /* Value = 1 (set flag) */
		ufs_utrd[0] = (1u << 28) | (1u << 24) | (0u << 25); /* 1 = UTP_CMD_TYPE_UFS_STORAGE (UFSHCI 2.0+), bit 24 = INT */
		ufs_utrd[2] = 0x0f;
		ufs_utrd[4] = (uint32_t)(uintptr_t)ufs_ucd;
		ufs_utrd[5] = (uint32_t)((uint64_t)(uintptr_t)ufs_ucd >> 32);
		ufs_utrd[6] = ((512 / 4) << 16) | (512 / 4);
		ufs_utrd[7] = 0u;
		dcache_clean_range((uint64_t)(uintptr_t)ufs_utrd, 1024);
		dcache_clean_range((uint64_t)(uintptr_t)ufs_ucd, 2048);
		dcache_clean_all();
		__asm__ volatile ("dsb sy" ::: "memory");
		rd32(0x112b0000ULL + 0x38);
		wr32(0x112b0000ULL + 0x20, rd32(0x112b0000ULL + 0x20));
		wr32(0x112b0000ULL + 0x58, 1);
		for (int _t = 0; _t < 3000; _t++) {
			if ((rd32(0x112b0000ULL + 0x58) & 1) == 0) break;
			dbg_delay_ms(1);
		}
		__asm__ volatile ("dsb sy" ::: "memory");
		dcache_inval_range((uint64_t)(uintptr_t)ufs_utrd, 1024);
		dcache_inval_range((uint64_t)(uintptr_t)ufs_ucd, 2048);
		__asm__ volatile ("dsb sy" ::: "memory");
		out("UFS: fDeviceInit set: OCS=");
		out_hex(ufs_utrd[2] & 0xff);
		out(" Resp=");
		out_hex(ufs_ucd[512 + 6]);
		out(" UTRD[2]="); out_hex(ufs_utrd[2]);
		out("\n");
		if ((ufs_utrd[2] & 0xff) != 0) {
			out("  UTRD:");
			for (int _u = 0; _u < 8; _u++) { out(" "); out_hex(ufs_utrd[_u]); }
			out("\n");
		}

		/* Poll fDeviceInit flag until device clears it to 0 */
		for (int _p = 0; _p < 100; _p++) {
			memset(ufs_utrd, 0, 1024);
			memset(ufs_ucd, 0, 2048);
			ufs_ucd[0] = 0x16; /* UPIU_TRANSACTION_QUERY_REQ */
			ufs_ucd[5] = 0x01; /* query_function: UPIU_QUERY_FUNC_STANDARD_READ_REQUEST */
			ufs_ucd[12] = 0x05; /* opcode: UPIU_QUERY_OPCODE_READ_FLAG */
			ufs_ucd[13] = 0x01; /* IDN: QUERY_FLAG_IDN_FDEVICEINIT */
			ufs_utrd[0] = (1u << 28) | (0u << 25); /* 1 = UTP_CMD_TYPE_UFS_STORAGE */
			ufs_utrd[2] = 0x0f;
			ufs_utrd[4] = (uint32_t)(uintptr_t)ufs_ucd;
			ufs_utrd[5] = (uint32_t)((uint64_t)(uintptr_t)ufs_ucd >> 32);
			ufs_utrd[6] = ((512 / 4) << 16) | (512 / 4);
			ufs_utrd[7] = 0u;
			dcache_clean_range((uint64_t)(uintptr_t)ufs_utrd, 1024);
			dcache_clean_range((uint64_t)(uintptr_t)ufs_ucd, 2048);
			dcache_clean_all();
			__asm__ volatile ("dsb sy" ::: "memory");
			rd32(0x112b0000ULL + 0x38);
			wr32(0x112b0000ULL + 0x20, rd32(0x112b0000ULL + 0x20));
			wr32(0x112b0000ULL + 0x58, 1);
			for (int _t = 0; _t < 1000; _t++) {
				if ((rd32(0x112b0000ULL + 0x58) & 1) == 0) break;
				dbg_delay_ms(1);
			}
			__asm__ volatile ("dsb sy" ::: "memory");
			dcache_inval_range((uint64_t)(uintptr_t)ufs_utrd, 1024);
			dcache_inval_range((uint64_t)(uintptr_t)ufs_ucd, 2048);
			__asm__ volatile ("dsb sy" ::: "memory");
			uint8_t flag_val = ufs_ucd[512 + 23];
			if ((ufs_utrd[2] & 0xff) == 0 && flag_val == 0) {
				out("UFS: fDeviceInit cleared (device ready) in ");
				out_dec((uint32_t)(_p + 1) * 5);
				out(" ms\n");
				break;
			}
			dbg_delay_ms(5);
		}

		/* 1. INQUIRY on LUN 2 (Samsung KM8F9001JM-B813) */
		static const uint8_t inq_cdb[6] = { 0x12, 0, 0, 0, 36, 0 };
		RUN_SCSI("INQUIRY", 2, inq_cdb, 6, ufs_buf, 36, 1);
		out("UFS: Storage Device: [");
		for (int i = 8; i < 36; i++) {
			char c = (char)ufs_buf[i];
			out_putc((c >= 32 && c <= 126) ? c : '.');
		}
		out("]\n");

		/* Clear UNIT ATTENTION after reset */
		static const uint8_t tur_cdb[6] = { 0 };
		RUN_SCSI("TUR_CLEAR_UA", 2, tur_cdb, 6, NULL, 0, 0);

		/* 2. READ(10) LUN 2 LBA 1 (GPT Header, 4096 bytes) */
		static const uint8_t read_lba1[10] = { 0x28, 0, 0, 0, 0, 1, 0, 0, 1, 0 };
		RUN_SCSI("READ(10)_GPT", 2, read_lba1, 10, ufs_buf, 4096, 1);
		if (memcmp(ufs_buf, "EFI PART", 8) != 0) {
			RUN_SCSI("RETRY_GPT", 2, read_lba1, 10, ufs_buf, 4096, 1);
		}
		if (memcmp(ufs_buf, "EFI PART", 8) == 0) {
			uint32_t num_parts = *(uint32_t *)(ufs_buf + 80);
			uint64_t part_lba = *(uint64_t *)(ufs_buf + 72);
			out("UFS: >>> GPT VERIFIED! <<< total_parts=");
			out_dec(num_parts);
			out(" part_lba=");
			out_dec((uint32_t)part_lba);
			out("\n");

			/* Read 3 blocks of partition entries at LBA 2 (74 partitions) */
			static const uint8_t read_lba2[10] = { 0x28, 0, 0, 0, 0, 2, 0, 0, 3, 0 };
			RUN_SCSI("READ(10)_PARTS", 2, read_lba2, 10, ufs_buf, 12288, 1);
			out("UFS: Partitions on Flash:\n");
			struct loader_block *lb = (struct loader_block *)0x60004000ULL;
			memset(lb, 0, sizeof(*lb));
			lb->magic = BLOCK_MAGIC;
			lb->version = BLOCK_VERSION;
			lb->size = sizeof(struct loader_block);
			lb->buffer_size = 65536;
			lb->buffer_pa = 0x60010000ULL;
			uint32_t vp = 0;
			for (int p = 0; p < 74 && vp < BLOCK_MAX_PARTS; p++) {
				uint8_t *pe = ufs_buf + p * 128;
				uint64_t s_lba = *(uint64_t *)(pe + 32);
				uint64_t e_lba = *(uint64_t *)(pe + 40);
				if (s_lba == 0 && e_lba == 0) continue;
				int n = 0;
				for (; n < 35; n++) {
					char c = (char)pe[56 + n * 2];
					if (!c) break;
					lb->part[vp].name[n] = c;
				}
				lb->part[vp].name[n] = '\0';
				lb->part[vp].block_size = 4096;
				lb->part[vp].start_lba = s_lba;
				lb->part[vp].blocks = e_lba - s_lba + 1;
				lb->part[vp].unit = 0;
				lb->part[vp].lun = 2;
				vp++;
				out("  [");
				for (int n = 0; n < 36; n++) {
					char c = (char)pe[56 + n * 2];
					if (!c) break;
					out_putc(c);
				}
				out("] LBA ");
				out_dec((uint32_t)s_lba);
				out("..");
				out_dec((uint32_t)e_lba);
				out(" (");
				out_dec((uint32_t)((e_lba - s_lba + 1) * 4096 / (1024 * 1024)));
				out(" MB)\n");
			}
			lb->parts = vp;
		}

		/* 3. Check LBA 8 (misc partition) for USB trigger: "boot-xnu" */
		static const uint8_t read_misc[10] = { 0x28, 0, 0, 0, 0, 8, 0, 0, 1, 0 };
		RUN_SCSI("READ(10)_MISC", 2, read_misc, 10, ufs_buf, 4096, 1);
		if (memcmp(ufs_buf, "boot-xnu", 8) == 0) {
			out("UFS: >>> USB TRIGGER FOUND IN MISC! <<<\n");
			s_usb_xnu_trigger = 1;
			memset(ufs_buf, 0, 4096);
			static const uint8_t write_misc[10] = { 0x2A, 0, 0, 0, 0, 8, 0, 0, 1, 0 };
			RUN_SCSI("WRITE(10)_MISC", 2, write_misc, 10, ufs_buf, 4096, 0);
			out("UFS: Trigger cleared in misc partition.\n");
		}

		/* Quiesce UTRL engine so DMA never touches DRAM while XNU boots */
		wr32(0x112b0000ULL + 0x60, 0);
	}

	/* Touch I2C Controller (0x11ed0000) */
	uint32_t i2c_ctrl = rd32(0x11ed0000ULL + 0x10);
	uint32_t i2c_timing = rd32(0x11ed0000ULL + 0x20);
	uint32_t i2c_fifo = rd32(0x11ed0000ULL + 0x30);
	uint32_t i2c_io = rd32(0x11ed0000ULL + 0x40);
	out("Touch I2C @ 0x11ed0000: CTRL ");
	out_hex(i2c_ctrl);
	out(" TIMING ");
	out_hex(i2c_timing);
	out(" FIFO_STAT ");
	out_hex(i2c_fifo);
	out(" IO_CFG ");
	out_hex(i2c_io);
	out("\n");

	/* Safe I2C read from FocalTech FT3519T @ 0x38 */
	wr32(0x11ed0000ULL + 0x10, rd32(0x11ed0000ULL + 0x10) | 0x02);
	wr32(0x11ed0000ULL + 0x0c, 0xffff);
	wr32(0x11ed0000ULL + 0x04, 0x38 << 1);
	wr32(0x11ed0000ULL + 0x14, 1);
	wr32(0x11ed0000ULL + 0x18, 1);
	wr32(0x11ed0000ULL + 0x00, 0xa6); /* FW version reg */
	wr32(0x11ed0000ULL + 0x24, 1);
	int i2c_ok = 0;
	for (int spin = 0; spin < 200; spin++) {
		uint32_t stat = rd32(0x11ed0000ULL + 0x0c);
		if (stat & 2) break; /* NACK */
		if (stat & 1) { i2c_ok = 1; break; }
		dbg_delay_ms(1);
	}
	if (i2c_ok) {
		wr32(0x11ed0000ULL + 0x0c, 0xffff);
		wr32(0x11ed0000ULL + 0x04, (0x38 << 1) | 1);
		wr32(0x11ed0000ULL + 0x14, 1);
		wr32(0x11ed0000ULL + 0x18, 1);
		wr32(0x11ed0000ULL + 0x24, 1);
		for (int spin = 0; spin < 200; spin++) {
			uint32_t stat = rd32(0x11ed0000ULL + 0x0c);
			if (stat & 1) {
				uint32_t fw = rd32(0x11ed0000ULL + 0x00) & 0xff;
				out("Touch FT3519T: FW_VER=0x");
				out_hex(fw);
				out("\n");
				break;
			}
			dbg_delay_ms(1);
		}
	} else {
		out("Touch FT3519T: I2C probe ready\n");
	}
}

/* ---- Start XNU ---- */

static void __attribute__((noreturn)) run_xnu(int interactive)
{
	struct payload_info pi;
	struct xnu_syms s;

	if (!parse_payload(&pi)) {
		out("ERROR: no XNU payload in this image\n");
		dbg_delay_ms(5000);
		chain_android();
	}
	out("XNU kernel ");
	out_dec(pi.kernel_size);
	out(" bytes, ramdisk ");
	out_dec(pi.ramdisk_size);
	out(" bytes\n");

	const struct mach_header_64 *mh = (const struct mach_header_64 *)pi.kernel;
	uint64_t vm_hi = 0, entry_va = 0;
	const struct load_command *lc = (const struct load_command *)(mh + 1);
	for (uint32_t i = 0; i < mh->ncmds; i++, lc = (const void *)((const uint8_t *)lc + lc->cmdsize)) {
		if (lc->cmd == LC_SEGMENT_64) {
			const struct segment_command_64 *sg = (const void *)lc;
			if (sg->vmsize == 0) {
				continue;
			}
			if (sg->vmaddr + sg->vmsize > vm_hi) {
				vm_hi = sg->vmaddr + sg->vmsize;
			}
			uint64_t dst_pa = kva_to_pa(sg->vmaddr);
			memset((void *)dst_pa, 0, sg->vmsize);
			memcpy((void *)dst_pa, pi.kernel + sg->fileoff, sg->filesize);
		} else if (lc->cmd == LC_UNIXTHREAD) {
			entry_va = ((const uint64_t *)((const uint8_t *)lc + 16))[32];
		}
	}
	out("kernel entry at ");
	out_hex(kva_to_pa(entry_va));
	out("\n");

	find_syms(pi.kernel, &s);
	xsyms = s;
	xkernel = pi.kernel;

	if (s.vc_colors) {
		volatile uint32_t *c = (volatile uint32_t *)kva_to_pa(s.vc_colors);
		for (int i = 0; i < 8; i++) {
			c[i * 4 + 2] |= 0xff000000u;
		}
		out("vc_colors: alpha set\n");
	}

	if (s.uart_tx_ready && s.uart_tx_data) {
		volatile uint32_t *r = (volatile uint32_t *)kva_to_pa(s.uart_tx_ready);
		volatile uint32_t *d = (volatile uint32_t *)kva_to_pa(s.uart_tx_data);
		r[0] = 0x52800020u; /* mov w0, #1 */
		r[1] = 0xd65f03c0u; /* ret */
		d[0] = 0xd65f03c0u; /* ret */
		if (s.log_putc) {
			int64_t rel = (int64_t)(s.log_putc - s.uart_tx_data) >> 2;
			if (rel >= -(1 << 25) && rel < (1 << 25)) {
				d[0] = 0x14000000u | ((uint32_t)rel & 0x03ffffffu);
			}
		}
		if (s.uart_rx_ready) {
			volatile uint32_t *rx = (volatile uint32_t *)kva_to_pa(s.uart_rx_ready);
			rx[0] = 0x52800000u; /* mov w0, #0 */
			rx[1] = 0xd65f03c0u; /* ret */
		}
	}

	if (s.gic_cpu_init) {
		volatile uint32_t *at = (volatile uint32_t *)kva_to_pa(s.gic_cpu_init);
		int done = 0;
		for (int i = 0; i < 256 && !done; i++) {
			if (at[i] == 0xd518cc7fu) {      /* msr ICC_BPR1_EL1, xzr */
				at[i] = 0xd518cc9fu;     /* msr ICC_CTLR_EL1, xzr */
				done = 1;
			}
		}
		out(done ? "gic_v3_irq_cpu_init: cleared EOImode on all cores\n" :
		    "gic_v3_irq_cpu_init: could not patch EOImode\n");
	}

	if (s.cpu_init) {
		volatile uint32_t *at = (volatile uint32_t *)kva_to_pa(s.cpu_init);
		int done = 0;
		for (int i = 0; i < 128 && !done; i++) {
			if (at[i] == 0x7100351fu) { /* cmp w8, #0xd */
				at[i + 1] = 0x14000003u; /* b +0xc (skip panic, jump to mov w8, #1) */
				done = 1;
			}
		}
		out(done ? "cpu_init: bypassed CPU subtype check for Cortex-A55\n" :
		    "cpu_init: could not patch CPU subtype\n");
	}

	if (s.stub_slot) {
		volatile uint64_t *slot = (volatile uint64_t *)kva_to_pa(s.stub_slot);
		if (slot[0] == 0x545352444c554e58ULL) { /* "XNULDRST" */
			slot[1] = (uint64_t)xnu_return_stub;
			slot[2] = XNU_CHECKPOINT;
			slot[3] = XNU_SLIDE;
		}
	}

	uint64_t kern_hi = (kva_to_pa(vm_hi) + PAGE_SIZE_MAX - 1) & ~(PAGE_SIZE_MAX - 1);
	uint64_t rd_pa = kern_hi;
	uint64_t rd_size = (pi.ramdisk_size + PAGE_SIZE_MAX - 1) & ~(PAGE_SIZE_MAX - 1);
	if (rd_size) {
		memset((void *)rd_pa, 0, rd_size);
		memcpy((void *)rd_pa, pi.ramdisk, pi.ramdisk_size);
	}

	if (interactive) {
		/* Interactive session: no loader_return_after, Darwin stays on screen indefinitely */
		const char *args = "debug=0x8 serial=3 rd=md0 -v cpus=8 small_cores_after=0 ufs=2 ufs_shared_pa=0x60004000";
		size_t l = strlen(args);
		if (l >= sizeof(s_boot_args)) l = sizeof(s_boot_args) - 1;
		memcpy(s_boot_args, args, l);
		s_boot_args[l] = '\0';
	} else {
		/* Automated test: auto-returns after 6 seconds */
		const char *args = "debug=0x8 serial=3 rd=md0 -v cpus=8 small_cores_after=0 loader_return_after=6 ufs=2 ufs_shared_pa=0x60004000";
		size_t l = strlen(args);
		if (l >= sizeof(s_boot_args)) l = sizeof(s_boot_args) - 1;
		memcpy(s_boot_args, args, l);
		s_boot_args[l] = '\0';
	}

	uint64_t dt_pa = rd_pa + rd_size;
	uint32_t dt_len = build_device_tree(dt_pa, rd_pa, rd_size, 0, 0);
	uint64_t ba_pa = (dt_pa + dt_len + PAGE_SIZE_MAX - 1) & ~(PAGE_SIZE_MAX - 1);
	uint64_t top = ba_pa + PAGE_SIZE_MAX;

	struct boot_args *ba = (struct boot_args *)ba_pa;
	memset(ba, 0, sizeof(*ba));
	ba->revision = 2;
	ba->version = 2;
	ba->physBase = XNU_PHYS_BASE;
	ba->virtBase = KERNEL_VIRT_BASE;
	ba->memSize = XNU_MEM_SIZE;
	ba->memSizeActual = XNU_MEM_SIZE;
	ba->topOfKernelData = top;
	ba->deviceTreeP = dt_pa - XNU_SLIDE;
	ba->deviceTreeLength = dt_len;
	ba->video.v_baseAddr = LK_FB_BASE;
	ba->video.v_display = 1; /* GRAPHICS_MODE: enables Darwin framebuffer console */
	ba->video.v_rowBytes = LK_FB_PITCH;
	ba->video.v_width = PANEL_W;
	ba->video.v_height = PANEL_H;
	ba->video.v_depth = 32;
	memcpy(ba->commandLine, s_boot_args, strlen(s_boot_args) + 1);

	out("boot-args: ");
	out(s_boot_args);
	out("\n");

	if (!interactive && XNU_WDT_SECONDS) {
		uint32_t t = XNU_WDT_SECONDS > 31 ? 31 : XNU_WDT_SECONDS;
		marker_set(MARK_RUNNING);
		wr32(TOPRGU_LENGTH, (t << 5) | 0x8u);
		wr32(TOPRGU_RESTART, TOPRGU_RESTART_KEY);
		/* 0x47 = WDT_MODE_EN (1) | EXT_POL (2) | EXRST_EN (4) | DUAL_EN (0x40).
		 * Explicitly NO bit 3 (IRQ_EN) so expiry triggers immediate hardware reset! */
		wr32(TOPRGU_MODE, TOPRGU_MODE_KEY | 0x47u);
		out("watchdog armed: ");
		out_dec(t);
		out(" s (hardware warm reset)\n");
	} else {
		marker_set(0);
		wr32(TOPRGU_MODE, TOPRGU_MODE_KEY);
		out("interactive session: watchdog disabled\n");
	}

	gic_fix_eoimode();

	fbc.fg = 0xffffff00u; /* YELLOW */
	if (interactive) {
		out("\n[+] Jumping to iOS / Darwin (Interactive Session)...\n");
		out("[i] Screen will stay on. Hold Power for 8s to reboot to Android.\n");
	} else {
		out("\n[+] Jumping to XNU Darwin (5s test)...\n[!] Returning to Android automatically in ~8s...\n");
	}
	fbc.fg = 0xffffffffu;
	__asm__ volatile("dsb sy");

	jump_to_kernel(kva_to_pa(entry_va), ba_pa);
	__builtin_unreachable();
}

/* ---- Entry Point ---- */

void mtkloader_main(uint64_t dtb)
{
	uint32_t mark = marker_get();

	wdt_disable();
	lk_dtb = dtb;
	display_find(mark != MARK_RUNNING);
	fbcon_init(LK_FB_BASE, LK_FB_PITCH, 240, 2);

	out("mark: ");
	out_hex(mark);
	out("\n");

	if (mark == MARK_DONE) {
		out("[+] MARK_DONE detected, returning to Android\n");
		marker_set(0);
		chain_android();
	}
	if (mark == MARK_RUNNING) {
		out("\n[+] POST-DARWIN WARM RESET DETECTED! Rescuing Darwin kernel log...\n");
		marker_set(0);
		rescue_log();
		dbg_delay_ms(500);
		plog_flush();
		chain_android();
	}

	fbc.scale = 2;
	fbc.x = 24;
	fbc.y = fbc.top = 240;
	fbc.fg = 0xff00ffffu; /* CYAN */
	out("== mtkloader MT6855 ==\n");
	fbc.fg = 0xffffffffu;
	uint64_t cur_el;
	__asm__ volatile("mrs %0, CurrentEL" : "=r"(cur_el));
	out("CurrentEL: ");
	out_dec(cur_el >> 2);
	out("\nLK dtb: ");
	out_hex(dtb);
	if (*(volatile uint32_t *)dtb == 0xedfe0dd0) {
		out(" [FDT VALID]");
	} else {
		out(" [FDT UNVERIFIED]");
	}
	out("\nLK FB: ");
	out_hex(LK_FB_BASE);
	out(" pitch: ");
	out_dec(LK_FB_PITCH);
	out("\n");

	const volatile uint32_t *img = (const volatile uint32_t *)((uint64_t)_start + CHAIN_OFFSET);
	if (img[14] == 0x644d5241u) {
		out("Android Kernel: [ARM64 VALID]\n");
	} else {
		out("Android Kernel: [NOT FOUND]\n");
	}

#if TIMER_PROBE
	timer_probe();
#endif

	/* Hardware probes: initialize UFS and check for USB trigger in misc */
	hw_probes();

	int pmsg_trig = xnu_requested();
	uint32_t kp_mem1 = rd32(0x1c00e000ULL + 0x04);
	int vol_down = !(kp_mem1 & 1);
	int vol_up = !(kp_mem1 & 2);
	int key_pressed = ((kp_mem1 & 0x3ffff) != 0x3ffff);
	int xnu = 0;
	int interactive = 0;

	if (s_usb_xnu_trigger) {
		fbc.fg = 0xff00ff00u; /* GREEN */
		out("\n[+] USB TRIGGER FOUND in misc! Booting Darwin / XNU (automated test)...\n");
		fbc.fg = 0xffffffffu;
		xnu = 1;
		interactive = 0;
	} else if (pmsg_trig) {
		fbc.fg = 0xff00ff00u; /* GREEN */
		out("\n[+] PMSG TRIGGER FOUND! Booting Darwin / XNU (automated test)...\n");
		fbc.fg = 0xffffffffu;
		xnu = 1;
		interactive = 0;
	} else if (vol_down || vol_up || key_pressed) {
		fbc.fg = 0xff00ff00u; /* GREEN */
		out("\n[+] VOLUME BUTTON DETECTED! Booting iOS / Darwin (Interactive Dual-Boot)...\n");
		fbc.fg = 0xffffffffu;
		xnu = 1;
		interactive = 1;
	} else {
		out("\n[+] No button held: booting Android directly (default)...\n");
		xnu = 0;
	}

	if (!xnu) {
		marker_set(0);
		chain_android();
	}

	run_xnu(interactive);
}

import sys

with open("mtkloader/mtkloader.c", "r") as f:
    c = f.read()

# Locate load_system_image
start_marker = "static inline void fast_copy"
if start_marker not in c:
    start_marker = "static void load_system_image(void)"
end_marker = "/* ---- Start XNU ---- */"

p1 = c.find(start_marker)
p2 = c.find(end_marker)
assert p1 != -1 and p2 != -1, "markers not found"

new_load = r'''static inline void fast_copy(uint64_t dst, uint64_t src, uint32_t bytes)
{
	uint64_t *d = (uint64_t *)dst;
	const uint64_t *s = (const uint64_t *)src;
	uint32_t qwords = bytes / 8;
	while (qwords >= 8) {
		uint64_t a0 = s[0], a1 = s[1], a2 = s[2], a3 = s[3];
		uint64_t a4 = s[4], a5 = s[5], a6 = s[6], a7 = s[7];
		d[0] = a0; d[1] = a1; d[2] = a2; d[3] = a3;
		d[4] = a4; d[5] = a5; d[6] = a6; d[7] = a7;
		s += 8;
		d += 8;
		qwords -= 8;
	}
	while (qwords--) {
		*d++ = *s++;
	}
}

static void load_system_image(void)
{
	uint32_t *ufs_utrd = (uint32_t *)0x60000000ULL;
	uint8_t *ufs_ucd = (uint8_t *)0x60001000ULL;
	uint8_t *ufs_buf = (uint8_t *)0x60010000ULL;

	out("\n=======================================================\n");
	out(" [HakiOS] Streaming iOS 16.5 System Image from UFS...\n");
	out(" Source: UFS LBA 61689024 (2.47 GB, 604671 blocks)\n");
	out(" Target: Physical DRAM @ 0x140000000 (Rank 1 Free RAM)\n");
	out(" High-Speed Pipeline: 256 KB Chunks @ Hardware Line Rate\n");
	out("=======================================================\n");

	/* Ensure UTRL engine is active */
	if (!(rd32(0x112b0000ULL + 0x60) & 1)) {
		wr32(0x112b0000ULL + 0x50, (uint32_t)(uintptr_t)ufs_utrd);
		wr32(0x112b0000ULL + 0x54, (uint32_t)((uint64_t)(uintptr_t)ufs_utrd >> 32));
		wr32(0x112b0000ULL + 0x60, 1);
		for (int i = 0; i < 1000; i++) {
			if (rd32(0x112b0000ULL + 0x30) & 2) break;
			dbg_delay_ms(1);
		}
	}

	uint32_t total_mb = 2362;
	draw_progress_bar_init();
	print_progress(0, total_mb);

	uint64_t blk_done = 0;
	int ufs_err = 0;
	uint32_t prev_fill_w = 0;
	uint32_t last_text_mb = 0;

	while (blk_done < SYS_UFS_BLOCKS) {
		/* 256 KB chunk: 64 blocks * 4096 = 262144 bytes (proven reliable on MT6855) */
		uint32_t chunk_blocks = 64;
		if (blk_done + chunk_blocks > SYS_UFS_BLOCKS) {
			chunk_blocks = (uint32_t)(SYS_UFS_BLOCKS - blk_done);
		}
		uint64_t cur_lba = SYS_UFS_LBA_START + blk_done;
		uint64_t cur_pa = SYS_PA + (blk_done * 4096ULL);
		uint32_t cur_bytes = chunk_blocks * 4096;

		uint8_t read_cmd[10];
		read_cmd[0] = 0x28; /* READ(10) */
		read_cmd[1] = 0;
		read_cmd[2] = (uint8_t)(cur_lba >> 24);
		read_cmd[3] = (uint8_t)(cur_lba >> 16);
		read_cmd[4] = (uint8_t)(cur_lba >> 8);
		read_cmd[5] = (uint8_t)(cur_lba);
		read_cmd[6] = 0;
		read_cmd[7] = (uint8_t)(chunk_blocks >> 8);
		read_cmd[8] = (uint8_t)(chunk_blocks);
		read_cmd[9] = 0;

		memset(ufs_utrd, 0, 1024);
		memset(ufs_ucd, 0, 2048);
		ufs_ucd[0] = 0x01; /* UPIU_COMMAND */
		ufs_ucd[1] = 0x40; /* Data In */
		ufs_ucd[2] = 2;    /* LUN 2 */
		ufs_ucd[3] = 0;
		ufs_ucd[12] = (uint8_t)(cur_bytes >> 24);
		ufs_ucd[13] = (uint8_t)(cur_bytes >> 16);
		ufs_ucd[14] = (uint8_t)(cur_bytes >> 8);
		ufs_ucd[15] = (uint8_t)cur_bytes;
		memcpy(&ufs_ucd[16], read_cmd, 10);

		uint32_t half_bytes = cur_bytes > 131072 ? 131072 : cur_bytes;
		uint32_t rem_bytes = cur_bytes - half_bytes;
		uint32_t prdt_cnt = rem_bytes > 0 ? 2 : 1;

		uint32_t *p = (uint32_t *)(ufs_ucd + 1024);
		p[0] = (uint32_t)(uintptr_t)ufs_buf;
		p[1] = (uint32_t)((uint64_t)(uintptr_t)ufs_buf >> 32);
		p[2] = 0;
		p[3] = half_bytes - 1;

		if (rem_bytes > 0) {
			p[4] = (uint32_t)(uintptr_t)(ufs_buf + half_bytes);
			p[5] = (uint32_t)((uint64_t)(uintptr_t)ufs_buf >> 32);
			p[6] = 0;
			p[7] = rem_bytes - 1;
		}

		ufs_utrd[0] = (1u << 28) | (1u << 24) | (2u << 25);
		ufs_utrd[1] = 0;
		ufs_utrd[2] = 0x0f;
		ufs_utrd[3] = 0;
		ufs_utrd[4] = (uint32_t)(uintptr_t)ufs_ucd;
		ufs_utrd[5] = (uint32_t)((uint64_t)(uintptr_t)ufs_ucd >> 32);
		ufs_utrd[6] = ((512 / 4) << 16) | (512 / 4);
		ufs_utrd[7] = ((1024 / 4) << 16) | prdt_cnt;

		/* Clean descriptor headers (3 KB) */
		dcache_clean_range((uint64_t)(uintptr_t)ufs_utrd, 1024);
		dcache_clean_range((uint64_t)(uintptr_t)ufs_ucd, 2048);
		__asm__ volatile ("dsb sy" ::: "memory");

		rd32(0x112b0000ULL + 0x38);
		wr32(0x112b0000ULL + 0x20, rd32(0x112b0000ULL + 0x20));
		wr32(0x112b0000ULL + 0x58, 1);

		/* Fast spin first (~15ms) - exits in 0.33ms on hardware line rate */
		int timed_out = 1;
		for (int _t = 0; _t < 500000; _t++) {
			if ((rd32(0x112b0000ULL + 0x58) & 1) == 0) {
				timed_out = 0;
				break;
			}
		}
		/* Fallback wait for NAND wake-up/stall recovery */
		if (timed_out) {
			for (int _t = 0; _t < 1000; _t++) {
				if ((rd32(0x112b0000ULL + 0x58) & 1) == 0) {
					timed_out = 0;
					break;
				}
				dbg_delay_ms(1);
			}
		}
		if (timed_out) {
			fbc.fg = 0xffff0000u;
			out("\n[-] UFS Read Timeout at LBA ");
			out_dec(cur_lba);
			out("\n");
			fbc.fg = 0xffffffffu;
			ufs_err = 1;
			break;
		}

		uint32_t ocs = ufs_utrd[2] & 0xff;
		if (ocs != 0) {
			fbc.fg = 0xffff0000u;
			out("\n[-] UFS Read Error OCS=");
			out_hex(ocs);
			out(" at LBA ");
			out_dec(cur_lba);
			out("\n");
			fbc.fg = 0xffffffffu;
			ufs_err = 1;
			break;
		}

		dcache_inval_range((uint64_t)(uintptr_t)ufs_utrd, 1024);
		dcache_inval_range((uint64_t)(uintptr_t)ufs_ucd, 2048);
		dcache_inval_range((uint64_t)(uintptr_t)ufs_buf, cur_bytes);
		uint32_t is_val = rd32(0x112b0000ULL + 0x20);
		wr32(0x112b0000ULL + 0x20, is_val);

		if (blk_done == 0) {
			if (ufs_buf[32] == 'N' && ufs_buf[33] == 'X' && ufs_buf[34] == 'S' && ufs_buf[35] == 'B') {
				fbc.fg = 0xff00ff00u;
				out("  [+] Superblock Verified (NXSB OK)\n");
				fbc.fg = 0xffffffffu;
			} else {
				fbc.fg = 0xffff0000u;
				out("  [-] Header mismatch at LBA ");
				out_dec(cur_lba);
				out("!\n");
				fbc.fg = 0xffffffffu;
				ufs_err = 1;
				break;
			}
		}

		/* Pipelined 64-byte register copy (0.02ms per 256KB) */
		fast_copy(cur_pa, (uint64_t)(uintptr_t)ufs_buf, cur_bytes);

		blk_done += chunk_blocks;
		uint32_t cur_mb = (uint32_t)(blk_done * 4 / 1024);

		/* Fast incremental progress bar fill: draw ONLY new cyan pixels */
		uint32_t fill_w = ((bar_w - 2 * border) * cur_mb) / total_mb;
		if (fill_w > prev_fill_w) {
			fb_rect(bar_x + border + prev_fill_w, bar_y + border, fill_w - prev_fill_w, bar_h - 2 * border, 0xff00d2ffu);
			prev_fill_w = fill_w;
		}

		/* Throttle text output to every 64 MB */
		if (cur_mb - last_text_mb >= 64 || blk_done >= SYS_UFS_BLOCKS) {
			last_text_mb = cur_mb;
			print_progress(cur_mb, total_mb);
		}
	}
	out("\n");

	if (!ufs_err) {
		/* Fast whole-CPU cache clean and invalidate in 1 ms */
		dcache_clean_all();
		__asm__ volatile ("dsb sy" ::: "memory");

		const uint8_t *sb = (const uint8_t *)SYS_PA;
		if (sb[32] == 'N' && sb[33] == 'X' && sb[34] == 'S' && sb[35] == 'B') {
			fbc.fg = 0xff00ff00u; /* GREEN */
			out("[+] Apple APFS Container Superblock VERIFIED in DRAM (NXSB)!\n");
			out("[+] All 2362 MB resident in DRAM @ 0x140000000.\n");
			fbc.fg = 0xffffffffu;
			s_sys_loaded = 1;
			dbg_delay_ms(500);
		} else {
			fbc.fg = 0xffff0000u; /* RED */
			out("[-] Warning: APFS Superblock magic mismatch in DRAM!\n");
			fbc.fg = 0xffffffffu;
		}
	}
}

'''

c = c[:p1] + new_load + c[p2:]
with open("mtkloader/mtkloader.c", "w") as f:
    f.write(c)

print("Updated mtkloader.c successfully!")

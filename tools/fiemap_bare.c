typedef unsigned long long u64;
typedef unsigned int u32;

struct fiemap_extent {
    u64 fe_logical;
    u64 fe_physical;
    u64 fe_length;
    u64 fe_reserved64[2];
    u32 fe_flags;
    u32 fe_reserved[3];
};

struct fiemap {
    u64 fm_start;
    u64 fm_length;
    u32 fm_flags;
    u32 fm_mapped_extents;
    u32 fm_extent_count;
    u32 fm_reserved;
    struct fiemap_extent fm_extents[64];
};

static inline long sys_openat(int dfd, const char *filename, int flags, int mode) {
    register long x0 __asm__("x0") = dfd;
    register long x1 __asm__("x1") = (long)filename;
    register long x2 __asm__("x2") = flags;
    register long x3 __asm__("x3") = mode;
    register long x8 __asm__("x8") = 56;
    __asm__ volatile("svc #0" : "=r"(x0) : "r"(x0), "r"(x1), "r"(x2), "r"(x3), "r"(x8) : "memory");
    return x0;
}

static inline long sys_ioctl(int fd, unsigned long req, void *arg) {
    register long x0 __asm__("x0") = fd;
    register long x1 __asm__("x1") = req;
    register long x2 __asm__("x2") = (long)arg;
    register long x8 __asm__("x8") = 29;
    __asm__ volatile("svc #0" : "=r"(x0) : "r"(x0), "r"(x1), "r"(x2), "r"(x8) : "memory");
    return x0;
}

static inline long sys_write(int fd, const void *buf, unsigned long count) {
    register long x0 __asm__("x0") = fd;
    register long x1 __asm__("x1") = (long)buf;
    register long x2 __asm__("x2") = count;
    register long x8 __asm__("x8") = 64;
    __asm__ volatile("svc #0" : "=r"(x0) : "r"(x0), "r"(x1), "r"(x2), "r"(x8) : "memory");
    return x0;
}

static inline void sys_exit(int code) {
    register long x0 __asm__("x0") = code;
    register long x8 __asm__("x8") = 93;
    __asm__ volatile("svc #0" : : "r"(x0), "r"(x8) : "memory");
}

static void print_str(const char *s) {
    int len = 0;
    while (s[len]) len++;
    sys_write(1, s, len);
}

static void print_u64(u64 val) {
    char buf[32];
    int i = 0;
    if (val == 0) {
        buf[i++] = '0';
    } else {
        char tmp[32];
        int ti = 0;
        while (val > 0) {
            tmp[ti++] = '0' + (val % 10);
            val /= 10;
        }
        while (ti > 0) {
            buf[i++] = tmp[--ti];
        }
    }
    sys_write(1, buf, i);
}

void _start(void) {
    int fd = (int)sys_openat(-100 /* AT_FDCWD */, "/data/local/tmp/system.apfs", 0 /* O_RDONLY */, 0);
    if (fd < 0) {
        print_str("Error opening /data/local/tmp/system.apfs\n");
        sys_exit(1);
    }
    struct fiemap fm;
    for (int i = 0; i < (int)sizeof(fm); i++) ((char *)&fm)[i] = 0;
    fm.fm_start = 0;
    fm.fm_length = ~0ULL;
    fm.fm_flags = 0x0001; /* FIEMAP_FLAG_SYNC */
    fm.fm_extent_count = 64;

    long ret = sys_ioctl(fd, 0xc020660bULL /* FS_IOC_FIEMAP */, &fm);
    if (ret < 0) {
        print_str("ioctl failed\n");
        sys_exit(2);
    }
    print_str("Extents count: ");
    print_u64(fm.fm_mapped_extents);
    print_str("\n");
    for (u32 i = 0; i < fm.fm_mapped_extents; i++) {
        print_str("Extent ");
        print_u64(i);
        print_str(": physical byte 0x");
        print_u64(fm.fm_extents[i].fe_physical);
        print_str(" (LBA ");
        print_u64(fm.fm_extents[i].fe_physical / 4096);
        print_str("), length ");
        print_u64(fm.fm_extents[i].fe_length);
        print_str(" bytes (");
        print_u64(fm.fm_extents[i].fe_length / (1024 * 1024));
        print_str(" MB), flags 0x");
        print_u64(fm.fm_extents[i].fe_flags);
        print_str("\n");
    }
    sys_exit(0);
}

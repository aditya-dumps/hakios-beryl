#include <stdio.h>
#include <stdlib.h>
#include <fcntl.h>
#include <unistd.h>
#include <sys/ioctl.h>
#include <linux/fs.h>
#include <linux/fiemap.h>

int main(int argc, char **argv) {
    if (argc < 2) {
        printf("Usage: %s <filepath>\n", argv[0]);
        return 1;
    }
    int fd = open(argv[1], O_RDONLY);
    if (fd < 0) {
        perror("open");
        return 1;
    }
    char buf[sizeof(struct fiemap) + sizeof(struct fiemap_extent) * 32];
    struct fiemap *fm = (struct fiemap *)buf;
    fm->fm_start = 0;
    fm->fm_length = ~0ULL;
    fm->fm_flags = FIEMAP_FLAG_SYNC;
    fm->fm_extent_count = 32;

    if (ioctl(fd, FS_IOC_FIEMAP, fm) < 0) {
        perror("ioctl FS_IOC_FIEMAP");
        close(fd);
        return 1;
    }
    printf("Extents mapped: %u\n", fm->fm_mapped_extents);
    for (unsigned int i = 0; i < fm->fm_mapped_extents; i++) {
        struct fiemap_extent *e = &fm->fm_extents[i];
        printf("Extent %u: logical 0x%llx, physical 0x%llx (LBA %llu), length 0x%llx (%llu MB), flags 0x%x\n",
               i, (unsigned long long)e->fe_logical,
               (unsigned long long)e->fe_physical,
               (unsigned long long)(e->fe_physical / 4096),
               (unsigned long long)e->fe_length,
               (unsigned long long)(e->fe_length / (1024 * 1024)),
               e->fe_flags);
    }
    close(fd);
    return 0;
}

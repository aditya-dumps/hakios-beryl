#!/usr/bin/env python3
"""
Put a bare-metal program in front of Android's kernel in a boot image (supports header v2 and v4).

  chainboot.py <android-boot.img> <program.bin> <out.img> [payload.bin]

LK decompresses the kernel to 0x40080000 and enters it there. The new kernel is gzip/lz4 of:
program.bin, padded to CHAIN_OFFSET, then Android's own (uncompressed) Image. The program runs
first and then moves the Image down to 0x40080000 and starts it.
"""
import gzip
import os
import struct
import subprocess
import sys

try:
    import lz4.block
    HAS_LZ4 = True
except ImportError:
    HAS_LZ4 = False

CHAIN_OFFSET = 0x40000


def pad(b, n):
    return b + b'\0' * (-len(b) % n)


def decompress_lz4_legacy(data):
    if not HAS_LZ4:
        raise RuntimeError("lz4 module not found for LZ4 legacy decompression")
    magic = data[:4]
    if magic != b'\x02\x21\x4c\x18':
        raise ValueError(f"Invalid LZ4 legacy magic: {magic.hex()}")
    pos = 4
    blocks = []
    while pos < len(data):
        if pos + 4 > len(data):
            break
        bsize = struct.unpack_from('<I', data, pos)[0]
        pos += 4
        if bsize == 0 or pos + bsize > len(data):
            break
        bdata = data[pos:pos + bsize]
        pos += bsize
        # Legacy blocks are up to 8 MB uncompressed
        decomp = lz4.block.decompress(bdata, uncompressed_size=8 * 1024 * 1024)
        blocks.append(decomp)
    return b''.join(blocks)


def compress_lz4_legacy(data):
    if not HAS_LZ4:
        raise RuntimeError("lz4 module not found for LZ4 legacy compression")
    magic = b'\x02\x21\x4c\x18'
    chunk_size = 8 * 1024 * 1024
    blocks = [magic]
    for i in range(0, len(data), chunk_size):
        chunk = data[i:i + chunk_size]
        compressed = lz4.block.compress(chunk, store_size=False, mode='high_compression', compression=12)
        blocks.append(struct.pack('<I', len(compressed)))
        blocks.append(compressed)
    return b''.join(blocks)


def decompress_kernel(kernel_bytes):
    if kernel_bytes[:2] == b'\x1f\x8b':
        print("[chainboot] Decompressing gzip kernel...")
        return gzip.decompress(kernel_bytes)
    elif kernel_bytes[:4] == b'\x02\x21\x4c\x18':
        print("[chainboot] Decompressing LZ4 legacy kernel...")
        return decompress_lz4_legacy(kernel_bytes)
    elif len(kernel_bytes) > 0x40 and kernel_bytes[0x38:0x3c] == b'ARM\x64':
        print("[chainboot] Kernel is uncompressed ARM64 Image")
        return kernel_bytes
    else:
        raise ValueError("Unknown kernel compression format")


def main():
    if len(sys.argv) < 4:
        print(f"Usage: {sys.argv[0]} <android-boot.img> <program.bin> <out.img> [payload.bin]")
        sys.exit(1)

    src, prog_path, out = sys.argv[1:4]
    payload = open(sys.argv[4], 'rb').read() if len(sys.argv) > 4 else b''
    d = open(src, 'rb').read()
    assert d[:8] == b'ANDROID!', 'not an Android boot image'

    ksize, _, rsize, _, ssize, _, _, page, hver = struct.unpack_from('<9I', d, 8)
    print(f"[chainboot] Detected Boot Image Header v{hver}, ksize={ksize}")

    if hver == 2:
        rdo_size = struct.unpack_from('<I', d, 1632)[0]
        dtb_size = struct.unpack_from('<I', d, 1648)[0]

        def pages(n):
            return (n + page - 1) // page * page

        off = page
        kernel = d[off:off + ksize]; off += pages(ksize)
        ramdisk = d[off:off + rsize]; off += pages(rsize)
        second = d[off:off + ssize]; off += pages(ssize)
        rdo = d[off:off + rdo_size]; off += pages(rdo_size)
        dtb = d[off:off + dtb_size]
    elif hver == 4:
        page = 4096
        def pages(n):
            return (n + page - 1) // page * page

        off = page
        kernel = d[off:off + ksize]; off += pages(ksize)
        ramdisk = d[off:off + rsize] if rsize else b''; off += pages(rsize)
        sig_size = struct.unpack_from('<I', d, 1580)[0]
        # In v4 signature follows ramdisk
        signature = d[off:off + sig_size] if sig_size else b''
    else:
        raise ValueError(f"Unsupported header version {hver}")

    image = decompress_kernel(kernel)
    assert image[0x38:0x3c] == b'ARM\x64', 'Extracted kernel is not an arm64 Image'
    linux_image_size = struct.unpack_from('<Q', image, 0x10)[0]
    print(f"[chainboot] Linux Image decompressed: {len(image)} bytes (header image_size: {linux_image_size})")

    prog = bytearray(open(prog_path, 'rb').read())
    assert prog[0x38:0x3c] == b'ARM\x64', 'program has no arm64 header'
    assert len(prog) <= CHAIN_OFFSET, f'program too large ({len(prog)} > {CHAIN_OFFSET})'

    payload_off = CHAIN_OFFSET + len(pad(image, 16)) if payload else 0
    total = max(CHAIN_OFFSET + linux_image_size, payload_off + len(payload))
    struct.pack_into('<Q', prog, 0x10, (total + 0xfffff) & ~0xfffff)
    struct.pack_into('<Q', prog, 0x28, len(image))
    struct.pack_into('<Q', prog, 0x30, payload_off)

    blob = bytes(prog) + b'\0' * (CHAIN_OFFSET - len(prog)) + image
    if payload:
        blob = pad(blob, 16) + payload
    print(f"[chainboot] Combined blob: {len(blob)} bytes (program={len(prog)}, image={len(image)})")

    # Compress combined blob using LZ4 legacy (matching MediaTek LK decompression)
    if HAS_LZ4:
        print("[chainboot] Compressing new kernel using LZ4 legacy...")
        new_kernel = compress_lz4_legacy(blob)
    else:
        print("[chainboot] Compressing new kernel using gzip...")
        new_kernel = gzip.compress(blob, compresslevel=6)
    print(f"[chainboot] Compressed new kernel: {len(new_kernel)} bytes")

    if hver == 2:
        hdr = bytearray(d[:page])
        struct.pack_into('<I', hdr, 8, len(new_kernel))
        out_data = bytes(hdr) + pad(new_kernel, page) + pad(ramdisk, page) + pad(second, page) + pad(rdo, page) + pad(dtb, page)
    elif hver == 4:
        PARTITION_SIZE = 134217728  # 128 MB
        out_buf = bytearray(b'\x00' * PARTITION_SIZE)

        hdr = bytearray(d[:page])
        struct.pack_into('<I', hdr, 8, len(new_kernel))
        # Clear signature size in header (unlocked bootloader)
        struct.pack_into('<I', hdr, 1580, 0)
        out_buf[:page] = hdr

        # Kernel at 4096
        k_end = page + len(new_kernel)
        out_buf[page:k_end] = new_kernel

        # Extract genuine stock Xiaomi VBMeta and AVB footer
        stock_footer = d[-64:]
        magic, vmaj, vmin, orig_size, vbmeta_off, vbmeta_sz = struct.unpack('>4sIIQQQ', stock_footer[:36])
        if magic == b'AVBf':
            stock_vbmeta = d[vbmeta_off:vbmeta_off + vbmeta_sz]
            assert stock_vbmeta[:4] == b'AVB0', f"Invalid stock vbmeta at {vbmeta_off}"

            # Relocate VBMeta right after new_kernel aligned to page
            new_vbmeta_off = (k_end + page - 1) // page * page
            out_buf[new_vbmeta_off:new_vbmeta_off + vbmeta_sz] = stock_vbmeta
            print(f"[chainboot] Preserving genuine Xiaomi VBMeta ({vbmeta_sz} bytes) at offset {new_vbmeta_off} ({hex(new_vbmeta_off)})")

            # Update AVB footer to point to relocated VBMeta
            new_footer = bytearray(stock_footer)
            struct.pack_into('>4sIIQQQ', new_footer, 0, b'AVBf', vmaj, vmin, new_vbmeta_off, new_vbmeta_off, vbmeta_sz)
            out_buf[-64:] = new_footer
            print(f"[chainboot] Preserving genuine Xiaomi AVB footer at offset {PARTITION_SIZE - 64}")
        else:
            print("[chainboot] WARNING: No AVB footer found in source boot image")

        out_data = bytes(out_buf)

    with open(out, 'wb') as f:
        f.write(out_data)

    print(f"[chainboot] Wrote {len(out_data)} bytes to {out}")

    avbtool = '/home/aditya/crDroid/external/avb/avbtool.py'
    if os.path.exists(avbtool):
        cmd = [sys.executable, avbtool, 'info_image', '--image', out]
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode == 0:
            print("[chainboot] Verified AVB layout with avbtool:\n" + res.stdout.strip())
        else:
            print(f"[chainboot] WARNING: avbtool info_image failed: {res.stderr}")


if __name__ == '__main__':
    main()

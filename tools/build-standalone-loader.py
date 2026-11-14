#!/usr/bin/env python3
import struct
import lz4.block

CHAIN_OFFSET = 0x8000
PARTITION_SIZE = 134217728 # 128 MB

def compress_lz4_legacy(data):
    magic = b'\x02\x21\x4c\x18'
    chunk_size = 8 * 1024 * 1024
    blocks = [magic]
    for i in range(0, len(data), chunk_size):
        chunk = data[i:i + chunk_size]
        compressed = lz4.block.compress(chunk, store_size=False, mode='high_compression', compression=12)
        blocks.append(struct.pack('<I', len(compressed)))
        blocks.append(compressed)
    return b''.join(blocks)

def main():
    stock_path = '/home/aditya/beryl/stock_boot_a.img'
    prog_path = '/home/aditya/beryl/mtkloader/mtkloader.bin'
    out_path = '/home/aditya/beryl/mtkloader/mtkloader_standalone.img'

    with open(stock_path, 'rb') as f:
        stock = f.read()

    # Extract stock VBMeta and footer
    vbmeta_offset = 19795968
    vbmeta_size = 1664
    stock_vbmeta = stock[vbmeta_offset:vbmeta_offset + vbmeta_size]
    stock_footer = stock[-64:]

    assert stock_vbmeta[:4] == b'AVB0', 'Invalid stock vbmeta'
    assert stock_footer[:4] == b'AVBf', 'Invalid stock footer'

    # Read mtkloader.bin
    prog = bytearray(open(prog_path, 'rb').read())
    assert prog[0x38:0x3c] == b'ARM\x64', 'program has no arm64 header'

    # Compress mtkloader with LZ4 legacy level 12
    compressed_kernel = compress_lz4_legacy(bytes(prog))
    print(f'[builder] mtkloader.bin: {len(prog)} bytes -> compressed: {len(compressed_kernel)} bytes')

    # Build Android boot image header v4 (matching stock)
    hdr = bytearray(stock[:4096])
    # Update kernel size
    struct.pack_into('<I', hdr, 8, len(compressed_kernel))
    # Ramdisk size = 0
    struct.pack_into('<I', hdr, 12, 0)
    # Header size = 1584
    struct.pack_into('<I', hdr, 20, 1584)
    # Signature size = 0
    struct.pack_into('<I', hdr, 1580, 0)

    # Assemble 128 MB partition
    out = bytearray(b'\x00' * PARTITION_SIZE)
    # Header at 0
    out[:4096] = hdr
    # Kernel at 4096
    out[4096:4096 + len(compressed_kernel)] = compressed_kernel
    # Stock VBMeta at 19795968
    out[vbmeta_offset:vbmeta_offset + vbmeta_size] = stock_vbmeta
    # Stock footer at end of partition
    out[-64:] = stock_footer

    with open(out_path, 'wb') as f:
        f.write(out)

    print(f'[builder] Successfully wrote {len(out)} bytes to {out_path}')
    print(f'[builder] VBMeta at offset {vbmeta_offset} ({hex(vbmeta_offset)})')
    print(f'[builder] AVB footer at offset {PARTITION_SIZE - 64} ({hex(PARTITION_SIZE - 64)})')

if __name__ == '__main__':
    main()

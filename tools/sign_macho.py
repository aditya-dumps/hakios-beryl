#!/usr/bin/env python3
"""
tools/sign_macho.py: Ad-hoc code signing utility for Mach-O binaries/dylibs.
Generates genuine Apple-compliant LC_CODE_SIGNATURE with CS_CodeDirectory,
SHA-256 page hashes, and CS_ADHOC (0x2) flags.
"""
import sys
import struct
import hashlib
import os

def sign_macho(path, ident=None):
    if not os.path.isfile(path):
        print(f"[-] Error: file not found: {path}")
        return False
        
    if ident is None:
        ident = os.path.basename(path).replace(".dylib", "")
        
    with open(path, "rb") as f:
        data = bytearray(f.read())
        
    if len(data) < 32:
        print(f"[-] Error: file too small: {path}")
        return False
        
    magic, cputype, cpusubtype, filetype, ncmds, sizeofcmds, flags, reserved = struct.unpack_from("<IIIIIIII", data, 0)
    if magic != 0xfeedfacf:
        print(f"[-] Error: not a 64-bit Mach-O file: {path} (magic 0x{magic:x})")
        return False
        
    # Check if LC_CODE_SIGNATURE already exists; if so, update page hashes
    offset = 32
    for _ in range(ncmds):
        cmd, cmdsize = struct.unpack_from("<II", data, offset)
        if cmd == 0x1d:
            dataoff, datasize = struct.unpack_from("<II", data, offset + 8)
            sb_magic, sb_len, count = struct.unpack_from(">III", data, dataoff)
            cd_offset = None
            for i in range(count):
                stype, soff = struct.unpack_from(">II", data, dataoff + 12 + i*8)
                if stype == 0: # CSSLOT_CODEDIRECTORY
                    cd_offset = dataoff + soff
                    break
            if cd_offset is None:
                print(f"[-] Error: CSSLOT_CODEDIRECTORY not found in {path}")
                return False
                
            hash_offset, = struct.unpack_from(">I", data, cd_offset + 16)
            page_sz_byte, = struct.unpack_from("B", data, cd_offset + 39)
            page_size = 1 << page_sz_byte if page_sz_byte != 0 else 4096
            code_limit, = struct.unpack_from(">I", data, cd_offset + 32)
            nCodeSlots = (code_limit + page_size - 1) // page_size
            
            hashes = bytearray()
            for i in range(nCodeSlots):
                start = i * page_size
                end = min(start + page_size, code_limit)
                chunk = data[start:end]
                if len(chunk) < page_size:
                    chunk = chunk + b"\x00" * (page_size - len(chunk))
                hashes += hashlib.sha256(chunk).digest()
                
            struct.pack_into(">I", data, cd_offset + 28, nCodeSlots)
            data[cd_offset + hash_offset : cd_offset + hash_offset + len(hashes)] = hashes
            with open(path, "wb") as f:
                f.write(data)
            print(f"[+] {path}: successfully updated SHA-256 page hashes in existing LC_CODE_SIGNATURE ({nCodeSlots} slots, cd_offset=0x{cd_offset:x})")
            return True
        offset += cmdsize
        
    pad = (16 - (len(data) % 16)) % 16
    data += b"\x00" * pad
    dataoff = len(data)
    
    page_size = 4096
    nCodeSlots = (dataoff + page_size - 1) // page_size
    
    ident_b = ident.encode() + b"\x00"
    while len(ident_b) % 4 != 0:
        ident_b += b"\x00"
        
    cd_header_fmt = ">IIIIIIIIIBBBBIIIIQQQQ"
    cd_header_size = struct.calcsize(cd_header_fmt)
    assert cd_header_size == 88
    ident_offset = cd_header_size
    hash_offset = ident_offset + len(ident_b)
    cd_length = hash_offset + nCodeSlots * 32
    
    sb_header_fmt = ">III"
    sb_blob_fmt = ">II"
    sb_header_size = struct.calcsize(sb_header_fmt)
    blob_entry_size = struct.calcsize(sb_blob_fmt)
    sb_length = sb_header_size + blob_entry_size + cd_length
    datasize = sb_length
    
    # Update load commands and Mach-O header first so page 0 is finalized before hashing!
    lc_sig = struct.pack("<IIII", 0x1d, 16, dataoff, datasize)
    cmds_end = 32 + sizeofcmds
    data[cmds_end : cmds_end + 16] = lc_sig
    struct.pack_into("<II", data, 16, ncmds + 1, sizeofcmds + 16)
    
    offset = 32
    for _ in range(ncmds):
        cmd, cmdsize = struct.unpack_from("<II", data, offset)
        if cmd == 0x19:
            segname = data[offset+8:offset+24].split(b"\x00")[0].decode()
            if segname == "__LINKEDIT":
                vmaddr, vmsize, fileoff, filesize = struct.unpack_from("<QQQQ", data, offset+24)
                new_filesize = dataoff + datasize - fileoff
                new_vmsize = (new_filesize + 4095) & ~4095
                struct.pack_into("<Q", data, offset+32, new_vmsize)
                struct.pack_into("<Q", data, offset+48, new_filesize)
                print(f"[*] {ident}: updated __LINKEDIT vmsize=0x{new_vmsize:x}, fileoff=0x{fileoff:x}, filesize=0x{new_filesize:x}")
        offset += cmdsize

    # Now compute accurate SHA-256 page hashes over finalized data 0..dataoff
    hashes = bytearray()
    for i in range(nCodeSlots):
        start = i * page_size
        end = min(start + page_size, dataoff)
        chunk = data[start:end]
        if len(chunk) < page_size:
            chunk = chunk + b"\x00" * (page_size - len(chunk))
        hashes += hashlib.sha256(chunk).digest()
        
    cd = struct.pack(cd_header_fmt,
        0xfade0c02,      # magic (CSMAGIC_CODEDIRECTORY)
        cd_length,       # length
        0x20400,         # version (2.4.0)
        0x2,             # flags (CS_ADHOC)
        hash_offset,     # hashOffset
        ident_offset,    # identOffset
        0,               # nSpecialSlots
        nCodeSlots,      # nCodeSlots
        dataoff,         # codeLimit
        32,              # hashSize (SHA-256)
        2,               # hashType (CS_HASHTYPE_SHA256)
        2,               # platform (iOS)
        12,              # pageSize (2^12 = 4096)
        0,               # spare2
        0,               # scatterOffset
        0,               # teamOffset
        0,               # spare3
        0,               # codeLimit64
        0,               # execSegBase
        0,               # execSegLimit
        0                # execSegFlags
    ) + ident_b + hashes
    
    sb = struct.pack(sb_header_fmt,
        0xfade0cc0,      # magic CSMAGIC_EMBEDDED_SIGNATURE
        sb_length,       # length
        1,               # count (1 blob)
    ) + struct.pack(sb_blob_fmt,
        0,               # type CSSLOT_CODEDIRECTORY
        sb_header_size + blob_entry_size, # offset to CodeDirectory
    ) + cd
    
    data += sb
        
    with open(path, "wb") as f:
        f.write(data)
    print(f"[+] Successfully signed {path} with ad-hoc signature ({len(data)} bytes, superblob at 0x{dataoff:x})")
    return True

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <file.dylib / binary> [ident]")
        sys.exit(1)
    ident = sys.argv[2] if len(sys.argv) > 2 else None
    ok = sign_macho(sys.argv[1], ident)
    sys.exit(0 if ok else 1)

#!/bin/bash
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"

CLANG="/home/aditya/crDroid/prebuilts/clang/host/linux-x86/clang-r547379/bin/clang"
LLD="/home/aditya/crDroid/prebuilts/clang/host/linux-x86/clang-r547379/bin/ld.lld"
CFLAGS="--target=aarch64-linux-gnu -ffreestanding -nostdlib -fno-builtin -mgeneral-regs-only -mstrict-align -O2 -Wall -Wextra"

echo "== Compiling fbdiag =="
"$CLANG" $CFLAGS -c "$HERE/fbdiag_start.S" -o "$HERE/fbdiag_start.o"
"$CLANG" $CFLAGS -c "$HERE/fbdiag.c" -o "$HERE/fbdiag.o"
"$LLD" -T "$HERE/link.ld" --oformat binary "$HERE/fbdiag_start.o" "$HERE/fbdiag.o" -o "$HERE/fbdiag.bin"

echo "fbdiag.bin built: $(wc -c < "$HERE/fbdiag.bin") bytes"

BOOT=${ANDROID_BOOT:-$ROOT/stock_boot_a.img}
echo "== Chaining fbdiag with $BOOT =="
python3 "$ROOT/tools/chainboot.py" "$BOOT" "$HERE/fbdiag.bin" "$HERE/fbdiag.img"
echo "== fbdiag.img ready: $(ls -lh "$HERE/fbdiag.img") =="

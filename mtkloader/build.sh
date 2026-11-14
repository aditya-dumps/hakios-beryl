#!/bin/bash
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"

CLANG="/home/aditya/crDroid/prebuilts/clang/host/linux-x86/clang-r547379/bin/clang"
LLD="/home/aditya/crDroid/prebuilts/clang/host/linux-x86/clang-r547379/bin/ld.lld"
CFLAGS="--target=aarch64-linux-gnu -ffreestanding -nostdlib -fno-builtin -mgeneral-regs-only -mstrict-align -O2 -Wall -Wextra"

echo "== Compiling mtkloader for beryl (MT6855) =="
"$CLANG" $CFLAGS "$@" -c "$HERE/start.S" -o "$HERE/start.o"
"$CLANG" $CFLAGS "$@" -c "$HERE/mtkloader.c" -o "$HERE/mtkloader.o"
"$LLD" -T "$HERE/link.ld" --oformat binary "$HERE/start.o" "$HERE/mtkloader.o" -o "$HERE/mtkloader.bin"

echo "mtkloader.bin built: $(wc -c < "$HERE/mtkloader.bin") bytes"

BOOT=${ANDROID_BOOT:-$ROOT/stock_boot_a.img}
if [ -f "$BOOT" ]; then
    echo "== Chaining mtkloader with $BOOT =="
    python3 "$ROOT/tools/chainboot.py" "$BOOT" "$HERE/mtkloader.bin" "$HERE/mtkloader.img"
    if [ -f "$HERE/payload.bin" ]; then
        echo "== Chaining mtkloader with payload.bin =="
        python3 "$ROOT/tools/chainboot.py" "$BOOT" "$HERE/mtkloader.bin" "$HERE/mtkloader_xnu.img" "$HERE/payload.bin"
    fi
    echo "== mtkloader.img ready =="
fi

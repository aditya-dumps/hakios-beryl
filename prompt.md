Bring up a MediaTek phone on HakiOS — agent prompt

Copy this file, fill the marked fields, and hand it to an agent that has never seen this
project. Everything the agent needs is named here; it should not have to guess.
0. Fill these in before handing this over
field	value
phone model / codename	Redmi Note 14 5G (beryl)
SoC	MT6855
SoC generation	Dimensity 7025 Ultra
RAM	8 GB LPDDR4X
storage	256 GB UFS 2.2 (Samsung KM8F9001JM-B813)
GPU	Imagination PowerVR BXM-8-256 (Rogue RGX)
bootloader unlocked?	yes
root available on Android?	yes
adb serial	$HAKIOS_SERIAL
1. What you are doing

You are bringing Apple's open XNU kernel (xnu-8796.121.2) and an unmodified iOS 16.5 user
space onto a MediaTek phone, the way Android is Linux on phones: **your own boot loader in
front of Android's kernel, your own drivers, your own configuration**. You are not writing a
ROM, and you are not replacing Android — Android boots normally, your loader is asked for one
XNU boot, XNU runs for a while, and the phone comes back to Android.

The MediaTek port of this project already exists and works on one phone (MT6768). **You are
porting its shape to a different SoC.** The shape transfers; the numbers do not. Every address,
register, core index and clock you use must come out of your phone's own device tree.

There is no Kconfig. CONFIG_HAKIOS_<NAME>=y compiles a driver into the kernel; every other
CONFIG_* symbol becomes a kernel boot-argument. One .config produces both. The boot
command line has a hard limit of 607 characters.
2. References (public, clone them)

# the common tree: kernel port, drivers, loader, tools, docs. Branch "mtk" is the MediaTek side.
git clone --branch mtk https://github.com/oosexgang/hakios-xnu-kernel.git hakios
# the one working MediaTek device port (Infinix Hot 20, MT6768): loader, run scripts, drivers
git clone https://github.com/oosexgang/hakios-mt6768.git hakios-mt6768
# the UEFI/boot-firmware repo (Qualcomm today; read it for the loader contract, not for MTK)
git clone https://github.com/oosexgang/hakios-uefi.git hakios-uefi
# the Metal driver (Mali support lives here)
git clone https://github.com/oosexgang/hakios-metal.git hakios-metal

Read, in this order, before writing code:

    1.
    hakios-mt6768/AGENTS.md — the rules of the MediaTek port (safety, naming, licences).
    2.
    hakios-mt6768/docs/porting/ and hakios/docs/porting/index.md — the order the work happens in.
    3.
    hakios/mtk/README.md — what every MediaTek driver is, which boot-argument turns it on, and

what the common tree provides for MTK (there is no Qualcomm assumption anywhere in it).

    4.
    hakios/mtk/loader/ — the bare-metal loader: mtkloader.c, start.S, build.sh,

build_flashed.py. This is the piece you fork first.

    5.
    hakios/mtk/tools/xnu-cycle.sh — one full run: build, flash boot_a, run, read the log back.

MediaTek's own GPL sources are for reading register layouts and hardware order (name them, never
copy the code). For the SoC you have, find the matching kernel source; the MT6768 one is
https://github.com/LineageOS/android_kernel_xiaomi_mt6768, and MT6893 examples are
https://github.com/xiaomi-mt6893-dev/kernel_xiaomi_mt6893 and
https://github.com/OnePlusOSS/android_kernel_oneplus_mt6893. Upstream Linux is for the GIC and
the UFS host driver: https://github.com/torvalds/linux (`drivers/irqchip/irq-gic-v3.c`,
`drivers/ufs/host/ufs-mediatek.c`).

Tooling you will need, all public:
what	where
device tree compiler (decompile the phone's own dtb)	https://github.com/dgibson/dtc
boot image unpack/repack	https://github.com/cofface/android_bootimg, https://github.com/LineageOS/android_system_tools_mkbootimg
U-Boot (read the MediaTek boot flow; you do not have to build it)	https://github.com/u-boot/u-boot
JTAG/debug, if you ever need it	https://github.com/openocd/openocd

Host tools: clang + ld.lld, adb, fastboot, python3, git.
3. The shape of a MediaTek boot

MediaTek phones have no UEFI. The chain is:

BROM -> preloader -> LK (MediaTek's boot loader) -> Android's kernel, in boot_a

Your loader is chained in front of Android's kernel inside boot_a. It runs with the MMU
off, brings up what XNU cannot (touch firmware, clocks, panel), builds XNU's device tree and
boot-arguments, starts the kernel, and after XNU_SECS the watchdog hands the phone back to
Android. The log comes back from pstore: /sys/fs/pstore/console-ramoops-0.

Android asks for the XNU boot with a marker in its pmsg zone (`DARWIN-<CODENAME>:BOOT-XNU` in
the MT6768 case; find your own phone's format by dumping the zone).
4. Do the work in this order

Each step ends with evidence in the log. Do not start step N+1 until step N's evidence is in
the log you read back.

Step 0 — facts. Read your phone's own device tree and write down what it says, before any
code:

adb shell su -c 'cp /sys/firmware/fdt /data/local/tmp/fdt.dtb'   # one root command per adb call
adb shell su -c 'chmod 644 /data/local/tmp/fdt.dtb'
adb pull /data/local/tmp/fdt.dtb
dtc -I dtb -O dts fdt.dtb > fdt.dts

Never put && or ; inside one quoted su -c string: everything after the first command
silently loses root. The tree is the phone's; quote its numbers and names, never commit it.

Record at least: SoC model and compatible; DRAM base and size; #address-cells /
#size-cells at the root; the CPU nodes with their enable-method and clock frequencies; the
GIC node (`arm,gic-v2` vs arm,gic-v3, and both register windows); PSCI; the storage node
(`msdc` for eMMC, ufshci for UFS) and its base; the display pipeline (disp, OVL layers, DSI,
panel name and resolution); the console UART; the watchdog; the touch controller (node name,
bus, chip id); SCP and CONNSYS if present.

Step 1 — a loader that chains. Fork hakios/mtk/loader/ and hakios-mt6768/mtkloader/
into your own device repository. Replace every platform constant with your phone's: the DRAM
window for XNU, the core order (MPIDR-based: the prime core first, then the big cores, then
the little ones — the tree's numbering is not sequential and may skip numbers), the GIC
distributor and CPU window (v3 has a different layout and a different EOImode from v2), the
panel and its framebuffer address and pitch, the RAM disk, the ramoops console and pmsg
addresses (read them from `/proc/iomem`), the boot partition size, the UART.

Build it and chain it. The reference does this with mtkloader/build.sh and
mtkloader/build_flashed.py; the chain into boot_a is mtk/tools/chainboot.py.

Step 2 — XNU boots with nothing of the phone's. XNU's own kernel, its device tree, its
console, launchd as PID 1, the phone back to Android afterwards. Prove it from the log: the
kernel's version line, launchd starting, the run ending by itself.

Step 3 — the phone's own hardware, one piece at a time. Each piece behind its own boot
argument, each step read-only first, each step's result printed in the log. The reference order
is: buttons and touch, CPU frequency, GPU, then storage, Wi-Fi, audio, sensors. Keep the
reference's driver names and step numbers where the hardware is the same; write a new driver
where it is not.

Step 4 — write it down. device.conf in your device repository is the record: works,
partial or missing per area, each with how it was turned on. Only what you have seen on
the phone is works.
5. Rules that are not negotiable

    Flash only boot_a. Never slot B, never any other partition. xnusys is written only

by tools/system-flash.sh.

    Always pass the serial (`adb -s`, `fastboot -s`); a second phone may be connected.
    Keep the user's stock boot_a image; it is how the phone is restored.
    One run at a time, 200–600 s, and never two flashing commands at once.
    Never change the device's SELinux mode, never mount a read-only partition rw, never delete or

format a partition.

    Never raise CPU or GPU voltages.
    The storage driver stays read-only by construction unless the owner asks otherwise.
    No iOS binary, image, cache, shader library, font or screenshot in the tree. Describe what the

screen showed in words.

    No vendor firmware, partition image or device tree in the tree; pull-firmware.sh fetches the

firmware into fw-*/, which git ignores.

    No personal data: no serials in the tree (scripts read `HAKIOS_SERIAL`), no home paths, no

tokens, no Wi-Fi names.

    Licences: kernel/ is APSL 2.0, everything else MIT. MediaTek's and Linux's GPL sources may be

read and named, never copied.

    New code uses hakios___, kern.hakios.__, /dev/hakios-*. Files copied from the reference

keep the former redwood_* prefix until they are merged; do not rename them piecemeally.

    Do not put the phone's current ROM name, its brand strings, or any getprop property into

the documents or the code: they are spoofed and change between flashes. Use the DT-derived
  identity only.
6. Evidence rules

    Every claim about the phone comes from the phone or from its device tree — never from the

reference port's addresses and never from documentation written for a different SoC.

    Nothing is "works" until a run on the phone shows it.
    When a run fails, the log is the evidence: read it, quote the line, then fix the cause. A

hypothesis is labelled a hypothesis.
7. What to hand back at the end

    the device repository (loader, drivers, device.conf, configs/, `docs/`), a git repository

of its own;

    docs/<codename>-facts.md: what the phone's own device tree says, each number with where it

came from;

    docs/<codename>-plan.md: the order the hardware is brought up in and what each step needs;
    the log of the last run, and device.conf saying what that run proved.

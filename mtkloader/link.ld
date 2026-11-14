ENTRY(_start)

SECTIONS
{
    . = 0x40000000;

    .text : {
        *(.text.boot)
        *(.text .text.*)
    }

    .rodata : {
        *(.rodata .rodata.*)
    }

    .data : {
        *(.data .data.*)
    }

    .bss : {
        __bss_start = .;
        *(.bss .bss.*)
        *(COMMON)
        __bss_end = .;
        . = ALIGN(16);
        . += 0x8000; /* 32 KB main stack in DRAM */
        __stack_top = .;
        . += 0x4000; /* 16 KB fault stack in DRAM */
        __fault_stack_top = .;
        . += 0x4000; /* 16 KB watcher stack in DRAM */
        __watcher_stack_top = .;
    }

    . = ALIGN(16);
    __loader_end = .;
}

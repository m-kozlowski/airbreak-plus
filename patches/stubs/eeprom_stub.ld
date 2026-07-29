/*
 * Linker script for EEPROM tool CDX stub
 *
 * Layout:
 *   +0x000  .sid_tag      Product ID string (bootloader reads via G S #SID)
 *   +0x200  .isr_vector   NVIC vector table / cdx_entry
 *                         [0]=SP, [1]=entry from here
 *   +0x2xx  .text         Code + rodata
 */

MEMORY
{
    FLASH (rx)  : ORIGIN = STUB_FLASH_ORIGIN, LENGTH = 768K
    RAM   (rwx) : ORIGIN = 0x20000000,        LENGTH = 128K
}

_estack = ORIGIN(RAM) + LENGTH(RAM);

ENTRY(Reset_Handler)

SECTIONS
{
    .sid_tag :
    {
        KEEP(*(.sid_tag))
        . = 0x200;
    } > FLASH

    .isr_vector :
    {
        . = ALIGN(4);
        KEEP(*(.isr_vector))
        . = ALIGN(4);
    } > FLASH

    .text :
    {
        . = ALIGN(4);
        *(.text)
        *(.text*)
        *(.rodata)
        *(.rodata*)
        . = ALIGN(4);
    } > FLASH

    _sidata = LOADADDR(.data);

    .data :
    {
        . = ALIGN(4);
        _sdata = .;
        *(.data)
        *(.data*)
        . = ALIGN(4);
        _edata = .;
    } > RAM AT> FLASH

    .bss :
    {
        . = ALIGN(4);
        _sbss = .;
        *(.bss)
        *(.bss*)
        *(COMMON)
        . = ALIGN(4);
        _ebss = .;
    } > RAM

    /DISCARD/ :
    {
        *(.ARM.attributes)
        *(.ARM.exidx*)
        *(.comment)
        *(.note*)
    }
}

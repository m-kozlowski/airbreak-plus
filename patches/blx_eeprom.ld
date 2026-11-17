ENTRY(eeprom_service)
MEMORY {
  MODULE (rwx) : ORIGIN = 0x20010000, LENGTH = 32K
  BUFFER (rw) : ORIGIN = 0x20018000, LENGTH = 32K
}
SECTIONS {
  .text : { blx_eeprom_start = .; KEEP(*(.entry)) *(.text*) *(.rodata*) } > MODULE
  .data : { *(.data*) *(.bss*) *(COMMON) } > MODULE
  ASSERT(SIZEOF(.data) == 0, "EEPROM module must not require initialized data or BSS")
  .buffer (NOLOAD) : { blx_transfer_buffer = .; . += LENGTH(BUFFER); } > BUFFER
  /DISCARD/ : { *(.ARM.exidx*) *(.comment*) *(.note*) }
}
blx_eeprom_size = SIZEOF(.text);

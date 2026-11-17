.syntax unified
.thumb
.section .rodata.blx_dump_abi, "a", %progbits
.balign 2
.global blx_eeprom_crc
.type blx_eeprom_crc, %object
blx_eeprom_crc: .short 0xffff
.size blx_eeprom_crc, .-blx_eeprom_crc

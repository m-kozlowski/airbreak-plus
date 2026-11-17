#include "blx_service.h"

/* This payload occupies the small BLX cave after the BID tag. */
void blx_dump_reply(u8 *p, u32 length, u32 uart, const volatile u8 *source) {
  if (p[0] == 'E') {
    length = 0;
    write_le16(p + 5, 0);
  }
  for (u32 i = 0; i < length; i++)
    p[7 + i] = source[i];
  service_send(p, 7 + length, uart);
}

u16 blx_dump_module_crc(u32 size) {
  __asm volatile ("dsb; isb" ::: "memory");
  return boot_crc16((const void *)blx_eeprom_start, size);
}

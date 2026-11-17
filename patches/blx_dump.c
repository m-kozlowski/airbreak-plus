#include "blx_service.h"

/* The shared payload linker resolves these in blx_dump_tail, across the BID
 * tag. Both payloads are copied to SRAM by native BLX startup. */
extern void blx_dump_reply(u8 *, u32, u32, const volatile u8 *);
extern u16 blx_dump_module_crc(u32);
extern const volatile u16 blx_eeprom_crc;

void start(void *context, decoded_frame_t *frame, u32 uart, void *state) {
  if (!frame || frame->type != 'O' || frame->payload_len < 7 ||
      (frame->payload[0] != 'D' && frame->payload[0] != 'U' &&
       frame->payload[0] != 'X')) {
    boot_command_dispatch(context, frame, uart, state);
    return;
  }
  u8 *p = frame->payload;
  u32 offset = read_le32(p + 1);
  u32 length = read_le16(p + 5);
  u32 module_size = (u32)blx_eeprom_size;
  volatile u8 *source = 0;
  if (p[0] == 'X') {
    if (blx_dump_module_crc(module_size) == blx_eeprom_crc) {
      eeprom_service(context, frame, uart, state);
      return;
    }
  } else if (length && length <= SERVICE_CHUNK) {
    if (p[0] == 'D' && frame->payload_len == 7 && offset < 0x100000u &&
        length <= 0x100000u - offset) {
      source = (volatile u8 *)(0x08000000u + offset);
    } else if (p[0] == 'U' && frame->payload_len == 7 + length &&
               offset < module_size && length <= module_size - offset) {
      source = blx_eeprom_start + offset;
      for (u32 i = 0; i < length; i++)
        source[i] = p[7 + i];
    }
  }
  p[0] = source ? p[0] + ('a' - 'A') : 'E';
  blx_dump_reply(p, length, uart, source);
}

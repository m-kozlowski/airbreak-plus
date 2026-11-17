#ifndef BLX_SERVICE_H
#define BLX_SERVICE_H

typedef unsigned char u8;
typedef unsigned short u16;
typedef unsigned int u32;

#define SERVICE_CHUNK 240u
#define EEPROM_SIZE 0x40000u
#define EEPROM_PAGE 256u
#define WRITE_BUFFER_SIZE 0x8000u

typedef struct {
  u8 type;
  u8 reserved[3];
  u32 payload_len;
  u8 payload[];
} decoded_frame_t;

/* Imported from the RAM module ELF through the shared payload linker. */
extern volatile u8 blx_eeprom_start[];
extern const u8 blx_eeprom_size[];
extern void eeprom_service(void *, decoded_frame_t *, u32, void *);

extern void boot_command_dispatch(void *, decoded_frame_t *, u32, void *);
extern int frame_build(u8, const void *, u32, void *);
extern void *usart_get(u32);
extern int usart_dma_write(void *, const void *, u32);
extern void *timeout_get_instance(void);
extern void timer_reset(void *);
extern u16 boot_crc16(const void *, u32);
extern u32 get_tick_scaled(void);
extern void boot_watchdog_reload(void);
extern u32 usart_read(void *, void *, u32);
/* Native parser: mirrored 1 KiB ring plus indices and frame state, 0x810 B. */
extern void frame_parser_reset(void *);
extern void frame_parser_append(void *, const void *, u32);
extern int frame_parser_next(void *, decoded_frame_t *);

static inline u32 read_le32(const u8 *p) {
  return (u32)p[0] | ((u32)p[1] << 8) | ((u32)p[2] << 16) | ((u32)p[3] << 24);
}
static inline u16 read_le16(const u8 *p) {
  return (u16)((u16)p[0] | ((u16)p[1] << 8));
}
static inline void write_le16(u8 *p, u16 n) {
  p[0] = n;
  p[1] = n >> 8;
}
static inline void write_le32(u8 *p, u32 n) {
  for (u32 i = 0; i < 4; i++) p[i] = n >> (8 * i);
}

/* Both BLX callers allocate 512 bytes for the decoded frame. The payload can
 * hold the 247-byte reply in place. DMA transmission completes before return. */
static inline __attribute__((always_inline)) void service_send(u8 *p, u32 n, u32 uart) {
  u32 output[129];
  if (frame_build('O', p, n, output))
    usart_dma_write(usart_get(uart), output, output[128]);
  timer_reset((u8 *)timeout_get_instance() + 4);
}
#endif

typedef unsigned char u8;
typedef unsigned short u16;
typedef unsigned int u32;

/* Full O frames carry binary dump requests. All other frames remain stock. */
#define DUMP_FRAME_TYPE 'O'
#define DUMP_REQUEST 'D'
#define DUMP_RESPONSE 'd'
#define DUMP_ERROR 'E'
#define DUMP_CHUNK_MAX 240u
#define FLASH_BASE 0x08000000u
#define FLASH_SIZE 0x00100000u

typedef struct {
  u8 type;
  u8 reserved[3];
  u32 payload_len;
  u8 payload[];
} decoded_frame_t;

extern void boot_command_dispatch(void *context, decoded_frame_t *frame,
                                  u32 uart_id, void *state);
extern int frame_build(u8 type, const void *payload, u32 payload_len,
                       void *output);
extern void *usart_get(u32 uart_id);
extern int usart_dma_write(void *usart, const void *data, u32 length);
extern void *timeout_get_instance(void);
extern void timer_reset(void *timer);

static u32 read_le32(const u8 *p) {
  return (u32)p[0] | ((u32)p[1] << 8) | ((u32)p[2] << 16) | ((u32)p[3] << 24);
}

static u16 read_le16(const u8 *p) {
  return (u16)((u16)p[0] | ((u16)p[1] << 8));
}

static void write_le32(u8 *p, u32 value) {
  p[0] = (u8)value;
  p[1] = (u8)(value >> 8);
  p[2] = (u8)(value >> 16);
  p[3] = (u8)(value >> 24);
}

static void write_le16(u8 *p, u16 value) {
  p[0] = (u8)value;
  p[1] = (u8)(value >> 8);
}

void start(void *context, decoded_frame_t *frame, u32 uart_id, void *state) {
  u8 payload[7 + DUMP_CHUNK_MAX];
  u8 output[0x204];
  u32 offset;
  u16 length;
  u32 i;

  if (frame == 0 || frame->type != DUMP_FRAME_TYPE ||
      frame->payload_len != 7 || frame->payload[0] != DUMP_REQUEST) {
    boot_command_dispatch(context, frame, uart_id, state);
    return;
  }

  offset = read_le32(frame->payload + 1);
  length = read_le16(frame->payload + 5);
  payload[0] = DUMP_ERROR;
  write_le32(payload + 1, offset);
  write_le16(payload + 5, length);

  if (length != 0 && length <= DUMP_CHUNK_MAX &&
      offset < FLASH_SIZE && (u32)length <= FLASH_SIZE - offset) {
    payload[0] = DUMP_RESPONSE;
    for (i = 0; i < length; i++)
      payload[7 + i] = *(const volatile u8 *)(FLASH_BASE + offset + i);
  } else {
    length = 0;
    write_le16(payload + 5, 0);
  }

  if (frame_build(DUMP_FRAME_TYPE, payload, 7u + length, output))
    usart_dma_write(usart_get(uart_id), output, *(u32 *)(output + 0x200));
  timer_reset((u8 *)timeout_get_instance() + 4);
}

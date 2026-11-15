#include "blx_service.h"

/* Ordinary AAPCS entry, called by BLX in SRAM: no startup, vector, clock tree,
 * UART, interrupt or stack replacement. Each request restores the SPI/GPIO
 * configuration it borrowed. PB3/4/5 AF5 = SPI1, PA15 = CS.
 * M95M02-DR (ST DS7024): 256 KiB, 256-byte pages, 5 MHz max, 10 ms max
 * write cycle. W protects the status register, not unprotected array writes
 * (table 6); leave it alone because this module never issues WRSR. */
#define REG(a) (*(volatile u32 *)(a))
#define A 0x40020000u
#define B 0x40020400u
#define AHB1 REG(0x40023830u)
#define APB2 REG(0x40023844u)
#define CR1 REG(0x40013000u)
#define CR2 REG(0x40013004u)
#define SR REG(0x40013008u)
#define DR (*(volatile u8 *)0x4001300cu)
#define CS (1u << 15)
#define BM ((3u << 6) | (3u << 8) | (3u << 10))
#define BF ((15u << 12) | (15u << 16) | (15u << 20))
extern u8 blx_transfer_buffer[];

enum { RANGE = 1, SPI_TIMEOUT, BUSY_TIMEOUT, PROTECTED, WRITE_ENABLE,
       VERIFY, BOOT_STATE, SPI_IN_USE, RECEIVE_TIMEOUT };

typedef struct {
  u32 ahb, apb, cr1, cr2, am, bm, af, speed, pull, type, ao, at, ap;
  u8 error;
} bus_t;

static void replace(u32 address, u32 mask, u32 value) {
  REG(address) = (REG(address) & ~mask) | (value & mask);
}

static void cs_high(void) {
  REG(A + 0x18) = CS;
  /* >=100 ns CS-high interval even at 168 MHz. */
  for (u32 i = 0; i < 32; i++) __asm volatile ("nop");
}

static int wait_spi(bus_t *b, u32 mask, u32 expected) {
  for (u32 i = 0; i < 100000; i++)
    if ((SR & mask) == expected) return 1;
  b->error = SPI_TIMEOUT;
  return 0;
}

static u8 xfer(bus_t *b, u8 data) {
  if (b->error || !wait_spi(b, 2, 2)) return 0;
  DR = data;
  if (!wait_spi(b, 1, 1)) return 0;
  return DR;
}

static void select_chip(bus_t *b, u8 command) {
  REG(A + 0x18) = CS << 16;
  xfer(b, command);
}

static void deselect_chip(bus_t *b) {
  if (!b->error) wait_spi(b, 0x80, 0);
  cs_high();
}

static u8 status(bus_t *b) {
  select_chip(b, 0x05);
  u8 value = xfer(b, 0xff);
  deselect_chip(b);
  return value;
}

static u8 ready(bus_t *b) {
  u32 start = get_tick_scaled();
  /* The iteration limit also bounds a stalled native SysTick. */
  for (u32 i = 0; i < 10000; i++) {
    u8 value = status(b);
    if (b->error || !(value & 1)) return value;
    if ((u32)(get_tick_scaled() - start) >= 100) break;
  }
  b->error = BUSY_TIMEOUT;
  return 0;
}

static void read_data(bus_t *b, u32 offset, u8 *out, u32 n) {
  select_chip(b, 0x03);
  xfer(b, offset >> 16);
  xfer(b, offset >> 8);
  xfer(b, offset);
  for (u32 i = 0; i < n; i++) out[i] = xfer(b, 0xff);
  deselect_chip(b);
}

static void open_bus(bus_t *b) {
  b->error = 0;
  b->ahb = AHB1;
  b->apb = APB2;
  AHB1 |= 3;
  APB2 |= 1u << 12;
  (void)APB2;
  b->cr1 = CR1;
  b->cr2 = CR2;
  /* BLX does not own an active SPI1 transaction. Refuse to steal one. */
  if (b->cr1 & 0x40) {
    b->error = SPI_IN_USE;
    return;
  }
  b->am = REG(A); b->bm = REG(B);
  b->af = REG(B + 0x20); b->speed = REG(B + 8);
  b->pull = REG(B + 0x0c); b->type = REG(B + 4);
  b->ao = REG(A + 0x14); b->at = REG(A + 4); b->ap = REG(A + 0x0c);
  cs_high();
  replace(A + 4, CS, 0);
  replace(A + 0x0c, 3u << 30, 0);
  replace(A, 3u << 30, 1u << 30);
  replace(B + 0x20, BF, (5u << 12) | (5u << 16) | (5u << 20));
  replace(B + 4, 7u << 3, 0);
  replace(B + 8, BM, BM);
  replace(B + 0x0c, BM, 0);
  replace(B, BM, (2u << 6) | (2u << 8) | (2u << 10));
  CR2 = 0;
  /* /64: below 5 MHz even if APB2 runs at 168 MHz. Mode 0, 8 bits. */
  CR1 = (1u << 2) | (5u << 3) | (1u << 8) | (1u << 9) | (1u << 6);
  (void)DR; (void)SR;  /* Clear stale RXNE/OVR before the first command. */
}

static void close_bus(bus_t *b) {
  if (b->error != SPI_IN_USE) {
    cs_high();
    CR1 = 0;
    CR2 = b->cr2;
    CR1 = b->cr1;
    replace(B, BM, b->bm);
    replace(B + 0x20, BF, b->af);
    replace(B + 8, BM, b->speed);
    replace(B + 0x0c, BM, b->pull);
    replace(B + 4, 7u << 3, b->type);
    replace(A, 3u << 30, b->am);
    replace(A + 4, CS, b->at);
    replace(A + 0x0c, 3u << 30, b->ap);
    REG(A + 0x18) = (b->ao & CS) ? CS : CS << 16;
  }
  replace(0x40023844u, 1u << 12, b->apb);
  replace(0x40023830u, 3, b->ahb);
}

static int equal(const u8 *a, const u8 *b, u32 n) {
  for (u32 i = 0; i < n; i++) if (a[i] != b[i]) return 0;
  return 1;
}

static void write_data(bus_t *b, u32 offset, const u8 *data, u8 *actual, u32 n) {
  u8 sr = ready(b);
  if (b->error) return;
  if (sr & 0x0c) { b->error = PROTECTED; return; }
  read_data(b, offset, actual, n);
  if (b->error || equal(data, actual, n)) return;
  select_chip(b, 0x06);  /* WREN */
  deselect_chip(b);
  sr = status(b);
  if (b->error) return;
  if (!(sr & 2)) { b->error = WRITE_ENABLE; return; }
  select_chip(b, 0x02);
  xfer(b, offset >> 16);
  xfer(b, offset >> 8);
  xfer(b, offset);
  for (u32 i = 0; i < n; i++) xfer(b, data[i]);
  deselect_chip(b);
  if (b->error) return;
  ready(b);
  if (b->error) return;
  select_chip(b, 0x04);  /* WRDI, including on devices with an ignored write. */
  deselect_chip(b);
  read_data(b, offset, actual, n);
  if (!b->error && !equal(data, actual, n)) b->error = VERIFY;
}

typedef struct {
  u32 parser[0x810 / 4];
  u8 input[511];
  u32 last;
} receiver_t;

static int receive_frame(receiver_t *rx, decoded_frame_t *frame, u32 uart) {
  if (frame_parser_next(rx->parser, frame)) return 1;
  u32 n = usart_read(usart_get(uart), rx->input, sizeof(rx->input));
  if (!n) return 0;
  frame_parser_append(rx->parser, rx->input, n);
  rx->last = get_tick_scaled();
  return frame_parser_next(rx->parser, frame);
}

static u8 read_range(decoded_frame_t *frame, u32 offset, u32 end,
                     u32 uart, u8 op, u32 window) {
  receiver_t rx;
  frame_parser_reset(rx.parser);
  u8 *p = frame->payload;
  u32 start = offset, acknowledged = offset;
  bus_t bus;
  bus.error = 0;
  if (op == 'R') {
    open_bus(&bus);
    if (!bus.error) ready(&bus);
  }
  while (!bus.error) {
    /* The native main loop cannot service IWDG while this range is running. */
    boot_watchdog_reload();
    if (receive_frame(&rx, frame, uart)) {
      u32 at = read_le32(p + 1);
      if (frame->type != 'O' || frame->payload_len != 7 || p[0] != 'A' ||
          read_le16(p + 5) || at <= acknowledged || at > offset ||
          (at != end && (at - start) % SERVICE_CHUNK)) {
        bus.error = RANGE;
        break;
      }
      acknowledged = at;
    }
    if (acknowledged == end) break;
    /* Cumulative ACKs replenish a sliding window. Poll between frames so a
     * responsive receiver keeps UART running without a window-boundary pause.
     * A stalled receiver may wait indefinitely; IWDG is still serviced. */
    if (offset == end || offset - acknowledged >= window * SERVICE_CHUNK) continue;
    u32 n = end - offset;
    if (n > SERVICE_CHUNK) n = SERVICE_CHUNK;
    if (op == 'R') read_data(&bus, offset, p + 7, n);
    else for (u32 i = 0; i < n; i++) p[7 + i] = *(const u8 *)(0x08000000u + offset + i);
    if (bus.error) break;
    p[0] = op + ('a' - 'A');
    write_le32(p + 1, offset);
    write_le16(p + 5, n);
    service_send(p, 7 + n, uart);
    offset += n;
  }
  if (op == 'R') close_bus(&bus);
  write_le32(p + 1, offset);
  if (bus.error) return bus.error;
  /* All data was consumed before this final reply, including a short tail. */
  p[0] = op + ('a' - 'A');
  write_le16(p + 5, 0);
  service_send(p, 7, uart);
  return 0;
}

static void write_credit(u8 *p, u32 offset, u32 uart) {
  p[0] = 'w';
  write_le32(p + 1, offset);
  write_le16(p + 5, 0);
  service_send(p, 7, uart);
}

/* Use the native CRC/escaping parser. The host may fill the entire staging
 * buffer without an acknowledgement between frames. No EEPROM page is touched
 * until the window is complete. A gap aborts it, after draining its tail. */
static u8 receive_window(decoded_frame_t *frame, u32 offset, u32 end, u32 uart) {
  receiver_t rx;
  u32 next = offset;
  rx.last = get_tick_scaled();
  u8 error = 0;
  frame_parser_reset(rx.parser);
  for (;;) {
    boot_watchdog_reload();
    if (receive_frame(&rx, frame, uart)) {
      u8 *p = frame->payload;
      if (frame->type != 'O' || frame->payload_len < 7 || p[0] != 'W') {
        error = RANGE;
        continue;
      }
      u32 at = read_le32(p + 1), n = read_le16(p + 5);
      if (!n || n > SERVICE_CHUNK || frame->payload_len != 7 + n ||
          at < offset || at >= end || n > end - at) {
        error = RANGE;
        continue;
      }
      if (at != next) error = RANGE;
      if (!error) {
        for (u32 i = 0; i < n; i++) blx_transfer_buffer[at - offset + i] = p[7 + i];
        next += n;
      }
      if (at + n == end) return error;
    }
    if ((u32)(get_tick_scaled() - rx.last) >= 2000) {
      return RECEIVE_TIMEOUT;
    }
  }
}

static u8 write_range(decoded_frame_t *frame, u32 offset, u32 end, u32 uart) {
  bus_t bus;
  u8 actual[EEPROM_PAGE];
  u8 *p = frame->payload;
  open_bus(&bus);
  if (!bus.error && (ready(&bus) & 0x0c)) bus.error = PROTECTED;
  while (!bus.error && offset < end) {
    u32 stop = end - offset > WRITE_BUFFER_SIZE ? offset + WRITE_BUFFER_SIZE : end;
    write_credit(p, offset, uart);
    bus.error = receive_window(frame, offset, stop, uart);
    u32 start = offset;
    while (!bus.error && offset < stop) {
      boot_watchdog_reload();
      u32 n = EEPROM_PAGE - offset % EEPROM_PAGE;
      if (n > stop - offset) n = stop - offset;
      write_data(&bus, offset, blx_transfer_buffer + offset - start, actual, n);
      if (!bus.error) offset += n;
    }
  }
  close_bus(&bus);
  write_le32(p + 1, offset);
  if (bus.error) return bus.error;
  /* Only this final credit establishes that SPI restoration also completed. */
  write_credit(p, end, uart);
  return 0;
}

__attribute__((section(".entry")))
void eeprom_service(void *context, decoded_frame_t *frame, u32 uart, void *state) {
  u8 *p = frame->payload;
  u32 offset = read_le32(p + 1), n = read_le16(p + 5);
  u8 error = RANGE;
  if (frame->payload_len < 8) goto fail;
  u8 op = p[7];
  /* Native bootloader mode byte at +4: 0 is the command/idle state. */
  if (!state || ((u8 *)state)[4] != 0) { error = BOOT_STATE; goto fail; }
  /* Keep BLX available after an interrupted transfer. Native timeout is in
   * ms; 0xffffffff suppresses application startup for about 49 days. The host
   * explicitly resets only after successful verification. */
  *(u32 *)timeout_get_instance() = 0xffffffffu;
  if (op == 'I' && frame->payload_len == 8 && !offset && !n) {
    static const u8 info[] = {'A', 'E', 'E', 'P', 4, 0, 0, 4, 0, 0, 1, 0, 0x80, 0, 0};
    for (u32 i = 0; i < sizeof(info); i++) p[7 + i] = info[i];
    p[0] = 'i'; n = sizeof(info);
  } else if (op == 'R' || op == 'D' || (op == 'W' && !n)) {
    if (frame->payload_len != 12 || (op != 'W' && (!n || n > 128))) goto fail;
    u32 end = read_le32(p + 8);
    if (offset >= end || end > (op == 'D' ? 0x100000u : EEPROM_SIZE)) goto fail;
    error = op == 'W' ? write_range(frame, offset, end, uart) :
                       read_range(frame, offset, end, uart, op, n);
    if (error) goto fail;
    return;
  } else goto fail;
  write_le16(p + 5, n);
  service_send(p, 7 + n, uart);
  return;
fail:
  p[0] = 'e'; p[7] = error;
  write_le16(p + 5, 1);
  service_send(p, 8, uart);
}

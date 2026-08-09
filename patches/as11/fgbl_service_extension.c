/*
 * Late dispatcher and CAN storage service inside the native FGBL SRAM
 * updater image. The stock staged-upgrade path remains unchanged unless the
 * early selector left the service cookie.
 */

typedef unsigned char u8;
typedef unsigned short u16;
typedef unsigned int u32;
typedef void (*nor_chip_select_fn)(int selected);

/* Shared state and objects resolved by fgbl_stubs_<version>.S. */
extern volatile u32 fgbl_service_cookie;
extern volatile u32 fgbl_service_active;
extern u8 sram_flash_writer_singleton;
extern u8 sram_writer_wrapper_singleton;

/* Native SRAM updater entry and periodic status/watchdog service. */
extern void sram_updater_run_staged_upgrade_flow(void *context);
extern u16 sram_updater_crc16_ccitt(const void *data, u32 length);
extern void sram_writer_wrapper_service(void *wrapper);

/* Native SPI-NOR job API retained in the copied SRAM updater. */
extern void *sram_nor_read_job_get(int index);
extern int sram_nor_read_job_submit_and_copy(
    void *job, const void *command, u32 command_length,
    void *destination, u32 read_length, nor_chip_select_fn chip_select);
extern int sram_nor_read_job_transmit(
    void *job, const void *data, u32 length,
    nor_chip_select_fn chip_select);
extern void sram_nor_enable_status_write_protection(void *reader);
extern void sram_nor_set_chip_select(int selected);
extern void sram_nor_set_write_protect(void *unused, int protected_state);
extern void *sram_nor_spi_reader_singleton(void);

/* Native internal-flash writer API retained in the copied SRAM updater. */
extern void *sram_flash_writer_init(void *writer);
extern void sram_flash_writer_queue_overlapping_sectors(
    void *writer, u32 address, u32 length);
extern void sram_flash_writer_unlock(void);
extern void sram_flash_writer_lock(void);
extern int sram_flash_writer_busy(void);
extern void sram_flash_writer_erase_next_sector(void *writer);
extern int sram_flash_writer_erase_queue_done(void *writer);
extern int sram_flash_writer_program_range(
    void *writer, u32 destination, const void *source, u32 length);
extern int sram_flash_writer_flush_partial(void *writer);

#define REG32(address) (*(volatile u32 *)(address))

/* Gate-to-extension state passed through fixed SRAM words. */
#define SERVICE_COOKIE 0x43565253u
#define SERVICE_ACTIVE 0x56544341u
#define SERVICE_ERROR  0x45525200u
#define SERVICE_NOR_READY 0x5944524Eu

/* Service packet ABI. */
#define SERVICE_REQUEST_ID  0x3C1u
#define SERVICE_RESPONSE_ID 0x3C0u
#define SERVICE_PROTOCOL_VERSION 2u
#define SERVICE_MAGIC 0xA5u

#define SERVICE_COMMAND_INFO 0x02u
#define SERVICE_COMMAND_READ 0x03u
#define SERVICE_COMMAND_ERASE 0x04u
#define SERVICE_COMMAND_WRITE 0x05u
#define SERVICE_COMMAND_RESET 0x06u

#define SERVICE_STATUS_OK              0x00u
#define SERVICE_STATUS_BAD_COMMAND     0x01u
#define SERVICE_STATUS_BAD_LENGTH      0x02u
#define SERVICE_STATUS_BAD_CRC         0x03u
#define SERVICE_STATUS_BAD_VERSION     0x04u
#define SERVICE_STATUS_BAD_TARGET      0x05u
#define SERVICE_STATUS_RANGE_ERROR     0x06u
#define SERVICE_STATUS_READ_FAILURE    0x07u
#define SERVICE_STATUS_ERASE_FAILURE   0x08u
#define SERVICE_STATUS_WRITE_FAILURE   0x09u
#define SERVICE_STATUS_VERIFY_FAILURE  0x0Au

/* Stable storage target identifiers. */
#define SERVICE_TARGET_FGCB 0x01u
#define SERVICE_TARGET_SPIN 0x02u

/* ISO-TP framing over classic CAN. */
#define ISOTP_TYPE_MASK 0xF0u
#define ISOTP_SINGLE_FRAME 0x00u
#define ISOTP_FIRST_FRAME 0x10u
#define ISOTP_CONSECUTIVE_FRAME 0x20u
#define ISOTP_FLOW_CONTROL 0x30u
#define ISOTP_FLOW_STATUS_CTS 0x00u
#define ISOTP_FLOW_STATUS_WAIT 0x01u
#define ISOTP_FLOW_STATUS_OVERFLOW 0x02u
#define ISOTP_RX_BLOCK_SIZE 32u

#define SERVICE_HEADER_SIZE 8u
#define SERVICE_CRC_SIZE 2u
#define SERVICE_MAX_REQUEST_PAYLOAD 4085u
#define SERVICE_MAX_REQUEST_PACKET \
    (SERVICE_HEADER_SIZE + SERVICE_MAX_REQUEST_PAYLOAD + SERVICE_CRC_SIZE)
#define SERVICE_MAX_RESPONSE_PAYLOAD 4085u
#define SERVICE_MAX_RESPONSE_PACKET \
    (SERVICE_HEADER_SIZE + SERVICE_MAX_RESPONSE_PAYLOAD + SERVICE_CRC_SIZE)
#define SERVICE_READ_METADATA_SIZE 7u
#define SERVICE_ERASE_METADATA_SIZE 9u
#define SERVICE_WRITE_METADATA_SIZE 5u
#define SERVICE_MAX_READ_DATA SERVICE_MAX_RESPONSE_PAYLOAD
#define SERVICE_MAX_WRITE_DATA \
    (SERVICE_MAX_REQUEST_PAYLOAD - SERVICE_WRITE_METADATA_SIZE)

/* Storage geometry and SPI-NOR commands. */
#define FLASH_BASE 0x08000000u
#define FLASH_SIZE 0x00200000u
#define FLASH_ERASE_SIZE 0x00020000u
#define FLASH_PROGRAM_SIZE 32u
#define NOR_SIZE   0x01000000u
#define NOR_PAGE_SIZE 0x00000100u
#define NOR_ERASE_4K 0x00001000u
#define NOR_ERASE_64K 0x00010000u

#define NOR_COMMAND_READ 0x03u
#define NOR_COMMAND_WRITE_ENABLE 0x06u
#define NOR_COMMAND_READ_STATUS 0x05u
#define NOR_COMMAND_PAGE_PROGRAM 0x02u
#define NOR_COMMAND_ERASE_4K 0x20u
#define NOR_COMMAND_ERASE_64K 0xD8u
#define NOR_STATUS_BUSY 0x01u
#define NOR_STATUS_WRITE_ENABLE 0x02u
#define NOR_WAIT_LIMIT 1000000u

/* Minimal STM32H7 clock, GPIO, and FDCAN register map. */
#define RCC_D2CCIP1R 0x58024450u
#define RCC_AHB4ENR  0x580244E0u
#define RCC_APB1HENR 0x580244ECu
#define RCC_GPIOAEN  (1u << 0)
#define RCC_FDCANEN  (1u << 8)
#define RCC_FDCANSEL_MASK 0x30000000u

#define GPIOA_BASE 0x58020000u
#define GPIO_MODER   0x00u
#define GPIO_OTYPER  0x04u
#define GPIO_OSPEEDR 0x08u
#define GPIO_PUPDR   0x0Cu
#define GPIO_AFRH    0x24u
#define GPIO_CAN_PINS ((1u << 11) | (1u << 12))
#define GPIO_CAN_MODE_MASK ((3u << 22) | (3u << 24))
#define GPIO_CAN_AF_MASK ((0xFu << 12) | (0xFu << 16))
#define GPIO_CAN_AF9 ((9u << 12) | (9u << 16))

#define FDCAN1_BASE 0x4000A000u
#define FDCAN_TEST  0x010u
#define FDCAN_CCCR  0x018u
#define FDCAN_NBTP  0x01Cu
#define FDCAN_IR    0x050u
#define FDCAN_IE    0x054u
#define FDCAN_ILE   0x05Cu
#define FDCAN_GFC   0x080u
#define FDCAN_SIDFC 0x084u
#define FDCAN_XIDFC 0x088u
#define FDCAN_RXF0C 0x0A0u
#define FDCAN_RXF0S 0x0A4u
#define FDCAN_RXF0A 0x0A8u
#define FDCAN_RXBC  0x0ACu
#define FDCAN_RXF1C 0x0B0u
#define FDCAN_RXESC 0x0BCu
#define FDCAN_TXBC  0x0C0u
#define FDCAN_TXESC 0x0C8u
#define FDCAN_TXBRP 0x0CCu
#define FDCAN_TXBAR 0x0D0u
#define FDCAN_TXEFC 0x0F0u

#define FDCAN_CCCR_INIT (1u << 0)
#define FDCAN_CCCR_CCE  (1u << 1)
#define FDCAN_CCCR_CSA  (1u << 3)
#define FDCAN_CCCR_CSR  (1u << 4)
#define FDCAN_CCCR_MODE_MASK \
    ((1u << 2) | (1u << 5) | (1u << 6) | (1u << 7) | \
     (1u << 8) | (1u << 9) | (1u << 12) | (1u << 14))

#define FDCAN_MESSAGE_RAM 0x4000AC00u
#define FDCAN_STD_FILTER_WORD 0u
#define FDCAN_RX_FIFO0_WORD 1u
#define FDCAN_RX_FIFO0_ELEMENTS 64u
#define FDCAN_ELEMENT_WORDS 4u
#define FDCAN_TX_BUFFER_WORD \
    (FDCAN_RX_FIFO0_WORD + FDCAN_RX_FIFO0_ELEMENTS * FDCAN_ELEMENT_WORDS)
#define FDCAN_MESSAGE_RAM_WORDS (FDCAN_TX_BUFFER_WORD + FDCAN_ELEMENT_WORDS)

#define FDCAN_WAIT_LIMIT 20000000u
#define FLASH_WAIT_LIMIT 20000000u
#define FDCAN_NBTP_VALUE(brp, sjw, tseg1, tseg2) \
    ((((sjw) - 1u) << 25) | (((brp) - 1u) << 16) | \
     (((tseg1) - 1u) << 8) | ((tseg2) - 1u))
#define FDCAN_NBTP_1MBPS_HSE16 \
    FDCAN_NBTP_VALUE(1u, 2u, 13u, 2u)

#define IWDG1_KR REG32(0x58004800u)
#define IWDG_REFRESH 0x0000AAAAu
#define SCB_AIRCR REG32(0xE000ED0Cu)
#define SCB_AIRCR_VECTKEY 0x05FA0000u
#define SCB_AIRCR_PRIGROUP_MASK 0x00000700u
#define SCB_AIRCR_SYSRESETREQ (1u << 2)

/* Prefix of the context passed to the native SRAM updater entry point. */
struct updater_context {
    void *status_store;
    void *container_processor;
    void *iwdg_control;
    void *local_data;
    void *status_indicator;
    void (*fatal_status_loop)(void *iwdg_control, void *status_indicator);
};

typedef char updater_context_must_be_six_words[
    sizeof(struct updater_context) == 24 ? 1 : -1
];

struct rx_packet {
    u8 bytes[SERVICE_MAX_REQUEST_PACKET];
    u16 length;
    u16 expected_length;
    u8 active;
    u8 next_sequence;
    u8 block_count;
};

/* Runtime helpers shared by transport and storage operations. */
static void watchdog_refresh(void)
{
    IWDG1_KR = IWDG_REFRESH;
}

static void service_housekeeping(void)
{
    sram_writer_wrapper_service(&sram_writer_wrapper_singleton);
    watchdog_refresh();
}

static void barrier(void)
{
    __asm__ volatile ("dsb" ::: "memory");
}

static u16 get_u16_le(const u8 *data)
{
    return (u16)((u16)data[0] | ((u16)data[1] << 8));
}

static u32 get_u32_le(const u8 *data)
{
    return (u32)data[0] | ((u32)data[1] << 8) |
           ((u32)data[2] << 16) | ((u32)data[3] << 24);
}

static void put_u16_le(u8 *data, u16 value)
{
    data[0] = (u8)value;
    data[1] = (u8)(value >> 8);
}

static int range_ok(u32 offset, u32 length, u32 base, u32 size)
{
    if (offset < base) {
        return 0;
    }
    offset -= base;
    return offset < size && length <= size - offset;
}

static u8 target_range_status(u8 target, u32 offset, u32 length)
{
    if (target == SERVICE_TARGET_FGCB) {
        return range_ok(offset, length, FLASH_BASE, FLASH_SIZE) ?
            SERVICE_STATUS_OK : SERVICE_STATUS_RANGE_ERROR;
    }
    if (target == SERVICE_TARGET_SPIN) {
        return range_ok(offset, length, 0u, NOR_SIZE) ?
            SERVICE_STATUS_OK : SERVICE_STATUS_RANGE_ERROR;
    }
    return SERVICE_STATUS_BAD_TARGET;
}

static int wait_register(u32 offset, u32 mask, u32 expected)
{
    u32 limit = FDCAN_WAIT_LIMIT;

    while ((REG32(FDCAN1_BASE + offset) & mask) != expected) {
        if (--limit == 0u) {
            return -1;
        }
        watchdog_refresh();
    }
    return 0;
}

/* Polling FDCAN1 driver for the fixed service request/response IDs. */
static void gpio_can_init(void)
{
    u32 value;

    REG32(RCC_AHB4ENR) |= RCC_GPIOAEN;
    (void)REG32(RCC_AHB4ENR);

    value = REG32(GPIOA_BASE + GPIO_MODER);
    value = (value & ~GPIO_CAN_MODE_MASK) | ((2u << 22) | (2u << 24));
    REG32(GPIOA_BASE + GPIO_MODER) = value;
    REG32(GPIOA_BASE + GPIO_OTYPER) &= ~GPIO_CAN_PINS;
    REG32(GPIOA_BASE + GPIO_OSPEEDR) &= ~GPIO_CAN_MODE_MASK;
    REG32(GPIOA_BASE + GPIO_PUPDR) &= ~GPIO_CAN_MODE_MASK;
    value = REG32(GPIOA_BASE + GPIO_AFRH);
    REG32(GPIOA_BASE + GPIO_AFRH) =
        (value & ~GPIO_CAN_AF_MASK) | GPIO_CAN_AF9;
    barrier();
}

static int fdcan_init(void)
{
    volatile u32 *ram = (volatile u32 *)FDCAN_MESSAGE_RAM;
    u32 i;
    u32 tail_offset = FDCAN_TX_BUFFER_WORD * 4u;
    u32 cccr;

    /* FGBL runs HSE at 16 MHz. Keep FDCAN on HSE explicitly. */
    REG32(RCC_D2CCIP1R) &= ~RCC_FDCANSEL_MASK;
    REG32(RCC_APB1HENR) |= RCC_FDCANEN;
    (void)REG32(RCC_APB1HENR);
    gpio_can_init();

    REG32(FDCAN1_BASE + FDCAN_CCCR) &= ~FDCAN_CCCR_CSR;
    if (wait_register(FDCAN_CCCR, FDCAN_CCCR_CSA, 0u) != 0) {
        return 1;
    }
    REG32(FDCAN1_BASE + FDCAN_CCCR) |= FDCAN_CCCR_INIT;
    if (wait_register(FDCAN_CCCR, FDCAN_CCCR_INIT, FDCAN_CCCR_INIT) != 0) {
        return 2;
    }
    REG32(FDCAN1_BASE + FDCAN_CCCR) |= FDCAN_CCCR_CCE;

    cccr = REG32(FDCAN1_BASE + FDCAN_CCCR);
    REG32(FDCAN1_BASE + FDCAN_CCCR) =
        (cccr & ~FDCAN_CCCR_MODE_MASK) | FDCAN_CCCR_INIT | FDCAN_CCCR_CCE;
    REG32(FDCAN1_BASE + FDCAN_TEST) &= ~(1u << 4);

    /* 16 MHz / (1 * (1 + 13 + 2)) = 1 Mbit/s, 87.5% sample point. */
    REG32(FDCAN1_BASE + FDCAN_NBTP) = FDCAN_NBTP_1MBPS_HSE16;

    for (i = 0; i != FDCAN_MESSAGE_RAM_WORDS; ++i) {
        ram[i] = 0u;
    }

    REG32(FDCAN1_BASE + FDCAN_SIDFC) = (1u << 16);
    REG32(FDCAN1_BASE + FDCAN_XIDFC) = 4u;
    REG32(FDCAN1_BASE + FDCAN_RXF0C) =
        4u | (FDCAN_RX_FIFO0_ELEMENTS << 16);
    REG32(FDCAN1_BASE + FDCAN_RXF1C) = tail_offset;
    REG32(FDCAN1_BASE + FDCAN_RXBC) = tail_offset;
    REG32(FDCAN1_BASE + FDCAN_TXEFC) = tail_offset;
    REG32(FDCAN1_BASE + FDCAN_TXBC) = tail_offset | (1u << 16);
    REG32(FDCAN1_BASE + FDCAN_RXESC) = 0u;
    REG32(FDCAN1_BASE + FDCAN_TXESC) = 0u;

    /* Exact standard-ID mask filter, routed to RX FIFO0. */
    ram[FDCAN_STD_FILTER_WORD] =
        0x88000000u | (SERVICE_REQUEST_ID << 16) | 0x7FFu;
    REG32(FDCAN1_BASE + FDCAN_GFC) = 0x2Bu;
    REG32(FDCAN1_BASE + FDCAN_IE) = 0u;
    REG32(FDCAN1_BASE + FDCAN_ILE) = 0u;
    REG32(FDCAN1_BASE + FDCAN_IR) = 0xFFFFFFFFu;
    barrier();

    REG32(FDCAN1_BASE + FDCAN_CCCR) &= ~FDCAN_CCCR_INIT;
    if (wait_register(FDCAN_CCCR, FDCAN_CCCR_INIT, 0u) != 0) {
        return 3;
    }
    return 0;
}

static int fdcan_receive(u8 *data, u8 *length)
{
    volatile u32 *element;
    u32 status = REG32(FDCAN1_BASE + FDCAN_RXF0S);
    u32 index;
    u32 word0;
    u32 word1;
    u32 dlc;
    u32 i;

    if ((status & 0x7Fu) == 0u) {
        return 0;
    }
    index = (status >> 8) & 0x3Fu;
    element = (volatile u32 *)(FDCAN_MESSAGE_RAM + 4u + index * 16u);
    word0 = element[0];
    word1 = element[1];
    dlc = (word1 >> 16) & 0xFu;

    if (((word0 >> 18) & 0x7FFu) != SERVICE_REQUEST_ID ||
        (word0 & 0x60000000u) != 0u ||
        (word1 & 0x00300000u) != 0u || dlc > 8u) {
        REG32(FDCAN1_BASE + FDCAN_RXF0A) = index;
        return -1;
    }

    for (i = 0; i != dlc; ++i) {
        data[i] = ((volatile u8 *)(element + 2))[i];
    }
    *length = (u8)dlc;
    REG32(FDCAN1_BASE + FDCAN_RXF0A) = index;
    return 1;
}

static int fdcan_send(const u8 *data, u8 length)
{
    volatile u32 *element =
        (volatile u32 *)(FDCAN_MESSAGE_RAM + FDCAN_TX_BUFFER_WORD * 4u);
    u32 payload_word0 = 0u;
    u32 payload_word1 = 0u;
    u32 i;

    if (length > 8u) {
        return -1;
    }
    if (wait_register(FDCAN_TXBRP, 1u, 0u) != 0) {
        return -1;
    }

    element[0] = SERVICE_RESPONSE_ID << 18;
    element[1] = (u32)length << 16;
    /* SRAMCAN payload writes must use aligned 32-bit accesses. */
    for (i = 0; i != length && i != 4u; ++i) {
        payload_word0 |= (u32)data[i] << (i * 8u);
    }
    for (; i != length; ++i) {
        payload_word1 |= (u32)data[i] << ((i - 4u) * 8u);
    }
    element[2] = payload_word0;
    element[3] = payload_word1;
    barrier();
    REG32(FDCAN1_BASE + FDCAN_TXBAR) = 1u;
    barrier();
    return wait_register(FDCAN_TXBRP, 1u, 0u);
}

/* ISO-TP reassembly, flow control, and packet transmission. */
static int append_isotp_data(struct rx_packet *packet, const u8 *data,
                             u8 length)
{
    u32 i;
    u32 remaining;

    remaining = packet->expected_length - packet->length;
    if (length > remaining) {
        length = (u8)remaining;
    }
    for (i = 0; i != length; ++i) {
        packet->bytes[packet->length++] = data[i];
    }
    return 0;
}

static int send_flow_control(void)
{
    u8 frame[3];

    frame[0] = ISOTP_FLOW_CONTROL | ISOTP_FLOW_STATUS_CTS;
    frame[1] = ISOTP_RX_BLOCK_SIZE;
    frame[2] = 0u;
    return fdcan_send(frame, sizeof(frame));
}

static int receive_isotp(struct rx_packet *packet, const u8 *frame, u8 length)
{
    u8 type;
    u16 expected_length;

    if (length == 0u) {
        return -1;
    }
    type = frame[0] & ISOTP_TYPE_MASK;

    if (type == ISOTP_SINGLE_FRAME) {
        expected_length = frame[0] & 0x0Fu;
        if (expected_length == 0u || expected_length > length - 1u ||
            expected_length > SERVICE_MAX_REQUEST_PACKET) {
            return -1;
        }
        packet->length = 0u;
        packet->expected_length = expected_length;
        packet->active = 0u;
        append_isotp_data(packet, frame + 1, (u8)(length - 1u));
        return 1;
    }

    if (type == ISOTP_FIRST_FRAME) {
        if (length < 2u) {
            return -1;
        }
        expected_length =
            (u16)(((u16)(frame[0] & 0x0Fu) << 8) | frame[1]);
        if (expected_length <= 7u ||
            expected_length > SERVICE_MAX_REQUEST_PACKET) {
            packet->active = 0u;
            return -1;
        }
        packet->length = 0u;
        packet->expected_length = expected_length;
        packet->next_sequence = 1u;
        packet->block_count = 0u;
        packet->active = 1u;
        append_isotp_data(packet, frame + 2, (u8)(length - 2u));
        if (send_flow_control() != 0) {
            packet->active = 0u;
            return -1;
        }
        return 0;
    }

    if (type != ISOTP_CONSECUTIVE_FRAME || packet->active == 0u ||
        length < 2u || (frame[0] & 0x0Fu) != packet->next_sequence) {
        packet->active = 0u;
        return -1;
    }
    packet->next_sequence = (u8)((packet->next_sequence + 1u) & 0x0Fu);
    append_isotp_data(packet, frame + 1, (u8)(length - 1u));
    if (packet->length == packet->expected_length) {
        packet->active = 0u;
        return 1;
    }

    packet->block_count++;
    if (packet->block_count == ISOTP_RX_BLOCK_SIZE) {
        packet->block_count = 0u;
        if (send_flow_control() != 0) {
            packet->active = 0u;
            return -1;
        }
    }
    return 0;
}

static int wait_flow_control(u8 *block_size)
{
    u32 limit = FDCAN_WAIT_LIMIT;
    u8 frame[8];
    u8 length;

    while (limit-- != 0u) {
        int result;

        service_housekeeping();
        result = fdcan_receive(frame, &length);
        if (result <= 0) {
            continue;
        }
        if (length < 3u ||
            (frame[0] & ISOTP_TYPE_MASK) != ISOTP_FLOW_CONTROL) {
            continue;
        }
        if ((frame[0] & 0x0Fu) == ISOTP_FLOW_STATUS_WAIT) {
            continue;
        }
        if ((frame[0] & 0x0Fu) != ISOTP_FLOW_STATUS_CTS || frame[2] != 0u) {
            return -1;
        }
        *block_size = frame[1];
        return 0;
    }
    return -1;
}

static int send_packet(u8 command, u8 status, u16 sequence,
                       const u8 *payload, u16 payload_length)
{
    u8 packet[SERVICE_MAX_RESPONSE_PACKET];
    u8 frame[8];
    u32 total_length;
    u32 offset;
    u32 i;
    u16 checksum;
    u8 consecutive_sequence = 1u;
    u8 block_size;
    u8 block_count = 0u;

    if (payload_length > SERVICE_MAX_RESPONSE_PAYLOAD) {
        return -1;
    }
    packet[0] = SERVICE_MAGIC;
    packet[1] = SERVICE_PROTOCOL_VERSION;
    packet[2] = command;
    packet[3] = status;
    put_u16_le(packet + 4, sequence);
    put_u16_le(packet + 6, payload_length);
    for (i = 0; i != payload_length; ++i) {
        packet[SERVICE_HEADER_SIZE + i] = payload[i];
    }
    total_length = SERVICE_HEADER_SIZE + payload_length;
    checksum = sram_updater_crc16_ccitt(packet, total_length);
    put_u16_le(packet + total_length, checksum);
    total_length += SERVICE_CRC_SIZE;

    if (total_length <= 7u) {
        frame[0] = (u8)total_length;
        for (i = 0u; i != total_length; ++i) {
            frame[i + 1u] = packet[i];
        }
        return fdcan_send(frame, (u8)(total_length + 1u));
    }

    frame[0] = ISOTP_FIRST_FRAME | (u8)(total_length >> 8);
    frame[1] = (u8)total_length;
    for (i = 0u; i != 6u; ++i) {
        frame[i + 2u] = packet[i];
    }
    if (fdcan_send(frame, sizeof(frame)) != 0 ||
        wait_flow_control(&block_size) != 0) {
        return -1;
    }

    offset = 6u;
    while (offset < total_length) {
        u32 remaining = total_length - offset;
        u8 chunk = (u8)(remaining > 7u ? 7u : remaining);

        frame[0] = ISOTP_CONSECUTIVE_FRAME | consecutive_sequence;
        for (i = 0; i != chunk; ++i) {
            frame[i + 1u] = packet[offset + i];
        }
        if (fdcan_send(frame, (u8)(chunk + 1u)) != 0) {
            return -1;
        }
        offset += chunk;
        consecutive_sequence = (u8)((consecutive_sequence + 1u) & 0x0Fu);
        block_count++;
        if (offset < total_length && block_size != 0u &&
            block_count == block_size) {
            block_count = 0u;
            if (wait_flow_control(&block_size) != 0) {
                return -1;
            }
        }
    }
    return 0;
}

static void send_error(const u8 *packet, u8 status)
{
    if (packet[0] == SERVICE_MAGIC) {
        send_packet(packet[2], status, get_u16_le(packet + 4), 0, 0u);
    }
}

static int bytes_equal(const u8 *left, const u8 *right, u32 length)
{
    while (length-- != 0u) {
        if (*left++ != *right++) {
            return 0;
        }
    }
    return 1;
}

/* SPI-NOR backend built on the native updater's synchronous job API. */
static void __attribute__((noinline)) nor_ensure_initialized(void)
{
    if (fgbl_service_cookie != SERVICE_NOR_READY) {
        void *reader = sram_nor_spi_reader_singleton();

        sram_nor_enable_status_write_protection(reader);
        fgbl_service_cookie = SERVICE_NOR_READY;
    }
}

static int nor_receive(const u8 *command, u32 command_length,
                       u8 *destination, u32 length)
{
    void *job;

    nor_ensure_initialized();
    job = sram_nor_read_job_get(0);
    return sram_nor_read_job_submit_and_copy(
        job, command, command_length, destination, length,
        sram_nor_set_chip_select
    );
}

static int nor_transmit(const u8 *data, u32 length)
{
    void *job;

    nor_ensure_initialized();
    job = sram_nor_read_job_get(0);
    return sram_nor_read_job_transmit(
        job, data, length, sram_nor_set_chip_select
    );
}

static int nor_read_status(u8 *status)
{
    u8 command = NOR_COMMAND_READ_STATUS;

    return nor_receive(&command, 1u, status, 1u);
}

static int nor_write_enable(void)
{
    u8 command = NOR_COMMAND_WRITE_ENABLE;
    u8 status;

    if (nor_transmit(&command, 1u) == 0 ||
        nor_read_status(&status) == 0) {
        return 0;
    }
    return (status & NOR_STATUS_WRITE_ENABLE) != 0u;
}

static int nor_wait_ready(void)
{
    u32 limit = NOR_WAIT_LIMIT;
    u8 status;

    while (limit-- != 0u) {
        service_housekeeping();
        if (nor_read_status(&status) == 0) {
            return 0;
        }
        if ((status & NOR_STATUS_BUSY) == 0u) {
            return 1;
        }
    }
    return 0;
}

static int nor_read_range(u32 offset, u8 *destination, u32 length)
{
    u8 command[4];

    while (length != 0u) {
        u32 chunk = length > NOR_PAGE_SIZE ? NOR_PAGE_SIZE : length;

        command[0] = NOR_COMMAND_READ;
        command[1] = (u8)(offset >> 16);
        command[2] = (u8)(offset >> 8);
        command[3] = (u8)offset;
        if (nor_receive(command, sizeof(command), destination, chunk) == 0) {
            return 0;
        }
        offset += chunk;
        destination += chunk;
        length -= chunk;
    }
    return 1;
}

static int nor_erase_range(u32 offset, u32 length)
{
    u8 command[4];
    u8 verify[NOR_PAGE_SIZE];
    u32 verify_offset;
    u32 i;

    if (length == NOR_ERASE_4K && (offset & (NOR_ERASE_4K - 1u)) == 0u) {
        command[0] = NOR_COMMAND_ERASE_4K;
    } else if (length == NOR_ERASE_64K &&
               (offset & (NOR_ERASE_64K - 1u)) == 0u) {
        command[0] = NOR_COMMAND_ERASE_64K;
    } else {
        return 0;
    }

    command[1] = (u8)(offset >> 16);
    command[2] = (u8)(offset >> 8);
    command[3] = (u8)offset;
    sram_nor_set_write_protect(0, 0);
    if (nor_write_enable() == 0 ||
        nor_transmit(command, sizeof(command)) == 0 ||
        nor_wait_ready() == 0) {
        sram_nor_set_write_protect(0, 1);
        return 0;
    }
    sram_nor_set_write_protect(0, 1);
    for (verify_offset = 0u; verify_offset != length;
         verify_offset += NOR_PAGE_SIZE) {
        service_housekeeping();
        if (nor_read_range(offset + verify_offset, verify,
                           NOR_PAGE_SIZE) == 0) {
            return 0;
        }
        for (i = 0u; i != NOR_PAGE_SIZE; ++i) {
            if (verify[i] != 0xFFu) {
                return 0;
            }
        }
    }
    return 1;
}

/* Return 1 on success, 0 on transfer failure, and -1 on verify failure. */
static int nor_write_range(u32 offset, const u8 *source, u32 length)
{
    u8 command[4u + NOR_PAGE_SIZE];
    u8 verify[NOR_PAGE_SIZE];

    sram_nor_set_write_protect(0, 0);
    while (length != 0u) {
        u32 page_left = NOR_PAGE_SIZE - (offset & (NOR_PAGE_SIZE - 1u));
        u32 chunk = length < page_left ? length : page_left;
        u32 i;

        command[0] = NOR_COMMAND_PAGE_PROGRAM;
        command[1] = (u8)(offset >> 16);
        command[2] = (u8)(offset >> 8);
        command[3] = (u8)offset;
        for (i = 0u; i != chunk; ++i) {
            command[4u + i] = source[i];
        }
        if (nor_write_enable() == 0 ||
            nor_transmit(command, 4u + chunk) == 0 ||
            nor_wait_ready() == 0) {
            sram_nor_set_write_protect(0, 1);
            return 0;
        }
        if (nor_read_range(offset, verify, chunk) == 0) {
            sram_nor_set_write_protect(0, 1);
            return 0;
        }
        if (bytes_equal(source, verify, chunk) == 0) {
            sram_nor_set_write_protect(0, 1);
            return -1;
        }
        offset += chunk;
        source += chunk;
        length -= chunk;
    }
    sram_nor_set_write_protect(0, 1);
    return 1;
}

/* Internal-flash backend built on the native SRAM flash writer. */
static int flash_erase_sector(u32 address)
{
    void *writer = &sram_flash_writer_singleton;
    u32 wait_limit;
    u32 i;

    sram_flash_writer_init(writer);
    sram_flash_writer_queue_overlapping_sectors(
        writer, address, FLASH_ERASE_SIZE
    );
    sram_flash_writer_unlock();
    while (sram_flash_writer_erase_queue_done(writer) == 0) {
        sram_flash_writer_erase_next_sector(writer);
        wait_limit = FLASH_WAIT_LIMIT;
        while (sram_flash_writer_busy() == 0) {
            service_housekeeping();
            if (--wait_limit == 0u) {
                sram_flash_writer_lock();
                return 0;
            }
        }
    }
    sram_flash_writer_lock();
    barrier();
    for (i = 0u; i != FLASH_ERASE_SIZE; ++i) {
        if ((i & 0xFFFu) == 0u) {
            service_housekeeping();
        }
        if (*(volatile const u8 *)(address + i) != 0xFFu) {
            return 0;
        }
    }
    return 1;
}

/* Return 1 on success, 0 on write failure, and -1 on verify failure. */
static int flash_write_range(u32 address, const u8 *source, u32 length)
{
    void *writer = &sram_flash_writer_singleton;
    u32 i;

    sram_flash_writer_init(writer);
    sram_flash_writer_unlock();
    if (sram_flash_writer_program_range(writer, address, source, length) == 0 ||
        sram_flash_writer_flush_partial(writer) == 0) {
        sram_flash_writer_lock();
        return 0;
    }
    sram_flash_writer_lock();
    barrier();
    for (i = 0u; i != length; ++i) {
        if ((i & 0xFFFu) == 0u) {
            service_housekeeping();
        }
        if (*(volatile const u8 *)(address + i) != source[i]) {
            return -1;
        }
    }
    return 1;
}

/* Validate service requests and dispatch them to one storage backend. */
static void handle_read_request(const u8 *request, const u8 *payload,
                                u16 payload_length)
{
    u8 response[SERVICE_MAX_RESPONSE_PAYLOAD];
    u16 sequence = get_u16_le(request + 4);
    u8 target;
    u32 offset;
    u16 length;
    u8 status;
    u32 i;

    if (payload_length != SERVICE_READ_METADATA_SIZE) {
        send_error(request, SERVICE_STATUS_BAD_LENGTH);
        return;
    }

    target = payload[0];
    offset = get_u32_le(payload + 1);
    length = get_u16_le(payload + 5);
    if (length == 0u || length > SERVICE_MAX_READ_DATA) {
        send_error(request, SERVICE_STATUS_BAD_LENGTH);
        return;
    }
    status = target_range_status(target, offset, length);
    if (status != SERVICE_STATUS_OK) {
        send_error(request, status);
        return;
    }

    if (target == SERVICE_TARGET_FGCB) {
        for (i = 0u; i != length; ++i) {
            response[i] = *(volatile const u8 *)(offset + i);
        }
    } else {
        if (nor_read_range(offset, response, length) == 0) {
            send_error(request, SERVICE_STATUS_READ_FAILURE);
            return;
        }
    }

    send_packet(SERVICE_COMMAND_READ, SERVICE_STATUS_OK, sequence,
                response, length);
}

static void handle_erase_request(const u8 *request, const u8 *payload,
                                 u16 payload_length)
{
    u16 sequence = get_u16_le(request + 4);
    u8 target;
    u32 offset;
    u32 length;
    u8 status;
    int result;

    if (payload_length != SERVICE_ERASE_METADATA_SIZE) {
        send_error(request, SERVICE_STATUS_BAD_LENGTH);
        return;
    }
    target = payload[0];
    offset = get_u32_le(payload + 1);
    length = get_u32_le(payload + 5);
    status = target_range_status(target, offset, length);
    if (status != SERVICE_STATUS_OK) {
        send_error(request, status);
        return;
    }

    if (target == SERVICE_TARGET_FGCB) {
        if (length != FLASH_ERASE_SIZE ||
            (offset & (FLASH_ERASE_SIZE - 1u)) != 0u) {
            send_error(request, SERVICE_STATUS_RANGE_ERROR);
            return;
        }
        result = flash_erase_sector(offset);
    } else {
        result = nor_erase_range(offset, length);
    }

    if (result == 0) {
        send_error(request, SERVICE_STATUS_ERASE_FAILURE);
        return;
    }
    send_packet(SERVICE_COMMAND_ERASE, SERVICE_STATUS_OK, sequence, 0, 0u);
}

static void handle_write_request(const u8 *request, const u8 *payload,
                                 u16 payload_length)
{
    u16 sequence = get_u16_le(request + 4);
    u8 target;
    u32 offset;
    u32 length;
    u8 status;
    int result;

    if (payload_length <= SERVICE_WRITE_METADATA_SIZE) {
        send_error(request, SERVICE_STATUS_BAD_LENGTH);
        return;
    }
    target = payload[0];
    offset = get_u32_le(payload + 1);
    length = payload_length - SERVICE_WRITE_METADATA_SIZE;
    if (length > SERVICE_MAX_WRITE_DATA) {
        send_error(request, SERVICE_STATUS_BAD_LENGTH);
        return;
    }
    status = target_range_status(target, offset, length);
    if (status != SERVICE_STATUS_OK) {
        send_error(request, status);
        return;
    }

    if (target == SERVICE_TARGET_FGCB) {
        if ((offset & (FLASH_PROGRAM_SIZE - 1u)) != 0u ||
            (length & (FLASH_PROGRAM_SIZE - 1u)) != 0u) {
            send_error(request, SERVICE_STATUS_RANGE_ERROR);
            return;
        }
        result = flash_write_range(
            offset, payload + SERVICE_WRITE_METADATA_SIZE, length
        );
    } else {
        result = nor_write_range(
            offset, payload + SERVICE_WRITE_METADATA_SIZE, length
        );
    }

    if (result == 0) {
        send_error(request, SERVICE_STATUS_WRITE_FAILURE);
        return;
    }
    if (result < 0) {
        send_error(request, SERVICE_STATUS_VERIFY_FAILURE);
        return;
    }
    send_packet(SERVICE_COMMAND_WRITE, SERVICE_STATUS_OK, sequence, 0, 0u);
}

static void handle_packet(struct rx_packet *packet)
{
    const u8 *request = packet->bytes;
    const u8 *payload;
    u16 sequence;
    u16 payload_length;
    u16 expected_crc;
    u16 actual_crc;

    if (packet->length < SERVICE_HEADER_SIZE + SERVICE_CRC_SIZE) {
        return;
    }
    if (request[0] != SERVICE_MAGIC) {
        return;
    }
    payload = request + SERVICE_HEADER_SIZE;
    sequence = get_u16_le(request + 4);
    payload_length = get_u16_le(request + 6);
    if ((u32)packet->length !=
        SERVICE_HEADER_SIZE + payload_length + SERVICE_CRC_SIZE) {
        send_error(request, SERVICE_STATUS_BAD_LENGTH);
        return;
    }
    expected_crc = get_u16_le(payload + payload_length);
    actual_crc = sram_updater_crc16_ccitt(
        request, SERVICE_HEADER_SIZE + payload_length
    );

    if (request[1] != SERVICE_PROTOCOL_VERSION) {
        send_error(request, SERVICE_STATUS_BAD_VERSION);
        return;
    }
    if (actual_crc != expected_crc) {
        send_error(request, SERVICE_STATUS_BAD_CRC);
        return;
    }
    if (request[3] != SERVICE_STATUS_OK) {
        send_error(request, SERVICE_STATUS_BAD_LENGTH);
        return;
    }

    if (request[2] == SERVICE_COMMAND_INFO) {
        static const u8 fgbl_bid[16] = "1.1.0.736edbdfd";
        u8 info[19];
        u32 i;

        if (payload_length != 0u) {
            send_error(request, SERVICE_STATUS_BAD_LENGTH);
            return;
        }
        info[0] = 0u;
        info[1] = 7u;
        info[2] = 0u;
        for (i = 0; i != sizeof(fgbl_bid); ++i) {
            info[3 + i] = fgbl_bid[i];
        }
        send_packet(SERVICE_COMMAND_INFO, SERVICE_STATUS_OK,
                    sequence, info, sizeof(info));
        return;
    }

    if (request[2] == SERVICE_COMMAND_READ) {
        handle_read_request(request, payload, payload_length);
        return;
    }
    if (request[2] == SERVICE_COMMAND_ERASE) {
        handle_erase_request(request, payload, payload_length);
        return;
    }
    if (request[2] == SERVICE_COMMAND_WRITE) {
        handle_write_request(request, payload, payload_length);
        return;
    }
    if (request[2] == SERVICE_COMMAND_RESET) {
        if (payload_length != 0u) {
            send_error(request, SERVICE_STATUS_BAD_LENGTH);
            return;
        }
        if (send_packet(SERVICE_COMMAND_RESET, SERVICE_STATUS_OK,
                        sequence, 0, 0u) == 0) {
            barrier();
            SCB_AIRCR = SCB_AIRCR_VECTKEY |
                (SCB_AIRCR & SCB_AIRCR_PRIGROUP_MASK) |
                SCB_AIRCR_SYSRESETREQ;
            barrier();
            for (;;) {
            }
        }
        return;
    }

    send_error(request, SERVICE_STATUS_BAD_COMMAND);
}

/* The service is request/response only; all long waits run housekeeping. */
static void service_loop(void)
{
    struct rx_packet packet;
    u8 frame[8];
    u8 frame_length;
    int result;

    packet.length = 0u;
    packet.expected_length = 0u;
    packet.active = 0u;
    packet.next_sequence = 0u;
    packet.block_count = 0u;

    for (;;) {
        service_housekeeping();
        result = fdcan_receive(frame, &frame_length);
        if (result <= 0) {
            continue;
        }
        result = receive_isotp(&packet, frame, frame_length);
        if (result > 0) {
            handle_packet(&packet);
        }
    }
}

/* Preserve the stock updater path unless the flash-resident gate selected us. */
void __attribute__((section(".text.0.main")))
start(struct updater_context *context)
{
    int init_status;

    if (fgbl_service_cookie != SERVICE_COOKIE) {
        sram_updater_run_staged_upgrade_flow(context);
        return;
    }

    fgbl_service_cookie = 0u;
    fgbl_service_active = SERVICE_ACTIVE;
    barrier();

    init_status = fdcan_init();
    if (init_status == 0) {
        service_loop();
    }

    fgbl_service_active = SERVICE_ERROR | (u32)init_status;
    barrier();
    for (;;) {
        watchdog_refresh();
    }
}

/*
 * EEPROM tool CDX stub firmware on s10 platform
 *
 * Bare-metal, single-threaded.  Replaces CDX region.
 * Binary protocol over USART3, DMA TX
 *
 * Hardware:
 *   SPI1:   PB3/SCK  PB4/MISO  PB5/MOSI
 *   CS:     PA15
 *   WP:     PC1
 *   USART3: PB10/TX  PB11/RX
 *   EEPROM: M95M02, 256KB, 256-byte pages
 */

#include "eeprom_stub.h"


u16 crc16_ccitt(const u8 *data, usize len)
{
    u16 crc = 0xFFFF;
    for (usize i = 0; i < len; i++) {
        crc ^= (u16)data[i] << 8;
        for (int b = 0; b < 8; b++)
            crc = (crc & 0x8000) ? (crc << 1) ^ 0x1021 : crc << 1;
    }
    return crc;
}

u16 crc16_ccitt_update(u16 crc, const u8 *data, usize len)
{
    while (len--) {
        crc ^= (u16)(*data++) << 8;
        for (int i = 0; i < 8; i++)
            crc = (crc & 0x8000) ? (crc << 1) ^ 0x1021 : crc << 1;
    }
    return crc;
}

void *memcpy(void *dst, const void *src, usize n)
{
    u8 *d = dst; const u8 *s = src;
    while (n--) *d++ = *s++;
    return dst;
}

void *memset(void *dst, int c, usize n)
{
    u8 *d = dst;
    while (n--) *d++ = (u8)c;
    return dst;
}

int memcmp(const void *a, const void *b, usize n)
{
    const u8 *p = a, *q = b;
    while (n--) {
        if (*p != *q) return (int)*p - (int)*q;
        p++; q++;
    }
    return 0;
}


extern u32 _sidata, _sdata, _edata, _sbss, _ebss, _estack;


// SID tag at CDX+0x000
// Bootloader reads bytes 0..15 from CDX base for G S #SID response.
__attribute__((section(".sid_tag"), used))
const char g_sid_tag[16] = FW_TAG;


// Vector table at CDX+0x200
// - CDX boot entry (bootloader reads [0]=SP, [1]=entry point)
// - NVIC dispatch (via VTOR pointing here)

void Reset_Handler(void);
void Default_Handler(void);
void TIM2_IRQHandler(void);
void DMA1_Stream3_IRQHandler(void);

__attribute__((section(".isr_vector"), used))
const u32 g_vectors[45] = {
    [0]  = (u32)&_estack,
    [1]  = (u32)Reset_Handler,
    [2]  = (u32)Default_Handler,        /* NMI        */
    [3]  = (u32)Default_Handler,        /* HardFault  */
    [4]  = (u32)Default_Handler,        /* MemManage  */
    [5]  = (u32)Default_Handler,        /* BusFault   */
    [6]  = (u32)Default_Handler,        /* UsageFault */
    [11] = (u32)Default_Handler,        /* SVCall     */
    [14] = (u32)Default_Handler,        /* PendSV     */
    [15] = (u32)Default_Handler,        /* SysTick    */
    [30] = (u32)DMA1_Stream3_IRQHandler,/* IRQ14      */
    [44] = (u32)TIM2_IRQHandler,        /* IRQ28      */
};

void Default_Handler(void) { for (;;); }

__attribute__((naked))
void Reset_Handler(void)
{
    __asm volatile ("ldr sp, =_estack");

    u32 *src = &_sidata, *dst = &_sdata;
    while (dst < &_edata)
        *dst++ = *src++;

    dst = &_sbss;
    while (dst < &_ebss)
        *dst++ = 0;

    SCB_CPACR |= (0xFu << 20);
    __asm volatile ("dsb; isb");

    SCB_VTOR = (u32)g_vectors;

    extern int main(void);
    main();
    for (;;);
}


static inline void iwdg_kick(void) { IWDG_KR = 0xAAAA; }

static void iwdg_extend_timeout_max(void)
{
    IWDG_KR  = 0x5555;
    IWDG_PR  = 0x06;
    IWDG_RLR = 0x0FFF;
    while (IWDG_SR)
        ;
    IWDG_KR = 0xAAAA;
}

void TIM2_IRQHandler(void)
{
    if (TIM2_SR & TIM_UIF) {
        TIM2_SR = ~TIM_UIF;
        iwdg_kick();
    }
}

static void watchdog_timer_init(void)
{
    RCC_APB1ENR |= RCC_APB1_TIM2EN;
    TIM2_PSC  = 42000 - 1;   // 84 MHz / 42000 = 2 kHz
    TIM2_ARR  = 40 - 1;      // 2 kHz / 40 = 50 Hz -> 20 ms
    TIM2_EGR  = TIM_UG;
    TIM2_DIER |= TIM_UIE;
    TIM2_CR1  |= TIM_CEN;
    nvic_enable_irq(IRQn_TIM2);
}


static inline u32 millis(void) { return TIM5_CNT / 2; }

static void tim5_timebase_init(void)
{
    RCC_APB1ENR |= RCC_APB1_TIM5EN;
    TIM5_PSC = 42000 - 1;   // 2 kHz from 84 MHz
    TIM5_ARR = 0xFFFFFFFF;
    TIM5_CNT = 0;
    TIM5_EGR = TIM_UG;
    TIM5_CR1 = TIM_CEN;
}


static void ensure_pll(void)
{
    if ((RCC_CFGR & RCC_CFGR_SWS_MASK) == RCC_CFGR_SWS_PLL)
        return;

    RCC_CR |= RCC_CR_HSEON;
    while (!(RCC_CR & RCC_CR_HSERDY))
        ;

    FLASH_ACR = FLASH_ACR_ICEN | FLASH_ACR_DCEN |
                FLASH_ACR_PRFTEN | FLASH_ACR_LATENCY_5WS;

    /* 8 MHz HSE / 8 * 336 / 2 = 168 MHz */
    RCC_PLLCFGR = (8u << 0) | (336u << 6) | (0u << 16) | RCC_PLLCFGR_SRC_HSE;

    RCC_CR |= RCC_CR_PLLON;
    while (!(RCC_CR & RCC_CR_PLLRDY))
        ;

    RCC_CFGR = RCC_CFGR_PPRE1_DIV4 | RCC_CFGR_PPRE2_DIV2;
    RCC_CFGR |= RCC_CFGR_SW_PLL;
    while ((RCC_CFGR & RCC_CFGR_SWS_MASK) != RCC_CFGR_SWS_PLL)
        ;
}


// SPI1 / EEPROM

static inline void cs_low(void)  { GPIOA_BSRR = (1u << (15 + 16)); }
static inline void cs_high(void) { GPIOA_BSRR = (1u << 15); }

static u8 spi1_xfer(u8 v)
{
    while (!(SPI1_SR & SPI_TXE))
        ;
    SPI1_DR = v;
    while (!(SPI1_SR & SPI_RXNE))
        ;
    return SPI1_DR;
}

static void spi1_init(void)
{
    RCC_AHB1ENR |= RCC_AHB1_GPIOAEN | RCC_AHB1_GPIOBEN | RCC_AHB1_GPIOCEN;
    RCC_APB2ENR |= RCC_APB2_SPI1EN;

    GPIOB_MODER   &= ~((3u<<6)|(3u<<8)|(3u<<10));
    GPIOB_MODER   |=  ((2u<<6)|(2u<<8)|(2u<<10));
    GPIOB_AFRL    &= ~((0xFu<<12)|(0xFu<<16)|(0xFu<<20));
    GPIOB_AFRL    |=  ((5u<<12)|(5u<<16)|(5u<<20));
    GPIOB_OSPEEDR |=  ((3u<<6)|(3u<<8)|(3u<<10));

    GPIOA_MODER &= ~(3u << 30);
    GPIOA_MODER |=  (1u << 30);
    cs_high();

    GPIOC_MODER &= ~(3u << 2);
    GPIOC_MODER |=  (1u << 2);
    GPIOC_BSRR   = (1u << 1);

    SPI1_CR1 = SPI_MSTR | SPI_SSM | SPI_SSI | SPI_BR_DIV8;
    SPI1_CR1 |= SPI_SPE;
}

static void eeprom_wait_ready(void)
{
    u8 sr;
    do {
        cs_low();
        spi1_xfer(EE_RDSR);
        sr = spi1_xfer(0xFF);
        cs_high();
    } while (sr & 0x01);
}

static void eeprom_wren(void)
{
    // M95M02 requires tSHSL >= 100ns between cs_high and next cs_low.
    // At 168MHz, back-to-back cs_high/cs_low is ~20ns - too fast.
    for (volatile int i = 0; i < 20; i++) ;
    cs_low();
    spi1_xfer(EE_WREN);
    cs_high();
    for (volatile int i = 0; i < 20; i++) ;
}

static void eeprom_unprotect(void)
{
    eeprom_wren();
    cs_low();
    spi1_xfer(EE_WRSR);
    spi1_xfer(0x00);
    cs_high();
    eeprom_wait_ready();
}

#if 0
static u8 eeprom_rdsr(void)
{
    cs_low();
    spi1_xfer(EE_RDSR);
    u8 sr = spi1_xfer(0xFF);
    cs_high();
    return sr;
}
#endif

void eeprom_read(u32 addr, u8 *buf, u32 len)
{
    cs_low();
    spi1_xfer(EE_READ);
    spi1_xfer((addr >> 16) & 0xFF);
    spi1_xfer((addr >> 8)  & 0xFF);
    spi1_xfer(addr & 0xFF);
    for (u32 i = 0; i < len; i++)
        buf[i] = spi1_xfer(0xFF);
    cs_high();
}

void eeprom_write_page(u32 addr, const u8 *buf, u32 len)
{
    u32 page_off = addr & (EEPROM_PAGE_SIZE - 1u);
    if (len == 0 || len > EEPROM_PAGE_SIZE || page_off + len > EEPROM_PAGE_SIZE)
        return;

    eeprom_wren();
    cs_low();
    spi1_xfer(EE_WRITE);
    spi1_xfer((addr >> 16) & 0xFF);
    spi1_xfer((addr >> 8)  & 0xFF);
    spi1_xfer(addr & 0xFF);
    for (u32 i = 0; i < len; i++)
        spi1_xfer(buf[i]);
    cs_high();
    eeprom_wait_ready();
}

void eeprom_write_buffer(u32 addr, const u8 *buf, u32 len)
{
    while (len) {
        u32 page_off = addr & (EEPROM_PAGE_SIZE - 1u);
        u32 space    = EEPROM_PAGE_SIZE - page_off;
        u32 n        = (len < space) ? len : space;
        eeprom_write_page(addr, buf, n);
        addr += n;
        buf  += n;
        len  -= n;
    }
}


// USART3 + DMA TX (DMA1 Stream 3 Channel 4)

static volatile u8 dma_tx_busy;

void DMA1_Stream3_IRQHandler(void)
{
    if (DMA1_LISR & DMA1_S3_TCIF) {
        DMA1_LIFCR = DMA1_S3_TCIF;
        DMA1_S3CR &= ~DMA_EN;
        dma_tx_busy = 0;
    }
}

static void usart3_init(u32 baud)
{
    RCC_AHB1ENR |= RCC_AHB1_GPIOBEN | RCC_AHB1_DMA1EN;
    RCC_APB1ENR |= RCC_APB1_USART3EN;

    GPIOB_MODER   &= ~((3u<<20) | (3u<<22));
    GPIOB_MODER   |=  ((2u<<20) | (2u<<22));
    GPIOB_AFRH    &= ~((0xFu<<8) | (0xFu<<12));
    GPIOB_AFRH    |=  ((7u<<8) | (7u<<12));
    GPIOB_OSPEEDR |=  ((3u<<20) | (3u<<22));
    GPIOB_PUPDR   &= ~((3u<<20) | (3u<<22));
    GPIOB_PUPDR   |=  (1u<<22);

    USART3_CR1 = 0;
    USART3_BRR = (PCLK1_HZ + baud / 2) / baud;
    USART3_CR3 = USART_DMAT;
    USART3_CR1 = USART_TE | USART_RE | USART_UE;

    DMA1_S3CR = 0;
    while (DMA1_S3CR & DMA_EN)
        ;
    DMA1_LIFCR = DMA1_S3_FLAGS_ALL;
    DMA1_S3PAR = 0x40004804;
    DMA1_S3CR  = DMA_CH4 | DMA_MINC | DMA_DIR_M2P | DMA_TCIE;

    nvic_set_priority(IRQn_DMA1_S3, 2);
    nvic_enable_irq(IRQn_DMA1_S3);
    dma_tx_busy = 0;
}

static void usart3_set_baud(u32 baud)
{
    while (!(USART3_SR & USART_TC))
        ;
    USART3_CR1 &= ~USART_UE;
    USART3_BRR = (PCLK1_HZ + baud / 2) / baud;
    USART3_CR1 &= ~USART_RE;
    USART3_CR1 |= USART_UE;
    (void)USART3_SR;
    (void)USART3_DR;
    USART3_CR1 |= USART_RE;
}

static void uart_dma_send(const u8 *data, u32 len)
{
    if (!len) return;
    while (dma_tx_busy)
        ;
    DMA1_LIFCR  = DMA1_S3_FLAGS_ALL;
    DMA1_S3M0AR = (u32)data;
    DMA1_S3NDTR = len;
    dma_tx_busy = 1;
    DMA1_S3CR  |= DMA_EN;
}

static void uart_dma_wait(void)
{
    while (dma_tx_busy)
        ;
    while (!(USART3_SR & USART_TC))
        ;
}

static int uart_getc_timeout(u8 *out, u32 timeout_ms)
{
    u32 start = millis();
    for (;;) {
        u32 sr = USART3_SR;
        if (sr & USART_RXNE) { *out = (u8)USART3_DR; return 1; }
        if (sr & USART_ERR_MASK) (void)USART3_DR;
        if ((u32)(millis() - start) >= timeout_ms) return 0;
    }
}

static void uart_drain_ms(u32 ms)
{
    u32 start = millis();
    while ((u32)(millis() - start) < ms) {
        while (USART3_SR & (USART_RXNE | USART_ERR_MASK))
            (void)USART3_DR;
    }
}


// Frame TX: [0x55] [TYPE] [LEN:2 BE] [payload] [CRC16:2 BE]

static u8 tx_buf[1 + 3 + MAX_FRAME_PAYLOAD + 2];

static void send_frame(u8 type, const u8 *payload, u16 len)
{
    uart_dma_wait();
    u8 *p = tx_buf;
    *p++ = PROTO_SYNC;
    *p++ = type;
    *p++ = (len >> 8) & 0xFF;
    *p++ = len & 0xFF;
    if (len && payload)
        memcpy(p, payload, len);
    p += len;
    u16 crc = crc16_ccitt(&tx_buf[1], 3 + len);
    *p++ = (crc >> 8) & 0xFF;
    *p++ = crc & 0xFF;
    uart_dma_send(tx_buf, (u32)(p - tx_buf));
}

void send_ack(void)                            { send_frame(RSP_ACK,  NULL, 0); }
void send_nack(u8 err)                         { send_frame(RSP_NACK, &err, 1); }
void send_data_frame(const u8 *data, u16 len)  { send_frame(RSP_DATA, data, len); }


static u8 rx_payload[MAX_FRAME_PAYLOAD];

static int handle_q_frame(void);  /* defined below, after command handlers */

static int recv_frame(u8 *cmd, u32 timeout_ms)
{
    u8 b;

    for (;;) {
        if (!uart_getc_timeout(&b, timeout_ms)) return -1;
        if (b == PROTO_SYNC) break;
    }

    u8 type;
    if (!uart_getc_timeout(&type, 50)) return -3;

    // simulate part of Resmed native ASCII protocol
    if (type == 'Q')
        return handle_q_frame();

    // Binary frame
    u8 lenbuf[2];
    if (!uart_getc_timeout(&lenbuf[0], 50)) return -3;
    if (!uart_getc_timeout(&lenbuf[1], 50)) return -3;

    *cmd = type;
    u16 len = ((u16)lenbuf[0] << 8) | lenbuf[1];
    if (len > MAX_FRAME_PAYLOAD) return -3;

    for (u16 i = 0; i < len; i++)
        if (!uart_getc_timeout(&rx_payload[i], 50)) return -3;

    u8 crc_raw[2];
    if (!uart_getc_timeout(&crc_raw[0], 50)) return -3;
    if (!uart_getc_timeout(&crc_raw[1], 50)) return -3;

    u16 crc_rx   = ((u16)crc_raw[0] << 8) | crc_raw[1];
    u8 hdr[3]    = { type, lenbuf[0], lenbuf[1] };
    u16 crc_calc = crc16_ccitt_update(0xFFFF, hdr, 3);
    crc_calc     = crc16_ccitt_update(crc_calc, rx_payload, len);

    return (crc_rx == crc_calc) ? (int)len : -3;
}


u16 fix_header_crc(u16 *old_crc)
{
    u8 hdr[HDR_LEN];
    eeprom_read(0, hdr, HDR_LEN);

    if (old_crc) {
        u8 lo, hi;
        eeprom_read(CRC_ADDR_LO, &lo, 1);
        eeprom_read(CRC_ADDR_HI, &hi, 1);
        *old_crc = (u16)lo | ((u16)hi << 8);
    }

    u16 crc = crc16_ccitt(hdr, HDR_LEN);
    u8 crc_le[2] = { crc & 0xFF, (crc >> 8) & 0xFF };
    eeprom_write_buffer(CRC_ADDR_LO, crc_le, 2);
    return crc;
}


static void cmd_ping(void)
{
    send_data_frame((const u8 *)FW_VERSION, sizeof(FW_VERSION) - 1);
}

static u8 ping_buf[2][EEPROM_PAGE_SIZE];

static void cmd_read(const u8 *pl, u16 plen)
{
    if (plen != 6) { send_nack(ERR_BAD_LEN); return; }

    u32 addr = ((u32)pl[0] << 16) | ((u32)pl[1] << 8) | pl[2];
    u32 len  = ((u32)pl[3] << 16) | ((u32)pl[4] << 8) | pl[5];

    if (!len || addr + len > EEPROM_SIZE) { send_nack(ERR_BAD_RANGE); return; }

    u8 ack_pl[3] = { (len >> 16) & 0xFF, (len >> 8) & 0xFF, len & 0xFF };
    send_frame(RSP_ACK, ack_pl, 3);
    uart_dma_wait();

    u16 crc = 0xFFFF;
    int cur = 0;
    u32 remaining = len;

    u32 chunk = (remaining > EEPROM_PAGE_SIZE) ? EEPROM_PAGE_SIZE : remaining;
    eeprom_read(addr, ping_buf[cur], chunk);

    while (remaining > 0) {
        u32 n = chunk;
        uart_dma_send(ping_buf[cur], n);
        crc = crc16_ccitt_update(crc, ping_buf[cur], n);
        remaining -= n;
        addr += n;

        if (remaining > 0) {
            int next = cur ^ 1;
            chunk = (remaining > EEPROM_PAGE_SIZE) ? EEPROM_PAGE_SIZE : remaining;
            eeprom_read(addr, ping_buf[next], chunk);
            cur = next;
        }
        uart_dma_wait();
    }

    u8 crc_tail[2] = { (crc >> 8) & 0xFF, crc & 0xFF };
    uart_dma_send(crc_tail, 2);
    uart_dma_wait();
}

static void cmd_write(const u8 *pl, u16 plen)
{
    if (plen < 4) { send_nack(ERR_BAD_LEN); return; }

    u32 addr     = ((u32)pl[0] << 16) | ((u32)pl[1] << 8) | pl[2];
    u16 data_len = plen - 3;
    const u8 *data = &pl[3];

    if (data_len > EEPROM_PAGE_SIZE)                    { send_nack(ERR_BAD_LEN);   return; }
    if (addr + data_len > EEPROM_SIZE)                  { send_nack(ERR_BAD_RANGE); return; }
    if ((addr & (EEPROM_PAGE_SIZE - 1)) + data_len > EEPROM_PAGE_SIZE)
                                                        { send_nack(ERR_BAD_RANGE); return; }

    eeprom_write_page(addr, data, data_len);

    u8 vfy[EEPROM_PAGE_SIZE];
    eeprom_read(addr, vfy, data_len);
    if (memcmp(vfy, data, data_len)) {
        // Report: [ERR_VERIFY] [first_mismatch_offset:2] [expected] [got] [data_len:2]
        u16 off = 0;
        for (u16 i = 0; i < data_len; i++) {
            if (vfy[i] != data[i]) { off = i; break; }
        }
        u8 detail[7] = {
            ERR_VERIFY,
            (off >> 8) & 0xFF, off & 0xFF,
            data[off], vfy[off],
            (data_len >> 8) & 0xFF, data_len & 0xFF
        };
        send_frame(RSP_NACK, detail, 7);
        return;
    }

    send_ack();
}

/*
 * Bulk write: streaming page writes with minimal per-page overhead.
 *
 * Initial frame payload: [addr_hi, addr_mid, addr_lo, count_hi, count_lo]
 *   addr  = start address (must be page-aligned)
 *   count = number of 256-byte pages
 *
 * After ACK, enters streaming mode:
 *   Host sends: [256B page data] [CRC16-hi] [CRC16-lo]  (258 raw bytes)
 *   FW responds: 0x06 (ACK) or error packet:
 *       [err_code] [page_hi] [page_lo] [off_hi] [off_lo] [expected] [got]
 *   Address auto-increments by PAGE_SIZE after each page.
 *   Host must wait for ACK before sending next page.
 *
 * On error, streaming stops. Host must re-enter with a new command.
 */
#define BULK_ACK       0x06
#define BULK_ERR_CRC   0x10
#define BULK_ERR_WRITE 0x11

static u8 bulk_page[EEPROM_PAGE_SIZE];
static u8 bulk_vfy[EEPROM_PAGE_SIZE];

static void cmd_write_bulk(const u8 *pl, u16 plen)
{
    if (plen != 5) { send_nack(ERR_BAD_LEN); return; }

    u32 addr  = ((u32)pl[0] << 16) | ((u32)pl[1] << 8) | pl[2];
    u16 count = ((u16)pl[3] << 8) | pl[4];

    if (addr & (EEPROM_PAGE_SIZE - 1))        { send_nack(ERR_BAD_RANGE); return; }
    if ((u32)addr + (u32)count * EEPROM_PAGE_SIZE > EEPROM_SIZE)
                                               { send_nack(ERR_BAD_RANGE); return; }

    send_ack();  // ready for streaming
    uart_dma_wait();

    static u8 bulk_resp[7];

    for (u16 p = 0; p < count; p++) {
        // raw page + CRC
        for (u16 i = 0; i < EEPROM_PAGE_SIZE; i++)
            if (!uart_getc_timeout(&bulk_page[i], 2000)) return;

        u8 crc_raw[2];
        if (!uart_getc_timeout(&crc_raw[0], 500)) return;
        if (!uart_getc_timeout(&crc_raw[1], 500)) return;

        u16 crc_rx = ((u16)crc_raw[0] << 8) | crc_raw[1];
        u16 crc_calc = crc16_ccitt(bulk_page, EEPROM_PAGE_SIZE);
        if (crc_rx != crc_calc) {
            bulk_resp[0] = BULK_ERR_CRC;
            bulk_resp[1] = (p >> 8); bulk_resp[2] = p & 0xFF;
            bulk_resp[3] = (crc_rx >> 8); bulk_resp[4] = crc_rx & 0xFF;
            bulk_resp[5] = (crc_calc >> 8); bulk_resp[6] = crc_calc & 0xFF;
            uart_dma_send(bulk_resp, 7);
            uart_dma_wait();
            return;
        }

        eeprom_write_page(addr, bulk_page, EEPROM_PAGE_SIZE);
        eeprom_read(addr, bulk_vfy, EEPROM_PAGE_SIZE);
        if (memcmp(bulk_vfy, bulk_page, EEPROM_PAGE_SIZE)) {
            u16 off = 0;
            for (u16 i = 0; i < EEPROM_PAGE_SIZE; i++) {
                if (bulk_vfy[i] != bulk_page[i]) { off = i; break; }
            }
            bulk_resp[0] = BULK_ERR_WRITE;
            bulk_resp[1] = (p >> 8); bulk_resp[2] = p & 0xFF;
            bulk_resp[3] = (off >> 8); bulk_resp[4] = off & 0xFF;
            bulk_resp[5] = bulk_page[off];
            bulk_resp[6] = bulk_vfy[off];
            uart_dma_send(bulk_resp, 7);
            uart_dma_wait();
            return;
        }

        bulk_resp[0] = BULK_ACK;
        uart_dma_send(bulk_resp, 1);
        uart_dma_wait();

        addr += EEPROM_PAGE_SIZE;
    }
}

static void cmd_erase(void)
{
    u8 page[EEPROM_PAGE_SIZE];
    memset(page, 0xFF, EEPROM_PAGE_SIZE);

    for (u32 a = 0; a < EEPROM_SIZE; a += EEPROM_PAGE_SIZE)
        eeprom_write_page(a, page, EEPROM_PAGE_SIZE);

    send_ack();
}

static void cmd_fix_crc_handler(void)
{
    u16 old;
    u16 new = fix_header_crc(&old);
    u8 resp[4] = { (old >> 8) & 0xFF, old & 0xFF, (new >> 8) & 0xFF, new & 0xFF };
    send_data_frame(resp, 4);
}

static const u32 valid_bauds[] = {
    9600, 19200, 38400, 57600, 115200,
    230400, 460800, 921600, 1000000, 2000000
};

static void cmd_set_baud(const u8 *pl, u16 plen)
{
    if (plen != 4) { send_nack(ERR_BAD_LEN); return; }

    u32 baud = ((u32)pl[0] << 24) | ((u32)pl[1] << 16) | ((u32)pl[2] << 8) | pl[3];

    int ok = 0;
    for (unsigned i = 0; i < sizeof(valid_bauds)/sizeof(valid_bauds[0]); i++)
        if (valid_bauds[i] == baud) { ok = 1; break; }
    if (!ok) { send_nack(ERR_BAD_BAUD); return; }

    send_ack();
    uart_dma_wait();

    u32 t = millis();
    while ((u32)(millis() - t) < 10)
        ;

    usart3_set_baud(baud);
    uart_drain_ms(50);
}

static void cmd_reset(void)
{
    send_ack();
    uart_dma_wait();

    u32 t = millis();
    while ((u32)(millis() - t) < 20)
        ;

    SCB_AIRCR = AIRCR_VECTKEY | AIRCR_SYSRESETREQ;
    for (;;);
}


/*
 * Resmed ASCII protocol
 *
 * Supported commands:
 *   P S #RES 0001  ->  reset into bootloader
 *   P S #RES 0003  ->  fast reset back to CDX
 *   P S #BLL 0001  ->  same as RES 0001, protocol compatibility
 *   G S #BID       ->  bootloader version (from BLX flash)
 *   G S #BLS       ->  bootloader state (always 0000 = CDX running)
 *   G S #CID       ->  CDX version (our SID tag)
 *   G S #SID       ->  same as CID, for compatibility
 */

static int hex_nibble(u8 c)
{
    if (c >= '0' && c <= '9') return c - '0';
    if (c >= 'A' && c <= 'F') return c - 'A' + 10;
    if (c >= 'a' && c <= 'f') return c - 'a' + 10;
    return -1;
}

static u8 nibble_hex(u8 n) { return n < 10 ? '0' + n : 'A' + n - 10; }

static void send_qr_frame(u8 type, const u8 *payload, u16 plen);

#define BID_FLASH_ADDR  ((const char *)0x08003F80)
#define BID_MAX_LEN     32

static u16 slen(const char *s)
{
    u16 n = 0;
    while (s[n]) n++;
    return n;
}

static void send_gs_response(const char *prefix, u16 pfx_len,
                             const char *value, u16 val_len)
{
    u8 resp[128];
    u16 n = 0;
    if ((u16)(pfx_len + 3 + val_len) > sizeof(resp))
        return;
    memcpy(resp, prefix, pfx_len);
    n = pfx_len;
    resp[n++] = ' ';
    resp[n++] = '=';
    resp[n++] = ' ';
    memcpy(resp + n, value, val_len);
    n += val_len;
    send_qr_frame('R', resp, n);
}

static void send_error_response(const char *prefix, u16 pfx_len,
                                const char *code, u16 code_len)
{
    u8 resp[128];
    u16 n = 0;
    if ((u16)(pfx_len + 3 + code_len) > sizeof(resp))
        return;
    memcpy(resp, prefix, pfx_len);
    n = pfx_len;
    resp[n++] = ' ';
    resp[n++] = '=';
    resp[n++] = ' ';
    memcpy(resp + n, code, code_len);
    n += code_len;
    send_qr_frame('E', resp, n);
}

static void send_qr_frame(u8 type, const u8 *payload, u16 plen)
{
    uart_dma_wait();
    u8 *p = tx_buf;
    *p++ = 0x55;
    *p++ = type;

    // Escape payload into tx_buf, compute body length
    u8 *body = p + 3;            // fill len later
    u16 blen = 0;
    for (u16 i = 0; i < plen; i++) {
        body[blen++] = payload[i];
        if (payload[i] == 0x55) body[blen++] = 0x55;
    }

    u16 total = 9 + blen;
    p[0] = nibble_hex((total >> 8) & 0xF);
    p[1] = nibble_hex((total >> 4) & 0xF);
    p[2] = nibble_hex(total & 0xF);
    p = body + blen;

    u16 crc = crc16_ccitt(tx_buf, 5 + blen);
    *p++ = nibble_hex((crc >> 12) & 0xF);
    *p++ = nibble_hex((crc >> 8) & 0xF);
    *p++ = nibble_hex((crc >> 4) & 0xF);
    *p++ = nibble_hex(crc & 0xF);

    uart_dma_send(tx_buf, (u32)(p - tx_buf));
}

static void bkp6r_write(u32 val)
{
    RCC_APB1ENR |= RCC_APB1_PWREN;
    PWR_CR |= PWR_CR_DBP;
    RTC_BKP6R = val;
}

static void reset_after_ack(void)
{
    uart_dma_wait();
    u32 t = millis();
    while ((u32)(millis() - t) < 20)
        ;
    SCB_AIRCR = AIRCR_VECTKEY | AIRCR_SYSRESETREQ;
    for (;;);
}

static int handle_q_frame(void)
{
    u8 lh[3];
    for (int i = 0; i < 3; i++)
        if (!uart_getc_timeout(&lh[i], 500)) return -2;

    int d0 = hex_nibble(lh[0]), d1 = hex_nibble(lh[1]), d2 = hex_nibble(lh[2]);
    if (d0 < 0 || d1 < 0 || d2 < 0) return -2;
    u16 total = (d0 << 8) | (d1 << 4) | d2;

    if (total < 9 || total > 500) return -2;
    u16 body_len = total - 9;

    u8 raw[500];
    for (u16 i = 0; i < body_len + 4; i++)
        if (!uart_getc_timeout(&raw[i], 500)) return -2;

    u8 hdr[5] = { 0x55, 'Q', lh[0], lh[1], lh[2] };
    u16 crc = crc16_ccitt_update(0xFFFF, hdr, 5);
    crc = crc16_ccitt_update(crc, raw, body_len);

    int c0 = hex_nibble(raw[body_len]);
    int c1 = hex_nibble(raw[body_len + 1]);
    int c2 = hex_nibble(raw[body_len + 2]);
    int c3 = hex_nibble(raw[body_len + 3]);
    if (c0 < 0 || c1 < 0 || c2 < 0 || c3 < 0) return -2;
    u16 crc_rx = (c0 << 12) | (c1 << 8) | (c2 << 4) | c3;
    if (crc != crc_rx) return -2;

    // unescape payload
    u8 pl[256];
    u16 plen = 0;
    for (u16 i = 0; i < body_len; i++) {
        pl[plen++] = raw[i];
        if (raw[i] == 0x55 && i + 1 < body_len && raw[i + 1] == 0x55)
            i++;
    }

    if (plen >= 13 && memcmp(pl, "P S #RES 0001", 13) == 0) {
        send_gs_response("P S #RES", 8, "0001", 4);
        reset_after_ack();
    }
    if (plen >= 13 && memcmp(pl, "P S #RES 0003", 13) == 0) {
        send_gs_response("P S #RES", 8, "0003", 4);
        bkp6r_write(BKP6R_FAST_BOOT);
        reset_after_ack();
    }
    if (plen >= 13 && memcmp(pl, "P S #BLL 0001", 13) == 0) {
        send_gs_response("P S #BLL", 8, "0001", 4);
        reset_after_ack();
    }

    // G S # queries
    if (plen >= 5 && memcmp(pl, "G S #", 5) == 0) {
        if (plen >= 8 && memcmp(pl + 5, "BID", 3) == 0) {
            const char *bid = BID_FLASH_ADDR;
            u16 blen = 0;
            while (blen < BID_MAX_LEN && bid[blen] && bid[blen] != (char)0xFF)
                blen++;
            send_gs_response("G S #BID", 8, bid, blen);
        }
        else if (plen >= 8 && memcmp(pl + 5, "CID", 3) == 0)
            send_gs_response("G S #CID", 8, g_sid_tag, slen(g_sid_tag));
        else if (plen >= 8 && memcmp(pl + 5, "SID", 3) == 0)
            send_gs_response("G S #SID", 8, g_sid_tag, slen(g_sid_tag));
        else if (plen >= 8 && memcmp(pl + 5, "RES", 3) == 0)
            send_gs_response("G S #RES", 8, "0000", 4);
        else if (plen >= 8 && memcmp(pl + 5, "BLL", 3) == 0)
            send_gs_response("G S #BLL", 8, "0000", 4);
        else if (plen >= 8 && memcmp(pl + 5, "BLS", 3) == 0)
            send_gs_response("G S #BLS", 8, "0000", 4);
        else {
            u16 pfx = (plen >= 8) ? 8 : plen;
            send_error_response((const char *)pl, pfx, "6006", 4);
        }
    }
    // P S # for unknown variables
    else if (plen >= 5 && memcmp(pl, "P S #", 5) == 0) {
        u16 pfx = (plen >= 8) ? 8 : plen;
        send_error_response((const char *)pl, pfx, "6006", 4);
    }

    return -2;
}


__attribute__((weak))
void dispatch_private(u8 cmd, const u8 *pl, u16 len)
{
    send_nack(ERR_BAD_CMD);
}

static void dispatch(u8 cmd, const u8 *pl, u16 len)
{
    switch (cmd) {
    case CMD_PING:     cmd_ping();                break;
    case CMD_READ:     cmd_read(pl, len);         break;
    case CMD_WRITE:    cmd_write(pl, len);        break;
    case CMD_WRITE_BULK: cmd_write_bulk(pl, len); break;
    case CMD_ERASE:    cmd_erase();               break;
    case CMD_FIX_CRC:  cmd_fix_crc_handler();     break;
    case CMD_SET_BAUD: cmd_set_baud(pl, len);     break;
    case CMD_RESET:    cmd_reset();               break;
    default:
        dispatch_private(cmd, pl, len);
        break;
    }
}


int main(void)
{
    ensure_pll();
    __asm volatile ("cpsie i");

    iwdg_extend_timeout_max();
    watchdog_timer_init();
    tim5_timebase_init();
    spi1_init();
    eeprom_unprotect();
    usart3_init(DEFAULT_BAUD);
    uart_drain_ms(100);

    for (;;) {
        u8 cmd = 0;
        int len = recv_frame(&cmd, 5000);
        if (len >= 0) {
            dispatch(cmd, rx_payload, (u16)len);
        } else if (len != -2) {
            // -1 = timeout, -3 = garbage ; reset to default baud
            usart3_set_baud(DEFAULT_BAUD);
            uart_drain_ms(50);
        }
    }
}

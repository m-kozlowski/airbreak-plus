#pragma once

typedef __UINT8_TYPE__   u8;
typedef __UINT16_TYPE__  u16;
typedef __UINT32_TYPE__  u32;
typedef __SIZE_TYPE__    usize;


typedef u8  uint8_t;
typedef u16 uint16_t;
typedef u32 uint32_t;
typedef usize size_t;

#define NULL ((void *)0)

#define REG(addr)  (*(volatile u32 *)(addr))
#define REG8(addr) (*(volatile u8  *)(addr))


#define DEFAULT_BAUD    57600u
#define FW_VERSION      "eeprom_stub 2.1"
#define FW_TAG          "EEP_T-0201"

// RCC
#define RCC_CR          REG(0x40023800)
#define RCC_PLLCFGR     REG(0x40023804)
#define RCC_CFGR        REG(0x40023808)
#define RCC_AHB1ENR     REG(0x40023830)
#define RCC_APB1ENR     REG(0x40023840)
#define RCC_APB2ENR     REG(0x40023844)

#define FLASH_ACR       REG(0x40023C00)

// GPIOA, CS = PA15
#define GPIOA_MODER     REG(0x40020000)
#define GPIOA_BSRR      REG(0x40020018)

// GPIOB, SPI1 PB3/4/5, USART3 PB10/11
#define GPIOB_MODER     REG(0x40020400)
#define GPIOB_OSPEEDR   REG(0x40020408)
#define GPIOB_PUPDR     REG(0x4002040C)
#define GPIOB_AFRL      REG(0x40020420)
#define GPIOB_AFRH      REG(0x40020424)

// GPIOC WP = PC1
#define GPIOC_MODER     REG(0x40020800)
#define GPIOC_BSRR      REG(0x40020818)

#define SPI1_CR1        REG(0x40013000)
#define SPI1_SR         REG(0x40013008)
#define SPI1_DR         REG8(0x4001300C)

#define USART3_SR       REG(0x40004800)
#define USART3_DR       REG(0x40004804)
#define USART3_BRR      REG(0x40004808)
#define USART3_CR1      REG(0x4000480C)
#define USART3_CR3      REG(0x40004814)

// DMA1 Stream 3 (USART3_TX, Channel 4)
#define DMA1_LISR       REG(0x40026000)
#define DMA1_LIFCR      REG(0x40026008)
#define DMA1_S3CR       REG(0x40026058)
#define DMA1_S3NDTR     REG(0x4002605C)
#define DMA1_S3PAR      REG(0x40026060)
#define DMA1_S3M0AR     REG(0x40026064)

// TIM2 (IWDG kicker)
#define TIM2_CR1        REG(0x40000000)
#define TIM2_DIER       REG(0x4000000C)
#define TIM2_SR         REG(0x40000010)
#define TIM2_EGR        REG(0x40000014)
#define TIM2_PSC        REG(0x40000028)
#define TIM2_ARR        REG(0x4000002C)

// TIM5 (timebase)
#define TIM5_CR1        REG(0x40000C00)
#define TIM5_EGR        REG(0x40000C14)
#define TIM5_CNT        REG(0x40000C24)
#define TIM5_PSC        REG(0x40000C28)
#define TIM5_ARR        REG(0x40000C2C)

#define IWDG_KR         REG(0x40003000)
#define IWDG_PR         REG(0x40003004)
#define IWDG_RLR        REG(0x40003008)
#define IWDG_SR         REG(0x4000300C)

#define SCB_VTOR        REG(0xE000ED08)
#define SCB_AIRCR       REG(0xE000ED0C)
#define SCB_CPACR       REG(0xE000ED88)

// PWR (for backup domain write access)
#define PWR_CR          REG(0x40007000)
#define PWR_CR_DBP      (1u << 8)
#define RCC_APB1_PWREN  (1u << 28)

// RTC backup registers
#define RTC_BKP6R       REG(0x40002868)
#define BKP6R_FAST_BOOT 0x1B183CA7u

#define NVIC_ISER(n)    REG(0xE000E100 + (n) * 4)
#define NVIC_IPR(n)     REG8(0xE000E400 + (n))


// RCC_CR
#define RCC_CR_HSEON        (1u << 16)
#define RCC_CR_HSERDY       (1u << 17)
#define RCC_CR_PLLON        (1u << 24)
#define RCC_CR_PLLRDY       (1u << 25)

// RCC_PLLCFGR
#define RCC_PLLCFGR_SRC_HSE (1u << 22)

// RCC_CFGR
#define RCC_CFGR_SW_PLL     (2u << 0)
#define RCC_CFGR_SWS_MASK   (3u << 2)
#define RCC_CFGR_SWS_PLL    (2u << 2)
#define RCC_CFGR_PPRE1_DIV4 (5u << 10)
#define RCC_CFGR_PPRE2_DIV2 (4u << 13)

// RCC clock enables
#define RCC_AHB1_GPIOAEN    (1u << 0)
#define RCC_AHB1_GPIOBEN    (1u << 1)
#define RCC_AHB1_GPIOCEN    (1u << 2)
#define RCC_AHB1_DMA1EN     (1u << 21)
#define RCC_APB1_TIM2EN     (1u << 0)
#define RCC_APB1_TIM5EN     (1u << 3)
#define RCC_APB1_USART3EN   (1u << 18)
#define RCC_APB2_SPI1EN     (1u << 12)

// FLASH_ACR
#define FLASH_ACR_LATENCY_5WS 5u
#define FLASH_ACR_PRFTEN    (1u << 8)
#define FLASH_ACR_ICEN      (1u << 9)
#define FLASH_ACR_DCEN      (1u << 10)

// SPI_CR1
#define SPI_MSTR            (1u << 2)
#define SPI_BR_DIV8         (1u << 4)
#define SPI_SPE             (1u << 6)
#define SPI_SSI             (1u << 8)
#define SPI_SSM             (1u << 9)

// SPI_SR
#define SPI_RXNE            (1u << 0)
#define SPI_TXE             (1u << 1)

// USART_SR
#define USART_PE            (1u << 0)
#define USART_FE            (1u << 1)
#define USART_NE            (1u << 2)
#define USART_ORE           (1u << 3)
#define USART_RXNE          (1u << 5)
#define USART_TC            (1u << 6)
#define USART_TXE           (1u << 7)
#define USART_ERR_MASK      (USART_PE | USART_FE | USART_NE | USART_ORE)

// USART_CR1
#define USART_RE            (1u << 2)
#define USART_TE            (1u << 3)
#define USART_UE            (1u << 13)

// USART_CR3
#define USART_DMAT          (1u << 7)

// DMA_SxCR
#define DMA_EN              (1u << 0)
#define DMA_TCIE            (1u << 4)
#define DMA_DIR_M2P         (1u << 6)
#define DMA_MINC            (1u << 10)
#define DMA_CH4             (4u << 25)

// DMA1 Stream 3 flags
#define DMA1_S3_TCIF        (1u << 27)
#define DMA1_S3_FLAGS_ALL   (0x3Du << 22)

// TIM bits
#define TIM_CEN             (1u << 0)
#define TIM_UIE             (1u << 0)
#define TIM_UG              (1u << 0)
#define TIM_UIF             (1u << 0)

// SCB_AIRCR
#define AIRCR_VECTKEY       (0x05FAu << 16)
#define AIRCR_SYSRESETREQ   (1u << 2)

// IRQ numbers
#define IRQn_DMA1_S3        14
#define IRQn_TIM2           28


static inline void nvic_enable_irq(int n)
{
    NVIC_ISER(n >> 5) = (1u << (n & 31));
}

static inline void nvic_set_priority(int n, u8 prio)
{
    NVIC_IPR(n) = (prio << 4);
}


#define PROTO_SYNC       0x55

#define CMD_PING         0x01
#define CMD_READ         0x02
#define CMD_WRITE        0x03
#define CMD_ERASE        0x04
#define CMD_FIX_CRC      0x05
#define CMD_SET_BAUD     0x06
#define CMD_RESET        0x07
#define CMD_WRITE_BULK   0x08

#define RSP_ACK          0x41
#define RSP_NACK         0x4E
#define RSP_DATA         0x44

#define ERR_BAD_CRC      0x01
#define ERR_BAD_CMD      0x02
#define ERR_BAD_RANGE    0x03
#define ERR_BAD_LEN      0x04
#define ERR_VERIFY       0x05
#define ERR_BAD_BAUD     0x06

#define CMD_PRIVATE_BASE 0x10
#define CMD_PRIVATE_MAX  0x1F

#define EEPROM_SIZE       (256u * 1024u)
#define EEPROM_PAGE_SIZE  256u
#define HDR_LEN           0x50
#define CRC_ADDR_LO       0x50
#define CRC_ADDR_HI       0x51

#define EE_WRITE          0x02
#define EE_READ           0x03
#define EE_WRSR           0x01
#define EE_RDSR           0x05
#define EE_WREN           0x06

#define MAX_FRAME_PAYLOAD 262u

// SYSCLK=168M, APB1=42M, APB1 timers=84M
#define PCLK1_HZ         42000000u
#define TIM_CLK_HZ       84000000u


u16 crc16_ccitt(const u8 *data, usize len);
u16 crc16_ccitt_update(u16 crc, const u8 *data, usize len);


void eeprom_read(u32 addr, u8 *buf, u32 len);
void eeprom_write_page(u32 addr, const u8 *buf, u32 len);
void eeprom_write_buffer(u32 addr, const u8 *buf, u32 len);
u16  fix_header_crc(u16 *old_crc);

void send_ack(void);
void send_nack(u8 err);
void send_data_frame(const u8 *data, u16 len);


void *memcpy(void *dst, const void *src, usize n);
void *memset(void *dst, int c, usize n);
int   memcmp(const void *a, const void *b, usize n);

// SPI NOR reader for Air11 / STM32H753.
//
// Built as a raw Thumb blob loaded at 0x24000000. OpenOCD sets:
//   r0 = NOR source address
//   r1 = byte count, max bounded by the OpenOCD SRAM buffer
//   r2 = destination RAM buffer
//
// The OpenOCD wrapper halts the target, masks interrupts, configures SPI5/GPIO,
// runs this stub, waits for BKPT, then dump_image's the RAM buffer.
// Build: make as11-nor-sram-reader
// Output: build/as11-nor-sram-reader.bin

#include <stdint.h>

#define REG32(addr) (*(volatile uint32_t *)(addr))

#define GPIOH_BSRR 0x58021C18u
#define IWDG1_KR   0x58004800u

#define SPI5_BASE  0x40015000u
#define SPI_CR1    (SPI5_BASE + 0x00u)
#define SPI_CR2    (SPI5_BASE + 0x04u)
#define SPI_SR     (SPI5_BASE + 0x14u)
#define SPI_IFCR   (SPI5_BASE + 0x18u)
#define SPI_TXDR   (SPI5_BASE + 0x20u)
#define SPI_RXDR   (SPI5_BASE + 0x30u)

#define SCB_DCCMVAC 0xE000EF68u
#define SPI_MAX_FRAMES 0xFFFCu
#define NOR_CMD_BYTES  4u

static inline void barrier(void);
static inline void feed_iwdg(void);
static void clean_dcache_range(uint8_t *ptr, uint32_t len);
static void read_transfer(uint32_t nor_addr, uint8_t *dst, uint32_t len);

void _start(uint32_t nor_addr, uint32_t len, uint8_t *dst) {
    uint8_t *out = dst;
    uint32_t done = 0u;

    feed_iwdg();

    while (done < len) {
        uint32_t n = len - done;
        if (n > (SPI_MAX_FRAMES - NOR_CMD_BYTES)) {
            n = SPI_MAX_FRAMES - NOR_CMD_BYTES;
        }

        read_transfer(nor_addr + done, out, n);
        clean_dcache_range(out, n);
        out += n;
        done += n;
        feed_iwdg();
    }

    feed_iwdg();

    __asm volatile ("bkpt #0xAB");
    for (;;) {
    }
}

static inline void barrier(void) {
    __asm volatile ("dsb 0xF\nisb 0xF" ::: "memory");
}

static inline void feed_iwdg(void) {
    REG32(IWDG1_KR) = 0x0000AAAAu;
}

static void clean_dcache_range(uint8_t *ptr, uint32_t len) {
    uintptr_t start = (uintptr_t)ptr & ~(uintptr_t)31u;
    uintptr_t end = ((uintptr_t)ptr + len + 31u) & ~(uintptr_t)31u;

    for (uintptr_t p = start; p < end; p += 32u) {
        REG32(SCB_DCCMVAC) = (uint32_t)p;
        if ((p & 0x7FFFu) == 0u) {
            feed_iwdg();
        }
    }
    barrier();
}

static void read_transfer(uint32_t nor_addr, uint8_t *dst, uint32_t len) {
    uint8_t *out = dst;
    uint32_t total_frames = len + 4u;
    uint32_t padded_frames = (total_frames + 3u) & ~3u;
    uint32_t total_words = padded_frames >> 2;
    uint32_t cmd_word =
        0x03u |
        (((nor_addr >> 16) & 0xFFu) << 8) |
        (((nor_addr >> 8) & 0xFFu) << 16) |
        ((nor_addr & 0xFFu) << 24);

    feed_iwdg();

    // CS low.
    REG32(GPIOH_BSRR) = 0x00200000u;

    REG32(SPI_CR1) = 0x00001000u;      // SSI high, SPE off.
    REG32(SPI_IFCR) = 0xFFFFFFFFu;
    REG32(SPI_CR2) = padded_frames;
    REG32(SPI_CR1) = 0x00001001u;      // SSI high, SPE on, CSTART off.

    for (uint32_t word_index = 0; word_index < total_words; word_index++) {
        uint32_t tx = (word_index == 0) ? cmd_word : 0u;

        if ((word_index & 0x3FFu) == 0u) {
            feed_iwdg();
        }

        while ((REG32(SPI_SR) & 0x00000002u) == 0u) {
        }
        REG32(SPI_TXDR) = tx;

        if (word_index == 0) {
            REG32(SPI_CR1) = 0x00001201u;  // Assert CSTART after first TX word.
        }

        while ((REG32(SPI_SR) & 0x00000001u) == 0u) {
        }
        uint32_t rx = REG32(SPI_RXDR);

        if (word_index != 0) {
            for (uint32_t j = 0; j < 4u && (uint32_t)(out - dst) < len; j++) {
                *out++ = (uint8_t)(rx >> (j * 8u));
            }
        }
    }

    while ((REG32(SPI_SR) & 0x00000008u) == 0u) {
    }

    REG32(SPI_IFCR) = 0xFFFFFFFFu;
    REG32(SPI_CR1) = 0x00001000u;

    // CS high.
    REG32(GPIOH_BSRR) = 0x00000020u;
}

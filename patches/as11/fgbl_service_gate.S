/*
 * Early FGBL service selector.
 *
 * The stock selector calls this before either the application jump or native
 * SRAM updater copy. PF13 is sampled as an active-low input with a temporary
 * pull-up. All touched GPIO/RCC state is restored before a stock tail-call.
 */

.syntax unified
.cpu cortex-m7
.thumb

.extern fgbl_copy_sram_updater_and_jump
.extern fgbl_jump_to_application
.extern fgbl_stock_request_magic
.extern fgbl_service_cookie
.extern fgbl_service_active

.equ RCC_AHB4ENR, 0x580244E0
.equ RCC_GPIOFEN, 0x20
.equ GPIOF_BASE, 0x58021400
.equ GPIO_MODER, 0x00
.equ GPIO_PUPDR, 0x0C
.equ GPIO_IDR, 0x10
.equ PF13_MODE_MASK, 0x0C000000
.equ PF13_PULL_UP, 0x04000000
.equ PF13_PIN, 0x00002000
.equ SERVICE_COOKIE, 0x43565253

.section .text.0.main, "ax", %progbits
.align 2
.global start
.type start, %function
.thumb_func
start:
    push    {r0-r3, r5-r7, lr}

    ldr     r0, =fgbl_service_cookie
    movs    r1, #0
    str     r1, [r0]
    ldr     r0, =fgbl_service_active
    str     r1, [r0]

    ldr     r5, =RCC_AHB4ENR
    ldr     r6, [r5]
    orr     r0, r6, #RCC_GPIOFEN
    str     r0, [r5]
    dsb

    ldr     r5, =GPIOF_BASE
    ldr     r7, [r5, #GPIO_MODER]
    ldr     r3, [r5, #GPIO_PUPDR]
    ldr     r2, =PF13_MODE_MASK
    bic     r0, r7, r2
    str     r0, [r5, #GPIO_MODER]
    bic     r0, r3, r2
    ldr     r1, =PF13_PULL_UP
    orr     r0, r0, r1
    str     r0, [r5, #GPIO_PUPDR]
    dsb
    movs    r1, #0xFF
.Lsettle_pull:
    subs    r1, r1, #1
    bne     .Lsettle_pull
    ldr     r0, [r5, #GPIO_IDR]
    ldr     r1, [r5, #GPIO_IDR]
    orr     r0, r0, r1
    ldr     r2, =PF13_PIN
    tst     r0, r2

    str     r3, [r5, #GPIO_PUPDR]
    str     r7, [r5, #GPIO_MODER]
    dsb
    ldr     r5, =RCC_AHB4ENR
    str     r6, [r5]
    dsb
    bne     .Lstock_selector

    ldr     r0, =fgbl_service_cookie
    ldr     r1, =SERVICE_COOKIE
    str     r1, [r0]
    dsb
    pop     {r0-r3, r5-r7, lr}
    mov     r0, sp
    b.w     fgbl_copy_sram_updater_and_jump

.Lstock_selector:
    /* PF13 released: preserve the stock APP-vs-updater decision. */
    pop     {r0-r3, r5-r7, lr}
    ldr     r0, =fgbl_stock_request_magic
    ldr     r0, [r0]
    cmp     r4, r0
    bne     .Lstock_updater
    b.w     fgbl_jump_to_application

.Lstock_updater:
    mov     r0, sp
    b.w     fgbl_copy_sram_updater_and_jump

.size start, . - start

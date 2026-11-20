.syntax unified
.thumb

.section .rodata.humid_start_abi, "a", %progbits
.align 1

/* Minimum tube temperature in whole degC, written by the patcher from
 * --humid-start-min-tube; 16 is the lowest tube setting.
 */
.global humid_start_min_tube_c
.type humid_start_min_tube_c, %object
humid_start_min_tube_c:
    .short 16
.size humid_start_min_tube_c, . - humid_start_min_tube_c

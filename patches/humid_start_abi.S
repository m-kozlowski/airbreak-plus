.syntax unified
.thumb

.section .rodata.humid_start_abi, "a", %progbits
.align 1

/* Custom-settings variable for the on/off switch; 0xffff keeps the feature
 * on.
 */
.global humid_start_enable_var_id
.type humid_start_enable_var_id, %object
humid_start_enable_var_id:
    .short 0xffff
.size humid_start_enable_var_id, . - humid_start_enable_var_id

/* Minimum tube temperature in whole degC, written by the patcher from
 * --humid-start-min-tube; 16 is the lowest tube setting.
 */
.global humid_start_min_tube_c
.type humid_start_min_tube_c, %object
humid_start_min_tube_c:
    .short 16
.size humid_start_min_tube_c, . - humid_start_min_tube_c

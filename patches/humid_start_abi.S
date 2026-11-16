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

/* Custom-settings variable for the minimum tube temperature (raw = whole
 * degC); 0xffff uses the lowest tube setting.
 */
.global humid_start_min_tube_var_id
.type humid_start_min_tube_var_id, %object
humid_start_min_tube_var_id:
    .short 0xffff
.size humid_start_min_tube_var_id, . - humid_start_min_tube_var_id

/* Custom-settings variable for the plate coupling (raw = coupling * 100);
 * 0xffff uses HUMIDITY_PLATE_COUPLING (humidity_model.h).
 */
.global humid_start_coupling_var_id
.type humid_start_coupling_var_id, %object
humid_start_coupling_var_id:
    .short 0xffff
.size humid_start_coupling_var_id, . - humid_start_coupling_var_id

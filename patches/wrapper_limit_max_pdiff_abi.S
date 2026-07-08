.syntax unified
.thumb

.section .rodata.wrapper_limit_max_pdiff_abi, "a", %progbits

/* ABI slots patched by patch-airsense when custom settings claim vars.
 * 0xffff means the wrapper uses its built-in default for that setting.
 */
.global wrapper_limit_max_pdiff_toggle_var_id
.type wrapper_limit_max_pdiff_toggle_var_id, %object
wrapper_limit_max_pdiff_toggle_var_id:
	.short 0xffff
	.short 0xffff

.global wrapper_limit_max_pdiff_triggercycle_var_id
.type wrapper_limit_max_pdiff_triggercycle_var_id, %object
wrapper_limit_max_pdiff_triggercycle_var_id:
	.short 0xffff
	.short 0xffff

.global wrapper_limit_max_pdiff_asv_max_var_id
.type wrapper_limit_max_pdiff_asv_max_var_id, %object
wrapper_limit_max_pdiff_asv_max_var_id:
	.short 0xffff
	.short 0xffff

.global wrapper_limit_max_pdiff_asv_sens_var_id
.type wrapper_limit_max_pdiff_asv_sens_var_id, %object
wrapper_limit_max_pdiff_asv_sens_var_id:
	.short 0xffff
	.short 0xffff

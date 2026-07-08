.syntax unified
.thumb

.section .rodata.wrapper_limit_max_pdiff_abi, "a", %progbits

/* ABI slot patched by patch-airsense when custom settings claim a toggle var.
 * 0xffff means there is no runtime toggle and custom ASV stays enabled.
 */
.global wrapper_limit_max_pdiff_toggle_var_id
.type wrapper_limit_max_pdiff_toggle_var_id, %object
wrapper_limit_max_pdiff_toggle_var_id:
	.short 0xffff
	.short 0xffff

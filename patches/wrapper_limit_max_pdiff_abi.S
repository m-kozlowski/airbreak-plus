.syntax unified
.thumb

.section .rodata.wrapper_limit_max_pdiff_abi, "a", %progbits

/* ABI slot patched by patch-airsense after wrapper injection. The wrapper code
 * reads this as the g[8] toggle var_id for enabling custom ASV behavior.
 */
.global wrapper_limit_max_pdiff_toggle_var_id
.type wrapper_limit_max_pdiff_toggle_var_id, %object
wrapper_limit_max_pdiff_toggle_var_id:
	.short 0xffff
	.short 0xffff

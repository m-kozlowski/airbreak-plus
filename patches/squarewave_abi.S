.syntax unified
.thumb

.section .rodata.squarewave_abi, "a", %progbits

/* Patched by patch-airsense when custom settings claim a switch var.
 * 0xffff keeps legacy behavior: squarewave is always enabled.
 */
.global squarewave_enable_var_id
.type squarewave_enable_var_id, %object
squarewave_enable_var_id:
	.short 0xffff
	.short 0xffff

/* Original stock method pointer replaced by patch_code_squarewave.
 * Used when the runtime switch is Off.
 */
.global squarewave_original_handler
.type squarewave_original_handler, %object
squarewave_original_handler:
	.word 0xffffffff

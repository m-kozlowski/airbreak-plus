.syntax unified
.thumb

.section .rodata.graph_abi, "a", %progbits
.align 2

/* 0xffff keeps the graph enabled when no custom setting is assigned. */
.global graph_enable_var_id
.type graph_enable_var_id, %object
graph_enable_var_id:
	.short 0xffff
	.short 0xffff

/* Original stock widget methods replaced by patch_code_graph. */
.global graph_draw_original
.type graph_draw_original, %object
graph_draw_original:
	.word 0xffffffff

.global graph_update_original
.type graph_update_original, %object
graph_update_original:
	.word 0xffffffff

.global graph_header_update_original
.type graph_header_update_original, %object
graph_header_update_original:
	.word 0xffffffff

.global graph_numbers_update_original
.type graph_numbers_update_original, %object
graph_numbers_update_original:
	.word 0xffffffff

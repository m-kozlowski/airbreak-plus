.syntax unified
.thumb

.section .rodata.graph_abi, "a", %progbits
.align 2

/* Original widget methods called by the therapy-screen graph wrappers. */
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

.global graph_simple_draw_original
graph_simple_draw_original:
	.word 0xffffffff
.global graph_simple_update_original
graph_simple_update_original:
	.word 0xffffffff

.syntax unified
.thumb

.section .rodata.graph_abi, "a", %progbits
.align 2

/* Original stock widget update methods replaced by patch_code_graph. */
.global graph_header_update_original
.type graph_header_update_original, %object
graph_header_update_original:
	.word 0xffffffff

.global graph_numbers_update_original
.type graph_numbers_update_original, %object
graph_numbers_update_original:
	.word 0xffffffff

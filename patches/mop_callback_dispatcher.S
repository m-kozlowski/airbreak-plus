.syntax unified
.thumb

.section .text, "ax", %progbits

/* Owns callback_table[MOP.callback_id]. The patcher writes the stock callback
 * followed by feature handlers into mop_callback_handler_table, terminated by
 * 0xffffffff.
 */
.global start
.type start, %function
.thumb_func
start:
	push {r4, lr}
	adr r4, mop_callback_handler_table
1:
	ldr r3, [r4], #4
	adds r2, r3, #1
	beq 2f
	cbz r3, 2f
	blx r3
	b 1b
2:
	pop {r4, pc}

.balign 4
.global mop_callback_handler_table
.type mop_callback_handler_table, %object
mop_callback_handler_table:
	.word 0xffffffff
	.word 0xffffffff
	.word 0xffffffff
	.word 0xffffffff
	.word 0xffffffff
	.word 0xffffffff

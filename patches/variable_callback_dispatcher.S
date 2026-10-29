.syntax unified
.thumb

.section .text, "ax", %progbits

/* Each copied thunk supplies its own flash-resident handler list in r0.
 * Firmware callbacks take no arguments. Keep the list cursor in a callee-saved
 * register so callbacks may invoke other callback chains without shared state.
 */
.global start
.type start, %function
.thumb_func
start:
	push {r4, lr}
	mov r4, r0
1:
	ldr r3, [r4], #4
	cbz r3, 2f
	blx r3
	b 1b
2:
	pop {r4, pc}
.size start, .-start

/* The patcher copies this position-independent adapter beside each handler
 * list. Only its list pointer changes; the dispatcher address is linked by
 * the normal payload build. Both literal loads stay local to the copy.
 */
.balign 4
.global variable_callback_thunk
.type variable_callback_thunk, %function
.thumb_func
variable_callback_thunk:
	ldr r0, variable_callback_thunk_handlers
	ldr r3, 3f
	bx r3
	.balign 4
.global variable_callback_thunk_handlers
variable_callback_thunk_handlers:
	.word 0xffffffff
3:
	.word start
.size variable_callback_thunk, .-variable_callback_thunk

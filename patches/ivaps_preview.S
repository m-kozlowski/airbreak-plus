.syntax unified
.thumb
.text

/* The extra stack words hold a candidate value and an entry selector. The stock
 * body keeps its local offsets; its patched epilogue releases both words.
 */
.macro calculator name, frame, saved
.balign 4
.global ivaps_stock_\name
.type ivaps_stock_\name, %function
.thumb_func
ivaps_stock_\name:
	movs r3, #0
	b enter_\name

.global ivaps_preview_\name
.type ivaps_preview_\name, %function
.thumb_func
ivaps_preview_\name:
	movs r3, #1
	b enter_\name

.global ivaps_preview_\name\()_rate
.type ivaps_preview_\name\()_rate, %function
.thumb_func
ivaps_preview_\name\()_rate:
	movs r3, #2
	b enter_\name

.global ivaps_preview_\name\()_height
.type ivaps_preview_\name\()_height, %function
.thumb_func
ivaps_preview_\name\()_height:
	movs r3, #3
	b enter_\name

.global ivaps_preview_\name\()_inches
.type ivaps_preview_\name\()_inches, %function
.thumb_func
ivaps_preview_\name\()_inches:
	movs r3, #4
enter_\name:
	push.w {\saved, lr}
	sub sp, #(\frame + 8)
	cmp r3, #3
	blo ready_\name
	ldr r1, =ivaps_height_inputs
	ldr r2, [r1]
	adds r2, #1
	beq stock_\name
	cmp r3, #4
	bne ready_\name
	bl prepare_inches
	b ready_\name
stock_\name:
	movs r3, #0
ready_\name:
	str r0, [sp, #\frame]
	str r3, [sp, #(\frame + 4)]
	ldr ip, =ivaps_calculate_\name + 6
	bx ip
.ltorg
.endm

calculator mv, 0xe0, r4-r10
calculator vt, 0xe0, r4-r10
calculator vk, 0x12c, r4-r11

/* The two outlined native readers also set up their handler address; one
 * preserves the preceding result in r5 before reading Pt Rate.
 */
.macro reader name, field, frame, selector, handler=-1, save=0
.global ivaps_read_\name\()_\field
.type ivaps_read_\name\()_\field, %function
.thumb_func
ivaps_read_\name\()_\field:
.if \save
	mov r5, r0
.endif
.if \handler >= 0
	add r0, sp, #\handler
.endif
	ldr r3, [sp, #(\frame + 4)]
	cmp r3, #\selector
	bne native_read
	ldr r0, [sp, #\frame]
.ifc \field,deadspace
	ldr r1, =ivaps_height_inputs
	ldrh r1, [r1, #4]
	ldr ip, =ivaps_height_deadspace
	bx ip
.else
	bx lr
.endif
.endm

reader mv, va, 0xe0, 1
reader mv, rate, 0xe0, 2
reader mv, deadspace, 0xe0, 3, 0xa8
reader vt, va, 0xe0, 1
reader vt, rate, 0xe0, 2
reader vt, deadspace, 0xe0, 3, 0xa8
reader vk, va, 0x12c, 1
reader vk, rate_saved, 0x12c, 2, 0x10, 1
reader vk, rate, 0x12c, 2, 0x10
reader vk, deadspace, 0x12c, 3
reader vk, height, 0x12c, 3

.thumb_func
native_read:
	ldr ip, =g4_numeric_get_value
	bx ip

.thumb_func
prepare_inches:
	push {r4, lr}
	mov r4, r0
	ldrh r0, [r1, #6]
	bl variable_get_by_id
	cmp r0, r4
	beq saved_inches
	mov r0, r4
	ldr r1, =ivaps_height_inputs
	ldrh r2, [r1]
	ldrh r1, [r1, #2]
	bl ivaps_height_inches_to_cm
	movs r3, #3
	pop {r4, pc}
saved_inches:
	/* Rounding to inches loses information: keep the saved centimetres on undo. */
	movs r3, #0
	pop {r4, pc}
.ltorg

.balign 4
.global ivaps_height_inputs
.type ivaps_height_inputs, %object
ivaps_height_inputs:
	.short 0xffff, 0xffff, 0xffff, 0xffff
.size ivaps_height_inputs, .-ivaps_height_inputs

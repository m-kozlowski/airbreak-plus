.syntax unified
.thumb
.section .text, "ax", %progbits

.global therapy_screen_construct
.type therapy_screen_construct, %function
.thumb_func
therapy_screen_construct:
    push.w {r4-r8, lr}
    sub sp, #24
    mov r6, r0
    cmp r1, #0
    ite eq
    ldreq ip, =gui_therapy_simple_body
    ldrne ip, =gui_therapy_bar_body
    bx ip

.global therapy_screen_construct_finish
.type therapy_screen_construct_finish, %function
.thumb_func
therapy_screen_construct_finish:
    bl scrollbar_add_item
    mov r0, r4
    add sp, #24
    pop.w {r4-r8, pc}

.global therapy_screen_boot
.type therapy_screen_boot, %function
.thumb_func
therapy_screen_boot:
    mov r0, r6
    bl start
    str r0, [r5, #0x60]
    movs r0, #0
    str r0, [r5, #0x5c]
    ldr ip, =gui_therapy_data_body
    bx ip

.global therapy_screen_update_hook
.type therapy_screen_update_hook, %function
.thumb_func
therapy_screen_update_hook:
    /* r6 is the dialog update result at the native GUI-loop callsite. */
    mov r3, r6
    b.w therapy_screen_update
.ltorg

.section .rodata.therapy_screen_abi, "a", %progbits
.balign 4
.global therapy_screen_var_id
therapy_screen_var_id: .short 0xffff
.global therapy_screen_simple_modes
therapy_screen_simple_modes: .short 0
.global therapy_screen_indirect_pages
therapy_screen_indirect_pages: .byte 0
.balign 4, 0xff

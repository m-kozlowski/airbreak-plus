.syntax unified
.thumb
.section .text

/* The caller keeps the menu pointer in r4. */
.global learn_targets_page_hook
.type learn_targets_page_hook,%function
.thumb_func
learn_targets_page_hook:
    mov r1,r4
    b.w learn_targets_select

/* Replaces ldrb.w r1,[r0,#0x20] in the default-page action. */
.global learn_targets_default_hook
.type learn_targets_default_hook,%function
.thumb_func
learn_targets_default_hook:
    push {r0,lr}
    bl learn_targets_default
    mov r1,r0
    pop {r0,pc}

.section .rodata
.global learn_targets_page, learn_targets_results_page, learn_targets_prompt_index
.type learn_targets_page,%object
learn_targets_page:
    .byte 0xff
.size learn_targets_page, .-learn_targets_page
.type learn_targets_results_page,%object
learn_targets_results_page:
    .byte 0xff
.size learn_targets_results_page, .-learn_targets_results_page
.type learn_targets_prompt_index,%object
learn_targets_prompt_index:
    .hword 0xffff
.size learn_targets_prompt_index, .-learn_targets_prompt_index

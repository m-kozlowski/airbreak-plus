.syntax unified
.thumb
.fpu fpv4-sp-d16
.section .text

/* Interior hooks preserve the interrupted code's caller-saved integer/FPU
 * registers and both flag registers. Frame is 96 bytes, aligned to 8. */
.macro save_live
    push {r0-r3,r12,lr}
    vpush {s0-s15}
    sub sp,sp,#8
    mrs r0,APSR
    str r0,[sp]
    vmrs r0,FPSCR
    str r0,[sp,#4]
.endm
.macro restore_live
    ldr r0,[sp,#4]
    vmsr FPSCR,r0
    ldr r0,[sp]
    msr APSR_nzcvq,r0
    add sp,sp,#8
    vpop {s0-s15}
    pop {r0-r3,r12,lr}
.endm
.macro function name
    .global \name
    .type \name,%function
    .thumb_func
\name:
.endm
.macro endfunction name
    .size \name,.-\name
.endm

function autoepap_normalization_hook
    save_live
    bl autoepap_on
    cmp r0,#0
    ite ne
    vmovne.f32 s2,#1.0
    vmoveq.f32 s2,#3.0
    vstr s2,[sp,#16]
    restore_live
    b.w autoepap_normalization_resume
endfunction autoepap_normalization_hook

function autoepap_phase_reset_hook
    save_live
    bl autoepap_on
    cmp r0,#0
    ite ne
    movne r1,#0
    moveq r1,#2
    str r1,[sp,#76]
    restore_live
    b.w autoepap_phase_reset_resume
endfunction autoepap_phase_reset_hook

/* Patch the VCMP at A24FC, not BPL at A2504: A2506 is another branch target. */
function autoepap_leak_boundary_hook
    save_live
    bl autoepap_on
    cmp r0,#0
    beq 1f
    restore_live
    vcmp.f32 s0,s2
    vmrs APSR_nzcv,FPSCR
    bgt.w autoepap_leak_reject
    b.w autoepap_leak_accept
1:
    restore_live
    vcmp.f32 s0,s2
    vmrs APSR_nzcv,FPSCR
    bpl.w autoepap_leak_reject
    b.w autoepap_leak_accept
endfunction autoepap_leak_boundary_hook

function autoepap_timing_gate_hook
    save_live
    bl autoepap_on
    cmp r0,#0
    beq 1f
    restore_live
    b.w autoepap_timing_measure
1:
    restore_live
    cmp r1,#6
    beq.w autoepap_timing_target
    b.w autoepap_timing_measure
endfunction autoepap_timing_gate_hook

function autoepap_timing_tail_hook
    save_live
    add r0,sp,#96
    bl autoepap_timing_tail
    cmp r0,#0
    beq 1f
    restore_live
    b.w autoepap_timing_cleanup
1:
    restore_live
    vldr s0,[sp,#4]
    b.w autoepap_timing_tail_resume
endfunction autoepap_timing_tail_hook

function autoepap_landmark_ref_hook
    mov r2,r4
    b.w autoepap_landmark_ref
endfunction autoepap_landmark_ref_hook

function autoepap_leak_ref_hook
    movs r2,#0x20
    b.w autoepap_flow_ref_hook
endfunction autoepap_leak_ref_hook
function autoepap_ibr_ref_hook
    movs r2,#0x46
    b.w autoepap_flow_ref_hook
endfunction autoepap_ibr_ref_hook
function autoepap_flow_ref_hook
    push {r4,lr}
    vpush {s0-s15}
    bl autoepap_flow_ref_impl
    vpop {s0-s15}
    pop {r4,pc}
endfunction autoepap_flow_ref_hook

function autoepap_epap_ref_hook
    save_live
    ldr r0,[sp,#72]
    ldr r1,[sp,#76]
    bl autoepap_epap_ref
    restore_live
    bx lr
endfunction autoepap_epap_ref_hook

/* Patcher-owned settings and optional Fall Time provider. Unassigned settings
 * leave AutoEPAP disabled; an absent provider keeps the stock fall duration.
 */
.section .rodata
.balign 4
.global autoepap_effective_fall
.type autoepap_effective_fall,%object
autoepap_effective_fall:
    .word 0xffffffff
.size autoepap_effective_fall,4
.global autoepap_enable_id, autoepap_lower_id, autoepap_upper_id
.type autoepap_enable_id,%object
autoepap_enable_id:
    .hword 0xffff
.size autoepap_enable_id,2
.type autoepap_lower_id,%object
autoepap_lower_id:
    .hword 0xffff
.size autoepap_lower_id,2
.type autoepap_upper_id,%object
autoepap_upper_id:
    .hword 0xffff
.size autoepap_upper_id,2

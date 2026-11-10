.syntax unified
.thumb
.fpu fpv4-sp-d16

/* Each hook replaces VCMP + VMRS, leaving the stock BPL and all surrounding
 * arming/timing checks intact. The C callback returns -1 for the stock result,
 * 0 to hold, or 1 to switch (N=1). Preserve live caller-saved registers, FPSCR
 * and the caller's Q bit; the 96-byte save area keeps the stack 8-byte aligned.
 */
.section .text.tc_hooks, "ax", %progbits
.macro tc_compare name, left, right, cycle
.global \name
.type \name, %function
.thumb_func
\name:
    vcmp.f32 \left, \right
    push {r0-r3, r12, lr}
    vpush {s0-s15}
    vmrs r2, fpscr
    mrs r3, apsr
    push {r2, r3}
    movs r0, #\cycle
    bl custom_tc_decision
    cmp r0, #0
    blt 1f
    lsl.w r1, r0, #31
    b 2f
1:
    ldr r1, [sp]
    and r1, r1, #0xf0000000
2:
    pop {r2, r3}
    vmsr fpscr, r2
    and r3, r3, #0x08000000
    orr r1, r1, r3
    vpop {s0-s15}
    msr apsr_nzcvq, r1
    pop {r0-r3, r12, pc}
.size \name, .-\name
.endm

tc_compare custom_tc_timing_trigger, s0, s16, 0
tc_compare custom_tc_timing_cycle, s16, s0, 1
tc_compare custom_tc_progress_trigger, s0, s1, 0
tc_compare custom_tc_progress_cycle, s1, s0, 1

.section .rodata.wrapper_limit_max_pdiff_abi, "a", %progbits

/* ABI slots patched by patch-airsense when custom settings claim vars.
 * 0xffff means the wrapper uses its built-in default for that setting.
 */
.global wrapper_limit_max_pdiff_toggle_var_id
.type wrapper_limit_max_pdiff_toggle_var_id, %object
wrapper_limit_max_pdiff_toggle_var_id:
	.short 0xffff
	.short 0xffff

.global wrapper_limit_max_pdiff_triggercycle_var_id
.type wrapper_limit_max_pdiff_triggercycle_var_id, %object
wrapper_limit_max_pdiff_triggercycle_var_id:
	.short 0xffff
	.short 0xffff

.global wrapper_limit_max_pdiff_asv_max_var_id
.type wrapper_limit_max_pdiff_asv_max_var_id, %object
wrapper_limit_max_pdiff_asv_max_var_id:
	.short 0xffff
	.short 0xffff

.global wrapper_limit_max_pdiff_asv_sens_var_id
.type wrapper_limit_max_pdiff_asv_sens_var_id, %object
wrapper_limit_max_pdiff_asv_sens_var_id:
	.short 0xffff
	.short 0xffff

.global wrapper_limit_max_pdiff_eps_var_id
.type wrapper_limit_max_pdiff_eps_var_id, %object
wrapper_limit_max_pdiff_eps_var_id:
	.short 0xffff
	.short 0xffff

.global wrapper_limit_max_pdiff_exhale_shape_var_id
.type wrapper_limit_max_pdiff_exhale_shape_var_id, %object
wrapper_limit_max_pdiff_exhale_shape_var_id:
	.short 0xffff
	.short 0xffff

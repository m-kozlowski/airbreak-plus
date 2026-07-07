.syntax unified
.thumb

.section .text, "ax", %progbits

.extern custom_menu_hook_common

/* The patcher replaces one stock append call at the tail of each clinical-menu
 * section with a branch to one of these thunks. The original call ABI already
 * has r0=list and r1=item; the thunk only adds r2=section id before tail-calling
 * the shared C implementation.
 */

.global custom_menu_hook_therapy
.type custom_menu_hook_therapy, %function
.thumb_func
custom_menu_hook_therapy:
	movs r2, #0
	b.n custom_menu_hook_common

.global custom_menu_hook_comfort
.type custom_menu_hook_comfort, %function
.thumb_func
custom_menu_hook_comfort:
	movs r2, #1
	b.n custom_menu_hook_common

.global custom_menu_hook_accessories
.type custom_menu_hook_accessories, %function
.thumb_func
custom_menu_hook_accessories:
	movs r2, #2
	b.n custom_menu_hook_common

.global custom_menu_hook_options
.type custom_menu_hook_options, %function
.thumb_func
custom_menu_hook_options:
	movs r2, #3
	b.n custom_menu_hook_common

.global custom_menu_hook_configuration
.type custom_menu_hook_configuration, %function
.thumb_func
custom_menu_hook_configuration:
	movs r2, #4
	b.n custom_menu_hook_common

/* Patched by patch-airsense after the payload is copied into CCX. The default
 * erased value keeps the C side in no-registry mode if the slot is not patched.
 */
.global custom_menu_registry_addr
.type custom_menu_registry_addr, %object
custom_menu_registry_addr:
	.word 0xffffffff

/* Patched with the firmware var_id of MOP. Runtime visibility uses the current
 * mode value as a bit index into each registry entry's mode_mask.
 */
.global custom_menu_mode_var_id
.type custom_menu_mode_var_id, %object
custom_menu_mode_var_id:
	.short 0xffff

.global custom_menu_reserved
.type custom_menu_reserved, %object
custom_menu_reserved:
	.short 0xffff

/* Original callback_table[MOP.callback_id] Thumb pointer, saved by patcher
 * before the table entry is replaced by custom_menu_mop_callback_hook.
 */
.balign 4
.global custom_menu_original_mop_callback
.type custom_menu_original_mop_callback, %object
custom_menu_original_mop_callback:
	.word 0xffffffff

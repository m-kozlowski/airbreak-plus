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

/* Patched with the globals[16] index of the renamed CSG storage group. */
.global custom_settings_group_index
.type custom_settings_group_index, %object
custom_settings_group_index:
	.byte 0xff
	.balign 4, 0xff

/* Patched by patch-airsense after the payload is copied into CCX. The default
 * erased value keeps the C side in no-registry mode if the slot is not patched.
 */
.global custom_menu_registry_addr
.type custom_menu_registry_addr, %object
custom_menu_registry_addr:
	.word 0xffffffff

/* Stock page-table metadata recovered by the patcher from the verified menu
 * controller and Reminders page constructor before those sites are changed.
 */
.global custom_menu_stock_page_count
.type custom_menu_stock_page_count, %object
custom_menu_stock_page_count:
	.byte 0xff

.global custom_menu_clinical_page_id
.type custom_menu_clinical_page_id, %object
custom_menu_clinical_page_id:
	.byte 0xff

.global custom_menu_back_str_id
.type custom_menu_back_str_id, %object
custom_menu_back_str_id:
	.short 0xffff

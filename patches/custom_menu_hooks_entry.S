.syntax unified
.thumb

.section .text, "ax", %progbits

.extern custom_menu_hook_common

/* All selected stock append calls use this adapter. Keep r0=list, r1=item and
 * pass the original return PC in r2 to identify the callsite. The tail branch
 * preserves LR and stack alignment for the C implementation's normal prologue.
 */

.global custom_menu_hook_append
.type custom_menu_hook_append, %function
.thumb_func
custom_menu_hook_append:
	mov r2, lr
	b.w custom_menu_hook_common

#if defined(CDX_VER_0204) || defined(CDX_VER_0205)
/* Lumis callers keep the menu in r4 and load the returned slot at +0x3c.
 * Preserve that convention when the inline page array becomes indirect.
 */
.global custom_menu_page_slot
.type custom_menu_page_slot, %function
.thumb_func
custom_menu_page_slot:
	ldrb r0, [r4]
	ldr ip, [r4, #0x3c]
	add r0, ip, r0, lsl #2
	subs r0, #0x3c
	bx lr
#endif

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

/* Optional callsite dispatch table; menu registry remains the UART format. */
.global custom_menu_dispatch_addr
.type custom_menu_dispatch_addr, %object
custom_menu_dispatch_addr:
	.word 0xffffffff

/* Optional sentinel-terminated visibility conditions, separate from the menu
 * registry used by UART discovery. Left erased when no feature adds rules.
 */
.global custom_menu_conditions_addr
.type custom_menu_conditions_addr, %object
custom_menu_conditions_addr:
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

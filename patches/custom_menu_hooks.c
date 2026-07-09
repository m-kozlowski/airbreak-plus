typedef unsigned char u8;
typedef unsigned short u16;
typedef unsigned int u32;

#include "s10_vars.h"

/* Registry entries are emitted by patch-airsense into reclaimed CCX space.
 * section selects the clinical menu section tail being hooked; flags carries
 * entry construction hints; mode_mask controls runtime per-MOP visibility.
 * A 0xff/0xffff entry terminates the registry.
 */
typedef struct {
	u8 section;
	u8 flags;
	u16 var_id;
	u32 mode_mask;
} custom_menu_entry_t;

#define CUSTOM_MENU_FLAG_G4_NUMERIC 0x01

extern void *malloc(unsigned size);
extern void scrollbar_add_item(void *list, void *item);
extern void *menu_create_text_or_float(int var_id, int arg);
extern void *menu_create_numeric_var(void *storage, int var_id, int arg);
extern void variable_lookup_handler(void *ctx, int var_id, int arg);
extern void variable_set_visible_from_handler(void *ctx, int visible);
extern void variable_handler_release(void *ctx);
extern int variable_get_g8(int var_id);

extern const u32 custom_menu_registry_addr;
extern const u32 custom_menu_original_mop_callback;

static const custom_menu_entry_t *custom_menu_registry(void)
{
	const custom_menu_entry_t *entry =
		(const custom_menu_entry_t *)custom_menu_registry_addr;
	if (!entry || (u32)entry == 0xffffffffu)
		return 0;
	return entry;
}

static void *custom_menu_create_item(const custom_menu_entry_t *entry)
{
	if (entry->flags & CUSTOM_MENU_FLAG_G4_NUMERIC) {
		void *storage = malloc(0x1c);
		if (!storage)
			return 0;
		return menu_create_numeric_var(storage, entry->var_id, 0);
	}

	return menu_create_text_or_float(entry->var_id, 0);
}

/* All section-specific assembly stubs tail-call here after replacing one stock
 * scrollbar_add_item(list, item) call. We first perform that original append,
 * then append any custom entries registered for the same section.
 */
void custom_menu_hook_common(void *list, void *item, unsigned section)
{
	scrollbar_add_item(list, item);

	if (!list)
		return;

	/* The patcher fills this ABI slot with the flash address of the generated
	 * registry. The erased value is kept as a defensive no-registry state.
	 */
	const custom_menu_entry_t *entry = custom_menu_registry();
	if (!entry)
		return;

	/* The registry should be sentinel-terminated, but keep a hard limit so a bad
	 * image cannot walk arbitrary flash if the terminator is missing.
	 */
	for (unsigned guard = 0; guard < 64; guard++, entry++) {
		if (entry->section == 0xff || entry->var_id == 0xffff)
			return;
		if (entry->section != section)
			continue;

		void *custom = custom_menu_create_item(entry);
		if (custom)
			scrollbar_add_item(list, custom);
	}
}

static void custom_menu_set_visible(u16 var_id, int visible)
{
	u32 ctx[16];

	variable_lookup_handler(ctx, var_id, 0);
	variable_set_visible_from_handler(ctx, visible);
	variable_handler_release(ctx);
}

void custom_menu_apply_mode_visibility(void)
{
	const custom_menu_entry_t *entry = custom_menu_registry();
	if (!entry)
		return;

	int mode = variable_get_g8(VAR_ID_MOP);

	for (unsigned guard = 0; guard < 64; guard++, entry++) {
		if (entry->section == 0xff || entry->var_id == 0xffff)
			return;

		int visible = 0;
		if ((unsigned)mode < 32)
			visible = (entry->mode_mask & (1u << (unsigned)mode)) != 0;
		custom_menu_set_visible(entry->var_id, visible);
	}
}

/* Replaces callback_table[MOP.callback_id]. Stock code first applies globals[24]
 * visibility; this wrapper then applies generated custom registry visibility
 * using the same handler method.
 */
void custom_menu_mop_callback_hook(void)
{
	void (*original)(void) = (void (*)(void))custom_menu_original_mop_callback;
	if (original && (u32)original != 0xffffffffu)
		original();
	custom_menu_apply_mode_visibility();
}

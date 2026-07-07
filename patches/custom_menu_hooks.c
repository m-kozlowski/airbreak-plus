typedef unsigned char u8;
typedef unsigned short u16;
typedef unsigned int u32;

/* Registry entries are emitted by patch-airsense into reclaimed CCX space.
 * section selects the clinical menu section tail being hooked; flags is reserved
 * for future visibility/filtering policy; var_id is the firmware variable to add.
 * A 0xff/0xffff entry terminates the registry.
 */
typedef struct {
	u8 section;
	u8 flags;
	u16 var_id;
	u32 reserved;
} custom_menu_entry_t;

extern void scrollbar_add_item(void *list, void *item);
extern void *menu_create_text_or_float(int var_id, int arg);

extern const u32 custom_menu_registry_addr;

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
	const custom_menu_entry_t *entry =
		(const custom_menu_entry_t *)custom_menu_registry_addr;
	if (!entry || (u32)entry == 0xffffffffu)
		return;

	/* The registry should be sentinel-terminated, but keep a hard limit so a bad
	 * image cannot walk arbitrary flash if the terminator is missing.
	 */
	for (unsigned guard = 0; guard < 64; guard++, entry++) {
		if (entry->section == 0xff || entry->var_id == 0xffff)
			return;
		if (entry->flags != 0 || entry->section != section)
			continue;

		/* This stock factory builds the correct menu widget for g[8] enum vars
		 * and g[4] numeric vars, matching how mixed stock sections are built.
		 */
		void *custom = menu_create_text_or_float(entry->var_id, 0);
		scrollbar_add_item(list, custom);
	}
}

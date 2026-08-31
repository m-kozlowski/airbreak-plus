typedef unsigned char u8;
typedef unsigned short u16;
typedef unsigned int u32;

#include "s10_vars.h"
#include "custom_menu_registry.h"

/* Registry entries are emitted by patch-airsense into reclaimed firmware space.
 * container selects a clinical menu section or a generated page; flags carries
 * entry construction hints; mode_mask controls runtime per-MOP visibility.
 * A 0xff/0xffff entry terminates the registry.
 */
#define CUSTOM_MENU_INLINE_PAGES_OFFSET 0x3c

extern void *malloc(unsigned size);
extern void scrollbar_add_item(void *list, void *item);
extern void gui_create_menus(void *menu, void *context);
extern void *scrollbar_init(void *storage, void *context, int capacity,
				   int title_str_id, int arg);
extern void *variable_0x1bc_and_0x1bd_writer_setup(void *storage, int page,
						   int item);
extern void *gui_create_back_button(void *storage, int str_id, int is_back,
				    void *action, int type);
extern void *menu_create_text_or_float(int var_id, int arg);
extern void *menu_create_numeric_var(void *storage, int var_id, int arg);
extern void *menu_create_static_string(void *storage, int str_id);
extern void variable_lookup_handler(void *ctx, int var_id, int arg);
extern void variable_set_visible_from_handler(void *ctx, int visible);
extern void variable_handler_release(void *ctx);
extern int variable_get_by_id(int var_id);
extern unsigned file_get_size(void *file);

extern const u32 custom_menu_registry_addr;
extern const u8 custom_settings_group_index;
extern const u8 custom_menu_stock_page_count;
extern const u8 custom_menu_clinical_page_id;
extern const u16 custom_menu_back_str_id;

static const custom_menu_entry_t *custom_menu_registry(void)
{
	const custom_menu_entry_t *entry =
		(const custom_menu_entry_t *)custom_menu_registry_addr;
	if (!entry || (u32)entry == 0xffffffffu)
		return 0;
	return entry;
}

static int custom_menu_entry_is_end(const custom_menu_entry_t *entry)
{
	return entry->container == 0xff || entry->item_id == 0xffff;
}

static unsigned custom_menu_page_ordinal(const custom_menu_entry_t *page)
{
	const custom_menu_entry_t *entry = custom_menu_registry();
	unsigned ordinal = 0;

	if (!entry)
		return 0xffff;
	for (unsigned guard = 0; guard < CUSTOM_MENU_REGISTRY_LIMIT;
	     guard++, entry++) {
		if (custom_menu_entry_is_end(entry))
			break;
		if (!(entry->flags & CUSTOM_MENU_FLAG_PAGE))
			continue;
		if (entry == page)
			return ordinal;
		ordinal++;
	}
	return 0xffff;
}

static void *custom_menu_create_navigation(const custom_menu_entry_t *entry)
{
	unsigned ordinal = custom_menu_page_ordinal(entry);
	if (ordinal == 0xffff)
		return 0;

	void *action_storage = malloc(8);
	if (!action_storage)
		return 0;
	void *action = variable_0x1bc_and_0x1bd_writer_setup(
		action_storage, custom_menu_stock_page_count + ordinal, 0);

	void *item_storage = malloc(0x14);
	if (!item_storage)
		return 0;
	return gui_create_back_button(item_storage, entry->item_id, 0, action, 0x29);
}

static void *custom_menu_create_item(const custom_menu_entry_t *entry)
{
	if (entry->flags & CUSTOM_MENU_FLAG_PAGE)
		return custom_menu_create_navigation(entry);

	if (entry->flags & CUSTOM_MENU_FLAG_HEADING) {
		void *storage = malloc(0x0c);
		if (!storage)
			return 0;
		return menu_create_static_string(storage, entry->item_id);
	}
	if (entry->flags & CUSTOM_MENU_FLAG_G4_NUMERIC) {
		void *storage = malloc(0x1c);
		if (!storage)
			return 0;
		return menu_create_numeric_var(storage, entry->item_id, 0);
	}

	return menu_create_text_or_float(entry->item_id, 0);
}

static unsigned custom_menu_container_size(u8 container)
{
	const custom_menu_entry_t *entry = custom_menu_registry();
	unsigned count = 0;

	if (!entry)
		return 0;
	for (unsigned guard = 0; guard < CUSTOM_MENU_REGISTRY_LIMIT;
	     guard++, entry++) {
		if (custom_menu_entry_is_end(entry))
			break;
		if (entry->container == container)
			count++;
	}
	return count;
}

static void *custom_menu_create_back(const custom_menu_entry_t *page)
{
	unsigned parent_page = custom_menu_clinical_page_id;
	if (page->container >= CUSTOM_MENU_PAGE_CONTAINER_BASE)
		parent_page = custom_menu_stock_page_count +
			(page->container - CUSTOM_MENU_PAGE_CONTAINER_BASE);

	void *action_storage = malloc(8);
	if (!action_storage)
		return 0;
	void *action = variable_0x1bc_and_0x1bd_writer_setup(
		action_storage, parent_page, 0);

	void *item_storage = malloc(0x14);
	if (!item_storage)
		return 0;
	return gui_create_back_button(
		item_storage, custom_menu_back_str_id, 1, action, 0x29);
}

static void *custom_menu_create_page(const custom_menu_entry_t *page,
				     unsigned ordinal, void *context)
{
	u8 container = CUSTOM_MENU_PAGE_CONTAINER_BASE + ordinal;
	unsigned capacity = custom_menu_container_size(container) + 1;
	void *storage = malloc(0x2c);
	if (!storage)
		return 0;
	void *list = scrollbar_init(storage, context, capacity, page->item_id, 0);
	if (!list)
		return 0;

	void *back = custom_menu_create_back(page);
	if (back)
		scrollbar_add_item(list, back);

	const custom_menu_entry_t *entry = custom_menu_registry();
	for (unsigned guard = 0; entry && guard < CUSTOM_MENU_REGISTRY_LIMIT;
	     guard++, entry++) {
		if (custom_menu_entry_is_end(entry))
			break;
		if (entry->container != container)
			continue;
		void *item = custom_menu_create_item(entry);
		if (item)
			scrollbar_add_item(list, item);
	}
	return list;
}

/* Build stock menus first so section hooks can append page links, then replace
 * the inline stock page array with one indirect table containing stock and
 * generated pages. The menu controller is a boot-lifetime singleton.
 */
void custom_menu_create_pages(void *menu, void *context)
{
	gui_create_menus(menu, context);

	const custom_menu_entry_t *entry = custom_menu_registry();
	unsigned page_count = 0;
	for (unsigned guard = 0; entry && guard < CUSTOM_MENU_REGISTRY_LIMIT;
	     guard++, entry++) {
		if (custom_menu_entry_is_end(entry))
			break;
		if (entry->flags & CUSTOM_MENU_FLAG_PAGE)
			page_count++;
	}
	if (!page_count || !custom_menu_stock_page_count ||
	    custom_menu_stock_page_count == 0xff)
		return;

	unsigned total = custom_menu_stock_page_count + page_count;
	void **inline_pages = (void **)((u8 *)menu + CUSTOM_MENU_INLINE_PAGES_OFFSET);
	void **pages = (void **)malloc(total * sizeof(*pages));
	if (!pages)
		return;

	for (unsigned i = 0; i < custom_menu_stock_page_count; i++)
		pages[i] = inline_pages[i];

	entry = custom_menu_registry();
	unsigned ordinal = 0;
	for (unsigned guard = 0; entry && guard < CUSTOM_MENU_REGISTRY_LIMIT;
	     guard++, entry++) {
		if (custom_menu_entry_is_end(entry))
			break;
		if (!(entry->flags & CUSTOM_MENU_FLAG_PAGE))
			continue;
		pages[custom_menu_stock_page_count + ordinal] =
			custom_menu_create_page(entry, ordinal, context);
		ordinal++;
	}
	*(void ***)inline_pages = pages;
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
	for (unsigned guard = 0; guard < CUSTOM_MENU_REGISTRY_LIMIT;
	     guard++, entry++) {
		if (custom_menu_entry_is_end(entry))
			return;
		if (entry->container != section)
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

	int mode = variable_get_by_id(VAR_ID_MOP);

	for (unsigned guard = 0; guard < CUSTOM_MENU_REGISTRY_LIMIT;
	     guard++, entry++) {
		if (custom_menu_entry_is_end(entry))
			return;
		if (entry->flags & (CUSTOM_MENU_FLAG_HEADING | CUSTOM_MENU_FLAG_PAGE))
			continue;
		int visible = 0;
		if ((unsigned)mode < 32)
			visible = (entry->mode_mask & (1u << (unsigned)mode)) != 0;
		custom_menu_set_visible(entry->item_id, visible);
	}
}

/* This replaces only the loader's second size query, reached after validation
 * has already failed. Report CSG as empty so stock code skips the configuration
 * fault, then continues through its existing truncate-and-rewrite path.
 */
unsigned custom_settings_error_file_size(void *file)
{
	unsigned size = file_get_size(file);
	const u8 *config = (const u8 *)file - 0x2c;

	if (config[0x25] == custom_settings_group_index)
		return 0;
	return size;
}

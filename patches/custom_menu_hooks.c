typedef unsigned char u8;
typedef unsigned short u16;
typedef unsigned int u32;

#include "s10_vars.h"
#include "custom_menu_registry.h"
#include "custom_menu_native.h"

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
extern void variable_set_editable_from_handler(void *ctx, int editable);
extern void variable_handler_release(void *ctx);
extern int variable_get_by_id(int var_id);
extern unsigned file_get_size(void *file);
extern void memcpy_unrolled(void *destination, const void *source,
			    unsigned size);

extern const u32 custom_menu_registry_addr;
extern const u32 custom_menu_dispatch_addr;
extern const u32 custom_menu_conditions_addr;
extern const u32 custom_menu_actions_addr;
extern const u8 custom_settings_group_index;
extern const u8 custom_menu_stock_page_count;
extern const u8 custom_menu_clinical_page_id;
extern const u16 custom_menu_back_str_id;

void custom_menu_apply_mode_visibility(void);

static const custom_menu_condition_t *custom_menu_conditions(void)
{
	if (!custom_menu_conditions_addr || custom_menu_conditions_addr == 0xffffffffu)
		return 0;
	return (const custom_menu_condition_t *)custom_menu_conditions_addr;
}

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

extern void *gui_action_write(void *, int, int);
extern void *gui_action_default(void *);
extern void *gui_action_sequence(void *);
extern void gui_action_prepend(void *, void *);
extern int snprintf(char *, unsigned, const char *, ...);

static void *custom_menu_create_action(const custom_menu_entry_t *entry)
{
	if (!custom_menu_actions_addr || custom_menu_actions_addr == 0xffffffffu)
		return 0;
	const custom_menu_action_t *spec =
		(const custom_menu_action_t *)custom_menu_actions_addr + entry->item_id;
	void *action = 0;
	if (spec->destination) {
		void *storage = malloc(8);
		if (!storage) return 0;
		action = spec->destination == 0xff ? gui_action_default(storage) :
			variable_0x1bc_and_0x1bd_writer_setup(storage,
				custom_menu_stock_page_count + spec->destination - CUSTOM_MENU_PAGE_CONTAINER_BASE,
				spec->item);
	}
	if (spec->write_id != 0xffff) {
		void *storage = malloc(12);
		if (!storage) return 0;
		void *write = gui_action_write(storage, spec->write_id, spec->value);
		if (action) {
			storage = malloc(8);
			if (!storage) return 0;
			void *sequence = gui_action_sequence(storage);
			/* Prepending runs the write before navigation. */
			gui_action_prepend(sequence, action);
			gui_action_prepend(sequence, write);
			action = sequence;
		} else action = write;
	}
	void *storage = malloc(spec->binding_id == 0xffff ? 0x14 : CUSTOM_MENU_BOUND_BUTTON_SIZE);
	if (!storage || !action) return 0;
	return spec->binding_id == 0xffff ?
		gui_create_back_button(storage, spec->label_id, 0, action, 0x29) :
		custom_menu_bound_button(storage, spec->label_id, spec->binding_id, action);
}

static void custom_menu_format_time(void *item, char *buffer, unsigned size)
{
	unsigned packed = *(u32 *)((u8 *)item + 0x18);
	if (size) snprintf(buffer, size, "%02u:%02u", (packed >> 8) & 255, packed & 255);
}

static void *custom_menu_create_item(const custom_menu_entry_t *entry)
{
	if (entry->flags & CUSTOM_MENU_FLAG_DECLARATION)
		return 0;
	if (entry->flags & CUSTOM_MENU_FLAG_PAGE)
		return custom_menu_create_navigation(entry);
	if (entry->flags & CUSTOM_MENU_FLAG_ACTION)
		return custom_menu_create_action(entry);

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
		void *item = menu_create_numeric_var(
			storage, entry->item_id,
			(entry->flags & CUSTOM_MENU_FLAG_SHOW_UNITS) != 0);
		if (entry->flags & CUSTOM_MENU_FLAG_PACKED_TIME) {
			u32 *methods = malloc(CUSTOM_MENU_NUMERIC_METHODS * sizeof(u32));
			if (methods) {
				memcpy_unrolled(methods, *(void **)item,
						CUSTOM_MENU_NUMERIC_METHODS * sizeof(u32));
				methods[CUSTOM_MENU_NUMERIC_FORMAT] = (u32)custom_menu_format_time;
				*(u32 **)item = methods;
			}
		}
		return item;
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
		if (entry->container == container && !(entry->flags & CUSTOM_MENU_FLAG_DECLARATION))
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
	int has_back = !(page->flags & CUSTOM_MENU_PAGE_NO_BACK);
	unsigned capacity = custom_menu_container_size(container) + has_back;
	void *storage = malloc(0x2c);
	if (!storage)
		return 0;
	void *list = scrollbar_init(storage, context, capacity, page->item_id, 0);
	if (!list)
		return 0;

	void *back = has_back ? custom_menu_create_back(page) : 0;
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
	/* Set initial visibility from loaded settings, before the first UI refresh. */
	if (custom_menu_conditions())
		custom_menu_apply_mode_visibility();

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

	memcpy_unrolled(pages, inline_pages,
			custom_menu_stock_page_count * sizeof(*pages));

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

static void custom_menu_append_range(void *list, unsigned first, unsigned count)
{
	const custom_menu_entry_t *registry = custom_menu_registry();
	if (!list || !registry || first + count > CUSTOM_MENU_REGISTRY_LIMIT)
		return;
	const custom_menu_entry_t *entry = registry + first;
	for (unsigned i = 0; i < count; i++, entry++) {
		if (custom_menu_entry_is_end(entry))
			return;
		void *custom = custom_menu_create_item(entry);
		if (custom)
			scrollbar_add_item(list, custom);
	}
}

/* Perform the displaced append exactly once, between its two custom ranges.
 * VIS affects subsequent rendering; it does not skip the native append hook.
 */
void custom_menu_hook_common(void *list, void *item, unsigned return_pc)
{
	const custom_menu_dispatch_t *dispatch =
		(const custom_menu_dispatch_t *)custom_menu_dispatch_addr;
	if (dispatch && custom_menu_dispatch_addr != 0xffffffffu) {
		for (unsigned guard = 0; guard < CUSTOM_MENU_REGISTRY_LIMIT;
		     guard++, dispatch++) {
			if (dispatch->return_pc == 0xffffffffu)
				break;
			if (dispatch->return_pc != (return_pc & ~1u))
				continue;
			custom_menu_append_range(list, dispatch->before_first,
						 dispatch->before_count);
			scrollbar_add_item(list, item);
			custom_menu_append_range(list, dispatch->after_first,
						 dispatch->after_count);
			return;
		}
	}
	scrollbar_add_item(list, item);
}

/* Sets VIS from the entry's modes and hide conditions, and, when the entry
 * has grey-out conditions, EDT from those: a non-editable row is greyed out.
 * The EDT setter is only mapped for SX567; the patcher allows grey-out there
 * only.
 */
static void custom_menu_set_state(u16 var_id, int visible, int editable)
{
	u32 ctx[16];

	variable_lookup_handler(ctx, var_id, 0);
	variable_set_visible_from_handler(ctx, visible);
#if !defined(CDX_VER_0204) && !defined(CDX_VER_0205)
	if (editable >= 0)
		variable_set_editable_from_handler(ctx, editable);
#endif
	variable_handler_release(ctx);
}

/* 1 when all applicable conditions of one kind hold (hide conditions for
 * grey = 0, grey-out conditions for grey = 1); -1 when there are no grey-out
 * conditions to apply.
 */
static int custom_menu_conditions_match(u16 var_id, u32 mode_bit, unsigned grey)
{
	const custom_menu_condition_t *condition = custom_menu_conditions();
	int match = grey ? -1 : 1;
	if (!condition)
		return match;
	for (; condition->item_id != 0xffff; condition++) {
		if (condition->item_id != var_id || !(condition->mode_mask & mode_bit) ||
		    (condition->nonzero >> 1) != grey)
			continue;
		if ((variable_get_by_id(condition->source_id) != 0) != (condition->nonzero & 1))
			return 0;
		match = 1;
	}
	return match;
}

void custom_menu_apply_mode_visibility(void)
{
	const custom_menu_entry_t *entry = custom_menu_registry();
	if (!entry)
		return;

	int mode = variable_get_by_id(VAR_ID_MOP);
	u32 mode_bit = (unsigned)mode < 32 ? 1u << (unsigned)mode : 0;

	for (unsigned guard = 0; guard < CUSTOM_MENU_REGISTRY_LIMIT;
	     guard++, entry++) {
		if (custom_menu_entry_is_end(entry))
			return;
		if (entry->flags & CUSTOM_MENU_NON_SETTING)
			continue;
		if (entry->mode_mask & CUSTOM_MENU_MODE_KEEP_VISIBILITY)
			continue;
		int visible = (entry->mode_mask & CUSTOM_MENU_MODE_BITS & mode_bit) != 0;
		if (visible)
			visible = custom_menu_conditions_match(entry->item_id, mode_bit, 0);
		custom_menu_set_state(entry->item_id, visible,
				      custom_menu_conditions_match(entry->item_id, mode_bit, 1));
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

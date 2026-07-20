/*
 * Shared menu bridge for settings requested by compiled payloads.
 *
 * Feature patches queue DataItems and item factories in the Python patcher.
 * The finalizer fills this registry and redirects the stock clinical scroller
 * constructor through this payload.
 */

#include "stubs.h"
#include "vars.h"

#define CUSTOM_MENU_ENTRY_CAPACITY 64
#define CUSTOM_MENU_FACTORY_CAPACITY 16
#define CUSTOM_MENU_REMOVAL_CAPACITY 16
#define GUI_TEXT_VALUE_ITEM_SIZE 0x48
#define GUI_TEXT_FORMATTER_WORDS 10

enum custom_menu_section {
    CUSTOM_MENU_SECTION_THERAPY = 0,
    CUSTOM_MENU_SECTION_COMFORT,
    CUSTOM_MENU_SECTION_ACCESSORIES,
    CUSTOM_MENU_SECTION_OPTIONS,
    CUSTOM_MENU_SECTION_CONFIGURATION,
    CUSTOM_MENU_SECTION_COUNT,
};

typedef struct {
    unsigned short var_id;   /* Firmware DataItem backing the setting. */
    unsigned short label_id; /* Firmware GUI text ID for the menu row. */
    unsigned short mode_mask; /* ActiveTherapyProfile bitset. */
    unsigned char section;    /* custom_menu_section ordinal. */
    unsigned char factory_index; /* Index in custom_menu_factories. */
} custom_menu_entry_t;

typedef void *(*custom_menu_item_factory_t)(
    unsigned int var_id, unsigned int label_id);

/* Active entries are contiguous; var_id 0xFFFF terminates the registry. */
volatile const custom_menu_entry_t custom_menu_entries[CUSTOM_MENU_ENTRY_CAPACITY]
    __attribute__((used, section(".rodata.registry"))) = {
        [0 ... CUSTOM_MENU_ENTRY_CAPACITY - 1] = {
            0xFFFFu, 0xFFFFu, 0u, 0xFFu, 0xFFu
        },
    };

/* Menu records reference this deduplicated table by factory_index. */
volatile const unsigned int custom_menu_factories[CUSTOM_MENU_FACTORY_CAPACITY]
    __attribute__((used, section(".rodata.factories"))) = {
        [0 ... CUSTOM_MENU_FACTORY_CAPACITY - 1] = 0xFFFFFFFFu,
    };

/* Stock row indexes omitted while rebuilding the clinical menu. */
volatile const unsigned short custom_menu_removed_rows[CUSTOM_MENU_REMOVAL_CAPACITY]
    __attribute__((used, section(".rodata.removed_rows"))) = {
        [0 ... CUSTOM_MENU_REMOVAL_CAPACITY - 1] = 0xFFFFu,
    };

static unsigned int custom_menu_entry_count(void)
{
    unsigned int count = 0;

    while (count < CUSTOM_MENU_ENTRY_CAPACITY &&
           custom_menu_entries[count].var_id != 0xFFFFu)
        ++count;
    return count;
}

static void apply_custom_menu_visibility(void)
{
    unsigned int count = custom_menu_entry_count();
    unsigned int mode = (unsigned int)DataItem_read_value_by_id(VAR_ID_MOP);
    unsigned int index;

    /* Mirror g[10] mode gating through the native DataItem visibility API. */
    for (index = 0; index < count; ++index) {
        const volatile custom_menu_entry_t *entry =
            &custom_menu_entries[index];
        int visible = mode < 16u &&
            (entry->mode_mask & (1u << mode)) != 0u;

        DataItem_set_visible_by_id(entry->var_id, visible);
    }
}

void *custom_menu_text_value_factory(
    unsigned int var_id, unsigned int label_id)
{
    unsigned int formatter[GUI_TEXT_FORMATTER_WORDS]
        __attribute__((aligned(8)));
    void *item = heap_alloc(GUI_TEXT_VALUE_ITEM_SIZE);

    if (item == 0)
        return 0;

    GuiTextValueFormatter_ctor(formatter);
    item = GuiMenuTextValueListItem_ctor(
        item, var_id, label_id, formatter);
    GuiTextValueFormatter_dtor(formatter);
    return item;
}

static void *create_custom_menu_item(
    const volatile custom_menu_entry_t *entry)
{
    unsigned int factory_address;
    custom_menu_item_factory_t factory;

    if (entry->factory_index >= CUSTOM_MENU_FACTORY_CAPACITY)
        return 0;
    factory_address = custom_menu_factories[entry->factory_index];
    if (factory_address == 0xFFFFFFFFu)
        return 0;
    factory = (custom_menu_item_factory_t)factory_address;

    return factory(entry->var_id, entry->label_id);
}

static int stock_row_is_removed(unsigned int stock_index)
{
    unsigned int index;

    for (index = 0; index < CUSTOM_MENU_REMOVAL_CAPACITY; ++index) {
        unsigned int removed = custom_menu_removed_rows[index];

        if (removed == 0xFFFFu)
            return 0;
        if (removed == stock_index)
            return 1;
    }
    return 0;
}

static int find_stock_sections(
    void **items,
    unsigned int item_count,
    unsigned int section_starts[CUSTOM_MENU_SECTION_COUNT])
{
    void *header_vtable;
    unsigned int section_count = 0;
    unsigned int index;

    if (items == 0 || item_count == 0 || items[0] == 0)
        return 0;

    header_vtable = *(void **)items[0];
    if (header_vtable == 0)
        return 0;

    /* Stock section headings share the first row's concrete class. */
    for (index = 0; index < item_count; ++index) {
        if (items[index] == 0 || *(void **)items[index] != header_vtable)
            continue;
        if (section_count >= CUSTOM_MENU_SECTION_COUNT)
            return 0;
        section_starts[section_count++] = index;
    }

    return section_count == CUSTOM_MENU_SECTION_COUNT &&
        section_starts[CUSTOM_MENU_SECTION_THERAPY] == 0;
}

void *custom_settings_clinical_scroller_ctor(
    void *scroller,
    unsigned int arg2,
    unsigned int arg3,
    unsigned int arg4,
    unsigned int arg5,
    void **items,
    unsigned int item_count,
    unsigned int arg8,
    unsigned int arg9,
    unsigned int arg10,
    unsigned int arg11,
    unsigned int arg12)
{
    unsigned int entry_count = custom_menu_entry_count();
    unsigned int section_starts[CUSTOM_MENU_SECTION_COUNT];
    unsigned int section;
    unsigned int stock_index;
    unsigned int output_index = 0;
    unsigned int output_count;
    void **expanded;

    if (!find_stock_sections(items, item_count, section_starts)) {
        return GuiScroller_ctor(
            scroller, arg2, arg3, arg4, arg5, items, item_count,
            arg8, arg9, arg10, arg11, arg12);
    }

    apply_custom_menu_visibility();
    output_count = item_count + entry_count;
    expanded = (void **)heap_alloc(
        output_count * (unsigned int)sizeof(void *));
    if (expanded == 0) {
        return GuiScroller_ctor(
            scroller, arg2, arg3, arg4, arg5, items, item_count,
            arg8, arg9, arg10, arg11, arg12);
    }

    /* Copy each stock section, then append its registered custom rows. */
    for (section = 0; section < CUSTOM_MENU_SECTION_COUNT; ++section) {
        unsigned int section_end = section + 1u < CUSTOM_MENU_SECTION_COUNT
            ? section_starts[section + 1u]
            : item_count;
        unsigned int custom_index;

        for (stock_index = section_starts[section];
             stock_index < section_end; ++stock_index) {
            if (!stock_row_is_removed(stock_index))
                expanded[output_index++] = items[stock_index];
        }
        for (custom_index = 0; custom_index < entry_count; ++custom_index) {
            if (custom_menu_entries[custom_index].section == section) {
                void *item = create_custom_menu_item(
                    &custom_menu_entries[custom_index]);

                if (item != 0)
                    expanded[output_index++] = item;
            }
        }
    }

    return GuiScroller_ctor(
        scroller, arg2, arg3, arg4, arg5, expanded, output_index,
        arg8, arg9, arg10, arg11, arg12);
}

void __attribute__((section(".text.0.main")))
start(void)
{
    /* MOP dispatcher entry: refresh visibility after the mode is committed. */
    apply_custom_menu_visibility();
}

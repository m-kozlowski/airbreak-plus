#include "custom_menu_native.h"
#include "custom_menu_registry.h"

extern const unsigned custom_menu_previews_addr;
extern int gui_numeric_row_changed(void *row);
extern void gui_numeric_row_leave(void *row);
extern void gui_numeric_row_read(void *row);
extern void variable_set_by_id(int var_id, int value);

_Static_assert(sizeof(struct custom_menu_numeric_row) == 0x1c, "numeric row ABI");

static const custom_menu_preview_t *preview_for(unsigned short source_id)
{
    const custom_menu_preview_t *preview =
        (const custom_menu_preview_t *)custom_menu_previews_addr;
    if (preview && custom_menu_previews_addr != 0xffffffffu) {
        for (; preview->target_id != 0xffff; ++preview)
            if (preview->source_id == source_id)
                return preview;
    }
    return 0;
}

static void update_targets(struct custom_menu_numeric_row *row)
{
    const custom_menu_preview_t *preview = preview_for(row->var_id);
    if (preview) {
        for (; preview->target_id != 0xffff; ++preview) {
            if (preview->source_id == row->var_id)
                variable_set_by_id(preview->target_id,
                                    preview->calculate(row->pending));
        }
    }
}

int custom_menu_preview_changed(struct custom_menu_numeric_row *row)
{
    int changed = gui_numeric_row_changed(row);
    /* Refreshing an idle source must not replace another editor's preview. */
    if (changed && row->state == 2)
        update_targets(row);
    return changed;
}

void custom_menu_preview_leave(struct custom_menu_numeric_row *row)
{
    int editing = row->state == 2;
    gui_numeric_row_leave(row);
    if (editing && row->state != 2 && preview_for(row->var_id)) {
        /* A hidden row may not get another refresh before its targets are read. */
        gui_numeric_row_read(row);
        if (gui_numeric_row_changed(row))
            update_targets(row);
    }
}

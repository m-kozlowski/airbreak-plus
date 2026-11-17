#include "gui_objects.h"

extern const unsigned gui_enum_row_methods[];
extern void *malloc(unsigned size);
extern void heap_free(void *object);
extern void *gui_variable_row_init(void *, int height, int var_id, unsigned flags);
extern void *gui_enum_model_init(void *, int var_id);
extern void *gui_enum_editor_init(void *, void *model, int var_id);
extern void gui_enum_row_open(void *row);
extern void gui_enum_row_close(void *row);
extern void gui_enum_row_show(void *row, int visible);
extern void gui_base_show(void *object, int visible);
extern int gui_base_is_visible(void *object);
extern void gui_screen_update(void *screen);

_Static_assert(sizeof(struct gui_enum_row) == 0x18, "enum row ABI");
_Static_assert(sizeof(struct gui_enum_editor) == 0x2c, "enum editor ABI");

void *custom_menu_enum_init(struct gui_enum_row *row, int var_id, unsigned flags)
{
    gui_variable_row_init(row, 0x29, var_id, (flags & ~2u) | 4u);
    row->methods = gui_enum_row_methods;
    row->editor = 0;
    return row;
}

void custom_menu_enum_open(struct gui_enum_row *row)
{
    if (!row->editor) {
        void *model = malloc(0x2c);
        struct gui_enum_editor *editor = malloc(sizeof(*editor));
        if (!model || !editor) {
            heap_free(model);
            heap_free(editor);
            return;
        }
        gui_enum_model_init(model, row->var_id);
        gui_enum_editor_init(editor, model, row->var_id);
        editor->owner = row;
        row->editor = editor;
    }
    gui_enum_row_open(row);
}

void custom_menu_enum_close(struct gui_enum_row *row)
{
    if (row->editor)
        gui_enum_row_close(row);
}

void custom_menu_enum_show(struct gui_enum_row *row, int visible)
{
    if (row->editor)
        gui_enum_row_show(row, visible);
    else
        gui_base_show(row, visible);
}

static void release_editor(void *object, void *context)
{
    (void)context;
    struct gui_enum_row *row = object;
    if (row->methods != gui_enum_row_methods || !row->editor || row->state == 2)
        return;
    struct gui_enum_editor *editor = row->editor;
    if (gui_base_is_visible(editor))
        return;

    gui_destroy(editor, &gui_enum_editor_type);
}

void custom_menu_editor_update(void *screen)
{
    gui_screen_update(screen);
    /* Selection callbacks have returned; none can still refer to an option. */
    gui_visit_objects(release_editor, 0);
}

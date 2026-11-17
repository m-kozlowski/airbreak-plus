#include "gui_objects.h"

struct registry_entry {
    const void *methods;
    unsigned char deleted, reserved[3];
    unsigned key, hash;
    void *object;
};

extern struct {
    const void *methods;
    void *hash;
    unsigned capacity, count;
    struct registry_entry **entries;
} gui_window_registry;

extern void gui_window_registry_remove(void *object);
extern unsigned WM_GetParent(unsigned window);
extern void WM__DeleteWindow(unsigned window);
extern void heap_free(void *object);
extern void gui_enum_handler_release(void *handler);
extern void variable_handler_release(void *handler);

#define WORD(p, off) (*(unsigned *)((unsigned char *)(p) + (off)))

void gui_visit_objects(void (*visit)(void *, void *), void *context)
{
    for (unsigned i = 0; i < gui_window_registry.capacity; ++i) {
        struct registry_entry *entry = gui_window_registry.entries[i];
        if (entry && !entry->deleted)
            visit(entry->object, context);
    }
}

static void remove_descendant(void *object, void *context)
{
    unsigned window = ((unsigned *)object)[1];
    while (window) {
        if (window == (unsigned)context) {
            gui_window_registry_remove(object);
            return;
        }
        window = WM_GetParent(window);
    }
}

void gui_free(void *object, gui_release_fn release)
{
    if (!object)
        return;
    if (release)
        release(object);
    heap_free(object);
}

void gui_free_array(void **objects, unsigned count, gui_release_fn release)
{
    for (unsigned i = 0; i < count; ++i)
        gui_free(objects[i], release);
    heap_free(objects);
}

void gui_destroy(void *object, const struct gui_object_type *type)
{
    if (!object)
        return;
    if (type->detach)
        type->detach(object);
    unsigned window = WORD(object, 4);
    gui_visit_objects(remove_descendant, (void *)window);
    WM__DeleteWindow(window);
    gui_free(object, type->release);
}

static void release_link(void *object)
{
    heap_free(*(void **)object);
}

void gui_release_composite(void *object)
{
    for (unsigned side = 0; side != 2; ++side)
        gui_free_array((void **)WORD(object, 0x0c + 4 * side),
                       WORD(object, 0x18 + 8 * side), release_link);
}

void gui_release_gauge(void *object)
{
    heap_free((void *)WORD(object, 0x68));
    for (unsigned i = 0; i < *((unsigned char *)object + 0x7a); ++i)
        heap_free((void *)WORD(object, 0x70 + 4 * i));
}

void gui_release_pressure(void *object)
{
    /* Both renderers borrow this row's window. */
    heap_free((void *)WORD(object, 0x0c));
    heap_free((void *)WORD(object, 0x10));
}

void gui_release_variable_header(void *object)
{
    variable_handler_release((unsigned char *)object + 0x0c);
    variable_handler_release((unsigned char *)object + 0x48);
}

static void detach_editor(void *object)
{
    struct gui_enum_editor *editor = object;
    editor->owner->editor = 0;
}

static void release_editor(void *object)
{
    struct gui_enum_editor *editor = object;
    gui_enum_handler_release((unsigned char *)editor->model + 4);
    heap_free(editor->model);
    gui_free_array(editor->items, editor->cancel_index + 1, 0);
    heap_free(editor->header);
    heap_free(editor->scroll);
}

const struct gui_object_type gui_enum_editor_type = {
    .detach = detach_editor,
    .release = release_editor,
};

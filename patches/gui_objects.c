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

void gui_destroy_windows(void *root)
{
    unsigned window = ((unsigned *)root)[1];
    gui_visit_objects(remove_descendant, (void *)window);
    WM__DeleteWindow(window);
}

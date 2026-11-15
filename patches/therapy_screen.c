/* Replace the main therapy page on the GUI task. Native data pages stay linked. */
#include "s10_vars.h"
#include "therapy_screen.h"

typedef unsigned char u8;
typedef unsigned short u16;
typedef unsigned int u32;

struct page {
    const u32 *methods;
    u32 window;
    void **rows;
    u32 count;
    u8 scroll_state[16];
    u8 id, reserved[3];
    int split;
    void *header;
    struct page *previous, *next;
    /* Extra storage on the two main-page allocation sites only. */
    void *parent;
    unsigned choice;
};

extern const u16 therapy_screen_var_id;
extern const u8 therapy_screen_indirect_pages;
extern const u16 therapy_screen_simple_modes;
extern struct page *gui_therapy_pages[2];
extern void *gui_task_group_get(void);
extern void gui_window_registry_remove(void *obj);
extern void WM__DeleteWindow(u32 window);
extern void heap_free(void *obj);
extern void variable_handler_release(void *handler);
extern int variable_get_by_id(int var_id);
extern void gui_invalidate_window(void *obj);
extern void gui_menu_system_update_selected_page(void *menu, int changed, int active);
extern struct page *therapy_screen_construct(void *parent, unsigned bar);
extern void gui_scrollable_layout_items(void *page);

_Static_assert(sizeof(struct page) == 60, "main-page allocation size");

#define WORD(p, off) (*(u32 *)((u8 *)(p) + (off)))

unsigned therapy_screen_get_choice(void)
{
    if (therapy_screen_var_id == 0xffffu)
        return THERAPY_BAR;
    unsigned choice = variable_get_by_id(therapy_screen_var_id);
    return choice < THERAPY_SCREEN_CHOICE_COUNT ? choice : THERAPY_BAR;
}

static unsigned use_bar(unsigned choice)
{
    if (choice == THERAPY_SIMPLE || choice == THERAPY_SIMPLE_GRAPH)
        return 0;
    if (choice == THERAPY_AUTO || choice == THERAPY_AUTO_GRAPH) {
        unsigned mode = variable_get_by_id(VAR_ID_MOP);
        return mode >= 16 || !(therapy_screen_simple_modes & (1u << mode));
    }
    return 1;
}

struct page *start(void *parent)
{
    unsigned choice = therapy_screen_get_choice();
    struct page *page = therapy_screen_construct(parent, use_bar(choice));
    page->parent = parent;
    page->choice = choice;
    return page;
}

static void show(struct page *page, int visible)
{
    ((void (*)(void *, int))page->methods[3])(page, visible);
}

void therapy_screen_layout(struct page *page)
{
    int compact = page->id == 9 && page->count == 10 &&
                  therapy_screen_has_graph(therapy_screen_get_choice());
    u8 status[7];
    int split = page->split;
    if (compact) {
        /* Give the graph the space occupied by the pressure-setting summaries.
         * Preserve their cached VIS bits: changing them would force a layout
         * on every poll and repeatedly erase the graph. */
        for (unsigned i = 0; i < 7; ++i) {
            u8 *flags = (u8 *)page->rows[i + 1] + 0x10;
            status[i] = *flags;
            *flags &= ~0x10;
        }
        /* Anchor the status icons at the bottom, leaving a gap for the graph. */
        page->split = 9;
    }
    gui_scrollable_layout_items(page);
    page->split = split;
    if (compact)
        for (unsigned i = 0; i < 7; ++i) {
            u8 *flags = (u8 *)page->rows[i + 1] + 0x10;
            *flags = (*flags & ~0x10) | (status[i] & 0x10);
        }
}

static void detach(struct page *page)
{
    struct page *previous = page->previous, *next = page->next;
    if (previous == page)
        gui_therapy_pages[0] = next == page ? 0 : next;
    else
        previous->next = next == page ? previous : next;
    if (next == page)
        gui_therapy_pages[1] = previous == page ? 0 : previous;
    else
        next->previous = previous == page ? next : previous;
}

static void free_composite(void *obj)
{
    for (unsigned side = 0; side != 2; ++side) {
        u32 *array = (u32 *)WORD(obj, 0x0c + 4 * side);
        unsigned count = WORD(obj, 0x18 + 8 * side);
        for (unsigned i = 0; i != count; ++i) {
            u32 *link = (u32 *)array[i];
            heap_free((void *)link[0]);
            heap_free(link);
        }
        heap_free(array);
    }
}

static void unlink_listener(void *gauge)
{
    u32 *link = (u32 *)((u8 *)gui_task_group_get() + 0x74);
    while (*link) {
        u32 *node = (u32 *)*link;
        if (node[0] == (u32)gauge) {
            *link = node[1];
            heap_free(node);
        } else {
            link = node + 1;
        }
    }
}

static void destroy(struct page *page)
{
    int simple = page->count == 10;
    show(page, 0);
    detach(page);
    if (simple)
        unlink_listener(page->rows[8]);
    for (unsigned i = 0; i < page->count; ++i)
        gui_window_registry_remove(page->rows[i]);
    gui_window_registry_remove(page);
    WM__DeleteWindow(page->window);

    for (unsigned i = 0; i < page->count; ++i) {
        void *row = page->rows[i];
        if ((simple && i == 9) || (!simple && i >= 3)) {
            free_composite(row);
        } else if (simple && i == 8) {
            heap_free((void *)WORD(row, 0x68));
            for (unsigned j = 0; j < *((u8 *)row + 0x7a); ++j)
                heap_free((void *)WORD(row, 0x70 + 4 * j));
        } else if (!simple && i == 1) {
            variable_handler_release((u8 *)row + 0x0c);
            variable_handler_release((u8 *)row + 0x48);
        } else if (!simple && i == 2) {
            /* The two renderers borrow this row's window. */
            heap_free((void *)WORD(row, 0x0c));
            heap_free((void *)WORD(row, 0x10));
        }
        heap_free(row);
    }
    heap_free(page->rows);
    heap_free(page);
}

void therapy_screen_update(void *menu, int changed, int active, int dialog)
{
    /* Finish ordinary navigation before replacing any object it may reference. */
    gui_menu_system_update_selected_page(menu, changed, active);
    if (!active || dialog)
        return;
    struct page **pages = (struct page **)((u8 *)menu + 0x3c);
    if (therapy_screen_indirect_pages)
        pages = *(struct page ***)pages;
    struct page *page = pages[9];
    unsigned choice = therapy_screen_get_choice();
    int selected = *(u8 *)menu == 9;
    int graph_changed = therapy_screen_has_graph(choice) !=
                        therapy_screen_has_graph(page->choice);
    int refresh = 0;
    if (use_bar(choice) != (page->count == 6)) {
        void *parent = page->parent;
        pages[9] = 0;
        destroy(page);
        page = start(parent);
        /* The stock constructor appends; move the replacement to the front. */
        detach(page);
        page->previous = page;
        page->next = gui_therapy_pages[0] ? gui_therapy_pages[0] : page;
        if (gui_therapy_pages[0])
            gui_therapy_pages[0]->previous = page;
        else
            gui_therapy_pages[1] = page;
        gui_therapy_pages[0] = page;
        pages[9] = page;
        if (selected) {
            ((void (*)(void *))page->methods[11])(page);
            show(page, 1);
            refresh = 1;
        }
    }
    /* Graphs draw outside their owner's window, so repaint the entire page. */
    if (graph_changed && *(u8 *)menu >= 9 && *(u8 *)menu <= 11) {
        if (selected && page->count == 10)
            therapy_screen_layout(page);
        gui_invalidate_window(pages[*(u8 *)menu]);
        refresh = 1;
    }
    page->choice = choice;
    if (refresh)
        gui_menu_system_update_selected_page(menu, 1, active);
}

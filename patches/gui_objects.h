#ifndef GUI_OBJECTS_H
#define GUI_OBJECTS_H

/* Visitors may remove objects, but must not insert new registry entries. */
void gui_visit_objects(void (*visit)(void *, void *), void *context);

typedef void (*gui_release_fn)(void *);

struct gui_object_type {
    void (*detach)(void *object);
    gui_release_fn release;
};

/* Call on the GUI task after input callbacks return. Detach removes external
 * references to the object and its children. Release frees owned resources
 * after the entire window tree has been deleted; gui_destroy frees the root. */
void gui_destroy(void *object, const struct gui_object_type *type);

/* Use for children whose windows were deleted with their parent's tree.
 * Release callbacks free only owned resources, leaving the object to gui_free. */
void gui_free(void *object, gui_release_fn release);
void gui_free_array(void **objects, unsigned count, gui_release_fn release);
void gui_release_composite(void *object);
void gui_release_gauge(void *object);
void gui_release_pressure(void *object);
void gui_release_variable_header(void *object);

struct gui_enum_editor {
    const void *methods;
    unsigned window;
    const void *input_methods;
    void *model, *header;
    struct gui_enum_row *owner;
    void **items;
    unsigned selected, cancel_index;
    void *scroll;
    unsigned visible_count;
};

struct gui_enum_row {
    const void *methods;
    unsigned window;
    unsigned char state, reserved;
    unsigned short var_id;
    unsigned value, flags;
    struct gui_enum_editor *editor;
};

extern const struct gui_object_type gui_enum_editor_type;

#endif

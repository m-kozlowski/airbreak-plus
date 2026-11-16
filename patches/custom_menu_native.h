#ifndef CUSTOM_MENU_NATIVE_H
#define CUSTOM_MENU_NATIVE_H

struct custom_menu_numeric_row {
    const void *methods;
    unsigned window;
    unsigned char state, reserved;
    unsigned short var_id;
    int displayed;
    unsigned flags;
    const void *input_methods;
    int pending;
};

/* Numeric values are stored at +0x18. Method counts cover the primary vtable,
 * ending before the secondary base's offset-to-top entry.
 */
#if defined(CDX_VER_0204) || defined(CDX_VER_0205)
enum {
    CUSTOM_MENU_BOUND_BUTTON_SIZE = 0x20,
    CUSTOM_MENU_NUMERIC_METHODS = 33,
    CUSTOM_MENU_NUMERIC_FORMAT = 26,
};
extern void *gui_create_bound_button(void *, int, int, int, void *, const void *);

static inline void *custom_menu_bound_button(void *storage, int label,
                                             int binding, void *action)
{
    /* Lumis has optional display data at +0x1c, after the action at +0x18. */
    return gui_create_bound_button(storage, label, 0, binding, action, 0);
}
#elif defined(CDX_VER_0302) || defined(CDX_VER_0305) || \
      defined(CDX_VER_0306) || defined(CDX_VER_0401) || defined(CDX_VER_0402)
enum {
    CUSTOM_MENU_BOUND_BUTTON_SIZE = 0x1c,
    CUSTOM_MENU_NUMERIC_METHODS = 31,
    CUSTOM_MENU_NUMERIC_FORMAT = 25,
};
extern void *gui_create_bound_button(void *, int, int, int, void *);

static inline void *custom_menu_bound_button(void *storage, int label,
                                             int binding, void *action)
{
    return gui_create_bound_button(storage, label, 0, binding, action);
}
#else
#error Unsupported native menu ABI
#endif

#endif

/* Shared physical-button hooks. Stock still owns GPIO sampling and debounce. */
#include "button_hooks.h"

typedef unsigned char u8;
typedef unsigned short u16;
typedef void (*method_t)(void);

enum {
    PANEL_UPDATE = 2,
    PANEL_CONFIGURE = 4,
    PANEL_CLEAR = 5,
    PANEL_TAKE = 6,
    PANEL_METHODS = 10,
    KEY_HOME = 4,
    KEY_ENCODER = 8,
};

/* Layout shared by the supported front-panel controllers. */
struct panel {
    const method_t *methods;
    unsigned next;
    unsigned debounce_ms;
    unsigned elapsed_ms;
    unsigned hold_ms;
    unsigned repeats;
    unsigned repeat_ms;
    u8 state;
    u8 pad_1d;
    u16 previous_mask;
    u8 pending;
    u8 pad_21;
    u16 initial_mask;
    u16 profile_index;
    u16 pad_26;
    u8 calibration;
    u8 pad_29[3];
    const void *profile;
    u16 pressed;
    u16 pad_32;
    unsigned gpio_count;
    u16 allowed;
};

/* A private copy of the vtable also owns our state. The stock object and its
 * addresses stay unchanged; no writable payload section or fixed RAM slot is
 * needed. Allocation lasts for the lifetime of the front-panel singleton.
 */
struct button_runtime {
    method_t methods[PANEL_METHODS];
    const method_t *original;
    unsigned held_ms;
    unsigned pending_ms;
    u16 buttons;
    u8 cancelled;
    u8 debounced;
    u8 pending_event;
    volatile u8 updating;
};

extern struct panel *front_panel_input_init(struct panel *panel);
extern void *malloc(unsigned size);
extern const struct button_hook_entry *const button_hook_registry;

static unsigned irq_save(void)
{
    unsigned saved;
    __asm__ volatile ("mrs %0, primask\n\tcpsid i" : "=r" (saved) :: "memory");
    return saved;
}

static void irq_restore(unsigned saved)
{
    __asm__ volatile ("msr primask, %0" :: "r" (saved) : "memory");
}

static void reset_gesture(struct button_runtime *state)
{
    state->held_ms = state->pending_ms = 0;
    state->buttons = state->pending_event = state->debounced = 0;
    /* Ignore keys already held at boot or when the GUI resets its input. */
    state->cancelled = 1;
}

static void clear_pending(struct panel *panel)
{
    struct button_runtime *state = (void *)panel->methods;
    unsigned saved = irq_save();
    ((void (*)(struct panel *))state->original[PANEL_CLEAR])(panel);
    reset_gesture(state);
    irq_restore(saved);
}

static int configure(struct panel *panel, unsigned profile)
{
    struct button_runtime *state = (void *)panel->methods;
    int result = ((int (*)(struct panel *, unsigned))state->original[PANEL_CONFIGURE])(
        panel, profile);
    clear_pending(panel);
    return result;
}

/* Track every stock sample, not just GUI polls. Any additional key cancels a
 * standalone hold until all keys are up, including either order of Home+dial.
 * Actions remain pending until the GUI consumes input; none run in this task.
 */
static void update(struct panel *panel, unsigned elapsed_ms)
{
    struct button_runtime *state = (void *)panel->methods;
    state->updating = 1;
    __asm__ volatile ("" ::: "memory");
    ((void (*)(struct panel *, unsigned))state->original[PANEL_UPDATE])(panel, elapsed_ms);

    unsigned pressed = panel->pressed;
    if (panel->calibration) {
        reset_gesture(state);
    } else if (!pressed) {
        if (!state->cancelled && state->debounced) {
            state->pending_event = state->buttons == KEY_HOME ?
                BUTTON_HOME_HOLD : BUTTON_ENCODER_HOLD;
            state->pending_ms = state->held_ms + elapsed_ms;
        }
        state->buttons = state->debounced = state->cancelled = 0;
        state->held_ms = 0;
    } else {
        if (!state->buttons) {
            state->buttons = pressed;
        } else {
            state->held_ms += elapsed_ms;
        }
        if (pressed != state->buttons ||
                (pressed != KEY_HOME && pressed != KEY_ENCODER)) {
            state->cancelled = 1;
        }
        if (panel->state >= 2 &&
                (panel->allowed ^ panel->previous_mask) == state->buttons) {
            state->debounced = 1;
        }
    }
    __asm__ volatile ("" ::: "memory");
    state->updating = 0;
}

struct panel *start(struct panel *panel)
{
    front_panel_input_init(panel);
    if (button_hook_registry == (const void *)0xffffffffu)
        return panel;

    struct button_runtime *state = malloc(sizeof(*state));
    if (!state)
        return panel;
    state->original = panel->methods;
    for (unsigned i = 0; i < PANEL_METHODS; ++i)
        state->methods[i] = panel->methods[i];
    state->methods[PANEL_UPDATE] = (method_t)update;
    state->methods[PANEL_CONFIGURE] = (method_t)configure;
    state->methods[PANEL_CLEAR] = (method_t)clear_pending;
    state->updating = 0;
    reset_gesture(state);
    panel->methods = state->methods;
    return panel;
}

static int dispatch(unsigned event, unsigned held_ms)
{
    int consumed = 0;
    if (!event)
        return 0;
    for (const struct button_hook_entry *entry = button_hook_registry;
            entry->handler; ++entry) {
        if (entry->event == event && held_ms >= entry->hold_ms) {
            int handled = entry->handler(event, held_ms);
            consumed |= handled && entry->consume;
        }
    }
    return consumed;
}

/* Replaces only the GUI's take-event call. Calibration readers retain stock
 * events. Snapshot the mailbox with interrupts masked; if the 10 ms producer
 * was preempted mid-update, leave both mailboxes untouched until the next poll.
 * Feature handlers run after interrupts have been restored.
 */
void button_hooks_take_event(struct panel *panel, u8 *event)
{
    if (panel->methods[PANEL_UPDATE] != (method_t)update) {
        ((void (*)(struct panel *, u8 *))panel->methods[PANEL_TAKE])(panel, event);
        return;
    }

    struct button_runtime *state = (void *)panel->methods;
    unsigned saved = irq_save();
    if (state->updating) {
        *event = 0;
        irq_restore(saved);
        return;
    }
    ((void (*)(struct panel *, u8 *))state->original[PANEL_TAKE])(panel, event);
    unsigned held_ms = state->pending_ms;
    unsigned held_event = state->pending_event;
    state->pending_event = 0;
    unsigned calibration = panel->calibration;
    irq_restore(saved);

    if (calibration)
        return;
    if (dispatch(held_event, held_ms) && *event == held_event - 0x10)
        *event = 0;
    if (dispatch(*event, 0))
        *event = 0;
}

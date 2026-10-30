#ifndef BUTTON_HOOKS_H
#define BUTTON_HOOKS_H

enum button_event {
    BUTTON_START_STOP = 1,
    BUTTON_START_STOP_HOLD = 2,
    BUTTON_HOME = 3,
    BUTTON_ENCODER = 4,
    BUTTON_CLINICAL_MENU = 7,
    BUTTON_AUX_8 = 8,
    BUTTON_AUX_9 = 9,
    BUTTON_HOME_HOLD = 0x13,
    BUTTON_ENCODER_HOLD = 0x14,
};

enum button_hook_flags {
    BUTTON_HOOK_CONSUME = 1,
    BUTTON_HOOK_AT_THRESHOLD = 2,
};

/* Called in the GUI input task. Return nonzero when the action was handled;
 * a consuming registration then suppresses the corresponding stock event.
 * held_ms is supplied for the two HOLD events, zero otherwise.
 */
typedef int (*button_handler_t)(unsigned event, unsigned held_ms);

struct button_hook_entry {
    button_handler_t handler;
    unsigned short event;
    unsigned short flags;
    unsigned hold_ms;
};

#endif

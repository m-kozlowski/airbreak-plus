typedef struct {
    int cursor, fill, positive, negative, prefix;
    int positive_valid, negative_valid, prefix_valid, confirmed;
    int ready, window_notice, cycle_notice, window_observer, cycle_observer;
    int sequence;
} Capture;

/* Capture phase boundaries in the circular flow buffer. Slots hold the cursor,
 * two window pairs, two phase starts, and the measured inspiratory duration. */
void capture_update(Capture *c, unsigned events, float flow, float *samples, int *slots) {
    if (c->sequence != 3) c->ready = 0;
    if (++c->cursor == 1000) c->cursor = 0;
    samples[c->cursor] = flow;
    slots[0] = c->cursor;
    if (c->fill < 1000) ++c->fill;
    if (c->cursor == c->positive) c->positive_valid = 0;
    if (c->cursor == c->negative) c->negative_valid = 0;
    if (c->cursor == c->prefix) c->prefix_valid = 0;
    if (events & (1u << 10)) { c->positive = c->cursor; c->positive_valid = 1; }
    if (events & (1u << 11)) { c->negative = c->cursor; c->negative_valid = 1; }
    if (events & (1u << 13)) {
        if (c->sequence == 1) c->sequence = 2;
        if (c->window_notice == 2) c->window_notice = 0;
        c->confirmed = 1;
        if (c->positive_valid == 1) {
            c->positive_valid = 2;
            if (c->negative_valid == 2) {
                if (c->prefix_valid) c->ready = 1;
                if (!c->cycle_notice) {
                    slots[5] = c->negative;
                    slots[1] = c->positive;
                    c->cycle_notice = 1;
                }
            }
            int distance = (c->cursor - c->positive + 1000) % 1000;
            if (c->fill > distance) { c->prefix = c->positive; c->prefix_valid = 1; }
        } else { c->positive_valid = 0; c->cycle_notice = 0; }
    }
    if (events & (1u << 12)) {
        if (!c->sequence) c->sequence = 1;
        else if (c->sequence == 2) c->sequence = 3;
        if (c->cycle_notice == 2) c->cycle_notice = 0;
        c->confirmed = 2;
        c->negative_valid = c->negative_valid == 1 ? 2 : 0;
    }
    if (!c->window_notice && c->confirmed == 2 && c->negative_valid == 2 &&
            c->positive_valid == 2 && c->prefix_valid) {
        slots[6] = c->positive;
        slots[2] = c->negative;
        slots[3] = c->prefix;
        slots[4] = c->negative;
        c->window_notice = 1;
    }
}

/* Two-pass observer acknowledgement is retained across the 10 Hz/100 Hz tasks. */
unsigned capture_notifications(Capture *c) {
    unsigned events = 0;
    if (c->window_observer) { c->window_observer = 0; c->window_notice = 2; }
    else if (c->window_notice == 1) { events |= 1u << 15; c->window_observer = 1; }
    if (c->sequence == 3 && c->ready) { c->ready = 0; events |= 1u << 13; }
    if (c->cycle_observer) { c->cycle_observer = 0; c->cycle_notice = 2; }
    else if (c->cycle_notice == 1) { events |= 1u << 14; c->cycle_observer = 1; }
    return events;
}

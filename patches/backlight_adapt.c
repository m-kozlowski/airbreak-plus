/*
 * backlight_adapt.c - Continuous steady-state backlight adaptation
 *
 * Replaces the "bl backlight_state_machine" call from the backlight tick.
 *
 * State 0 is the steady "screen on" loop. Nonzero states handle wake,
 * timeout dim, and off transitions in stock firmware.
 *
 * After stock wake/start-stop/dim/off transitions, this hook briefly reasserts
 * the ambient targets so the stock transition tail cannot leave stale levels.
 *
 * Start/stop while steady uses per-channel transition flags at 0x4C..0x50
 * without changing ctx->state. We advance those channel transitions here, but
 * avoid the stock helper that would also reset the idle timer every tick.
 *
 * Uses firmware variables for all brightness levels:
 *   ASF - ambient sensor filtered
 *   ATH - ambient threshold
 *   LBL - button backlight low
 *   LLL - LCD backlight low
 *   LBH - button backlight high
 *   LLH - LCD backlight high
 *
 * LCD and buttons stay at their low level up to ATH, then ramp smoothly
 * toward their high level at the configurable full-brightness threshold.
 */

#include "s10_vars.h"

// STEP value doesnt change much, as code relies on filtered sensor value
// that gets updated at roughly the same cadence as this hook, so each delta is near 0 anyway
// but it may come in handy in the future
#define LCD_STEP  10              // LCD fade step per tick
#define BTN_STEP  2               // button fade step per tick
                                  //
#define DEFAULT_FULL_ASF 0xC00    // fallback ASF value where linear mode reaches max
#define LCD_TARGET_DEADBAND 1     // ignore small LCD target changes caused by brief ASF spikes

#define RESUME_REASSERT_TICKS 12  // ticks to override the tail of stock transitions
#define PENDING_LCD 0x01
#define PENDING_BTN 0x02

extern int variable_get_by_id(int var_id);
extern void backlight_state_machine(void *ctx);
extern const unsigned short backlight_adapt_full_asf_var_id;

typedef void (*set_fn_t)(void *, int);
typedef void (*step_fn_t)(void *);

// backlight context struct (partial, offsets match firmware layout)
struct bl_ctx {
    unsigned char state;         // 0x00: 0=steady, nonzero=transition
    unsigned char phase;         // 0x01: stock transition/event state
    char _pad0[0x32];
    unsigned char dark_latch;    // 0x34: stock low/high selector
    unsigned char gate35;        // 0x35: stock steady-state gate
    unsigned char reassert_ticks; // 0x36: unused stock padding claimed by this patch
    unsigned char _pad1;
    void *ch_lcd;                // 0x38
    void *ch_btn0;               // 0x3C
    void *ch_btn1;               // 0x40
    void *ch_btn2;               // 0x44
    void *ch_btn3;               // 0x48
    unsigned char pending[5];    // 0x4C..0x50: stock per-channel transitions
};

static void __attribute__((noinline, section(".text.x.apply_step"))) apply_value(void *channel, int value)
{
    if (!channel)
        return;

    unsigned char *ch = (unsigned char *)channel;
    ch[5] = (unsigned char)value;

    // call channel->vtable[7] (set_brightness)
    unsigned int *vtable = *(unsigned int **)channel;
    set_fn_t set = (set_fn_t)vtable[7];
    set(channel, value);

    __asm volatile ("" ::: "memory");
}

static void __attribute__((noinline, section(".text.x.apply_step"))) apply_step(
    void *channel, int target, int step_size)
{
    if (!channel)
        return;

    unsigned char *ch = (unsigned char *)channel;
    int current = ch[5];

    if (current == target)
        return;

    int next;
    if (current > target) {
        next = current - step_size;
        if (next < target) next = target;
    } else {
        next = current + step_size;
        if (next > target) next = target;
    }

    apply_value(channel, next);

    // prevent tail call, compiler must return here
    __asm volatile ("" ::: "memory");
}

static void __attribute__((noinline, section(".text.x.apply_step"))) run_pending_transition(void *channel, int pending)
{
    if (!channel)
        return;

    unsigned int *vtable = *(unsigned int **)channel;
    step_fn_t step;

    if (pending == 1) {
        step = (step_fn_t)vtable[3];
    } else if (pending == 2) {
        step = (step_fn_t)vtable[4];
    } else {
        return;
    }

    step(channel);

    __asm volatile ("" ::: "memory");
}

static int __attribute__((noinline, section(".text.x.apply_step"))) run_pending_transitions(struct bl_ctx *ctx)
{
    int active = 0;

    // Replaying the stock pending transition on buttons makes them snap off on
    // therapy start/stop, then our ambient loop slowly restores them. Let the
    // custom ambient path own buttons; only advance the LCD pending transition.
    if (ctx->pending[0] != 0) {
        run_pending_transition(ctx->ch_lcd, ctx->pending[0]);
        active |= PENDING_LCD;
    }
    if (ctx->pending[1] != 0) {
        active |= PENDING_BTN;
    }
    if (ctx->pending[2] != 0) {
        active |= PENDING_BTN;
    }
    if (ctx->pending[3] != 0) {
        active |= PENDING_BTN;
    }
    if (ctx->pending[4] != 0) {
        active |= PENDING_BTN;
    }

    // Stock active-step normalizes phase 3 back to 1 after the per-channel
    // transition finishes. Keep that piece without touching its idle timer.
    if (ctx->phase == 3)
        ctx->phase = 1;

    if (active) {
        ctx->pending[0] = 0;
        ctx->pending[1] = 0;
        ctx->pending[2] = 0;
        ctx->pending[3] = 0;
        ctx->pending[4] = 0;
    }

    return active;
}

static unsigned char __attribute__((noinline, section(".text.x.apply_step"))) target_from_asf(
    int asf, int ath, int full_asf, unsigned char low, unsigned char high)
{
    if (asf <= ath)
        return low;

    if (ath >= full_asf || asf >= full_asf)
        return high;

    {
        int span = full_asf - ath;
        int level = low + ((asf - ath) * ((int)high - (int)low)) / span;

        if (level < low)
            level = low;
        if (level > high)
            level = high;

        return (unsigned char)level;
    }
}

static void __attribute__((noinline, section(".text.x.apply_step"))) apply_lcd_step(
    void *channel, unsigned char target, unsigned char low, unsigned char high)
{
    int current;
    int delta;
    int adjusted = target;

    if (!channel)
        return;

    current = ((unsigned char *)channel)[5];
    delta = current - target;
    if (delta < 0)
        delta = -delta;

    if (target != low && target != high) {
        if (delta <= LCD_TARGET_DEADBAND)
            return;

        // Advance only by the part of the target movement outside the
        // deadband. Exact low/high endpoints bypass it and remain reachable.
        if (current < target)
            adjusted -= LCD_TARGET_DEADBAND;
        else
            adjusted += LCD_TARGET_DEADBAND;
    }

    apply_step(channel, adjusted, LCD_STEP);
}

void start(struct bl_ctx *ctx)
{
    // Let stock own nonzero transition states. The stock constructor does not
    // initialize byte 0x36, so only values in our bounded counter range are
    // accepted when steady-state processing resumes.
    if (ctx->state != 0) {
        ctx->reassert_ticks = RESUME_REASSERT_TICKS;
        backlight_state_machine(ctx);
        return;
    }

    int full_asf = DEFAULT_FULL_ASF;

    if (backlight_adapt_full_asf_var_id != 0xFFFFu)
        full_asf = variable_get_by_id((int)backlight_adapt_full_asf_var_id);

    // A zero full-brightness threshold explicitly selects the unmodified
    // firmware state machine instead of the continuous adaptation path.
    if (full_asf == 0) {
        backlight_state_machine(ctx);
        return;
    }

    int reassert_ticks = ctx->reassert_ticks;
    if (reassert_ticks > RESUME_REASSERT_TICKS) {
        reassert_ticks = 0;
        ctx->reassert_ticks = 0;
    }

    int asf = variable_get_by_id(VAR_ID_ASF);
    int ath = variable_get_by_id(VAR_ID_ATH);
    unsigned char lcd_low = (unsigned char)variable_get_by_id(VAR_ID_LLL);
    unsigned char lcd_high = (unsigned char)variable_get_by_id(VAR_ID_LLH);
    unsigned char btn_low = (unsigned char)variable_get_by_id(VAR_ID_LBL);
    unsigned char btn_high = (unsigned char)variable_get_by_id(VAR_ID_LBH);
    unsigned char lcd_target = target_from_asf(asf, ath, full_asf, lcd_low, lcd_high);
    unsigned char btn_target = target_from_asf(asf, ath, full_asf, btn_low, btn_high);

    {
        int pending = run_pending_transitions(ctx);

        if (pending & PENDING_BTN) {
            // Buttons are ambient-owned. If stock queued a steady-state
            // transition, restore the desired level immediately instead of
            // leaving them off for one tick and ramping up slowly afterward.
            apply_value(ctx->ch_btn0, btn_target);
            apply_value(ctx->ch_btn1, btn_target);
            apply_value(ctx->ch_btn2, btn_target);
            apply_value(ctx->ch_btn3, btn_target);
        }
        if (pending & PENDING_LCD)
            return;
    }

    if (reassert_ticks > 0) {
        // During the post-transition window, keep outputs pinned to their
        // ambient-selected targets. For LCD this avoids wake overshoot where
        // stock briefly lands at LLH before the steady-state hook pulls it
        // back down.
        apply_value(ctx->ch_lcd, lcd_target);
        apply_value(ctx->ch_btn0, btn_target);
        apply_value(ctx->ch_btn1, btn_target);
        apply_value(ctx->ch_btn2, btn_target);
        apply_value(ctx->ch_btn3, btn_target);
        ctx->reassert_ticks = (unsigned char)(reassert_ticks - 1);
        return;
    }

    apply_lcd_step(ctx->ch_lcd, lcd_target, lcd_low, lcd_high);
    apply_step(ctx->ch_btn0, btn_target, BTN_STEP);
    apply_step(ctx->ch_btn1, btn_target, BTN_STEP);
    apply_step(ctx->ch_btn2, btn_target, BTN_STEP);
    apply_step(ctx->ch_btn3, btn_target, BTN_STEP);

    // prevent tail call
    __asm volatile ("" ::: "memory");
}

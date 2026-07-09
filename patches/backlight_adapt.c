/*
 * backlight_adapt.c - Continuous steady-state backlight adaptation
 *
 * Replaces the "bl backlight_state_machine" call from the backlight tick.
 *
 * State 0 is the steady "screen on" loop. Nonzero states handle wake,
 * timeout dim, and off transitions in stock firmware.
 *
 * After stock wake/start-stop/dim/off transitions, this hook waits briefly
 * before resuming active ambient control so it does not fight their tail end.
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
 * Buttons keep the existing binary low/high behavior around ATH.
 * LCD stays at LLL up to ATH, then ramps smoothly toward LLH and clamps
 * at LCD_FULL_ASF.
 */

#include "s10_vars.h"

// STEP value doesnt change much, as code relies on filtered sensor value
// that gets updated at roughly the same cadence as this hook, so each delta is near 0 anyway
// but it may come in handy in the future
#define LCD_STEP  10              // LCD fade step per tick
#define BTN_STEP  2               // button fade step per tick
                                  //
#define MIN_HYST         0x10     // minimum ASF hysteresis around ATH
#define LCD_FULL_ASF     0xC00    // ASF value where linear LCD mode reaches max
#define LCD_LINEAR_ADAPT 1        // 1 = linear LCD ramp above ATH, 0 = legacy two-stage LCD mode
#define BTN_LINEAR_ADAPT 1        // 1 = linear button ramp above ATH, 0 = legacy two-stage button mode
#define BTN_FULL_ASF LCD_FULL_ASF // ASF value where linear button mode reaches max
#define LCD_TARGET_DEADBAND 6     // ignore small LCD target changes caused by brief ASF spikes

#define MODE_DARK 0x01
#define MODE_DELAY_SHIFT 1
#define MODE_DELAY_MASK  0x3E
#define MODE_INIT 0x80
#define RESUME_DELAY 12           // ticks to wait after stock transitions before adaptation
#define PENDING_LCD 0x01
#define PENDING_BTN 0x02

extern int variable_get_g8(int var_id);
extern void backlight_state_machine(void *ctx);

// backlight context struct (partial, offsets match firmware layout)
struct bl_ctx {
    unsigned char state;         // 0x00: 0=steady, nonzero=transition
    unsigned char phase;         // 0x01: stock transition/event state
    char _pad0[0x32];
    unsigned char dark_latch;    // 0x34: stock low/high selector
    unsigned char gate35;        // 0x35: stock steady-state gate
    unsigned char mode;          // 0x36: 0=bright, 1=dark
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
    typedef void (*set_fn_t)(void *, int);
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

    ch[5] = (unsigned char)next;

    // call channel->vtable[7] (set_brightness)
    typedef void (*set_fn_t)(void *, int);
    unsigned int *vtable = *(unsigned int **)channel;
    set_fn_t set = (set_fn_t)vtable[7];
    set(channel, next);

    // prevent tail call, compiler must return here
    __asm volatile ("" ::: "memory");
}

static void __attribute__((noinline, section(".text.x.apply_step"))) run_pending_transition(void *channel, int pending)
{
    if (!channel)
        return;

    typedef void (*step_fn_t)(void *);
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

static unsigned char __attribute__((noinline, section(".text.x.apply_step"))) lcd_target_from_asf(
    int asf, int ath, unsigned char low, unsigned char high, int dark_mode)
{
#if LCD_LINEAR_ADAPT
    if (asf <= ath)
        return low;

    if (ath >= LCD_FULL_ASF || asf >= LCD_FULL_ASF)
        return high;

    {
        int span = LCD_FULL_ASF - ath;
        int level = low + ((asf - ath) * ((int)high - (int)low)) / span;

        if (level < low)
            level = low;
        if (level > high)
            level = high;

        return (unsigned char)level;
    }
#else
    (void)asf;
    (void)ath;

    if (dark_mode)
        return low;
    return high;
#endif
}

static unsigned char __attribute__((noinline, section(".text.x.apply_step"))) stabilize_lcd_target(
    void *channel, unsigned char target)
{
#if LCD_LINEAR_ADAPT
    int current;
    int delta;
    int adjusted;

    if (!channel)
        return target;

    current = ((unsigned char *)channel)[5];
    delta = current - target;
    if (delta < 0)
        delta = -delta;

    if (delta <= LCD_TARGET_DEADBAND)
        return (unsigned char)current;

    if (current < target) {
        adjusted = current + (delta - LCD_TARGET_DEADBAND);
        if (adjusted > target)
            adjusted = target;
    } else {
        adjusted = current - (delta - LCD_TARGET_DEADBAND);
        if (adjusted < target)
            adjusted = target;
    }

    return (unsigned char)adjusted;
#else
    (void)channel;
#endif

    return target;
}

static unsigned char __attribute__((noinline, section(".text.x.apply_step"))) btn_target_from_asf(
    int asf, int ath, unsigned char low, unsigned char high, int dark_mode)
{
#if BTN_LINEAR_ADAPT
    if (asf <= ath)
        return low;

    if (ath >= BTN_FULL_ASF || asf >= BTN_FULL_ASF)
        return high;

    {
        int span = BTN_FULL_ASF - ath;
        int level = low + ((asf - ath) * ((int)high - (int)low)) / span;

        if (level < low)
            level = low;
        if (level > high)
            level = high;

        return (unsigned char)level;
    }
#else
    (void)asf;
    (void)ath;

    if (dark_mode)
        return low;
    return high;
#endif
}

void start(struct bl_ctx *ctx)
{
    int asf = variable_get_g8(VAR_ID_ASF);
    //int asf = variable_get_g8(VAR_ID_ASR);
    int ath = variable_get_g8(VAR_ID_ATH);
    unsigned char lcd_low = (unsigned char)variable_get_g8(VAR_ID_LLL);
    unsigned char lcd_high = (unsigned char)variable_get_g8(VAR_ID_LLH);
    unsigned char btn_low = (unsigned char)variable_get_g8(VAR_ID_LBL);
    unsigned char btn_high = (unsigned char)variable_get_g8(VAR_ID_LBH);

    // hysteresis deadband = max(ATH >> 5, MIN_HYST)
    int hyst = ath >> 5;
    if (hyst < MIN_HYST)
        hyst = MIN_HYST;

    int mode = ctx->mode;
    int delay = (mode & MODE_DELAY_MASK) >> MODE_DELAY_SHIFT;

    if ((mode & MODE_INIT) == 0) {
        mode = (asf < ath) ? MODE_DARK : 0;
        delay = 0;
    } else {
        mode &= MODE_DARK;
        if (mode == 0) {
            if (asf + hyst < ath)
                mode = MODE_DARK;
        } else {
            if (asf > ath + hyst)
                mode = 0;
        }
    }

    ctx->dark_latch = (unsigned char)(mode & MODE_DARK);

    unsigned char lcd_target = lcd_target_from_asf(
        asf, ath, lcd_low, lcd_high, mode & MODE_DARK);
    lcd_target = stabilize_lcd_target(ctx->ch_lcd, lcd_target);
    unsigned char btn_target = btn_target_from_asf(
        asf, ath, btn_low, btn_high, mode & MODE_DARK);

    // Let stock own nonzero transition states, then hold off briefly after it
    // returns to steady so we don't snap the levels back mid-transition.
    if (ctx->state != 0) {
        ctx->mode = (unsigned char)(MODE_INIT | (mode & MODE_DARK) |
                                    ((RESUME_DELAY << MODE_DELAY_SHIFT) & MODE_DELAY_MASK));
        backlight_state_machine(ctx);
        return;
    }

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

    if (delay > 0) {
        // During the post-transition cooldown, keep outputs pinned to their
        // ambient-selected targets. For LCD this avoids wake overshoot where
        // stock briefly lands at LLH before the steady-state hook pulls it
        // back down.
        apply_value(ctx->ch_lcd, lcd_target);
        apply_value(ctx->ch_btn0, btn_target);
        apply_value(ctx->ch_btn1, btn_target);
        apply_value(ctx->ch_btn2, btn_target);
        apply_value(ctx->ch_btn3, btn_target);
        delay--;
        ctx->mode = (unsigned char)(MODE_INIT | (mode & MODE_DARK) |
                                    ((delay << MODE_DELAY_SHIFT) & MODE_DELAY_MASK));
        return;
    }

    ctx->mode = (unsigned char)(MODE_INIT | (mode & MODE_DARK));

    apply_step(ctx->ch_lcd,  lcd_target, LCD_STEP);
    apply_step(ctx->ch_btn0, btn_target, BTN_STEP);
    apply_step(ctx->ch_btn1, btn_target, BTN_STEP);
    apply_step(ctx->ch_btn2, btn_target, BTN_STEP);
    apply_step(ctx->ch_btn3, btn_target, BTN_STEP);

    // prevent tail call
    __asm volatile ("" ::: "memory");
}

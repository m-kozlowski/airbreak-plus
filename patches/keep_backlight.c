/* Keep-awake requests and button feedback, independent of the graph payload. */
typedef unsigned char u8;
typedef void (*method_t)(void);
typedef int (*request_t)(void);

enum {
    PWM_ENABLE = 3,
    PWM_METHODS = 6,
    BLINK_MS = 150,
};

struct pwm {
    const method_t *methods;
};

/* Clone only the PWM controller's methods, leaving its stock object in place.
 * The clone owns our RAM state for the singleton's lifetime. LED gating tracks
 * the current stock requests even during feedback, without touching brightness.
 */
struct keep_state {
    method_t methods[PWM_METHODS];
    const method_t *original;
    unsigned timer[3];
    u8 manual;
    u8 pending;
    u8 phases;
    u8 dark;
    u8 outputs;
};

extern void *malloc(unsigned size);
extern void pwm_controller_init(struct pwm *pwm);
extern struct pwm *pwm_controller_get(void);
extern void backlight_output_timeout_update(void *ctx);
extern void backlight_outputs_apply_state(void *ctx);
extern void millisecond_timer_init(void *timer, unsigned elapsed);
extern int millisecond_timer_expired(void *timer, unsigned ms);
extern const request_t *const keep_backlight_requests;

static void output_enable(struct pwm *pwm, unsigned output, int enabled)
{
    struct keep_state *state = (void *)pwm->methods;
    /* The two navigation lights use outputs 0 and 3; Start/Stop uses 1 and 2. */
    if (output == 0 || output == 3) {
        unsigned bit = 1u << output;
        state->outputs = (state->outputs & ~bit) | (enabled == 1 ? bit : 0);
        if (state->dark)
            enabled = 0;
    }
    ((void (*)(struct pwm *, unsigned, int))state->original[PWM_ENABLE])(
        pwm, output, enabled);
}

struct pwm *keep_backlight_init(struct pwm *pwm)
{
    pwm_controller_init(pwm);
    struct keep_state *state = malloc(sizeof(*state));
    if (!state)
        return pwm;
    state->original = pwm->methods;
    for (unsigned i = 0; i < PWM_METHODS; ++i)
        state->methods[i] = pwm->methods[i];
    state->methods[PWM_ENABLE] = (method_t)output_enable;
    state->manual = state->pending = state->phases = state->dark = state->outputs = 0;
    pwm->methods = state->methods;
    return pwm;
}

static struct keep_state *get_state(struct pwm *pwm)
{
    return pwm->methods[PWM_ENABLE] == (method_t)output_enable ?
        (void *)pwm->methods : 0;
}

/* button_hooks calls this in the GUI task when a standalone hold reaches 3 s.
 * Let the next backlight tick wake the screen and begin the acknowledgement.
 */
int keep_backlight_toggle(unsigned event, unsigned held_ms)
{
    struct keep_state *state = get_state(pwm_controller_get());
    if (!state)
        return 0;
    state->manual ^= 1;
    /* Dark/light phases: one pulse needs one phase, two pulses need three. */
    state->pending = state->manual ? 1 : 3;
    return 1;
}

static void apply_feedback(struct pwm *pwm, struct keep_state *state)
{
    for (unsigned output = 0; output <= 3; output += 3) {
        int enabled = !state->dark && (state->outputs & (1u << output));
        ((void (*)(struct pwm *, unsigned, int))state->original[PWM_ENABLE])(
            pwm, output, !!enabled);
    }
}

static int requested(void)
{
    if (keep_backlight_requests)
        for (const request_t *entry = keep_backlight_requests; *entry; ++entry)
            if ((*entry)())
                return 1;
    return 0;
}

/* Hook the timeout call, before stock ambient and output updates. Each request
 * refreshes the normal idle timer; the final request ending leaves a full
 * timeout. Wake retains the GUI-selected timeout policy, including post-therapy.
 */
void start(void *ctx)
{
    u8 *backlight = ctx;
    struct pwm *pwm = pwm_controller_get();
    struct keep_state *state = get_state(pwm);
    int pending = state && state->pending;
    int keep = (state && state->manual) || requested();

    /* State 3 is Lumis alarm indication. Leave its output policy in charge. */
    if (backlight[0] <= 2 && (pending || keep)) {
        if (backlight[0]) {
            u8 phase = backlight[1];
            backlight_outputs_apply_state(ctx);
            backlight[1] = phase;
        } else {
            millisecond_timer_init(backlight + 4, 0);
        }
    }

    if (state) {
        if (backlight[0] == 3) {
            state->pending = state->phases = state->dark = 0;
            apply_feedback(pwm, state);
        } else if (pending) {
            state->phases = state->pending;
            state->pending = 0;
            state->dark = 1;
            millisecond_timer_init(state->timer, 0);
            apply_feedback(pwm, state);
        } else if (state->phases && millisecond_timer_expired(state->timer, BLINK_MS)) {
            --state->phases;
            state->dark = state->phases && !state->dark;
            millisecond_timer_init(state->timer, 0);
            apply_feedback(pwm, state);
        }
    }
    backlight_output_timeout_update(ctx);
}

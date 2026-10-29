#include "../s10_vars.h"

typedef struct Node Node;
typedef void (*Method)(Node *);
struct Node { const Method *methods; Node *next; u32 enabled; };
#define SLOT(type, size) union { type data; u32 storage[(size) / 4]; }
/* One allocation owns both scheduler nodes, analysis scratch and persistent
 * histories. Reserved object spans keep the audited state layout intact.
 * Only the fast/slow prefixes are registered with the stock worker manager.
 */
typedef struct {
    Node fast, slow;
    int configured;
    float lower, upper;
    u32 fast_events, slow_events;
    struct { float inhale, exhale; u32 first_measured; } timing;
    u32 ventilation_seen_negative;
    u32 enable_header[3];
    SLOT(Detector, 52) phase;
    SLOT(Capture, 132) capture;
    struct { u32 headers[3]; float snapshot; u32 rest[4]; float scratch[200]; } shape;
    u32 qualification[3], landmark[3], fit[3], segments[3], harmonic[3], membership[3], index[3];
    SLOT(ShapeHistory, 72) shape_history;
    SLOT(Reduced, 36) reduced;
    SLOT(EventHistory, 224) events;
    SLOT(Pressure, 52) pressure;
    int capture_slots[8], control[10];
    float segment_values[8], fit_values[5], memberships[6], results[9], combined[2];
} Autoepap;
_Static_assert(sizeof(Autoepap) == 1748, "reused estimator private state");
_Static_assert(sizeof(EventHistory) <= 224, "event history source span");

extern void therapy_variable_get_float(float **, int);
extern void *therapy_variable_get(int **, int);
extern void *therapy_manager_get(void);
extern void *malloc(unsigned);
extern void therapy_worker_append(Node *, int);
extern int variable_get_by_id(int);
extern void variable_set_by_id(int, int);
extern int system_tick_get(void);
extern void *ivaps_ventilation_estimator_register(void);
extern void ivaps_settings_update(void *);
extern void therapy_mode67_pressure_waveform_worker_update(void *);

extern const volatile unsigned short autoepap_enable_id, autoepap_lower_id, autoepap_upper_id;
extern int (*const volatile autoepap_effective_fall)(int, int);
extern float *const stock_flow_samples;
static const Method fast_methods[7], slow_methods[7];

static float *fref(int index) { float *p; therapy_variable_get_float(&p, index); return p; }
static int *iref(int index) { int *p; therapy_variable_get(&p, index); return p; }
static float *flow_samples(void) { return stock_flow_samples; }

Autoepap *autoepap_find(void) {
    /* Group 2 owns the fast node. Its vtable identifies our state without
     * reserving a writable global or borrowing another worker's RAM. */
    Node *node = *(Node **)((unsigned char *)therapy_manager_get() + 0x10);
    while (node && node->methods != fast_methods) node = node->next;
    return (Autoepap *)node;
}

int autoepap_active(const Autoepap *s) {
    return s && s->configured && *iref(0x6f) == 6 && s->lower != s->upper;
}

int autoepap_on(void) { return autoepap_active(autoepap_find()); }

void autoepap_load_settings(Autoepap *s) {
    s->configured = autoepap_enable_id != 0xffff && variable_get_by_id(autoepap_enable_id) != 0;
    s->lower = *fref(0x0f);
    s->upper = s->lower;
    if (s->configured) {
        /* Custom pressure descriptors use the stock pressure scale of 50. */
        if (autoepap_lower_id != 0xffff) s->lower = (float)variable_get_by_id(autoepap_lower_id) / 50.0f;
        if (autoepap_upper_id != 0xffff) s->upper = (float)variable_get_by_id(autoepap_upper_id) / 50.0f;
    }
}

void autoepap_settings_hook(void *ctx) {
    ivaps_settings_update(ctx);
    Autoepap *s = autoepap_find();
    if (s) autoepap_load_settings(s);
}

extern void variable_lookup_handler(u32 *, int, int);
extern void variable_handler_release(u32 *);
extern void variable_set_visible_from_handler(u32 *, int);
extern void g4_numeric_set_dynamic_min(void *, int);
extern void g4_numeric_set_dynamic_max(void *, int);

static void autoepap_set_visible(int var_id, int visible) {
    u32 ctx[16];
    variable_lookup_handler(ctx, var_id, 0);
    variable_set_visible_from_handler(ctx, visible);
    variable_handler_release(ctx);
}

/* Read settings directly so startup callbacks also work before worker creation.
 * The MOP dispatcher calls this after stock visibility; the generic custom-menu
 * handler leaves these pressure bounds to us.
 */
void autoepap_apply_mode_visibility(void) {
    if (autoepap_enable_id == 0xffff || autoepap_lower_id == 0xffff || autoepap_upper_id == 0xffff)
        return;
    int ivaps = variable_get_by_id(VAR_ID_MOP) == 9;
    int enabled = variable_get_by_id(autoepap_enable_id) != 0;
    autoepap_set_visible(VAR_ID_EPI, ivaps && !enabled);
    autoepap_set_visible(autoepap_lower_id, ivaps && enabled);
    autoepap_set_visible(autoepap_upper_id, ivaps && enabled);
}

/* Match the paired stock pressure controls: each bound limits the other.
 * The generic lookup stores its concrete handler pointer at +0x38.
 * Notify the normal settings-refresh queue, not the therapy worker directly.
 */
void autoepap_setting_changed(void) {
    if (autoepap_lower_id != 0xffff && autoepap_upper_id != 0xffff) {
        u32 ctx[15];
        variable_lookup_handler(ctx, autoepap_lower_id, 0);
        g4_numeric_set_dynamic_max((void *)ctx[14], variable_get_by_id(autoepap_upper_id));
        variable_handler_release(ctx);
        variable_lookup_handler(ctx, autoepap_upper_id, 0);
        g4_numeric_set_dynamic_min((void *)ctx[14], variable_get_by_id(autoepap_lower_id));
        variable_handler_release(ctx);
    }
    autoepap_apply_mode_visibility();
    variable_set_by_id(VAR_ID_SCT, system_tick_get());
}

static void clear_bytes(void *memory, unsigned size) {
    unsigned char *p = memory;
    while (size--) *p++ = 0;
}

/* Profile callbacks reset histories even for 6 -> 6. Ordinary settings reload
 * does not call this method. Detector and observer state have narrower resets. */
void autoepap_mode(Node *node) {
    Autoepap *s = (Autoepap *)node;
    int previous = s->fast.enabled;
    if (!previous) {
        clear_bytes(&s->phase, sizeof(s->phase));
        s->phase.data.accumulate_after_test = 1;
    }
    /* Lumis retains the outer capture sequence and both observer acknowledgments. */
    clear_bytes(&s->capture.data, __builtin_offsetof(Capture, window_observer));
    s->shape.snapshot = 0;
    clear_bytes(&s->reduced, sizeof(s->reduced));
    s->events.data.count = s->events.data.valid = 0;
    s->events.data.shape_active = s->events.data.shape_start = s->events.data.shape_ticks = 0;
    s->events.data.reduced_active = s->events.data.reduced_start = 0;
    s->events.data.reduced_pressure = 0;
    clear_bytes(s->control + 1, 8 * sizeof(*s->control));
    clear_bytes(s->segment_values, sizeof(s->segment_values));
    clear_bytes(s->fit_values, sizeof(s->fit_values));
    s->combined[0] = 0;
    clear_bytes(s->results, 8 * sizeof(*s->results));
    clear_bytes(&s->pressure, sizeof(s->pressure));
    s->fast_events = s->slow_events = 0;
    s->fast.enabled = s->slow.enabled = *iref(0x12) == 6;
    s->control[6] = -1;
    s->pressure.data.lower = s->lower;
    s->pressure.data.upper = s->upper;
    s->pressure.data.target = s->results[7] = s->lower;
    shape_history_reset(&s->shape_history.data);
    if (*iref(0x12) == 6 && s->configured && s->lower != s->upper)
        clear_bytes(flow_samples(), 4000);
}

static void autoepap_stop(Node *node) {
    Autoepap *s = (Autoepap *)node;
    s->fast.enabled = s->slow.enabled = 0;
}

/* Stock waveform lookups cache EPAP at initialization/expiration. Keep
 * that cache meaningful when adaptation is subsequently disabled mid-breath. */
void *autoepap_epap_ref(float **output, int index) {
    Autoepap *s = autoepap_find();
    int profile = *iref(0x12);
    if (s && (profile == 6 || profile == 7))
        *output = autoepap_active(s) ? s->results + 7 : &s->lower;
    else therapy_variable_get_float(output, index);
    return output;
}

/* Composite nodes own lifetime storage; their prefix destructors do not free it. */
static void lifecycle_noop(Node *node) { (void)node; }
static void detector_noop(void *ctx, int time) { (void)ctx; (void)time; }
static void detector_duration(void *ctx, int duration) { ((Autoepap *)ctx)->capture_slots[7] = duration; }
static void detector_event(void *ctx, unsigned event) { ((Autoepap *)ctx)->fast_events |= 1u << event; }

void autoepap_fast(Node *node) {
    Autoepap *s = (Autoepap *)node;
    s->fast_events = 0;
    s->control[0] = autoepap_active(s);
    if (!s->control[0]) return;
    float target = *fref(0x18);
    DetectorOutput callbacks = {s, detector_noop, detector_noop, detector_duration, detector_event};
    float filtered = *fref(0x46);
    detect_phase(&s->phase.data, &callbacks, filtered, 1.2f,
                 phase_volume_threshold(*fref(0x1d), target) * 6.0f, *iref(0));
    capture_update(&s->capture.data, s->fast_events, filtered, flow_samples(), s->capture_slots);
    float deviation = *fref(0xb5);
    s->shape.snapshot = deviation;
    if (*iref(0x76)) return;
    s->fast_events |= reduced_flow_update(&s->reduced.data, flow_samples(), s->capture_slots[0],
                                         target, deviation, *fref(0x23),
                                         s->results + 5, s->control + 9, s->results + 4);
    s->control[8] = s->reduced.data.active;
    reduced_history_capture(&s->events.data, s->fast_events, *iref(0), s->results[4], s->results[7]);
}

static Span span_between(int start, int end) {
    Span span = {flow_samples(), start, (end - start + 1000) % 1000};
    return span;
}

void autoepap_slow(Node *node) {
    Autoepap *s = (Autoepap *)((unsigned char *)node - __builtin_offsetof(Autoepap, slow));
    s->slow_events = 0;
    if (!autoepap_active(s)) {
        pressure_target(&s->pressure.data, s->results + 7, s->results + 8,
                        0, 0, 0, s->lower, 0, 0, 0, 0);
        return;
    }
    s->slow_events = capture_notifications(&s->capture.data);
    int *c = s->capture_slots;
    Span inhale = span_between(c[6], c[2]);
    Span exhale = span_between(c[5], c[1]);
    float target = *fref(0x18);
    if (s->slow_events & (1u << 13))
        s->control[7] = shape_event(&inhale, &exhale, c[2], c[6], c[1], s->shape.snapshot, s->shape.scratch);
    if (s->slow_events & (1u << 13)) s->control[6] = breath_landmark(&inhale);
    if (s->slow_events & (1u << 15)) {
        Span qualified;
        s->control[4] = qualify_window(&inhale, target, &qualified);
        s->control[1] = qualified.start;
        s->control[2] = (qualified.start + qualified.count) % 1000;
        s->control[3] = qualified.count;
        int fall = *iref(0x0e);
        if (autoepap_effective_fall != (void *)0xffffffffu) fall = autoepap_effective_fall(1, fall);
        s->combined[0] = produce_fit(&qualified, *iref(0x0d), fall, target, s->fit_values);
        s->control[5] = produce_segments(&qualified, s->segment_values);
        s->combined[1] = shape_memberships(s->segment_values, s->control[5], s->combined[0], s->memberships);
    }
    if (s->slow_events & (1u << 13)) {
        s->results[0] = harmonic_ratio(&inhale, s->control[6]);
        s->results[1] = breath_shape_index(s->results[0], c[7]);
    }
    if ((s->slow_events & (1u << 13)) && !*iref(0x76)) {
        Span breath = span_between(c[6], c[1]);
        s->results[2] = shape_pressure(&s->shape_history.data, &breath, s->control[4], target,
                                      *fref(0x1d), s->results[1], s->combined[1], s->results[7],
                                      *fref(0x23), s->results + 3);
        s->results[6] = shape_history_capture(&s->events.data, s->control[7], *iref(0), c[0], c[6], c[1],
                                             *fref(0x23), s->results[7], s->results[2], s->upper);
    }
    pressure_target(&s->pressure.data, s->results + 7, s->results + 8, 1,
                    s->slow_events & (1u << 13), *iref(0), s->lower,
                    s->results[2], s->results[6], s->control[8], s->control[9]);
}

void autoepap_waveform_hook(void *ctx) {
    Autoepap *s = autoepap_find();
    int active = autoepap_active(s);
    if (s && *iref(0x12) == 6)
        pressure_slew(&s->pressure.data, s->results + 7, *fref(0x20),
                      s->lower, s->upper, active, *iref(0x76));
    therapy_mode67_pressure_waveform_worker_update(ctx);
    if (active) *fref(0x28) = s->results[7];
}

static const Method fast_methods[7] = {
    lifecycle_noop, lifecycle_noop, autoepap_stop, autoepap_mode,
    autoepap_mode, autoepap_stop, autoepap_fast
};
static const Method slow_methods[7] = {
    lifecycle_noop, lifecycle_noop, lifecycle_noop, lifecycle_noop,
    lifecycle_noop, lifecycle_noop, autoepap_slow
};

void *start(void) {
    void *original = ivaps_ventilation_estimator_register();
    if (autoepap_find()) return original;
    Autoepap *s = malloc(sizeof(*s));
    if (!s) return original;
    clear_bytes(s, sizeof(*s));
    s->timing.first_measured = 1;
    therapy_worker_append(&s->fast, 2);
    therapy_worker_append(&s->slow, 0);
    s->fast.methods = fast_methods;
    s->slow.methods = slow_methods;
    s->fast.enabled = s->slow.enabled = 0;
    autoepap_load_settings(s);
    return original;
}

extern void breath_phase_adaptation_mode_update(void *), breath_phase_adaptation_update(void *);
extern void breath_transition_detector_update(void *), ivaps_breath_timing_worker_mode_update(void *), ivaps_breath_timing_worker_update(void *);
extern void ivaps_breath_timing_update_targets(void *, int, int), ring_buffer3_push(void *, int);
extern void ivaps_ventilation_estimator_mode_update(void *), ivaps_ventilation_estimator_update(void *);
extern float iir_filter_order4_update(float, void *), tau_filter_update_weighted(float, float *, int);
extern float ivaps_breath_timing_stability_factor(float, float, float);
extern void therapy_feedback_item_phase1_init(u32 *, unsigned), therapy_manager_set_feedback_item(u32 *);
extern void iir_filter_order4_reset(float, void *), tau_filter_init_int(float, void *, int);

/* The stock allocation stays at 404 bytes. The Lumis extra byte lives in Autoepap. */
typedef struct {
    unsigned char header[16], short_filter[176], long_filter[176];
    float average[4], threshold;
    unsigned char positive, padding[3];
    float integral;
    int count;
    float sum;
} Ventilation;
_Static_assert(sizeof(Ventilation) == 404, "SX567 estimator allocation");

/* The SX567 stop slot is a no-op; Lumis disables the estimator so its next
 * start performs the fresh-state reset rather than an enabled-worker refresh. */
void autoepap_ventilation_stop(Ventilation *worker) {
    worker->header[8] = 0;
}

void autoepap_ventilation_mode(Ventilation *worker) {
    Autoepap *s = autoepap_find();
    int previous = worker->header[8];
    if (!previous) {
        iir_filter_order4_reset(0.0f, worker->short_filter);
        iir_filter_order4_reset(0.0f, worker->long_filter);
        tau_filter_init_int(0.0f, worker->average, 0x4000);
        worker->threshold = worker->integral = worker->sum = 0;
        worker->positive = worker->count = 0;
        if (s) s->ventilation_seen_negative = 0;
    }
    int count = worker->count;
    float sum = worker->sum;
    ivaps_ventilation_estimator_mode_update(worker);
    /* SX567 clears these on every mode callback; Lumis only on disabled entry. */
    worker->count = count;
    worker->sum = sum;
}

void autoepap_ventilation_update(Ventilation *worker) {
    Autoepap *s = autoepap_find();
    if (!autoepap_active(s)) {
        ivaps_ventilation_estimator_update(worker);
        if (s) s->ventilation_seen_negative |= *fref(0x26) < 0.0f;
        return;
    }
    float flow = *fref(0x25), target = *fref(0x18), magnitude = absolute(flow);
    *fref(0xaf) = tau_filter_update_weighted(magnitude * 0.5f, worker->average, 1);
    *fref(0xb3) = target;
    ++worker->count;
    if (!s->ventilation_seen_negative) {
        s->ventilation_seen_negative = flow < 0.0f;
        return;
    }
    int positive = flow >= 0.0f;
    if (positive != worker->positive) { worker->positive = positive; worker->integral = 0.0f; }
    float volume_flow = magnitude * 0.5f;
    if (worker->integral < worker->threshold) { worker->integral += magnitude; volume_flow = 0.0f; }
    *fref(0xb0) = volume_flow;
    float fast = iir_filter_order4_update(volume_flow, worker->short_filter);
    float slow = iir_filter_order4_update(volume_flow, worker->long_filter);
    *fref(0xb2) = fast; *fref(0xb1) = slow;
    *fref(0xb4) = (fast - target) / target;
    float deviation = (slow - target) / target;
    *fref(0xb5) = deviation;
    worker->sum += deviation;
    if (worker->count > 0) *fref(0xb6) = worker->sum / (float)worker->count;
    if (*iref(0x63)) { worker->count = 0; worker->sum = 0.0f; }
}

void *autoepap_flow_ref_impl(float **output, int index, int replacement) {
    therapy_variable_get_float(output, autoepap_on() ? replacement : index);
    return output;
}

typedef struct {
    Node node;
    float adaptation[4], activity[4];
    int interval;
    unsigned char negative, padding[3];
} PhaseAdaptation;

static void publish_leak_tau(float weight) {
    *iref(0x1a) = round_positive(((1.0f - weight) + weight * 0.1f) *
                               minimum(2.5f * (float)*iref(0x2a), 2000.0f));
}

void autoepap_phase_mode(PhaseAdaptation *worker) {
    int previous = worker->node.enabled;
    breath_phase_adaptation_mode_update(worker);
    if (!previous && autoepap_on())
        *iref(0x1a) = (int)minimum(2.5f * (float)*iref(0x2a), 2000.0f);
}

void autoepap_phase_update(PhaseAdaptation *worker) {
    /* Retain the stock phase membership; only its leak-filter time changes. */
    breath_phase_adaptation_update(worker);
    if (autoepap_on()) publish_leak_tau(worker->adaptation[0]);
}

/* Keep the small adapter: the detector is also needed for private group-2 events. */
static void transition_positive(void *ctx, int time) { (void)ctx; *iref(0x1f) = time; }
static void transition_negative(void *ctx, int time) { (void)ctx; *iref(0x1e) = time; }
static void transition_event(void *ctx, unsigned event) {
    (void)ctx;
    u32 item[3];
    therapy_feedback_item_phase1_init(item, event - 10);
    therapy_manager_set_feedback_item(item);
}
typedef struct { Node node; int pending; float positive, negative; } Transition;

void autoepap_transition(Transition *worker) {
    if (!autoepap_on()) { breath_transition_detector_update(worker); return; }
    Detector detector = {*iref(0x20), worker->pending, 0, 0,
                         worker->positive, worker->negative, 0};
    DetectorOutput callbacks = {0, transition_positive, transition_negative, detector_noop, transition_event};
    detect_phase(&detector, &callbacks, *fref(0x46), 3.0f,
                 phase_volume_threshold(*fref(0x1d), *fref(0x18)) * 6.0f, *iref(0));
    *iref(0x20) = detector.phase;
    worker->pending = detector.pending_time;
    worker->positive = detector.positive_sum;
    worker->negative = detector.negative_sum;
}

typedef struct {
    Node node;
    int inhale_ring[5], exhale_ring[5], inhale_start, exhale_start, last_inhale;
} Timing;

static void timing_seed(Autoepap *s, Timing *worker) {
    for (int i = 0; i < 3; ++i) {
        ring_buffer3_push(worker->inhale_ring, 160);
        ring_buffer3_push(worker->exhale_ring, 240);
    }
    s->timing.inhale = 160.0f; s->timing.exhale = 240.0f;
    worker->last_inhale = 160;
    *iref(0x2d) = 160; *iref(0x2c) = 240;
}

void autoepap_timing_mode(Timing *worker) {
    Autoepap *s = autoepap_find();
    if (!autoepap_active(s)) {
        int previous = worker->node.enabled;
        ivaps_breath_timing_worker_mode_update(worker);
        int profile = *iref(0x6f), subtype = *iref(0x13);
        if (s && (!previous || profile == 6 || (profile == 4 && (subtype == 1 || subtype == 2)))) {
            s->timing.inhale = (float)*iref(0x2d);
            s->timing.exhale = (float)*iref(0x2c);
        }
        return;
    }
    ivaps_breath_timing_update_targets(worker, *iref(0x6f), *iref(0x13));
    if (!worker->node.enabled) {
        worker->inhale_start = worker->exhale_start = *iref(0);
        timing_seed(s, worker);
    }
    worker->node.enabled = 1;
}

void autoepap_timing_update(Timing *worker) {
    Autoepap *s = autoepap_find();
    int active = autoepap_active(s);
    int profile = *iref(0x6f), subtype = *iref(0x13);
    int configured = (profile == 6 && !active) || (profile == 4 && (subtype == 1 || subtype == 2));
    /* This flag belongs to registration, not to each profile reset. A configured
     * timing return leaves it pending until the first measured update. */
    if (s && !configured && s->timing.first_measured) {
        s->timing.first_measured = 0;
        if (active) timing_seed(s, worker);
    }
    ivaps_breath_timing_worker_update(worker);
}

/* Original worker frame at 0x080AABB4: min/median/max at 3/1/5 and 4/2/9. */
int autoepap_timing_tail(const float *frame) {
    Autoepap *s = autoepap_find();
    if (!s) return 0;
    int active = autoepap_active(s);
    float ti = frame[1], te = frame[2], total = ti + te;
    if (ti < 40.0f || te < 60.0f) return 1;
    float inhale = ti, exhale = te;
    if (total >= 500.00003f) {
        if (ti >= 200.00002f) ti = 58.58f + sqrtf(ti) * 10.0f;
        if (te >= 300.00003f) te = 126.79f + sqrtf(te) * 10.0f;
    }
    if (inhale < 400.00003f || (inhale < 600.00006f && total < 1300.0001f)) {
        if (inhale >= 400.00003f) ti *= ivaps_breath_timing_stability_factor(frame[3], inhale, frame[5]);
        s->timing.inhale = inhale + (s->timing.inhale - inhale) * expf(ti / -800.0f);
        if (!active) s->timing.inhale = (float)(int)s->timing.inhale;
        *iref(0x2d) = round_positive(s->timing.inhale);
    }
    if (exhale < 750.00006f || (exhale < 1100.0001f && total < 1300.0001f)) {
        if (exhale >= 750.00006f) te *= ivaps_breath_timing_stability_factor(frame[4], exhale, frame[9]);
        s->timing.exhale = exhale + (s->timing.exhale - exhale) * expf(te / -1200.0f);
        if (!active) s->timing.exhale = (float)(int)s->timing.exhale;
        *iref(0x2c) = round_positive(s->timing.exhale);
    }
    return 1;
}

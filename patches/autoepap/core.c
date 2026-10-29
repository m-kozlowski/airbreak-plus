/* Symmetric ten-tap flow filter; the second half mirrors these coefficients. */
static const float fir_coefficients[5] = {
    0x1.1ffc14p-3f, 0x1.6cd530p-3f, 0x1.ae606ep-3f, 0x1.da9770p-3f, 0x1.ea36dcp-3f
};
static const float shape_weights[8] = {1.0f, 0.95f, 0.9f, 0.8f, 0.7f, 0.55f, 0.4f, 0.25f};

typedef unsigned int u32;
extern float sqrtf(float);
extern float expf(float);

static inline float minimum(float a, float b) { return a < b ? a : b; }
static inline float maximum(float a, float b) { return a > b ? a : b; }
static inline float absolute(float a) { return a < 0.0f ? -a : a; }
static inline float clamp(float v, float a, float b) {
    float lo = minimum(a, b), hi = maximum(a, b);
    return v < lo ? lo : v > hi ? hi : v;
}
static inline int round_positive(float a) { return (int)(a + 0.5f); }

typedef struct {
    const float *samples;
    int start, count;
} Span;

static inline float sample(const Span *span, int index) {
    int pos = span->start + index;
    pos %= 1000;
    if (pos < 0) pos += 1000;
    return span->samples[pos];
}

extern float linear_map_clamped_2point(float, float, float, float, float);
extern float linear_map_clamped_3point(float, float, float, float, float, float, float);
extern float linear_map_clamped_4point(float, float, float, float, float, float, float, float, float);

typedef struct {
    float target, lower, upper;
    unsigned char phase_latch;
    int previous_time;
    unsigned char previous_valid;
} Pressure;

/* limit changes latch at the rising half-phase boundary. */
void pressure_refresh(Pressure *p, float *current, float phase,
                      float lower, float upper) {
    if (phase >= 0.50000006f && !p->phase_latch &&
            (lower != p->lower || upper != p->upper)) {
        p->lower = lower;
        p->upper = upper;
        p->target = clamp(p->target, lower, upper);
        *current = clamp(*current, lower, upper);
    }
    p->phase_latch = phase >= 0.50000006f;
}

void pressure_slew(Pressure *p, float *current, float phase,
                   float lower, float upper, int enabled, int inhibited) {
    if (lower == upper) pressure_refresh(p, current, phase, lower, upper);
    if (enabled && !inhibited) {
        pressure_refresh(p, current, phase, lower, upper);
        float delta = p->target - *current;
        if (phase < 0.50000006f || delta < 0.0f)
            *current += clamp(delta, -0.01f, 0.01f);
    }
}

/* the event dispatch gate is outside this numeric kernel. */
void pressure_target(Pressure *p, float *current, float *published,
                     int enabled, int ready, int now, float lower,
                     float shape_correction, float event_correction,
                     int reduced_flow, int reduced_ticks) {
    if (!enabled) {
        *current = lower;
    } else if (ready) {
        float next = p->target;
        if (shape_correction > 0.0f || event_correction > 0.0f) {
            next += shape_correction + event_correction;
        } else if (p->previous_valid &&
                   (!reduced_flow || (float)reduced_ticks / 100.0f < 10.0f)) {
            int dt = now - p->previous_time;
            if (dt < 0) dt = 0;
            if (dt > 999) dt = 1000;
            float distance = *current - lower;
            if (distance >= 4.0000005f)
                distance = (distance - 4.0f) * 0.5f + 4.0f;
            next += (expf(((float)dt / -100.0f) / 1200.0f) - 1.0f)
                    * distance;
        }
        p->previous_valid = 1;
        p->previous_time = now;
        p->target = clamp(next, p->lower, p->upper);
    }
    *published = p->target;
}

/* mirrored ten-tap FIR, full-span SD and prefix RMS. */
int shape_variability(const Span *span, float duration, float front,
                      float back, float *scratch, float *sd, float *prefix,
                      int with_prefix) {
    int begin = (int)(front * 100.0f);
    int n = (int)(duration * 100.0f) - (int)(back * 100.0f) - begin - 10;
    int k = with_prefix ? n / 4 : 0;
    if (k > 200) k = 200;
    if (n <= 0 || (with_prefix && k < 2)) return 0;
    float sum = 0.0f, squares = 0.0f;
    for (int i = 0; i < n; ++i) {
        float y = 0.0f;
        for (int j = 0; j < 5; ++j) {
            float c = fir_coefficients[j];
            y = y + c * sample(span, begin + i + j)
                  + c * sample(span, begin + i + 9 - j);
        }
        sum += y;
        squares += y * y;
        if (i < k) scratch[i] = y;
    }
    float mean = sum / (float)n;
    *sd = sqrtf(maximum(squares - sum * mean, 0.0f) / (float)(n - 1));
    if (k) {
        squares = 0.0f;
        for (int i = 0; i < k; ++i) {
            float d = scratch[i] - mean;
            squares += d * d;
        }
        *prefix = sqrtf(squares / (float)k);
    }
    return 1;
}

/* retain the raw-index ratio, not a wrapped ring distance. */
int shape_event(const Span *a, const Span *b, int i26, int i2a, int i25,
                float cached_deviation, float *scratch) {
    float da = (float)a->count / 100.0f;
    float db = (float)b->count / 100.0f;
    float sda, sdb, prefix;
    if (da < 0.8f || db < 1.0f) return 0;
    if (!shape_variability(a, da, 0.1f, 0.1f, scratch, &sda, &prefix, 0)) return 0;
    if (!shape_variability(b, db, 0.15f, 0.1f, scratch, &sdb, &prefix, 1)) return 0;
    if (!(sda < 2.4f && sdb < 1.8000001f &&
          prefix < 2.4f && cached_deviation < 0.0f)) return 0;
    float ratio = (float)(i26 - i2a) / (float)(i25 - i2a);
    return ratio >= 0.25f && ratio < 0.50000006f;
}

/* Least-squares fit; preserve the accumulation order for float precision. */
int linear_fit(const Span *span, float origin, float step,
               float *mean_x, float *mean_y, float *slope, float *variance) {
    if (!span->count) return 0;
    float sx = 0.0f, sy = 0.0f, sxx = 0.0f, sxy = 0.0f, syy = 0.0f;
    for (int i = 0; i < span->count; ++i) {
        float x = origin + (float)i * step, y = sample(span, i);
        sx += x;
        sy += y;
        sxx += x * x;
        sxy += x * y;
        syy += y * y;
    }
    float n = (float)span->count;
    *mean_x = sx / n;
    *mean_y = sy / n;
    float denominator = sxx - sx * *mean_x;
    if (absolute(denominator) < 0.0000010000001f) return 0;
    float m = (sxy - sx * (sy / n)) / denominator;
    *slope = m;
    *variance = ((syy - sy * *mean_y) +
                 (m * denominator + (sx * *mean_y - sxy) * 2.0f) * m) / n;
    return 1;
}

/* Trim the pressure transitions before fitting the inspiratory flow. */
int cropped_flow_fit(const Span *span, int rise_ticks, int fall_ticks,
                     float target_va, float *outputs) {
    if (span->count < 50 || target_va <= 0.0f) return 0;
    if (rise_ticks < 10) rise_ticks = 10;
    int begin = round_positive((float)rise_ticks * 1.25f);
    int end = round_positive((float)fall_ticks * 0.25f);
    int n = span->count - begin - end;
    if (begin >= span->count || n < round_positive((float)span->count * 0.25f)) return 0;
    Span cropped = {span->samples, span->start + begin, n};
    float mx, my, m, v;
    if (!linear_fit(&cropped, 0.0f, 0.01f, &mx, &my, &m, &v)) return 0;
    float scale = 4.5f / target_va;
    outputs[0] = sqrtf(v) * scale;
    outputs[1] = m * scale;
    outputs[2] = my * scale;
    outputs[3] = mx;
    return 1;
}

/* only the validity test, not subsequent boundary processing. */
int qualify_breath(const Span *span, float target_va) {
    float duration = (float)span->count / 100.0f;
    if (duration < 0.45f || duration >= 5.0000005f) return 0;
    float sum = 0.0f, negative = 0.0f;
    for (int i = 0; i < span->count; ++i) {
        float value = sample(span, i);
        sum += value;
        if (value < 0.0f) negative -= value;
    }
    return sum * 1000.0f / 6000.0f >= 50.0f &&
           ((negative * 1000.0f) / 6000.0f) / 1000.0f < target_va / 100.0f;
}

typedef struct {
    int phase, pending_time, negative_time, positive_time;
    float positive_sum, negative_sum;
    int accumulate_after_test;
} Detector;

typedef struct {
    void *context;
    void (*positive_begin)(void *, int);
    void (*negative_begin)(void *, int);
    void (*duration)(void *, int);
    void (*event)(void *, unsigned);
} DetectorOutput;

/* Phase setters and callbacks become explicit private state. */
void detect_phase(Detector *d, const DetectorOutput *out, float flow,
                  float threshold, float volume_threshold, int now) {
    switch (d->phase) {
    case 0:
        if (!(flow > threshold)) return;
        d->phase = 1;
        d->positive_sum = flow;
        break;
    case 1:
        if (flow <= 0.0f) { d->phase = 0; return; }
        d->positive_sum += flow;
        if (d->positive_sum > volume_threshold) { d->phase = 3; out->event(out->context, 13); }
        return;
    case 2:
        if (flow <= 0.0f) { d->phase = 5; d->positive_sum = 0.0f; return; }
        if (!d->accumulate_after_test) d->positive_sum += flow;
        if (d->positive_sum > volume_threshold) {
            d->phase = 3;
            out->positive_begin(out->context, d->pending_time);
            out->event(out->context, 13);
            d->negative_sum = 0.0f;
            return;
        }
        if (d->accumulate_after_test) d->positive_sum += flow;
        return;
    case 3:
        if (flow <= 0.0f) {
            d->phase = 4;
            d->negative_sum += flow;
            d->pending_time = now;
            d->negative_time = now;
            out->event(out->context, 11);
        }
        return;
    case 4:
        if (flow > 0.0f) { d->phase = 3; d->negative_sum = 0.0f; return; }
        if (!d->accumulate_after_test) d->negative_sum += flow;
        if (d->negative_sum < -volume_threshold) {
            d->phase = 5;
            out->negative_begin(out->context, d->pending_time);
            out->event(out->context, 12);
            d->positive_sum = 0.0f;
            return;
        }
        if (d->accumulate_after_test) d->negative_sum += flow;
        return;
    default:
        if (!(flow > threshold)) return;
        d->phase = 2;
        d->positive_sum += flow;
        out->duration(out->context, d->negative_time - d->positive_time);
    }
    d->pending_time = now;
    d->positive_time = now;
    out->event(out->context, 10);
}

float phase_volume_threshold(float dead_space, float target_va) {
    return maximum(0.42f * dead_space,
                   0.007f * minimum(target_va, 6.0f));
}

typedef struct {
    int warmup, sum, elapsed;
    float weight, recovery;
    int active;
} Reduced;

float rolling_flow(Reduced *r, const float *samples, int head) {
    int previous = head - 200;
    if (previous < 0) previous += 1000;
    r->sum += round_positive(minimum(absolute(samples[head]), 300.0f) * 1024.0f);
    if (r->warmup >= 200)
        r->sum -= round_positive(minimum(absolute(samples[previous]), 300.0f) * 1024.0f);
    return ((float)r->sum / 2048.0f) / 200.0f;
}

/* Return bits describe the two private group-2 events. */
unsigned reduced_flow_update(Reduced *r, const float *samples, int head,
                             float target_va, float deviation, float leak,
                             float *flow, int *elapsed, float *weight) {
    if (++r->warmup > 200) r->warmup = 200;
    *flow = rolling_flow(r, samples, head);
    if (r->warmup < 200) *flow = target_va;
    int low = *flow <= target_va * 0.2f;
    int active = low || deviation < -0.9499999f;
    unsigned events = 0;
    *elapsed = 0;
    *weight = 0.0f;
    if (!r->active) {
        if (active) {
            r->active = 1;
            events |= 1u << 14;
            r->elapsed = 0;
            r->weight = r->recovery = 0.0f;
        }
        return events;
    }
    float factor = 1.0f;
    if (!active) {
        if (!low) r->recovery += (deviation + 0.95f) * 0.01f;
        if (r->recovery < 0.15f)
            factor = linear_map_clamped_2point(deviation, -0.95f, 1.0f, -0.9f, 0.0f);
        else {
            r->active = 0;
            events |= 1u << 15;
        }
    } else r->recovery = 0.0f;
    if (r->active) {
        ++r->elapsed;
        if (leak < 60.0f)
            r->weight += factor * linear_map_clamped_2point(leak, 48.0f, 1.0f, 60.0f, 0.0f);
        else r->weight = 0.0f;
    }
    *elapsed = r->elapsed;
    *weight = r->weight;
    return events;
}

/* Trapezoidal membership: zero outside, one across the central plateau. */
static float trapezoid(float x, float a, float b, float c, float d) {
    return linear_map_clamped_4point(x, a, 0.0f, b, 1.0f, c, 1.0f, d, 0.0f);
}

/* Classify eight segment features into six flow-shape memberships. */
float shape_memberships(const float *f, int validity, float fit_membership,
                        float *out) {
    float combined = 0.0f;
    if (validity == 1 || validity == 3) {
        float a = trapezoid(f[0], -0.2f, -0.1f, 0.1f, 0.2f);
        float b = linear_map_clamped_2point(f[1], 0.05f, 1.0f, 0.1f, 0.0f);
        float c = linear_map_clamped_2point(f[2], -0.2f, 0.0f, 0.0f, 1.0f);
        out[0] = minimum(minimum(a, b), c);
        out[1] = 0.0f;
        if (f[5] > 0.0f && f[0] >= -0.6f && f[0] < -0.099999994f) {
            float blend = linear_map_clamped_2point(f[3], 0.08f, 0.0f, 0.12f, 1.0f);
            float reference = blend * 0.08f +
                (1.0f - blend) * (0.04f + (f[0] + 0.5f) * 0.1f);
            a = linear_map_clamped_2point(f[1] - reference, 0.0f, 1.0f, 0.01f, 0.0f);
            b = trapezoid(f[2], -0.05f, 0.0f, 0.3f, 0.5f);
            c = trapezoid(-f[0] / f[5], -0.4f, -0.2f, 0.2f, 0.4f);
            float d = linear_map_clamped_2point(f[4], -0.4f, 0.0f, -0.3f, 1.0f);
            out[1] = minimum(minimum(minimum(a, b), c), d);
        }
        a = trapezoid(f[0], -0.1f, -0.05f, 0.05f, 0.1f);
        b = linear_map_clamped_2point(f[2], -0.1f, 0.0f, 0.0f, 1.0f);
        c = linear_map_clamped_2point(f[3], -0.05f, 0.0f, 0.0f, 1.0f);
        out[2] = minimum(minimum(a, b), c);
        a = trapezoid(f[0], -0.3f, -0.2f, 0.2f, 0.3f);
        b = linear_map_clamped_2point(f[2], 0.1f, 0.0f, 0.3f, 1.0f);
        c = linear_map_clamped_2point(f[3], 0.15f, 0.0f, 0.3f, 1.0f);
        out[3] = minimum(minimum(a, b), c);
        float cap = linear_map_clamped_2point(f[1], 0.1f, 1.0f, 0.2f, 0.0f);
        a = trapezoid(f[0], -0.45f, -0.3f, 0.1f, 0.2f);
        b = linear_map_clamped_2point(f[4], 0.0f, 0.0f, 0.2f, 1.0f);
        c = trapezoid(f[0], -0.55f, -0.45f, 0.1f, 0.2f);
        float d = linear_map_clamped_2point(f[4], 0.2f, 0.0f, 0.3f, 1.0f);
        out[4] = minimum(minimum(minimum(a, b), minimum(c, d)), cap);
        for (int i = 0; i < 5; ++i) combined = maximum(combined, out[i]);
    }
    if (validity == 2 || validity == 3) {
        float a = trapezoid(f[6], -0.4f, -0.2f, 0.2f, 0.4f);
        float b = linear_map_clamped_2point(f[7], 0.3f, 0.0f, 0.4f, 1.0f);
        out[5] = minimum(a, b);
        combined = maximum(combined, out[5]);
    }
    return maximum(combined, fit_membership);
}

/* The reference is held at its value at first crossing. */
float fit_prefix_excess(const Span *span, int begin, float mean_x,
                        float mean_y, float slope, float scale) {
    float result = 0.0f;
    slope /= 100.0f;
    mean_x *= 100.0f;
    for (int i = 0; i < begin; ++i) {
        float reference = mean_y + ((float)i - ((float)begin + mean_x)) * slope;
        if (sample(span, i) > reference) {
            for (int j = i; j < begin; ++j) result = sample(span, j) - reference + result;
            return (result / (float)(begin - i)) * scale;
        }
    }
    return result;
}

float fit_membership(float deviation, float slope, float mean, float excess) {
    float prefix;
    if (mean < 4.5000005f) prefix = linear_map_clamped_2point(excess, 2.25f, 0.0f, 4.5f, 1.0f);
    else prefix = linear_map_clamped_2point(excess / mean, 0.5f, 0.0f, 1.0f, 1.0f);
    float factor = linear_map_clamped_2point(mean, 3.0f, 1.0f, 4.2f, 0.0f);
    float deviation_m = linear_map_clamped_2point(deviation, 0.6f, 1.0f, 0.9f, 0.0f);
    float slope_m = trapezoid(slope, -9.0f - 3.0f * factor,
                              -6.0f - 3.0f * factor,
                              6.0f, 9.0f);
    return minimum(prefix, minimum(deviation_m, slope_m));
}

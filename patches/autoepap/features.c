
/* Ring spans exclude their end position. */
int segment_features(const Span *span, float first, float last, float out[7]) {
    int begin = round_positive((float)span->count * first);
    int end = round_positive((float)span->count * last);
    int n = end - begin;
    if (begin < 0 || end >= span->count || n <= 1) return 0;
    float total = 0.0f;
    for (int i = 0; i < span->count; ++i) total += sample(span, i);
    float mean = total / (float)span->count;
    if (!(mean > 0.0f)) return 0;
    float prefix = 0.0f;
    for (int i = 0; i < begin; ++i)
        prefix += sample(span, i) - (float)i * (sample(span, begin) / (float)begin);
    out[4] = prefix / total;
    out[5] = (float)n / 100.0f;
    mean = maximum(mean, 24.0f);
    float sx = 0.0f, sy = 0.0f, sxx = 0.0f, sxy = 0.0f;
    for (int i = 0; i < n; ++i) {
        float x = (float)i / (float)n, y = sample(span, begin + i);
        sx += x;
        sy += y;
        sxx += x * x;
        sxy += x * y;
    }
    float mx = sx / (float)n;
    float denominator = sxx - sx * mx;
    out[6] = (sy / mean) / (float)n;
    if (denominator == 0.0f) return 0;
    out[0] = (sxy / mean - sx * out[6]) / denominator;
    float suffix = 0.0f, residual = 0.0f;
    for (int i = n; i < span->count - begin; ++i) {
        float line = out[6] + ((float)i / (float)n - mx) * out[0];
        suffix += sample(span, begin + i) / mean - line;
    }
    out[3] = out[6] > 0.0f ? suffix / ((float)(span->count - end) * out[6]) : 0.0f;
    float projection = 0.0f, energy = 0.0f;
    for (int i = 0; i < n; ++i) {
        float y = sample(span, begin + i) / mean;
        float error = out[6] + ((float)i / (float)n - mx) * out[0] - y;
        residual += error * error;
        float x = (float)i / (float)(n - 1);
        float basis = x < 0.5f ? 0.25f - x : x - 0.75f;
        projection += (y - out[6]) * basis;
        energy += basis * basis;
    }
    out[1] = sqrtf(residual / (float)n);
    out[2] = projection / sqrtf(energy);
    return 1;
}

/* Two windows supply eight persistent feature outputs. */
int produce_segments(const Span *span, float out[8]) {
    float result[7];
    int valid = 0;
    if (segment_features(span, 0.3f, 0.85f, result)) {
        for (int i = 0; i < 5; ++i) out[i] = result[i];
        out[5] = result[5] * result[6];
        valid |= 1;
    }
    if (segment_features(span, 0.2f, 0.8f, result)) {
        out[6] = result[0];
        out[7] = result[2];
        valid |= 2;
    }
    return valid;
}

/* Combine the cropped regression and excess flow before the fitted segment. */
float produce_fit(const Span *span, int rise, int fall, float target, float out[5]) {
    float fit[4];
    if (!cropped_flow_fit(span, rise, fall, target, fit)) return 0.0f;
    if (rise < 10) rise = 10;
    int begin = round_positive((float)rise * 1.25f);
    float scale = 4.5f / target;
    float excess = fit_prefix_excess(span, begin, fit[3], fit[2] / scale,
                                    fit[1] / scale, scale);
    out[0] = fit[0];
    out[1] = fit[1];
    out[2] = fit[2];
    out[3] = excess;
    out[4] = fit_membership(fit[0], fit[1], fit[2], excess);
    return out[4];
}

typedef struct {
    int pending;
    float values[8];
    int cursor, low, high, count;
    unsigned char valid;
    unsigned char padding[3];
    float normalization;
} ShapeHistory;

/* Source span, including the cyclic-counter fields. */
void shape_history_reset(ShapeHistory *h) {
    h->pending = 0;
    h->cursor = h->high = 7;
    h->low = 0;
    h->count = 0;
    h->valid = 0;
    h->normalization = 5.55f;
    for (int i = 0; i < 8; ++i) {
        h->values[i] = 0.0f;
    }
}

static void shape_history_push(ShapeHistory *h, float value) {
    h->values[h->cursor] = value;
    h->cursor = (h->cursor + 1) & 7;
    if (h->cursor == 7) h->valid = 1;
}

/* Missing eligible breaths are zero entries, not held values. */
void shape_history_insert(ShapeHistory *h, float value) {
    if (h->pending > 0) --h->pending;
    while (h->pending > 0) {
        shape_history_push(h, 0.0f);
        --h->pending;
    }
    shape_history_push(h, value);
}

/* Blend successive breaths through their smaller membership. */
float shape_history_evaluate(ShapeHistory *h) {
    while (h->pending > 0) {
        shape_history_push(h, 0.0f);
        --h->pending;
    }
    float sum = 0.0f, previous = 0.0f;
    if (!h->valid) return sum;
    for (int i = 0; i < 8; ++i) {
        float value = h->values[(h->cursor - 1 - i) & 7];
        float mixed = value + (1.0f - value) * minimum(previous, value);
        sum += mixed * mixed * shape_weights[i];
        previous = value;
    }
    return sqrtf(sum / h->normalization);
}

/* Convert qualified flow shape and ventilation deficit into an EPAP increment. */
float shape_pressure(ShapeHistory *h, const Span *span, int qualified,
                     float target_va, float dead_space, float index,
                     float membership, float current_epap, float reference_flow,
                     float *ventilation_factor) {
    *ventilation_factor = 0.0f;
    ++h->pending;
    if (!qualified || target_va < 1.0f || !span->count) return 0.0f;
    float positive = 0.0f, negative = 0.0f;
    for (int i = 0; i < span->count; ++i) {
        float v = sample(span, i);
        if (v >= 0.0f) positive += v;
        else negative -= v;
    }
    positive = maximum(positive * 1000.0f / 6000.0f - dead_space, 0.0f);
    negative = maximum(negative * 1000.0f / 6000.0f - dead_space, 0.0f);
    float ratio = (((positive / 1000.0f + negative / 1000.0f) * 0.5f *
                    6000.0f) / (float)span->count) / target_va;
    float factor = linear_map_clamped_2point(ratio, 0.2f, 1.0f, 0.8f, 0.0f);
    *ventilation_factor = factor;
    shape_history_insert(h, factor * maximum(index, membership));
    membership = maximum(clamp(index, 0.0f, 1.0f), membership);
    float threshold = linear_map_clamped_3point(current_epap, 14.0f, 0.0f, 18.0f, 0.3f,
                                20.0f, 0.8f);
    if (!(membership > threshold)) return 0.0f;
    float pressure_scale = current_epap < 15.0f ?
        linear_map_clamped_2point(current_epap, 10.0f, 1.0f, 15.0f, 0.7f) :
        linear_map_clamped_3point(current_epap, 15.0f, 0.7f, 19.0f, 0.4f, 20.0f, 0.0f);
    float flow_scale = linear_map_clamped_2point(reference_flow, 30.0f, 1.0f, 60.0f, 0.0f);
    if (ratio < 1.0f) factor = factor <= 0.0f ? 1.0f : 2.0f * shape_history_evaluate(h) + 0.5f;
    else {
        float blend = linear_map_clamped_2point(membership, 0.7f, 0.0f, 0.9f, 1.0f);
        factor = linear_map_clamped_2point(ratio, (1.0f - blend) + blend * 1.7f, 1.0f,
                            (1.0f - blend) * 1.5f + blend * 2.2f, 0.0f);
    }
    return (membership - threshold) * pressure_scale * flow_scale * factor * 0.2f;
}

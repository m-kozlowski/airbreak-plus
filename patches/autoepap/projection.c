/* Stock numerical objects, with private window bindings at the two scorer calls. */
extern void *therapy_fixed_vector_group1_ref_init(u32 *, int);
extern void *cyclic_counter_init(int *, const int *, const int *);
extern void *clamp_int_to_bounds(int *, const int *);
extern void *ring_span_fixed_vector_init(u32 *, u32 *);
extern void asv_breath_shape_harmonic_projector_init(u32 *, u32 *);
extern void asv_breath_shape_project_first_segment(u32 *, float *, float *);
extern void asv_breath_shape_project_second_segment(u32 *, float *, float *);
extern int asv_breath_landmark_score_next(void *, float *);
extern void *therapy_variable_get(int **, int);

typedef struct {
    u32 owner;
    int start, end;
    float mean;
    int scale;
    float normalization;
    int sums[2];
    float moments[2];
    int length, quarter, half, cursor[4];
    unsigned char initial, padding[3];
} Scorer;
_Static_assert(sizeof(Scorer) == 72, "stock scorer layout");
int breath_landmark(const Span *);

void *autoepap_landmark_ref(int **out, int index, Scorer *scorer) {
    if (scorer->owner != (u32)breath_landmark) return therapy_variable_get(out, index);
    *out = index == 0x38 ? &scorer->start : &scorer->end;
    return out;
}

int breath_landmark(const Span *span) {
    int n = span->count;
    if (n < 2 || n > 500) return -1;
    Scorer scorer;
    scorer.owner = (u32)breath_landmark;
    scorer.start = span->start;
    scorer.end = (span->start + n) % 1000;
    scorer.mean = 0.0f;
    int positives = 0;
    for (int i = 0; i < n; ++i) {
        float value = sample(span, i);
        if (value >= 0.0f) { scorer.mean += value; ++positives; }
    }
    if (!positives) return -1;
    scorer.mean /= (float)positives;
    if (!(scorer.mean > 0.0f)) return -1;
    scorer.length = n;
    scorer.half = (n / 2 + 1) & ~1;
    scorer.quarter = scorer.half / 2;
    scorer.scale = 0x7fffffff / (n * (n + 2) * 6);
    float q = (float)scorer.quarter;
    float norm = ((float)scorer.scale * (q + 1.0f) * q * (q - 1.0f)) /
                 ((float)(n / 2 - 1) * 6.0f);
    scorer.normalization = norm != 0.0f ? 1.0f / norm : 0.0f;
    scorer.initial = 1;
    int zero = 0, last = 999;
    cyclic_counter_init(scorer.cursor, &zero, &last);
    clamp_int_to_bounds(scorer.cursor, &scorer.start);
    float value = 0.0f, best_score = -1.0f;
    int best = -1;
    while (!asv_breath_landmark_score_next(&scorer, &value)) {
        if (value > best_score) { best_score = value; best = scorer.cursor[0]; }
    }
    if (best_score < 0.15f) return -1;
    return (best + scorer.quarter - 1 - span->start + 1000) % 1000;
}

static void projection_bounds(u32 *window, int begin, int end) {
    /* Lumis uses an exclusive end here. SX567's public setter rejects a
     * one-sample span, though its projector supports it; fill the same fields. */
    window[1] = begin;
    window[2] = (end + 999) % 1000;
    window[7] = (end - begin + 999) % 1000;
    clamp_int_to_bounds((int *)(window + 3), (const int *)(window + 1));
}

float harmonic_ratio(const Span *span, int landmark) {
    if (landmark <= 0 || landmark >= span->count) return 0.0f;
    u32 vector[2], window[8], projector[13];
    therapy_fixed_vector_group1_ref_init(vector, 0);
    ring_span_fixed_vector_init(window, vector);
    asv_breath_shape_harmonic_projector_init(projector, window);
    int middle = (span->start + landmark) % 1000;
    float a, b, c, d;
    projection_bounds(window, span->start, middle);
    asv_breath_shape_project_first_segment(projector, &a, &b);
    projection_bounds(window, middle, (span->start + span->count) % 1000);
    asv_breath_shape_project_second_segment(projector, &c, &d);
    float numerator = (b + d) * (b + d);
    float denominator = (a + c) * (a + c) + numerator;
    float magnitudes = absolute(b) + absolute(d);
    if (denominator > 0.0f && magnitudes > 0.0f &&
            minimum(b / magnitudes, d / magnitudes) >= 0.3f)
        return numerator / denominator;
    return 0.0f;
}

float breath_shape_index(float ratio, int duration) {
    return duration > 350 ? 0.0f : linear_map_clamped_2point(ratio, 0.17f, 0.0f, 0.3f, 1.0f);
}

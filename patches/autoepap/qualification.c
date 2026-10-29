/* Locate inspiratory onset from the rising edge around the flow peak. */
int qualify_onset(const Span *span, int *onset, int *ambiguous, int *half_peak) {
    int peak = 0;
    *ambiguous = 0;
    *onset = 0;
    for (int i = 1; i < span->count; ++i)
        if (sample(span, i) > sample(span, peak)) peak = i;
    float height = sample(span, peak);
    if (!(height > 0.0f)) return 0;
    int half = 0, high = 0, seen = 0;
    for (int i = 0; i <= peak; ++i) {
        float value = sample(span, i);
        if (value >= height * 0.5f && !seen) { half = i; seen = 1; }
        if (value >= height * 0.75f) { high = i; break; }
    }
    int low = high;
    while (low > 0 && sample(span, low) > height * 0.25f) --low;
    if (half <= low) { *ambiguous = 1; *half_peak = half; return 0; }
    if (low == high) return 0;
    float slope = (sample(span, high) - sample(span, low)) / (float)(high - low);
    int first = slope > 0.0f ? (int)((float)low - sample(span, low) / slope + 0.5f) : 0;
    if (first < 0) first = 0;
    if (first > span->count) first = span->count;
    *onset = first;
    return 1;
}

/* Peak decline changes the temporary onset-fit window. */
int qualify_peak_end(const Span *span, int start) {
    int best = start;
    float peak = sample(span, start), drop = peak * 0.2f;
    for (int i = start; i < span->count; ++i) {
        float value = sample(span, i);
        if (value > peak) { peak = value; best = i; }
        else if (value <= peak - drop) break;
    }
    return best;
}

/* Negative runs at the tail are compared with positive mean flow. */
int qualify_end(const Span *span) {
    float positive = 0.0f;
    int positive_count = 0, has_negative = 0;
    for (int i = 0; i < span->count; ++i) {
        float value = sample(span, i);
        if (value < 0.0f) has_negative = 1;
        else { positive += value; ++positive_count; }
    }
    if (!positive_count) return 0;
    float mean = positive / (float)positive_count;
    if (!has_negative || !(mean > 0.0f)) return span->count;
    int end = span->count, in_run = 0, count = 0;
    float run = 0.0f, suffix = 0.0f;
    for (int i = span->count - 1; i >= 0; --i) {
        float value = sample(span, i);
        if (!in_run) {
            if (value < 0.0f) { in_run = 1; count = 0; run = 0.0f; }
        } else if (value < 0.0f) { ++count; run += value; }
        else {
            in_run = 0;
            if (!count) continue;
            float relative_mean = -(run / (float)count) / mean;
            float relative_volume = -(((run * 1000.0f) / 6000.0f) / 1000.0f) / mean;
            if (!(suffix >= 0.0f &&
                  (relative_mean < 0.20000002f || relative_volume < 0.0005f) &&
                  relative_volume < 0.0008333334f)) end = i + 1;
        }
        suffix += value;
    }
    return end;
}

int qualify_window(const Span *span, float target, Span *result) {
    *result = *span;
    if (!qualify_breath(span, target)) { result->count = 0; return 0; }
    Span fitting = *span;
    int first = 0, ambiguous = 0, half = 0;
    qualify_onset(&fitting, &first, &ambiguous, &half);
    for (int i = 0; i < 2 && ambiguous; ++i) {
        fitting.count = qualify_peak_end(&fitting, half);
        qualify_onset(&fitting, &first, &ambiguous, &half);
    }
    result->start = (span->start + first) % 1000;
    result->count = span->count - first;
    result->count = qualify_end(result);
    return 1;
}

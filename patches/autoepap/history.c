typedef struct { int start, end; float weight, pressure; } Interval;
typedef struct {
    Interval records[10];
    int count;
    u32 valid;
    int shape_active, shape_start, shape_ticks;
    float shape_pressure;
    int reduced_active, reduced_start;
    float reduced_pressure;
} EventHistory;

/* Keep nine retained intervals and one slot for the next append. */
void interval_append(EventHistory *h, int start, int end, float weight, float pressure) {
    Interval *r = h->records + h->count;
    r->start = start;
    r->end = end;
    r->weight = weight;
    r->pressure = pressure;
    h->valid |= 1u << h->count;
    if (++h->count > 9) h->count = 9;
}

void reduced_history_capture(EventHistory *h, unsigned events, int now,
                             float weight, float pressure) {
    if (events & (1u << 14)) {
        h->reduced_active = 1;
        h->reduced_start = now;
        h->reduced_pressure = pressure;
    }
    if ((events & (1u << 15)) && h->reduced_active) {
        h->reduced_active = 0;
        interval_append(h, h->reduced_start, now, weight, h->reduced_pressure);
    }
}

typedef struct {
    int time, covered;
    float weight;
    int starts;
    float pressure;
} Boundary;

/* insert unique, ordered endpoints. */
static void boundary_insert(Boundary *points, int *count, int time) {
    int pos = 0;
    while (pos < *count && points[pos].time < time) ++pos;
    if (pos < *count && points[pos].time == time) return;
    for (int i = *count; i > pos; --i) points[i] = points[i - 1];
    points[pos].time = time;
    points[pos].covered = points[pos].starts = 0;
    points[pos].weight = points[pos].pressure = 0.0f;
    ++*count;
}

/* Merge overlapping intervals using their maximum weight per unit time. */
int consolidate_intervals(EventHistory *h, int before) {
    Boundary points[20];
    int count = 0;
    for (int i = 0; i < h->count; ++i) {
        Interval *r = h->records + i;
        if (r->start < r->end && r->end < before) {
            boundary_insert(points, &count, r->start);
            boundary_insert(points, &count, r->end);
        }
    }
    for (int i = 0; i < h->count; ++i) {
        Interval *r = h->records + i;
        if (!(r->start < r->end && r->end < before)) continue;
        int p = 0;
        while (points[p].time != r->start) ++p;
        points[p].starts = 1;
        points[p].pressure = r->pressure;
        float density = r->weight / (float)(r->end - r->start);
        while (points[p].time != r->end) {
            float weight = (float)(points[p + 1].time - points[p].time) * density;
            if (!points[p].covered || points[p].weight < weight) points[p].weight = weight;
            points[p++].covered = 1;
        }
        h->valid &= ~(1u << i);
    }
    int kept = 0;
    for (int i = 0; i < h->count; ++i)
        if (h->valid & (1u << i)) h->records[kept++] = h->records[i];
    h->count = kept;
    h->valid = (1u << kept) - 1u;
    int active = 0, start = 0;
    float weight = 0.0f, pressure = 0.0f;
    for (int i = 0; i + 1 < count; ++i) {
        if (points[i].covered) {
            if (!active) {
                start = points[i].time;
                weight = 0.0f;
                pressure = points[i].pressure;
                active = 1;
            }
            weight += points[i].weight;
        } else if (active) {
            interval_append(h, start, points[i].time, weight, pressure);
            active = 0;
        }
    }
    if (active) interval_append(h, start, points[count - 1].time, weight, pressure);
    return kept;
}

/* Consume completed consolidated records. */
float event_pressure_target(EventHistory *h, int before, float upper) {
    float target = 0.0f;
    if (!h->count) return target;
    int kept = consolidate_intervals(h, before);
    for (int i = kept; i < h->count; ++i) {
        const Interval *r = h->records + i;
        float duration = r->weight / 100.0f;
        if (duration < 9.0f) continue;
        float ceiling = maximum(upper + 2.0f, 12.0f);
        target = maximum(target, r->pressure);
        if (ceiling > target)
            target += (1.0f - expf((10.0f / ceiling) * -0.022221666f * duration)) *
                      (ceiling - target);
    }
    h->count = kept;
    h->valid &= (1u << kept) - 1u;
    return target;
}

/* Capture indices are ring positions; times are 100 Hz ticks. */
float shape_history_capture(EventHistory *h, int shape, int now, int head,
                            int start, int end, float reference_flow,
                            float current_epap, float shape_correction, float upper) {
    int duration = (end - start + 1000) % 1000;
    int delay = (head - end + 1000) % 1000;
    int onset = now - duration - delay - 1;
    int active = shape == 1 && reference_flow < 48.000004f;
    if (!h->shape_active) {
        if (active) {
            h->shape_active = 1;
            h->shape_start = onset;
            h->shape_ticks = duration;
            h->shape_pressure = current_epap;
        }
    } else if (active) h->shape_ticks += duration;
    else {
        h->shape_active = 0;
        if (onset - h->shape_start == h->shape_ticks)
            interval_append(h, h->shape_start, onset, (float)h->shape_ticks, h->shape_pressure);
    }
    return maximum(event_pressure_target(h, onset, upper) - (current_epap + shape_correction), 0.0f);
}

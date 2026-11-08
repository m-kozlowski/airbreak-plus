#include "breath_tracking.h"
#include "stubs.h"

void init_history(history_t *hist) {
  for(int i=0; i<HISTORY_LENGTH; i++) {
    hist->flow[i] = 0.0f;
    hist->cmd_ipap[i] = 0.0f;
  }
  hist->tick = -1;
}

void update_history(history_t *hist) {
  hist->tick += 1;
  const int i = hist->tick & (HISTORY_LENGTH - 1);
  hist->flow[i] = *flow_compensated;
  hist->cmd_ipap[i] = *cmd_ipap;
}

float get_delta_flow(history_t *hist, int bin_size) {
  const int t = hist->tick;
  if (t < 2*bin_size) { return 0.0f; }
  float recent = 0.0f;
  float previous = 0.0f;
  for (int i=0; i<bin_size; i++) {
    recent += hist->flow[(t-i) & (HISTORY_LENGTH - 1)];
  }
  for (int i=bin_size; i<2*bin_size; i++) {
    previous += hist->flow[(t-i) & (HISTORY_LENGTH - 1)];
  }
  return (recent - previous) / (float)(bin_size*bin_size);
}


bool is_cmd_ipap_constant(history_t *hist) {
  const int t = hist->tick;
  if (t < 4) { return false; }
  const int t1 = t & (HISTORY_LENGTH - 1);
  const int t2 = (t-4) & (HISTORY_LENGTH - 1);
  return absf(hist->cmd_ipap[t1] - hist->cmd_ipap[t2]) <= 0.041f;
}


///////////////////////////////
// All-purpose tracking code //

void init_breath(breath_t *breath) {
  breath->volume = 0.0f;
  breath->volume_max = 0.0f;
  breath->exh_maxflow = 0.0f;
  breath->inh_maxflow = 0.0f;
  breath->t = 0;
  breath->ti = 0.0f;
  breath->te = 0.0f;
}
void init_tracking(tracking_t *tr) {
  tr->breath_count = 0;
  tr->tick = 0;
  tr->st_inhaling = false;
  tr->st_just_started = false;
  tr->st_valid_breath = false;
  tr->st_full_breath = false;
  tr->st_pre_trigger = 0;
  tr->st_pre_cycle = 0;

  init_breath(&tr->recent);
  tr->recent.te = 2.0f; tr->recent.ti = 1.6f; tr->recent.volume_max = 0.3f; tr->recent.exh_maxflow = -25.0f; tr->recent.inh_maxflow = 25.0f; // Init with reasonable-ish defaults in case code wants to rely on these
  init_breath(&tr->last);
  init_breath(&tr->current);

  tr->final_ps = 0.0f;
}

// Called after the stock detectors, only for an accepted phase event.
void finish_tracking(tracking_t *tr, bool inhaling) {
  if (inhaling == tr->st_inhaling) { return; }
  if (inhaling) {
    tr->st_inhaling = true; tr->st_just_started = true; tr->st_pre_trigger = 0; tr->st_pre_cycle = 0;

    tr->last = tr->current;
    tr->breath_count += 1;
    init_breath(&tr->current);
    tr->final_ps = *cmd_ps;

    // Exclude the initial partial record, not short complete breaths.
    tr->st_valid_breath = tr->st_full_breath;
    tr->st_full_breath = true;
    if (tr->st_valid_breath) {
      inplace(lerp, &tr->recent.volume_max, tr->last.volume_max, tr_coeff);
      inplace(lerp, &tr->recent.exh_maxflow, tr->last.exh_maxflow, tr_coeff);
      inplace(lerp, &tr->recent.inh_maxflow, tr->last.inh_maxflow, tr_coeff);
      inplace(lerp, &tr->recent.ti, tr->last.ti, tr_coeff);
      // Limit one record's influence while still adapting to sustained changes.
      const float te_limit = tr->recent.te * 0.5f;
      tr->recent.te += tr_coeff * clamp(tr->last.te - tr->recent.te, -te_limit, te_limit);
    }
  } else {
    tr->st_inhaling = false; tr->st_just_started = true; tr->st_pre_trigger = 0; tr->st_pre_cycle = 0;
    tr->final_ps = *cmd_ps;
  }
}

// Sample N closes the previous 10 ms interval. The stock phase decision follows
// this integration; a new phase starts at zero without counting this sample twice.
void prepare_tracking(tracking_t *tr, history_t *hist) {
  tr->st_just_started = false;
  tr->tick += 1; tr->current.t += 1;
  if (tr->st_inhaling) {
    tr->current.ti += 0.01f;
    inplace(max, &tr->current.inh_maxflow, *flow_compensated);

    if (*flow_compensated < tr->current.inh_maxflow * sens_cycle) {
      if (tr->st_pre_cycle < 255) { tr->st_pre_cycle += 1; }
    }
    else { tr->st_pre_cycle = max(tr->st_pre_cycle - 1, 0); } // Don't just reset it

  } else {
    tr->current.te += 0.01f;
    inplace(min, &tr->current.exh_maxflow, *flow_compensated);

    // If flow extrapolated 80ms(~blower delay) into the future crosses threshold, increment pretrigger
    const float flow2 = max(*flow_compensated, *flow_compensated + get_delta_flow(hist, 4)*8.0f); // Flow extrapolated 80ms into the future
    if (flow2 > sens_trigger) {
      if (tr->st_pre_trigger < 255) { tr->st_pre_trigger += 1; }
    }
    else { tr->st_pre_trigger = 0; } // This has to reset, flow doesn't slow down during the start of a breath
  }

  tr->current.volume += (*flow_compensated / 60.0f) * 0.01f;
  inplace(max, &tr->current.volume, 0.0f);
  inplace(max, &tr->current.volume_max, tr->current.volume);
}

extern void *breath_progress_worker_register(void);
extern void *breath_timing_progress_worker_register(void);
extern void breath_phase_ramp_worker_update(breath_node *);
extern const unsigned int breath_tracking_attach_prepare;
extern const unsigned int breath_tracking_attach_finish;
typedef void (*tracking_attach)(breath_tracking_t *);
static const breath_method tracking_prepare_methods[7];

breath_tracking_t *breath_tracking_find(void) {
  breath_node *n = ((breath_node **)therapy_manager_get())[4];
  while (n && n->methods != tracking_prepare_methods) { n = n->next; }
  return (breath_tracking_t *)n;
}

STATIC void tracking_noop(breath_node *node) { }

STATIC void tracking_stop(breath_node *node) {
  breath_tracking_t *s = (breath_tracking_t *)node;
  s->prepare.enabled = s->finish.enabled = 0;
  s->reset = true;
}

STATIC void tracking_mode(breath_node *node) {
  breath_tracking_t *s = (breath_tracking_t *)node;
  int mode = ivars[0x12];
  s->prepare.enabled = s->finish.enabled = mode == MODE_VAUTO || mode == MODE_S;
  s->reset = true;
}

STATIC uint32 breath_events(void) {
  // Group 2's event word is cleared before its 100 Hz worker pass.
  return ((uint32 *)therapy_manager_get())[8] & 0x3fu;
}

STATIC void tracking_prepare(breath_node *node) {
  breath_tracking_t *s = (breath_tracking_t *)node;
  if (s->reset) {
    init_history(&s->hist);
    init_tracking(&s->tr);
    // Adopt the retained native phase after the mode callbacks have run.
    if (ivars[0x71] == 2) { s->tr.st_inhaling = s->progress[0x20] != 0; }
    else if (ivars[0x71] == 1) {
      uint32 events = breath_events();
      // T's transition precedes preparation; the sample closes the old phase.
      s->tr.st_inhaling = events ? (events & 0x38u) != 0 : s->timed[0x10] == 0;
    } else { s->tr.st_inhaling = s->timing[0x28] != 0; }
    s->reset = false;
  }
  // Flow is fresh; the pressure command is still from the preceding tick.
  update_history(&s->hist);
  prepare_tracking(&s->tr, &s->hist);
}

STATIC void tracking_finish(breath_node *node) {
  breath_tracking_t *s = (breath_tracking_t *)((unsigned char *)node -
                           __builtin_offsetof(breath_tracking_t, finish));
  uint32 events = breath_events();
  if (events & 7u) { finish_tracking(&s->tr, true); }
  else if (events & 0x38u) { finish_tracking(&s->tr, false); }
}

static const breath_method tracking_prepare_methods[7] = {
  tracking_noop, tracking_noop, tracking_stop, tracking_mode, tracking_mode, tracking_stop, tracking_prepare
};
static const breath_method tracking_finish_methods[7] = {
  tracking_noop, tracking_noop, tracking_noop, tracking_noop, tracking_noop, tracking_noop, tracking_finish
};

void *breath_tracking_register_prepare(void) {
  breath_tracking_t *s = breath_tracking_find();
  if (!s) {
    s = malloc(sizeof(*s));
    unsigned char *p = (unsigned char *)s;
    for (unsigned i = 0; i < sizeof(*s); ++i) { p[i] = 0; }
    init_history(&s->hist);
    init_tracking(&s->tr);
    s->reset = true;
    therapy_worker_append(&s->prepare, 2);
    s->prepare.methods = tracking_prepare_methods;
    s->prepare.enabled = 0;
    if (breath_tracking_attach_prepare != 0xFFFFFFFFu) {
      ((tracking_attach)breath_tracking_attach_prepare)(s);
    }
  }
  s->progress = breath_progress_worker_register();
  return s->progress;
}

void *breath_tracking_register_finish(void) {
  breath_tracking_t *s = breath_tracking_find();
  s->timing = breath_timing_progress_worker_register();
  if (!s->finish.methods) {
    therapy_worker_append(&s->finish, 2);
    s->finish.methods = tracking_finish_methods;
    s->finish.enabled = 0;
    breath_node *n = ((breath_node **)therapy_manager_get())[4];
    while (n && n->methods[6] != breath_phase_ramp_worker_update) { n = n->next; }
    s->timed = (unsigned char *)n;
    if (breath_tracking_attach_finish != 0xFFFFFFFFu) {
      ((tracking_attach)breath_tracking_attach_finish)(s);
    }
  }
  return s->timing;
}

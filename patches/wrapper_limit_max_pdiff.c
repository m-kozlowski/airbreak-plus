#include "stubs.h"
#include "common_code.h"

#include "my_asv.h" // Include the asv_data_t definition

const float INSTANT_PS = 0.45f;

typedef struct {
  float eps; // EPS (cmH2O) - used to prevent instant jumps in pressure in case of autotriggering
  float ips_fa; // Flow-Assist IPS (cmH2O) - currently used to augment pretrigger effort
} features_t;

STATIC void init_features(features_t *feat) {
  feat->eps = 0.0f;
  feat->ips_fa = 0.0f;
}


extern void pressure_limit_max_difference();
extern int variable_get_by_id(int var_id);
extern const unsigned short wrapper_limit_max_pdiff_toggle_var_id;
extern const unsigned short wrapper_limit_max_pdiff_triggercycle_var_id;
extern const unsigned short wrapper_limit_max_pdiff_asv_max_var_id;
extern const unsigned short wrapper_limit_max_pdiff_asv_sens_var_id;

STATIC bool custom_g8_toggle(unsigned short var_id, bool fallback) {
  return (var_id == 0xFFFFu) ? fallback : (variable_get_by_id((int)var_id) != 0);
}

STATIC int custom_var_raw(unsigned short var_id, int fallback) {
  return (var_id == 0xFFFFu) ? fallback : variable_get_by_id((int)var_id);
}

STATIC float custom_asv_sens_multiplier(void) {
  switch (custom_var_raw(wrapper_limit_max_pdiff_asv_sens_var_id, 2)) {
    case 0: return 0.50f;
    case 1: return 0.75f;
    case 3: return 1.25f;
    case 4: return 1.50f;
    case 2:
    default: return 1.00f;
  }
}

typedef struct breath_node breath_node;
typedef void (*breath_method)(breath_node *);
struct breath_node {
  const breath_method *methods;
  breath_node *next;
  uint32 enabled;
};

typedef enum {
  VAUTO_OFF,
  VAUTO_WAIT_INSPIRATION,
  VAUTO_ACTIVE,
} vauto_state_t;

typedef struct {
  breath_node prepare, finish;
  unsigned char *progress, *timing, *timed;
  history_t *hist;
  tracking_t *tr;
  triggercycle_t *trc;
  int mode;
  vauto_state_t vauto_state;
  float asv_max, asv_sens;
  bool custom_enabled, custom_tc;
  volatile bool settings_dirty;
  bool reset;
} breath_pipeline_t;

extern void *therapy_manager_get(void);
extern void therapy_worker_append(breath_node *, int group);
extern void *breath_progress_worker_register(void);
extern void *breath_timing_progress_worker_register(void);
extern void breath_phase_ramp_worker_update(breath_node *);
static const breath_method prepare_methods[7];

void custom_breath_settings_changed(void) {
  // Startup callbacks can precede worker creation. Do not allocate state here.
  breath_node *n = ((breath_node **)therapy_manager_get())[4];
  while (n && n->methods != prepare_methods) { n = n->next; }
  if (n) { ((breath_pipeline_t *)n)->settings_dirty = true; }
}

STATIC void load_breath_settings(breath_pipeline_t *s) {
  // Clear before reading so a callback during the reload remains pending.
  s->settings_dirty = false;
  s->custom_enabled = custom_g8_toggle(wrapper_limit_max_pdiff_toggle_var_id, true);
  s->custom_tc = custom_g8_toggle(wrapper_limit_max_pdiff_triggercycle_var_id, true);
  s->asv_max = custom_var_raw(wrapper_limit_max_pdiff_asv_max_var_id, 0) / 50.0f;
  s->asv_sens = custom_asv_sens_multiplier();
}

STATIC void init_breath_pipeline(breath_pipeline_t *s) {
  unsigned char *p = (unsigned char *)s;
  for (unsigned i = 0; i < sizeof(*s); ++i) { p[i] = 0; }
  s->hist = get_history();
  s->tr = get_tracking();
  s->trc = get_triggercycle();
  s->settings_dirty = true;
  s->reset = true;
}

STATIC breath_pipeline_t *get_breath_pipeline(void) {
  return GET_PTR(PTR_BREATH_PIPELINE, breath_pipeline_t, init_breath_pipeline);
}

STATIC void breath_noop(breath_node *node) { }

STATIC void breath_stop(breath_node *node) {
  breath_pipeline_t *s = (breath_pipeline_t *)node;
  s->prepare.enabled = s->finish.enabled = 0;
  s->vauto_state = VAUTO_OFF;
  s->trc->trigger = s->trc->cycle = TC_STOCK;
  s->reset = true;
}

STATIC void breath_mode(breath_node *node) {
  breath_pipeline_t *s = (breath_pipeline_t *)node;
  // Lifecycle callbacks use the requested mode; I[6F] is published next tick.
  s->mode = ivars[0x12];
  s->prepare.enabled = s->finish.enabled = s->mode == MODE_VAUTO || s->mode == MODE_S;
  s->vauto_state = VAUTO_OFF;
  s->trc->trigger = s->trc->cycle = TC_STOCK;
  s->settings_dirty = true;
  s->reset = true;
}

STATIC uint32 breath_events(void) {
  // Group 2's event word is cleared before its 100 Hz worker pass.
  return ((uint32 *)therapy_manager_get())[8] & 0x3fu;
}

STATIC void reset_vauto_state(void) {
  init_asv_data(get_asv_data());
  init_features(GET_PTR(PTR_FEATURES, features_t, init_features));
}

STATIC void breath_prepare(breath_node *node) {
  breath_pipeline_t *s = (breath_pipeline_t *)node;
  if (s->settings_dirty) { load_breath_settings(s); }
  if (s->reset) {
    init_history(s->hist);
    init_tracking(s->tr);
    init_triggercycle(s->trc);
    reset_vauto_state();
    // The native mode callbacks have now run. A retained native phase is not
    // necessarily expiration, even when two modes share the same detector.
    if (ivars[0x71] == 2) { s->tr->st_inhaling = s->progress[0x20] != 0; }
    else if (ivars[0x71] == 1) {
      uint32 events = breath_events();
      // T's worker precedes preparation. On its transition tick the sample
      // still belongs to the phase that just ended.
      s->tr->st_inhaling = events ? (events & 0x38u) != 0 : s->timed[0x10] == 0;
    } else { s->tr->st_inhaling = s->timing[0x28] != 0; }
    s->reset = false;
  }

  bool requested = s->mode == MODE_VAUTO && vauto_ps > 0.0f && s->custom_enabled;
  if (!requested) {
    if (s->vauto_state != VAUTO_OFF) { reset_vauto_state(); }
    s->vauto_state = VAUTO_OFF;
  } else if (s->vauto_state == VAUTO_OFF) {
    s->vauto_state = VAUTO_WAIT_INSPIRATION;
  }

  // Flow and measured pressure are fresh; the pressure command is still N-1.
  update_history(s->hist);
  prepare_tracking(s->tr, s->hist);
  bool enabled = ivars[0x71] != 1 && s->custom_tc;
  if (s->mode == MODE_VAUTO) {
    enabled &= s->vauto_state == VAUTO_ACTIVE;
  }
  prepare_triggercycle(s->trc, s->tr, s->hist, enabled);
}

STATIC void breath_finish(breath_node *node) {
  breath_pipeline_t *s = (breath_pipeline_t *)((unsigned char *)node -
                            __builtin_offsetof(breath_pipeline_t, finish));
  uint32 events = breath_events();
  if (events & 7u) { finish_tracking(s->tr, true); }
  else if (events & 0x38u) { finish_tracking(s->tr, false); }
  if (s->vauto_state == VAUTO_WAIT_INSPIRATION &&
      s->tr->st_inhaling && s->tr->st_just_started) {
    s->vauto_state = VAUTO_ACTIVE;
  }
}

static const breath_method prepare_methods[7] = {
  breath_noop, breath_noop, breath_stop, breath_mode, breath_mode, breath_stop, breath_prepare
};
static const breath_method finish_methods[7] = {
  breath_noop, breath_noop, breath_noop, breath_noop, breath_noop, breath_noop, breath_finish
};

// These wrap two existing registrations, retaining the stock list order and
// vtables (including the optional iBR wrapper). Both nodes use the shared heap.
void *custom_breath_register_prepare(void) {
  breath_pipeline_t *s = get_breath_pipeline();
  if (!s->prepare.methods) {
    therapy_worker_append(&s->prepare, 2);
    s->prepare.methods = prepare_methods;
    s->prepare.enabled = 0;
  }
  s->progress = breath_progress_worker_register();
  return s->progress;
}

void *custom_breath_register_finish(void) {
  breath_pipeline_t *s = get_breath_pipeline();
  s->timing = breath_timing_progress_worker_register();
  if (!s->finish.methods) {
    therapy_worker_append(&s->finish, 2);
    s->finish.methods = finish_methods;
    s->finish.enabled = 0;
    // Cache the already-registered T worker without a fixed singleton RAM address.
    breath_node *n = ((breath_node **)therapy_manager_get())[4];
    while (n && n->methods[6] != breath_phase_ramp_worker_update) { n = n->next; }
    s->timed = (unsigned char *)n;
  }
  return s->timing;
}

// Assembly comparison hooks only read decisions prepared for this tick.
int custom_tc_decision(int cycle) {
  breath_pipeline_t *s = get_breath_pipeline();
  if (!s->prepare.enabled || s->reset) { return TC_STOCK; }
  return cycle ? s->trc->cycle : s->trc->trigger;
}

// Reshapes PS in 0.0-1.0 format to differently shaped slopes with `mult` times the AUC, first increasing slope before magnitude
// Only using ^4 shape, because going to ^8 and above is very jarring and results in bad premature cycling
STATIC float reshape_vauto_ps(float ps1, float mult) {
  // ^2 - 1.330, ^6 - 1.707, ^8 - 1.770
  float inverse = 1.0f - ps1;
  float inverse_squared = inverse * inverse;
  float ps4 = 1.0f - inverse_squared * inverse_squared;  // ~1.594x the AUC
  ps4 = ps4 * 0.25f + ps1 * 0.75f; // 25%=1.1485x, 50%=~1.297x the AUC
  const float auc = 1.1485;
  if (mult <= 1.0) { 
    return ps1; 
  } else if ((mult > 1.0) && (mult <= 2.0)) {
    return remap(mult, 1.0f, 2.0f, ps1, ps4 * (2.0f / auc));
  } else {
    return ps4 * (mult / auc);
  }

  return ps1;
}


void MAIN start() {
  breath_pipeline_t *s = get_breath_pipeline();
  if (s->vauto_state != VAUTO_ACTIVE || !(vauto_ps > 0.0f)) {
    pressure_limit_max_difference();
    return;
  }

  tracking_t *tr = s->tr;
  asv_data_t *asv = get_asv_data();
  float asv_max = wrapper_limit_max_pdiff_asv_max_var_id == 0xFFFFu ?
                  2.0f * vauto_ps : s->asv_max;
  asv->asv_sens = s->asv_sens;
  update_asv_data(asv, tr, asv_max > 0.0f);

  features_t *feat = GET_PTR(PTR_FEATURES, features_t, init_features);

  float new_ps = *cmd_ps;

  // The pre-ramp reference is EPAP + PS/2, so this uses EPAP - PS/2.
  float current_eps = clamp((*cmd_epap - vauto_ps) * 0.2f, 0.4f, 1.6f);

  const float ps = *cmd_ps + vauto_ps/2.0f;
  const float ps1 = (ps/vauto_ps); // 0.0 to 1.0

  if (tr->st_inhaling) {
    float base_ps = remap(ps1, 0.0f, 1.0f, feat->eps, vauto_ps-INSTANT_PS) + INSTANT_PS;
    new_ps = base_ps;
    if (asv_max > 0.0f) {
      float new_ps1 = reshape_vauto_ps(ps1, asv->asv_factor);
      float boosted_ps = remap(new_ps1, 0.0f, 1.0f, feat->eps, vauto_ps - INSTANT_PS) + INSTANT_PS*asv->asv_factor;
      new_ps = min(boosted_ps, base_ps + asv_max);
    }

    feat->ips_fa = 0.0f;
    feat->eps = min(feat->eps + 0.01f * current_eps, 0.0f);

    asv->final_ips = max(asv->final_ips, new_ps);
  } else { // Exhaling
    if (tr->current.ti >= 0.7f) {
      current_eps = max(0.0f, current_eps - (asv->final_ips - vauto_ps) * 0.25f);
      if (tr->st_just_started) { feat->eps = -current_eps; }
      else {
        float eps1 = remap01c(tr->current.volume / tr->current.volume_max, 0.10f, 0.7f);
        eps1 = sqrtf(eps1);
        eps1 = min(eps1, remap01c(tr->current.te, max(1.2f, tr->recent.te * 0.8f), max(0.4f, tr->recent.te * 0.4f)));
        feat->eps = max(feat->eps, -current_eps * eps1);
      }
    }
    float new_ps1 = ps1*ps1 * 0.75f + 0.25f * ps1;
    new_ps = remap(new_ps1, 0.0f, 1.0f, feat->eps, asv->final_ips);

    if (tr->st_pre_trigger > 0) { feat->ips_fa = min(tr->st_pre_trigger, 2) * 0.2f; };
    if (*flow_compensated <= 0.0f) { feat->ips_fa = 0.0f; }
    new_ps += feat->ips_fa;
  }

  // Convert support above EPAP back to the signed midpoint-relative waveform.
  new_ps = *cmd_ps + (new_ps - ps);

  const float orig_ps = *cmd_ps;
  *cmd_ps = new_ps;
  pressure_limit_max_difference(); // Execute the original function
  *cmd_ps = orig_ps;
}

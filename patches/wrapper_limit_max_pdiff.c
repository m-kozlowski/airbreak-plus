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


// +1 pointer address: 0x000f93d0. Original function address: 0x080bc992
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

STATIC float custom_asv_max_cm(void) {
  if (wrapper_limit_max_pdiff_asv_max_var_id == 0xFFFFu) {
    return 2.0f * vauto_ps;
  }
  int raw = variable_get_by_id((int)wrapper_limit_max_pdiff_asv_max_var_id);
  return raw / 50.0f;
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
  bool custom_enabled = custom_g8_toggle(wrapper_limit_max_pdiff_toggle_var_id, true);
  if ((*therapy_mode == MODE_VAUTO) && (!custom_enabled || vauto_ps <= 0.0f)) {
    pressure_limit_max_difference();
    return;
  }

  history_t *hist = get_history();
  update_history(hist);
  tracking_t *tr = get_tracking();
  update_tracking(tr);
  asv_data_t *asv = get_asv_data();
  float asv_max = custom_asv_max_cm();
  asv->asv_sens = custom_asv_sens_multiplier();
  update_asv_data(asv, tr);
  if (asv_max <= 0.0f) { asv->asv_factor = 1.0f; }

  features_t *feat = GET_PTR(PTR_FEATURES, features_t, init_features);

  apply_jitter(true);

  float dps = 0.0f;
  bool triggercycle_toggle = custom_g8_toggle(wrapper_limit_max_pdiff_triggercycle_var_id, true);

  triggercycle_t *trc = get_triggercycle();
  trc->custom_trigger = trc->custom_cycle = false; // Default state is off.
  if (triggercycle_toggle && (*therapy_mode == MODE_S)) {
    trc->custom_trigger = true;
    trc->custom_cycle = true;
  }
  else if (triggercycle_toggle && (*therapy_mode == MODE_VAUTO)) {
    trc->custom_trigger = true;
    trc->custom_cycle = true;
  }
  update_triggercycle(trc, tr);

  float new_ps = *cmd_ps;

  if (*therapy_mode == MODE_VAUTO) {

    float current_eps = clamp((*cmd_epap - vauto_ps) * 0.2f, 0.4f, 1.6f);

    int t = hist->tick;
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

    new_ps = *cmd_ps + (new_ps - ps); // Correction for the bizarre way VAuto handles the *cmd_ps fvar
  }

  const float orig_ps = *cmd_ps;
  *cmd_ps = new_ps;
  pressure_limit_max_difference(); // Execute the original function
  *cmd_ps = orig_ps;

  apply_jitter(false);
}

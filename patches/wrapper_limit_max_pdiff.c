#include "stubs.h"
#include "common_code.h"

#include "my_asv.h" // Include the asv_data_t definition

const float INSTANT_PS = 0.45f;
const float EPS = 1.2f;

typedef struct
{
  float mode;
  float st_inhaling;
  float st_just_started;
  float st_pre_trigger;
  float current_eps;
  float ps;
  float ps1;
  float new_ps;
  float returned_ps;
  float feat_eps;
  float feat_ips_fa;
  float asv_factor;
  float final_ips;
  float volume;
  float volume_max;
  float ti;
  float te;
} vauto_debug_t;

typedef struct
{
  float eps;    // EPS (cmH2O) - used to prevent instant jumps in pressure in case of autotriggering
  float ips_fa; // Flow-Assist IPS (cmH2O) - currently used to augment pretrigger effort
  // Debug snapshot read by tcl/airsense-info.tcl. It lives inside the existing
  // PTR_FEATURES allocation so we do not write to guessed RAM or add a pointer-table slot.
  vauto_debug_t dbg;
} features_t;

STATIC void init_features(features_t *feat)
{
  feat->eps = 0.0f;
  feat->ips_fa = 0.0f;
  feat->dbg.mode = 0.0f;
  feat->dbg.st_inhaling = 0.0f;
  feat->dbg.st_just_started = 0.0f;
  feat->dbg.st_pre_trigger = 0.0f;
  feat->dbg.current_eps = 0.0f;
  feat->dbg.ps = 0.0f;
  feat->dbg.ps1 = 0.0f;
  feat->dbg.new_ps = 0.0f;
  feat->dbg.returned_ps = 0.0f;
  feat->dbg.feat_eps = 0.0f;
  feat->dbg.feat_ips_fa = 0.0f;
  feat->dbg.asv_factor = 0.0f;
  feat->dbg.final_ips = 0.0f;
  feat->dbg.volume = 0.0f;
  feat->dbg.volume_max = 0.0f;
  feat->dbg.ti = 0.0f;
  feat->dbg.te = 0.0f;
}

// +1 pointer address: 0x000f93d0. Original function address: 0x080bc992
extern void pressure_limit_max_difference();

// Reshapes PS in 0.0-1.0 format to differently shaped slopes with `mult` times the AUC, first increasing slope before magnitude
// Only using ^4 shape, because going to ^8 and above is very jarring and results in bad premature cycling
STATIC float reshape_vauto_ps(float ps1, float mult)
{
  // ^2 - 1.330, ^6 - 1.707, ^8 - 1.770
  float ps4 = 1.0f - pow(1.0f - ps1, 4); // ~1.594x the AUC
  ps4 = ps4 * 0.25f + ps1 * 0.75f;       // 25%=1.1485x, 50%=~1.297x the AUC
  const float auc = 1.1485;
  if (mult <= 1.0)
  {
    return ps1;
  }
  else if ((mult > 1.0) && (mult <= 2.0))
  {
    return remap(mult, 1.0f, 2.0f, ps1, ps4 * (2.0f / auc));
  }
  else
  {
    return ps4 * (mult / auc);
  }

  return ps1;
}

STATIC float calculate_vauto_inhale_ps(float ps1, float current_eps, tracking_t *tr, asv_data_t *asv, features_t *feat)
{
  float new_ps = remap(ps1, 0.0f, 1.0f, feat->eps, vauto_ps - INSTANT_PS) + INSTANT_PS;
  bool toggle = (ti_min <= 150);
  if (toggle)
  { // Disable if Ti min is set to above 0.1s
    float new_ps1 = reshape_vauto_ps(ps1, asv->asv_factor);
    new_ps = remap(new_ps1, 0.0f, 1.0f, feat->eps, vauto_ps - INSTANT_PS) + INSTANT_PS * asv->asv_factor;
  }

  feat->ips_fa = 0.0f;
  feat->eps = min(feat->eps + 0.01f * current_eps, 0.0f);

  asv->final_ips = max(asv->final_ips, new_ps);
  return new_ps;
}

STATIC float calculate_vauto_exhale_ps(float ps1, float current_eps, tracking_t *tr, asv_data_t *asv, features_t *feat)
{
  if (tr->current.ti >= 0.7f)
  {
    current_eps = max(0.0f, current_eps - (asv->final_ips - vauto_ps) * 0.25f);
    if (tr->st_just_started)
    {
      feat->eps = -current_eps;
    }
    else
    {
      float eps1 = 0.0f;
      // volume_max can still be zero near therapy startup or odd phase transitions.
      // Keep eps1 at zero instead of creating NaN/Inf from volume / volume_max.
      if (tr->current.volume_max > 0.0f)
      {
        eps1 = remap01c(tr->current.volume / tr->current.volume_max, 0.10f, 0.7f);
        eps1 = sqrtf(eps1);
      }
      eps1 = min(eps1, remap01c(tr->current.te, max(1.2f, tr->recent.te * 0.8f), max(0.4f, tr->recent.te * 0.4f)));
      feat->eps = max(feat->eps, -current_eps * eps1);
    }
  }

  float new_ps1 = ps1 * ps1 * 0.75f + 0.25f * ps1;
  float new_ps = remap(new_ps1, 0.0f, 1.0f, feat->eps, asv->final_ips);

  if (tr->st_pre_trigger > 0)
  {
    feat->ips_fa = min(tr->st_pre_trigger, 2) * 0.2f;
  };
  if (*flow_compensated <= 0.0f)
  {
    feat->ips_fa = 0.0f;
  }
  new_ps += feat->ips_fa;
  return new_ps;
}

STATIC float calculate_vauto_ps(tracking_t *tr, asv_data_t *asv, features_t *feat)
{
  // These VAuto fvars are runtime bounds, not direct clinician-menu settings.
  // The UI Max IPAP / Min EPAP values can be reconstructed as bound +/- PS/2.
  float current_eps = clamp((*cmd_epap - vauto_ps) * 0.2f, 0.4f, 1.6f);

  const float ps = *cmd_ps + vauto_ps / 2.0f;
  const float ps1 = (ps / vauto_ps); // 0.0 to 1.0

  float new_ps = tr->st_inhaling
                     ? calculate_vauto_inhale_ps(ps1, current_eps, tr, asv, feat)
                     : calculate_vauto_exhale_ps(ps1, current_eps, tr, asv, feat);

  const float returned_ps = *cmd_ps + (new_ps - ps); // Correction for the bizarre way VAuto handles the *cmd_ps fvar

  // Snapshot after calculating side effects so Tcl sees the values used for this tick.
  feat->dbg.mode = (float)*therapy_mode;
  feat->dbg.st_inhaling = tr->st_inhaling ? 1.0f : 0.0f;
  feat->dbg.st_just_started = tr->st_just_started ? 1.0f : 0.0f;
  feat->dbg.st_pre_trigger = (float)tr->st_pre_trigger;
  feat->dbg.current_eps = current_eps;
  feat->dbg.ps = ps;
  feat->dbg.ps1 = ps1;
  feat->dbg.new_ps = new_ps;
  feat->dbg.returned_ps = returned_ps;
  feat->dbg.feat_eps = feat->eps;
  feat->dbg.feat_ips_fa = feat->ips_fa;
  feat->dbg.asv_factor = asv->asv_factor;
  feat->dbg.final_ips = asv->final_ips;
  feat->dbg.volume = tr->current.volume;
  feat->dbg.volume_max = tr->current.volume_max;
  feat->dbg.ti = tr->current.ti;
  feat->dbg.te = tr->current.te;

  return returned_ps;
}

void MAIN start()
{
  history_t *hist = get_history();
  update_history(hist);
  tracking_t *tr = get_tracking();
  update_tracking(tr);
  asv_data_t *asv = get_asv_data();
  update_asv_data(asv, tr);

  features_t *feat = GET_PTR(PTR_FEATURES, features_t, init_features);

  apply_jitter(true);

  triggercycle_t *trc = get_triggercycle();
  trc->custom_trigger = trc->custom_cycle = false; // Default state is off.
  if (*therapy_mode == MODE_S)
  {
    trc->custom_trigger = true;
    trc->custom_cycle = true;
  }
  else if (*therapy_mode == MODE_VAUTO)
  {
    trc->custom_trigger = true;
    trc->custom_cycle = true;
  }
  update_triggercycle(trc, tr);

  float new_ps = *cmd_ps;

  if (*therapy_mode == MODE_VAUTO)
  {
    new_ps = calculate_vauto_ps(tr, asv, feat);
  }

  const float orig_ps = *cmd_ps;
  *cmd_ps = new_ps;
  pressure_limit_max_difference(); // Execute the original function
  *cmd_ps = orig_ps;

  apply_jitter(false);
}

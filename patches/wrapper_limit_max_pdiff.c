#include "stubs.h"
#include "common_code.h"

#include "my_asv.h" // Include the asv_data_t definition

const float INSTANT_PS = 0.45f;
const float EPS = 1.2f;

typedef struct
{
  float mode;
  float is_inhaling;
  float phase_just_started;
  float pre_trigger_ticks;
  float current_eps;
  float runtime_ps_center;
  float normalized_ps;
  float target_ps;
  float returned_cmd_ps;
  float feature_eps;
  float feature_ips_flow_assist;
  float asv_factor;
  float final_ips;
  float volume;
  float volume_max;
  float ti;
  float te;
  float config_trigger_raw;
  float config_cycle_raw;
  float config_max_ipap;
  float config_min_epap;
  float config_ps;
  float config_ti_min;
  float config_ti_max;
} vauto_debug_t;

typedef struct
{
  float eps;             // EPS (cmH2O) - used to prevent instant jumps in pressure in case of autotriggering
  float ips_flow_assist; // Flow-Assist IPS (cmH2O) - currently used to augment pretrigger effort
  // Debug snapshot read by tcl/airsense-info.tcl. It lives inside the existing
  // PTR_FEATURES allocation so we do not write to guessed RAM or add a pointer-table slot.
  vauto_debug_t dbg;
} features_t;

STATIC void init_features(features_t *features)
{
  features->eps = 0.0f;
  features->ips_flow_assist = 0.0f;
  features->dbg.mode = 0.0f;
  features->dbg.is_inhaling = 0.0f;
  features->dbg.phase_just_started = 0.0f;
  features->dbg.pre_trigger_ticks = 0.0f;
  features->dbg.current_eps = 0.0f;
  features->dbg.runtime_ps_center = 0.0f;
  features->dbg.normalized_ps = 0.0f;
  features->dbg.target_ps = 0.0f;
  features->dbg.returned_cmd_ps = 0.0f;
  features->dbg.feature_eps = 0.0f;
  features->dbg.feature_ips_flow_assist = 0.0f;
  features->dbg.asv_factor = 0.0f;
  features->dbg.final_ips = 0.0f;
  features->dbg.volume = 0.0f;
  features->dbg.volume_max = 0.0f;
  features->dbg.ti = 0.0f;
  features->dbg.te = 0.0f;
  features->dbg.config_trigger_raw = 0.0f;
  features->dbg.config_cycle_raw = 0.0f;
  features->dbg.config_max_ipap = 0.0f;
  features->dbg.config_min_epap = 0.0f;
  features->dbg.config_ps = 0.0f;
  features->dbg.config_ti_min = 0.0f;
  features->dbg.config_ti_max = 0.0f;
}

// +1 pointer address: 0x000f93d0. Original function address: 0x080bc992
extern void pressure_limit_max_difference();
extern int variable_get_g8(int var_id);

// Shape the within-breath pressure curve without changing the configured PS range.
// Higher powers felt abrupt in testing and tended to cause premature cycling.
STATIC float reshape_vauto_ps(float normalized_ps, float multiplier)
{
  float fourth_order_ps = 1.0f - pow(1.0f - normalized_ps, 4);
  float blended_ps = fourth_order_ps * 0.25f + normalized_ps * 0.75f;
  const float blended_auc = 1.1485f;
  if (multiplier <= 1.0f)
  {
    return normalized_ps;
  }
  else if (multiplier <= 2.0f)
  {
    return remap(multiplier, 1.0f, 2.0f, normalized_ps, blended_ps * (2.0f / blended_auc));
  }
  else
  {
    return blended_ps * (multiplier / blended_auc);
  }
}

STATIC float calculate_vauto_inhale_ps(float normalized_ps, float current_eps, tracking_t *tracking, asv_data_t *asv, features_t *features)
{
  float target_ps = remap(normalized_ps, 0.0f, 1.0f, features->eps, vauto_ps - INSTANT_PS) + INSTANT_PS;
  bool use_shaped_inhale = (ti_min <= 150);
  if (use_shaped_inhale)
  {
    // TiMin is used as a visible kill switch for this more aggressive curve.
    float shaped_ps = reshape_vauto_ps(normalized_ps, asv->asv_factor);
    target_ps = remap(shaped_ps, 0.0f, 1.0f, features->eps, vauto_ps - INSTANT_PS) + INSTANT_PS * asv->asv_factor;
  }

  features->ips_flow_assist = 0.0f;
  features->eps = min(features->eps + 0.01f * current_eps, 0.0f);

  asv->final_ips = max(asv->final_ips, target_ps);
  return target_ps;
}

STATIC float calculate_vauto_exhale_ps(float normalized_ps, float current_eps, tracking_t *tracking, asv_data_t *asv, features_t *features)
{
  if (tracking->current.ti >= 0.7f)
  {
    current_eps = max(0.0f, current_eps - (asv->final_ips - vauto_ps) * 0.25f);
    if (tracking->st_just_started)
    {
      features->eps = -current_eps;
    }
    else
    {
      float exhale_progress = 0.0f;
      // volume_max can still be zero near therapy startup or odd phase transitions.
      // Keep progress at zero instead of creating NaN/Inf from volume / volume_max.
      if (tracking->current.volume_max > 0.0f)
      {
        exhale_progress = remap01c(tracking->current.volume / tracking->current.volume_max, 0.10f, 0.7f);
        exhale_progress = sqrtf(exhale_progress);
      }
      exhale_progress = min(exhale_progress, remap01c(tracking->current.te, max(1.2f, tracking->recent.te * 0.8f), max(0.4f, tracking->recent.te * 0.4f)));
      features->eps = max(features->eps, -current_eps * exhale_progress);
    }
  }

  float exhale_curve = normalized_ps * normalized_ps * 0.75f + 0.25f * normalized_ps;
  float target_ps = remap(exhale_curve, 0.0f, 1.0f, features->eps, asv->final_ips);

  if (tracking->st_pre_trigger > 0)
  {
    features->ips_flow_assist = min(tracking->st_pre_trigger, 2) * 0.2f;
  };
  if (*flow_compensated <= 0.0f)
  {
    features->ips_flow_assist = 0.0f;
  }
  target_ps += features->ips_flow_assist;
  return target_ps;
}

STATIC float calculate_vauto_ps(tracking_t *tracking, asv_data_t *asv, features_t *features)
{
  // VAuto keeps cmd_ps around a shifted midpoint, not as direct pressure support.
  // Work in normalized PS for shaping, then return the shifted value the stock limiter expects.
  float current_eps = clamp((*cmd_epap - vauto_ps) * 0.2f, 0.4f, 1.6f);

  const float runtime_ps_center = *cmd_ps + vauto_ps / 2.0f;
  const float normalized_ps = runtime_ps_center / vauto_ps;

  float target_ps = tracking->st_inhaling
                        ? calculate_vauto_inhale_ps(normalized_ps, current_eps, tracking, asv, features)
                        : calculate_vauto_exhale_ps(normalized_ps, current_eps, tracking, asv, features);

  const float returned_cmd_ps = *cmd_ps + (target_ps - runtime_ps_center);

  // Snapshot after calculating side effects so Tcl sees the values used for this tick.
  features->dbg.mode = (float)*therapy_mode;
  features->dbg.is_inhaling = tracking->st_inhaling ? 1.0f : 0.0f;
  features->dbg.phase_just_started = tracking->st_just_started ? 1.0f : 0.0f;
  features->dbg.pre_trigger_ticks = (float)tracking->st_pre_trigger;
  features->dbg.current_eps = current_eps;
  features->dbg.runtime_ps_center = runtime_ps_center;
  features->dbg.normalized_ps = normalized_ps;
  features->dbg.target_ps = target_ps;
  features->dbg.returned_cmd_ps = returned_cmd_ps;
  features->dbg.feature_eps = features->eps;
  features->dbg.feature_ips_flow_assist = features->ips_flow_assist;
  features->dbg.asv_factor = asv->asv_factor;
  features->dbg.final_ips = asv->final_ips;
  features->dbg.volume = tracking->current.volume;
  features->dbg.volume_max = tracking->current.volume_max;
  features->dbg.ti = tracking->current.ti;
  features->dbg.te = tracking->current.te;
  // Direct config values read through the firmware variable accessor.
  // Pressure and timing config values use raw/50 scaling in resmed_config.py.
  features->dbg.config_trigger_raw = (float)variable_get_g8(0x0246);
  features->dbg.config_cycle_raw = (float)variable_get_g8(0x0245);
  features->dbg.config_max_ipap = (float)variable_get_g8(0x01D6) / 50.0f;
  features->dbg.config_min_epap = (float)variable_get_g8(0x01D5) / 50.0f;
  features->dbg.config_ps = (float)variable_get_g8(0x01D7) / 50.0f;
  features->dbg.config_ti_min = (float)variable_get_g8(0x01DC) / 50.0f;
  features->dbg.config_ti_max = (float)variable_get_g8(0x01DD) / 50.0f;

  return returned_cmd_ps;
}

void MAIN start()
{
  history_t *history = get_history();
  update_history(history);
  tracking_t *tracking = get_tracking();
  update_tracking(tracking);
  asv_data_t *asv = get_asv_data();
  update_asv_data(asv, tracking);

  features_t *features = GET_PTR(PTR_FEATURES, features_t, init_features);

  apply_jitter(true);

  triggercycle_t *trigger_cycle = get_triggercycle();
  trigger_cycle->custom_trigger = trigger_cycle->custom_cycle = false;
  if (*therapy_mode == MODE_S)
  {
    trigger_cycle->custom_trigger = true;
    trigger_cycle->custom_cycle = true;
  }
  else if (*therapy_mode == MODE_VAUTO)
  {
    trigger_cycle->custom_trigger = true;
    trigger_cycle->custom_cycle = true;
  }
  update_triggercycle(trigger_cycle, tracking);

  float command_ps_for_limiter = *cmd_ps;

  if (*therapy_mode == MODE_VAUTO)
  {
    command_ps_for_limiter = calculate_vauto_ps(tracking, asv, features);
  }

  const float original_cmd_ps = *cmd_ps;
  *cmd_ps = command_ps_for_limiter;
  pressure_limit_max_difference();
  *cmd_ps = original_cmd_ps;

  apply_jitter(false);
}

#include "stubs.h"
#include "common_code.h"

#include "my_asv.h"

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
  float eps;
  float ips_flow_assist;
  vauto_debug_t debug;
} vauto_features_t;

extern void pressure_limit_max_difference();
extern int variable_get_g8(int var_id);

STATIC void init_vauto_features(vauto_features_t *features);
STATIC float calculate_vauto_command_ps(tracking_t *tracking, asv_data_t *asv, vauto_features_t *features);
STATIC float calculate_inhale_target_ps(float normalized_ps, float current_eps, asv_data_t *asv, vauto_features_t *features);
STATIC float calculate_exhale_target_ps(float normalized_ps, float current_eps, tracking_t *tracking, asv_data_t *asv, vauto_features_t *features);
STATIC float reshape_inhale_ps(float normalized_ps, float multiplier);
STATIC void capture_vauto_debug(vauto_features_t *features, tracking_t *tracking, asv_data_t *asv, float current_eps, float runtime_ps_center, float normalized_ps, float target_ps, float returned_cmd_ps);

void MAIN start()
{
  history_t *history = get_history();
  update_history(history);

  tracking_t *tracking = get_tracking();
  update_tracking(tracking);

  asv_data_t *asv = get_asv_data();
  update_asv_data(asv, tracking);

  vauto_features_t *features = GET_PTR(PTR_FEATURES, vauto_features_t, init_vauto_features);

  apply_jitter(true);

  triggercycle_t *trigger_cycle = get_triggercycle();
  trigger_cycle->custom_trigger = false;
  trigger_cycle->custom_cycle = false;

  if (*therapy_mode == MODE_S || *therapy_mode == MODE_VAUTO)
  {
    trigger_cycle->custom_trigger = true;
    trigger_cycle->custom_cycle = true;
  }
  update_triggercycle(trigger_cycle, tracking);

  float command_ps_for_stock_limiter = *cmd_ps;
  if (*therapy_mode == MODE_VAUTO)
  {
    command_ps_for_stock_limiter = calculate_vauto_command_ps(tracking, asv, features);
  }

  const float original_cmd_ps = *cmd_ps;
  *cmd_ps = command_ps_for_stock_limiter;
  pressure_limit_max_difference();
  *cmd_ps = original_cmd_ps;

  apply_jitter(false);
}

STATIC void init_vauto_features(vauto_features_t *features)
{
  features->eps = 0.0f;
  features->ips_flow_assist = 0.0f;

  features->debug.mode = 0.0f;
  features->debug.is_inhaling = 0.0f;
  features->debug.phase_just_started = 0.0f;
  features->debug.pre_trigger_ticks = 0.0f;
  features->debug.current_eps = 0.0f;
  features->debug.runtime_ps_center = 0.0f;
  features->debug.normalized_ps = 0.0f;
  features->debug.target_ps = 0.0f;
  features->debug.returned_cmd_ps = 0.0f;
  features->debug.feature_eps = 0.0f;
  features->debug.feature_ips_flow_assist = 0.0f;
  features->debug.asv_factor = 0.0f;
  features->debug.final_ips = 0.0f;
  features->debug.volume = 0.0f;
  features->debug.volume_max = 0.0f;
  features->debug.ti = 0.0f;
  features->debug.te = 0.0f;
  features->debug.config_trigger_raw = 0.0f;
  features->debug.config_cycle_raw = 0.0f;
  features->debug.config_max_ipap = 0.0f;
  features->debug.config_min_epap = 0.0f;
  features->debug.config_ps = 0.0f;
  features->debug.config_ti_min = 0.0f;
  features->debug.config_ti_max = 0.0f;
}

STATIC float calculate_vauto_command_ps(tracking_t *tracking, asv_data_t *asv, vauto_features_t *features)
{
  const float current_eps = clamp((*cmd_epap - vauto_ps) * 0.2f, 0.4f, 1.6f);

  // In VAuto, firmware stores a PS-centered runtime value. Convert to normalized
  // 0..1 pressure support so inhale/exhale shaping is independent of the absolute PS.
  const float runtime_ps_center = *cmd_ps + vauto_ps / 2.0f;
  const float normalized_ps = runtime_ps_center / vauto_ps;

  const float target_ps = tracking->st_inhaling
                              ? calculate_inhale_target_ps(normalized_ps, current_eps, asv, features)
                              : calculate_exhale_target_ps(normalized_ps, current_eps, tracking, asv, features);

  // Stock VAuto applies cmd_ps around a shifted center, so feed the stock limiter
  // the delta from our target rather than the target pressure support directly.
  const float returned_cmd_ps = *cmd_ps + (target_ps - runtime_ps_center);

  capture_vauto_debug(features, tracking, asv, current_eps, runtime_ps_center, normalized_ps, target_ps, returned_cmd_ps);

  return returned_cmd_ps;
}

STATIC float calculate_inhale_target_ps(float normalized_ps, float current_eps, asv_data_t *asv, vauto_features_t *features)
{
  float target_ps = remap(normalized_ps, 0.0f, 1.0f, features->eps, vauto_ps - INSTANT_PS) + INSTANT_PS;

  // TiMin above 0.1s is used as an operator-visible kill switch for the aggressive
  // ASV-shaped inhale curve, avoiding another hidden setting channel.
  if (ti_min <= 150)
  {
    const float shaped_ps = reshape_inhale_ps(normalized_ps, asv->asv_factor);
    target_ps = remap(shaped_ps, 0.0f, 1.0f, features->eps, vauto_ps - INSTANT_PS) + INSTANT_PS * asv->asv_factor;
  }

  features->ips_flow_assist = 0.0f;
  features->eps = min(features->eps + 0.01f * current_eps, 0.0f);
  asv->final_ips = max(asv->final_ips, target_ps);

  return target_ps;
}

STATIC float calculate_exhale_target_ps(float normalized_ps, float current_eps, tracking_t *tracking, asv_data_t *asv, vauto_features_t *features)
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
      // Keeping progress at zero avoids NaN/Inf leaking into pressure commands.
      if (tracking->current.volume_max > 0.0f)
      {
        exhale_progress = remap01c(tracking->current.volume / tracking->current.volume_max, 0.10f, 0.7f);
        exhale_progress = sqrtf(exhale_progress);
      }

      const float timing_progress = remap01c(tracking->current.te, max(1.2f, tracking->recent.te * 0.8f), max(0.4f, tracking->recent.te * 0.4f));
      exhale_progress = min(exhale_progress, timing_progress);
      features->eps = max(features->eps, -current_eps * exhale_progress);
    }
  }

  const float exhale_curve = normalized_ps * normalized_ps * 0.75f + 0.25f * normalized_ps;
  float target_ps = remap(exhale_curve, 0.0f, 1.0f, features->eps, asv->final_ips);

  if (tracking->st_pre_trigger > 0)
  {
    features->ips_flow_assist = min(tracking->st_pre_trigger, 2) * 0.2f;
  }

  if (*flow_compensated <= 0.0f)
  {
    features->ips_flow_assist = 0.0f;
  }

  return target_ps + features->ips_flow_assist;
}

STATIC float reshape_inhale_ps(float normalized_ps, float multiplier)
{
  const float fourth_order = 1.0f - pow(1.0f - normalized_ps, 4);
  const float blended_curve = fourth_order * 0.25f + normalized_ps * 0.75f;
  const float blended_curve_auc = 1.1485f;

  if (multiplier <= 1.0f)
  {
    return normalized_ps;
  }

  if (multiplier <= 2.0f)
  {
    return remap(multiplier, 1.0f, 2.0f, normalized_ps, blended_curve * (2.0f / blended_curve_auc));
  }

  return blended_curve * (multiplier / blended_curve_auc);
}

STATIC void capture_vauto_debug(vauto_features_t *features, tracking_t *tracking, asv_data_t *asv, float current_eps, float runtime_ps_center, float normalized_ps, float target_ps, float returned_cmd_ps)
{
  features->debug.mode = (float)*therapy_mode;
  features->debug.is_inhaling = tracking->st_inhaling ? 1.0f : 0.0f;
  features->debug.phase_just_started = tracking->st_just_started ? 1.0f : 0.0f;
  features->debug.pre_trigger_ticks = (float)tracking->st_pre_trigger;
  features->debug.current_eps = current_eps;
  features->debug.runtime_ps_center = runtime_ps_center;
  features->debug.normalized_ps = normalized_ps;
  features->debug.target_ps = target_ps;
  features->debug.returned_cmd_ps = returned_cmd_ps;
  features->debug.feature_eps = features->eps;
  features->debug.feature_ips_flow_assist = features->ips_flow_assist;
  features->debug.asv_factor = asv->asv_factor;
  features->debug.final_ips = asv->final_ips;
  features->debug.volume = tracking->current.volume;
  features->debug.volume_max = tracking->current.volume_max;
  features->debug.ti = tracking->current.ti;
  features->debug.te = tracking->current.te;

  // These are true config reads, not runtime fvars. Scaling matches resmed_config.py.
  features->debug.config_trigger_raw = (float)variable_get_g8(0x0246);
  features->debug.config_cycle_raw = (float)variable_get_g8(0x0245);
  features->debug.config_max_ipap = (float)variable_get_g8(0x01D6) / 50.0f;
  features->debug.config_min_epap = (float)variable_get_g8(0x01D5) / 50.0f;
  features->debug.config_ps = (float)variable_get_g8(0x01D7) / 50.0f;
  features->debug.config_ti_min = (float)variable_get_g8(0x01DC) / 50.0f;
  features->debug.config_ti_max = (float)variable_get_g8(0x01DD) / 50.0f;
}

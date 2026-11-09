#include "stubs.h"
#include "common_code.h"
#include "breath_tracking.h"

const float EPS_FIXED_TIME = 1.2f;

extern int variable_get_by_id(int var_id);
extern const unsigned short squarewave_enable_var_id;
extern const unsigned int squarewave_original_handler;

typedef void (*squarewave_handler_t)(int param_1);

STATIC bool squarewave_enabled(void) {
  if (squarewave_enable_var_id == 0xFFFFu) {
    return true;
  }
  return variable_get_by_id((int)squarewave_enable_var_id) != 0;
}

STATIC void squarewave_call_original(int param_1) {
  if (squarewave_original_handler != 0xFFFFFFFFu) {
    ((squarewave_handler_t)squarewave_original_handler)(param_1);
  }
}

// The entry point. All other functions **must** be marked INLINE or STATIC
void MAIN start(int param_1) {
  if (!squarewave_enabled()) {
    squarewave_call_original(param_1);
    return;
  }

  // The two tracking workers have already consumed this tick's flow and phase events.
  const breath_tracking_t *tracking = breath_tracking_find();
  if (!tracking) {
    squarewave_call_original(param_1);
    return;
  }
  const tracking_t *tr = &tracking->tr;

  const float s_eps = 0.8f;                // (cmH2O)
  const float s_rise_time = s_rise_time_f; // (s)
  const float s_fall_time = 0.8f;          // (s)

  // Set the commanded PS and EPAP values based on our target
  *cmd_epap = s_epap;
  if (tr->st_inhaling) {
    const float t = tr->current.ti;
    const float smooth_time = 0.075f; // (s) Smooth the last N ms of the ramp into 2N of half-speed ramp
    const float t2 = min(t, s_rise_time - smooth_time) + clamp((t-(s_rise_time-smooth_time))*0.5f, 0.0f, smooth_time);

    float perc = 0.1f + 0.7f * remap01c(t2, 0.0f, s_rise_time) + (0.4f * breath_progress); // breath_progress during inhale is 0-0.5

    perc = max(0.0f, perc - (tr->st_pre_cycle * 0.01f) / 1.5f ); // 1.5s to go from 100->0% of PS

    *cmd_ps = s_ips * perc;
  } else { // Exhale
    const float t = tr->current.te;
    // Without a positive peak volume, use the time-based relief alone.
    float eps_mult = remap01c(t, EPS_FIXED_TIME, 0.4f);
    if (tr->current.volume_max > 0.0f) {
      eps_mult = min(remap01c(tr->current.volume / tr->current.volume_max, 0.1f, 0.7f), eps_mult);
    }

    float ips_mult = remap01c(t, s_fall_time, 0.0f); ips_mult = ips_mult * ips_mult * 0.95f;
    
    *cmd_ps = ips_mult * tr->final_ps - (1.0f - ips_mult) * eps_mult * s_eps;
  }
  
  // Limit support to the configured PS and maximum exhale relief.
  *cmd_ps = clamp(*cmd_ps, -s_eps, s_ips);

  return;
}

#include "stubs.h"
#include "common_code.h"

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

// This is where the real magic starts
// The entry point. All other functions **must** be marked INLINE or STATIC
void MAIN start(int param_1) {
  if (!squarewave_enabled()) {
    squarewave_call_original(param_1);
    return;
  }

  // It's updated in `wrapper_limit_max_pdiff` which always runs
  tracking_t *tr = get_tracking();

  const float s_eps = 0.8f;                // (s)
  const float s_rise_time = s_rise_time_f; // (s)
  const float s_fall_time = 0.8f;          // (s)

  // Binary toggle if IPAP ends in 0.2 or 0.8
  const float a = (s_ipap - (int)s_ipap);
  const int8 toggle = (((a >= 0.1f) && (a <= 0.3f)) || ((a >= 0.7f) && (a <= 0.9f)));

  const float delta = 0.010f; // It's 10+-0.01ms, basically constant
  const float flow = *flow_compensated / 60.0f; // (L/s)


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
    float eps_mult = remap01c(tr->current.volume / tr->current.volume_max, 0.1f, 0.7f);
    eps_mult = min(eps_mult, remap01c(t, EPS_FIXED_TIME, 0.4f));

    float ips_mult = remap01c(t, s_fall_time, 0.0f); ips_mult = ips_mult * ips_mult * 0.95f;
    
    *cmd_ps = ips_mult * tr->final_ps - (1.0f - ips_mult) * eps_mult * s_eps;
  }
  
  // Safeguards against going cray cray
  *cmd_ps = clamp(*cmd_ps, -s_eps, s_ips);
  *cmd_epap = clamp(*cmd_epap, s_epap, s_epap);
  *cmd_ipap = *cmd_epap + *cmd_ps;

  return;
}

#ifndef _my_asv_c_
#define _my_asv_c_

#include "my_asv.h"

/////////////////////////
// PID Controller Code //

void pid_init(pid_t *pid, float p, float i, float d, float _min, float _max) {
  pid->last_error = 0.0f;
  pid->cumulative_error = 0.0f;
  pid->current_error = 0.0f;
  pid->kp = p; pid->ki = i; pid->kd = d;
  pid->output_min = _min;
  pid->output_max = _max;
}

float pid_get_signal(pid_t *pid) {
  float result = pid->kp * pid->current_error; // Proportional branch
  result += pid->cumulative_error; // Integral branch (pre-multiplied by pid->ki in update)
  result += pid->kd * (pid->current_error - pid->last_error); // Derivative branch
  return clamp(result, pid->output_min, pid->output_max);
}

void pid_update(pid_t *pid, float current_error) {
  pid->last_error = pid->current_error;
  pid->current_error = current_error;
  // Instead of a typical saturation check, just pre-multiply by ki and clamp to min/max
  pid->cumulative_error += pid->ki * pid->current_error;
  pid->cumulative_error = clamp(pid->cumulative_error, pid->output_min, pid->output_max);
}

////////////////////////
// ASV algorithm code //

asv_data_t *get_asv_data() {
  asv_data_t *asv = GET_PTR(PTR_ASV_DATA, asv_data_t, init_asv_data);
  const unsigned now = tim_read_tim5();
  // Initialize if it's the first time or more than 0.1s elapsed, suggesting that the therapy was stopped and re-started.
  if ((now - asv->last_time) > 100000) { init_asv_data(asv); }
  asv->last_time = now;

  return asv;
}

void init_asv_data(asv_data_t *data) {
  data->last_time = tim_read_tim5();
  data->breath_count = 0;

  data->ticks = -1; // Uninitialized

  pid_init(&data->pid, asv_pid_p, asv_pid_i, asv_pid_d, asv_pid_min, asv_pid_max);
  data->asv_factor = 1.0f;
  data->final_ips = 0.0f;
  data->asv_sens = 1.0f;

  data->asv_dampen = 0.0f;
  data->asv_skip = -ASV_BREATH_SKIP;

  data->target_vol = 0.0f;
  data->target_vol2 = 0.0f;

  for(int i=0; i<ASV_STEP_COUNT+1; i++) {
    data->targets_current[i] = 0.0f;
    data->targets_recent[i] = 0.0f;
    data->targets_recent2[i] = 0.0f;
  }
}

void update_asv_data(asv_data_t* asv, tracking_t* tr) {
  // TODO: Wait for average error to stabilize before engaging ASV
  breath_t *current = &tr->current;
  breath_t *last = &tr->last;
  breath_t *recent = &tr->recent;

  // Handle starting a new breath
  if (tr->st_inhaling && tr->st_just_started && tr->st_valid_breath) { // New breath just started
    float asv_coeff3 = asv_coeff2;
    if (last->volume_max > asv->target_vol2) { asv_coeff3 *= 0.5f; }
    if (last->volume_max > asv->target_vol2 * 1.3f) { asv_coeff3 *= 0.5f; }
    if (last->volume_max < asv->target_vol2 * 0.7f) { asv_coeff3 *= 0.5f; }
    inplace(lerp, &asv->target_vol2, last->volume_max, asv_coeff3);
    inplace(lerp, &asv->target_vol, asv->target_vol2, asv_coeff1);

    for(int i=0; i<ASV_STEP_COUNT+1; i++) {
      // If it has zero volume, it means the breath was past its peak already, ignore it.
      if (asv->targets_current[i] > 0.0f) {
        inplace(lerp, &asv->targets_recent2[i], asv->targets_current[i], asv_coeff3);
        inplace(lerp, &asv->targets_recent[i], asv->targets_recent2[i], asv_coeff1);
      }
      asv->targets_current[i] = 0.0f;
    }

    asv->final_ips = 0.0f;
    asv->breath_count += 1;

    // Skip first N breaths needing ASV, to ensure it doesn't fire on autotriggered breaths or other noise.
    if (pid_get_signal(&asv->pid) <= 0.1f) {
      asv->asv_skip = max(asv->asv_skip - 1, -ASV_BREATH_SKIP);
    } else if (asv->asv_skip < 0) {
      asv->asv_skip += 1;
      inplace(min, &asv->pid.cumulative_error, ASV_BREATH_SKIP_MAX_FACTOR);
    } else {
      asv->asv_skip = ASV_BREATH_SKIP_OFF; // This many breaths not needing ASV to turn it back off
    }

    // Handle ASV target dampening after hyperpneas.
    if (asv_dampen_max > 0.0f) {
      float error_volume = (last->volume_max - recent->volume_max) / (recent->volume_max + 0.001f);
      if (error_volume > 0.0f) { error_volume = max(error_volume - 0.1f, 0.0f) * 1.25f; }
      else { error_volume = (error_volume - 0.025f) * 0.75f; }
      asv->asv_dampen = clamp(asv->asv_dampen * 0.9f + error_volume, 0.0f, 1.0f);
    }
  }

  float asv_mod = 0.0f;
  if (asv_dampen_max > 0.0f) {
    asv_mod = (asv->asv_dampen > 0.1f) ? (-1.0f * asv_dampen_max * asv->asv_dampen) : 0.0f;
  }


  // Handle the ASV checkpoints and calculate error signal for the PID 
  // FIXME: The padded step logic needs to calculate with STEP_SKIP better
  int i = current->t / ASV_STEP_LENGTH - ASV_STEP_SKIP + 1;
  if ((current->t%ASV_STEP_LENGTH == 0) && (i>=0) && (i<ASV_STEP_COUNT+1) && tr->st_inhaling) {
    asv->targets_current[i] = current->volume;
    if (i >= 1) { // Ignore the first, padded step 
      const float error_volume = asv->targets_current[i] / (asv->targets_recent[i] + 0.001f);
      const float recent_flow = asv->targets_recent[i] - asv->targets_recent[i-1];
      const float current_flow = asv->targets_current[i] - asv->targets_current[i-1];
      const float error_flow = current_flow / (recent_flow + 0.001f);

      float error = remap01c(error_volume, asv_low + asv_mod, 0.4f + asv_mod) - remap01c(error_volume, asv_high + asv_mod*0.5f, 1.4f + asv_mod*0.5f);
      // Speed up tiny adjustments slightly.
      if (error > 0.0f) { error = error * 0.975f - 0.025f; }
      if (error < 0.0f) { error = error * 0.95f - 0.05f; }

      pid_update(&asv->pid, error);
    }
  }

  // Diminish the asv factor during the first `(N+1)*50ms`, to avoid huge sudden PS in case of false breaths
  const float mult = remap01c(1.0f * current->t, 0.0f, 1.0f * ASV_STEP_LENGTH * (ASV_STEP_SKIP+1));
  float pid_signal = pid_get_signal(&asv->pid) * asv->asv_sens;
  asv->asv_factor = clamp(1.0f + pid_signal * mult, 1.0f, 1.0f + asv_pid_max);
 
  if (asv->asv_skip < 0) {
    inplace(min, &asv->asv_factor, 1.0f + ASV_BREATH_SKIP_MAX_FACTOR);
  }
}

#endif

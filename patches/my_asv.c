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
  return GET_PTR(PTR_ASV_DATA, asv_data_t, init_asv_data);
}

STATIC void asv_reset_feedback(asv_data_t *asv) {
  pid_init(&asv->pid, asv_pid_p, asv_pid_i, asv_pid_d, asv_pid_min, asv_pid_max);
  asv->asv_skip = -ASV_BREATH_SKIP;
  asv->breath_need = ASV_UNKNOWN;
  asv->pid_updated = false;
}

void init_asv_data(asv_data_t *data) {
  data->breath_count = 0;

  data->tracking_tick = (uint32)-1;

  asv_reset_feedback(data);
  data->asv_factor = 1.0f;
  data->final_ips = 0.0f;
  data->asv_sens = 1.0f;

  data->asv_dampen = 0.0f;

  data->target_vol = 0.0f;
  data->target_vol2 = 0.0f;
  data->checkpoints = 0;
  data->full_inspiration = false;
  data->boost_enabled = false;

  for(int i=0; i<ASV_STEP_COUNT+1; i++) {
    data->targets_current[i] = 0.0f;
    data->targets_recent[i] = 0.0f;
    data->targets_recent2[i] = 0.0f;
    data->target_samples[i] = 0;
  }
}

STATIC void asv_learn_inspiration(asv_data_t *asv, float volume_max) {
  float asv_coeff3 = asv_coeff2;
  if (volume_max > asv->target_vol2) { asv_coeff3 *= 0.5f; }
  if (volume_max > asv->target_vol2 * 1.3f) { asv_coeff3 *= 0.5f; }
  if (volume_max < asv->target_vol2 * 0.7f) { asv_coeff3 *= 0.5f; }

  if (asv->breath_count < ASV_WARMUP_BREATHS) {
    inplace(lerp, &asv->target_vol, volume_max, 1.0f / (asv->breath_count + 1));
    asv->target_vol2 = asv->target_vol;
  } else {
    inplace(lerp, &asv->target_vol2, volume_max, asv_coeff3);
    inplace(lerp, &asv->target_vol, volume_max, tr_coeff);
  }
  asv->breath_count += 1;

  for(int i=0; i<ASV_STEP_COUNT+1; i++) {
    if (asv->checkpoints & (1u << i)) {
      if (asv->target_samples[i] < ASV_WARMUP_BREATHS) {
        // Average raw samples once, then seed both stages with that mean.
        asv->target_samples[i] += 1;
        inplace(lerp, &asv->targets_recent[i], asv->targets_current[i], 1.0f / asv->target_samples[i]);
        asv->targets_recent2[i] = asv->targets_recent[i];
      } else {
        inplace(lerp, &asv->targets_recent2[i], asv->targets_current[i], asv_coeff3);
        inplace(lerp, &asv->targets_recent[i], asv->targets_recent2[i], asv_coeff1);
      }
    }
  }

  // Use the completed inspiration, not volume accumulated during expiration.
  if (asv_dampen_max > 0.0f && asv->breath_count >= ASV_WARMUP_BREATHS) {
    float error_volume = (volume_max - asv->target_vol) / (asv->target_vol + 0.001f);
    if (error_volume > 0.0f) { error_volume = max(error_volume - 0.1f, 0.0f) * 1.25f; }
    else { error_volume = (error_volume - 0.025f) * 0.75f; }
    asv->asv_dampen = clamp(asv->asv_dampen * 0.9f + error_volume, 0.0f, 1.0f);
  }
}

STATIC void asv_apply_breath_need(asv_data_t *asv) {
  if (asv->breath_need == ASV_NO_NEED) {
    asv->asv_skip = max(asv->asv_skip - 1, -ASV_BREATH_SKIP);
  } else if (asv->breath_need == ASV_NEED) {
    if (asv->asv_skip < 0) {
      asv->asv_skip += 1;
      inplace(min, &asv->pid.cumulative_error, ASV_BREATH_SKIP_MAX_FACTOR);
    } else {
      asv->asv_skip = ASV_BREATH_SKIP_OFF; // This many breaths not needing ASV to turn it back off
    }
  }
}

void update_asv_data(asv_data_t* asv, tracking_t* tr, bool boost_enabled) {
  breath_t *current = &tr->current;

  if (boost_enabled != asv->boost_enabled) {
    // Keep learning while boost is off, but never resume accumulated demand.
    if (boost_enabled) { asv_reset_feedback(asv); }
    asv->breath_need = ASV_UNKNOWN;
    asv->pid_updated = false;
    asv->boost_enabled = boost_enabled;
  }

  // A bypass or restart must not turn a partial inspiration into learning data.
  if (tr->tick != asv->tracking_tick + 1) {
    asv->full_inspiration = false;
    asv->pid_updated = false;
    asv->breath_need = ASV_UNKNOWN;
  }
  asv->tracking_tick = tr->tick;

  if (tr->st_inhaling && tr->st_just_started) {
    if (boost_enabled) { asv_apply_breath_need(asv); }
    asv->breath_need = ASV_UNKNOWN;
    asv->full_inspiration = true;
    asv->pid_updated = false;
    asv->checkpoints = 0;
    for(int i=0; i<ASV_STEP_COUNT+1; i++) {
      asv->targets_current[i] = 0.0f;
    }
    asv->final_ips = 0.0f;
  }

  float asv_mod = 0.0f;
  if (asv_dampen_max > 0.0f) {
    asv_mod = (asv->asv_dampen > 0.1f) ? (-1.0f * asv_dampen_max * asv->asv_dampen) : 0.0f;
  }


  // t counts completed 10 ms intervals from the accepted inspiration event.
  // A cycle tick still contains the final inspiratory sample.
  // FIXME: The padded step logic needs to calculate with STEP_SKIP better
  int i = current->t / ASV_STEP_LENGTH - ASV_STEP_SKIP + 1;
  if (asv->full_inspiration && (current->t%ASV_STEP_LENGTH == 0) && (i>=0) && (i<ASV_STEP_COUNT+1) &&
      (tr->st_inhaling || tr->st_just_started)) {
    asv->targets_current[i] = current->volume;
    asv->checkpoints |= 1u << i;
    if (boost_enabled && i >= 1 && asv->target_samples[i] >= ASV_WARMUP_BREATHS) {
      const float error_volume = asv->targets_current[i] / (asv->targets_recent[i] + 0.001f);
      const float recent_flow = asv->targets_recent[i] - asv->targets_recent[i-1];
      const float current_flow = asv->targets_current[i] - asv->targets_current[i-1];
      const float error_flow = current_flow / (recent_flow + 0.001f);

      float error = remap01c(error_volume, asv_low + asv_mod, 0.4f + asv_mod) - remap01c(error_volume, asv_high + asv_mod*0.5f, 1.4f + asv_mod*0.5f);
      // Speed up tiny adjustments slightly.
      if (error > 0.0f) { error = error * 0.975f - 0.025f; }
      if (error < 0.0f) { error = error * 0.95f - 0.05f; }

      pid_update(&asv->pid, error);
      asv->pid_updated = true;
    }
  }

  if (!tr->st_inhaling && tr->st_just_started) {
    if (asv->full_inspiration) {
      // Capture the old reference's result before learning from this inspiration.
      asv->breath_need = !boost_enabled || !asv->pid_updated ? ASV_UNKNOWN :
                        pid_get_signal(&asv->pid) <= 0.1f ? ASV_NO_NEED : ASV_NEED;
      asv_learn_inspiration(asv, current->volume_max);
    }
    asv->full_inspiration = false;
  }

  asv->asv_factor = 1.0f;
  if (!asv->full_inspiration || !boost_enabled) { return; }

  // Diminish the asv factor during the first `(N+1)*50ms`, to avoid huge sudden PS in case of false breaths
  const float mult = remap01c(1.0f * current->t, 0.0f, 1.0f * ASV_STEP_LENGTH * (ASV_STEP_SKIP+1));
  float pid_signal = pid_get_signal(&asv->pid) * asv->asv_sens;
  asv->asv_factor = clamp(1.0f + pid_signal * mult, 1.0f, 1.0f + asv_pid_max);
 
  if (asv->asv_skip < 0) {
    inplace(min, &asv->asv_factor, 1.0f + ASV_BREATH_SKIP_MAX_FACTOR);
  }
}

#endif

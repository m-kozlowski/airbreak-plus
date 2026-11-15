#include "feat_triggercycle.h"

void init_triggercycle(triggercycle_t *trc) {
  trc->volbased = 0.0f;
  trc->trigger = trc->cycle = TC_STOCK;
}

// Runs once per tick before either native phase detector. F[7]/F[8] remain the
// configured sensitivities, including for stock rearming and waveform shaping.
void prepare_triggercycle(triggercycle_t *trc, tracking_t *tr, history_t *hist, bool enabled) {
  trc->trigger = trc->cycle = TC_STOCK;
  if (!tr->st_valid_sample) {
    trc->volbased = 0.0f;
    return;
  }
  if (tr->st_inhaling) {
    trc->volbased = 0.0f;
    if (enabled) {
      float fraction = -0.225f + 0.5f * sens_cycle;
      trc->cycle = (*flow_compensated < tr->current.inh_maxflow * fraction ||
                    tr->st_pre_cycle >= PRE_CYCLE_MAX_TICKS) ? TC_SWITCH : TC_HOLD;
    }
    return;
  }

  if (*flow_compensated < 0.0f) { trc->volbased = 0.0f; }
  else { trc->volbased += *flow_compensated / 60.0f * 0.01f; }
  if (!enabled) { return; }

  // Outside this window the native flow comparison remains in control.
  bool constant_pressure = is_cmd_ipap_constant(hist);
  if (!constant_pressure && !tr->st_pre_trigger) { return; }

  float score = remap01c(*flow_compensated, 0.0f, sens_trigger);
  if (tr->current.te >= 1.2f) {
    score += remap01c(trc->volbased, 0.020f, 0.040f) * 0.3f -
             remap01c(trc->volbased, 0.015f, 0.05f) * 0.2f;
  }
  if (constant_pressure) {
    // At this point F[1] is the current measurement and F[2A] is the command
    // from the preceding tick, before either waveform writes a new command.
    score += (remap01c(p_error, -0.1f, -0.35f) - remap01c(p_error, 0.1f, 0.35f)) * 0.3f;
  }
  score += remap01c(absf(tr->recent.te - tr->current.te), 0.3f, 0.0f) * 0.2f;
  trc->trigger = score >= 1.0f ? TC_SWITCH : TC_HOLD;
}

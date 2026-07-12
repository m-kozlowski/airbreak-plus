#ifndef _feat_triggercycle_c_
#define _feat_triggercycle_c_

#include "feat_triggercycle.h"

void init_triggercycle(triggercycle_t *trc) {
  trc->last_trigger = 0.0f;
  trc->real_trigger = sens_trigger;
  trc->last_cycle = 0.0f;
  trc->real_cycle = sens_cycle;

  trc->custom_trigger = false;
  trc->custom_cycle = false;
}

triggercycle_t* get_triggercycle() {
  return GET_PTR(PTR_TRIGGERCYCLE, triggercycle_t, init_triggercycle);
}

void update_triggercycle(triggercycle_t *trc, tracking_t *tr) {
  // If the value is changed, it means it was changed by the UI code due to user input. Update the reference value
  if (sens_trigger != trc->last_trigger) {
    trc->real_trigger = sens_trigger;
  }
  if (sens_cycle != trc->last_cycle) {
    trc->real_cycle = sens_cycle;
  }

  if (!trc->custom_trigger) { sens_trigger = trc->real_trigger; }
  if (!trc->custom_cycle) { sens_cycle = trc->real_cycle; }
  
  history_t *hist = get_history();

  if (tr->st_inhaling) {
    const float cti = tr->current.ti;
    const float s = trc->real_cycle;

    if (trc->custom_cycle) {
      float s2 = -0.225f + 0.5f * s; // Results in thresholds of: 0.025, -0.05, -0.1, -0.15, -0.185 (% of peak flow)
      if ( (flow_unfucked < (tr->current.inh_maxflow * s2)) || (tr->st_pre_cycle >= PRE_CYCLE_MAX_TICKS) ) {
        sens_cycle = 0.95; // Guarantee cycling
      } else {
        sens_cycle = -0.5; // Do not cycle (unless flow is very negative)
      }
    }
  } else {
    const float cte = tr->current.te;
    const float rte = tr->recent.te;
    const float s = trc->real_trigger;

    // Essentially: Increase threshold if we're >0.3s away from expected next inhale, more beyond >0.6s
    sens_trigger = remapc(cte, rte - 0.6f, rte - 0.3f, s * 1.2f + 2.0f, s * 1.0f);

    if(*flow_compensated < 0.0f) { trc->volbased = 0.0f; } else { trc->volbased += *flow_compensated / 60.0f * 0.01f; }

    // Fuzzy logic custom trigger that considers each of: flow, volume, pressure error(early inhalation reduces mask pressure before blower compensates), time(expected moment of next inhale)
    //  * Volbased: Most non-inhales only reach 10-15mL, most ineffective efforts reach 25-30mL
    //  * Pressure Error: usually goes to at least 0.2cmH2O below command just before detected inhales, sometimes up to 0.4-0.5. Random fluctuations usually stay within 0.15
    //  * Time-based: Slightly lower trigger threshold within +-0.3s of expected next 

    if (trc->custom_trigger && (is_cmd_ipap_constant(hist) || tr->st_pre_trigger > 0)) {
      float do_trigger = remap01c(*flow_compensated, 0.0f, s);

      if (cte >= 1.2f) {
        do_trigger += remap01c(trc->volbased, 0.020f, 0.040f) * 0.3f - remap01c(trc->volbased, 0.015f, 0.05f) * 0.2f;
      }
      if (is_cmd_ipap_constant(hist)) {
        do_trigger += (remap01c(p_error, -0.1f, -0.35f) - remap01c(p_error, 0.1f, 0.35f)) * 0.3f; 
      }

      do_trigger += remap01c(abs(rte-cte), 0.3f, 0.0f) * 0.2f;

      if (do_trigger >= 1.0f) {sens_trigger = -5.0f; } // Guarantee trigger
      else { sens_trigger = 999.0f; } // Make trigger impossible
    } else { sens_trigger = trc->real_trigger; }
  }

  trc->last_cycle = sens_cycle;
  trc->last_trigger = sens_trigger;
}


#endif
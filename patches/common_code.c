#include "common_code.h"
#include "stubs.h"

float remap(float s, float start, float end, float new_start, float new_end) {
  return new_start + remap01(s, start, end) * (new_end - new_start);
}

float remapc(float s, float start, float end, float new_start, float new_end) {
  return new_start + remap01c(s, start, end) * (new_end - new_start);
}

float remap01(float s, float start, float end) {
   return (s - start)/(end-start);
}

float remap01c(float s, float start, float end) {
   return clamp( remap01(s, start, end), 0.0f, 1.0f );
}

float lerp(float from, float to, float coeff) {
   return from + (to - from) * coeff;
}



typedef struct {
  unsigned magic;
  void** pointers;
} magic_ptr_t;

// NSTUB defines magic_ptr as an absolute symbol at the RAM address.
extern magic_ptr_t magic_ptr __attribute__((section(".absolute")));
#define magic_ptr_p (&magic_ptr)
const unsigned MAGIC = 0x07E49001;

void *get_pointer(ptr_index index, int size, void (*init_fn)(void*)) {
  const int max_pointers = __PTR_LAST;
  if (magic_ptr_p->magic != MAGIC) {
    magic_ptr_p->pointers = malloc(sizeof(void*) * max_pointers);
    magic_ptr_p->magic = MAGIC;
    for(int i=0; i<max_pointers; i++) {
      magic_ptr_p->pointers[i] = 0;
    }
  }
  if (magic_ptr_p->pointers[index] == 0) {
    magic_ptr_p->pointers[index] = malloc(size);
    init_fn(magic_ptr_p->pointers[index]);
  }
  return magic_ptr_p->pointers[index];
}


void init_history(history_t *hist) {
  for(int i=0; i<HISTORY_LENGTH; i++) {
    hist->flow[i] = 0.0f;
    hist->cmd_ipap[i] = 0.0f;
  }
  hist->tick = -1;
}

void update_history(history_t *hist) {
  hist->tick += 1;
  const int i = hist->tick & (HISTORY_LENGTH - 1);
  hist->flow[i] = *flow_compensated;
  hist->cmd_ipap[i] = *cmd_ipap;
}

history_t *get_history() { 
  return GET_PTR(PTR_HISTORY, history_t, init_history);
}

float get_delta_flow(history_t *hist, int bin_size) {
  const int t = hist->tick;
  if (t < 2*bin_size) { return 0.0f; }
  float recent = 0.0f;
  float previous = 0.0f;
  for (int i=0; i<bin_size; i++) {
    recent += hist->flow[(t-i) & (HISTORY_LENGTH - 1)];
  }
  for (int i=bin_size; i<2*bin_size; i++) {
    previous += hist->flow[(t-i) & (HISTORY_LENGTH - 1)];
  }
  return (recent - previous) / (float)(bin_size*bin_size);
}


bool is_cmd_ipap_constant(history_t *hist) {
  const int t = hist->tick;
  if (t < 4) { return false; }
  const int t1 = t & (HISTORY_LENGTH - 1);
  const int t2 = (t-4) & (HISTORY_LENGTH - 1);
  return absf(hist->cmd_ipap[t1] - hist->cmd_ipap[t2]) <= 0.041f;
}


///////////////////////////////
// All-purpose tracking code //

void init_breath(breath_t *breath) {
  breath->volume = 0.0f;
  breath->volume_max = 0.0f;
  breath->exh_maxflow = 0.0f;
  breath->inh_maxflow = 0.0f;
  breath->t = 0;
  breath->ti = 0.0f;
  breath->te = 0.0f;
}
void init_tracking(tracking_t *tr) {
  tr->breath_count = 0;
  tr->tick = 0;
  tr->st_inhaling = false;
  tr->st_just_started = false;
  tr->st_valid_breath = false;
  tr->st_full_breath = false;
  tr->st_pre_trigger = 0;
  tr->st_pre_cycle = 0;

  init_breath(&tr->recent);
  tr->recent.te = 2.0f; tr->recent.ti = 1.6f; tr->recent.volume_max = 0.3f; tr->recent.exh_maxflow = -25.0f; tr->recent.inh_maxflow = 25.0f; // Init with reasonable-ish defaults in case code wants to rely on these
  init_breath(&tr->last);
  init_breath(&tr->current);

  tr->final_ps = 0.0f;
}

tracking_t* get_tracking() {
  return GET_PTR(PTR_TRACKING, tracking_t, init_tracking);
}

// Called after the stock detectors, only for an accepted phase event.
void finish_tracking(tracking_t *tr, bool inhaling) {
  if (inhaling == tr->st_inhaling) { return; }
  if (inhaling) {
    tr->st_inhaling = true; tr->st_just_started = true; tr->st_pre_trigger = 0; tr->st_pre_cycle = 0;

    tr->last = tr->current;
    tr->breath_count += 1;
    init_breath(&tr->current);
    tr->final_ps = *cmd_ps;

    // Exclude the initial partial record, not short complete breaths.
    tr->st_valid_breath = tr->st_full_breath;
    tr->st_full_breath = true;
    if (tr->st_valid_breath) {
      inplace(lerp, &tr->recent.volume_max, tr->last.volume_max, tr_coeff);
      inplace(lerp, &tr->recent.exh_maxflow, tr->last.exh_maxflow, tr_coeff);
      inplace(lerp, &tr->recent.inh_maxflow, tr->last.inh_maxflow, tr_coeff);
      inplace(lerp, &tr->recent.ti, tr->last.ti, tr_coeff);
      inplace(lerp, &tr->recent.te, tr->last.te, tr_coeff);
    }
  } else {
    tr->st_inhaling = false; tr->st_just_started = true; tr->st_pre_trigger = 0; tr->st_pre_cycle = 0;
    tr->final_ps = *cmd_ps;
  }
}

// Sample N closes the previous 10 ms interval. The stock phase decision follows
// this integration; a new phase starts at zero without counting this sample twice.
void prepare_tracking(tracking_t *tr, history_t *hist) {
  tr->st_just_started = false;
  tr->tick += 1; tr->current.t += 1;
  if (tr->st_inhaling) { 
    tr->current.ti += 0.01f;
    inplace(max, &tr->current.inh_maxflow, *flow_compensated);

    if (*flow_compensated < tr->current.inh_maxflow * sens_cycle) {
      if (tr->st_pre_cycle < 255) { tr->st_pre_cycle += 1; }
    }
    else { tr->st_pre_cycle = max(tr->st_pre_cycle - 1, 0); } // Don't just reset it

  } else { 
    tr->current.te += 0.01f;
    inplace(min, &tr->current.exh_maxflow, *flow_compensated);

    // If flow extrapolated 80ms(~blower delay) into the future crosses threshold, increment pretrigger
    const float flow2 = max(*flow_compensated, *flow_compensated + get_delta_flow(hist, 4)*8.0f); // Flow extrapolated 80ms into the future
    if (flow2 > sens_trigger) {
      if (tr->st_pre_trigger < 255) { tr->st_pre_trigger += 1; }
    }
    else { tr->st_pre_trigger = 0; } // This has to reset, flow doesn't slow down during the start of a breath
  }

  tr->current.volume += (*flow_compensated / 60.0f) * 0.01f;
  inplace(max, &tr->current.volume, 0.0f);
  inplace(max, &tr->current.volume_max, tr->current.volume);
}

#include "my_asv.c"
#include "feat_triggercycle.c"

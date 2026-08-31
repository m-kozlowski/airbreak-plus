#ifndef _feat_triggercycle_h_
#define _feat_triggercycle_h_

#define PRE_CYCLE_MAX_TICKS 60 // 600ms

// Necessary to monitor actual setting changes despite the memory address being overwritten
typedef struct {
  float last_trigger;
  float real_trigger;
  float last_cycle;
  float real_cycle;

  float volbased; // Custom volume accumulator that resets to 0 when flow<0

  bool custom_trigger : 1; // Currently unimplemented
  bool custom_cycle : 1; // Based on static-leak-compenstaed flow, as I suspect vsync is mangling cycling with non-easybreathe waveforms
} triggercycle_t;

void init_triggercycle(triggercycle_t *trc);
triggercycle_t* get_triggercycle();
void update_triggercycle(triggercycle_t *trc, tracking_t *tr);

#endif

// 7. Apply EPS to S mode

// PAP - lower trigger threshold with cumulative volume - most non-inhales only reach 10-15mL, most ineffective efforts reach 25-30mL, and with p_error(only if recent commanded volume was constant)
// 20-40mL for -0%-25% threshold 5-15 for +0%-25%
// Previously did 0.05-0.3cmH2O p_error to 3cmH2O, or -62.5% threshold, though baseline was 1.5cmH2O higher, so more like -30% ?



// Function pointer wizardry - probably/definitely won't use, overkill and bug-prone
/*
void *array[9];
bool (*trigger_fn[9])();
bool (*cycle_fn[9])();
trigger_fn[4] = ...;
bool result = (*trigger_fn[4])();
*/

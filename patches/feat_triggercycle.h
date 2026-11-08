#ifndef _feat_triggercycle_h_
#define _feat_triggercycle_h_

#define PRE_CYCLE_MAX_TICKS 60 // 600ms

// A comparison hook can keep the stock result, hold the phase or request a switch.
enum { TC_STOCK = -1, TC_HOLD = 0, TC_SWITCH = 1 };

typedef struct {
  float volbased; // Positive-flow volume accumulated during expiration
  int trigger;
  int cycle;
} triggercycle_t;

void init_triggercycle(triggercycle_t *trc);
triggercycle_t *get_triggercycle(void);
void prepare_triggercycle(triggercycle_t *trc, tracking_t *tr, history_t *hist, bool enabled);

#endif

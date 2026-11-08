#ifndef _breath_tracking_h_
#define _breath_tracking_h_

#include "common_code.h"

///////////////////////////
// History functionality //

#define HISTORY_LENGTH 16

typedef struct {
  int tick;
  float16 flow[HISTORY_LENGTH];
  float16 cmd_ipap[HISTORY_LENGTH];
  // float16 pressure[HISTORY_LENGTH];
} history_t;

void init_history(history_t *hist);
void update_history(history_t *hist);

float get_delta_flow(history_t *hist, int bin_size); // Get the rate of change of the flow curve
bool is_cmd_ipap_constant(history_t *hist); // Test if cmd_ipap is currently unchanging

///////////////////////////////
// All-purpose tracking code //

// Setup storage for important data
typedef struct {
  float volume;
  float volume_max;

  // New stuff
  float exh_maxflow;
  float inh_maxflow;
  int16 t; // Completed 10ms intervals since inspiration
  float ti; // (s)
  float te; // (s)
} breath_t;

void init_breath(breath_t *breath);

#define tr_coeff 0.025f

typedef struct {
  uint32 breath_count;
  uint32 tick;

  bool st_inhaling : 1;
  bool st_just_started : 1; // Whether the inhale/exhale portion started this tick
  bool st_valid_breath : 1; // Last record contains a complete breath with valid samples
  bool st_full_breath : 1; // Observed its start and every subsequent flow sample
  bool st_valid_sample : 1; // This tick's compensated flow is finite
  uint8 st_pre_trigger ;  // "early trigger", e.g. flow will cross trigger threshold in amount of time similar to blower response, eliminating delay
  uint8 st_pre_cycle ;    // Low-flow counter used by Custom T/C and the squarewave PS ramp-down

  breath_t recent; // Tracks recent breath parameters to compare against.
  breath_t last;
  breath_t current;

  float final_ps; // PS at the end of the last inhale or exhale phase
} tracking_t;

void init_tracking(tracking_t *tr);
void prepare_tracking(tracking_t *tr, history_t *hist);
void finish_tracking(tracking_t *tr, bool inhaling);

typedef struct breath_node breath_node;
typedef void (*breath_method)(breath_node *);
struct breath_node {
  const breath_method *methods;
  breath_node *next;
  uint32 enabled;
};

typedef struct {
  breath_node prepare, finish;
  unsigned char *progress, *timing, *timed;
  history_t hist;
  tracking_t tr;
  bool reset;
} breath_tracking_t;

extern void *therapy_manager_get(void);
extern void therapy_worker_append(breath_node *, int group);

breath_tracking_t *breath_tracking_find(void);
void *breath_tracking_register_prepare(void);
void *breath_tracking_register_finish(void);

#endif

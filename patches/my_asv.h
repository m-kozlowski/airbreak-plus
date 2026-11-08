#ifndef _my_asv_h_
#define _my_asv_h_

#include "breath_tracking.h"

///////////////////
// Config values //

#define ASV_STEP_LENGTH 5 // (10ms ticks)
#define ASV_STEP_COUNT 20 // (steps)
#define ASV_STEP_SKIP 3 // (steps) Steps after the trigger before the first checkpoint
#define ASV_WARMUP_BREATHS 20 // Raw samples per checkpoint before PID comparisons

_Static_assert(ASV_STEP_SKIP >= 1, "First checkpoint must follow the trigger");
_Static_assert(ASV_STEP_COUNT >= 1 && ASV_STEP_COUNT <= 32,
               "Checkpoint count must fit the 32-bit mask");

// Low and high targets. The ASV PID will target at least `asv_low` volume and at most `asv_high`
#define asv_low 0.94f
#define asv_high 0.96f

// Slow: 0.2f, 0.025f, 0.05f - very slow, fails to do its job a lot of the time. TBH autotriggered breaths can still be jarring
#define asv_pid_p 0.5f
#define asv_pid_i 0.1f
#define asv_pid_d 0.2f
#define asv_pid_min 0.0f
#define asv_pid_max 1.5f

#define asv_coeff1 0.025f // ~40% contribution from last 20 breaths, ~66% from 40, ~77% from 60
#define asv_coeff2 0.3f

#define asv_dampen_max 0.4f

// Amount of breaths needing ASV to enable and disable asv_factor
#define ASV_BREATH_SKIP 2
#define ASV_BREATH_SKIP_OFF 6
#define ASV_BREATH_SKIP_MAX_FACTOR 0.2f

/////////////////////////
// PID controller code //

typedef struct {
  float last_error;
  float cumulative_error;
  float current_error;
  float kp;
  float ki;
  float kd;
  float output_min;
  float output_max;
} pid_t;

void pid_init(pid_t *pid, float p, float i, float d, float _min, float _max);
float pid_get_signal(pid_t *pid);
void pid_update(pid_t *pid, float current_error);

////////////////////////
// ASV algorithm code //

typedef enum {
  ASV_UNKNOWN,
  ASV_NO_NEED,
  ASV_NEED,
} asv_need_t;

typedef struct {
  uint32 breath_count;

  uint32 tracking_tick; // Last tracker sample processed by ASV
  pid_t pid;
  float asv_factor;
  float final_ips; // Final max IPS value, used to maintain correct downslope
  float asv_sens; // Multiplier applied to the ASV PID output

  float asv_dampen; // How much to drop the target by, other than after a hyperpnea, it's usually 0
  int8 asv_skip; // If < 0, limit maximum ASV factor for `ASV_BREATH_SKIP` breaths needing <0.1f ASV

  float target_vol; // Single-stage peak-volume reference for dampening
  float target_vol2; // Faster peak-volume reference for the learning coefficient

  uint32 checkpoints; // Collected this inspiration; zero volume is a valid sample
  asv_need_t breath_need; // Completed inspiration, consumed at the next trigger
  bool full_inspiration; // Observed its start and every subsequent tracker sample
  bool pid_updated; // Compared at least one checkpoint with a warmed-up reference
  bool boost_enabled;
  uint8 target_samples[ASV_STEP_COUNT]; // Saturates at ASV_WARMUP_BREATHS

  float16 targets_recent[ASV_STEP_COUNT];
  float16 targets_recent2[ASV_STEP_COUNT]; // sadly need a 2nd copy for the two-stage lerp
  float16 targets_current[ASV_STEP_COUNT];
} asv_data_t;

void init_asv_data(asv_data_t *data);
void update_asv_data(asv_data_t* asv, tracking_t* tr, bool boost_enabled);

#endif

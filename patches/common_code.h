#ifndef _common_code_h_
#define _common_code_h_

// Mandatory definitions
#define INLINE inline __attribute__((always_inline))
#define MAIN __attribute__((section(".text.0.main")))
#define STATIC static __attribute__((section(".text.x.nonmain")))


// Types
typedef unsigned int uint32;
typedef signed short int16;
typedef signed char int8;
typedef unsigned char uint8;
typedef __fp16 float16;
#if __STDC_VERSION__ < 202311L
typedef _Bool bool;
#define false 0
#define true  1
#endif


// PAP memory addresses (resolved from per-version stubs.S)
extern float fvars[];
extern int ivars[];

static float *cmd_ps = &fvars[0x29]; // Additive pressure waveform; signed around the midpoint in VAuto (cmH2O)
static float *cmd_epap = &fvars[0x28]; // Pressure reference before ramp; EPAP + PS/2 in VAuto (cmH2O)
static float *cmd_ipap = &fvars[0x2a]; // Final pressure command throughout the breath, not a stored IPAP setting (cmH2O)

static float *cmd_epap_ramp = &fvars[0x2d]; // Ramped pressure reference (cmH2O)

static const float *flow_raw = &fvars[0x3]; // (L/min)
static const float *flow_patient = &fvars[0x0]; // (L/min)
static const float *flow_compensated = &fvars[0x25]; // (L/min)

static const float *actual_pressure = &fvars[1]; // (cmH2O) Actual current pressure in the circuit

static const   int *therapy_mode = &ivars[0x6f]; // It's 0 when device is inactive
// Values of therapy_mode:
enum {
  MODE_OFF   = 0, // Inactive
  MODE_CPAP  = 1, // CPAP
  MODE_APAP  = 2, // APAP / AutoSet / AutoSet For Her
  MODE_VAUTO = 3, // VAuto
  MODE_S     = 4, // S / ST / PAC (with EasyBreathe=Off)
  MODE_IVAPS = 6, // iVAPS
  MODE_S_EB  = 8, // S / ST / PAC (with EasyBreathe=On)
  MODE_ASV   = 9, // ASV / ASVAuto
};

static const   int *pap_timer = &ivars[0];

#define breath_progress (fvars[0x20]) // Inhale(0.0 to 0.5), Exhale(0.5 to 1.0). Breath duration-dependent. Works in S, VAuto modes, but not ASV

#define p_actual  (fvars[1])
#define p_command (fvars[0x2a])

#define p_error (p_actual - p_command) // Positive when above target

// Configured flow-trigger and cycle thresholds.
#define sens_trigger fvars[0x7] // (L/min). Possible values: 13.2, 8.1, 4.8, 3.3, 1.8
#define sens_cycle fvars[0x8] // Fraction of peak inspiratory flow; values depend on mode

// S mode configuration
#define s_ipap fvars[0xe]
#define s_epap fvars[0xf]
#define s_ips (s_ipap - s_epap)
#define s_rise_time_i ivars[0xD] // (8ms ticks)
#define s_rise_time_f (s_rise_time_i * 0.008f) // (s)
// VAuto bounds use the midpoint between EPAP and IPAP (cmH2O).
#define vauto_reference_max fvars[0x9] // Max IPAP - PS/2
#define vauto_reference_min fvars[0xa] // Min EPAP + PS/2
#define vauto_ps fvars[0xb]

// AutoSet/APAP pressure bounds share the VAuto slots (cmH2O).
#define apap_pressure_max fvars[0x9]
#define apap_pressure_min fvars[0xa]
#define apap_epr fvars[0xb]

#define ti_min (ivars[0x5]*10) // (ms) integer
#define ti_max (ivars[0x6]*10) // (ms) integer

// Utility functions
#define min(a,b) ({ \
  __typeof__ (a) _a = (a); \
  __typeof__ (b) _b = (b); \
  _a < _b ? _a : _b; \
})

#define max(a,b) ({ \
  __typeof__ (a) _a = (a); \
  __typeof__ (b) _b = (b); \
  _a > _b ? _a : _b; \
})

#define clamp(a, _min, _max) ({ \
  __typeof__ (a) _a = (a); \
  __typeof__ (_min) __min = (_min); \
  __typeof__ (_max) __max = (_max); \
  _a > __max ? __max : (_a < __min ? __min : _a); \
})

#define clamp01(a) ({ clamp(a, 0.0f, 1.0f) })

#define absf(a) __builtin_fabsf(a)

// Usage example: `inplace(max, &a, b)`
#define inplace(fn, ptr, args...) ({ \
  __typeof__ (ptr) _ptr = (ptr); \
  *_ptr = fn(*_ptr, args); \
})

static inline float remap01(float s, float start, float end) {
  return (s - start)/(end-start);
}

static inline float remap01c(float s, float start, float end) {
  return clamp(remap01(s, start, end), 0.0f, 1.0f);
}

// Keep argument rounding separate from the fused multiply-add inside remap.
static __attribute__((noinline, unused)) float remap(float s, float start, float end, float new_start, float new_end) {
  return new_start + remap01(s, start, end) * (new_end - new_start);
}

static inline float remapc(float s, float start, float end, float new_start, float new_end) {
  return new_start + remap01c(s, start, end) * (new_end - new_start);
}

static inline float lerp(float from, float to, float coeff) {
  return from + (to - from) * coeff;
}


#endif

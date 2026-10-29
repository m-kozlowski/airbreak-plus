/* Adjustable fall duration for the stock S/ST/T/PAC and iVAPS waveforms. */
#include "s10_vars.h"

typedef unsigned short u16;

extern const u16 fall_time_duration_var_id;
extern int variable_get_by_id(int var_id);
extern void therapy_variable_get(int **ref, int index);
extern void bilevel_pressure_waveform_expiration_ramp(void *ctx);
extern float ivaps_pressure_waveform_expiration_ramp(void *ctx, float support);
extern const volatile int therapy_waveform_profile;

/* Also used by AutoEPAP's flow fit, which trims by the actual fall duration. */
int fall_time_effective_ticks(int ivaps, int original_ticks)
{
    int ticks = 0;
    if (fall_time_duration_var_id != 0xffffu) {
        /* These are MOP values, not the internal waveform profile numbers. */
        int mop = variable_get_by_id(VAR_ID_MOP);
        /* The iVAPS generator also serves another internal profile; only
         * profile 6 receives the custom duration. S uses the linear ramp in
         * profile 4; its Easy-Breathe profile has no timed fall ramp.
         */
        if (ivaps ? (mop == 9 && therapy_waveform_profile == 6)
                  : ((mop == 3 && therapy_waveform_profile == 4) ||
                     mop == 4 || mop == 5 || mop == 10)) {
            /* Full transition time in ms; the stock waveform runs at 100 Hz. */
            ticks = variable_get_by_id(fall_time_duration_var_id) / 10;
        }
    }

    return ticks > 0 ? ticks : original_ticks;
}

static int *fall_time_override(int ivaps, int *original)
{
    int ticks = fall_time_effective_ticks(ivaps, 0);
    if (!ticks) {
        return 0;
    }

    /* Integer therapy state 0x0e is the stock fall duration in 10 ms ticks.
     * Scope the override to this call, including stock phase transitions.
     */
    int *fall_ticks;
    therapy_variable_get(&fall_ticks, 0x0e);
    *original = *fall_ticks;
    *fall_ticks = ticks;
    return fall_ticks;
}

void start(void *ctx)
{
    int original;
    int *fall_ticks = fall_time_override(0, &original);
    bilevel_pressure_waveform_expiration_ramp(ctx);
    if (fall_ticks) {
        *fall_ticks = original;
    }
}

/* iVAPS returns a shaped pressure-support value instead of updating the
 * S/ST/T/PAC output variables. Keep that curve and its phase transitions intact.
 */
float fall_time_ivaps(void *ctx, float support)
{
    int original;
    int *fall_ticks = fall_time_override(1, &original);
    float result = ivaps_pressure_waveform_expiration_ramp(ctx, support);
    if (fall_ticks) {
        *fall_ticks = original;
    }
    return result;
}

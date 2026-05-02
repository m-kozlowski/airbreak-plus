#include "stubs.h"
#include "common_code.h"

const float EPS_FIXED_TIME = 1.2f;

typedef struct
{
    bool st_inhaling;
    uint8 st_pre_cycle;
    float ti;
    float te;
    float volume;
    float volume_max;
    float final_ps;
    float progress;
    float epap;
    float ips;
    float s_rise_time;
} tophwave_input_t;

typedef struct
{
    float cmd_ps;
    float cmd_epap;
    float cmd_ipap;
} tophwave_output_t;

STATIC float simple_wave(uint32 tick, uint32 rampTime, uint32 waitTime, float minPressure, float maxPressure)
{
    const uint32 cycleTime = waitTime * 2 + rampTime * 2;
    const uint32 t = tick % cycleTime;

    if (t < waitTime)
    {
        return minPressure;
    }
    if (t < waitTime + rampTime)
    {
        return remap(t - waitTime, 0, rampTime, minPressure, maxPressure);
    }
    if (t < waitTime * 2 + rampTime)
    {
        return maxPressure;
    }

    return remap(t - waitTime * 2 - rampTime, 0, rampTime, maxPressure, minPressure);
}

STATIC uint32 seconds_to_pap_ticks(float seconds)
{
    return max(1u, (uint32)(seconds * 100.0f));
}

STATIC tophwave_output_t tophwave_compute(tophwave_input_t in)
{
    const float s_eps = 0.8f;
    const float s_fall_time = 0.8f;

    tophwave_output_t out;
    out.cmd_epap = in.epap;

    if (in.st_inhaling)
    {
        const float smooth_time = 0.075f;
        const float t2 = min(in.ti, in.s_rise_time - smooth_time) + clamp((in.ti - (in.s_rise_time - smooth_time)) * 0.5f, 0.0f, smooth_time);

        float perc = 0.1f + 0.7f * remap01c(t2, 0.0f, in.s_rise_time) + (0.4f * in.progress);

        perc = max(0.0f, perc - (in.st_pre_cycle * 0.01f) / 1.5f);

        out.cmd_ps = in.ips * perc;
    }
    else
    {
        float eps_mult = remap01c(in.volume / in.volume_max, 0.1f, 0.7f);
        eps_mult = min(eps_mult, remap01c(in.te, EPS_FIXED_TIME, 0.4f));

        float ips_mult = remap01c(in.te, s_fall_time, 0.0f);
        ips_mult = ips_mult * ips_mult * 0.95f;

        out.cmd_ps = ips_mult * in.final_ps - (1.0f - ips_mult) * eps_mult * s_eps;
    }

    out.cmd_ps = clamp(out.cmd_ps, -s_eps, in.ips);
    out.cmd_epap = clamp(out.cmd_epap, in.epap, in.epap);
    out.cmd_ipap = out.cmd_epap + out.cmd_ps;

    return out;
}

void MAIN start(int param_1)
{
    /*
    tracking_t *tr = get_tracking();

    tophwave_input_t in;
    in.st_inhaling = tr->st_inhaling;
    in.st_pre_cycle = tr->st_pre_cycle;
    in.ti = tr->current.ti;
    in.te = tr->current.te;
    in.volume = tr->current.volume;
    in.volume_max = tr->current.volume_max;
    in.final_ps = tr->final_ps;
    in.progress = breath_progress;
    in.epap = s_epap;
    in.ips = s_ips;
    in.s_rise_time = s_rise_time_f;

    tophwave_output_t out = tophwave_compute(in);

    *cmd_ps = out.cmd_ps;
    *cmd_epap = out.cmd_epap;
    *cmd_ipap = out.cmd_ipap;
    */

    const uint32 rampTime = seconds_to_pap_ticks(s_rise_time_f);
    const uint32 waitTime = seconds_to_pap_ticks(1);
    const float pressure = simple_wave(*pap_timer, rampTime, waitTime, 3.2, 5.4);

    *cmd_ps = 0.0f;
    *cmd_epap = pressure;
    *cmd_ipap = pressure;

    return;
}
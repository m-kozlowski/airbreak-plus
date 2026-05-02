#define UNIT_TEST
#include "../patches/common_code.c"
#include "../patches/tophwave.c"

int printf(const char *format, ...);

static int failures = 0;

static void expect_near(const char *name, float actual, float expected)
{
    const float delta = actual > expected ? actual - expected : expected - actual;
    if (delta > 0.0001f)
    {
        printf("FAIL %s: expected %.6f, got %.6f\n", name, expected, actual);
        failures += 1;
    }
}

static tophwave_input_t base_input(void)
{
    tophwave_input_t in;
    in.st_inhaling = true;
    in.st_pre_cycle = 0;
    in.ti = 0.0f;
    in.te = 0.0f;
    in.volume = 0.0f;
    in.volume_max = 1.0f;
    in.final_ps = 0.0f;
    in.progress = 0.0f;
    in.epap = 6.0f;
    in.ips = 10.0f;
    in.s_rise_time = 0.5f;
    in.trigger = 4.8f;
    in.cycle = 0.25f;
    in.pap_tick = 0;
    return in;
}

static void test_inhale_mid_ramp_sets_pressure_support(void)
{
    tophwave_input_t in = base_input();
    in.ti = 0.25f;
    in.progress = 0.25f;

    tophwave_output_t out = tophwave_compute(in);

    expect_near("inhale mid ramp ps", out.cmd_ps, 5.5f);
    expect_near("inhale mid ramp epap", out.cmd_epap, 6.0f);
    expect_near("inhale mid ramp ipap", out.cmd_ipap, 11.5f);
}

static void test_pre_cycle_reduces_inhale_pressure_support(void)
{
    tophwave_input_t in = base_input();
    in.ti = 0.5f;
    in.progress = 0.5f;
    in.st_pre_cycle = 30;

    tophwave_output_t out = tophwave_compute(in);

    expect_near("pre cycle reduced ps", out.cmd_ps, 7.475f);
    expect_near("pre cycle ipap", out.cmd_ipap, 13.475f);
}

static void test_exhale_blends_final_pressure_toward_eps(void)
{
    tophwave_input_t in = base_input();
    in.st_inhaling = false;
    in.te = 0.4f;
    in.volume = 0.4f;
    in.volume_max = 1.0f;
    in.final_ps = 8.0f;

    tophwave_output_t out = tophwave_compute(in);

    expect_near("exhale blended ps", out.cmd_ps, 1.595f);
    expect_near("exhale blended ipap", out.cmd_ipap, 7.595f);
}

static void test_exhale_pressure_support_clamps_to_negative_eps(void)
{
    tophwave_input_t in = base_input();
    in.st_inhaling = false;
    in.te = 0.4f;
    in.volume = 1.0f;
    in.volume_max = 1.0f;
    in.final_ps = -10.0f;

    tophwave_output_t out = tophwave_compute(in);

    expect_near("exhale negative eps clamp", out.cmd_ps, -0.8f);
    expect_near("exhale negative eps ipap", out.cmd_ipap, 5.2f);
}

static void test_inhale_pressure_support_clamps_to_ips(void)
{
    tophwave_input_t in = base_input();
    in.ti = 1.0f;
    in.progress = 0.5f;

    tophwave_output_t out = tophwave_compute(in);

    expect_near("inhale ips clamp", out.cmd_ps, 10.0f);
    expect_near("inhale ips clamp ipap", out.cmd_ipap, 16.0f);
}

static void test_simple_wave_waits_at_min_pressure(void)
{
    tophwave_input_t in = base_input();
    in.s_rise_time = 0.1f;

    in.pap_tick = 0;
    expect_near("simple wave starts at min", simple_wave(in), 3.2f);
    in.pap_tick = 99;
    expect_near("simple wave waits at min", simple_wave(in), 3.2f);
}

static void test_simple_wave_ramps_up_after_wait(void)
{
    tophwave_input_t in = base_input();
    in.s_rise_time = 0.1f;

    in.pap_tick = 100;
    expect_near("simple wave ramp up start", simple_wave(in), 3.2f);
    in.pap_tick = 105;
    expect_near("simple wave ramp up midpoint", simple_wave(in), 4.3f);
    in.pap_tick = 110;
    expect_near("simple wave ramp up end", simple_wave(in), 5.4f);
}

static void test_simple_wave_waits_at_max_pressure(void)
{
    tophwave_input_t in = base_input();
    in.s_rise_time = 0.1f;

    in.pap_tick = 110;
    expect_near("simple wave waits at max start", simple_wave(in), 5.4f);
    in.pap_tick = 209;
    expect_near("simple wave waits at max end", simple_wave(in), 5.4f);
}

static void test_simple_wave_ramps_down_and_wraps(void)
{
    tophwave_input_t in = base_input();
    in.s_rise_time = 0.1f;

    in.pap_tick = 210;
    expect_near("simple wave ramp down start", simple_wave(in), 5.4f);
    in.pap_tick = 215;
    expect_near("simple wave ramp down midpoint", simple_wave(in), 4.3f);
    in.pap_tick = 220;
    expect_near("simple wave wraps to min", simple_wave(in), 3.2f);
}

static void test_seconds_to_pap_ticks_converts_10ms_timer(void)
{
    if (seconds_to_pap_ticks(0.5f) != 50)
    {
        printf("FAIL seconds to pap ticks: expected 50, got %u\n", seconds_to_pap_ticks(0.5f));
        failures += 1;
    }
    if (seconds_to_pap_ticks(0.0f) != 1)
    {
        printf("FAIL seconds to pap ticks clamp: expected 1, got %u\n", seconds_to_pap_ticks(0.0f));
        failures += 1;
    }
}

int main(void)
{
    test_inhale_mid_ramp_sets_pressure_support();
    test_pre_cycle_reduces_inhale_pressure_support();
    test_exhale_blends_final_pressure_toward_eps();
    test_exhale_pressure_support_clamps_to_negative_eps();
    test_inhale_pressure_support_clamps_to_ips();
    test_simple_wave_waits_at_min_pressure();
    test_simple_wave_ramps_up_after_wait();
    test_simple_wave_waits_at_max_pressure();
    test_simple_wave_ramps_down_and_wraps();
    test_seconds_to_pap_ticks_converts_10ms_timer();

    if (failures != 0)
    {
        return 1;
    }

    printf("PASS tophwave unit tests\n");
    return 0;
}
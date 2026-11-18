/* Limit heated-tube warm-up to the humidity the water chamber can supply.
 *
 * The stock climate controller drives the tube toward HTS as soon as therapy
 * starts, long before the plate has heated the water, so early air is warm and
 * dry. While the plate warms, cap the tube setpoint where the estimated moisture
 * the chamber adds (humidity_model.h) gives the target RH, and let the stock
 * model aim for HTS so the plate keeps heating at full demand. The cap is never
 * below the lowest tube setting (16 degC) or the Min Tube setting.
 *
 * The tube heater works in proportion to the gap between its setpoint and the
 * measured tube, so a tube just below the cap barely heats and lags behind it.
 * While the tube is below the cap the setpoint therefore leads the cap by
 * four times the remaining gap, never above HTS, and falls back to the cap as the
 * tube reaches it.
 *
 * The cap ends once it reaches HTS, the plate stops rising, or the warm-up
 * time limit expires. The stock model keeps aiming for HTS until the measured
 * tube is within a degree of it, so the plate does not cool when the tube is
 * released.
 */
#include "s10_vars.h"
#include "humidity_model.h"

typedef unsigned char u8;
typedef float (*getf_t)(void *);
typedef int (*geti_t)(void *);

struct obj {
    void *const *vptr;
};

enum {
    INPUT_SLOTS = 18,
    INPUT_TUBE_PRESENT = 0x1c / 4,
    INPUT_HUMIDIFIER_ACTIVE = 0x20 / 4,
    INPUT_CLIMATE_MODE = 0x34 / 4,
    INPUT_TARGET_RH = 0x44 / 4,
    SENSOR_PLATE = 0x0c / 4,
    SENSOR_AMBIENT_T = 0x10 / 4,
    SENSOR_AMBIENT_RH = 0x14 / 4,
    /* The climate controller stores its sensors at +0x14 and inputs at +0x28. */
    SENSORS_TO_INPUTS = 0x14,
    CLIMATE_MODE_AUTO = 1,
    SAMPLE_MS = 60000,
    IDLE_MS = 60000,
    MAX_MINUTES = 60,
    /* Minutes between plate checks; a power of two. */
    WINDOW_MINUTES = 8,
    HANDOFF_MS = 300000,
    STATE_MAGIC = 0x50555754,
};

/* The lowest tube temperature setting, degC. */
#define MIN_TUBE_TEMP 16.0f
/* Plate rise per minute below which the plate counts as stopped, degC. The
 * plate approaches its limit slowly, at a few tenths of a degree per minute
 * for a long time, and is still heating then.
 */
#define PLATE_STALL_RATE 0.05f
/* Setpoint lead over the cap, as a multiple of the tube's gap below it. The
 * setpoint is never above HTS, so the tube never heats faster than stock.
 */
#define TRACK_GAIN 4.0f
/* How close the measured tube must get to HTS before the stock reference
 * temperature takes over again, degC.
 */
#define HANDOFF_MARGIN 1.0f

/* Cloning the inputs vtable lets both hooks find this state from their own
 * object without reserving a writable global.
 */
struct state {
    void *methods[INPUT_SLOTS];
    unsigned magic;
    unsigned seen[3];
    unsigned sample[3];
    /* Words, not bytes: Thumb has short loads for them at these offsets. */
    unsigned minutes;
    unsigned done;
    unsigned capping;
    /* The tube setting and target RH last seen; a change restarts the check. */
    float setpoints;
    float last_plate;
    struct humidity_coeffs coeffs;
};

extern void *malloc(unsigned size);
extern void millisecond_timer_init(void *timer, unsigned elapsed);
extern int millisecond_timer_expired(void *timer, unsigned ms);
extern float climate_tube_setpoint_get(struct obj *inputs);
extern float climate_reference_temperature_get(struct obj *sensors);
extern void *const climate_inputs_vtable[];
extern const unsigned short humid_start_enable_var_id;
extern const unsigned short humid_start_coupling_var_id;
extern const unsigned short humid_start_min_tube_c;
extern int variable_get_by_id(int var_id);

static float call_f(struct obj *o, int slot) { return ((getf_t)o->vptr[slot])(o); }
static int call_i(struct obj *o, int slot) { return ((geti_t)o->vptr[slot])(o); }

/* Custom settings, when installed, supply the switch. */
static int enabled(void)
{
    return humid_start_enable_var_id == 0xffffu ||
           variable_get_by_id(humid_start_enable_var_id);
}

/* Plate bound coupling: the custom setting, else the built-in constant. */
static float coupling(void)
{
    if (humid_start_coupling_var_id == 0xffffu)
        return HUMIDITY_PLATE_COUPLING;
    return coupling_from_raw(variable_get_by_id(humid_start_coupling_var_id));
}

/* Lowest the cap goes: the patch-time Min Tube (whole degC), never below
 * the lowest tube setting.
 */
static float cap_floor(void)
{
    int lowest = (int)MIN_TUBE_TEMP;
    int setting = humid_start_min_tube_c;
    if (setting > lowest)
        lowest = setting;
    return (float)lowest;
}

static void restart(struct state *s, float plate)
{
    s->done = 0;
    s->minutes = 0;
    s->last_plate = plate;
    humidity_coeffs_read(&s->coeffs);
    millisecond_timer_init(s->sample, 0);
}

/* Ends warm-up. The sample timer is free from here on and times the hand-off. */
static void finish(struct state *s)
{
    s->done = 1;
    millisecond_timer_init(s->sample, 0);
}

static struct state *state_of(struct obj *inputs, int create)
{
    struct state *s = (struct state *)inputs->vptr;
    if (inputs->vptr != climate_inputs_vtable)
        return s->magic == STATE_MAGIC ? s : 0;
    if (!create || !(s = malloc(sizeof(*s))))
        return 0;
    for (unsigned i = 0; i < INPUT_SLOTS; ++i)
        s->methods[i] = climate_inputs_vtable[i];
    s->magic = STATE_MAGIC;
    inputs->vptr = (void *const *)s->methods;
    return s;
}

/* Matches the stock reference-temperature branch that returns the measured
 * tube temperature: a heated tube in Auto climate control.
 */
static int auto_with_tube(struct obj *inputs)
{
    return call_i(inputs, INPUT_TUBE_PRESENT) &&
           call_i(inputs, INPUT_CLIMATE_MODE) == CLIMATE_MODE_AUTO;
}

/* Replaces the climate inputs' tube-setpoint getter (HTS, degC). */
float start(struct obj *inputs)
{
    float set = climate_tube_setpoint_get(inputs);
    /* A new state starts a session; its timers are not set yet. */
    int fresh = inputs->vptr == climate_inputs_vtable;
    struct state *s = state_of(inputs, 1);
    if (!s)
        return set;
    struct obj *sensors = (struct obj *)((u8 *)inputs - SENSORS_TO_INPUTS);
    float plate = call_f(sensors, SENSOR_PLATE);
    /* The tube controller only asks during therapy; a long gap starts a session.
     * A changed tube setting or target RH checks again whether the tube needs
     * holding back, which ends at once if the water is already warm enough.
     */
    /* The tube setting steps by whole degrees and the target RH is above 0 and
     * at most 1, so their sum is different for every pair.
     */
    float target_rh = call_f(inputs, INPUT_TARGET_RH);
    if (fresh || set + target_rh != s->setpoints ||
            millisecond_timer_expired(s->seen, IDLE_MS))
        restart(s, plate);
    s->setpoints = set + target_rh;
    millisecond_timer_init(s->seen, 0);
    /* After warm-up the reference stays at HTS until the tube has caught up. */
    s->capping = s->done &&
                 variable_get_by_id(VAR_ID_HTT) < set * 10.0f - 10.0f * HANDOFF_MARGIN &&
                 !millisecond_timer_expired(s->sample, HANDOFF_MS);
    if (s->done || !enabled() || !call_i(inputs, INPUT_HUMIDIFIER_ACTIVE) ||
            !auto_with_tube(inputs))
        return set;

    float ambient = call_f(sensors, SENSOR_AMBIENT_T);
    if (millisecond_timer_expired(s->sample, SAMPLE_MS)) {
        millisecond_timer_init(s->sample, 0);
        /* A plate that barely rose over the last window has reached the model's
         * target. The plate wobbles, stalls for a minute or two and creeps up
         * slowly while still heating, so compare over several minutes.
         */
        int check = !(++s->minutes & (WINDOW_MINUTES - 1));
        if (s->minutes >= MAX_MINUTES ||
                (check && plate - s->last_plate < PLATE_STALL_RATE * WINDOW_MINUTES &&
                 plate > ambient + 8.0f)) {
            finish(s);
            return set;
        }
        if (check)
            s->last_plate = plate;
    }

    float outlet = humidity_outlet(&s->coeffs, plate, ambient,
                                   call_f(sensors, SENSOR_AMBIENT_RH),
                                   variable_get_by_id(VAR_ID_HPM) * 0.01f,
                                   variable_get_by_id(VAR_ID_AFL) * 0.01f,
                                   coupling());
    /* Without a usable estimate (a sensor reading NaN) the tube behaves as stock
     * instead of waiting at the floor.
     */
    if (!(outlet >= 0.0f)) {
        finish(s);
        return set;
    }
    /* The floor is the lowest tube setting or the Min Tube setting, not the
     * ambient reading: the sensor sits in the warm case, and a floor above the
     * tube would keep it heating. The tube heats to the floor at once and stays
     * there until the estimated moisture allows more.
     */
    /* A floor above the tube setting leaves nothing to search for: the result
     * is then not below the setting, which ends warm-up below.
     */
    float lowest = cap_floor();
    float limit = humidity_model_temperature(outlet, target_rh, lowest, set);
    if (limit + 0.01f >= set) {
        finish(s);
        return set;
    }
    s->capping = 1;
    /* Lead the cap while the tube is below it, so the heater works harder. */
    float gap = limit - climate_reference_temperature_get(sensors);
    if (gap > 0.0f)
        limit += TRACK_GAIN * gap;
    return limit < set ? limit : set;
}

/* Replaces the sensors' humidity-model reference temperature. */
float humid_start_reference(struct obj *sensors)
{
    struct obj *inputs = (struct obj *)((u8 *)sensors + SENSORS_TO_INPUTS);
    struct state *s = state_of(inputs, 0);
    if (s && s->capping && auto_with_tube(inputs))
        return climate_tube_setpoint_get(inputs);
    return climate_reference_temperature_get(sensors);
}

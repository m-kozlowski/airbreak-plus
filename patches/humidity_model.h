#ifndef HUMIDITY_MODEL_H
#define HUMIDITY_MODEL_H

/* Estimate of the moisture the humidifier chamber adds.
 *
 * The stock humidifier is open loop: it sets the heater duty from the moisture
 * the air needs, duty = k0 + k1 * flow * dAH (+ k2 * (plate - ambient)), with
 * flow in L/min and dAH in g/m3, capped at 0.85 and limited near a 63-68 degC
 * plate. k3 + k4 * duty is only a low-plate threshold for full power. The
 * duty says what the water would evaporate once warm; while the water heats
 * it evaporates less, which is the dry start.
 *
 * Two upper bounds are therefore combined:
 * - plate: the chamber adds at most the saturation humidity gained between
 *   ambient and ambient + coupling * (plate - ambient), so water no warmer
 *   than the room adds nothing;
 * - power: the measured heater duty, through the stock calibration, can add
 *   at most (duty - k0) / (k1 * flow) g/m3.
 * The smaller one holds during warm-up (plate) and at steady state (power).
 * Flow is the average blower flow (AFL), not the instantaneous flow, which
 * swings with every breath. Stock only runs its model at 8 L/min or more;
 * below that, or without usable calibration, only the plate bound applies.
 */

#define HUMIDITY_MIN_FLOW 8.0f

struct humidity_coeffs {
    float k0, k1;
};

extern int humidity_model_coefficients_get(void *unused, float *k0, float *k1,
                                           float *k2, float *k3, float *k4);

/* Plate bound without a Start Coupling setting: fraction of the plate's rise
 * above ambient over which the chamber adds saturation humidity. Lower values
 * hold the tube back longer and lower the estimated RH.
 */
#define HUMIDITY_PLATE_COUPLING 0.25f

/* The Start Coupling setting (raw = coupling * 100) held to its menu range,
 * so a stale stored value cannot starve or flood the estimate.
 */
static inline float coupling_from_raw(int raw)
{
    if (raw < 10)
        raw = 10;
    if (raw > 100)
        raw = 100;
    return raw * 0.01f;
}

/* Stock saturation absolute humidity, g/m3. */
static __attribute__((noinline)) float ah_sat(float t)
{
    return 4.61f + t * (0.436f + t * (0.00122f + t * 0.000427f));
}

/* Leaves k1 at zero when the calibration is missing or unusable. */
static inline void humidity_coeffs_read(struct humidity_coeffs *c)
{
    float k2, k3, k4;
    c->k0 = 0.0f;
    c->k1 = 0.0f;
    if (!humidity_model_coefficients_get(0, &c->k0, &c->k1, &k2, &k3, &k4) ||
            !(c->k1 > 0.0f && c->k0 * c->k0 < 1.0f))
        c->k1 = 0.0f;
}

/* Absolute humidity leaving the chamber, g/m3: the room air plus the
 * smaller of the plate and heater-power bounds on the added moisture.
 * duty is the measured humidifier heater duty, 0..1, and flow the average
 * blower flow in L/min.
 */
static inline float humidity_outlet(const struct humidity_coeffs *c, float plate,
                                    float ambient, float room_rh, float duty,
                                    float flow, float coupling)
{
    float room = room_rh * ah_sat(ambient);
    float added = ah_sat(ambient + coupling * (plate - ambient)) - ah_sat(ambient);
    if (c->k1 > 0.0f && flow >= HUMIDITY_MIN_FLOW) {
        float powered = (duty - c->k0) / (c->k1 * flow);
        if (powered < added)
            added = powered;
    }
    return room + (added > 0.0f ? added : 0.0f);
}

/* Temperature in [lo, hi] where rh * ah_sat(T) equals ah. When there is none the
 * result ends up within 0.001 degC of the nearer bound.
 */
static inline float humidity_model_temperature(float ah, float rh, float lo, float hi)
{
    for (int i = 0; i < 16; ++i) {
        float mid = 0.5f * (lo + hi);
        if (rh * ah_sat(mid) < ah)
            lo = mid;
        else
            hi = mid;
    }
    return 0.5f * (lo + hi);
}

#endif

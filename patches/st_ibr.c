/* Lumis-style adaptive backup timing for the stock ST breath worker. */
#include "s10_vars.h"

typedef unsigned short u16;

extern const u16 st_ibr_enable_var_id;
extern int variable_get_by_id(int var_id);
extern void therapy_variable_get(int **ref, int index);

/* The last two bytes are unused stock padding in the supported SX567 versions.
 * Keep the worker's size and all existing field offsets unchanged.
 */
struct breath_worker {
    unsigned char base[8];
    unsigned char active;
    unsigned char padding[3];
    float peak_flow;
    float inspiration_step;
    int inspiration_ticks;
    float expiration_step;
    int expiration_ticks;
    unsigned char inhaling;
    unsigned char trigger_armed;
    unsigned char cycle_armed;
    unsigned char phase_reset;
    unsigned char trigger_kind;
    unsigned char cycle_kind;
    u16 ibr_state;
};

extern void breath_progress_worker_reset(struct breath_worker *ctx);
extern void breath_progress_worker_update_mode(struct breath_worker *ctx);
extern void breath_progress_worker_disable(struct breath_worker *ctx);
extern void breath_progress_worker_update(struct breath_worker *ctx);

static int enabled(void)
{
    return st_ibr_enable_var_id != 0xffffu &&
        variable_get_by_id(VAR_ID_MOP) == 4 &&
        variable_get_by_id(st_ibr_enable_var_id) != 0;
}

/* Three low bits hold the mandatory-breath count (0..5); the remaining bits
 * hold the saved period. Stock ST caps the base period at 1200 ticks, so the
 * longest adaptive period is 1800. Zero marks a reset or disabled state.
 */
static void save_state(struct breath_worker *ctx, int count, int period)
{
    ctx->ibr_state = (u16)((period << 3) | count);
}

void st_ibr_reset(struct breath_worker *ctx)
{
    ctx->ibr_state = 0;
    breath_progress_worker_reset(ctx);
}

void st_ibr_update_mode(struct breath_worker *ctx)
{
    int was_active = ctx->active;
    breath_progress_worker_update_mode(ctx);
    if (!was_active || !ctx->active || !enabled()) {
        ctx->ibr_state = 0;
    }
}

void st_ibr_disable(struct breath_worker *ctx)
{
    ctx->ibr_state = 0;
    breath_progress_worker_disable(ctx);
}

void start(struct breath_worker *ctx)
{
    if (!enabled()) {
        ctx->ibr_state = 0;
        breath_progress_worker_update(ctx);
        return;
    }

    int *period_ref;
    therapy_variable_get(&period_ref, 2);
    int base_period = *period_ref;
    int count = ctx->ibr_state & 7;
    int period = ctx->ibr_state >> 3;
    int was_inhaling = ctx->inhaling;
    int timed = 0;

    if (!was_inhaling) {
        period = base_period;
        if (count < 5) {
            int longest = base_period * 3 / 2;
            period = longest - count * ((longest - base_period) / 4);
        }
        /* Stock increments expiration time before testing the deadline, and
         * checks the deadline before attempting a spontaneous trigger.
         */
        timed = ctx->expiration_ticks + 1 + ctx->inspiration_ticks >= period;
    } else if (count == 0 || count >= 5 || period == 0) {
        period = base_period;
    }

    /* Use the stock trigger/cycle logic with a call-local timing override.
     * At inspiration -> expiration, Lumis retains the last deadline for
     * mandatory breaths 1..4. That same period sets the expiration phase slope.
     * Restore the RRT-derived base period before returning to the worker pipeline.
     */
    *period_ref = period;
    breath_progress_worker_update(ctx);
    *period_ref = base_period;

    if (!was_inhaling && ctx->inhaling) {
        if (!timed) {
            count = 0;
        } else if (count < 5) {
            ++count;
        }
    }
    save_state(ctx, count, period);
}

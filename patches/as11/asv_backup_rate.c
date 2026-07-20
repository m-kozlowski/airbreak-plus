/*
 * Suppress ASV/ASVAuto backup breaths while the stock no-breathing detector
 * remains active.
 *
 * Native callback and feedback accessors are supplied by the selected
 * per-version stubs.
 */

#include "stubs.h"

/* Python writes the reclaimed setting var_id here; 0xFFFF means no control. */
volatile const unsigned short as11_asv_backup_rate_var_id
    __attribute__((used, section(".rodata.params"))) = 0xFFFFu;

static int backup_rate_enabled(void)
{
    /* Without menu integration, the standalone patch defaults backup rate Off. */
    if (as11_asv_backup_rate_var_id == 0xFFFFu)
        return 0;

    return DataItem_read_value_by_id(as11_asv_backup_rate_var_id) != 0;
}

void __attribute__((section(".text.0.main")))
start(void *ctx)
{
    int *no_breathing;
    float *phase;

    /* Stock feedback slots: no-breathing state and backup-breath phase. */
    FeedbackInput_get_ref(&no_breathing, 0x3c);
    FeedbackOutput_get_ref(&phase, 0x6f);

    /* Keep the stock phase below the backup-breath transition when disabled. */
    if (!backup_rate_enabled() && *no_breathing == 1 && *phase > 0.98f)
        *phase = 0.98f;

    /* The wrapper preserves the rest of the stock ASV update path. */
    AsvFeature_update(ctx);
}

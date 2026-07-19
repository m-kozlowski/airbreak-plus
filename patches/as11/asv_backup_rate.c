/*
 * Suppress ASV/ASVAuto backup breaths while the stock no-breathing detector
 * remains active.
 *
 * Native callback and feedback accessors are supplied by the selected
 * per-version stubs.
 */

#include "stubs.h"

void __attribute__((section(".text.0.main")))
start(void *ctx)
{
    int *no_breathing;
    float *phase;

    FeedbackInput_get_ref(&no_breathing, 0x3c);
    FeedbackOutput_get_ref(&phase, 0x6f);

    if (*no_breathing == 1 && *phase > 0.98f)
        *phase = 0.98f;

    AsvFeature_update(ctx);
}

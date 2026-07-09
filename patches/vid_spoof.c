/*
 * vid_spoof.c - MOP-based Variant ID override
 *
 * Hooks the g[8] persistent writeback (vtable+0xE4) to update VID
 * whenever MOP (therapy mode) is committed.
 *
 */

#include "s10_vars.h"

extern int vid_spoof_original_writeback(void *obj);
extern int variable_get_by_id(int var_id);
extern void variable_set_by_id(int var_id, int raw_value);

static const unsigned char vid_lut[12] = {
    0x1A,   // CPAP
    0x1A,   // AutoSet
    0x1A,   // APAP
    0x0B,   // S
    0x07,   // ST
    0x07,   // T
    0x09,   // VAuto
    0x13,   // ASV
    0x13,   // ASVAuto
    0x2E,   // iVAPS
    0x07,   // PAC
    0x19    // AutoSet For Her
};

int __attribute__((section(".text.0.main")))
start(void *obj)
{
    int ret = vid_spoof_original_writeback(obj);

    unsigned char idx = ((unsigned char *)obj)[0x14];
    if (idx == 0) {
        unsigned int mop = (unsigned int)variable_get_by_id(VAR_ID_MOP);
        if (mop <= 11) {
            unsigned int v = vid_lut[mop];
            variable_set_by_id(VAR_ID_VID, v);
        }
    }

    return ret;
}

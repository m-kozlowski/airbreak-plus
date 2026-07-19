/*
 * vid_spoof.c - MOP-based VariantIdentifier (VID) override
 *
 * Runs after the persistent MOP writeback and updates VID for the selected
 * therapy mode. Native DataItem access and variable IDs are supplied by the
 * selected per-version stubs and variable header.
 */

#include "stubs.h"
#include "vars.h"

/*
 * AS11 dump-backed mode groups:
 *   VID  3: CPAP, AutoSet, AutoSet For Her
 *   VID  7: Spont, VAuto
 *   VID 10: ST, Timed
 *   VID 12: ASV, ASVAuto
 *
 * iVAPS and PAC are not mapped for now.
 */
static const unsigned char vid_lut[11] = {
    3,   // CPAP
    3,   // AutoSet
    3,   // AutoSet For Her
    7,   // Spont
    10,  // ST
    10,  // Timed
    7,   // VAuto
    12,  // ASV
    12,  // ASVAuto
    0,   // iVAPS
    0,   // PAC
};

void __attribute__((section(".text.0.main")))
start(void)
{
    unsigned int mop = (unsigned int)DataItem_read_value_by_id(VAR_ID_MOP);
    if (mop < sizeof(vid_lut)) {
        unsigned int vid = vid_lut[mop];
        if (vid != 0)
            DataItem_write_raw_by_id(VAR_ID_VID, (int)vid);
    }
}

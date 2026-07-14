/*
 * vid_spoof.c - RID/MOP-based Variant ID override
 *
 * MOP selects the baseline VID. Firmware-confirmed RID/MOP pairs replace it
 * with the corresponding regional variant.
 *
 */

#include "s10_vars.h"

extern int variable_get_by_id(int var_id);
extern void variable_set_by_id(int var_id, int raw_value);

static const unsigned char vid_by_mop[12] = {
    26,   // CPAP
    26,   // AutoSet
    26,   // APAP
    11,   // S
     7,   // ST
     7,   // T
     9,   // VAuto
    19,   // ASV
    19,   // ASVAuto
    46,   // iVAPS
    46,   // PAC
    25,   // AutoSet For Her
};

enum {
    MOP_AUTOSET = 1,
    MOP_VAUTO = 6,
    MOP_ASV = 7,
    MOP_ASVAUTO = 8,
    MOP_IVAPS = 9,
    MOP_PAC = 10,
    MOP_AUTOSET_FOR_HER = 11,
};

struct vid_mapping {
    unsigned short rid;
    unsigned char mop;
    unsigned char vid;
};

static const struct vid_mapping regional_vid_map[] = {
    {13, MOP_AUTOSET,         39},
    {13, MOP_VAUTO,            9},
    {13, MOP_ASV,             19},
    {13, MOP_ASVAUTO,         19},
    {15, MOP_AUTOSET,         26},
    {15, MOP_ASV,             19},
    {15, MOP_ASVAUTO,         19},
    {15, MOP_IVAPS,           46},
    {15, MOP_PAC,             46},
    {16, MOP_AUTOSET,         26},
    {17, MOP_AUTOSET,         26},
    {32, MOP_AUTOSET,         34},
    {32, MOP_AUTOSET_FOR_HER, 34},
    {42, MOP_AUTOSET,         39},
    {42, MOP_VAUTO,            9},
};

void start(void)
{
    unsigned int rid = (unsigned int)variable_get_by_id(VAR_ID_RID);
    unsigned int mop = (unsigned int)variable_get_by_id(VAR_ID_MOP);
    unsigned int vid;

    if (mop >= sizeof(vid_by_mop))
        return;

    vid = vid_by_mop[mop];
    for (unsigned int i = 0;
         i < sizeof(regional_vid_map) / sizeof(regional_vid_map[0]); ++i) {
        if (regional_vid_map[i].rid == rid && regional_vid_map[i].mop == mop) {
            vid = regional_vid_map[i].vid;
            break;
        }
    }
    variable_set_by_id(VAR_ID_VID, vid);
}

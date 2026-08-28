/*
 * vid_spoof.c - MOP-based software variant identity override
 *
 * Runs after the persistent MOP writeback. The selected VID and the software
 * identity strings derived from it are published as one coherent profile.
 * Native DataItem access and variable IDs are supplied by the selected
 * per-version stubs and variable header.
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

static unsigned int read_text(unsigned short var_id, char *text, unsigned int capacity)
{
    unsigned int length = (unsigned int)DataItem_read_bytes_by_id(var_id, text, capacity);

    if (length == 0 || length >= capacity)
        return 0;
    text[length] = '\0';
    return length;
}

/* FGT ends in an unpadded decimal variant, for example 2e_M46_V3. */
static int replace_fgt_vid(char *text, unsigned int capacity, unsigned int vid)
{
    unsigned int i;

    for (i = 0; i + 4 < capacity && text[i] != '\0'; ++i) {
        if (text[i] != '_' || text[i + 1] != 'V')
            continue;
        if (vid >= 10)
            text[i + 2] = (char)('0' + vid / 10);
        text[i + 2 + (vid >= 10)] = (char)('0' + vid % 10);
        text[i + 3 + (vid >= 10)] = '\0';
        return 1;
    }
    return 0;
}

/* GCD and CID encode VID as the two-digit field after the second dot. */
static int replace_dotted_vid(char *text, unsigned int capacity, unsigned int vid)
{
    unsigned int i;
    unsigned int dots = 0;

    for (i = 0; i + 3 < capacity && text[i] != '\0'; ++i) {
        if (text[i] != '.')
            continue;
        if (++dots != 2)
            continue;
        if (text[i + 3] != '.')
            return 0;
        text[i + 1] = (char)('0' + vid / 10);
        text[i + 2] = (char)('0' + vid % 10);
        return 1;
    }
    return 0;
}

/* PVI ends in a zero-padded three-digit variant. */
static int replace_pvi_vid(char *text, unsigned int length, unsigned int vid)
{
    if (length < 3)
        return 0;
    text[length - 3] = (char)('0' + vid / 100);
    text[length - 2] = (char)('0' + (vid / 10) % 10);
    text[length - 1] = (char)('0' + vid % 10);
    return 1;
}

static void publish_variant_identity(unsigned int vid)
{
    char fgt[17];
    char gcd[30];
    char cid[65];
    char pvi[37];
    unsigned int pvi_length;

    if (!read_text(VAR_ID_FGT, fgt, sizeof(fgt)) ||
        !read_text(VAR_ID_GCD, gcd, sizeof(gcd)) ||
        !read_text(VAR_ID_CID, cid, sizeof(cid)))
        return;
    pvi_length = read_text(VAR_ID_PVI, pvi, sizeof(pvi));
    if (pvi_length == 0)
        return;

    /* Prepare every derived value before publishing any part of the profile. */
    if (!replace_fgt_vid(fgt, sizeof(fgt), vid) ||
        !replace_dotted_vid(gcd, sizeof(gcd), vid) ||
        !replace_dotted_vid(cid, sizeof(cid), vid) ||
        !replace_pvi_vid(pvi, pvi_length, vid))
        return;

    DataItem_write_text_notify_by_id(VAR_ID_FGT, fgt);
    DataItem_write_text_notify_by_id(VAR_ID_GCD, gcd);
    DataItem_write_text_notify_by_id(VAR_ID_CID, cid);
    DataItem_write_text_notify_by_id(VAR_ID_PVI, pvi);
    DataItem_write_raw_by_id(VAR_ID_VID, (int)vid);
}

void __attribute__((section(".text.0.main")))
start(void)
{
    unsigned int mop = (unsigned int)DataItem_read_value_by_id(VAR_ID_MOP);
    if (mop < sizeof(vid_lut)) {
        unsigned int vid = vid_lut[mop];
        if (vid != 0)
            publish_variant_identity(vid);
    }
}

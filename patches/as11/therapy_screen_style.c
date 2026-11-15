/* Therapy View Auto: raw TSS 3 selects Simple or Pressure by therapy mode. */

#include "stubs.h"
#include "vars.h"

#define TSS_SIMPLE         0
#define TSS_PRESSURE_BAR   1
#define TSS_AUTO           3

/* Native DataItem switch: action header, child list, var_id, fallback. */
#define SWITCH_SIZE        0x14u
#define SWITCH_FALLBACK    0x10u

/* CPAP, AutoSet and AutoSet for Her keep Simple; other modes use Pressure. */
static const unsigned char simple_profiles[] = {0, 1, 2};

static int auto_style(void)
{
    int profile = DataItem_read_value_by_id(VAR_ID_MOP);
    for (unsigned int i = 0; i < sizeof(simple_profiles); ++i)
        if (profile == simple_profiles[i])
            return TSS_SIMPLE;
    return TSS_PRESSURE_BAR;
}

/* Replaces the native registration of PressureBar (raw TSS 1). Auto is a
 * native switch on MOP, so navigation resolves the mode whenever it enters
 * the therapy screen. Simple is the TSS switch fallback. */
void __attribute__((section(".text.0.main"))) start(void *tss_switch, unsigned int value, void *pressure_bar)
{
    GuiSwitchAction_add(tss_switch, value, pressure_bar);
    void *simple = *(void **)((unsigned char *)tss_switch + SWITCH_FALLBACK);
    if (!simple || !pressure_bar)
        return;
    void *by_profile = heap_alloc(SWITCH_SIZE);
    if (!by_profile)
        return;
    GuiDataItemSwitch_ctor(by_profile, VAR_ID_MOP, pressure_bar);
    for (unsigned int i = 0; i < sizeof(simple_profiles); ++i)
        GuiSwitchAction_add(by_profile, simple_profiles[i], simple);
    GuiSwitchAction_add(tss_switch, TSS_AUTO, by_profile);
}

/* Replaces the TSS read of the PressureBar bitmap condition, which compares
 * the value with 1. The CPAP-only visibility consumer needs no hook: Auto
 * resolves to Simple in CPAP. */
int therapy_screen_style_read(unsigned short var_id)
{
    int value = DataItem_read_value_by_id(var_id);
    return value == TSS_AUTO ? auto_style() : value;
}

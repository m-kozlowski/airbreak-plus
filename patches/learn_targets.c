#include "s10_vars.h"
#include "button_hooks.h"

extern int variable_get_by_id(int);
extern void variable_set_by_id(int, int);
extern void variable_set_member_clear_by_index(int, int);
extern int gui_inactivity_filter(void *, int);
extern const unsigned char learn_targets_page, learn_targets_results_page;
extern const unsigned short learn_targets_prompt_index;

/* Learning (ZRM=9) uses the normal therapy GUI handler, so a short Start/Stop
 * press needs an explicit cancellation request.
 */
int learn_targets_stop_button(unsigned event, unsigned held_ms)
{
    (void)held_ms;
    if (event != BUTTON_START_STOP || variable_get_by_id(VAR_ID_ZRM) != 9)
        return 0;
    variable_set_by_id(VAR_ID_ZUI, 4);
    return 1;
}

/* Feed activity event 12 to both timers during learning. ZRM 9 -> 4 does not
 * reset them, so an expired timer could fire immediately afterward.
 */
int learn_targets_inactivity(void *timer, int event)
{
    if (variable_get_by_id(VAR_ID_ZRM) != 9)
        return gui_inactivity_filter(timer, event);

    gui_inactivity_filter(timer, 12);
    return event == 10 || event == 11 ? 0 : event;
}

static int learning(void)
{
    /* ZLC prevents a pending Accept from reopening the results page. */
    return variable_get_by_id(VAR_ID_ILE) == 1 &&
           variable_get_by_id(VAR_ID_ZLC) == 0;
}

unsigned learn_targets_default(void *menu)
{
    unsigned normal = *((unsigned char *)menu + 0x20);
    return learning() && variable_get_by_id(VAR_ID_ZLS) < 3 ?
           learn_targets_page : normal;
}

unsigned learn_targets_select(int var_id, void *menu)
{
    unsigned page = variable_get_by_id(var_id), target = page, item = 0;
    int state = variable_get_by_id(VAR_ID_ZLS);
    if (state != 2 && variable_get_by_id(VAR_ID_SPM) == 2)
        variable_set_member_clear_by_index(learn_targets_prompt_index, 1);

    if (learning()) {
        if (state == 3 && variable_get_by_id(VAR_ID_ZUM) == 1) {
            target = learn_targets_results_page;
            item = 1; /* Heading followed by Accept. */
        } else if (page == learn_targets_results_page) {
            target = state < 3 ? learn_targets_page :
                     *((unsigned char *)menu + 0x20);
        }
    } else if (page == learn_targets_page || page == learn_targets_results_page) {
        target = *((unsigned char *)menu + 0x20);
    }
    if (target != page) {
        variable_set_by_id(VAR_ID_ZVI, item);
        variable_set_by_id(VAR_ID_ZML, target);
    }
    return target;
}

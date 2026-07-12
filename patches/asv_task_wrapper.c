// Author: noombs @ Discord

extern int isNotBreathingPtr;
extern float breathPercentagePtr;
extern int variable_get_by_id(int var_id);
extern void asv_task_function(void *ctx);
extern const unsigned short asv_task_wrapper_backup_rate_var_id;

static int backup_rate_enabled(void)
{
    if (asv_task_wrapper_backup_rate_var_id == 0xFFFFu)
        return 0;

    return variable_get_by_id((int)asv_task_wrapper_backup_rate_var_id) != 0;
}

void start(void *ctx) {
    // Clamp the trigger point unless the runtime setting requests stock behavior.
    if (!backup_rate_enabled() &&
        isNotBreathingPtr == 1 && breathPercentagePtr > 0.98f) {
        breathPercentagePtr = 0.98f;
    }

    // Execute the ASV task
    asv_task_function(ctx);
}

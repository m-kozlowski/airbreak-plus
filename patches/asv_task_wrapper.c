// Author: noombs @ Discord

extern int asv_low_flow_state;
extern float asv_phase_estimate;
extern int variable_get_by_id(int var_id);
extern void asv_publish_target_ventilation_and_pressure(void *ctx);
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
        asv_low_flow_state == 1 && asv_phase_estimate > 0.98f) {
        asv_phase_estimate = 0.98f;
    }

    asv_publish_target_ventilation_and_pressure(ctx);
}

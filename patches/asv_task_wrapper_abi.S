.syntax unified
.thumb

.section .rodata.asv_task_wrapper_abi, "a", %progbits
.align 2

/* Patched with the reclaimed g[8] switch var_id by custom settings.
 * 0xffff preserves the payload's legacy behavior: backup rate is suppressed.
 */
.global asv_task_wrapper_backup_rate_var_id
.type asv_task_wrapper_backup_rate_var_id, %object
asv_task_wrapper_backup_rate_var_id:
    .short 0xffff
.size asv_task_wrapper_backup_rate_var_id, . - asv_task_wrapper_backup_rate_var_id

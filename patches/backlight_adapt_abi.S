.syntax unified
.thumb

/* Patched with the reclaimed g[4] var_id used as the full-brightness ASF
 * threshold. The sentinel keeps the payload useful without custom settings.
 */
.section .rodata.backlight_adapt_abi, "a", %progbits
.align 2
.global backlight_adapt_full_asf_var_id
.type backlight_adapt_full_asf_var_id, %object
backlight_adapt_full_asf_var_id:
    .short 0xffff
.size backlight_adapt_full_asf_var_id, . - backlight_adapt_full_asf_var_id

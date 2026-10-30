.syntax unified
.thumb
.section .rodata
.balign 4

/* Optional zero-terminated list of keep-awake predicates from other payloads. */
.global keep_backlight_requests
.type keep_backlight_requests,%object
keep_backlight_requests:
    .word 0
.size keep_backlight_requests,4

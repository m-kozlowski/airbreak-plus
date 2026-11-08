.syntax unified
.thumb

.section .rodata.breath_tracking_abi, "a", %progbits
.balign 4

/* Optional constructors, connected after both payloads are installed. */
.global breath_tracking_attach_prepare
.type breath_tracking_attach_prepare, %object
breath_tracking_attach_prepare:
    .word 0xffffffff

.global breath_tracking_attach_finish
.type breath_tracking_attach_finish, %object
breath_tracking_attach_finish:
    .word 0xffffffff

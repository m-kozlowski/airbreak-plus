.syntax unified
.thumb
.section .rodata
.balign 4

/* Patcher-generated, zero-terminated registry. No registry means stock input. */
.global button_hook_registry
.type button_hook_registry,%object
button_hook_registry:
    .word 0xffffffff
.size button_hook_registry,4

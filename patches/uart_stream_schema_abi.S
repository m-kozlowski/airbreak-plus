.syntax unified
.thumb

/* Filled with the displaced G C command handler before the hook is installed. */
.section .rodata.uart_stream_schema_abi, "a", %progbits
.align 2
.global uart_stream_schema_original_handler
.type uart_stream_schema_original_handler, %object
uart_stream_schema_original_handler:
    .word 0xffffffff
.size uart_stream_schema_original_handler, . - uart_stream_schema_original_handler

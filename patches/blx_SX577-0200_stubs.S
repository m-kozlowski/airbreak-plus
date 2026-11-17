.syntax unified
.thumb

/* SX577-0200 BLX is copied from file offset 0x300 to SRAM 0x20000000. */
.global boot_command_dispatch
.thumb_set boot_command_dispatch, 0x200001bf

.global usart_dma_write
.thumb_set usart_dma_write, 0x20001293

.global timer_reset
.thumb_set timer_reset, 0x20000df7

.global timeout_get_instance
.thumb_set timeout_get_instance, 0x20000f39

.global usart_get
.thumb_set usart_get, 0x200013cb

.global frame_build
.thumb_set frame_build, 0x20001545

/* Native CCITT CRC (initial 0xffff), and SysTick time in milliseconds. */
.global boot_crc16
.thumb_set boot_crc16, 0x2000166b
.global get_tick_scaled
.thumb_set get_tick_scaled, 0x20001cb9

.global boot_watchdog_reload
.thumb_set boot_watchdog_reload, 0x20002837

.global usart_read
.thumb_set usart_read, 0x20001203
.global frame_parser_reset
.thumb_set frame_parser_reset, 0x20003171
.global frame_parser_append
.thumb_set frame_parser_append, 0x20003189
.global frame_parser_next
.thumb_set frame_parser_next, 0x20003191

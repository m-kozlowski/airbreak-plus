// SX584-0204 firmware function addresses

#define NSTUB(addr,name) \
	.global name; \
	.type name, %function; \
	name = addr
#define NSTUB_VAR(addr,name) \
	.global name; \
	.type name, %object; \
	name = addr

.text

// Front-panel input singleton
NSTUB(0x08055EEB, front_panel_input_init)

// Stock bilevel and iVAPS pressure waveforms
NSTUB(0x08077829, therapy_variable_get)
NSTUB(0x08089A4D, bilevel_pressure_waveform_expiration_ramp)
NSTUB(0x08097E35, ivaps_pressure_waveform_expiration_ramp)
NSTUB_VAR(0x2000969C, therapy_waveform_profile)

// Memory and clinical menus
NSTUB(0x0803B435, malloc)
NSTUB(0x080408F1, memcpy_unrolled)
NSTUB(0x080379C9, gui_create_menus)
NSTUB(0x0803CBAF, scrollbar_init)
NSTUB(0x0803C6A5, scrollbar_add_item)
NSTUB(0x0803B1B9, variable_0x1bc_and_0x1bd_writer_setup)
NSTUB(0x0803CE59, gui_create_back_button)
NSTUB(0x0803D7E9, menu_create_text_or_float)
NSTUB(0x0803E585, menu_create_numeric_var)
NSTUB(0x0803DA69, menu_create_static_string)

// Variable access and config storage
NSTUB(0x0803F1A1, variable_get_by_id)
NSTUB(0x0803EC6D, variable_lookup_handler)
NSTUB(0x0803EC89, variable_handler_release)
NSTUB(0x0803EF4D, variable_set_visible_from_handler)
NSTUB(0x080A13B1, file_get_size)

// ASV backup rate: integer state 0x3c and float phase 0x5b.
NSTUB_VAR(0x20009738, isNotBreathingPtr)
NSTUB_VAR(0x20009A04, breathPercentagePtr)
NSTUB(0x080C897D, asv_task_function)

// Backlight
NSTUB(0x080546AF, backlight_state_machine)
NSTUB(0x080544CB, backlight_output_timeout_update)
NSTUB(0x0805445F, backlight_outputs_apply_state)
NSTUB(0x08046083, millisecond_timer_init)
NSTUB(0x080460AB, millisecond_timer_expired)
NSTUB(0x08055CFD, pwm_controller_init)
NSTUB(0x08055E67, pwm_controller_get)

// LCD
NSTUB(0x0806320F, lcd_write_cmd)
NSTUB(0x08063217, lcd_write_data)
NSTUB(0x08060F6F, lcd_delay_ms)
NSTUB(0x0805CA09, original_board_init)
NSTUB(0x080630B3, lcd_get_device)

// Header clock
NSTUB(0x0803BF13, gui_root_screen_init)
NSTUB(0x0803C125, gui_root_screen_get)
NSTUB(0x0803BF7B, gui_root_screen_layout_right_widgets)
NSTUB(0x080431F3, gui_disp_string_at_utf8)
NSTUB(0x080431E1, gui_get_string_width)
NSTUB(0x0804F2E9, WM_InvalidateRect)

// UART metadata and formatting
NSTUB(0x08004101, ccx_get_globals)
NSTUB(0x0803ED97, variable_handler_get_uart_name)
NSTUB(0x0803EE8B, variable_handler_wire_width)
NSTUB(0x08046147, string_id_lookup_current_locale)
NSTUB(0x08045FB5, strlen_fast)
NSTUB(0x08046565, snprintf)
NSTUB(0x0804FF43, format_hex_u16)
NSTUB(0x0804FF6B, format_fixed_width_hex)
NSTUB(0x080BCD0D, parse_hex_u16)

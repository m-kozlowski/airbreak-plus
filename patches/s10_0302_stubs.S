// SX567-0302 firmware function addresses

#define NSTUB(addr,name) \
	.global name; \
	.type name, %function; \
	name = addr
#define NSTUB_VAR(addr,name) \
	.global name; \
	.type name, %object; \
	name = addr

.text

// GUI / LCD
NSTUB(0x0807AE71, GUI_SetColor)
NSTUB(0x0807B095, LCD_FillRect)
NSTUB(0x0806CD65, snprintf)
NSTUB_VAR(0x680000A0, gui_context)
NSTUB(0x0806CC5B, gui_invalidate_window)
NSTUB(0x08069BBB, gui_method_fc104_setup_and_invalidate)

NSTUB(0x08063639, malloc)
NSTUB(0x0808198F, tim_read_tim5)
NSTUB(0x08060D15, gui_create_menus)
NSTUB(0x08064C35, scrollbar_init)
NSTUB(0x08064769, scrollbar_add_item)
NSTUB(0x08063505, variable_0x1bc_and_0x1bd_writer_setup)
NSTUB(0x08064EE1, gui_create_back_button)
NSTUB(0x08065631, menu_create_text_or_float)
NSTUB(0x08065D39, menu_create_numeric_var)
NSTUB(0x080658B1, menu_create_static_string)
NSTUB(0x08066391, variable_lookup_handler)
NSTUB(0x080663AD, variable_handler_release)
NSTUB(0x0806664F, variable_set_visible_from_handler)
NSTUB(0x080664BA, variable_handler_get_uart_name)
NSTUB(0x0806658E, variable_handler_wire_width)
NSTUB(0x08004100, ccx_get_globals)
NSTUB(0x0806C96B, string_id_lookup_current_locale)

// Config persistence
NSTUB(0x0809D911, file_get_size)

// Variable system
NSTUB(0x0806675A, variable_set_by_id)
NSTUB(0x080668A2, variable_get_by_id)
NSTUB(0x080D92B8, parse_hex_u16)

NSTUB(0x080BC02B, pressure_limit_max_difference)
NSTUB_VAR(0x2000E948, fvars)
NSTUB_VAR(0x2000E750, ivars)
NSTUB_VAR(0x20000BE0, magic_ptr)

// Backlight adaptation
NSTUB(0x08079B30, backlight_state_machine)

// LCD driver
NSTUB(0x0808072F, lcd_write_cmd)
NSTUB(0x08080737, lcd_write_data)
NSTUB(0x0808085B, lcd_delay_ms)
NSTUB(0x08080DDB, flexcolor_ensure_init)
NSTUB(0x080E2585, flexcolor_set_interface)
NSTUB(0x080E25AB, original_controller_init)
NSTUB(0x080D8923, original_hw_init)
NSTUB(0x0807B5B5, original_board_init)
NSTUB(0x080D880D, flexcolor_draw_bitmap)
NSTUB(0x080D872F, flexcolor_fill_rect)
NSTUB(0x08080D33, flexcolor_draw_hline)
NSTUB(0x08080C81, flexcolor_draw_vline)
NSTUB(0x080D829F, flexcolor_cs_assert)
NSTUB(0x080D82A9, flexcolor_write_data)
NSTUB(0x080866AB, iwdg_reload)
NSTUB(0x080805D3, lcd_get_device)

// ASV task wrapper
NSTUB_VAR(0x2000E808, isNotBreathingPtr)
NSTUB_VAR(0x2000EA9C, breathPercentagePtr)
NSTUB(0x080E2AF8, asv_task_function)

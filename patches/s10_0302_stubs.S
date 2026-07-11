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
NSTUB_VAR(0x680000A0, gui_context)

NSTUB(0x08063639, malloc)
NSTUB(0x0808198F, tim_read_tim5)
NSTUB(0x08064769, scrollbar_add_item)
NSTUB(0x08065631, menu_create_text_or_float)
NSTUB(0x08065D39, menu_create_numeric_var)
NSTUB(0x08066391, variable_lookup_handler)
NSTUB(0x080663AD, variable_handler_release)
NSTUB(0x0806664F, variable_set_visible_from_handler)

// Config persistence
NSTUB(0x0809D911, file_get_size)

// Variable system
NSTUB(0x0806675A, variable_set_by_id)
NSTUB(0x080668A2, variable_get_by_id)

NSTUB(0x080BC02B, pressure_limit_max_difference)
NSTUB_VAR(0x2000E948, fvars)
NSTUB_VAR(0x2000E750, ivars)
NSTUB_VAR(0x20000BE0, magic_ptr)

// Backlight adaptation
NSTUB(0x08079B30, backlight_state_machine)

// LCD driver
NSTUB(0x0808072F, lcd_write_cmd)
NSTUB(0x08080737, lcd_write_data)
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

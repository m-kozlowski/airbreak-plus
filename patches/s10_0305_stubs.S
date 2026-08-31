// SX567-0305 firmware function addresses

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
NSTUB(0x0807B5E9, GUI_SetColor)
NSTUB(0x0807B80D, LCD_FillRect)

// Formatting / memory
NSTUB(0x0806D495, snprintf)
NSTUB(0x08068529, memcpy_unrolled)
NSTUB(0x0806CF09, strlen_fast)
NSTUB(0x080BDC91, sqrtf)
NSTUB(0x08075607, format_hex_u16)
NSTUB(0x0807562F, format_fixed_width_hex)

// GUI internals
NSTUB_VAR(0x680000A0, gui_context)
NSTUB(0x0806D38B, gui_invalidate_window)
NSTUB(0x0806A2DF, gui_method_fc104_setup_and_invalidate)

NSTUB(0x08063D5D, malloc)
NSTUB(0x08082117, tim_read_tim5)
NSTUB(0x08061435, gui_create_menus)
NSTUB(0x08065359, scrollbar_init)
NSTUB(0x08064E8D, scrollbar_add_item)
NSTUB(0x08063C29, variable_0x1bc_and_0x1bd_writer_setup)
NSTUB(0x08065605, gui_create_back_button)
NSTUB(0x08065D55, menu_create_text_or_float)
NSTUB(0x0806645D, menu_create_numeric_var)
NSTUB(0x08065FD5, menu_create_static_string)
NSTUB(0x08066AB5, variable_lookup_handler)
NSTUB(0x08066AD1, variable_handler_release)
NSTUB(0x08066D73, variable_set_visible_from_handler)
NSTUB(0x08066BDE, variable_handler_get_uart_name)
NSTUB(0x08066CB2, variable_handler_wire_width)
NSTUB(0x08004100, ccx_get_globals)
NSTUB(0x0806D09B, string_id_lookup_current_locale)

// Config persistence
NSTUB(0x0809E095, file_get_size)

// Variable system
NSTUB(0x08066E7E, variable_set_by_id)
NSTUB(0x08066FC6, variable_get_by_id)
NSTUB(0x080D9AA8, parse_hex_u16)

NSTUB(0x080BC81B, pressure_limit_max_difference)
NSTUB_VAR(0x2000E948, fvars)
NSTUB_VAR(0x2000E750, ivars)
NSTUB_VAR(0x20000BE0, magic_ptr)

// Backlight adaptation
NSTUB(0x0807A2A8, backlight_state_machine)

// LCD driver
NSTUB(0x08080EB7, lcd_write_cmd)
NSTUB(0x08080EBF, lcd_write_data)
NSTUB(0x08080FE3, lcd_delay_ms)
NSTUB(0x08081563, flexcolor_ensure_init)
NSTUB(0x080E2D75, flexcolor_set_interface)
NSTUB(0x080E2D9B, original_controller_init)
NSTUB(0x080D9113, original_hw_init)
NSTUB(0x0807BD2D, original_board_init)
NSTUB(0x080D8FFD, flexcolor_draw_bitmap)
NSTUB(0x080D8F1F, flexcolor_fill_rect)
NSTUB(0x080814BB, flexcolor_draw_hline)
NSTUB(0x08081409, flexcolor_draw_vline)
NSTUB(0x080D8A8F, flexcolor_cs_assert)
NSTUB(0x080D8A99, flexcolor_write_data)
NSTUB(0x080873DB, iwdg_reload)
NSTUB(0x08080D5B, lcd_get_device)

// ASV task wrapper
NSTUB_VAR(0x2000E808, isNotBreathingPtr)
NSTUB_VAR(0x2000EA9C, breathPercentagePtr)
NSTUB(0x080E32E8, asv_task_function)

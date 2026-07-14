// SX567-0306 firmware function addresses

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
NSTUB(0x0807B5E5, GUI_SetColor)
NSTUB(0x0807B809, LCD_FillRect)
NSTUB_VAR(0x680000A0, gui_context)

NSTUB(0x08063D5D, malloc)
NSTUB(0x08082097, tim_read_tim5)
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

// Config persistence
NSTUB(0x0809E019, file_get_size)

// Variable system
NSTUB(0x08066E7E, variable_set_by_id)
NSTUB(0x08066FC6, variable_get_by_id)

NSTUB(0x080BC733, pressure_limit_max_difference)
NSTUB_VAR(0x2000E948, fvars)
NSTUB_VAR(0x2000E750, ivars)
NSTUB_VAR(0x20000BE0, magic_ptr)

// Backlight adaptation
NSTUB(0x0807A2A4, backlight_state_machine)

// LCD driver
NSTUB(0x08080E37, lcd_write_cmd)
NSTUB(0x08080E3F, lcd_write_data)
NSTUB(0x080814E3, flexcolor_ensure_init)
NSTUB(0x080E2C91, flexcolor_set_interface)
NSTUB(0x080E2CB7, original_controller_init)
NSTUB(0x080D9027, original_hw_init)
NSTUB(0x0807BD29, original_board_init)
NSTUB(0x080D8F11, flexcolor_draw_bitmap)
NSTUB(0x080D8E33, flexcolor_fill_rect)
NSTUB(0x0808143B, flexcolor_draw_hline)
NSTUB(0x08081389, flexcolor_draw_vline)
NSTUB(0x080D89A3, flexcolor_cs_assert)
NSTUB(0x080D89AD, flexcolor_write_data)
NSTUB(0x0808735B, iwdg_reload)
NSTUB(0x08080CDB, lcd_get_device)

// ASV task wrapper
NSTUB_VAR(0x2000E808, isNotBreathingPtr)
NSTUB_VAR(0x2000EA9C, breathPercentagePtr)
NSTUB(0x080E3204, asv_task_function)

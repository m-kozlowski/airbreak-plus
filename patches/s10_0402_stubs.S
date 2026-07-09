// SX567-0402 firmware function addresses

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
NSTUB(0x0807BB0F, LCD_SetClipRectMax)
NSTUB(0x0807B661, LCD_DrawPixel)
NSTUB(0x0806D499, snprintf)
NSTUB(0x08072D49, GUI_SetFont)
NSTUB(0x0806B243, GUI_SetFont_default)
NSTUB(0x08072D89, GUI_SetTextMode)
NSTUB(0x08072DA1, GUI_SetTextAlign)
NSTUB(0x0807BCE9, GUI_GotoXY)
NSTUB(0x08072F6D, GUI_DispStringAt)
NSTUB_VAR(0x08060DB4, font_16)
NSTUB_VAR(0x680000A0, gui_context)

NSTUB(0x08063D5D, malloc)
NSTUB(0x08082097, tim_read_tim5)
NSTUB(0x08064E8D, scrollbar_add_item)
NSTUB(0x08065D55, menu_create_text_or_float)
NSTUB(0x0806645D, menu_create_numeric_var)
NSTUB(0x08066AB5, variable_lookup_handler)
NSTUB(0x08066AD1, variable_handler_release)
NSTUB(0x08066D73, variable_set_visible_from_handler)

NSTUB(0x080BCBC3, pressure_limit_max_difference)
NSTUB_VAR(0x2000E954, fvars)
NSTUB_VAR(0x2000E75C, ivars)
NSTUB_VAR(0x2000E814, isNotBreathingPtr)
NSTUB_VAR(0x2000EAA8, breathPercentagePtr)
NSTUB(0x080E36DD, asv_task_function)

NSTUB_VAR(0x20000BE0, magic_ptr)

// Variable system
NSTUB(0x08066E7E, variable_set_by_id)
NSTUB(0x08066FC6, variable_get_by_id)

// Backlight adaptation
NSTUB(0x0807A2A4, backlight_state_machine)

// LCD driver
NSTUB(0x08080E37, lcd_write_cmd)
NSTUB(0x08080E3F, lcd_write_data)
NSTUB(0x080814E3, flexcolor_ensure_init)
NSTUB(0x080E3169, flexcolor_set_interface)
NSTUB(0x080E318F, original_controller_init)
NSTUB(0x080D226F, original_hw_init)
NSTUB(0x0807BD29, original_board_init)
NSTUB(0x080D93E9, flexcolor_draw_bitmap)
NSTUB(0x080D9231, flexcolor_fill_rect)
NSTUB(0x0808143B, flexcolor_draw_hline)
NSTUB(0x08081389, flexcolor_draw_vline)
NSTUB(0x080D8E7B, flexcolor_cs_assert)
NSTUB(0x080D8E85, flexcolor_write_data)
NSTUB(0x080875BB, iwdg_reload)
NSTUB(0x08080CDB, lcd_get_device)

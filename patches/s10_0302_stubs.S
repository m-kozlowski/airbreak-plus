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

// Stock ST breath timing and worker lifecycle
NSTUB(0x080A78D1, breath_progress_worker_reset)
NSTUB(0x080A78FD, breath_progress_worker_update_mode)
NSTUB(0x080A79A7, breath_progress_worker_disable)
NSTUB(0x080A79AD, breath_progress_worker_update)

// Stock bilevel and iVAPS pressure waveforms
NSTUB(0x0809FED9, therapy_variable_get)
NSTUB(0x080AFC09, bilevel_pressure_waveform_expiration_ramp)
NSTUB(0x080AB8B1, ivaps_pressure_waveform_expiration_ramp)
NSTUB_VAR(0x2000E798, therapy_waveform_profile)

// GUI / LCD
NSTUB(0x0807AE71, GUI_SetColor)
NSTUB(0x0807B095, LCD_FillRect)

// Formatting / memory
NSTUB(0x0806CD65, snprintf)
NSTUB(0x08067E05, memcpy_unrolled)
NSTUB(0x0806C7D9, strlen_fast)
NSTUB(0x080BD4A1, sqrtf)
NSTUB(0x08074ED7, format_hex_u16)
NSTUB(0x08074EFF, format_fixed_width_hex)

// GUI internals
NSTUB(0x0807261D, GUI_SetFont)
NSTUB(0x0807265D, GUI_SetTextMode)
NSTUB(0x08072675, GUI_SetTextAlign)
NSTUB(0x08072841, GUI_DispStringAt)
NSTUB_VAR(0x08060694, font_16)
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

// Active-language fonts and cached GUI layout
NSTUB(0x0806A9E1, gui_font_profile_get)
NSTUB(0x0806AA25, gui_font_profile_select_for_lnc)
NSTUB(0x0806EA73, gui_variable_binding_update_value)
NSTUB(0x08066C15, g8_index_from_short_var_id)
NSTUB(0x08069B01, gui_get_string_width)
NSTUB(0x0806CD49, gui_base_window_height)
NSTUB(0x0806DCEF, gui_disp_string_lookup_left)
NSTUB(0x08063F85, gui_variable_text_widget_update)
NSTUB(0x08063EE5, gui_variable_text_widget_draw)
NSTUB(0x0806CF05, gui_pressure_arc_layout_init)
NSTUB(0x0806CF9D, gui_draw_breath_arc)
NSTUB_VAR(0x08059630, font_text_japanese)
NSTUB_VAR(0x0804EA40, font_text_chinese)
NSTUB_VAR(0x080992B0, font_large_standard)
NSTUB_VAR(0x08097024, font_large_cjk)

// Header clock
NSTUB(0x08063FEF, gui_root_screen_init)
NSTUB(0x080641FD, gui_root_screen_get)
NSTUB(0x08064053, gui_root_screen_layout_right_widgets)
NSTUB(0x08069B13, gui_disp_string_at_utf8)
NSTUB(0x080739E5, WM_InvalidateRect)

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
NSTUB(0x0807999E, backlight_output_timeout_update)
NSTUB(0x08079930, backlight_outputs_apply_state)
NSTUB(0x0806C8A6, millisecond_timer_init)

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

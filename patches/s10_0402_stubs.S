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

// Stock ST breath timing and worker lifecycle
NSTUB(0x080A8469, breath_progress_worker_reset)
NSTUB(0x080A8495, breath_progress_worker_update_mode)
NSTUB(0x080A853F, breath_progress_worker_disable)
NSTUB(0x080A8545, breath_progress_worker_update)

// Stock bilevel and iVAPS pressure waveforms
NSTUB(0x080A0A71, therapy_variable_get)
NSTUB(0x080B07A1, bilevel_pressure_waveform_expiration_ramp)
NSTUB(0x080AC449, ivaps_pressure_waveform_expiration_ramp)
NSTUB_VAR(0x2000E7A4, therapy_waveform_profile)

// GUI / LCD
NSTUB(0x0807B5E5, GUI_SetColor)
NSTUB(0x0807B809, LCD_FillRect)
NSTUB(0x0807BB0F, LCD_SetClipRectMax)
NSTUB(0x0807B661, LCD_DrawPixel)

// Formatting / memory
NSTUB(0x0806D499, snprintf)
NSTUB(0x0806852D, memcpy_unrolled)
NSTUB(0x0806CF0D, strlen_fast)
NSTUB(0x080BE039, sqrtf)
NSTUB(0x08075603, format_hex_u16)
NSTUB(0x0807562B, format_fixed_width_hex)

// GUI internals
NSTUB(0x08072D49, GUI_SetFont)
NSTUB(0x0806B243, GUI_SetFont_default)
NSTUB(0x08072D89, GUI_SetTextMode)
NSTUB(0x08072DA1, GUI_SetTextAlign)
NSTUB(0x0807BCE9, GUI_GotoXY)
NSTUB(0x08072F6D, GUI_DispStringAt)
NSTUB_VAR(0x08060DB4, font_16)
NSTUB_VAR(0x680000A0, gui_context)
NSTUB(0x0806D38F, gui_invalidate_window)
NSTUB(0x0806A2E3, gui_method_fc104_setup_and_invalidate)

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
NSTUB(0x08066BDE, variable_handler_get_uart_name)
NSTUB(0x08066CB2, variable_handler_wire_width)
NSTUB(0x08004100, ccx_get_globals)
NSTUB(0x0806D09F, string_id_lookup_current_locale)

// Active-language fonts and cached GUI layout
NSTUB(0x0806B115, gui_font_profile_get)
NSTUB(0x0806B159, gui_font_profile_select_for_lnc)
NSTUB(0x0806F1A3, gui_variable_binding_update_value)
NSTUB(0x08067339, g8_index_from_short_var_id)
NSTUB(0x0806A229, gui_get_string_width)
NSTUB(0x0806D47D, gui_base_window_height)
NSTUB(0x0806E41F, gui_disp_string_lookup_left)
NSTUB(0x080646A9, gui_variable_text_widget_update)
NSTUB(0x08064609, gui_variable_text_widget_draw)
NSTUB(0x0806D635, gui_pressure_arc_layout_init)
NSTUB(0x0806D6CD, gui_draw_breath_arc)
NSTUB_VAR(0x08059D50, font_text_japanese)
NSTUB_VAR(0x0804ED40, font_text_chinese)
NSTUB_VAR(0x08099E48, font_large_standard)
NSTUB_VAR(0x08097BBC, font_large_cjk)

// Header clock
NSTUB(0x08064713, gui_root_screen_init)
NSTUB(0x08064921, gui_root_screen_get)
NSTUB(0x08064777, gui_root_screen_layout_right_widgets)
NSTUB(0x0806A23B, gui_disp_string_at_utf8)
NSTUB(0x08074111, WM_InvalidateRect)

// Config persistence
NSTUB(0x0809E4A9, file_get_size)

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
NSTUB(0x080D9E94, parse_hex_u16)

// Backlight adaptation
NSTUB(0x0807A2A4, backlight_state_machine)
NSTUB(0x0807A112, backlight_output_timeout_update)
NSTUB(0x0807A0A4, backlight_outputs_apply_state)
NSTUB(0x0806CFDA, millisecond_timer_init)

// LCD driver
NSTUB(0x08080E37, lcd_write_cmd)
NSTUB(0x08080E3F, lcd_write_data)
NSTUB(0x08080F63, lcd_delay_ms)
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

// iVAPS AutoEPAP: stock workers and numerical primitives
NSTUB(0x080BE001, expf)
NSTUB(0x080BF211, iir_filter_order4_update)
NSTUB(0x080BF3D1, iir_filter_order4_reset)
NSTUB(0x080BDE43, tau_filter_update_weighted)
NSTUB(0x080A0A5B, therapy_variable_get_float)
NSTUB(0x080A0D93, therapy_manager_get)
NSTUB(0x080A09D9, therapy_worker_append)
NSTUB(0x080A0D91, therapy_worker_shutdown_noop)
NSTUB(0x08074EEF, system_tick_get)
NSTUB(0x080E338D, ivaps_settings_update)
NSTUB(0x080AC0A5, therapy_mode67_pressure_waveform_worker_update)
NSTUB(0x080A5D45, breath_phase_adaptation_mode_update)
NSTUB(0x080A5E5D, breath_phase_adaptation_update)
NSTUB(0x080A74B5, breath_transition_detector_update)
NSTUB(0x080AA739, ivaps_breath_timing_worker_mode_update)
NSTUB(0x080AAA6D, ivaps_breath_timing_worker_update)
NSTUB(0x080AA8BD, ivaps_breath_timing_update_targets)
NSTUB(0x080BF5E5, ring_buffer3_push)
NSTUB(0x080A0C77, therapy_feedback_item_phase1_init)
NSTUB(0x080A0C9F, therapy_manager_set_feedback_item)
NSTUB(0x080BE73D, linear_map_clamped_2point)
NSTUB(0x080BE771, linear_map_clamped_3point)
NSTUB(0x080BE7DD, linear_map_clamped_4point)
NSTUB(0x080AA99D, ivaps_breath_timing_stability_factor)
NSTUB(0x080A10AF, therapy_fixed_vector_group1_ref_init)
NSTUB(0x080BE3ED, cyclic_counter_init)
NSTUB(0x080BE435, clamp_int_to_bounds)
NSTUB(0x080BFCA5, ring_span_fixed_vector_init)
NSTUB(0x080BFD3D, asv_breath_shape_harmonic_projector_init)
NSTUB(0x080BFD8D, asv_breath_shape_project_first_segment)
NSTUB(0x080C0005, asv_breath_shape_project_second_segment)
NSTUB(0x080BF8C9, asv_breath_landmark_score_next)
NSTUB(0x080A45A1, ivaps_ventilation_estimator_register)
NSTUB(0x080A4279, ivaps_ventilation_estimator_mode_update)
NSTUB(0x080A43F1, ivaps_ventilation_estimator_update)
NSTUB(0x080BDE19, tau_filter_init_int)
NSTUB(0x080A39AD, autoepap_normalization_resume)
NSTUB(0x080A5F0F, autoepap_phase_reset_resume)
NSTUB(0x080A2507, autoepap_leak_accept)
NSTUB(0x080A24E7, autoepap_leak_reject)
NSTUB(0x080AAB3B, autoepap_timing_measure)
NSTUB(0x080AAB17, autoepap_timing_target)
NSTUB(0x080AADA1, autoepap_timing_cleanup)
NSTUB(0x080AABB9, autoepap_timing_tail_resume)
NSTUB_VAR(0x200002EC, stock_flow_samples)
NSTUB(0x0806C9FF, g4_numeric_set_dynamic_min)
NSTUB(0x0806CA11, g4_numeric_set_dynamic_max)

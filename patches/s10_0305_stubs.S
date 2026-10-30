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

// Front-panel input singleton
NSTUB(0x0808257F, front_panel_input_init)

// Stock ST breath timing and worker lifecycle
NSTUB(0x080A80C1, breath_progress_worker_reset)
NSTUB(0x080A80ED, breath_progress_worker_update_mode)
NSTUB(0x080A8197, breath_progress_worker_disable)
NSTUB(0x080A819D, breath_progress_worker_update)

// Stock bilevel and iVAPS pressure waveforms
NSTUB(0x080A065D, therapy_variable_get)
NSTUB(0x080B03F9, bilevel_pressure_waveform_expiration_ramp)
NSTUB(0x080AC0A1, ivaps_pressure_waveform_expiration_ramp)
NSTUB_VAR(0x2000E798, therapy_waveform_profile)

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
NSTUB(0x08072D4D, GUI_SetFont)
NSTUB(0x08072D8D, GUI_SetTextMode)
NSTUB(0x08072DA5, GUI_SetTextAlign)
NSTUB(0x08072F71, GUI_DispStringAt)
NSTUB_VAR(0x08060DB4, font_16)
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

// Active-language fonts and cached GUI layout
NSTUB(0x0806B111, gui_font_profile_get)
NSTUB(0x0806B155, gui_font_profile_select_for_lnc)
NSTUB(0x0806F1A3, gui_variable_binding_update_value)
NSTUB(0x08067339, g8_index_from_short_var_id)
NSTUB(0x0806A225, gui_get_string_width)
NSTUB(0x0806D479, gui_base_window_height)
NSTUB(0x0806E41F, gui_disp_string_lookup_left)
NSTUB(0x080646A9, gui_variable_text_widget_update)
NSTUB(0x08064609, gui_variable_text_widget_draw)
NSTUB(0x0806D635, gui_pressure_arc_layout_init)
NSTUB(0x0806D6CD, gui_draw_breath_arc)
NSTUB_VAR(0x08059D50, font_text_japanese)
NSTUB_VAR(0x0804ED40, font_text_chinese)
NSTUB_VAR(0x08099A34, font_large_standard)
NSTUB_VAR(0x080977A8, font_large_cjk)

// Header clock
NSTUB(0x08064713, gui_root_screen_init)
NSTUB(0x08064921, gui_root_screen_get)
NSTUB(0x08064777, gui_root_screen_layout_right_widgets)
NSTUB(0x0806A237, gui_disp_string_at_utf8)
NSTUB(0x08074115, WM_InvalidateRect)

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
NSTUB(0x0807A116, backlight_output_timeout_update)
NSTUB(0x0807A0A8, backlight_outputs_apply_state)
NSTUB(0x0806CFD6, millisecond_timer_init)
NSTUB(0x0806CFFE, millisecond_timer_expired)
NSTUB(0x08080450, pwm_controller_init)
NSTUB(0x080805BA, pwm_controller_get)

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

// iVAPS AutoEPAP: stock workers and numerical primitives
NSTUB(0x080BDC59, expf)
NSTUB(0x080BEE69, iir_filter_order4_update)
NSTUB(0x080BF029, iir_filter_order4_reset)
NSTUB(0x080BDA9B, tau_filter_update_weighted)
NSTUB(0x080A0647, therapy_variable_get_float)
NSTUB(0x080A097F, therapy_manager_get)
NSTUB(0x080A05C5, therapy_worker_append)
NSTUB(0x080A097D, therapy_worker_shutdown_noop)
NSTUB(0x08074EF3, system_tick_get)
NSTUB(0x080E2F99, ivaps_settings_update)
NSTUB(0x080ABCFD, therapy_mode67_pressure_waveform_worker_update)
NSTUB(0x080A59A5, breath_phase_adaptation_mode_update)
NSTUB(0x080A5ABD, breath_phase_adaptation_update)
NSTUB(0x080A7115, breath_transition_detector_update)
NSTUB(0x080AA391, ivaps_breath_timing_worker_mode_update)
NSTUB(0x080AA6C5, ivaps_breath_timing_worker_update)
NSTUB(0x080AA515, ivaps_breath_timing_update_targets)
NSTUB(0x080BF23D, ring_buffer3_push)
NSTUB(0x080A0863, therapy_feedback_item_phase1_init)
NSTUB(0x080A088B, therapy_manager_set_feedback_item)
NSTUB(0x080BE395, linear_map_clamped_2point)
NSTUB(0x080BE3C9, linear_map_clamped_3point)
NSTUB(0x080BE435, linear_map_clamped_4point)
NSTUB(0x080AA5F5, ivaps_breath_timing_stability_factor)
NSTUB(0x080A0C9B, therapy_fixed_vector_group1_ref_init)
NSTUB(0x080BE045, cyclic_counter_init)
NSTUB(0x080BE08D, clamp_int_to_bounds)
NSTUB(0x080BF8FD, ring_span_fixed_vector_init)
NSTUB(0x080BF995, asv_breath_shape_harmonic_projector_init)
NSTUB(0x080BF9E5, asv_breath_shape_project_first_segment)
NSTUB(0x080BFC5D, asv_breath_shape_project_second_segment)
NSTUB(0x080BF521, asv_breath_landmark_score_next)
NSTUB(0x080A4201, ivaps_ventilation_estimator_register)
NSTUB(0x080A3ED9, ivaps_ventilation_estimator_mode_update)
NSTUB(0x080A4051, ivaps_ventilation_estimator_update)
NSTUB(0x080BDA71, tau_filter_init_int)
NSTUB(0x080A360D, autoepap_normalization_resume)
NSTUB(0x080A5B6F, autoepap_phase_reset_resume)
NSTUB(0x080A20F3, autoepap_leak_accept)
NSTUB(0x080A20D3, autoepap_leak_reject)
NSTUB(0x080AA793, autoepap_timing_measure)
NSTUB(0x080AA76F, autoepap_timing_target)
NSTUB(0x080AA9F9, autoepap_timing_cleanup)
NSTUB(0x080AA811, autoepap_timing_tail_resume)
NSTUB_VAR(0x200002EC, stock_flow_samples)
NSTUB(0x0806C9FB, g4_numeric_set_dynamic_min)
NSTUB(0x0806CA0D, g4_numeric_set_dynamic_max)

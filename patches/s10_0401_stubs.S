// SX567-0401 firmware function addresses

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
NSTUB(0x080824FF, front_panel_input_init)

// Stock ST breath timing and worker lifecycle
NSTUB(0x080A8239, breath_progress_worker_reset)
NSTUB(0x080A8265, breath_progress_worker_update_mode)
NSTUB(0x080A830F, breath_progress_worker_disable)
NSTUB(0x080A8315, breath_progress_worker_update)

// Stock bilevel and iVAPS pressure waveforms
NSTUB(0x080A0841, therapy_variable_get)
NSTUB(0x080B0571, bilevel_pressure_waveform_expiration_ramp)
NSTUB(0x080AC219, ivaps_pressure_waveform_expiration_ramp)
NSTUB_VAR(0x2000E798, therapy_waveform_profile)

// GUI / LCD
NSTUB(0x0807B5E5, GUI_SetColor)
NSTUB(0x0807B809, LCD_FillRect)
NSTUB(0x0807BB0F, LCD_SetClipRectMax)
NSTUB(0x0807B661, LCD_DrawPixel)

// Formatting / memory
NSTUB(0x0806D499, snprintf)
NSTUB(0x0806852D, memcpy_unrolled)
NSTUB(0x0806CF0D, strlen_fast)
NSTUB(0x080BDE09, sqrtf)
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
NSTUB_VAR(0x08099C18, font_large_standard)
NSTUB_VAR(0x0809798C, font_large_cjk)

// Header clock
NSTUB(0x08064713, gui_root_screen_init)
NSTUB(0x08064921, gui_root_screen_get)
NSTUB(0x08064777, gui_root_screen_layout_right_widgets)
NSTUB(0x0806A23B, gui_disp_string_at_utf8)
NSTUB(0x08074111, WM_InvalidateRect)

// Config persistence
NSTUB(0x0809E279, file_get_size)

NSTUB(0x080BC993, pressure_limit_max_difference)
NSTUB_VAR(0x2000E948, fvars)
NSTUB_VAR(0x2000E750, ivars)
NSTUB_VAR(0x2000E808, isNotBreathingPtr)
NSTUB_VAR(0x2000EA9C, breathPercentagePtr)
NSTUB(0x080E3465, asv_task_function)

NSTUB_VAR(0x20000BE0, magic_ptr)

// Variable system
NSTUB(0x08066E7E, variable_set_by_id)
NSTUB(0x08066FC6, variable_get_by_id)
NSTUB(0x080D9C1C, parse_hex_u16)

// Backlight adaptation
NSTUB(0x0807A2A4, backlight_state_machine)
NSTUB(0x0807A112, backlight_output_timeout_update)
NSTUB(0x0807A0A4, backlight_outputs_apply_state)
NSTUB(0x0806CFDA, millisecond_timer_init)
NSTUB(0x0806D002, millisecond_timer_expired)
NSTUB(0x080803D0, pwm_controller_init)
NSTUB(0x0808053A, pwm_controller_get)

// LCD driver
NSTUB(0x08080E37, lcd_write_cmd)
NSTUB(0x08080E3F, lcd_write_data)
NSTUB(0x08080F63, lcd_delay_ms)
NSTUB(0x080814E3, flexcolor_ensure_init)
NSTUB(0x080E2EF1, flexcolor_set_interface)
NSTUB(0x080E2F17, original_controller_init)
NSTUB(0x080D9287, original_hw_init)
NSTUB(0x0807BD29, original_board_init)
NSTUB(0x080D9171, flexcolor_draw_bitmap)
NSTUB(0x080D9093, flexcolor_fill_rect)
NSTUB(0x0808143B, flexcolor_draw_hline)
NSTUB(0x08081389, flexcolor_draw_vline)
NSTUB(0x080D8C03, flexcolor_cs_assert)
NSTUB(0x080D8C0D, flexcolor_write_data)
NSTUB(0x080875BB, iwdg_reload)
NSTUB(0x08080CDB, lcd_get_device)

// iVAPS AutoEPAP: stock workers and numerical primitives
NSTUB(0x080BDDD1, expf)
NSTUB(0x080BEFE1, iir_filter_order4_update)
NSTUB(0x080BF1A1, iir_filter_order4_reset)
NSTUB(0x080BDC13, tau_filter_update_weighted)
NSTUB(0x080A082B, therapy_variable_get_float)
NSTUB(0x080A0B63, therapy_manager_get)
NSTUB(0x080A07A9, therapy_worker_append)
NSTUB(0x080A0B61, therapy_worker_shutdown_noop)
NSTUB(0x08074EEF, system_tick_get)
NSTUB(0x080E3115, ivaps_settings_update)
NSTUB(0x080ABE75, therapy_mode67_pressure_waveform_worker_update)
NSTUB(0x080A5B15, breath_phase_adaptation_mode_update)
NSTUB(0x080A5C2D, breath_phase_adaptation_update)
NSTUB(0x080A7285, breath_transition_detector_update)
NSTUB(0x080AA509, ivaps_breath_timing_worker_mode_update)
NSTUB(0x080AA83D, ivaps_breath_timing_worker_update)
NSTUB(0x080AA68D, ivaps_breath_timing_update_targets)
NSTUB(0x080BF3B5, ring_buffer3_push)
NSTUB(0x080A0A47, therapy_feedback_item_phase1_init)
NSTUB(0x080A0A6F, therapy_manager_set_feedback_item)
NSTUB(0x080BE50D, linear_map_clamped_2point)
NSTUB(0x080BE541, linear_map_clamped_3point)
NSTUB(0x080BE5AD, linear_map_clamped_4point)
NSTUB(0x080AA76D, ivaps_breath_timing_stability_factor)
NSTUB(0x080A0E7F, therapy_fixed_vector_group1_ref_init)
NSTUB(0x080BE1BD, cyclic_counter_init)
NSTUB(0x080BE205, clamp_int_to_bounds)
NSTUB(0x080BFA75, ring_span_fixed_vector_init)
NSTUB(0x080BFB0D, asv_breath_shape_harmonic_projector_init)
NSTUB(0x080BFB5D, asv_breath_shape_project_first_segment)
NSTUB(0x080BFDD5, asv_breath_shape_project_second_segment)
NSTUB(0x080BF699, asv_breath_landmark_score_next)
NSTUB(0x080A4371, ivaps_ventilation_estimator_register)
NSTUB(0x080A4049, ivaps_ventilation_estimator_mode_update)
NSTUB(0x080A41C1, ivaps_ventilation_estimator_update)
NSTUB(0x080BDBE9, tau_filter_init_int)
NSTUB(0x080A377D, autoepap_normalization_resume)
NSTUB(0x080A5CDF, autoepap_phase_reset_resume)
NSTUB(0x080A22D7, autoepap_leak_accept)
NSTUB(0x080A22B7, autoepap_leak_reject)
NSTUB(0x080AA90B, autoepap_timing_measure)
NSTUB(0x080AA8E7, autoepap_timing_target)
NSTUB(0x080AAB71, autoepap_timing_cleanup)
NSTUB(0x080AA989, autoepap_timing_tail_resume)
NSTUB_VAR(0x200002EC, stock_flow_samples)
NSTUB(0x0806C9FF, g4_numeric_set_dynamic_min)
NSTUB(0x0806CA11, g4_numeric_set_dynamic_max)

// Air11 APPX 8.5.0 native function addresses.

#define NSTUB(addr, name) \
	.global name; \
	.type name, %function; \
	.thumb_set name, addr

.text

// Skip the native caller's r4 setup.
NSTUB(0x08071668, DataItem_get_var_id_virtual)
NSTUB(0x0806A988, DataItem_read_bytes_by_id)
NSTUB(0x0806A65C, DataItem_read_value_by_id)
NSTUB(0x0806A6FE, DataItem_set_visible_by_id)
NSTUB(0x0806A512, DataItem_write_raw_by_id)
NSTUB(0x0806AA20, DataItem_write_text_notify_by_id)
NSTUB(0x0813700A, memset)
NSTUB(0x08190FD2, AsvFeature_update)
NSTUB(0x08113AEE, FeedbackInput_get_ref)
NSTUB(0x08113AD8, FeedbackOutput_get_ref)
NSTUB(0x08063628, heap_alloc)
NSTUB(0x08146742, rpc_profile_json_formatter_registry_ctor)
NSTUB(0x08146FFC, rpc_profile_json_formatter_registration_ctor)
NSTUB(0x08146798, json_encoder_write_raw_span)
NSTUB(0x08068EE8, GuiTextValueFormatter_ctor)
NSTUB(0x08069048, GuiTextValueFormatter_dtor)
NSTUB(0x08068F00, GuiMenuTextValueListItem_ctor)
NSTUB(0x08069054, gui_menu_data_value_callback_ctor_empty)
NSTUB(0x080691D8, gui_menu_data_value_callback_dtor)
NSTUB(0x08069068, GuiMenuDataValueListItem_ctor)
NSTUB(0x08067C20, GuiScroller_ctor)
NSTUB(0x080717CA, GuiPaint_DrawLocalizedTextById)
NSTUB(0x08071786, GuiPaint_DrawStringInRect)
NSTUB(0x08062ECC, gui_localized_text_font_slot_for_id)
NSTUB(0x080797BA, datetime_current_local_milliseconds_of_day)
NSTUB(0x08063C24, user_interface_root_widget_ctor)
NSTUB(0x08063D10, user_interface_root_widget_status_blink_timer_callback_adjustor)
NSTUB(0x0806F18C, thunk_gui_timer_handle_reschedule_with_optional_delay)
NSTUB(0x080634F0, gui_owned_object_invalidate)
NSTUB(0x08082B96, touch_screen_controller_process_report)
NSTUB(0x08082D3A, touch_screen_controller_discard_all_reports)
NSTUB(0x0808CF7A, ring_buffer_free_count)
NSTUB(0x0808CFD8, ring_buffer_front_ptr)
NSTUB(0x0808CF14, ring_buffer_write_elements)
NSTUB(0x08092146, user_interface_process_touch_events)
NSTUB(0x080A0F84, led_status_controller_singleton)
NSTUB(0x080AFB1E, led_timeout_channel_slot_by_index)
NSTUB(0x080AF840, led_channel_schedule_transition)
NSTUB(0x080AFD4A, led_timeout_fade_channels_off)

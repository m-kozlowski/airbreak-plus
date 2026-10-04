// Air11 APPX 8.4.0 native function addresses.

#define NSTUB(addr, name) \
	.global name; \
	.type name, %function; \
	.thumb_set name, addr

.text

// Skip the native caller's r4 setup.
NSTUB(0x08071104, DataItem_get_var_id_virtual)
NSTUB(0x0806A7AC, DataItem_read_bytes_by_id)
NSTUB(0x0806A480, DataItem_read_value_by_id)
NSTUB(0x0806A522, DataItem_set_visible_by_id)
NSTUB(0x0806A336, DataItem_write_raw_by_id)
NSTUB(0x0806A844, DataItem_write_text_notify_by_id)
NSTUB(0x0813652A, memset)
NSTUB(0x0818EE9E, AsvFeature_update)
NSTUB(0x08112F92, FeedbackInput_get_ref)
NSTUB(0x08112F7C, FeedbackOutput_get_ref)
NSTUB(0x0806344C, heap_alloc)
NSTUB(0x0814E6B0, rpc_profile_json_formatter_registry_ctor)
NSTUB(0x0814ED66, rpc_profile_json_formatter_registration_ctor)
NSTUB(0x0814E700, json_encoder_write_raw_span)
NSTUB(0x08068D0C, GuiTextValueFormatter_ctor)
NSTUB(0x08068E6C, GuiTextValueFormatter_dtor)
NSTUB(0x08068D24, GuiMenuTextValueListItem_ctor)
NSTUB(0x08068E78, gui_menu_data_value_callback_ctor_empty)
NSTUB(0x08069000, gui_menu_data_value_callback_dtor)
NSTUB(0x08068E90, GuiMenuDataValueListItem_ctor)
NSTUB(0x08067A44, GuiScroller_ctor)
NSTUB(0x08071266, GuiPaint_DrawLocalizedTextById)
NSTUB(0x08071222, GuiPaint_DrawStringInRect)
NSTUB(0x08062CF0, gui_localized_text_font_slot_for_id)
NSTUB(0x080792BA, datetime_current_local_milliseconds_of_day)
NSTUB(0x08063A48, user_interface_root_widget_ctor)
NSTUB(0x08063B34, user_interface_root_widget_status_blink_timer_callback_adjustor)
NSTUB(0x0806EC28, thunk_gui_timer_handle_reschedule_with_optional_delay)
NSTUB(0x08063314, gui_owned_object_invalidate)
NSTUB(0x0808267E, touch_screen_controller_process_report)
NSTUB(0x08082822, touch_screen_controller_discard_all_reports)
NSTUB(0x0808CA3A, ring_buffer_free_count)
NSTUB(0x0808CA98, ring_buffer_front_ptr)
NSTUB(0x0808C9D4, ring_buffer_write_elements)
NSTUB(0x08091BD6, user_interface_process_touch_events)
NSTUB(0x080A0BF8, led_status_controller_singleton)
NSTUB(0x080AF62A, led_timeout_channel_slot_by_index)
NSTUB(0x080AF34C, led_channel_schedule_transition)
NSTUB(0x080AF856, led_timeout_fade_channels_off)

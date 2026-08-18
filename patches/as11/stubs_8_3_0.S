// Air11 APPX 8.3.0 native function addresses.

#define NSTUB(addr, name) \
	.global name; \
	.type name, %function; \
	.thumb_set name, addr

.text

NSTUB(0x0806F092, DataItem_get_var_id_virtual)
NSTUB(0x08068968, DataItem_read_value_by_id)
NSTUB(0x080689BA, DataItem_set_visible_by_id)
NSTUB(0x0806881E, DataItem_write_raw_by_id)
NSTUB(0x0818A63A, AsvFeature_update)
NSTUB(0x08110F5E, FeedbackInput_get_ref)
NSTUB(0x08110F48, FeedbackOutput_get_ref)
NSTUB(0x08061A60, heap_alloc)
NSTUB(0x0814BF70, rpc_profile_json_formatter_registry_ctor)
NSTUB(0x0814C626, rpc_profile_json_formatter_registration_ctor)
NSTUB(0x0814BFC0, json_encoder_write_raw_span)
NSTUB(0x08066998, GuiTextValueFormatter_ctor)
NSTUB(0x08066AF8, GuiTextValueFormatter_dtor)
NSTUB(0x080669B0, GuiMenuTextValueListItem_ctor)
NSTUB(0x08066CB0, GuiScroller_ctor)
NSTUB(0x0806F1F6, GuiPaint_DrawLocalizedTextById)
NSTUB(0x0806F1B2, GuiPaint_DrawStringInRect)
NSTUB(0x08061274, gui_localized_text_font_slot_for_id)
NSTUB(0x0807C4A6, datetime_current_local_milliseconds_of_day)
NSTUB(0x0806205C, user_interface_root_widget_ctor)
NSTUB(0x08062148, user_interface_root_widget_status_blink_timer_callback_adjustor)
NSTUB(0x0806CBB0, thunk_gui_timer_handle_reschedule_with_optional_delay)
NSTUB(0x08061928, gui_owned_object_invalidate)

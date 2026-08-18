// Air11 APPX 8.5.0 native function addresses.

#define NSTUB(addr, name) \
	.global name; \
	.type name, %function; \
	.thumb_set name, addr

.text

NSTUB(0x08071666, DataItem_get_var_id_virtual)
NSTUB(0x0806A65C, DataItem_read_value_by_id)
NSTUB(0x0806A6FE, DataItem_set_visible_by_id)
NSTUB(0x0806A512, DataItem_write_raw_by_id)
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
NSTUB(0x08067C20, GuiScroller_ctor)
NSTUB(0x080717CA, GuiPaint_DrawLocalizedTextById)
NSTUB(0x08071786, GuiPaint_DrawStringInRect)
NSTUB(0x08062ECC, gui_localized_text_font_slot_for_id)
NSTUB(0x080797BA, datetime_current_local_milliseconds_of_day)
NSTUB(0x08063C24, user_interface_root_widget_ctor)
NSTUB(0x08063D10, user_interface_root_widget_status_blink_timer_callback_adjustor)
NSTUB(0x0806F18C, thunk_gui_timer_handle_reschedule_with_optional_delay)
NSTUB(0x080634F0, gui_owned_object_invalidate)

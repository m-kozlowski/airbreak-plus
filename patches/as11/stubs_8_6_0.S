// Air11 APPX 8.6.0 native function addresses.

#define NSTUB(addr, name) \
	.global name; \
	.type name, %function; \
	.thumb_set name, addr

.text

NSTUB(0x08071CDA, DataItem_get_var_id_virtual)
NSTUB(0x0806AFC0, DataItem_read_bytes_by_id)
NSTUB(0x0806AC94, DataItem_read_value_by_id)
NSTUB(0x0806AD36, DataItem_set_visible_by_id)
NSTUB(0x0806AB4A, DataItem_write_raw_by_id)
NSTUB(0x0806B058, DataItem_write_text_notify_by_id)
NSTUB(0x081378E2, memset)
NSTUB(0x0819209E, AsvFeature_update)
NSTUB(0x0811434A, FeedbackInput_get_ref)
NSTUB(0x08114334, FeedbackOutput_get_ref)
NSTUB(0x08063B80, heap_alloc)
NSTUB(0x08146FFE, rpc_profile_json_formatter_registry_ctor)
NSTUB(0x081478B8, rpc_profile_json_formatter_registration_ctor)
NSTUB(0x08147054, json_encoder_write_raw_span)
NSTUB(0x08069524, GuiTextValueFormatter_ctor)
NSTUB(0x08069684, GuiTextValueFormatter_dtor)
NSTUB(0x0806953C, GuiMenuTextValueListItem_ctor)
NSTUB(0x08068180, GuiScroller_ctor)
NSTUB(0x08071E3E, GuiPaint_DrawLocalizedTextById)
NSTUB(0x08071DFA, GuiPaint_DrawStringInRect)
NSTUB(0x08063424, gui_localized_text_font_slot_for_id)
NSTUB(0x08079E22, datetime_current_local_milliseconds_of_day)
NSTUB(0x08064180, user_interface_root_widget_ctor)
NSTUB(0x0806426C, user_interface_root_widget_status_blink_timer_callback_adjustor)
NSTUB(0x0806F800, thunk_gui_timer_handle_reschedule_with_optional_delay)
NSTUB(0x08063A48, gui_owned_object_invalidate)

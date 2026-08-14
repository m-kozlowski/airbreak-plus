// Air11 APPX 8.0.1 native function addresses.

#define NSTUB(addr, name) \
	.global name; \
	.type name, %function; \
	.thumb_set name, addr

.text

NSTUB(0x0806E7DE, DataItem_get_var_id_virtual)
NSTUB(0x08068118, DataItem_read_value_by_id)
NSTUB(0x08067F8E, DataItem_write_raw_by_id)
NSTUB(0x0806E942, GuiPaint_DrawLocalizedTextById)
NSTUB(0x0806E8FE, GuiPaint_DrawStringInRect)
NSTUB(0x08060BB0, gui_localized_text_font_slot_for_id)
NSTUB(0x0807DA5A, datetime_current_local_milliseconds_of_day)
NSTUB(0x0806196A, user_interface_root_widget_ctor)
NSTUB(0x08061A54, user_interface_root_widget_status_blink_timer_callback_adjustor)
NSTUB(0x0806C2FC, thunk_gui_timer_handle_reschedule_with_optional_delay)
NSTUB(0x08061238, gui_owned_object_invalidate)

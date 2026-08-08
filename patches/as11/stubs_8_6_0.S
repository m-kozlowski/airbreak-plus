// Air11 APPX 8.6.0 native function addresses.

#define NSTUB(addr, name) \
	.global name; \
	.type name, %function; \
	.thumb_set name, addr

.text

NSTUB(0x08071CDA, DataItem_get_var_id_virtual)
NSTUB(0x0806AC94, DataItem_read_value_by_id)
NSTUB(0x0806AD36, DataItem_set_visible_by_id)
NSTUB(0x0806AB4A, DataItem_write_raw_by_id)
NSTUB(0x0819209E, AsvFeature_update)
NSTUB(0x0811434A, FeedbackInput_get_ref)
NSTUB(0x08114334, FeedbackOutput_get_ref)
NSTUB(0x08063B80, heap_alloc)
NSTUB(0x08069524, GuiTextValueFormatter_ctor)
NSTUB(0x08069684, GuiTextValueFormatter_dtor)
NSTUB(0x0806953C, GuiMenuTextValueListItem_ctor)
NSTUB(0x08068180, GuiScroller_ctor)

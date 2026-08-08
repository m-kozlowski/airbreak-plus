// Air11 APPX 8.4.0 native function addresses.

#define NSTUB(addr, name) \
	.global name; \
	.type name, %function; \
	.thumb_set name, addr

.text

NSTUB(0x08071102, DataItem_get_var_id_virtual)
NSTUB(0x0806A480, DataItem_read_value_by_id)
NSTUB(0x0806A522, DataItem_set_visible_by_id)
NSTUB(0x0806A336, DataItem_write_raw_by_id)
NSTUB(0x0818EE9E, AsvFeature_update)
NSTUB(0x08112F92, FeedbackInput_get_ref)
NSTUB(0x08112F7C, FeedbackOutput_get_ref)
NSTUB(0x0806344C, heap_alloc)
NSTUB(0x08068D0C, GuiTextValueFormatter_ctor)
NSTUB(0x08068E6C, GuiTextValueFormatter_dtor)
NSTUB(0x08068D24, GuiMenuTextValueListItem_ctor)
NSTUB(0x08067A44, GuiScroller_ctor)

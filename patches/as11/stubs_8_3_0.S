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
NSTUB(0x08066998, GuiTextValueFormatter_ctor)
NSTUB(0x08066AF8, GuiTextValueFormatter_dtor)
NSTUB(0x080669B0, GuiMenuTextValueListItem_ctor)
NSTUB(0x08066CB0, GuiScroller_ctor)

// Air11 APPX 8.5.0 native function addresses.

#define NSTUB(addr, name) \
	.global name; \
	.type name, %function; \
	name = addr

.text

NSTUB(0x08071666, DataItem_get_var_id_virtual)
NSTUB(0x0806A65C, DataItem_read_value_by_id)
NSTUB(0x0806A512, DataItem_write_raw_by_id)
NSTUB(0x08190FD2, AsvFeature_update)
NSTUB(0x08113AEE, FeedbackInput_get_ref)
NSTUB(0x08113AD8, FeedbackOutput_get_ref)

// Air11 APPX 8.0.1 native function addresses.

#define NSTUB(addr, name) \
	.global name; \
	.type name, %function; \
	.thumb_set name, addr

.text

NSTUB(0x0806E7DE, DataItem_get_var_id_virtual)
NSTUB(0x08068118, DataItem_read_value_by_id)
NSTUB(0x08067F8E, DataItem_write_raw_by_id)

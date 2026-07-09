// SX567-0302 firmware function addresses

#define NSTUB(addr,name) \
	.global name; \
	.type name, %function; \
	name = addr

.text

// Variable system
NSTUB(0x0806675A, variable_set_by_id)
NSTUB(0x080668A2, variable_get_by_id)

// VID spoof
NSTUB(0x08069DF4, vid_spoof_original_writeback)

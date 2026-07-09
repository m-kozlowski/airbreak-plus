// SX567-0305 firmware function addresses

#define NSTUB(addr,name) \
	.global name; \
	.type name, %function; \
	name = addr

.text

// Variable system
NSTUB(0x08066E7E, variable_set_by_id)
NSTUB(0x08066FC6, variable_get_by_id)

// VID spoof
NSTUB(0x0806A518, vid_spoof_original_writeback)

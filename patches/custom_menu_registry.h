#ifndef CUSTOM_MENU_REGISTRY_H
#define CUSTOM_MENU_REGISTRY_H

/* Shared binary format emitted by the patcher and consumed by firmware payloads. */
typedef struct {
	unsigned char container;
	unsigned char flags;
	unsigned short item_id;
	unsigned int mode_mask;
} custom_menu_entry_t;

#define CUSTOM_MENU_FLAG_G4_NUMERIC 0x01
#define CUSTOM_MENU_FLAG_HEADING    0x02
#define CUSTOM_MENU_FLAG_PAGE       0x04

#define CUSTOM_MENU_PAGE_CONTAINER_BASE 0x80
#define CUSTOM_MENU_REGISTRY_LIMIT      64

#endif

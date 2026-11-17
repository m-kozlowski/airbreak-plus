#ifndef CUSTOM_MENU_REGISTRY_H
#define CUSTOM_MENU_REGISTRY_H

/* Shared binary format emitted by the patcher and consumed by firmware payloads. */
typedef struct {
	unsigned char container;
	unsigned char flags;
	unsigned short item_id;
	unsigned int mode_mask;
} custom_menu_entry_t;

/* Return PC (Thumb bit cleared) selects before/after ranges in the registry.
 * An all-ones return_pc terminates this separate dispatch table.
 */
typedef struct {
	unsigned int return_pc;
	unsigned char before_first;
	unsigned char before_count;
	unsigned char after_first;
	unsigned char after_count;
} custom_menu_dispatch_t;

/* All conditions applicable to an item and the current MOP must hold. */
typedef struct {
	unsigned short item_id;
	unsigned short source_id;
	unsigned short mode_mask;
	/* Bit 0: the source must be nonzero (1) or zero (0). Bit 1: grey the row
	 * out (clear EDT) instead of hiding it when the condition fails.
	 */
	unsigned short nonzero;
} custom_menu_condition_t;

typedef struct {
	unsigned short source_id, target_id;
	int (*calculate)(int raw_value);
} custom_menu_preview_t;

/* write_id and binding_id use 0xffff for absent values. destination is 0 for
 * no navigation, 0xff for the default page, or 0x80+ for a generated page.
 * label_id is a firmware string ID.
 */
typedef struct {
	unsigned short write_id, label_id, binding_id;
	unsigned char destination, item;
	int value;
} custom_menu_action_t;

#define CUSTOM_MENU_FLAG_G4_NUMERIC 0x01
#define CUSTOM_MENU_FLAG_HEADING    0x02
#define CUSTOM_MENU_FLAG_PAGE       0x04
#define CUSTOM_MENU_FLAG_SHOW_UNITS 0x08
#define CUSTOM_MENU_FLAG_DECLARATION 0x10
#define CUSTOM_MENU_FLAG_ACTION      0x20
#define CUSTOM_MENU_FLAG_VIEW        0x40
#define CUSTOM_MENU_FLAG_PACKED_TIME 0x80
/* Page-only flag; numeric rows use this bit for SHOW_UNITS. */
#define CUSTOM_MENU_PAGE_NO_BACK     0x08
#define CUSTOM_MENU_NON_SETTING (CUSTOM_MENU_FLAG_PAGE | CUSTOM_MENU_FLAG_HEADING | \
                                CUSTOM_MENU_FLAG_ACTION | CUSTOM_MENU_FLAG_VIEW)

#define CUSTOM_MENU_MODE_BITS            0x00000fffu
#define CUSTOM_MENU_MODE_KEEP_VISIBILITY 0x80000000u

#define CUSTOM_MENU_PAGE_CONTAINER_BASE 0x80
#define CUSTOM_MENU_REGISTRY_LIMIT      64

#endif

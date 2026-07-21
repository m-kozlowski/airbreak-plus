"""Reviewed Air11 firmware-version metadata."""


AS11_OTA_DESCRIPTOR_PRESETS = {
    "14.8.3.0": {
        "desc2": 0x2D89E58F,
        "desc3": 0xBEB37EE2,
    },
    "15.8.4.0": {
        "desc2": 0xD785ABA6,
        "desc3": 0xBEB37EE2,
    },
    "16.8.5.0": {
        "desc2": 0x7862CBA7,
        "desc3": 0xBEB37EE2,
    },
}


AS11_PATCH_VERSIONS = {
    "8_0_1": {
        "mop_callback_dispatcher": {
            "writeback": 0x0806E070,
            "vtable_slot": 0x081925E8,
        },
    },
    "8_3_0": {
        "mop_callback_dispatcher": {
            "writeback": 0x0806E928,
            "vtable_slot": 0x0819EA20,
        },
        "custom_settings": {
            "menu": {
                "scroller_call": 0x0805AC68,
            },
            "reclaim": {
                "reminders": {
                    "row_index": 0x7E,
                    "row_call": (0x0805A9E4, 0x08067672),
                    "row_label": (0x0805A9E2, "bb21"),
                    "row_store": (0x0805A9EC, "cbf8f801"),
                    "scheduler_call": (0x0808E01C, 0x0809DBD4),
                },
            },
        },
        "asv_backup_rate": {
            "vtable_slot": 0x081A72D4,
            "label_id": 0x0097,
        },
    },
    "8_4_0": {
        "mop_callback_dispatcher": {
            "writeback": 0x08070998,
            "vtable_slot": 0x081A332C,
        },
        "custom_settings": {
            "menu": {
                "scroller_call": 0x0805E014,
            },
            "reclaim": {
                "reminders": {
                    "row_index": 0x82,
                    "row_call": (0x0805DD88, 0x080698D6),
                    "row_label": (0x0805DD84, "4ff49671"),
                    "row_store": (0x0805DD90, "cbf80802"),
                    "scheduler_call": (0x08091F7C, 0x080A0120),
                },
            },
        },
        "asv_backup_rate": {
            "vtable_slot": 0x081AC1F4,
            "label_id": 0x00EC,
        },
    },
    "8_5_0": {
        "mop_callback_dispatcher": {
            "writeback": 0x08070EFC,
            "vtable_slot": 0x081A52E0,
        },
        "custom_settings": {
            "menu": {
                # Final GuiScroller_ctor call in the clinical-settings
                # constructor; redirected through the menu bridge.
                "scroller_call": 0x0805E056,
            },
            "reclaim": {
                "reminders": {
                    # Stock Reminders row and scheduler consumers detached
                    # before their persistent settings are reclaimed.
                    "row_index": 0x81,
                    "row_call": (0x0805DDC2, 0x08069AAE),
                    "row_label": (0x0805DDBE, "40f23111"),
                    "row_store": (0x0805DDCA, "cbf80402"),
                    "scheduler_call": (0x080924EE, 0x080A06B8),
                },
            },
        },
        "asv_backup_rate": {
            "vtable_slot": 0x081AE044,
            "label_id": 0x00F1,
        },
    },
}

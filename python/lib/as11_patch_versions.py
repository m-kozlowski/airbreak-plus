"""Reviewed Air11 firmware-version metadata."""


AS11_OTA_COMPATIBILITY_FINGERPRINT_PRESETS = {
    "14.8.3.0": {
        "conf_appl_compatibility_fingerprint": 0x2D89E58F,
        "fgbl_appl_compatibility_fingerprint": 0xBEB37EE2,
    },
    "15.8.4.0": {
        "conf_appl_compatibility_fingerprint": 0xD785ABA6,
        "fgbl_appl_compatibility_fingerprint": 0xBEB37EE2,
    },
    "16.8.5.0": {
        "conf_appl_compatibility_fingerprint": 0x7862CBA7,
        "fgbl_appl_compatibility_fingerprint": 0xBEB37EE2,
    },
    "17.8.6.0": {
        "conf_appl_compatibility_fingerprint": 0xBECBC5BC,
        "fgbl_appl_compatibility_fingerprint": 0xBEB37EE2,
    },
}


# TODO: Integrate FGBL patch metadata with the version-maintenance workflow.
AS11_FGBL_PATCH_VERSIONS = {
    "1_1_0": {
        "selector_hook": 0x080009F6,
        "dispatch_hook_storage": 0x08009AB2,
    },
}


# A missing feature key means that the patch has not been ported to that APPX.
# An explicit None means that the patch does not apply to that APPX.
AS11_PATCH_VERSIONS = {
    "8_0_1": {
        "rpc_dispatcher": {
            "init_entry": 0x0817EE14,
        },
        "timezone_write": {
            "metadata_gate": {
                "address": 0x08198E24, "before": "e10f", "after": "0121",
            },
            "data_rule_gate": {
                "address": 0x081661D4, "before": "17ead47f", "after": "002f00bf",
            },
            "menu_warning_action": {
                "address": 0x0805A35C, "before": "06f045fd", "after": "00bf00bf",
            },
        },
        "mop_callback_dispatcher": {
            "writeback": 0x0806E070,
            "vtable_slot": 0x081925E8,
        },
        "header_clock": {
            "draw_call": 0x08061860,
            "root_ctor_call": 0x0807D4BC,
            "timer_callback_slot": 0x08197264,
            "home_text_id": 0x0070,
            "empty_text_id": 0x0068,
        },
    },
    "8_3_0": {
        "rpc_dispatcher": {
            "init_entry": 0x08189C6C,
        },
        "timezone_write": {
            "metadata_gate": {
                "address": 0x081A57D0, "before": "e10f", "after": "0121",
            },
            "data_rule_gate": {
                "address": 0x0816C14A, "before": "16ead47f", "after": "002e00bf",
            },
            "menu_warning_action": {
                "address": 0x0805AA62, "before": "06f038fd", "after": "00bf00bf",
            },
        },
        "mop_callback_dispatcher": {
            "writeback": 0x0806E928,
            "vtable_slot": 0x0819EA20,
        },
        "header_clock": {
            "draw_call": 0x08061F52,
            "menu_draw_call": 0x08066A7A,
            "root_ctor_call": 0x0809D554,
            "timer_callback_slot": 0x081A3AC0,
            "home_text_id": 0x0072,
            "empty_text_id": 0x006A,
            "menu_text_id": 0x00BB,
        },
        "custom_settings": {
            "rpc_enum_symbols": 0x08105318,
            "rpc_enum_symbol_count": 974,
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
        "rpc_dispatcher": {
            "init_entry": 0x0818E21C,
        },
        "timezone_write": {
            "metadata_gate": {
                "address": 0x081AA640, "before": "e10f", "after": "0121",
            },
            "data_rule_gate": {
                "address": 0x081691CE, "before": "16ead47f", "after": "002e00bf",
            },
            "menu_warning_action": {
                "address": 0x0805DE0A, "before": "05f048f8", "after": "00bf00bf",
            },
        },
        "mop_callback_dispatcher": {
            "writeback": 0x08070998,
            "vtable_slot": 0x081A332C,
        },
        "header_clock": {
            "draw_call": 0x0806393E,
            "menu_draw_call": 0x08068DEE,
            "root_ctor_call": 0x0809FA98,
            "timer_callback_slot": 0x081A8604,
            "home_text_id": 0x0075,
            "empty_text_id": 0x0068,
            "menu_text_id": 0x012C,
        },
        "custom_settings": {
            "rpc_enum_symbols": 0x081070A0,
            "rpc_enum_symbol_count": 1027,
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
        "rpc_dispatcher": {
            "init_entry": 0x08190614,
        },
        "timezone_write": {
            "metadata_gate": {
                "address": 0x081AC438, "before": "e10f", "after": "0121",
            },
            "data_rule_gate": {
                "address": 0x0815F720, "before": "17ead47f", "after": "002f00bf",
            },
            "menu_warning_action": {
                "address": 0x0805DE44, "before": "05f019f9", "after": "00bf00bf",
            },
        },
        "mop_callback_dispatcher": {
            "writeback": 0x08070EFC,
            "vtable_slot": 0x081A52E0,
        },
        "header_clock": {
            "draw_call": 0x08063B1A,
            "menu_draw_call": 0x08068FCA,
            "root_ctor_call": 0x080A001C,
            "timer_callback_slot": 0x081AA5C0,
            "home_text_id": 0x0078,
            "empty_text_id": 0x006A,
            "menu_text_id": 0x0131,
        },
        "custom_settings": {
            "rpc_enum_symbols": 0x08107BA8,
            "rpc_enum_symbol_count": 1032,
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
    "8_6_0": {
        "rpc_dispatcher": {
            "init_entry": 0x081916DC,
        },
        "timezone_write": {
            "metadata_gate": {
                "address": 0x081AD428, "before": "e10f", "after": "0121",
            },
            "data_rule_gate": {
                "address": 0x0815EA0C, "before": "17ead47f", "after": "002f00bf",
            },
            "menu_warning_action": {
                "address": 0x0805E374, "before": "05f02df9", "after": "00bf00bf",
            },
        },
        "mop_callback_dispatcher": {
            "writeback": 0x08071570,
            "vtable_slot": 0x081A6190,
        },
        "header_clock": {
            "draw_call": 0x08064076,
            "menu_draw_call": 0x08069606,
            "root_ctor_call": 0x080A0864,
            "timer_callback_slot": 0x081AB534,
            "home_text_id": 0x0078,
            "empty_text_id": 0x006A,
            "menu_text_id": 0x0131,
        },
        "custom_settings": {
            "rpc_enum_symbols": 0x08108398,
            "rpc_enum_symbol_count": 1041,
            "menu": {
                "scroller_call": 0x0805E586,
            },
            "reclaim": {
                "reminders": {
                    "row_index": 0x81,
                    "row_call": (0x0805E2F2, 0x0806A0EA),
                    "row_label": (0x0805E2EE, "40f23111"),
                    "row_store": (0x0805E2FA, "cbf80402"),
                    "scheduler_call": (0x08092D3A, 0x080A0EF8),
                },
            },
        },
        "asv_backup_rate": {
            "vtable_slot": 0x081AF034,
            "label_id": 0x00F1,
        },
    },
}

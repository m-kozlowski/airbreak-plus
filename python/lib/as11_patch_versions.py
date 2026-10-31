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
    "18.8.7.0": {
        "conf_appl_compatibility_fingerprint": 0x1B460250,
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
        "backlight": {
            "threshold_low": 0x0808A960,
            "threshold_high": 0x0808A968,
            "low": 0x0807E6AC,
            "high": 0x0807E6A8,
            "delay_ms": 0x0808A920,
        },
        "airplane_reminder": {
            "address": 0x0806F4F6,
            "before": "00f072f8",
            "after": "00bf00bf",
        },
        "scroll_animation": {
            "step_init": 0x08066488,
            "before": "ab6305f13c03",
        },
        "cloud_firmware_change": {
            "suppress_download": {
                "address": 0x080BAA26,
                "before": "18b9",
                "after": "00bf",
            },
            "suppress_apply": {
                "address": 0x080DAFA4,
                "before": "0322",
                "after": "0222",
            },
        },
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
            "home_page_store": 0x08056278,
            "single_pressure_page_store": 0x08056F04,
            "pressure_bar_page_store": 0x08057560,
            "page_array_base": 0x0806F2FC,
            "page_ids": (0, 6, 7),
            "home_text_id": 0x0070,
            "empty_text_id": 0x0068,
        },
    },
    "8_3_0": {
        "backlight": {
            "threshold_low": 0x080AD330,
            "threshold_high": 0x080AD338,
            "low": 0x0809E170,
            "high": 0x0809E16C,
            "delay_ms": 0x080AD2F0,
        },
        "airplane_reminder": {
            "address": 0x0808D87C,
            "before": "00f071f8",
            "after": "00bf00bf",
        },
        "scroll_animation": {
            "step_init": 0x08066D14,
            "before": "ab6305f13c03",
        },
        "cloud_firmware_change": {
            "suppress_download": {
                "address": 0x080BBD42,
                "before": "50b9",
                "after": "00bf",
            },
            "suppress_apply": {
                "address": 0x080DE780,
                "before": "0322",
                "after": "0222",
            },
        },
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
            "home_page_store": 0x08056780,
            "single_pressure_page_store": 0x08057158,
            "pressure_bar_page_store": 0x080577EA,
            "page_array_base": 0x080AC6AA,
            "page_ids": (0, 2, 3),
            "home_text_id": 0x0072,
            "empty_text_id": 0x006A,
            "menu_text_id": 0x00BB,
        },
        "custom_settings": {
            "rpc_enum_symbols": 0x08105318,
            "rpc_enum_symbol_count": 974,
            "gui_enum_count_pointer": 0x08073A5C,
            "gui_enum_table_pointer": 0x08073A60,
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
        "backlight": {
            "threshold_low": 0x080AF97A,
            "threshold_high": 0x080AF982,
            "low": 0x080A06BC,
            "high": 0x080A06B8,
            "delay_ms": 0x080AF928,
        },
        "airplane_reminder": {
            "address": 0x0809176A,
            "before": "00f076f8",
            "after": "00bf00bf",
        },
        "scroll_animation": {
            "step_init": 0x08067AA8,
            "before": "29640121ab63",
        },
        "cloud_firmware_change": {
            "suppress_download": {
                "address": 0x080BE24A,
                "before": "50b9",
                "after": "00bf",
            },
            "suppress_apply": {
                "address": 0x080E0E18,
                "before": "0322",
                "after": "0222",
            },
        },
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
            "home_page_store": 0x08059806,
            "single_pressure_page_store": 0x0805A21A,
            "pressure_bar_page_store": 0x0805A8D4,
            "page_array_base": 0x080AECC2,
            "page_ids": (0, 2, 3),
            "home_text_id": 0x0075,
            "empty_text_id": 0x0068,
            "menu_text_id": 0x012C,
        },
        "therapy_screen_style": {
            "label_id": 0x00AF,
            "option_labels": (0x01F4, 0x0099, 0x0208),
        },
        "custom_settings": {
            "rpc_enum_symbols": 0x081070A0,
            "rpc_enum_symbol_count": 1027,
            "gui_enum_count_pointer": 0x080761A0,
            "gui_enum_table_pointer": 0x080761A4,
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
        "screen_keep_awake": {
            "touch_report_vtable_slot": 0x081A98B4,
            "process_touch_events_call": 0x08091E9C,
            "fade_transition_call": 0x080AF884,
            "target_intensity_call": 0x080AF2D4,
            "runtime_state_init": {
                "address": 0x080AF2B0,
                "before": "84f86800",
                "after": "c4f86800",
            },
        },
    },
    "8_5_0": {
        "backlight": {
            "threshold_low": 0x080AFE6E,
            "threshold_high": 0x080AFE76,
            "low": 0x080A0A2C,
            "high": 0x080A0A28,
            "delay_ms": 0x080AFE1C,
        },
        "airplane_reminder": {
            "address": 0x08091CD0,
            "before": "00f07bf8",
            "after": "00bf00bf",
        },
        "scroll_animation": {
            "step_init": 0x08067C84,
            "before": "29640121ab63",
        },
        "cloud_firmware_change": {
            "suppress_download": {
                "address": 0x080BEA86,
                "before": "50b9",
                "after": "00bf",
            },
            "suppress_apply": {
                "address": 0x080E16C8,
                "before": "0322",
                "after": "0222",
            },
        },
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
            "home_page_store": 0x0805986C,
            "single_pressure_page_store": 0x0805A28A,
            "pressure_bar_page_store": 0x0805A944,
            "page_array_base": 0x080AF50E,
            "page_ids": (0, 2, 3),
            "home_text_id": 0x0078,
            "empty_text_id": 0x006A,
            "menu_text_id": 0x0131,
        },
        "therapy_screen_style": {
            "label_id": 0x00B4,
            "option_labels": (0x01FA, 0x009C, 0x020E),
        },
        "custom_settings": {
            "rpc_enum_symbols": 0x08107BA8,
            "rpc_enum_symbol_count": 1032,
            # Literal-pool slots read by the GUI enum-label resolver.
            "gui_enum_count_pointer": 0x0807667C,
            "gui_enum_table_pointer": 0x08076680,
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
        "screen_keep_awake": {
            "touch_report_vtable_slot": 0x081AB718,
            "process_touch_events_call": 0x08092406,
            "fade_transition_call": 0x080AFD78,
            "target_intensity_call": 0x080AF7C8,
            "runtime_state_init": {
                "address": 0x080AF7A4,
                "before": "84f86800",
                "after": "c4f86800",
            },
        },
    },
    "8_6_0": {
        "backlight": {
            "threshold_low": 0x080B06D2,
            "threshold_high": 0x080B06DA,
            "low": 0x080A1268,
            "high": 0x080A1264,
            "delay_ms": 0x080B0680,
        },
        "airplane_reminder": {
            "address": 0x08092520,
            "before": "00f079f8",
            "after": "00bf00bf",
        },
        "scroll_animation": {
            "step_init": 0x080681E4,
            "before": "29640121ab63",
        },
        "ble_oxi_fallback": {
            # OXI main interface and its self+8 connect/disconnect interface.
            "ble_oxi_gatt_client_on_stack_event": 0x081AEF18,
            "ble_oxi_gatt_client_queue_connect": 0x081AEF24,
            "ble_oxi_gatt_client_request_disconnect": 0x081AEF28,
            "thunk_ble_oxi_gatt_client_queue_connect": 0x081AEF44,
            "this_adjustor_ble_oxi_gatt_client_request_disconnect": 0x081AEF48,
        },
        "cellular_download": {
            "task_pointer_slot": 0x3000B070,
            "can_start_vtable_slot": 0x081C62E4,
            "set_state_prologue": "73b50446",
        },
        "cloud_firmware_change": {
            "suppress_download": {
                "address": 0x080BF266,
                "before": "50b9",
                "after": "00bf",
            },
            "suppress_apply": {
                "address": 0x080E1E00,
                "before": "0322",
                "after": "0222",
            },
        },
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
            "home_page_store": 0x08059D9C,
            "single_pressure_page_store": 0x0805A7BA,
            "pressure_bar_page_store": 0x0805AE74,
            "page_array_base": 0x080AFD72,
            "page_ids": (0, 2, 3),
            "home_text_id": 0x0078,
            "empty_text_id": 0x006A,
            "menu_text_id": 0x0131,
        },
        "therapy_screen_style": {
            "label_id": 0x00B4,
            "option_labels": (0x01FB, 0x009C, 0x020F),
        },
        "custom_settings": {
            "rpc_enum_symbols": 0x08108398,
            "rpc_enum_symbol_count": 1041,
            "gui_enum_count_pointer": 0x08076CE8,
            "gui_enum_table_pointer": 0x08076CEC,
            "menu": {
                "scroller_call": 0x0805E586,
            },
            "reclaim": {
                "reminders": {
                    "row_index": 0x81,
                    "row_call": (0x0805E2F2, 0x0806A0EA),
                    "row_label": (0x0805E2EE, "40f23111"),
                    "row_store": (0x0805E2FA, "cbf80402"),
                    "row_build_start": 0x0805E2C2,
                    "row_build_end": 0x0805E2FE,
                    "scheduler_call": (0x08092D3A, 0x080A0EF8),
                },
            },
        },
        "asv_backup_rate": {
            "vtable_slot": 0x081AF034,
            "label_id": 0x00F1,
        },
        "flow_wave": {
            "gui_update_call": 0x08092D6C,
            "page_build_start": 0x08062DEE,
            "page_build_end": 0x0806301A,
            "page_store": 0x08063016,
            "tss_switch_pointer": 0x08059208,
            "therapy_page_state_call": 0x080AFD4C,
            "therapy_page_policy_call": 0x080A1D2C,
        },
        "screen_keep_awake": {
            "touch_report_vtable_slot": 0x081AC774,
            "process_touch_events_call": 0x08092C52,
            "fade_transition_call": 0x080B05DC,
            "target_intensity_call": 0x080B002C,
            "runtime_state_init": {
                "address": 0x080B0008,
                "before": "84f86800",
                "after": "c4f86800",
            },
        },
    },
    "8_7_0": {
        "backlight": {
            "threshold_low": 0x080B1856,
            "threshold_high": 0x080B185E,
            "low": 0x080A1E34,
            "high": 0x080A1E30,
            "delay_ms": 0x080B1804,
        },
        "airplane_reminder": {
            "address": 0x08093050,
            "before": "00f079f8",
            "after": "00bf00bf",
        },
        "cellular_download": {
            "task_pointer_slot": 0x3000AF38,
            "can_start_vtable_slot": 0x081C9794,
            "set_state_prologue": "73b50446",
        },
        "ble_oxi_fallback": {
            "ble_oxi_gatt_client_on_stack_event": 0x081B184C,
            "ble_oxi_gatt_client_queue_connect": 0x081B1858,
            "ble_oxi_gatt_client_request_disconnect": 0x081B185C,
            "thunk_ble_oxi_gatt_client_queue_connect": 0x081B1878,
            "this_adjustor_ble_oxi_gatt_client_request_disconnect": 0x081B187C,
        },
        "cloud_firmware_change": {
            "suppress_download": {
                "address": 0x080C0476,
                "before": "80b9",
                "after": "00bf",
            },
            "suppress_apply": {
                "address": 0x080E3140,
                "before": "0322",
                "after": "0222",
            },
        },
        "rpc_dispatcher": {
            "init_entry": 0x08194100,
        },
        "mop_callback_dispatcher": {
            "writeback": 0x08071E3C,
            "vtable_slot": 0x081A926C,
        },
        "timezone_write": {
            "metadata_gate": {
                "address": 0x081B05B0,
                "before": "e10f",
                "after": "0121",
            },
            "data_rule_gate": {
                "address": 0x08160272,
                "before": "16ead47f",
                "after": "002e00bf",
            },
            "menu_warning_action": {
                "address": 0x0805E8B6,
                "before": "05f034f9",
                "after": "00bf00bf",
            },
        },
        "screen_keep_awake": {
            "touch_report_vtable_slot": 0x081AF890,
            "process_touch_events_call": 0x0809378C,
            "fade_transition_call": 0x080B1760,
            "target_intensity_call": 0x080B11B0,
            "runtime_state_init": {
                "address": 0x080B118C,
                "before": "84f86800",
                "after": "c4f86800",
            },
        },
        "scroll_animation": {
            "step_init": 0x08068808,
            "before": "29640121ab63",
        },
        "header_clock": {
            "draw_call": 0x080645C6,
            "menu_draw_call": 0x08069C5E,
            "root_ctor_call": 0x080A1434,
            "timer_callback_slot": 0x081AE568,
            "home_page_store": 0x0805A2B0,
            "single_pressure_page_store": 0x0805ACCE,
            "pressure_bar_page_store": 0x0805B388,
            "page_array_base": 0x080B0EF6,
            "page_ids": (1, 3, 4),
            "home_text_id": 0x0079,
            "empty_text_id": 0x006B,
            "menu_text_id": 0x0133,
        },
        "custom_settings": {
            "gui_enum_count_pointer": 0x08077598,
            "gui_enum_table_pointer": 0x0807759C,
            "rpc_enum_symbols": 0x08109A2C,
            "rpc_enum_symbol_count": 1051,
            "menu": {
                "scroller_call": 0x0805EACC,
            },
            "reclaim": {
                "reminders": {
                    "row_index": 0x81,
                    "row_call": (0x0805E836, 0x0806A746),
                    "row_label": (0x0805E832, "40f23311"),
                    "row_store": (0x0805E83E, "cbf80402"),
                    # Omit both navigation-action and menu-row allocations.
                    "row_build_start": 0x0805E806,
                    "row_build_end": 0x0805E842,
                    "scheduler_call": (0x08093874, 0x080A1AC4),
                },
            },
        },
        "asv_backup_rate": {
            "vtable_slot": 0x081B222C,
            "label_id": 0x00F3,
        },
        "therapy_screen_style": {
            "label_id": 0x00B5,
            "option_labels": (0x01FE, 0x009D, 0x0212),
        },
        "flow_wave": {
            "gui_update_call": 0x080938A6,
            # Replace construction of the Reminders page and all its children.
            "page_build_start": 0x0806333E,
            "page_build_end": 0x0806356A,
            "page_store": 0x08063566,
            "tss_switch_pointer": 0x080596F4,
            # Native therapy-page classification: state publication and UI policy.
            "therapy_page_state_call": 0x080B0ED0,
            "therapy_page_policy_call": 0x080A28F4,
        },
    },
}

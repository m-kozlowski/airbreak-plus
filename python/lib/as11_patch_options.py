"""Air11 patch options."""

import argparse
import re

from .patch_options import ALL_PATCHES, Parameter, Patch, Phase, Platform, Value, str2bool


RPC_DATAITEM_PERMISSION_FLAGS = frozenset(("RPC", "RPW"))


def parse_u16(value):
    try:
        out = int(value, 0)
    except ValueError:
        raise argparse.ArgumentTypeError("expected integer or hex value") from None
    if out < 0 or out > 0xFFFF:
        raise argparse.ArgumentTypeError("expected 16-bit value")
    return out


def parse_rpc_permission(value):
    parts = [part.strip() for part in value.split(":")]
    if len(parts) != 3 or not parts[0]:
        raise argparse.ArgumentTypeError(
            "expected METHOD:VCID:BOOL or DATAITEM:FLAG:BOOL"
        )
    target, selector, enabled_text = parts
    try:
        enabled = str2bool(enabled_text)
    except argparse.ArgumentTypeError as exc:
        raise argparse.ArgumentTypeError(
            "invalid RPC permission %r: %s" % (value, exc)
        ) from None

    flag = selector.upper()
    if flag in RPC_DATAITEM_PERMISSION_FLAGS:
        if re.fullmatch(r"(?:0[xX][0-9a-fA-F]+|[0-9]+)", target):
            target = parse_u16(target)
        return "dataitem", target, flag, enabled

    try:
        vcid = parse_u16(selector)
    except argparse.ArgumentTypeError:
        raise argparse.ArgumentTypeError(
            "invalid RPC permission %r: selector must be a VCID, RPC, or RPW" %
            value
        ) from None
    return "method", target, vcid, enabled


def format_rpc_permission(rule):
    kind, target, selector, enabled = rule
    if isinstance(target, int):
        target = "0x%04X" % target
    if kind == "method":
        selector = "0x%04X" % selector
    return "%s:%s:%d" % (target, selector, enabled)


PLATFORM = Platform("air11", categories=(
    "Therapy unlocks",
    "Therapy modifications",
    "Therapy data and reporting",
    "Connectivity and control",
    "Quality of life",
    "Miscellaneous",
), phases=(
    Phase("Patches", (
        Patch("patch-unlock-features",
              "Unlock all therapy modes and make their settings available in the clinical menu",
              True, "unlock_features", category="Therapy unlocks"),
        Patch("patch-asv-ps-range", "Unlock ASV/ASVAuto pressure support range",
              True, "asv_pressure_support_range", category="Therapy unlocks"),
        Patch("patch-asv-backup-rate", "Add backup-rate switch in ASV, ASVAuto",
              True, "asv_backup_rate", category="Therapy modifications"),
        Patch("patch-custom-settings", "Add menu settings for the patches that need them",
              True, "enable_custom_settings", category="Therapy modifications"),
        Patch("patch-therapy-screen",
              "Show additional respiratory statistics on the Therapy Screen",
              True, "therapy_screen", category="Therapy modifications"),
        Patch("patch-therapy-screen-style", "Add Therapy View: choose the therapy screen layout",
              True, "therapy_screen_style", category="Therapy modifications"),
        Patch("patch-flow-wave", "Show flow and pressure graphs in the Flow therapy view",
              False, "flow_wave", category="Therapy modifications",
              requires=("patch-custom-settings",)),
        Patch("patch-edf-superset", "Record all available signals to the SD card in every therapy mode",
              True, "patch_edf_superset", category="Therapy data and reporting"),
        Patch("patch-vid-spoof",
              "Report a device variant that matches the therapy mode, so myAir accepts the data",
              True, "vid_spoof", category="Therapy data and reporting"),
        Patch("patch-rpc-json-profile-visibility",
              "Expose supported therapy/feature profile nodes in RPC JSON",
              True, "rpc_json_profile_visibility", category="Connectivity and control"),
        Patch("patch-rpc-permissions", "Apply configured RPC method and DataItem permissions",
              True, "rpc_permissions", category="Connectivity and control", parameters=(
                  Parameter("rpc-permission",
                            "Set METHOD:VCID or DATAITEM:RPC|RPW permission; repeatable. "
                            "Overrides the built-in rule for the same pair.",
                            Value(parse_rpc_permission, "TARGET:VCID|FLAG:BOOL", repeat=True,
                                  format=format_rpc_permission)),
              )),
        Patch("patch-timezone-write", "Allow changing the time zone without erasing therapy data",
              True, "timezone_write", category="Connectivity and control"),
        Patch("patch-ble-oxi-fallback",
              "Work around pairing and measurement incompatibilities in Bluetooth PLX pulse oximeters "
              "(experimental)",
              False, "ble_oxi_fallback", category="Connectivity and control"),
        Patch("patch-cloud-firmware-change",
              "Don't install firmware updates from the cellular service; keep their details",
              False, "cloud_firmware_change", category="Connectivity and control", parameters=(
                  Parameter("cloud-firmware-change-mode",
                            "Behavior of patch-cloud-firmware-change: metadata keeps only the update "
                            "details; stage also downloads and verifies the file without installing it. "
                            "Default: metadata.",
                            Value(choices=("metadata", "stage")), "metadata"),
              )),
        Patch("patch-cellular-download",
              "Add a command that downloads a file from a URL over the cellular modem",
              False, "cellular_download", category="Connectivity and control"),
        Patch("patch-defaults", "Change factory defaults",
              True, "patch_defaults", category="Quality of life"),
        Patch("patch-unlock-languages", "Unlock all languages in the firmware",
              True, "unlock_languages", category="Quality of life"),
        Patch("patch-header-clock", "Show local time and usage time in the header during therapy",
              True, "header_clock", category="Quality of life", parameters=(
                  Parameter("header-clock-usage",
                            "Usage time shown: PPD since the last noon (default), "
                            "PUD for the current mask-on period.",
                            Value(str.upper, choices=("PPD", "PUD")), "PPD"),
              )),
        Patch("patch-screen-keep-awake", "Toggle screen inactivity timeout with a three-finger hold",
              True, "screen_keep_awake", category="Quality of life"),
        Patch("patch-backlight",
              "Set ambient-light thresholds, LCD brightness levels, and response delay",
              False, "backlight", category="Quality of life", parameters=(
                  Parameter("backlight-threshold-low",
                            "Dim mode below this AmbientLight value, 0..255. Default: 10.",
                            Value(int, "VALUE"), 10),
                  Parameter("backlight-threshold-high",
                            "Bright mode at or above this AmbientLight value, 0..255. Default: 19.",
                            Value(int, "VALUE"), 19),
                  Parameter("backlight-low",
                            "Screen brightness in dim light, 0..100%, not above --backlight-high. "
                            "Default: 20.",
                            Value(int, "PERCENT"), 20),
                  Parameter("backlight-high", "Screen brightness in bright light, 0..100%. Default: 100.",
                            Value(int, "PERCENT"), 100),
                  Parameter("backlight-delay-ms", "Ambient-mode change delay, 0..65534 ms. Default: 3000.",
                            Value(int, "MS"), 3000),
              )),
        Patch("patch-startup-logo", "Choose the logo shown at startup",
              False, "startup_logo", category="Quality of life", parameters=(
                  Parameter("startup-logo",
                            "Startup logo: 0 Off, 1 AirSense 11, 2 AirCurve 11, 3 Lumis 11, "
                            "4 ResMed. Default: 4.",
                            Value(int, choices=range(5)), 4),
              )),
        Patch("patch-scroll-animation", "Scroll menus faster",
              False, "scroll_animation", category="Quality of life"),
        Patch("patch-sensitivity-split-screen", "Show a picture next to the Trigger and Cycle choices",
              False, "sensitivity_split_screen", category="Quality of life"),
        Patch("patch-airplane-reminder", "Suppress the standby airplane-mode reminder",
              True, "airplane_reminder", category="Quality of life"),
        Patch("patch-motor-nagscreen",
              "Remove the \"Your device has reached its design life\" nag screen",
              True, "motor_nagscreen", category="Quality of life"),
        Patch("patch-fgbl-service", "Add bootloader support for firmware dump and restore over CAN",
              True, "patch_fgbl_service", category="Miscellaneous"),
        Patch("patch-airbreak-info",
              "Report Airbreak version and applied patch metadata through RPC Get",
              True, "enable_airbreak_info", category="Miscellaneous"),
    )),
), parameters=(ALL_PATCHES,))

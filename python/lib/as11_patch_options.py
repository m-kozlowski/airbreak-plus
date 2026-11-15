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


PLATFORM = Platform("air11", phases=(
    Phase("Patches", (
        Patch("patch-airbreak-info",
              "Expose Airbreak version and applied patch metadata through RPC Get.",
              True, "enable_airbreak_info"),
        Patch("patch-fgbl-service", "Add bootloader support for firmware dump and restore over CAN.",
              True, "patch_fgbl_service"),
        Patch("patch-unlock-features",
              "Unlock supported therapy modes, related settings, and GUI editability.",
              True, "unlock_features"),
        Patch("patch-unlock-languages", "Unlock all configured language choices.",
              True, "unlock_languages"),
        Patch("patch-defaults", "Patch firmware defaults for selected settings.",
              True, "patch_defaults"),
        Patch("patch-rpc-json-profile-visibility",
              "Expose supported therapy/feature profile nodes in RPC JSON.",
              True, "rpc_json_profile_visibility"),
        Patch("patch-edf-superset", "Expose the official S11 EDF schema superset.",
              True, "patch_edf_superset"),
        Patch("patch-asv-ps-range", "Unlock ASV/ASVAuto pressure support range.",
              True, "asv_pressure_support_range"),
        Patch("patch-therapy-screen",
              "Show additional respiratory statistics in compatible therapy modes.",
              True, "therapy_screen"),
        Patch("patch-therapy-screen-style", "Enable persistent therapy-screen style selection.",
              True, "therapy_screen_style"),
        Patch("patch-header-clock", "Show local time and usage time in the header during therapy.",
              True, "header_clock", parameters=(
                  Parameter("header-clock-usage",
                            "Usage shown during therapy: PPD for the therapy day (default), "
                            "PUD for the current mask-on interval.",
                            Value(str.upper, choices=("PPD", "PUD")), "PPD"),
              )),
        Patch("patch-custom-settings", "Expose settings requested by active feature patches.",
              True, "enable_custom_settings"),
        Patch("patch-flow-wave", "Show live flow and pressure waveforms in the Flow therapy view.",
              False, "flow_wave"),
        Patch("patch-screen-keep-awake", "Toggle LCD inactivity suppression with a three-finger hold.",
              True, "screen_keep_awake"),
        Patch("patch-backlight",
              "Set ambient-light thresholds, LCD brightness levels, and response delay.",
              False, "backlight", parameters=(
                  Parameter("backlight-threshold-low",
                            "Dim mode below this AmbientLight value, 0..255. Default: 10.",
                            Value(int, "VALUE"), 10),
                  Parameter("backlight-threshold-high",
                            "Bright mode at or above this AmbientLight value, 0..255. Default: 19.",
                            Value(int, "VALUE"), 19),
                  Parameter("backlight-low",
                            "Dim LCD brightness, 0..100, no higher than --backlight-high. Default: 20.",
                            Value(int, "PERCENT"), 20),
                  Parameter("backlight-high", "Bright LCD brightness, 0..100. Default: 100.",
                            Value(int, "PERCENT"), 100),
                  Parameter("backlight-delay-ms", "Ambient-mode change delay, 0..65534 ms. Default: 3000.",
                            Value(int, "MS"), 3000),
              )),
        Patch("patch-scroll-animation",
              "Shorten menu scrolling with a 1.5x step at the native timer interval.",
              False, "scroll_animation"),
        Patch("patch-startup-logo", "Replace the startup logo with --startup-logo.",
              False, "startup_logo", parameters=(
                  Parameter("startup-logo",
                            "Startup logo: 0 Off, 1 AirSense 11, 2 AirCurve 11, 3 Lumis 11, "
                            "4 ResMed. Default: 4.",
                            Value(int, choices=range(5)), 4),
              )),
        Patch("patch-sensitivity-split-screen",
              "Show graphics beside supported Trigger/Cycle sensitivity selectors.",
              False, "sensitivity_split_screen"),
        Patch("patch-asv-backup-rate", "Add ASV/ASVAuto backup-rate suppression and control.",
              True, "asv_backup_rate"),
        Patch("patch-airplane-reminder", "Suppress the standby airplane-mode reminder.",
              True, "airplane_reminder"),
        Patch("patch-motor-nagscreen", "Remove \"Motor life exceeded\" nag screen.",
              True, "motor_nagscreen"),
        Patch("patch-rpc-permissions", "Apply configured RPC method and DataItem permissions.",
              True, "rpc_permissions", parameters=(
                  Parameter("rpc-permission",
                            "Set METHOD:VCID or DATAITEM:RPC|RPW permission; repeatable. "
                            "Overrides the built-in rule for the same pair.",
                            Value(parse_rpc_permission, "TARGET:VCID|FLAG:BOOL", repeat=True,
                                  format=format_rpc_permission)),
              )),
        Patch("patch-cloud-firmware-change",
              "Retain cloud flow-generator firmware changes without applying them.",
              False, "cloud_firmware_change", parameters=(
                  Parameter("cloud-firmware-change-mode",
                            "Behavior of patch-cloud-firmware-change: retain download "
                            "metadata only, or stage and verify the file without applying it. "
                            "Default: metadata.",
                            Value(choices=("metadata", "stage")), "metadata"),
              )),
        Patch("patch-cellular-download",
              "Download an HTTP resource to upgrade storage through the cellular modem.",
              False, "cellular_download"),
        Patch("patch-ble-oxi-fallback",
              "Work around pairing and measurement-status incompatibilities in Bluetooth PLX "
              "pulse oximeters (experimental).",
              False, "ble_oxi_fallback"),
        Patch("patch-timezone-write", "Allow time-zone changes after summary history exists.",
              True, "timezone_write"),
        Patch("patch-vid-spoof", "Install runtime MOP-based software variant spoofing.",
              True, "vid_spoof"),
    )),
), parameters=(ALL_PATCHES,))

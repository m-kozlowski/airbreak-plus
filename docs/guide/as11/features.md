# Air11 Standard Patch Features

The standard Air11 image includes the features below, except those marked
optional. See [Patching](patching.md#selecting-patches) to change the selection.

## Supported Therapy Modes

The mode and clinical-setting patch exposes:

- CPAP
- AutoSet
- AutoSet for Her
- S
- ST
- T
- VAuto
- ASV
- ASVAuto
- iVAPS
- PAC

Mode-specific pressure, timing, trigger, cycle, and comfort settings are made
editable where the firmware provides a supported setting path.

## Therapy Screen

The therapy-screen patch adds leak, minute ventilation, respiratory rate,
tidal volume, and I:E ratio to the CPAP, AutoSet, and AutoSet for Her therapy
screens. It also adds inspiratory time to ASV and ASVAuto.

The separate `therapy-screen-style patch` adds `Therapy View` under Configuration,
with `Simple`, `Pressure`, and `Flow` choices.

With the optional FlowWave patch, `Flow` shows the last 12 seconds of breathing
flow and mask pressure, with the current pressure in the upper-left corner.
The graph makes room when you expand the statistics. This patch requires
custom settings and replaces Reminders.
Without FlowWave, selecting `Flow` displays the Simple screen.

## ASV Pressure-Support Range

The ASV range patch removes the stock 5 cmH2O minimum separation between
minimum and maximum pressure support in ASV and ASVAuto. Descriptor bounds and
the paired range-selector calculation are patched together.

## ASV Backup Rate

The ASV backup-rate patch adds a persistent `Backup Rate` control to the
clinical therapy settings in ASV and ASVAuto. `On` preserves stock behavior
and `Off` suppresses backup breaths. The default is `On`.

Without the custom-settings patch, backup breaths are disabled without a menu
control.

## Header Clock

The home screen header shows local time. During therapy, the header shows
local time and usage time side by side.

Usage time is the total hours and minutes of mask use since the last local
noon, including earlier sessions. Build with `--header-clock-usage PUD` to
show only the current mask-on interval.

To enable the feature, turn on `Clock` under Configuration in the clinical
menu. The default is `Off`. Without the custom-settings patch, the feature
is always enabled.

## Startup Logo (Optional)

Choose the startup logo when building the image: AirSense 11, AirCurve 11,
Lumis 11, ResMed, or none. The first startup after flashing can still show the
previous logo; the next startup uses the new selection. If splash-screen
display has been disabled on the device, it remains disabled.

## Sensitivity Split Screen (Optional)

Adds a graphic beside the choice list when editing Trigger or Cycle in the
clinical therapy settings. Trigger uses this layout in CPAP, S, ST, iVAPS,
and PAC; Cycle in S, ST, and iVAPS. VAuto keeps its existing editors.
The patch changes presentation, not sensitivity values or therapy behavior.

## Custom Settings

The custom-settings patch adds the `Backup Rate` and `Clock` menu controls
used by the corresponding patches, and the `Therapy View` selector. Their
values are saved across restarts. Backup Rate and Clock replace the stock
Reminders feature; Therapy View preserves it when used on its own.

## Languages and Defaults

The language patch enables the configured language set. The default patch
changes firmware defaults for selected patient and device settings, including
patient access to ramp and pressure relief.

Persisted settings can take precedence over firmware defaults on an existing
device. A default patch is not a command to overwrite every current setting.

## Remote Access

The remote-access patches expose additional therapy and feature settings to
compatible tools. They can make selected commands available over connections
where the stock firmware blocks them. By default, this includes `SetDateTime`
and `ApplyUpgrade` over paired Bluetooth, allowing the date and time to be set
and firmware to be updated without extracting the device OTA key. `ResetDevice`
is also enabled for remote restarts. Commands can also be blocked on selected
direct-control connections.

Selected device settings can also be made available for remote reading or
writing. By default, this includes Warmup, which preheats the humidifier before
therapy.

## PLX Oximeter Compatibility (Optional)

Works around pairing and measurement-status incompatibilities in Bluetooth
PLX pulse oximeters, such as the ChoiceMMed MD300C208S sold as Medisana PM100
Connect. This patch is experimental.

## Cloud Updates (Optional)

An optional cloud-update patch prevents flow-generator updates received from
the cellular service from being installed. By default, it records the update
details without downloading the file. It can instead download and retain the
file for inspection without installing it. Modem and alarm-module updates are
unaffected.

## Cellular Downloads (Optional)

The cellular-download patch adds `AirbreakDownload` to RPC, allowing a supplied
HTTP URL to be downloaded through the cellular modem into firmware-update
storage. The patch is disabled by default.

## Time Zone

The time-zone patch allows the configured time zone to be changed without
erasing patient data.

## Screen Keep-Awake

Hold three fingers on the screen for two seconds to prevent inactivity from
turning off the display. Repeat the gesture to restore normal behavior. The
display pulses when keep-awake is enabled and fades out when it is disabled.
The setting lasts until the device restarts. Requires firmware 8.4 or later.

## Faster Menu Scrolling (Optional)

`--patch-scroll-animation y` shortens menu scrolling by increasing the animation
step by 50%.

## EDF Recording

Stock Air11 variants and therapy modes record different subsets of the
available EDF data. The patch enables a common recording superset so switching
therapy mode does not remove data that the firmware is able to record.

The files remain standard EDF files on the SD card. Signals not used or
produced by the active therapy mode or connected hardware may remain empty or
zero, and the additional channels can make the files slightly larger.

Signal layouts are documented in the
[Air11 EDF Signal Reference](../../as11/edf_signals.md).

## Variant Reporting

The compiled VID-spoof payload updates the reported software variant when the
selected therapy mode is committed. This keeps EDF identity and cloud reporting
aligned with supported AirSense or AirCurve mode families where a mapping is
known.

The payload must be built for the address expected by the patcher. If the
binary is missing, stale, or its destination is occupied, the patcher reports
the problem and skips VID spoofing rather than installing an unsafe hook.

## Device Design-Life Message

The motor patch suppresses the "Your device has reached its design life"
message shown when accumulated runtime reaches its firmware threshold. The
stored runtime counter continues to track device usage.

## Bootloader Service

The bootloader-service patch allows firmware and external flash to be read
and written over CAN, including when the application cannot start. It supports
bootloader version 1.1.0.

See [CAN Firmware Dump](service_dump.md) for entering service mode and
backing up the firmware, and [as11_flash](../../tools/as11_flash.md) for
service commands.

## Build Information

The build-information patch exposes the Airbreak version, patch results, and
custom-setting assignments through RPC `Get AirbreakInfo`. Compatible tools
can use this information to identify the installed modifications.

See [AirbreakInfo](../../as11/patch_airbreak_info.md) for the reported fields.

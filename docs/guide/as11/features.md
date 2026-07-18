# Air11 Standard Patch Features

The standard Air11 image applies the patches selected in `patch-airsense-s11`.
These features are separate from the Air10 compiled therapy payloads.

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

Mode-specific pressure, timing, trigger, cycle, and comfort settings are made
editable where the firmware provides a supported setting path.

iVAPS and PAC remain hidden. Their Air11 implementations and related settings
are excluded by the standard patch.

## ASV Pressure-Support Range

The ASV range patch removes the stock 5 cmH2O minimum separation between
minimum and maximum pressure support in ASV and ASVAuto. Descriptor bounds and
the paired range-selector calculation are patched together.

## Languages and Defaults

The language patch enables the configured language set. The default patch
changes firmware defaults for selected patient and device settings, including
patient access to ramp and pressure relief.

Persisted settings can take precedence over firmware defaults on an existing
device. A default patch is not a command to overwrite every current setting.

## RPC Profiles and Permissions

The RPC profile patch exposes supported therapy and feature profile nodes that
are hidden by product configuration.

The permission patch enables `SetDateTime` and plain `ApplyUpgrade` over the
paired BLE connection by default. Additional permission changes can be
configured in the `RPC_PERMISSIONS` array in `patch-airsense-s11`.

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

The compiled VID-spoof payload updates `VariantIdentifier` when the selected
therapy mode is committed. This keeps EDF identity and cloud reporting aligned
with supported AirSense or AirCurve mode families where a mapping is known.

The payload must be built for the address expected by the patcher. If the
binary is missing, stale, or its destination is occupied, the patcher reports
the problem and skips VID spoofing rather than installing an unsafe hook.

## Device Design-Life Message

The motor patch suppresses the "Your device has reached its design life"
message shown when accumulated runtime reaches its firmware threshold. The
stored runtime counter continues to track device usage.

## Not Included

The current Air11 patch does not include the Air10 Custom VAuto, Square Wave,
adaptive backlight, replacement LCD, custom menu, or ASV backup-rate payloads.

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
- iVAPS
- PAC

Mode-specific pressure, timing, trigger, cycle, and comfort settings are made
editable where the firmware provides a supported setting path.

## Therapy Screen

The therapy-screen patch adds leak, minute ventilation, respiratory rate,
tidal volume, and I:E ratio to the CPAP, AutoSet, and AutoSet for Her therapy
screens. It also adds inspiratory time to ASV and ASVAuto.

## ASV Pressure-Support Range

The ASV range patch removes the stock 5 cmH2O minimum separation between
minimum and maximum pressure support in ASV and ASVAuto. Descriptor bounds and
the paired range-selector calculation are patched together.

## ASV Backup Rate

The ASV backup-rate patch adds a persistent `Backup Rate` control to the
clinical therapy settings in ASV and ASVAuto. `On` preserves stock behavior
and `Off` suppresses backup breaths.

See [Air11 Custom Settings](../../as11/custom_settings.md) for persistence and
fallback behavior.

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
and firmware to be updated without extracting the device OTA key. Commands can
also be blocked on selected direct-control connections.

Selected device settings can also be made available for remote reading or
writing. By default, this includes Warmup, which preheats the humidifier before
therapy.

An optional cloud-update patch prevents flow-generator updates received from
the cellular service from being installed. By default, it records the update
details without downloading the file. It can instead download and retain the
file for inspection without installing it. Modem and alarm-module updates are
unaffected.

## Time Zone

The time-zone patch allows the configured time zone to be changed without
erasing patient data.

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

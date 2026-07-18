# General Features

These features expand the modes, settings, recording, and hardware options
available on supported AirSense 10 and AirCurve 10 firmware. They are included
in the standard patched images unless noted otherwise.

## All Therapy Modes

AirSense 10 and AirCurve 10 variants from the same firmware generation share
the underlying therapy implementations. 
The device-specific configuration
normally limits the mode selector to the modes sold with a particular model.
The patch removes that restriction, exposing CPAP, AutoSet, APAP, S, ST, T,
VAuto, ASV, ASVAuto, iVAPS, PAC, and AutoSet for Her.

<p align="center">
  <img src="../../images/unlocked-therapy-modes-1.png" alt="Unlocked therapy modes, first page" width="220">
  <img src="../../images/unlocked-therapy-modes-2.png" alt="Unlocked therapy modes, second page" width="220">
</p>

This patch changes only mode availability. It does not expose the related
clinical settings; that is handled by the clinical settings patch below.
It also leaves the model's original EDF signal selection unchanged. Full recording
for the additional modes requires the EDF merge patch.

## Clinical Settings and Pressure Range

The clinical menu exposes the settings associated with the unlocked therapy
modes, including mode-specific pressure, timing, trigger, cycle, and comfort
controls.
The menu continues to show only settings relevant to the currently
selected mode.

Standard pressure controls are expanded to the full 1.0 to 30.0 cmH2O range.

<p align="center">
  <img src="../../images/unlocked-pressure-ranges.png" alt="Unlocked ASVAuto pressure ranges" width="240">
</p>

## Motor Runtime Warning

The patch removes the "Motor life exceeded" nag screen that stock firmware can
show after roughly 20,000 blower runtime hours.

Only the warning screen is removed. The device still tracks and reports its
actual runtime hours,
and no therapy records, service information, or usage data are erased.

## EDF Recording

Stock device variants and therapy modes record different subsets of the
available EDF signals.
The patch enables a common signal superset so switching
therapy mode does not remove settings and summary channels that the firmware is
able to record.

The files remain standard EDF files on the SD card. Signals that are not used
or produced by the active therapy mode may remain empty or zero, and recording
the additional channels can make the files slightly larger.

## myAir Cloud Compatibility

myAir accepts sessions only when the selected therapy mode is supported by the
reported device model. Using a mode unlocked from another AirSense or AirCurve
variant can otherwise cause cloud reporting to be rejected.

The patch keeps the reported model compatible with the selected therapy mode
while preserving the device serial number and existing cloud provisioning.

## Replacement LCD Driver

An optional universal LCD driver supports ILI9325 and ILI9328 panels, which are
among the most readily available replacement displays for these devices. This
allows a compatible replacement panel to be used when the original display is
damaged or unavailable.

The controller is detected at startup. Devices with the original ILI9341 panel
continue to use the stock display path, so the same patched image can support
both the original and replacement controllers. Enable this driver when
building with `PATCH_S10_LCD=1`.

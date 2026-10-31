# Air11 Patching

The Air11 patcher modifies a complete firmware image and updates its checksums.
It validates the structures used by each selected patch instead of relying on a
single fixed address map.

## Firmware Image

Use a complete, unmodified 2 MiB Air11 image. It can be dumped from the target
device over [SWD](openocd.md#dump-the-firmware), dumped through the
[bootloader CAN service](service_dump.md), or obtained from another source.
The image does not have to match the firmware release or product variant
currently installed on the target device.

The repository does not distribute firmware images or patched builds. Retain
an unmodified firmware dump for recovery.

Using a different release or product variant can change product identity and
may reset persisted settings or sleep data on first boot.

## Prerequisites

- a complete Air11 image named `as11.bin`
- Python 3.10 or newer
- GNU Make
- `arm-none-eabi-gcc`, linker, and objcopy

## Standard Build

```bash
make as11
```

This builds the Air11 payload binaries and creates:

```text
build/as11-patched.bin
```

The console shows compact patch status by default. A verbose transcript of the
latest build is written to `make.log`; use `make as11 V=1` to also show it on
the console.

To use different paths:

```bash
make as11 AS11_FIRMWARE=/path/to/original.bin \
    AS11_PATCHED=build/my-as11-patched.bin
```

`make as11-patched` is the permissive alternative for systems without the Arm
toolchain. It attempts to build the payloads, then lets the patcher skip patches
whose compiled payload is unavailable. The standard `make as11` target fails
instead of producing that reduced result.

## What Each Patch Does

### Therapy Unlocks

| Patch | What it does | Switch |
|-------|--------------|--------|
| Unlock features | Enables additional supported therapy modes and settings and makes them editable in the clinical menu | `--patch-unlock-features` |
| Unlock ASV PS range | Removes the stock 5 cmH2O separation between minimum and maximum pressure support in ASV and ASVAuto | `--patch-asv-ps-range` |

### Therapy Modifications

| Patch | What it does | Switch |
|-------|--------------|--------|
| ASV backup rate | Allows automatic backup breaths to be disabled in ASV and ASVAuto; the Backup Rate setting controls the behavior | `--patch-asv-backup-rate` |
| Therapy screen | Shows additional respiratory statistics in CPAP, AutoSet, AutoSet For Her, ASV, and ASVAuto | `--patch-therapy-screen` |
| Therapy-screen style | Lets you choose and save the therapy-screen layout | `--patch-therapy-screen-style` |
| [FlowWave](features.md#therapy-screen) (optional) | Shows live breathing flow and mask pressure in the Flow view; requires custom settings | `--patch-flow-wave` |
| [Custom settings](../../as11/custom_settings.md) | Adds clinical-menu settings used by other patches and preserves their values across restarts | `--patch-custom-settings` |

### Therapy Data and Reporting

| Patch | What it does | Switch |
|-------|--------------|--------|
| EDF superset | Adds all supported signals to SD-card therapy files, including signals used by unlocked modes | `--patch-edf-superset` |
| VID spoof | Reports the mapped AirSense or AirCurve variant when therapy mode changes | `--patch-vid-spoof` |

### Connectivity and Control

| Patch | What it does | Switch |
|-------|--------------|--------|
| RPC profile visibility | Exposes supported therapy and feature profile nodes in RPC JSON | `--patch-rpc-json-profile-visibility` |
| RPC permissions | Applies configured method/VCID and DataItem RPC permissions | `--patch-rpc-permissions` |
| [PLX oximeter compatibility](features.md#plx-oximeter-compatibility-optional) (optional) | Works around pairing and measurement-status incompatibilities in Bluetooth PLX pulse oximeters | `--patch-ble-oxi-fallback` |
| Cloud firmware changes | Retains cellular flow-generator updates without installing them | `--patch-cloud-firmware-change` |
| Time-zone write | Allows the time zone to be changed through RPC or the device menu after therapy history exists | `--patch-timezone-write` |

### Quality of Life

| Patch | What it does | Switch |
|-------|--------------|--------|
| Unlock languages | Enables all configured language choices | `--patch-unlock-languages` |
| Defaults | Changes the initial values of selected settings without replacing values already saved on the device | `--patch-defaults` |
| Header clock | Shows local time in the dashboard and therapy-screen headers when enabled in Configuration; default Off | `--patch-header-clock` |
| Screen keep-awake | Uses a three-finger hold to toggle whether inactivity turns off the display | `--patch-screen-keep-awake` |
| Backlight (optional) | Sets ambient-light thresholds, LCD brightness levels, and response delay at build time | `--patch-backlight` |
| Startup logo (optional) | Selects the logo shown when the device starts | `--patch-startup-logo [0..4]` |
| Sensitivity split screen (optional) | Shows a graphic beside Trigger/Cycle sensitivity choices in supported modes | `--patch-sensitivity-split-screen` |
| Motor nag removal | Removes the design-life warning while preserving the runtime counter | `--patch-motor-nagscreen` |
| Airplane-mode reminder | Removes the automatic airplane-mode reminder | `--patch-airplane-reminder` |

### Miscellaneous

| Patch | What it does | Switch |
|-------|--------------|--------|
| [Runtime identity](../../as11/patch_airbreak_info.md) | Exposes the Airbreak version and installed changes through RPC | `--patch-airbreak-info` |
| Bootloader service | Adds internal-flash and NOR memory-chip read/write service over CAN for bootloader 1.1.0 | `--patch-fgbl-service` |

See [Features](features.md) for additional behavior details.

## Selecting Patches

Most switches use `y` to enable a patch or `n` to disable it. For example, to enable only
feature unlocks and expanded SD-card recording:

```bash
python3 python/patch-airsense-s11.py \
    as11.bin build/as11-minimal.bin PATCH \
    --all-patches n \
    --patch-unlock-features y \
    --patch-edf-superset y
```

When building through Make, options can also be passed with `AIR11_PATCH_ARGS`.
See [patch options](../../patch_options.md) for examples and saved preferences.

Startup logo takes a number instead of `y/n`: `0` Off, `1` AirSense 11,
`2` AirCurve 11, `3` Lumis 11, or `4` ResMed. Using `--patch-startup-logo`
without a number selects ResMed; omitting the switch preserves the stock logo.

For example, add both optional patches to the standard build:

```bash
make as11 AIR11_PATCH_ARGS='--patch-startup-logo 4 --patch-sensitivity-split-screen y'
```

## Backlight

Enable `--patch-backlight y` to configure automatic brightness when building
the image:

| Option | Range | Default | Meaning |
|--------|-------|---------|---------|
| `--backlight-threshold-low` | 0..255 | 10 | Dim mode is selected below this `AmbientLight` value |
| `--backlight-threshold-high` | 0..255 | 19 | Bright mode is selected at or above this `AmbientLight` value |
| `--backlight-low` | 0..100 | 20 | Dim LCD brightness, in percent |
| `--backlight-high` | 0..100 | 100 | Bright LCD brightness, in percent |
| `--backlight-delay-ms` | 0..65534 | 3000 | Time the requested ambient mode must differ from the current mode before switching, in ms |

Between the thresholds, the device holds the previous mode.
APPX 8.4.0 and later also require more than 10 seconds since activity before
switching to dim mode.

For example, use 10%/80% LCD brightness, ambient thresholds of 5/30, and a
one-second response delay:

```bash
make as11 AIR11_PATCH_ARGS='--patch-backlight y --backlight-threshold-low 5 --backlight-threshold-high 30 --backlight-low 10 --backlight-high 80 --backlight-delay-ms 1000'
```

## Bootloader Service

`patch-fgbl-service` adds a bootloader maintenance mode for reading and writing
internal flash and the physical NOR memory chip over CAN. It is included in the default
patch set for bootloader version 1.1.0. To enter service mode while resetting or
powering on the device, hold the physical Start/Stop button or transmit a
continuous 1 Mbit/s CAN burst. Release the button or stop the burst when the
status LED starts blinking.

```bash
python3 python/patch-airsense-s11.py \
    as11.bin build/as11-service.bin PATCH \
    --all-patches n \
    --patch-fgbl-service y
```

See [as11_flash service](../../tools/as11_flash.md#bootloader-service) for the
CAN and AirCANnect commands.

## Next

- [Flashing](flashing.md)

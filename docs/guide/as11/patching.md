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
| [Custom settings](../../as11/custom_settings.md) | Adds clinical-menu settings used by other patches and preserves their values across restarts | `--patch-custom-settings` |

### Therapy Data and Reporting

| Patch | What it does | Switch |
|-------|--------------|--------|
| EDF superset | Adds all supported signals to SD-card therapy files, including signals used by unlocked modes | `--patch-edf-superset` |
| VID spoof | Updates `VariantIdentifier` when therapy mode changes so EDF and cloud identity follow the mapped device family | `--patch-vid-spoof` |

### Connectivity and Control

| Patch | What it does | Switch |
|-------|--------------|--------|
| RPC profile visibility | Exposes supported therapy and feature profile nodes in RPC JSON | `--patch-rpc-json-profile-visibility` |
| RPC permissions | Applies configured command permissions for each communication-interface VCID | `--patch-rpc-permissions` |

### Quality of Life

| Patch | What it does | Switch |
|-------|--------------|--------|
| Unlock languages | Enables all configured language choices | `--patch-unlock-languages` |
| Defaults | Changes the initial values of selected settings without replacing values already saved on the device | `--patch-defaults` |
| Motor nag removal | Removes the design-life warning while preserving the runtime counter | `--patch-motor-nagscreen` |

### Miscellaneous

| Patch | What it does | Switch |
|-------|--------------|--------|
| Bootloader service | Adds internal-flash and SPI-NOR read/write service over CAN for bootloader 1.1.0 | `--patch-fgbl-service` |

See [Features](features.md) for additional behavior details.

## Selecting Patches

Edit `PATCHES` near the top of `patch-airsense-s11` to choose the standard
patches. RPC method permissions use the `RPC_PERMISSIONS` array in the same
file.

For a one-off image, invoke the Python patcher directly:

```bash
python3 python/patch-airsense-s11.py \
    as11.bin build/as11-minimal.bin PATCH \
    --all-patches n \
    --patch-unlock-features y \
    --patch-edf-superset y
```

List all patch switches with:

```bash
python3 python/patch-airsense-s11.py -h
```

## Bootloader Service

`patch-fgbl-service` adds a bootloader maintenance mode for reading and writing
internal flash and the physical SPI NOR over CAN. It is included in the default
patch set for bootloader version 1.1.0. To enter service mode, hold the physical
Start/Stop button while resetting or powering on the device. Release the button
when the status LED starts blinking.

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

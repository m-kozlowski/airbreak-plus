# Air11 Patching

The Air11 patcher modifies a complete firmware image and updates its checksums.
It validates the structures used by each selected patch instead of relying on a
single fixed address map.

## Firmware Image

Use a complete, unmodified 2 MiB Air11 image. It can be dumped from the target
device over [SWD](openocd.md#dump-the-firmware) or obtained from another 
source. The image does not have to match the firmware release or product
variant currently installed on the target device.

The repository does not distribute firmware images or patched builds. Keep the
unmodified input separately from generated output. When SWD access is
available, also preserve the exact image dumped from the target for recovery.

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

To use different paths:

```bash
make as11 AS11_FIRMWARE=/path/to/original.bin \
    AS11_PATCHED=build/my-as11-patched.bin
```

`make as11-patched` is the permissive alternative for systems without the Arm
toolchain. It attempts to build the payloads, then lets the patcher skip patches
whose compiled payload is unavailable. The standard `make as11` target fails
instead of producing that reduced result.

## Default Patch Set

The compatibility wrapper selects:

| Patch | Effect |
|-------|--------|
| `patch-unlock-features` | supported therapy modes, settings, and GUI editability |
| `patch-unlock-languages` | configured language availability |
| `patch-defaults` | selected firmware defaults |
| `patch-rpc-json-profile-visibility` | supported therapy and feature RPC nodes |
| `patch-edf-superset` | expanded SD-card therapy data recording for unlocked modes |
| `patch-vid-spoof` | correct product identification in SD-card and cloud data for unlocked modes |
| `patch-motor-nagscreen` | removes the "device has reached its design life" warning triggered after ~20,000 hours of runtime |
| `patch-asv-ps-range` | ASV/ASVAuto MinPS-MaxPS range restriction removal |
| `patch-asv-backup-rate` | disables the ASV/ASVAuto backup rate; `patch-custom-settings` adds a persistent On/Off control |
| `patch-custom-settings` | menu controls requested by selected compiled payloads |
| `patch-rpc-permissions` | controls which device commands are available through each communication interface |

See [Features](features.md) for the resulting behavior.

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

## Build Result

A successful run prints the result of every selected patch, updates the image
checksums, and prints the output hash. Do not flash the image if the patcher
reports an error or unexpectedly skips a selected patch.

Continue with [Flashing](flashing.md).

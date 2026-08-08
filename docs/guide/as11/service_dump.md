# CAN firmware dump

Airbreak can read the complete 2 MiB internal flash over CAN without opening
the device. This is an alternative to the standard SWD dump. It requires an
unmodified Air11 image containing bootloader version 1.1.0. This file is
referred to below as the **reference image**.

This procedure replaces the bootloader, which starts the device and applies
firmware updates. If power or CAN communication is lost while it is being
written, the device may stop booting and require SWD recovery. Keep the device
and adapter powered until the update completes.

The repository does not distribute ResMed firmware. The reference image may
come from any AirSense 11 or AirCurve 11 image with bootloader version `1.1.0`.
Only its 128 KiB bootloader region is written to the device.

## Requirements

- a complete, unmodified 2 MiB Air11 reference image
- the Airbreak build tools, including `arm-none-eabi-gcc`
- a [CAN connection](../../as11/can_connection.md)
- an SWD programmer if bootloader recovery becomes necessary

## Prepare the bootloader

Check the reference image versions:

```
python3 python/as11_descriptors.py reference.bin
```

The bootloader version must be `1.1.0`.

Build the compiled payloads:

```
make as11-binaries
```

Create an image containing only the bootloader service patch:

```
python3 python/patch-airsense-s11.py \
    reference.bin build/service-enabled.bin PATCH \
    --all-patches n \
    --patch-fgbl-service y
```

Install only the bootloader region. The model definition and application
firmware already installed on the device are not changed.

```
python3 python/as11_flash.py flash \
    -d can:/dev/ttyACM0 \
    -f build/service-enabled.bin \
    --block bootloader \
    --include-bootloader
```

## Enter service mode

1. Remove power from the device.
2. Hold the physical Start/Stop button.
3. Restore power while holding the button.
4. Release the button when the status LED starts blinking.

Confirm that the service responds:

```
python3 python/as11_flash.py \
    -d can:/dev/ttyACM0 service info
```

## Dump the internal flash

```
python3 python/as11_flash.py \
    -d can:/dev/ttyACM0 service read-flash device-dump.bin
```

Check the dump:

```
stat -c %s device-dump.bin
python3 python/as11_descriptors.py device-dump.bin
```

The bootloader in this dump includes the service patch.

## Rebuild an unmodified image

The dump contains the service-enabled bootloader. Replace that region with the
unmodified bootloader from the reference image before using the dump as patcher
input:

```
cp device-dump.bin device-original.bin
dd if=reference.bin of=device-original.bin \
    bs=131072 count=1 conv=notrunc status=none
```

Check the rebuilt image:

```
python3 python/as11_descriptors.py device-original.bin
```

Use `device-original.bin` as the input for normal patching. It combines the
stock bootloader from the reference image with the model definition and
application firmware dumped from the device.

## Optional: dump the physical NOR

The service can also read the complete 16 MiB physical SPI NOR:

```
python3 python/as11_flash.py \
    -d can:/dev/ttyACM0 service read-nor device-nor.bin
```

The SPI NOR contains unit-specific data, including device identity, calibration, and settings.

## Leave service mode

Release the Start/Stop button, then reset the device through the service:

```
python3 python/as11_flash.py \
    -d can:/dev/ttyACM0 service reset
```

The normal application starts after the reset.

## Restore the stock bootloader

To remove the service extension, install only the unmodified bootloader from
the reference image:

```
python3 python/as11_flash.py flash \
    -d can:/dev/ttyACM0 \
    -f reference.bin \
    --block bootloader \
    --include-bootloader
```

The model definition and application firmware remain unchanged.
Button-selected service mode is no longer available after the stock bootloader
starts.

## Recover a failed bootloader update

If the device no longer boots, connect an SWD programmer as described in the
[connection guide](connection.md#swd) and start OpenOCD:

```
./run-ocd.sh as11
```

In the OpenOCD console, write only the bootloader from the reference image:

```
flash_fgbl reference.bin
```

`flash_fgbl` accepts a complete 2 MiB image or a separate 128 KiB bootloader
block. It writes and verifies only the bootloader region.

## Next

- [Patching](patching.md)

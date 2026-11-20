# CAN firmware dump

Airbreak can read the complete 2 MiB internal flash over CAN without opening
the device. This is an alternative to the standard SWD dump. It requires an
unmodified Air11 image with a bootloader the service patch supports, referred
to below as the **reference image**.

> **Before you start:** This procedure replaces the bootloader, which starts
> the device and applies firmware updates. If power or CAN communication is
> lost while it is being written, the device may stop booting and require SWD
> recovery. Keep the device and adapter powered until the update completes.

The repository does not distribute ResMed firmware. The reference image may
come from any AirSense 11 or AirCurve 11 unit whose bootloader the service
patch supports; only its 128 KiB bootloader region is written to the device.

## Why this works

The Air11 internal flash is divided into regions that the update path addresses
independently:

| Region | Content |
|--------|---------|
| FGBL | bootloader and lower update path |
| CONF | model definition: descriptors, schemas, and product data |
| APPL | application firmware: therapy control, user interface, drivers |

Because the regions are independent, the reference image supplies only a
service-enabled FGBL while the device keeps its own CONF and APPL. The service
runs inside the bootloader, so it reads and writes flash even when the
application cannot start. The factory bootloader cannot read flash back; the
service patch adds the read path.

## Requirements

- a complete, unmodified 2 MiB Air11 reference image
- the Airbreak build tools, including `arm-none-eabi-gcc`
- a [CAN connection](../../as11/can_connection.md)
- an SWD programmer if bootloader recovery becomes necessary

## Prepare the bootloader

Check the reference image:

```
python3 python/resmed_image.py info reference.bin
```

The `Boot:` line reports the image's bootloader; `info` refuses an image whose
bootloader it does not recognize. The service patch supports specific
bootloader builds and rejects an unsupported reference by its build ID.

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

Install the bootloader region. `--include-bootloader` is the deliberate
confirmation required for a bootloader write, and `--block bootloader` keeps
the write to that region.

```
python3 python/as11_flash.py flash \
    -d can:/dev/ttyACM0 \
    -f build/service-enabled.bin \
    --block bootloader \
    --include-bootloader
```

Before writing, `as11_flash` reads the device's running bootloader and stops if
its flash layout differs from the reference image's, which would otherwise
leave the existing CONF and APPL at the wrong offsets. Pass `--force` only when
you are sure the layouts match.

## Enter service mode

1. Remove power from the device.
2. Hold the physical Start/Stop button.
3. Restore power while holding the button.
4. Release the button when the status LED starts blinking.

Alternatively, start the CAN entry burst:

```
python3 python/as11_flash.py \
    -d can:/dev/ttyACM0 service enter
```

Restore power while the command is running. It stops the burst as soon as
service mode responds.

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
python3 python/resmed_image.py info device-dump.bin
```

The output must identify a complete Air11 image and show `ok` for all three
block CRCs. The bootloader in this dump includes the service patch.

## Rebuild an unmodified image

The dump contains the service-enabled bootloader. Replace that region with the
unmodified bootloader from the reference image before using the dump as patcher
input:

```
python3 python/resmed_image.py replace \
    device-dump.bin device-original.bin \
    --fgbl reference.bin
```

Use `device-original.bin` as the input for normal patching. It combines the
stock bootloader from the reference image with the model definition and
application firmware dumped from the device.

See the [`resmed_image.py` reference](../../tools/resmed_image.md) for other
file operations.

## Optional: back up the NOR chip and OTA key

Beside the main firmware, the device has a second memory chip: a 16 MiB NOR
flash. It stores data unique to this unit, including its identity, factory
calibration, settings and recordings, and the device-specific OTA key. None of
it can be regenerated, so it is worth backing up while the service is reachable.

Read the complete NOR:

```
python3 python/as11_flash.py \
    -d can:/dev/ttyACM0 service read-nor device-nor.bin
```

The OTA key inside that backup is what authenticated Bluetooth updates need, and
this is the only way to capture it without an SWD session. Extract it:

```
python3 python/as11_nor_tool.py device-nor.bin key-get OTA -o ota-key.hex
```

Store it against a Bluetooth device alias for later updates:

```
python3 python/as11_config.py devices ota-key <alias> --key-file ota-key.hex
```

See [Retrieving the local OTA key](../../as11/ota_protocol.md#retrieving-the-local-ota-key)
for key handling and [`as11_nor_tool.py`](../../tools/as11_nor_tool.md) for other
NOR contents.

## Leave service mode

Stop the CAN burst or release the Start/Stop button, then reset the device
through the service:

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

# Serial firmware dump (UART)

Airbreak can read a device's complete firmware through the external serial
port, without opening the case. This is an alternative to the standard SWD
dump. Use it when you want to keep the device closed and already have an
unmodified firmware file from another AirSense 10 or AirCurve 10 device. This
file is referred to below as the **reference image**.

> **Before you start:** This procedure overwrites the bootloader - the part
> that starts the device and handles serial firmware updates. If power or the
> serial connection drops mid-write, the device may fail to start, and the only
> way back is an SWD programmer and an opened case: exactly what this method
> avoids. Leave both connected until the tool reports the write is complete.

The repository does not distribute ResMed firmware. The reference image does
not have to match your device: a different model or firmware version is fine.
Only its bootloader is used. Nothing else about your device changes.

Lumis ST-A firmware uses a different bootloader and is not supported.

## Why this works

ResMed's own update protocol addresses three parts of the firmware separately:

| Block | Content |
|-------|---------|
| BLX | Bootloader and serial update protocol |
| CCX | Model definition: identity, available modes and settings, limits, localized interface text, etc. |
| CDX | Application firmware: therapy control, user interface, drivers |

This separation allows the bootloader to be replaced without writing the other
two blocks.

The bootloader is generic for a given bootloader ID. It does not contain a
device serial number, calibration, model selection, or therapy settings. Those
remain in the other parts of the device.

The factory bootloader can write firmware but cannot read it back. The
airbreak patch adds one read command and leaves the existing update commands
unchanged. The dump command itself only reads flash memory.

## Requirements

- a reference image: another unmodified 1 MB firmware file from an AirSense 10
  or AirCurve 10 device
- the airbreak build tools, including `arm-none-eabi-gcc` for the compiled
  payload
- a [serial connection](serial_connection.md) to the accessory port
- access to an SWD programmer if bootloader recovery becomes necessary

## Prepare the bootloader

Check the reference image first:

```
./python/resmed_image.py info reference.bin
```

The output must report `SX577-0200`, and every listed block CRC must report
`ok`.

The serial dump extension is a compiled payload, so build it first. This needs
`arm-none-eabi-gcc`:

```
make binaries
```

Then patch the reference image. The default Air10 patch includes the serial
dump extension:

```
./patch-airsense reference.bin build/dump-enabled.bin
```

Install only the bootloader from the patched image. `--include-bootloader` is
a separate confirmation required for every bootloader write; without it,
`resmed_flash.py` refuses to modify the bootloader.

```
./python/resmed_flash.py -p /dev/ttyACM0 \
    -f build/dump-enabled.bin --block bootloader --include-bootloader
```

The tool prints a flash plan before writing. Check that it lists only the
bootloader, with no other block listed, then accept the write.

## Dump the installed firmware

```
./python/resmed_flash.py -p /dev/ttyACM0 --dump device-dump.bin
```

The tool reads exactly 1,048,576 bytes and validates each firmware part before
completing the output file. Inspect the result independently:

```
./python/resmed_image.py info device-dump.bin
```

Keep this dump safe and unchanged: it is your only way to restore this
device's firmware. It holds the complete internal flash, with the
dump-enabled bootloader in place of the original one.

Unit-specific data lives in EEPROM, outside the internal flash: serial number,
calibration, settings, therapy statistics, etc. None of it is
part of this dump. You can back the EEPROM up separately with
[`resmed_config.py`](../tools/resmed_config.md#calibration-eeprom).

## Optional follow-up

The main procedure ends here. The remaining sections cover three separate
situations:

- [Rebuild an original image](#rebuild-an-original-image): you want a stock
  firmware file, without the dump extension
- [Restore the stock bootloader](#restore-the-stock-bootloader): you want the
  device back on its original bootloader
- [Recover a failed bootloader update](#recover-a-failed-bootloader-update):
  the device stopped answering over UART

## Rebuild an original image

Replace the dump-enabled bootloader with the unmodified bootloader from the
reference image:

```
./python/resmed_image.py replace device-dump.bin device-original.bin \
    --blx reference.bin
```

`reference.bin` may be a complete image or a separately extracted bootloader
block. The tool checks that it matches the selected platform before writing
the output. The other two blocks are copied from `device-dump.bin` without
modification.

See the [`resmed_image.py` reference](../tools/resmed_image.md) for other file
operations.

## Restore the stock bootloader

To remove the serial dump extension from a working device, flash only the
unmodified bootloader:

```
./python/resmed_flash.py -p /dev/ttyACM0 \
    -f reference.bin --block bootloader --include-bootloader
```

Everything else on the device remains unchanged. Serial firmware dumping is
no longer available after the stock bootloader starts.

## Recover a failed bootloader update

If the device no longer answers over UART, connect an SWD programmer as
described in the [wiring guide](wiring.md), then start OpenOCD:

```
./run-ocd.sh
```

In the OpenOCD console, write only the original bootloader:

```
flash_blx reference.bin
```

`flash_blx` accepts either a complete 1 MB image or a 16 KB bootloader block.
It writes only the bootloader flash sector and verifies the written bytes.

## Next

[Building and patching](patching.md)

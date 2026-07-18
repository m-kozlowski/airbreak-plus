# Air11 Flashing

The patched image can be installed over SWD or CAN. BLE is useful for later
updates after its pairing and OTA-key requirements have been prepared.

## SWD

Start OpenOCD as described in [OpenOCD](openocd.md#start-openocd), then run:

```tcl
flash_new build/as11-patched.bin
```

The helper programs and verifies the complete image, then resets the device.
Keep the unchanged device backup before replacing the image.

## CAN

Leave the clinical menu and return the device to standby before applying an
update.

For a serial SLCAN adapter:

```bash
python3 python/as11_flash.py flash \
    -d can:/dev/ttyACM0 \
    -f build/as11-patched.bin
```

For SocketCAN:

```bash
python3 python/as11_flash.py flash \
    -d can:can0 \
    -f build/as11-patched.bin
```

The command uploads and verifies the image, then applies the update. The device
reboots automatically.

Adapter setup and wiring are documented in
[Air11 CAN Connection](../../as11/can_connection.md). The full command
reference, including partial images and advanced apply modes, is in
[as11_flash](../../tools/as11_flash.md).

## BLE

Stock authenticated BLE updates require the device-specific OTA key retrieved
over SWD. After pairing the device, store the key with its alias:

```bash
python3 python/as11_config.py devices ota-key bedroom --key-file ota-key.hex
```

Then flash with:

```bash
python3 python/as11_flash.py flash \
    -d ble:bedroom \
    -f build/as11-patched.bin
```

After `patch-rpc-permissions` has been installed, later BLE updates can use
plain apply without the OTA key:

```bash
python3 python/as11_flash.py flash \
    -d ble:bedroom \
    -f build/as11-patched.bin \
    --apply-plain
```

Pairing and device aliases are documented under
[as11_config devices](../../tools/as11_config.md#devices). OTA-key handling is
documented under
[Retrieving the local OTA key](../../as11/ota_protocol.md#retrieving-the-local-ota-key).

## Verify

After the reboot, open the clinical menu and confirm that the expected therapy
modes and settings are available.

## Restoring the Original Image

Use the unchanged image dumped from the device before its first patch. That
image is the preferred rollback source even when a different image
was used for patching.

To restore it over SWD, start OpenOCD as described in
[OpenOCD](openocd.md#start-openocd), then run:

```tcl
flash_new /path/to/as11-original.bin
```

If the application still runs and CAN is available, the same backup can be
restored through the normal update path:

```bash
python3 python/as11_flash.py flash \
    -d can:/dev/ttyACM0 \
    -f /path/to/as11-original.bin
```

Leave the clinical menu and put the device in standby before applying the
image. If CAN communication is unavailable, use SWD.

Restoring an exact device backup does not require a settings reset. An image
from another product variant may migrate or reset persisted data and is not an
exact rollback image.

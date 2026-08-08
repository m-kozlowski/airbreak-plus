# Air11 Quickstart

End-to-end guide for unlocking ResMed AirSense 11 and AirCurve 11 devices.

## What You Need

### Path A: dump firmware from the device

This path makes a complete backup before patching. A direct SWD dump also keeps
SWD available for recovery. If an unmodified Air11 image is available as a
reference, the [bootloader CAN service](service_dump.md) can instead dump the
firmware without opening the device.

SWD hardware:

- an SWD programmer, such as ST-Link or WeAct MiniDebugger
- a TC2050-IDC cable and jumper wires
- access to the TC2050 footprint on the Air11 main board

SWD software:

- OpenOCD
- Python 3.10 or newer
- GNU Make
- the Arm embedded GCC toolchain

See [Disassembly](disassembly.md) for access to the programming footprint and
[Connection](connection.md#swd) for the exact programmer wiring.

### Path B: use an existing unmodified firmware image

If a complete, unmodified Air11 firmware image is already available, the device
does not need to be opened. Prepare and patch that image locally, then flash the
generated result over CAN.

Hardware:

- a [supported USB-CAN adapter](../../as11/can_connection.md#tested-adapters)
- a [PSU and CAN pass-through cable](../../as11/can_connection.md#connector-and-pinout)

Software:

- Python 3.10 or newer
- GNU Make
- the Arm embedded GCC toolchain
- Python serial support when using a serial SLCAN adapter

The patch source does not have to match the firmware release or product
variant currently installed on the device. It must be a complete Air11 image;
the patcher validates the required structures before producing the output.

## 1. Prepare the Tools

On Debian or Ubuntu:

```bash
sudo apt install git make gcc-arm-none-eabi binutils-arm-none-eabi \
    python3 python3-crcmod
git clone https://github.com/m-kozlowski/airbreak-plus.git
cd airbreak-plus
```

For Windows, see [WSL2 Setup](../wsl_setup.md).

For the SWD path, also install:

```bash
sudo apt install openocd telnet-ssl
```

For a serial SLCAN adapter, also install:

```bash
sudo apt install python3-serial
```

## 2. Open and Connect the Device

### SWD

[Open the device](disassembly.md) to expose the programming footprint, then
[connect the SWD programmer](connection.md#swd).

### CAN

Connect the USB-CAN adapter using the pass-through cable described in
[Air11 CAN Connection](../../as11/can_connection.md#connector-and-pinout).

## 3. Obtain the Firmware Image

### Path A: dump firmware from the device

**SWD:** Follow [OpenOCD and Firmware Dump](openocd.md), or start OpenOCD from
the repository root:

```bash
./run-ocd.sh as11
```

In another terminal:

```bash
telnet localhost 4444
```

At the OpenOCD prompt:

```tcl
dump
```

This creates `as11.bin`. Keep an unchanged copy as the device backup.

The same SWD session can also be used to
[retrieve the device-specific OTA key](../../as11/ota_protocol.md#retrieving-the-local-ota-key)
or check and correct the hardware RTC with `rtc::now`, `rtc::sync`, and
`rtc::set_time`.

**CAN (no SWD):** If you want to keep the device
closed and have an unmodified Air11 image to use as a reference, follow
[CAN firmware dump](service_dump.md). Use the resulting `device-original.bin`
as `as11.bin`.

### Path B: use an existing unmodified image

Place the image in the repository root as `as11.bin` and keep an unchanged copy
separately.

See [Patching](patching.md#firmware-image) for input image details.

## 4. Patch

```bash
make as11
```

The patched image is written to:

```text
build/as11-patched.bin
```

Do not continue if the patcher reports an error or unexpectedly skips a
selected patch.

## 5. Flash

### SWD

At the OpenOCD prompt:

```tcl
flash_new build/as11-patched.bin
```

### CAN

For a serial SLCAN adapter:

```bash
python3 python/as11_flash.py flash \
    -d can:/dev/ttyACM0 \
    -f build/as11-patched.bin
```

The upload is verified before the image is applied. The device reboots when
the update completes.

## 6. Verify

Open the clinical menu and confirm that the expected therapy modes and
settings are available.

## Restoring the Original Image

Over SWD:

```tcl
flash_new /path/to/as11-original.bin
```

If the application still runs, the backup can also be restored over CAN. See
[Restoring the Original Image](flashing.md#restoring-the-original-image).

## Later BLE Updates

Stock authenticated BLE updates require the device-specific OTA key. It can be
retrieved during the initial SWD session; see
[Retrieving the local OTA key](../../as11/ota_protocol.md#retrieving-the-local-ota-key).
The standard patch also permits plain BLE apply for later updates. See
[Flashing](flashing.md#ble).

## Detailed Guide

| Guide | Content |
|-------|---------|
| [Disassembly](disassembly.md) | Opening the enclosure and reaching the SWD footprint |
| [Connection](connection.md) | SWD wiring and optional CAN hardware |
| [OpenOCD](openocd.md) | Firmware dump, optional OTA key, and RTC sync |
| [CAN firmware dump](service_dump.md) | Optional closed-case dump using the bootloader service |
| [Features](features.md) | Standard patch behavior and current limits |
| [Patching](patching.md) | Build targets and patch selection |
| [Flashing](flashing.md) | SWD, CAN, and BLE installation and restoring the original image |

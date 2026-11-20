# Air11 Quickstart

End-to-end guide for unlocking ResMed AirSense 11 and AirCurve 11 devices.

## What You Need

Two paths, depending on whether you already have an unmodified Air11 firmware
image.

### Path A: you already have an unmodified Air11 image

The device stays closed and needs no SWD hardware. Place your unmodified image
in the repository root as `as11.bin`, keep an unchanged copy as a backup, then
go to [step 3 (patch)](#3-patch). Flashing is over CAN (the device's wired data
link, reached with a USB-CAN adapter without opening the case).

Hardware:

- a [supported USB-CAN adapter](../../as11/can_connection.md#tested-adapters)
- a [PSU and CAN pass-through cable](../../as11/can_connection.md#connector-and-pinout)

Software:

- Python 3.10 or newer
- GNU Make
- the Arm embedded GCC toolchain
- Python serial support when using a serial SLCAN adapter

The patch source does not have to match the firmware release or product variant
on the device. It must be a complete Air11 image; the patcher validates the
required structures before producing the output.

### Path B: dump the firmware from the device

Use this when no unmodified image is available. The dump is also your recovery
backup.

The usual route connects over SWD (a wired link to the device's processor,
using an ST-Link programmer and a TC2050 cable on the open board), which also
stays available afterward for recovery.

**Alternative: CAN service dump (no SWD).** To keep the case closed, the
[bootloader CAN service](service_dump.md) can dump the firmware over CAN. It
needs a separate unmodified Air11 image as a reference and it rewrites the
device bootloader, so read its recovery warning before choosing it. With no
reference image and no way to open the case, there is no dump path; obtain an
image and use Path A instead.

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
[Connection](connection.md#swd) for the exact programmer wiring. The CAN
alternative's hardware and steps are in [CAN firmware dump](service_dump.md).

## 1. Prepare the Tools

On Debian or Ubuntu:

```bash
sudo apt install git make gcc-arm-none-eabi binutils-arm-none-eabi python3
git clone https://github.com/m-kozlowski/airbreak-plus.git
cd airbreak-plus
```

For Windows, see [WSL2 Setup](../wsl_setup.md).

For the SWD dump (Path B), also install:

```bash
sudo apt install openocd telnet-ssl
```

For a serial SLCAN adapter, also install:

```bash
sudo apt install python3-serial
```

## 2. Obtain the Firmware Image

*Path B only. Path A already has `as11.bin`; go to [step 3](#3-patch).*

### SWD

[Open the device](disassembly.md) and
[connect the SWD programmer](connection.md#swd), then follow
[OpenOCD and Firmware Dump](openocd.md), or start OpenOCD from the
repository root:

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

The same SWD session can also
[retrieve the device-specific OTA key](../../as11/ota_protocol.md#retrieving-the-local-ota-key)
or check and correct the device's hardware clock (RTC) with `rtc::now`,
`rtc::sync`, and `rtc::set_time`.

### CAN (no SWD)

With a separate unmodified Air11 image as a reference, follow
[CAN firmware dump](service_dump.md). Use the resulting `device-original.bin`
as `as11.bin`.

While the device is in service mode, also
[back up its NOR chip and extract the OTA key](service_dump.md#optional-back-up-the-nor-chip-and-ota-key).
The NOR is a small memory chip, separate from the firmware, holding data unique
to your device (identity, factory calibration, the OTA key) that cannot be
regenerated. This is the only convenient chance to capture it without SWD, and
[later authenticated BLE updates](#later-ble-updates) need the key.

## 3. Patch

For graphical patch selection and builds, use [AirBreaker](../airbreaker.md)
and select `air11`. From a terminal:

```bash
make as11
```

The patched image is written to:

```text
build/as11-patched.bin
```

Do not continue if the patcher reports an error or unexpectedly skips a
selected patch.

## 4. Flash

### CAN (Path A, or Path B without SWD)

Connect the USB-CAN adapter using the pass-through cable described in
[Air11 CAN Connection](../../as11/can_connection.md#connector-and-pinout).
For a serial SLCAN adapter:

```bash
python3 python/as11_flash.py flash \
    -d can:/dev/ttyACM0 \
    -f build/as11-patched.bin
```

The upload is verified before the image is applied. The device reboots when the
update completes.

### SWD (Path B)

With the programmer still attached, at the OpenOCD prompt:

```tcl
flash_new build/as11-patched.bin
```

## 5. Verify

Open the clinical menu and confirm that the expected therapy modes and settings
are available.

## Restoring the Original Image

Over SWD:

```tcl
flash_new /path/to/as11-original.bin
```

If the application still runs, the backup can also be restored over CAN. See
[Restoring the Original Image](flashing.md#restoring-the-original-image).

## Later BLE Updates

Installing official ResMed updates over Bluetooth (BLE) requires the
device-specific OTA key. Retrieve it once, by either method:

- **From an SWD session:** see
  [Retrieving the local OTA key](../../as11/ota_protocol.md#retrieving-the-local-ota-key).
- **From the device NOR over CAN:** read it in service mode; see
  [back up the NOR chip and OTA key](service_dump.md#optional-back-up-the-nor-chip-and-ota-key).

The key is optional: the standard patch also permits plain Bluetooth apply for
later updates. See [Flashing](flashing.md#ble).

## Detailed Guide

| Guide | Content |
|-------|---------|
| [Disassembly](disassembly.md) | Opening the enclosure and reaching the SWD footprint |
| [Connection](connection.md) | SWD wiring and optional CAN hardware |
| [OpenOCD](openocd.md) | Firmware dump, optional OTA key, and RTC sync |
| [CAN firmware dump](service_dump.md) | Closed-case firmware dump, NOR memory-chip backup, and OTA key over the bootloader service |
| [Features](features.md) | Standard patch behavior and current limits |
| [Patching](patching.md) | Build targets and patch selection |
| [Flashing](flashing.md) | SWD, CAN, and BLE installation and restoring the original image |

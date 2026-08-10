# as11_flash

BLE / CAN firmware flash tool for AirSense 11 / AirCurve 11 series.

Push a raw firmware image to the device, target a specific flash block,
optionally apply the upgrade. Builds the `.abc` OTA container internally and
sends it over the same RPC path the device's own updater uses. Supports both
BLE and CAN transports.

## Contents

- [Commands](#commands)
  - [`flash`](#flash)
  - [`upload`](#upload)
  - [`build`](#build)
  - [`info`](#info)
  - [`apply`](#apply)
  - [`targets`](#targets)
- [Flash specific blocks](#flash-specific-blocks)
- [Apply modes](#apply-modes)
  - [Apply over BLE](#apply-over-ble)
- [Bootloader service](#bootloader-service)
  - [Install and enter service mode](#install-and-enter-service-mode)
  - [Service identity and reset](#service-identity-and-reset)
  - [Read storage](#read-storage)
  - [Write storage](#write-storage)
  - [Transport options](#transport-options)

## Commands

### flash

Build the OTA container from a raw firmware image and upload it in one step.
This is the primary path -- start here.

```
as11_flash.py flash -d ble:as11 -f patched.bin --block conf+app
as11_flash.py flash -d ble:AA:BB:CC:DD:EE:FF -f patched.bin --block conf+app
as11_flash.py flash -d can:/dev/ttyACM0 -f patched.bin --block conf+app
as11_flash.py flash -d can:can0 --can-flavour socketcan -f patched.bin --block conf+app
as11_flash.py flash -d ble:as11 -f patched.bin --block config --apply-plain
as11_flash.py flash -d ble:as11 -f patched.bin --block full --include-full-flash --apply
```

`-f` accepts a full internal flash image (the patcher's output), an APPL/CONF
extract, or any block payload. The tool auto-detects the layout and packages
the requested `--block` slice. If `--block` is omitted, `flash` guesses a
safe non-bootloader target from the input size when possible.

By default `flash` applies after `CheckUpgradeFile`: authenticated apply on
BLE, plain `ApplyUpgrade` on CAN/TCP. Use `--verify-only` to upload and verify
without rebooting or writing flash.

### upload

Push a pre-built `.abc` container without rebuilding it. Useful when the
container was produced ahead of time or by a separate workflow. Unlike
`flash`, `upload` is verify-only by default.

```
as11_flash.py upload -d ble:as11 patched.abc
as11_flash.py upload -d ble:as11 patched.abc --apply
as11_flash.py upload -d ble:as11 patched.abc --fix-crc
```

### build

Offline: assemble an `.abc` container from a raw image without touching a device.

```
as11_flash.py build -f patched.bin --block firmware -o patched.abc
as11_flash.py build -f patched.bin --block full --include-full-flash -o full.abc
```

### info

Inspect an existing `.abc` container.

```
as11_flash.py info patched.abc
```

### apply

Apply a previously uploaded and verified container. The command can use a
saved `.abc`, a raw firmware image that rebuilds to the same `.abc`, or the
known SHA-256 hash from an earlier successful upload.

```
as11_flash.py apply -d can:/dev/ttyACM0 --hash HASH64
as11_flash.py apply -d can:/dev/ttyACM0 -f patched.bin --block conf+app
as11_flash.py apply -d ble:as11 --abc-file patched.abc
```

### targets

List the supported `--block` names and what they cover.

```
as11_flash.py targets
```

## Flash specific blocks

| Block | Content | Extra flag |
|-------|---------|-----------|
| `config` | `CONF` config/aux block | -- |
| `firmware` / `app` | `APPL` main application image | -- |
| `conf+app` | `APCX` combined config + application range | -- |
| `bootloader` | `FGBL` bootloader / low updater region | `--include-bootloader` |
| `full` / `all` | `FGCB` complete internal flash image | `--include-full-flash` |

```
as11_flash.py flash -d ble:as11 -f patched.bin --block firmware
as11_flash.py flash -d ble:as11 -f patched.bin --block conf+app --apply
```

## Apply modes

| Flag | Effect |
|------|--------|
| no apply flag on `upload` | Verify only; stop after `CheckUpgradeFile` |
| no apply flag on BLE `flash`/`apply` | authenticated apply |
| no apply flag on CAN/TCP `flash`/`apply` | plain `ApplyUpgrade` |
| `--verify-only` | Verify only; stop after `CheckUpgradeFile` |
| `--apply` | Verify, then `ApplyAuthenticatedUpgrade` |
| `--apply-authenticated` | Synonym for `--apply` |
| `--apply-plain` | Verify, then `ApplyUpgrade` (unauthenticated) |

Authenticated apply resolves the OTA signing key from `--key`, `--key-file`,
`$AS11_OTA_KEY`, or a stored BLE device `otaKey`.

### Apply over BLE

The stock BLE RPC exposes authenticated apply, but the HMAC needs the
device's OTA key. Plain `ApplyUpgrade` over BLE needs a firmware permission
patch first. Pick one path before flashing:

1. **Authenticated path.** Retrieve the device's OTA key over SWD/OpenOCD
   using `tcl/as11-keys.tcl` and pass it via `--key`, `--key-file`, or
   `$AS11_OTA_KEY`, or store it as the device alias `otaKey`. The key is
   per-device. Procedure documented in
   [`docs/as11/ota_protocol.md`](../as11/ota_protocol.md#retrieving-the-local-ota-key).

2. **Unauthenticated path (`--apply-plain`).** Flash the `patch-rpc-permissions`
   patch first, which exposes `ApplyUpgrade` on encrypted BLE permission
   selector `0x0396`. Host requests still go over the paired VCID `0x0397`.
   After that `--apply-plain` works over BLE with no key. The first install
   of the patched firmware still has to land via SWD or CAN; subsequent BLE
   flashes can use unauthenticated apply.

CAN exposes `ApplyUpgrade` natively, so `--apply-plain` works there
without either step.

## Bootloader service

The `service` command communicates with the bootloader service extension over
direct CAN or AirCANnect binary TCP. It reads and writes internal STM32 flash
and the physical SPI NOR independently of the normal OTA mechanism.

### Install and enter service mode

The device must contain the `patch-fgbl-service` patch. While resetting or
powering on the device, either hold the physical Start/Stop button or transmit
a continuous 1 Mbit/s CAN burst. Release the button or stop the burst when the
status LED starts blinking.

Enter service mode with:

```
as11_flash.py -d can:/dev/ttyACM0 service enter
```

If the service is already running, `enter` reports its identity without
resetting it. Otherwise it sends `ResetDevice(Fast)` and starts a CAN burst.
`INFO` probes are interleaved with the burst every 100 ms, and the command
returns as soon as service mode responds. The entry window is 30 seconds.
With AirCANnect, the bridge performs the same sequence locally and converts
the successful internal `INFO` response into the `enter` response.

Check that the service responds:

```
as11_flash.py -d can:/dev/ttyACM0 service info
as11_flash.py -d can:can0 --can-flavour socketcan service info
as11_flash.py -d tcp:aircannect service info
```

See the [CAN firmware dump guide](../guide/as11/service_dump.md) for installing
the service patch when the device does not already contain it.

### Service identity and reset

`service info` reports the service version and bootloader build ID. It does not
read or modify storage.

`service reset` leaves service mode and starts the normal application when the
Start/Stop button is released.

```
as11_flash.py -d can:/dev/ttyACM0 service reset
```

### Read storage

`read-flash` reads internal STM32 flash, `read-nor` reads the physical SPI NOR,
and `read-bkpsram` reads the 4 KiB battery-backed SRAM. All commands require an
output file; without a region or range they read the complete target.

```
as11_flash.py -d can:/dev/ttyACM0 service read-flash flash.bin
as11_flash.py -d can:/dev/ttyACM0 service read-flash appl.bin APPL
as11_flash.py -d can:/dev/ttyACM0 service read-flash part.bin \
  0x08040000 0x20000
as11_flash.py -d tcp:aircannect service read-nor nor.bin
as11_flash.py -d tcp:aircannect service read-nor part.bin 0 0x10000
as11_flash.py -d can:/dev/ttyACM0 service read-bkpsram bkpsram.bin
```

Flash reads accept the named regions `FGBL`, `CONF`, `APPL`, `APCX`, and
`FGCB`, together with their normal `as11_flash.py` aliases. The output file is
opened directly; a failed transfer leaves the bytes received before the
failure in that file.

Complete NOR dumps can be inspected and extracted with
[`as11_nor_tool.py`](as11_nor_tool.md).

### Write storage

`write-flash` and `write-nor` require an input file. They erase each selected
erase unit before programming it, then read back and verify each programmed
fragment. Ranges must align to the storage erase unit: 128 KiB for internal
flash and 64 KiB for SPI NOR.

`write-bkpsram` writes backup SRAM directly and verifies it without erase. Its
offset is relative to `0x38800000`; without a range it writes all 4096 bytes.

```
as11_flash.py -d can:/dev/ttyACM0 service write-flash flash.bin
as11_flash.py -d can:/dev/ttyACM0 service write-flash appl.bin APPL
as11_flash.py -d can:/dev/ttyACM0 service write-flash flash.bin APPL
as11_flash.py -d can:/dev/ttyACM0 service write-flash part.bin \
  0x08040000 0x20000
as11_flash.py -d tcp:aircannect service write-nor nor.bin
as11_flash.py -d can:/dev/ttyACM0 service write-bkpsram bkpsram.bin
```

For a named flash region or numeric range, the input may contain either that
range alone or the complete 2 MiB internal-flash image. A numeric SPI-NOR range
similarly accepts either the selected range or a complete physical-NOR image.

### Transport options

The service uses fixed classic-CAN and ISO-TP settings, independently of the
stock DatagramCan and JSON-RPC endpoint. The complete wire contract is in the
[bootloader service protocol](../as11/bootloader_service_protocol.md).

The receiver controls multi-frame transfers with ISO-TP Flow Control frames.
The AS11 advertises a block size of 32 frames and zero separation time. The
direct CAN host advertises a block size of 255 and zero separation time;
AirCANnect selects its own receive block size. Direct CAN commands accept
`--block-size 0..255`; zero disables intermediate Flow Control frames.

With `-d tcp:<host>[:<port>]`, the tool uses AirCANnect binary mode on port
`39011` by default. AirCANnect handles ISO-TP fragmentation, flow control, and
reassembly and carries complete service packets over TCP.

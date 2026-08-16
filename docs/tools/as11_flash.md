# as11_flash

Firmware upgrade and bootloader service tool for Air11 devices.

Build an `.abc` OTA container from one or more firmware regions, upload it to
the device, and optionally apply the upgrade. The selected firmware inputs
determine the target flash range.

## Contents

- [Commands](#commands)
  - [`flash`](#flash)
  - [`upload`](#upload)
  - [`build`](#build)
  - [`info`](#info)
  - [`apply`](#apply)
  - [`targets`](#targets)
- [Firmware inputs](#firmware-inputs)
- [Apply modes](#apply-modes)
  - [Apply over BLE](#apply-over-ble)
- [Bootloader service](#bootloader-service)
  - [Install and enter service mode](#install-and-enter-service-mode)
  - [Service identity and reset](#service-identity-and-reset)
  - [Flash firmware](#flash-firmware)
  - [Read storage](#read-storage)
  - [Write storage](#write-storage)
  - [Transport options](#transport-options)

## Commands

### flash

Build the OTA container from a raw firmware image and upload it in one step.
This is the primary path -- start here.

```
as11_flash.py flash -d ble:as11 -f patched.bin
as11_flash.py flash -d ble:AA:BB:CC:DD:EE:FF -f patched.bin
as11_flash.py flash -d can:/dev/ttyACM0 -f patched.bin
as11_flash.py flash -d can:can0 --can-flavour socketcan -f patched.bin
as11_flash.py flash -d ble:as11 -f patched.bin --block config --apply-plain
as11_flash.py flash -d ble:as11 -f patched.bin --block full --include-bootloader --apply
```

`--fgbl`, `--conf`, and `--appl` accept either the corresponding raw region or
a complete 2 MiB internal image. The tool extracts each selected region and
infers the OTA target from their combination. See [Firmware inputs](#firmware-inputs).

By default `flash` applies after `CheckUpgradeFile`: authenticated apply on
BLE, plain `ApplyUpgrade` on CAN/TCP. Use separate `build` and `upload`
commands when the staged image should not be applied immediately.

### upload

Push a pre-built `.abc` container without rebuilding it. Useful when the
container was produced ahead of time or by a separate workflow. Unlike
`flash`, `upload` stops after `CheckUpgradeFile` by default.

```
as11_flash.py upload -d ble:as11 patched.abc
as11_flash.py upload -d ble:as11 patched.abc --apply
```

### build

Offline: assemble an `.abc` container from a raw image without touching a device.

```
as11_flash.py build --appl patched.bin --fingerprint-preset 16.8.5.0 -o patched.abc
as11_flash.py build --full patched.bin --block fgcb -o full.abc
```

For targets that use release-specific compatibility fingerprints, select the
preset matching the input image. An offline build does not require an
additional confirmation flag. `flash` retains explicit confirmation for the
FGBL and FGCB targets.

### info

Inspect an existing `.abc` container.

```
as11_flash.py info patched.abc
```

### apply

Apply a previously uploaded and verified container. Pass the same `.abc` file
or its SHA-256 hash from the successful upload.

```
as11_flash.py apply -d can:/dev/ttyACM0 --hash HASH64
as11_flash.py apply -d ble:as11 patched.abc
as11_flash.py apply -d can:/dev/ttyACM0 --hash HASH64 \
    --authentication HMAC64
```

### targets

List the base firmware input combinations and their inferred OTA targets.

```
as11_flash.py targets
```

## Firmware inputs

| Inputs | OTA target | Content | `flash` confirmation |
|--------|------------|---------|--------------------------------|
| `--fgbl PATH` | `FGBL` | bootloader and lower updater | `--include-bootloader` |
| `--conf PATH` | `CONF` | configuration and product data | -- |
| `--appl PATH` | `APPL` | application | -- |
| `--conf PATH --appl PATH` | `APCX` | configuration and application | -- |
| `--fgbl PATH --conf PATH --appl PATH` | `FGCB` | complete internal flash | `--include-bootloader` |
| `-f PATH` / `--full PATH` | `APCX` | configuration and application from a complete image | -- |
| `-f PATH --include-bootloader` | `FGCB` | complete internal flash | `--include-bootloader` |

Each regional argument accepts either an exact raw region or a complete 2 MiB
internal image. The same full image can therefore be supplied to more than one
regional argument. `-f` is shorthand for `--full`; both require a complete
2 MiB image. For `flash`, they select `APCX` by default and `FGCB` when
`--include-bootloader` is present. A regional argument used together with
`--full` replaces that region from the full image.

With `flash`, `--block NAME` selects a target from the supplied regions. The
inputs must cover the selected target; additional regions are ignored. Block
names and aliases are case-insensitive.

The release preset supplies the CONF/APPL and FGBL/APPL compatibility
fingerprints. They can be overridden with
`--conf-appl-fingerprint` and `--fgbl-appl-fingerprint`.

Unless `--fg-security-fingerprint` is supplied, `flash` reads `_SBA` and
`_SKF` for the descriptor's FG security fingerprint. If `_SBA` is `No`, the
field is written as zero. An offline `build` defaults to zero when no override
is supplied.

Without `--block`, regional inputs must match one of the combinations listed
above. Offline `build` defaults a complete image to `APCX`; use `--block FGCB`
to build a complete-image container. The updater erases the whole selected
target before programming it, so the supplied inputs must cover that target
without gaps.

```
as11_flash.py flash -d ble:as11 --appl patched.bin
as11_flash.py flash -d ble:as11 --conf patched.bin --appl patched.bin --apply
```

## Apply modes

| Flag | Effect |
|------|--------|
| no apply flag on `upload` | Verify only; stop after `CheckUpgradeFile` |
| no apply flag on BLE `flash`/`apply` | authenticated apply |
| no apply flag on CAN/TCP `flash`/`apply` | plain `ApplyUpgrade` |
| `--apply` | Use `ApplyAuthenticatedUpgrade` |
| `--apply-authenticated` | Synonym for `--apply` |
| `--apply-plain` | Use `ApplyUpgrade` (unauthenticated) |
| `--authentication HEX64` | Use a precomputed authentication value with standalone `apply` |

`upload` and `flash` always run `CheckUpgradeFile` before an apply method.
Standalone `apply` addresses a container that was uploaded and verified
earlier; it does not repeat `CheckUpgradeFile`.

Authenticated apply resolves the OTA signing key from `--key`, `--key-file`,
`$AS11_OTA_KEY`, or a stored BLE device `otaKey`. The standalone `apply`
command can instead receive the resulting HMAC through `--authentication`.

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

### Flash firmware

`service flash` enters service mode if necessary, programs the selected
internal-flash range, and resets the device. If service mode already responds,
the command uses the active session without resetting it first. A failed write
leaves the device in service mode for another attempt.

Firmware inputs and `--block` follow the same rules as the normal `flash`
command; see [Firmware inputs](#firmware-inputs).

```
as11_flash.py -d can:/dev/ttyACM0 service flash -f patched.bin
as11_flash.py -d can:/dev/ttyACM0 service flash -f patched.bin --block APPL
as11_flash.py -d can:/dev/ttyACM0 service flash \
  --conf conf.bin --appl appl.bin
```

A complete image passed with `-f` selects `APCX` by default. Add
`--include-bootloader` to program the complete `FGCB` image. Any target that
contains `FGBL` requires this flag.

The command checks the firmware CRC footers before connecting. `--fix-crc`
repairs mismatched footers in memory before programming; `--force` permits
programming an image that still fails local validation. Each programmed
fragment is read back and verified by the service.

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

When the Python `lz4` module and service compression commands are available,
reads and writes use independent LZ4 blocks automatically. Unsupported or
incompressible transfers use the normal READ and WRITE commands.

The receiver controls multi-frame transfers with ISO-TP Flow Control frames.
The AS11 advertises a block size of 32 frames and zero separation time. The
direct CAN host advertises a block size of 255 and zero separation time;
AirCANnect selects its own receive block size. Direct CAN commands accept
`--block-size 0..255`; zero disables intermediate Flow Control frames.

With `-d tcp:<host>[:<port>]`, the tool uses AirCANnect binary mode on port
`39011` by default. AirCANnect handles ISO-TP fragmentation, flow control, and
reassembly and carries complete service packets over TCP.

# as11_flash

## Name

`as11_flash.py` - build and transfer Air11 firmware; access bootloader service storage.

## Contents

- [Synopsis](#synopsis)
- [Description](#description)
- [Arguments](#arguments)
- [Options](#options)
  - [Container options](#container-options)
- [Commands](#commands)
  - [flash](#flash)
  - [upload](#upload)
  - [build](#build)
  - [info](#info)
  - [apply](#apply)
  - [targets](#targets)
- [Firmware inputs](#firmware-inputs)
- [Apply modes](#apply-modes)
  - [Apply over BLE](#apply-over-ble)
- [Bootloader service](#bootloader-service)
  - [enter](#enter)
  - [info / reset](#info--reset)
  - [service flash](#service-flash)
  - [Read storage](#read-storage)
  - [Write storage](#write-storage)
  - [Transport options](#transport-options)
- [Output](#output)
- [Environment](#environment)
- [Files](#files)
- [Exit Status](#exit-status)
- [Examples](#examples)
- [See Also](#see-also)

## Synopsis

```text
as11_flash.py build INPUT_OPTIONS -o ABC [OPTIONS]
as11_flash.py info ABC
as11_flash.py targets
as11_flash.py -d DEVICE flash INPUT_OPTIONS [OPTIONS]
as11_flash.py -d DEVICE upload ABC [OPTIONS]
as11_flash.py -d DEVICE apply ABC [OPTIONS]
as11_flash.py -d DEVICE apply --hash HEX64 [OPTIONS]
as11_flash.py -d DEVICE service COMMAND [ARGUMENTS] [OPTIONS]
```

## Description

Builds and inspects OTA containers, checks firmware CRCs, uploads images,
verifies staging, and applies upgrades. Selects and combines firmware regions
from complete images or separate blocks.

Programs firmware and reads or writes internal flash, external NOR, and backup
SRAM through the bootloader service extension.

## Arguments

| Argument | Meaning |
|----------|---------|
| `DEVICE` | Transport target; see the device options below |
| `INPUT_OPTIONS` | Firmware source options listed under [Firmware inputs](#firmware-inputs) |
| `ABC` | Host path to an OTA container; output for `build`, input for `info`, `upload`, and `apply` |
| `HEX64` | SHA-256 container hash as 64 hexadecimal digits |

## Options

Device options are accepted before or after the command.

| Option | Meaning | Default |
|--------|---------|---------|
| `-d`, `--device TARGET` | `ble:ADDRESS`, `can:TARGET`, or `tcp:HOST[:PORT]` | `AS11_DEVICE` |
| `--addr ADDRESS` | Compatibility shortcut for `-d ble:ADDRESS` | None |
| `-p`, `--port PORT` | Compatibility shortcut for `-d can:PORT` | None |
| `--can-flavour NAME` | `slcan`, `socketcan`, or `waveshare`; `canable` aliases `slcan` | Inferred from target |
| `--debug` | Transport packet logging | Off |
| `-h`, `--help` | Show help | -- |

BLE targets accept a MAC, UUID, or stored alias. TCP targets use the AirCANnect
bridge, default port `39011`. See [connection syntax](as11_config.md#connection).

### Container options

| Option | Commands | Meaning / default |
|--------|----------|-------------------|
| `--fingerprint-preset NAME` | `build`, `flash` | Default `auto`: live `flash` queries `ApplicationIdentifier`; offline `build` requires an explicit preset or fingerprint overrides when needed |
| `--conf-appl-fingerprint U32` | `build`, `flash` | Override CONF/APPL compatibility fingerprint |
| `--fgbl-appl-fingerprint U32` | `build`, `flash` | Override FGBL/APPL compatibility fingerprint |
| `--fg-security-fingerprint U32` | `build`, `flash` | Override security fingerprint; queried live, zero offline |
| `--fix-crc` | `build`, `flash` | Repair input CRC footers in memory |
| `--force` | `build`, `flash`, `upload` | Override local validation failures |
| `--dry-run` | `flash`, `upload` | Validate and preview the plan offline; `flash` requires explicit fingerprints when automatic discovery would need the device |
| `--verify-timeout SECONDS` | `flash`, `upload` | `CheckUpgradeFile` and apply timeout; default `120` |

`build --help` lists fingerprint presets. Individual fingerprint options
override preset values.

For the security fingerprint, live `flash` reads `_SBA` and `_SKF` unless
overridden. When `_SBA` is `No`, it uses zero.

Input options and target selection are listed under [Firmware inputs](#firmware-inputs).
Apply options are listed under [Apply modes](#apply-modes).

## Commands

### flash

```text
flash INPUT_OPTIONS [OPTIONS]
```

Build, upload, verify, and apply an OTA container from
[firmware inputs](#firmware-inputs), using authenticated apply on BLE and
plain apply on CAN/TCP by default.

| Option | Meaning |
|--------|---------|
| `--save-abc PATH` | Save the built container |

Shared flags are listed under [Container options](#container-options) and
[Apply modes](#apply-modes).

```sh
as11_flash.py -d ble:as11 flash -f patched.bin
as11_flash.py -d can:can0 flash -f patched.bin --block full --include-bootloader
```

### upload

```text
upload ABC [OPTIONS]
```

Upload a pre-built `ABC` container and stop after `CheckUpgradeFile` by default.

| Option | Meaning | Default |
|--------|---------|---------|
| `--apply`, `--apply-authenticated` | Apply after verification, using an OTA key | Off |
| `--apply-plain` | Apply after verification without authentication | Off |

Validation and timeout flags are in [Container options](#container-options);
keys and reset settings are in [Apply modes](#apply-modes).

```sh
as11_flash.py -d ble:as11 upload patched.abc
as11_flash.py -d ble:as11 upload patched.abc --apply
```

### build

```text
build INPUT_OPTIONS -o ABC [OPTIONS]
```

Assemble an `ABC` container offline from [firmware inputs](#firmware-inputs).

| Option | Meaning |
|--------|---------|
| `-o`, `--output PATH` | Required output container path |

Use the input release's [fingerprint preset](#container-options) for targets
with release-specific fingerprints. Offline builds do not require
`--include-bootloader`.

```sh
as11_flash.py build --appl patched.bin --fingerprint-preset 16.8.5.0 -o patched.abc
as11_flash.py build --full patched.bin --block fgcb -o full.abc
```

### info

```text
info ABC
```

Inspect an existing `.abc` container.

```sh
as11_flash.py info patched.abc
```

### apply

```text
apply ABC [OPTIONS]
apply --hash HEX64 [OPTIONS]
```

Apply a previously uploaded and verified container without repeating
`CheckUpgradeFile`.

| Option | Meaning |
|--------|---------|
| `--hash HEX64` | Successful upload's SHA-256 instead of a host `ABC` file |
| `--authentication HEX64` | Precomputed HMAC instead of an OTA key |

Default apply mode and key sources are listed under [Apply modes](#apply-modes).
The host file must be the same container that was uploaded.

```sh
as11_flash.py -d ble:as11 apply patched.abc
as11_flash.py -d can:/dev/ttyACM0 apply --hash HASH64 --authentication HMAC64
```

### targets

```text
targets
```

List firmware input combinations and their inferred OTA targets.

```sh
as11_flash.py targets
```

## Firmware inputs

| Inputs | OTA target | Content | `flash` confirmation |
|--------|------------|---------|--------------------------------|
| `--fgbl PATH` | `FGBL` | bootloader and lower updater | `--include-bootloader` |
| `--conf PATH` | `CONF` | model definition | -- |
| `--appl PATH` | `APPL` | application firmware | -- |
| `--conf PATH --appl PATH` | `APCX` | model definition and application firmware | -- |
| `--fgbl PATH --conf PATH --appl PATH` | `FGCB` | complete internal flash | `--include-bootloader` |
| `-f PATH` / `--full PATH` | `APCX` | configuration and application from a complete image | -- |
| `-f PATH --include-bootloader` | `FGCB` | complete internal flash | `--include-bootloader` |

Each regional option accepts an exact raw region or a complete 2 MiB image.
`-f`, `--full` requires a complete image. A regional option supplied alongside
`--full` replaces that region's source.

`--block NAME` selects a target from the supplied regions; without it, the
input combination determines the target. Inputs must cover the target without
gaps; additional regions are ignored. Names and aliases are case-insensitive.

| Target | Aliases |
|--------|---------|
| `FGBL` | `bootloader` |
| `CONF` | `config` |
| `APPL` | `app`, `firmware` |
| `APCX` | `conf+app`, `config+firmware` |
| `FGCB` | `full`, `all` |

Offline `build` defaults a complete image to `APCX`; use `--block FGCB`
for a complete-image container. Live `flash` and `service flash` require
`--include-bootloader` for any target containing `FGBL`.
The updater erases the selected target before programming it.

## Apply modes

| Flag | Effect |
|------|--------|
| no apply flag on `upload` | Verify only; stop after `CheckUpgradeFile` |
| no apply flag on BLE `flash`/`apply` | authenticated apply |
| no apply flag on CAN/TCP `flash`/`apply` | plain `ApplyUpgrade` |
| `--apply` | Use `ApplyAuthenticatedUpgrade` |
| `--apply-authenticated` | Synonym for `--apply` |
| `--apply-plain` | Use `ApplyUpgrade` (unauthenticated) |
| `--reset-settings` | Send `resetSettingsToDefault=true`; plain apply only; default is false |
| `--key HEX64` | OTA signing key as 64 hex characters |
| `--key-file PATH` | OTA signing key as 32 raw bytes or hex text |

`upload` and `flash` always run `CheckUpgradeFile` before applying.

Authenticated apply resolves the OTA signing key from `--key`, `--key-file`,
`$AS11_OTA_KEY`, or a stored BLE device `otaKey`. The standalone `apply`
command can instead receive the resulting HMAC through `--authentication`.

### Apply over BLE

| Mode | Requirement |
|------|-------------|
| Authenticated (default) | Device-specific OTA key; see [key retrieval](../as11/ota_protocol.md#retrieving-the-local-ota-key) |
| `--apply-plain` | Firmware with `ApplyUpgrade` enabled for encrypted BLE, e.g. `patch-rpc-permissions` installed through SWD or CAN |

CAN exposes plain `ApplyUpgrade` natively, without a key or permission patch.
Encrypted-BLE selectors are listed in
[RPC permissions](../as11/rpc_protocol.md#rpc-permission-selectors).

## Bootloader service

The `service` command accesses bootloader storage over CAN or an AirCANnect
TCP bridge. It requires `patch-fgbl-service`; see the
[installation and entry guide](../guide/as11/service_dump.md).

| Command | Operation |
|---------|-----------|
| `enter` | Enter service mode, or report an already-running service |
| `info` | Report service identity |
| `reset` | Leave service mode and reset |
| `flash` | Program selected firmware regions and reset |
| `read-flash` / `write-flash` | Read/write internal flash |
| `read-nor` / `write-nor` | Read/write physical NOR |
| `read-bkpsram` / `write-bkpsram` | Read/write backup SRAM |

### enter

```text
service enter [--timeout SECONDS]
```

Report an already-running service without resetting it, or send
`ResetDevice(Fast)` and request service mode during reboot.

| Option | Meaning | Default |
|--------|---------|---------|
| `--timeout SECONDS` | Entry window | `30` |

Direct CAN sends a continuous 1 Mbit/s entry burst with `INFO` probes every
100 ms and returns as soon as the service responds. AirCANnect runs this
sequence at the bridge; its response handling is specified in the
[TCP service protocol](../as11/bootloader_service_protocol.md#aircannect-tcp-transport).

Manual entry holds Start/Stop during reset or power-on, or supplies the CAN
burst; release the button or stop the burst when the status LED blinks.

```sh
as11_flash.py -d can:/dev/ttyACM0 service enter
```

### info / reset

```text
service info [--timeout SECONDS]
service reset [--timeout SECONDS]
```

`info` reports the service version and bootloader build ID without accessing
storage; `reset` starts the normal application once Start/Stop is released.

| Option | Meaning | Default |
|--------|---------|---------|
| `--timeout SECONDS` | Service response timeout | `5` |

```sh
as11_flash.py -d tcp:aircannect service info
as11_flash.py -d can:/dev/ttyACM0 service reset
```

### service flash

```text
service flash INPUT_OPTIONS [OPTIONS]
```

Enter service mode if necessary, program selected internal-flash regions,
verify each fragment by readback, and reset.

| Option | Meaning | Default |
|--------|---------|---------|
| `--fix-crc` | Repair input CRC footers in memory before programming | Off |
| `--force` | Permit programming despite local validation failures | Off |

[Firmware inputs](#firmware-inputs) and [Transport options](#transport-options)
apply. CRC checks run before connecting. An already-running service is reused
without an initial reset; a failed write leaves it active for another attempt.

```sh
as11_flash.py -d can:/dev/ttyACM0 service flash -f patched.bin --block APPL
as11_flash.py -d can:/dev/ttyACM0 service flash --conf conf.bin --appl appl.bin
```

### Read storage

```text
service read-flash FILE [REGION | OFFSET LENGTH] [OPTIONS]
service read-nor FILE [VOLUME | OFFSET LENGTH] [OPTIONS]
service read-bkpsram FILE [OFFSET LENGTH] [OPTIONS]
```

`read-flash` reads internal STM32 flash, `read-nor` reads the physical SPI NOR,
and `read-bkpsram` reads the 4 KiB battery-backed SRAM. All commands require an
output file `FILE`; the default range is the complete target.
`REGION` selects a named flash region. `OFFSET` and `LENGTH` select a byte
range: flash uses absolute addresses from `0x08000000`; NOR and backup SRAM
use zero-based offsets. Backup-SRAM offset zero corresponds to `0x38800000`.

`VOLUME` selects `settings`, `datalog`, or `upgrade` (also `nor:0`, `nor:1`,
or `nor:2`). The file contains only that physical volume, starting at file
offset zero. Volume sizes and NOR offsets are listed in the
[NOR layout](as11_nor_tool.md#layout).

Flash reads accept the named regions `FGBL`, `CONF`, `APPL`, `APCX`, and
`FGCB`, together with their normal `as11_flash.py` aliases. The output file is
opened directly; a failed transfer leaves the bytes received before the
failure in that file.

Complete NOR and single-volume dumps can be inspected and extracted with
[`as11_nor_tool.py`](as11_nor_tool.md).

```sh
as11_flash.py -d can:/dev/ttyACM0 service read-flash part.bin 0x08040000 0x20000
as11_flash.py -d tcp:aircannect service read-nor nor.bin
as11_flash.py -d can:/dev/ttyACM0 service read-nor settings.bin settings
```

### Write storage

```text
service write-flash FILE [REGION | OFFSET LENGTH] [OPTIONS]
service write-nor FILE [OFFSET LENGTH] [OPTIONS]
service write-bkpsram FILE [OFFSET LENGTH] [OPTIONS]
```

`write-flash` and `write-nor` erase the selected storage units, program them,
and verify each fragment by readback.

`FILE` is the host input image; range arguments follow [Read storage](#read-storage).
Ranges must align to the storage erase unit: 128 KiB for internal flash and
64 KiB for SPI NOR.

`write-bkpsram` writes backup SRAM directly and verifies it without erase. Its
offset is relative to `0x38800000`; without a range it writes all 4096 bytes.

For a named flash region or numeric range, the input may contain either that
range alone or the complete 2 MiB internal-flash image. A numeric SPI-NOR range
similarly accepts either the selected range or a complete physical-NOR image.

```sh
as11_flash.py -d can:/dev/ttyACM0 service write-flash flash.bin APPL
as11_flash.py -d can:/dev/ttyACM0 service write-bkpsram bkpsram.bin
```

### Transport options

Reads and writes use LZ4 compression automatically when the Python `lz4`
module and service support it; other transfers use uncompressed blocks.

| Option | Meaning | Default |
|--------|---------|---------|
| `--timeout SECONDS` | Service response timeout; entry window for `enter` | `5`; `30` for `enter` |
| `--block-size FRAMES` | Direct CAN receive block size, `0..255`; `0` disables intermediate Flow Control | `255` |

Direct CAN advertises zero separation time. AirCANnect selects its own receive
block size. Device flow control and framing are specified in the
[service protocol](../as11/bootloader_service_protocol.md#iso-tp-framing).

## Output

Text identity, container, validation, and transfer reports. Transport logs and
errors go to stderr. `build`, `--save-abc`, and `service read-*` write binary
files; failed service reads leave partial output at the requested path.

## Environment

| Variable | Meaning |
|----------|---------|
| `AS11_DEVICE` | Optional target in `-d` format; explicit `-d`, `--addr`, or `--port` takes precedence |
| `AS11_OTA_KEY` | OTA key used when no explicit key argument is supplied |

## Files

| File | Use |
|------|-----|
| `~/.as11_ble.json` | BLE pairing, aliases, and fallback `otaKey` |
| `--key-file PATH` | Device-specific OTA key, binary or hex text |
| `ABC` | OTA container used by `info`, `upload`, or `apply` |

## Exit Status

| Status | Meaning |
|--------|---------|
| `0` | Operation completed |
| `1` | Target, file, validation, transport, RPC, or timeout error |
| `2` | Invalid command-line syntax or argument type |
| `130` | Interrupted by Ctrl-C |

## Examples

Build an application container, verify its upload, then apply it:

```sh
as11_flash.py build --appl patched.bin --fingerprint-preset 16.8.5.0 -o patched.abc
as11_flash.py -d can:can0 upload patched.abc
as11_flash.py -d can:can0 apply patched.abc
```

Enter service mode, capture NOR, then inspect the dump:

```sh
as11_flash.py -d can:can0 service enter
as11_flash.py -d can:can0 service read-nor nor.bin
as11_flash.py -d can:can0 service reset
as11_nor_tool.py nor.bin info
```

## See Also

[OTA protocol](../as11/ota_protocol.md),
[bootloader service protocol](../as11/bootloader_service_protocol.md),
[as11_config](as11_config.md), [as11_nor_tool](as11_nor_tool.md),
[Air11 flashing guide](../guide/as11/flashing.md).

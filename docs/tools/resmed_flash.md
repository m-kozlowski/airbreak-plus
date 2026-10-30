# resmed_flash

## Name

`resmed_flash.py` - flash Air 10 and S9 firmware through the UART bootloader.

## Contents

- [Synopsis](#synopsis)
- [Description](#description)
- [Connection](#connection)
- [Operations](#operations)
  - [Flash a firmware image](#flash-a-firmware-image)
  - [Flash specific blocks](#flash-specific-blocks)
  - [Dump an Air 10 firmware image](#dump-an-air-10-firmware-image)
  - [Read device identity](#read-device-identity)
- [Options](#options)
- [Output](#output)
- [Exit Status](#exit-status)
- [Examples](#examples)
- [See Also](#see-also)

## Synopsis

```text
resmed_flash.py -p PORT -f IMAGE [OPTIONS]
resmed_flash.py -p PORT --dump FILE [OPTIONS]
resmed_flash.py -p PORT --info [OPTIONS]
```

## Description

Reads device identity, flashes complete images or selected firmware blocks,
and dumps internal flash through the UART bootloader. Checks input CRCs,
supports CRC repair, and negotiates the transfer speed.

## Connection

Bootloader entry uses USART3 at 57600 baud, 8N1. Transfer speed is selected
with `--baud`. Transfer framing is described in the
[serial protocol](../serial_protocol.md#flash-data-protocol).

| `PORT` | Connection |
|--------|------------|
| Serial device path | UART, directly or through a USB-UART adapter |
| `tcp:HOST[:PORT]` | AirBridge TCP bridge |

## Operations

### Flash a firmware image

```text
-f IMAGE [OPTIONS]
```

Flash CMX on Air 10 or CCX+CDX on S9 from the complete internal-flash `IMAGE`.
To keep AirSense/AirCurve 10 settings, let the tool enter the bootloader.
If the device is already in the bootloader, the tool cannot enable settings
preservation.

| Option | Meaning | Default |
|--------|---------|---------|
| `-f`, `--file IMAGE` | Firmware input path | Required |
| `--include-bootloader` | Add BLX to the selected regions | Off |
| `--fix-crc` | Repair input CRCs before flashing | Off |
| `--force` | Permit flashing with invalid CRCs | Off |
| `--dry-run` | Validate without writing; standalone blocks may require device identity | Off |
| `--no-reset` | Skip the final reset | Off |
| `--factory-reset` | Restore AirSense/AirCurve 10 settings to firmware defaults, retaining calibration and serial numbers | Off |

```sh
resmed_flash.py -p /dev/ttyACM0 -f patched.bin
```

### Flash specific blocks

```text
-f IMAGE --block NAME [--block NAME ...] [OPTIONS]
```

Flash selected blocks from `IMAGE`, retaining the rest of the device's firmware.

| Option | Meaning | Default |
|--------|---------|---------|
| `--block NAME` | Select a block; repeatable and case-insensitive | CMX on Air 10; CCX+CDX on S9 |
| `--raw` | Accept an image smaller than the single selected block | Off |

A single selected block accepts a standalone image of its exact size.
Bootloader writes require `--include-bootloader`, including with `all`.
CRC and reset options follow [Flash a firmware image](#flash-a-firmware-image).

| Name | Content |
|------|---------|
| `config`, `conf`, `ccx` | Model definition |
| `firmware`, `fw`, `cdx` | Application firmware |
| `cmx` | CCX+CDX combined (Air 10) |
| `all` | BLX+CMX (Air 10) or BLX+CCX+CDX (S9) |
| `bootloader`, `boot`, `blx` | Bootloader |

```sh
resmed_flash.py -p /dev/ttyACM0 -f patched.bin --block config
resmed_flash.py -p /dev/ttyACM0 -f patched.bin --block all --include-bootloader
```

### Dump an Air 10 firmware image

```text
--dump FILE [OPTIONS]
```

Read complete internal flash into `FILE`; requires the
[patched Air 10 bootloader](../guide/serial_dump.md).

```sh
resmed_flash.py -p /dev/ttyACM0 --dump firmware.bin
```

### Read device identity

```text
--info [OPTIONS]
```

Show device identity and exit.

```sh
resmed_flash.py -p /dev/ttyACM0 --info
resmed_flash.py -p tcp:airbridge-host --info
```

## Options

| Option | Meaning | Default |
|--------|---------|---------|
| `-p`, `--port PORT` | Serial port or `tcp:HOST[:PORT]` | Required |
| `--tcp-mode MODE` | `raw` or `transparent` | `transparent` |
| `--baud BAUD` | `auto`, `57600`, `115200`, or `460800` | `auto` |
| `--completion-timeout SECONDS` | Wait for the device's final transfer status; S9 verification retains a minimum 15-second budget | `3` |
| `--no-enter` | Use an already-running bootloader; settings may be reset | Off |
| `--no-wait` | Fail immediately if the device is unavailable | Off |
| `--timing` | Print transfer timing statistics | Off |
| `-h`, `--help` | Show help | -- |

## Output

Identity, validation, progress, and transfer summaries are printed to the terminal.
`--dump FILE` writes a binary firmware image.

An `unconfirmed` result means the device did not provide a conclusive response;
it does not necessarily mean flashing failed. Check the device before retrying.
For delayed responses over TCP, increase `--completion-timeout SECONDS`.

Application startup is checked separately unless `--no-reset` is selected.

## Exit Status

| Status | Meaning |
|--------|---------|
| `0` | Operation completed |
| `1` | Connection, validation, or transfer failure |
| `2` | Invalid command-line syntax |
| `3` | Flash result or application startup could not be confirmed |

## Examples

Dump internal flash through the patched bootloader, then inspect its CRCs:

```sh
resmed_flash.py -p /dev/ttyACM0 --dump firmware.bin
resmed_image.py info firmware.bin
```

## See Also

[resmed_image](resmed_image.md), [serial protocol](../serial_protocol.md),
[serial firmware dump guide](../guide/serial_dump.md).

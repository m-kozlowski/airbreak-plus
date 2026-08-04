# resmed_flash

UART firmware flash tool for ResMed Air 10 / S9 series. It flashes firmware
through the device's standard bootloader. On supported Air 10 devices, it can
also dump a complete image when a [patched bootloader](../guide/serial_dump.md)
is installed.

Communicates over the USART3 service port at 57600 8N1. Enters the bootloader, negotiates baud rate, and transfers firmware blocks using the native ResMed flash protocol (S-records over F-frames).

## Connection

Serial port (direct or via USB-UART adapter):
```
resmed_flash.py -p /dev/ttyACM0 ...
```

TCP via AirBridge:
```
resmed_flash.py -p tcp:airbridge-host ...
```

## Flash a firmware image

```
resmed_flash.py -p /dev/ttyACM0 -f patched.bin
```

Flashes CMX (or CCX+CDX on S9), skipping the bootloader by default.

## Flash specific blocks

| Block | Content | Flag |
|-------|---------|------|
| `config` | CCX (configuration data) | `--block config` |
| `firmware` | CDX (application code) | `--block firmware` |
| `cmx` | CCX+CDX combined (S10) | `--block cmx` |
| `all` | BLX+CMX (S10) or BLX+CCX+CDX (S9) | `--block all` |
| `bootloader` | BLX | `--block bootloader --include-bootloader` |

```
resmed_flash.py -p /dev/ttyACM0 -f patched.bin --block config
```

## Dump an Air 10 firmware image

```
resmed_flash.py -p /dev/ttyACM0 --dump firmware.bin
```

Reads the complete Air 10 firmware image. See the [serial firmware dump
guide](../guide/serial_dump.md) for preparing the bootloader, rebuilding an
original image, and SWD recovery.

## Other options

| Flag | Effect |
|------|--------|
| `--info` | Show device identity and exit |
| `--dump FILE` | Read the complete firmware image |
| `--fix-crc` | Recalculate CRC before flashing |
| `--force` | Flash even with bad CRC |
| `--dry-run` | Validate image without writing |
| `--baud auto` | Auto-negotiate transfer speed (default) |
| `--no-reset` | Do not reset device after flash |
| `--no-enter` | Skip bootloader entry (already in BL) |

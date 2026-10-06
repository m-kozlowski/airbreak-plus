# as11_nor_tool

## Name

`as11_nor_tool.py` - inspect and edit Air11 external SPI NOR dumps offline.

## Contents

- [Synopsis](#synopsis)
- [Description](#description)
- [Arguments](#arguments)
- [Options](#options)
- [Layout](#layout)
- [Commands](#commands)
  - [info / region-list](#info--region-list)
  - [region-get](#region-get)
  - [key-list / key-get / key-set](#key-list--key-get--key-set)
  - [fat-ls / fat-get / fat-getdir / fat-put / fat-putdir](#fat-ls--fat-get--fat-getdir--fat-put--fat-putdir)
  - [upgrade-info / upgrade-get](#upgrade-info--upgrade-get)
  - [extract-volume](#extract-volume)
- [Output](#output)
- [Exit Status](#exit-status)
- [Examples](#examples)
- [See Also](#see-also)

## Synopsis

```text
as11_nor_tool.py IMAGE COMMAND [ARGUMENTS] [OPTIONS]
```

## Description

Reconstructs logical volumes from wear-levelled NOR storage. Inspects geometry
and CRCs, extracts raw regions and FAT files, imports files and directory
trees, reads and replaces the OTA key, extracts staged upgrades, and exports
volumes as mountable FAT images.

## Arguments

`IMAGE`: complete 16 MiB physical NOR dump or one physical-volume dump from
[`as11_flash.py service read-nor`](as11_flash.md#read-storage). Single-volume
dumps are identified by size: settings 384 KiB, datalog 10,304 KiB, upgrade
5,632 KiB. Use the same volume names in commands; offsets are relative to the
input file. Keys and raw security/manufacturing regions require a full dump.

## Options

Options follow the command.

| Option | Commands | Meaning |
|--------|----------|---------|
| `--json` | `info`, `region-list`, `key-list`, `upgrade-info`, `fat-ls` | JSON output |
| `-o`, `--output FILE` | `key-set`, `fat-put`, `fat-putdir` | Write a modified copy; default: update `IMAGE` in place |
| `-o`, `--output FILE` | `key-get` | Write the key as hex text to FILE |
| `--key-file FILE` | `key-set` | Read a 32-byte key or hex text |
| `-r`, `--recursive` | `fat-ls` | Recurse into subdirectories |
| `-h`, `--help` | All | Show help |

## Layout

The first 64 KiB erase block holds raw security and manufacturing data. The
rest is split into three Micrium uC/FS NOR devices:

| Device | Physical range | Logical filesystem |
|--------|----------------|--------------------|
| `nor:0` | `0x010000..0x06ffff` | settings |
| `nor:1` | `0x070000..0xa7ffff` | datalog |
| `nor:2` | `0xa80000..0xffffff` | firmware upgrade staging |

Named raw regions:

| Name | Offset | Size | Alias |
|------|-------:|-----:|-------|
| `security-data` | `0x000000` | `0x200` | `security` |
| `auth-key-ring` | `0x000000` | `0x100` | `auth-keys` |
| `ota-key` | `0x000100` | `0x20` | `ota` |
| `steehl-security-data` | `0x000180` | `0x80` | `steehl-security` |
| `manufacturing-data` | `0x00e000` | `0x400` | `md0`, `_md0` |
| `manufacturing-test-record` | `0x00f000` | `0x400` | `md1`, `_md1` |

## Commands

### info / region-list

```text
info [--json]
region-list [--json]
```

`info` reports FTL geometry, erase-count range, sector-state counts, logical
mapping coverage, CRC errors, and FAT geometry per volume. `region-list` lists
named raw regions with offsets and sizes.

```sh
as11_nor_tool.py nor.bin info
as11_nor_tool.py nor.bin region-list
```

### region-get

```text
region-get REGION OUTPUT
```

Extract the raw `REGION` named in [Layout](#layout) to `OUTPUT`, or `-` for
stdout.

```sh
as11_nor_tool.py nor.bin region-get md0 MD0.bin
```

### key-list / key-get / key-set

```text
key-list [--json]
key-get NAME [-o FILE]
key-set NAME HEX64 [-o FILE]
key-set NAME --key-file FILE [-o OUTPUT]
```

`NAME` selects a key; currently only `OTA` has a confirmed name and range.
`HEX64` is a 32-byte key as 64 hexadecimal digits. `key-list` lists key names
and status without printing key material; `key-get` prints the key as uppercase
hex or writes it to `-o FILE`; `key-set` replaces it from `HEX64` or
`--key-file`. A key of all zero or all `FF` bytes is rejected.

```sh
as11_nor_tool.py nor.bin key-get OTA
as11_nor_tool.py nor.bin key-set OTA --key-file ota-key.txt -o nor-with-key.bin
```

Key storage and authenticated upgrades are described in the
[OTA protocol](../as11/ota_protocol.md#retrieving-the-local-ota-key).

### fat-ls / fat-get / fat-getdir / fat-put / fat-putdir

```text
fat-ls VOLUME [PATH] [-r] [--json]
fat-get VOLUME PATH OUTPUT
fat-getdir VOLUME PATH DIRECTORY
fat-put VOLUME INPUT PATH [-o OUTPUT]
fat-putdir VOLUME DIRECTORY PATH [-o OUTPUT]
```

Requires `pyfatfs`. `VOLUME` accepts `settings`, `datalog`, `upgrade`, a numeric
index, or the native `nor:N` name. `PATH` addresses a file or directory inside
the volume.

| Command | Operation |
|---------|-----------|
| `fat-ls` | List a directory; default path `/` |
| `fat-get` | Extract a file; `OUTPUT=-` writes to stdout |
| `fat-getdir` | Extract a directory tree |
| `fat-put` | Write a file; `INPUT=-` reads from stdin |
| `fat-putdir` | Copy a directory tree, creating directories and replacing matching files |

```sh
as11_nor_tool.py nor.bin fat-ls datalog / -r
as11_nor_tool.py nor.bin fat-get datalog /Summary.bin Summary.bin
as11_nor_tool.py nor.bin fat-put settings BGL.set /SETTINGS/BGL.set -o updated.bin
```

<a id="staged-upgrade"></a>

### upgrade-info / upgrade-get

```text
upgrade-info [--json]
upgrade-get OUTPUT
```

`/UPGRADE/Upgrade.abc` is a fixed-size staging file with a four-byte used-size
prefix. `upgrade-info` inspects the embedded OTA container; `upgrade-get`
extracts it to `OUTPUT` (`-` for stdout).

```sh
as11_nor_tool.py nor.bin upgrade-info
as11_nor_tool.py nor.bin upgrade-get staged.abc
```

### extract-volume

```text
extract-volume VOLUME OUTPUT
```

Reconstruct the logical block device `VOLUME` into `OUTPUT` (`-` for stdout),
starting with its FAT boot sector. `VOLUME` accepts the same names as `fat-*`.
There is no whole-volume import; use `fat-put` or `fat-putdir` to change files
in the image.

```sh
as11_nor_tool.py nor.bin extract-volume settings settings.fat
```

## Output

Listings are text tables, or JSON with `--json`. Errors go to stderr.

Dumps and extracts contain unit-specific security, manufacturing, and therapy
data; treat them as private.

## Exit Status

| Status | Meaning |
|--------|---------|
| `0` | Operation completed |
| `1` | Image, filesystem, key, or file error |
| `2` | Invalid command-line syntax |

## Examples

Extract the OTA key from a dump and store it for a paired BLE device:

```sh
as11_nor_tool.py nor.bin key-get OTA -o ota-key.txt
as11_config.py devices ota-key bedroom --key-file ota-key.txt
```

Extract the staged upgrade container and inspect it:

```sh
as11_nor_tool.py nor.bin upgrade-get staged.abc
as11_flash.py info staged.abc
```

## See Also

[as11_flash service commands](as11_flash.md#bootloader-service),
[OTA protocol](../as11/ota_protocol.md).

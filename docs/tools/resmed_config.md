# resmed_config

## Name

`resmed_config.py` - read, write, and stream Air 10 / S9 variables.

## Contents

- [Synopsis](#synopsis)
- [Description](#description)
- [Options](#options)
- [Connection](#connection)
  - [`ecp:` backend](#ecp-backend)
- [Commands](#commands)
  - [info](#info)
  - [get](#get)
  - [set / setv](#set--setv)
  - [dump / restore](#dump--restore)
  - [list](#list)
  - [known](#known)
  - [raw](#raw)
  - [stream](#stream)
  - [caps](#caps)
  - [custom-settings](#custom-settings)
  - [errors](#errors)
  - [calibration eeprom](#calibration-eeprom)
- [Variable groups](#variable-groups)
- [Output](#output)
- [Files](#files)
- [Exit Status](#exit-status)
- [Examples](#examples)
- [See Also](#see-also)

## Synopsis

```text
resmed_config.py [OPTIONS] COMMAND [ARGUMENTS]
resmed_config.py -p PORT [OPTIONS] COMMAND [ARGUMENTS]
```

## Description

Reads and writes variables as raw or scaled values, saves and restores
configuration snapshots, decodes live streams, and queries variable limits and
custom-setting metadata. Provides EEPROM backup, restore, and maintenance
operations, offline variable lookup, SD-card settings-file editing, and Air 10
SD error-log reading.

## Options

Global options precede the command.

| Option | Meaning | Default |
|--------|---------|---------|
| `-p`, `--port PORT` | Serial port, `tcp:host[:port]`, or `ecp:path` | Required except for `list`, `known`, and `errors --sd` |
| `--tcp-mode MODE` | `raw`, `transparent`, or `text` | `text` |
| `--baud BAUD` | `auto`, `57600`, `115200`, or `460800` | `auto` |
| `-v`, `--verbose` | Include variable descriptions | Off |
| `-h`, `--help` | Show help | -- |

## Connection

| `PORT` | Target |
|--------|--------|
| Serial device path | Direct UART or USB-UART adapter |
| `tcp:HOST[:PORT]` | AirBridge TCP bridge |
| `ecp:PATH` | SD-card settings file or directory |

### `ecp:` backend

Reads assignments from `Settings.ecp`, appends setting changes, and updates
`Settings.crc` on close. `PATH` selects an existing file or the SD card's
`SETTINGS` directory. The device applies the changes on the next card mount.
Live streaming, raw UART commands, custom-setting metadata, and calibration
operations require a device connection.

## Commands

### info

```text
info
```

Show device identity: BID, SID, serial number, and product name.

```sh
resmed_config.py -p /dev/ttyACM0 info
```

### get

```text
get TARGET ...
```

Read variables selected by each `TARGET`: a variable tag, group name, or
`all`. Group names are listed under [Variable groups](#variable-groups).

```sh
resmed_config.py -p /dev/ttyACM0 get IPC MPA MPI
resmed_config.py -p /dev/ttyACM0 get MGL
```

### set / setv

```text
set VAR VALUE [VAR VALUE ...]
setv VAR VALUE [VAR VALUE ...]
```

Write one or more `VAR`/`VALUE` pairs. `VAR` is a variable tag. For numeric
variables, `set` accepts raw hexadecimal values and `setv` accepts scaled
numbers or enum labels. String variables take text values.

```sh
resmed_config.py -p /dev/ttyACM0 set IPC 01F4
resmed_config.py -p /dev/ttyACM0 setv IPC 10.0 MOP AutoSet
```

### dump / restore

```text
dump -o FILE [OPTIONS]
restore -i FILE [OPTIONS]
```

`dump` writes a JSON configuration snapshot to host file `FILE`; `restore`
applies settings from that file.

| Option | Commands | Meaning |
|--------|----------|---------|
| `-o`, `--output FILE` | `dump` | Required JSON output path |
| `-i`, `--input FILE` | `restore` | Required JSON input path |
| `--groups GROUP ...` | `dump` | Include only selected groups; default: all |
| `--exclude-groups GROUP ...` | `dump`, `restore` | Omit selected groups |
| `--exclude-vars VAR ...` | `dump`, `restore` | Omit selected variables |
| `--dry-run` | `restore` | Preview setting changes |

```sh
resmed_config.py -p /dev/ttyACM0 dump --groups MGL EGL -o therapy.json
resmed_config.py -p /dev/ttyACM0 restore -i config.json --exclude-groups BGL
```

### list

```text
list [--groups GROUP ...]
```

List known variables and descriptions offline.

| Option | Meaning | Default |
|--------|---------|---------|
| `--groups GROUP ...` | Select [variable groups](#variable-groups) | All groups |

```sh
resmed_config.py list --groups MGL DGL
```

### known

```text
known [REGISTRY [PATTERN]]
```

Look up names offline. `REGISTRY` selects `vars`, `groups`, or `enums`;
the default is to list registries. `PATTERN` is a substring filter for `vars`,
a group name for `groups`, or a variable tag for `enums`.

```sh
resmed_config.py known vars EPR
resmed_config.py known enums MOP
```

### raw

```text
raw COMMAND ...
```

Join `COMMAND` words with spaces and send the resulting UART command to the
device. Quote text containing shell metacharacters such as `#`.

```sh
resmed_config.py -p /dev/ttyACM0 raw 'G S #BID'
```

### stream

```text
stream TAG ... [--raw] [--duration SECONDS]
```

Subscribe to the `L`-frame channels selected by `TAG`, splitting, naming, and
scaling known fields by default.

| Option | Meaning | Default |
|--------|---------|---------|
| `--raw` | Print unchanged `L` payloads, including internal channels `RAW` and `FTX` | Off |
| `--duration SECONDS` | Capture length | Until Ctrl-C |

Patched firmware supplies its active layout through `G C &TAG`; stock
layouts are selected from ResScan metadata using MID and VID. The command
disables the channels it enabled on exit. AirBridge requires
`--tcp-mode transparent`; text mode handles one command response at a time.

```sh
resmed_config.py -p /dev/ttyACM0 stream RAW FTX --raw
resmed_config.py -p tcp:airbridge-host --tcp-mode transparent stream PMD PBT BRH --duration 30
```

### caps

```text
caps [TARGET ...]
```

Query variable values and limits from the device.

Each `TARGET` is a variable tag, group name, or `all`; default: `all`.

```sh
resmed_config.py -p /dev/ttyACM0 caps IPC MOP EPR
```

### custom-settings

```text
custom-settings
```

Show the custom variables exposed by Airbreak-patched firmware, including
localized labels, categories, mode masks, current values, display metadata,
and stock variable capabilities.

This command requires the UART metadata patch and a live serial or transparent
TCP connection. See the [serial protocol](../serial_protocol.md#custom-settings-registry)
for the underlying `G C &CSG` records.

```sh
resmed_config.py -p /dev/ttyACM0 custom-settings
```

### errors

```text
errors --sd PATH [--logs TAG ...] [--summary] [--order time|record] [--json]
```

Read Air 10 fault and activity history from SD-card log files, without a
device connection. `PATH` accepts the card root, its `SETTINGS` directory,
or a single `.log` file.

| Option | Meaning | Default |
|--------|---------|---------|
| `--sd PATH` | Log file or directory to read | Required |
| `--logs TAG ...` | Select logs by name, case-insensitive | All available logs |
| `--summary` | Show one row per code, with record count and first/last timestamps | Off |
| `--order time\|record` | Sort by date, or keep write order within each log | `time` |
| `--json` | Write records, file metadata, warnings, and errors as JSON to stdout | Off |

`TAG` is the log filename without `.log`: use `ERR` for `ERR.log`, not
`AER`. The `Var` column names the variable recorded in that log; for example,
`ERR` records `AER`, and `DLL` records `DLA`.

| Log | Contents |
|-----|----------|
| `ABR` | Fatal application errors |
| `ERR` | Firmware diagnostic codes, including SD, storage, and restart errors |
| `ELI` | Saved exception addresses |
| `TXC` | Humidifier faults |
| `TXH` | Heated-tube faults |
| `TXE`, `TXW` | System faults |
| `TRR` | Transient alarms and peripheral communication errors |
| `ZRL` | Saved system-error state |
| `DLL` | Therapy and mask-on/off transitions, dial and button actions, menu navigation, SD-card insertion/removal, and humidifier state changes |

Summarize faults without listing the activity log:

```sh
resmed_config.py errors --sd /media/RESMED --logs ABR ERR TXC TXH TXE TXW TRR --summary
```

Read a single log or export the complete history:

```sh
resmed_config.py errors --sd ./SETTINGS/TXC.log
resmed_config.py errors --sd ./SETTINGS --json > errors.json
```

Timestamps use the device clock. Use `--order record` to follow the recorded
sequence when the clock has been changed. Only retained history is available;
the device overwrites the oldest records when a log fills. Summary counts
refer to stored records, not a sum of `NOC`.

JSON retains per-file write order regardless of `--order`. With `--summary`,
it includes both individual records and grouped counts.

Unreadable or invalid files and missing requested logs produce exit status
`1`; other selected files are still read.

### calibration eeprom

```text
calibration eeprom ACTION [--yes] [--really] [--timeout SECONDS]
```

Run the stock firmware EEPROM/SD maintenance service (`CAL=000B`) from the
normal UART variable protocol, using fixed paths on the device's SD card
rather than host files.

The command enters calibration mode with `ROP=0004`, selects `CAL=000B`, starts
the selected `ETR` command, polls until `ETR=0000`, then restores the original
`CAL` and `ROP` values. An unfinished operation retains its `ETR` value.

| Option | Meaning | Default |
|--------|---------|---------|
| `--yes` | Confirm restore/import operations | Off |
| `--really` | Additional confirmation for erase/format; requires `--yes` | Off |
| `--timeout SECONDS` | Wait for `ETR=0000` | `300` |

| Action | `ETR` | Firmware behavior |
|--------|-------|-------------------|
| `sd-backup-raw` | `0003` | copy all 512 raw EEPROM pages to `mmc:0:EEPROM\EEPROM.dat` |
| `sd-restore-raw` | `0004` | restore complete 512-byte pages from `mmc:0:EEPROM\EEPROM.dat` |
| `sd-export-tree` | `0005` | copy `eep:0:` root files and one directory level to `mmc:0:EEPROM` |
| `sd-import-tree` | `0006` | copy the root, `DATALOG`, `ERRORLOG`, and `SETTINGS` directories back to `eep:0:` |
| `erase-logical-pages` | `0001` | zero raw EEPROM pages 0 through 501; requires `--yes --really`; destroys unit-specific EEPROM data |
| `format-eep-fat` | `0002` | formats/reinitializes the `eep:0` FAT filesystem; requires `--yes --really`; destroys unit-specific EEPROM data |

```sh
resmed_config.py -p /dev/ttyACM0 calibration eeprom sd-backup-raw
resmed_config.py -p /dev/ttyACM0 calibration eeprom sd-import-tree --yes
```

## Variable groups

| Group | Content |
|-------|---------|
| AGL | AutoSet params |
| BGL | Board identity and calibration |
| CGL | CPAP params |
| DGL | Bilevel timing |
| EGL | EPR params |
| IGL | Bilevel pressure |
| MGL | Machine settings |
| NGL | Backlight settings |
| PGL | Peripherals/accessories |
| QXH | ASVAuto params |
| QXJ | iVAPS params |
| RGL | Reminders/replacement |
| SGL | System settings |
| UGL | Usage data |
| VGL | VAuto params |
| XGL | ASV fixed params |

This table describes stock variable meanings. Images built with
`custom_settings` reuse selected Reminder variables but keep their UART names,
so `resmed_config` continues to list them under its static `RGL` group.
Device-side persistence for those values moves to `CSG.set`; see
[Custom settings](../custom_settings.md).

## Output

Commands print identity, variable, capability, or status text. `dump` writes
JSON; `restore` reads that format. `stream` prints decoded and scaled fields,
or unchanged `L` payloads with `--raw`.

## Files

| File | Use |
|------|-----|
| `Settings.ecp` | Offline setting changes for the SD-card backend |
| `Settings.crc` | Companion checksum, updated with `Settings.ecp` |
| `dump -o FILE` / `restore -i FILE` | JSON configuration snapshot |

## Exit Status

| Status | Meaning |
|--------|---------|
| `0` | Command completed |
| `1` | Missing target, connection failure, invalid value, or failed operation |
| `2` | Invalid command-line syntax |

## Examples

Save settings, preview their restoration, then restore them:

```sh
resmed_config.py -p /dev/ttyACM0 dump -o config.json
resmed_config.py -p /dev/ttyACM0 restore -i config.json --dry-run
resmed_config.py -p /dev/ttyACM0 restore -i config.json
```

Prepare an SD-card assignment and inspect the stored value:

```sh
resmed_config.py -p ecp:/sdcard/SETTINGS/ set PNA AirSense_10_airbreak
resmed_config.py -p ecp:/sdcard/SETTINGS/ get PNA
```

## See Also

[Serial protocol](../serial_protocol.md), [custom settings](../custom_settings.md),
[eeprom_tool](eeprom_tool.md), [resmed_flash](resmed_flash.md).

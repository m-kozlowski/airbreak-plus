# as11_config

## Name

`as11_config.py` - configure Air11 devices and access RPC, streams, events, and spools.

## Contents

- [Synopsis](#synopsis)
- [Description](#description)
- [Arguments](#arguments)
  - [JSON input](#json-input)
  - [Time input](#time-input)
- [Options](#options)
- [Connection](#connection)
- [Commands](#commands)
  - [get](#get)
  - [set](#set)
  - [rpc](#rpc)
  - [reset](#reset)
  - [gettime / settime](#gettime--settime)
  - [session](#session)
  - [stream / subscribe](#stream--subscribe)
  - [spool](#spool)
  - [known](#known)
  - [devices](#devices)
- [Output](#output)
- [Environment](#environment)
- [Files](#files)
- [Exit Status](#exit-status)
- [Examples](#examples)
- [See Also](#see-also)

## Synopsis

```text
as11_config.py -d DEVICE [OPTIONS] COMMAND [ARGUMENTS]
as11_config.py known [REGISTRY [PATTERN]] [OPTIONS]
as11_config.py devices [COMMAND [ARGUMENTS]]
as11_config.py spool [TYPE] --input FILE [OPTIONS]
```

## Description

Reads and writes settings, calls JSON-RPC methods, streams measurements, and
subscribes to events and value changes. Downloads and decodes historical spools
(waveforms, profile snapshots, diagnostic errors), manages BLE pairing,
aliases, and OTA keys, and looks up variables, groups, and selectors offline.

## Arguments

### JSON input

`set --json JSON`, `rpc --params JSON`, and `rpc --batch JSON` accept a literal JSON value,
`-` for stdin, or `@PATH` for a file. `set --json` requires an object
mapping setting names to values.

### Time input

`settime TIME` and `spool --from-dt TIME` accept:

| Form | Interpretation |
|------|----------------|
| ISO 8601 timestamp | Explicit timezone, or host local time when omitted |
| `YYYY-MM-DD`, `YYYY/MM/DD`, `DD.MM.YYYY`, `DD-MM-YYYY`, `DD/MM/YYYY` | Local midnight |
| `HH:MM[:SS]` | Today at the given local time |
| 10- or 11-digit integer | Unix epoch seconds |
| `+Ns`, `-Nm`, `+Nh`, `-Nd` | Offset from now; either sign with seconds, minutes, hours, or days |
| `now` | Current host time |

Quote timestamps containing spaces. Use `--from-dt=-7d` for a negative
spool offset; for a positional value use `settime -- -30m`.

## Options

Device and logging options are accepted before or after the command. RPC
options belong to commands that contact a device.

| Option | Meaning | Default |
|--------|---------|---------|
| `-d`, `--device TARGET` | Transport and target; see [Connection](#connection) | `AS11_DEVICE` |
| `--addr ADDRESS` | Compatibility shortcut for `-d ble:ADDRESS` | None |
| `-p`, `--port PORT` | Compatibility shortcut for `-d can:PORT` | None |
| `--can-flavour NAME` | `slcan`, `socketcan`, or `waveshare`; `canable` aliases `slcan` | Inferred from target |
| `--can-frame-interval-ms MS` | CAN frame transmit interval in milliseconds | Legacy SLCAN: `0.25`; Elmue/SocketCAN: `0`; Waveshare: `2` |
| `--timeout SECONDS` | RPC response timeout | `5` |
| `-v`, `--verbose` | Transfer and informational logging | Off |
| `--debug` | Packet-level logging | Off |
| `-h`, `--help` | Show help | -- |

`set` consumes trailing name/value arguments itself: place common options before
the first pair. `devices scan --timeout` instead controls scan duration.

## Connection

| Target | Transport |
|--------|-----------|
| `ble:MAC`, `ble:UUID`, `ble:ALIAS` | BLE; stored pairing or [devices pair](#devices) |
| `can:TARGET` | CAN adapter or SocketCAN interface |
| `tcp:HOST[:PORT]` | AirCANnect TCP bridge; default port `39011` |

`can0`, `vcan0`, and `slcan0` select SocketCAN. Serial targets such as
`/dev/ttyACM0`, `/dev/ttyUSB0`, and `COM3` select SLCAN. Waveshare requires
explicit selection. The same syntax applies to [AS11_DEVICE](#environment).

## Commands

### get

```text
get [NAME ...] [--group GROUP]...
get --list-groups
```

Read variables selected by `NAME` or `--group GROUP`. Supply at least one name
or group. `NAME` accepts a protocol long name, short tag (with or without the
leading `_`), or one of the three-character CONF groups.

| Option | Meaning |
|--------|---------|
| `-g`, `--group NAME` | Expand a named group; repeatable |
| `--list-groups` | List group sizes offline |

CONF groups `BGL`, `DDO`, `DID`, `HST`, `MCA`, `MCF`, `TLP`, and `PDL` may be
passed directly; other named groups require `--group`. Use `known groups
<group>` to list members. See [CONF g[6] and g[7]](../as11/conf_block_format.md#g6----external-nor-settingsgroup-schemas).

```sh
as11_config.py -d ble:as11 get SerialNumber MOP GOM
as11_config.py -d ble:as11 get --group DeviceConfiguration
```

### set

```text
set NAME VALUE [--type TYPE] [NAME VALUE [--type TYPE] ...]
set --json JSON
```

Write `NAME`/`VALUE` pairs using the `Set` RPC. `NAME` identifies a setting by
protocol long name or short tag. `--type TYPE` follows the pair it modifies.
`set --json` supplies the entire mapping using [JSON input](#json-input).

| Type | Value |
|------|-------|
| `str` | String; default |
| `int` | Decimal integer |
| `float` | Floating-point number |
| `bool` | `true`, `yes`, `1`, `false`, `no`, or `0`; case-insensitive |
| `json` | JSON literal |

```sh
as11_config.py -d ble:as11 set Cpap-SetPressure 10 --type float RampEnable On
as11_config.py -d ble:as11 set --json '{"Cpap-SetPressure":10}'
```

### rpc

```text
rpc --method NAME [--params JSON]
rpc --batch JSON
```

Call a JSON-RPC method or send a batch over CAN, BLE, or TCP.

| Option | Meaning |
|--------|---------|
| `--method NAME` | Method name; mutually exclusive with `--batch` |
| `--params JSON` | Method parameters; see [JSON input](#json-input); omitted by default |
| `--batch JSON` | Array of complete request envelopes, including each request's `jsonrpc`, `method`, `id`, and optional `params` |

```sh
as11_config.py -d ble:as11 rpc --method GetVersion
as11_config.py -d ble:as11 rpc --method Get --params '["SerialNumber"]'
as11_config.py -d ble:as11 rpc --batch '[
  {"jsonrpc":"1.0","id":101,"method":"GetDateTime"},
  {"jsonrpc":"1.0","id":102,"method":"Get","params":["_MOP"]}
]'
```

Batch output is the first response document containing a matching ID. Denied
requests may be omitted; asynchronous replies may arrive later. IDs must be
unique within the batch. Notifications omit `id`; a notification-only batch
returns `[]` after sending.

### reset

```text
reset [MODE]
```

Call `ResetDevice` with `type=MODE`; default: `Fast`.

`MODE` accepts `Off`, `TriggerWatchdog`, `Fast`, or `TriggerPowerLoss`.
See [reset modes](../as11/rpc_protocol.md#resetdevice) for their behavior.

```sh
as11_config.py -d can:can0 reset
as11_config.py -d can:can0 reset TriggerWatchdog
```

### gettime / settime

```text
gettime
settime [TIME] [--dry-run]
```

Read or set the device clock. `settime` defaults to the current host time; see
[Time input](#time-input) for `TIME`. `--dry-run` previews the payload offline.

```sh
as11_config.py -d ble:as11 gettime
as11_config.py -d ble:as11 settime +1h --dry-run
```

### session

Open an interactive CLI and keep the transport open across commands. Interactive
commands use the same syntax and options as normal commands; `help [COMMAND]`
shows command help, and `quit`, `exit`, or `q` closes the session.

`SubscribeEvent` subscriptions end with their RPC connection, so after an
interactive `subscribe` the session reconnects before the next prompt.

```sh
as11_config.py -d ble:as11 session
```

### stream / subscribe

```text
stream [--data-ids ID,...] [--edf ALIAS,...] [OPTIONS]
subscribe [SELECTOR ...] [--events LABEL,...] [--duration SECONDS]
```

`stream` receives sampled measurements; `subscribe` receives event and DataItem
notifications. Output is NDJSON. `SELECTOR` is an exact event-family selector or
DataItem name; DataItems produce an initial value followed by `ValueChange`
notifications. With no selector, `subscribe` sends an empty `dataIds` list.

| Option | Command | Meaning / default |
|--------|---------|-------------------|
| `--data-ids ID,...` | `stream` | Explicit data IDs |
| `--edf ALIAS,...` | `stream` | Expand EDF aliases; may combine with `--data-ids` |
| `--sample-ms MS` | `stream` | `10` with no selectors, fastest selected alias period for `--edf` alone, otherwise `200` |
| `--report-ms MS` | `stream` | Default `5 * sampleIntervalMs` |
| `--events LABEL,...`, `--event LABEL,...` | `subscribe` | Resolve payload labels to event selectors |
| `--duration SECONDS` | Both | Stop after the duration; default until Ctrl-C |

Without `--data-ids` or `--edf`, `stream` requests all `BRP`, `PLD`, `SA2`, and
`TCV` alias data IDs. Sample intervals are `10..65000 ms`, report intervals
`10..300000 ms`, both rounded down to `10 ms`; the report interval must be one
to five sample intervals, and one stream carries at most 30 data IDs. See the
[stream mappings](../as11/rpc_streams.md) and [event selectors](../as11/rpc_events.md).

```sh
as11_config.py -d can:can0 stream --edf BRP,PLD --sample-ms 40
as11_config.py -d ble:as11 subscribe UsageEvents-TherapyStatusEvents --duration 60
```

### spool

```text
spool TYPE [OPTIONS]
spool [TYPE] --input FILE [OPTIONS]
spool --list-types
```

Download and decode spool data. `TYPE` is a spool name from `--list-types`;
live downloads require it, offline decoding detects it from `FILE`.

| Option | Meaning | Default |
|--------|---------|---------|
| `--from-dt TIME` | Earliest record timestamp; see [Time input](#time-input) | All records |
| `--max-size BYTES` | Unencoded payload ceiling per round | `4096` |
| `--max-rounds N` | Maximum continuation rounds | Unlimited |
| `--no-follow` | Stop after the first round | Off |
| `--fragment-timeout SECONDS` | Deadline for a round's fragments; separate from `--timeout` | `30` |
| `--fragment-max BYTES` | Requested fragment size | `3000`; device ceiling `3576` |
| `--format FORMAT` | `table`, `json`, `csv`, or `summary` | `table` |
| `--details` | Event interpretations and unknown fields below the table; table only | Off |
| `--no-decode` | Raw download; exclusive with `--input`, `--format`, `--details` | Off |
| `--app-version VERSION` | Diagnostic error-map version | Queried live; all bundled maps offline |
| `-i`, `--input FILE` | Decode a captured payload offline | None |
| `-o`, `--output FILE` | Save the downloaded raw payload; exclusive with `--input` | None |
| `--list-types` | List spool types offline | Off |

Downloads follow continuation addresses automatically and validate fragment
order and the terminal SHA-256 each round. `--format` selects the presentation:

| Format | Output |
|--------|--------|
| `table` | Terminal-oriented record, event, metric, and sample tables |
| `json` | Complete decoded model |
| `csv` | Decoded model flattened to `path,value` rows |
| `summary` | Compact record, event-count, or sample-range summary |

`--no-decode` output is a Base64 envelope with transfer metadata. Payload
semantics are in the [spool reference](../as11/rpc_spools.md).

```sh
as11_config.py -d ble:as11 spool Summary --from-dt=-7d
as11_config.py -d ble:as11 spool DiagnosticExceptionEvents-AppErrors --details
```

### known

```text
known [REGISTRY [PATTERN]] [--selector TEXT]
```

Offline listing of the known registries.
`REGISTRY` selects `vars`, `groups`, `subtrees`, `streams`, `edf`, `events`, or
`spools`; the default lists registries. `PATTERN` filters the chosen registry,
selects a group, or selects EDF aliases for `streams`. `--selector TEXT`
filters selector names in `known events`.

`known subtrees` prints the non-DataItem selectors accepted by `Get` (see the
[Get input reference](../as11/rpc_get_inputs.md)). `known streams <EDF>` prints
the data IDs behind an alias. `known events <text>` resolves payload event
labels to the selector to subscribe.

```sh
as11_config.py known groups HST
as11_config.py known events PressureStart
```

### devices

```text
devices [list]
devices scan [--timeout SECONDS] [--all]
devices pair TARGET [--passkey CODE]
devices alias TARGET NAME
devices unalias NAME
devices ota-key TARGET [KEY | --key HEX64 | --key-file FILE | --clear]
```

BLE device management.
`TARGET` is a BLE address, UUID, or stored alias. `KEY` and `HEX64` accept 64
hexadecimal digits; `FILE` contains 32 raw bytes or hex text.

| Command | Operation |
|---------|-----------|
| `scan` | List BLE advertisements; `--timeout` defaults to 10 s; `--all` removes filters |
| `list` | List stored devices; default subcommand |
| `pair` | Pair with a device; prompts when the passkey is omitted |
| `alias` | Assign an alias |
| `unalias` | Remove an alias |
| `ota-key` | Store a key, remove it with `--clear`, or report its status by default |

```sh
as11_config.py devices pair AA:BB:CC:DD:EE:FF
as11_config.py devices ota-key bedroom --key-file ota-key.hex
```

## Output

`get`, `set`, `rpc`, `gettime`, and `settime` print JSON responses. `stream` and
`subscribe` print one notification per line (NDJSON); setup responses and
transfer diagnostics go to stderr. `known` and `devices` print text tables.
Spool formats are listed under [spool](#spool).

## Environment

| Variable | Meaning |
|----------|---------|
| `AS11_DEVICE` | Optional target in `-d` format; explicit `-d`, `--addr`, or `--port` takes precedence |
| `AS11_SESSION_HISTORY` | Override the interactive history file |
| `XDG_STATE_HOME` | History directory base when `AS11_SESSION_HISTORY` is unset |

## Files

| File | Use |
|------|-----|
| `~/.as11_ble.json` | Pairing credentials, aliases, and optional OTA keys |
| `$XDG_STATE_HOME/airsense11/as11_config_history` | Session history when `XDG_STATE_HOME` is set |
| `~/.as11_config_history` | Default session history path |
| `spool -o FILE` / `spool -i FILE` | Raw binary spool payload |
| `--params @PATH` / `--json @PATH` | JSON RPC parameters |
| `devices ota-key --key-file FILE` | 32 raw key bytes or hex text |

## Exit Status

| Status | Meaning |
|--------|---------|
| `0` | Command completed; returned JSON may still contain an RPC `error` |
| `1` | Target, transport, timeout, spool, or processing error |
| `2` | Invalid command-line syntax or argument type |
| `130` | Unhandled Ctrl-C; `stream` and `subscribe` handle Ctrl-C and return `0` |

## Examples

Capture a spool raw, then decode it offline later:

```sh
as11_config.py -d ble:as11 spool Summary --from-dt=-7d -o summary.bin
as11_config.py spool --input summary.bin
```

Pair a device, alias it, then read by alias:

```sh
as11_config.py devices pair AA:BB:CC:DD:EE:FF
as11_config.py devices alias AA:BB:CC:DD:EE:FF bedroom
as11_config.py -d ble:bedroom get SerialNumber
```

Decode captured diagnostic errors with a specific firmware map:

```sh
as11_config.py spool DiagnosticExceptionEvents-AppErrors --input app-errors.bin \
    --app-version 8.4.0
```

## See Also

[RPC protocol](../as11/rpc_protocol.md), [RPC streams](../as11/rpc_streams.md),
[RPC events](../as11/rpc_events.md), [RPC spools](../as11/rpc_spools.md),
[as11_flash](as11_flash.md), [as11_descriptors](as11_descriptors.md).

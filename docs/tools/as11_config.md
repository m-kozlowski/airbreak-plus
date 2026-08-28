# as11_config

Configuration, RPC, and data access tool for Air11 devices.

Read and write settings, call JSON-RPC methods, stream live data, subscribe to events, download spool data, and manage BLE [pairing aliases](#devices).

## Connection

BLE:
```
as11_config.py -d ble:alias get SerialNumber
as11_config.py -d ble:AA:BB:CC:DD:EE:FF get SerialNumber
```

CAN:
```
as11_config.py -d can:/dev/ttyACM0 get SerialNumber
as11_config.py -d can:slcan0 --can-flavour socketcan get SerialNumber
```

Prefer `-d ble:...` and `-d can:...` to select the transport target. `--addr` and `-p/--port` are compatibility shortcuts, and `AS11_ADDR` and `AS11_CAN_PORT` are also supported.

## Commands

### get

Read one or more variables by name or group.

```
as11_config.py -d ble:as11 get SerialNumber
as11_config.py -d ble:as11 get MOP GOM TOM
as11_config.py -d ble:as11 get --group DeviceConfiguration
as11_config.py -d ble:as11 get HST
as11_config.py -d ble:as11 get SerialNumber --group Network
```

Three-character variable tags may be passed with or without the leading `_`.

Three-character CONF groups may be passed directly or through `--group`:
`BGL`, `DDO`, `DID`, `HST`, `MCA`, `MCF`, `TLP`, and `PDL`. Other named groups
require `--group`. Use `--list-groups` to list group sizes and
`known groups <group>` to list members. The CONF groups are described in
[CONF g[6] and g[7]](../as11/conf_block_format.md#g6----external-nor-settingsgroup-schemas).

### set

Write one or more settings using the `Set` RPC. Values default to strings unless `--type` is given.

```
as11_config.py -d ble:as11 set TherapyMode AutoSet
as11_config.py -d ble:as11 set MOP AutoSetProfile
as11_config.py -d ble:as11 set SetPressure 10 --type int RampEnable true --type bool
as11_config.py -d ble:as11 set --json '{"SetPressure":10}'
```

### rpc

Call an arbitrary JSON-RPC method.

```
as11_config.py -d ble:as11 rpc --method GetVersion
as11_config.py -d ble:as11 rpc --method Get --params '["SerialNumber"]'
as11_config.py -d ble:as11 rpc --method SetDateTime --params '{"dateTime":"2026-01-01T00:00:00.000Z"}'
```

### gettime / settime

Read or set the device clock.

```
as11_config.py -d ble:as11 gettime
as11_config.py -d ble:as11 settime
as11_config.py -d ble:as11 settime 2026-01-01T00:00:00Z
as11_config.py -d ble:as11 settime +1h --dry-run
```

### session

Open an interactive CLI and keep the transport open across commands. Interactive
commands use the same syntax and options as normal `as11_config.py` commands;
use `help [COMMAND]` to show their standard help. A nested `session` command is
not accepted.

```
as11_config.py -d ble:as11 session
```

`SubscribeEvent` subscriptions end with their RPC connection. After an
interactive `subscribe` command finishes, the session reconnects before showing
the next prompt.

### stream / subscribe

Receive live NDJSON notifications from the device.

Without `--data-ids` or `--edf`, `stream` requests all EDF alias data IDs
(`BRP`, `PLD`, `SA2`, `TCV`) at the fastest accepted interval:
`sampleIntervalMs=10`, `reportIntervalMs=50`.

```
as11_config.py -d ble:as11 stream
as11_config.py -d can:can0 stream --duration 60
as11_config.py -d can:can0 stream --edf BRP
as11_config.py -d can:can0 stream --edf BRP,PLD --sample-ms 40
as11_config.py -d ble:as11 stream --data-ids Leak-50hz,RespiratoryRate-50hz --duration 60
as11_config.py -d ble:as11 subscribe --duration 60
as11_config.py -d ble:as11 subscribe UsageEvents-TherapyStatusEvents --duration 60
as11_config.py -d ble:as11 subscribe _ROP --duration 60
as11_config.py -d ble:as11 subscribe --events PressureStart --duration 60
```

EDF stream aliases (`BRP`, `PLD`, `SA2`, `TCV`) and their raw data IDs are
listed in [AS11 RPC Stream Reference](../as11/rpc_streams.md).
Event subscription selectors and payload event families are listed in
[AS11 RPC Event Reference](../as11/rpc_events.md). Positional `subscribe`
arguments accept exact event-family selectors or DataItem names. DataItems
produce an initial value followed by `ValueChange` notifications.
`subscribe --events` accepts payload event labels and expands them to the
selector or selectors that carry those events. `--event` is accepted as an
alias for `--events`.

StartStream interval limits verified so far: minimum sample interval is `10 ms`,
intervals are rounded down to a `10 ms` boundary, and `reportIntervalMs` must
not exceed `sampleIntervalMs * 5`.

### spool

Download and decode spool data.

```
as11_config.py -d ble:as11 spool Summary
as11_config.py -d ble:as11 spool TherapyEvents-RespiratoryEvents --format table
as11_config.py -d ble:as11 spool DiagnosticExceptionEvents-AppErrors --details
as11_config.py -d ble:as11 spool RespiratoryFlow6p25Hz --format csv
as11_config.py -d ble:as11 spool Summary --format summary
as11_config.py -d ble:as11 spool Summary --from-dt 2026-08-01
as11_config.py -d ble:as11 spool Summary --from-dt=-7d -o summary.bin
as11_config.py -d ble:as11 spool Summary --no-decode
as11_config.py spool --input summary.bin
as11_config.py spool Summary --input summary.bin
as11_config.py -d ble:as11 spool --list-types
```

Spool types, payload families, and inner record shapes are listed in
[AS11 RPC Spool Reference](../as11/rpc_spools.md).

The tool builds the `spoolAddress` as:

```
{ "<spool type>": { "fromDateTime": "<ISO timestamp>" } }
```

The confirmed spool-address selector is `fromDateTime`. The returned
`nextSpoolAddress` uses the same shape and is followed automatically unless
`--no-follow` is passed.

`--from-dt` accepts a full ISO 8601 timestamp, a local date such as
`2026-08-01`, Unix epoch seconds, or a relative value such as `-7d`, `-12h`,
or `-30m`. Without the option, the tool requests all available records.

Each round validates the fragment sequence and the terminal SHA-256 before
accepting its payload. `--max-size` controls the unencoded payload ceiling per
round. `--fragment-max` defaults to `3000`; the device clamps larger requests
to `3576` bytes. Use `-v` to show transfer rounds, fragments, and hash checks.

Spool payloads are decoded by default. `--format` selects the presentation:

| Format | Output |
|--------|--------|
| `table` | Terminal-oriented record, event, metric, and sample tables; the default. |
| `json` | Complete decoded model. |
| `csv` | Complete model flattened to `path,value` rows. |
| `summary` | Compact record, event-count, or sample-range summary. |

Event tables contain one line per record. Known event-specific values are
included in the `Details` column. `--details` additionally prints diagnostic
interpretations and unrecognized fields below the table.

The complete model includes all decoded samples, raw values, units, timing,
compression metadata, and unrecognized protobuf fields. `--no-decode` instead
returns a JSON envelope containing the payload as Base64 and the transfer
metadata. The `-o` option writes the raw payload to a file; combined with
`--no-decode`, it suppresses payload output on stdout.

Use `-i/--input` to decode a previously captured raw payload without contacting
a device. The spool type is detected from the payload when omitted. Supply it
as the positional argument when the outer protobuf field is ambiguous.

Archived signal spools such as `RespiratoryFlow6p25Hz` include complete RC03
record metadata and both raw and scaled sample arrays.

`SettingProfilesCollection` contains historical active-profile,
therapy-profile, feature-profile, and alarm-profile snapshots. Pressures and
time values include their scaled values and units; enum-like settings retain
their raw values.

`ConfigurationProfilesCollection` contains the configuration
attributes and `DataDeliveryControlV2` spool on/off mask.

`TherapyOneMinutePeriodic` contains one-minute pressure, leak, ventilation,
respiratory-rate, I:E-ratio, and oximetry series when oximetry is present.

Metric snapshots (`MachineMetrics`, `MemoryMetrics`, `CellularDataUsage`)
contain named current snapshot fields where known. `MemoryMetrics` reports
write, erase, and FTL generation counters for the `SETTINGS`, `DATALOG`, and
`UPGRADE` volumes in external NOR flash.

`DiagnosticTenMinutePeriodic` contains ten-minute cellular signal-strength and
signal-quality series.

For `atmosphericPressure10min`, the archive scale is decoded; the physical unit
is not identified.

`SoundcheckVector` contains soundcheck vector bins and peak pairs.

`AcousticSignatureV2` and `RecordedSound` retain their blob data as Base64.
`RecordedSound` is gated by `SoundDownloadAllowed`.

Event records include the numeric type, known event name, start/end timestamps,
duration, and all extra fields.

Diagnostic exception spools use APPX-specific error manifests. Live `spool`
decoding reads `ApplicationIdentifier` automatically. For an offline capture,
pass `--app-version`, or omit it to compare all bundled firmware maps:

```
as11_config.py spool DiagnosticExceptionEvents-AppErrors --input app-errors.bin \
    --app-version 8.4.0
```

The output retains the numeric code and lists every matching direct producer,
producer call site, mapped filesystem status, and recognized NOR/SD volume
monitor. `ResettableErrors` records also include the firmware `SystemError`
symbol. Codes with more than one possible producer are marked `[ambiguous]`.

`Summary` records contain the period range, duration, timezone offset, session
entries, scalar values, and percentile metrics.

### known

Offline listing of known variables, groups, streams, events, and spool types.

```
as11_config.py known
as11_config.py known vars
as11_config.py known groups
as11_config.py known groups HST
as11_config.py known subtrees
as11_config.py known streams
as11_config.py known streams BRP
as11_config.py known streams BRP,SA2
as11_config.py known edf
as11_config.py known events
as11_config.py known events PressureStart
as11_config.py known events --selector SystemActivityEvents-FrequentActivityEvents
as11_config.py known spools
```

`known subtrees` prints the named non-DataItem selectors accepted by
`Get`; their semantics and release-scoped catalog are documented in the
[Air11 RPC Get Input Reference](../as11/rpc_get_inputs.md).
`known streams <EDF>` prints the data IDs behind an EDF stream alias.
`known events` prints `SubscribeEvent` selectors and event label counts.
`known events <text>` resolves payload event labels to the selector that
should be subscribed. `known spools` prints spool types grouped by current
payload-family hints.

### devices

BLE device management: scan, pair, list, alias, unalias, and default OTA-key
storage for paired devices.

```
as11_config.py devices scan
as11_config.py devices pair AA:BB:CC:DD:EE:FF
as11_config.py devices alias AA:BB:CC:DD:EE:FF bedroom
as11_config.py devices ota-key bedroom --key HEXSTR
as11_config.py devices ota-key bedroom --key-file ota-key.hex
as11_config.py devices ota-key bedroom --clear
as11_config.py devices list
```

`devices ota-key` stores the key in the existing BLE credential record. The
normal device list only shows whether an OTA key is configured; it does not
print the key.

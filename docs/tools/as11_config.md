# as11_config

BLE / CAN configuration and data access tool for AirSense 11 / AirCurve 11 series.

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
as11_config.py -d ble:as11 get _MOP _GOM _TOM
as11_config.py -d ble:as11 get --group DeviceConfiguration
as11_config.py -d ble:as11 get SerialNumber --group Network
```

### set

Write one or more settings using the `Set` RPC. Values default to strings unless `--type` is given.

```
as11_config.py -d ble:as11 set TherapyMode AutoSet
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

Open an interactive REPL and keep the transport open across commands.

```
as11_config.py -d ble:as11 session
```

### stream / subscribe

Receive live NDJSON notifications from the device.

Without `--data-ids` or `--edf`, `stream` requests all EDF alias data IDs
(`BRP`, `PLD`, `SA2`) at the fastest accepted interval:
`sampleIntervalMs=10`, `reportIntervalMs=50`.

```
as11_config.py -d ble:as11 stream
as11_config.py -d can:can0 stream --duration 60
as11_config.py -d can:can0 stream --edf BRP
as11_config.py -d can:can0 stream --edf BRP,PLD --sample-ms 40
as11_config.py -d ble:as11 stream --data-ids Leak-50hz,RespiratoryRate-50hz --duration 60
as11_config.py -d ble:as11 subscribe --duration 60
as11_config.py -d ble:as11 subscribe UsageEvents-TherapyStatusEvents --duration 60
as11_config.py -d ble:as11 subscribe --events PressureStart --duration 60
```

EDF stream aliases (`BRP`, `PLD`, `SA2`) and their raw data IDs are listed in
[AS11 RPC Stream Reference](../as11/rpc_streams.md).
Event subscription selectors and payload event families are listed in
[AS11 RPC Event Reference](../as11/rpc_events.md). Positional `subscribe`
arguments are exact selectors. `subscribe --events` accepts payload event
labels and expands them to the selector or selectors that carry those events.
`--event` is accepted as an alias for `--events`.

StartStream interval limits verified so far: minimum sample interval is `10 ms`,
intervals are rounded down to a `10 ms` boundary, and `reportIntervalMs` must
not exceed `sampleIntervalMs * 5`.

### spool

Download spool data, optionally decode it on the host.

```
as11_config.py -d ble:as11 spool Summary
as11_config.py -d ble:as11 spool TherapyEvents-RespiratoryEvents --decode
as11_config.py -d ble:as11 spool SettingProfilesCollection --decode
as11_config.py -d ble:as11 spool ConfigurationProfilesCollection --decode
as11_config.py -d ble:as11 spool RespiratoryFlow6p25Hz --decode --samples
as11_config.py -d ble:as11 spool TherapyOneMinutePeriodic --decode --samples
as11_config.py -d ble:as11 spool DiagnosticTenMinutePeriodic --decode --samples
as11_config.py -d ble:as11 spool MachineMetrics --decode
as11_config.py -d ble:as11 spool SoundcheckVector --decode
as11_config.py -d ble:as11 spool Summary --from-dt 2026-01-01T00:00:00.000Z -o summary.bin
as11_config.py -d ble:as11 spool --list-types
as11_config.py -d ble:as11 spool --probe --from-dt 2026-04-29T00:00:00.000Z
```

Spool types, payload families, and inner record shapes are listed in
[AS11 RPC Spool Reference](../as11/rpc_spools.md).

The tool builds the `spoolAddress` as:

```
{ "<spool type>": { "fromDateTime": "<ISO timestamp>" } }
```

`--probe` runs one non-following spool round per selected type and prints a
compact status table. Use `--only populated` to hide empty rows. Spools with
a `gate_var` (currently only `RecordedSound`) are pre-checked and reported as
`GATED` without a round-trip when the gate is closed.

The confirmed spool-address selector is `fromDateTime`. The returned
`nextSpoolAddress` uses the same shape and is followed automatically unless
`--no-follow` is passed.

For archived signal spools such as `RespiratoryFlow6p25Hz`, `--decode`
prints record metadata and decoded RC03 ranges. Add `--samples` to print the
decoded samples as CSV with `record,index,time_ms,value_raw,value` columns.

For `SettingProfilesCollection`, `--decode` prints historical therapy and
feature profile snapshots. Pressures and time values are scaled into human
units. Enum-like settings are left as `Raw` values until their labels are
verified.

For `ConfigurationProfilesCollection`, `--decode` prints the configuration
attributes and `DataDeliveryControlV2` spool on/off mask.

For `TherapyOneMinutePeriodic`, `--decode` prints record ranges for the
one-minute therapy measurements. Add `--samples` to print dashboard-friendly
CSV rows with pressure, leak, ventilation, respiratory rate, I:E ratio, and
oximetry columns when oximetry is present.

For metric snapshots (`MachineMetrics`, `MemoryMetrics`,
`CellularDataUsage`), `--decode` prints named current snapshot fields where
known. `MemoryMetrics` is decoded structurally; the memory pool and three
metric values are shown without overclaiming their exact units.

For `DiagnosticTenMinutePeriodic`, `--decode` prints ten-minute cellular
diagnostic signal ranges. Add `--samples` to print CSV samples for signal
strength and signal-quality streams.

For `SoundcheckVector`, `--decode` prints soundcheck vector bins and peak
pairs. Add `--samples` for CSV rows.

`AcousticSignatureV2` and `RecordedSound` use conservative byte/blob
decoders because populated samples have not yet been verified. `RecordedSound`
is gated by `SoundDownloadAllowed`.

For event spools, `--decode` prints a TSV table with event type, start/end
timestamps, duration, and any extra fields. Event type names are shown only
where the mapping is known; otherwise the numeric type is left as-is.

Diagnostic exception spools use APPX-specific error manifests. Live `spool`
decoding reads `ApplicationIdentifier` automatically. For an offline capture,
pass `--app-version`, or omit it to compare all bundled firmware maps:

```
as11_config.py decode --type DiagnosticExceptionEvents-AppErrors \
    --app-version 8.4.0 app-errors.bin
```

The output retains the numeric code and lists every matching direct producer
and mapped backend status. Codes with more than one candidate are marked
`[ambiguous]`. Add `--details` to include producer call-site addresses.

For `Summary`, `--decode` prints a compact record header plus scalar and
percentile metric lines. The compact header includes the period range,
`duration_min`, timezone offset, session count, and decoded session mode
entry codes when present. Those session entry codes are not yet proven to be
the same enum as `ActiveTherapyProfile`. Add `--details` to print the older
field-by-field view with subfield annotations and still-unresolved internal
fields.

Use `--decode --raw-proto` to bypass the spool-specific pretty-printers and
inspect the generic protobuf wire structure.

### decode

Decode a previously captured spool payload offline, without contacting the
device. Pass `--type` when the payload type is known.

```
as11_config.py decode summary.bin
as11_config.py decode --type Summary summary.bin
as11_config.py decode --details summary.bin
as11_config.py decode --type SettingProfilesCollection settings.bin
as11_config.py decode --samples respflow.bin
as11_config.py decode --type TherapyOneMinutePeriodic --samples therapy-1min.bin
as11_config.py decode --type DiagnosticTenMinutePeriodic --samples diag10.bin
as11_config.py decode --raw-proto unknown.bin
```

### known

Offline listing of known variables, groups, streams, events, and spool types.

```
as11_config.py known
as11_config.py known vars
as11_config.py known vars groups
as11_config.py known streams
as11_config.py known streams BRP
as11_config.py known streams BRP,SA2
as11_config.py known edf
as11_config.py known events
as11_config.py known events PressureStart
as11_config.py known events --selector SystemActivityEvents-FrequentActivityEvents
as11_config.py known spools
```

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
as11_config.py -d ble:AA:BB:CC:DD:EE:FF devices pair
as11_config.py devices alias AA:BB:CC:DD:EE:FF bedroom
as11_config.py devices ota-key bedroom --key HEXSTR
as11_config.py devices ota-key bedroom --key-file ota-key.hex
as11_config.py devices ota-key bedroom --clear
as11_config.py devices list
```

`devices ota-key` stores the key in the existing BLE credential record. The
normal device list only shows whether an OTA key is configured; it does not
print the key.

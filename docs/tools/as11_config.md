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
```

EDF stream aliases (`BRP`, `PLD`, `SA2`) and their raw data IDs are listed in
[AS11 RPC Stream Reference](../as11/rpc_streams.md).

StartStream interval limits verified so far: minimum sample interval is `10 ms`,
intervals are rounded down to a `10 ms` boundary, and `reportIntervalMs` must
not exceed `sampleIntervalMs * 5`.

### spool

Download spool data, optionally decode it on the host.

```
as11_config.py -d ble:as11 spool Summary
as11_config.py -d ble:as11 spool TherapyEvents-RespiratoryEvents --decode
as11_config.py -d ble:as11 spool RespiratoryFlow6p25Hz --decode --samples
as11_config.py -d ble:as11 spool Summary --from-dt 2026-01-01T00:00:00.000Z -o summary.bin
as11_config.py -d ble:as11 spool --list-types
as11_config.py -d ble:as11 spool --probe --from-dt 2026-04-29T00:00:00.000Z
```

Spool types, payload families, wire fields, and inner record shapes are
listed in [AS11 RPC Spool Reference](../as11/rpc_spools.md).

The tool builds the `spoolAddress` as:

```
{ "<spool type>": { "fromDateTime": "<ISO timestamp>" } }
```

`--probe` runs one non-following spool round per selected type and prints a
compact status table. Each populated row's outer protobuf field is checked
against the registry's `wire_field`. Use `--only populated` to hide empty
rows. Spools with a `gate_var` (currently only `RecordedSound`) are
pre-checked and reported as `GATED` without a round-trip when the gate is
closed.

The confirmed spool-address selector is `fromDateTime`. The returned
`nextSpoolAddress` uses the same shape and is followed automatically unless
`--no-follow` is passed.

For archived signal spools such as `RespiratoryFlow6p25Hz`, `--decode`
prints record metadata and decoded RC03 ranges. Add `--samples` to print the
decoded samples as CSV with `record,index,time_ms,value_raw,value` columns.

For event spools, `--decode` prints a TSV table with event type, start/end
timestamps, duration, and any extra fields. Event type names are shown only
where the mapping is known; otherwise the numeric type is left as-is.

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
device. The spool type is inferred from the outer protobuf field number
unless `--type` is given.

```
as11_config.py decode summary.bin
as11_config.py decode --type Summary summary.bin
as11_config.py decode --details summary.bin
as11_config.py decode --samples respflow.bin
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
as11_config.py known spools
```

`known streams <EDF>` prints the data IDs behind an EDF stream alias.
`known spools` prints spool types grouped by current payload-family hints.

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

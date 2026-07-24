# Air11 RPC Spool Reference

This document lists every known `StartSpool` spool type, its payload
family, and the inner record shapes for each family. Protocol
mechanics, request fields, status codes, and the cursor-advance
caveat are described in
[Air11 RPC Protocol](rpc_protocol.md#spool-rpc).

## Contents

- [Spool registry](#spool-registry)
  - [Families](#families)
  - [Full enumeration](#full-enumeration)
- [Inner record shapes](#inner-record-shapes)
  - [Profile collection records](#profile-collection-records)
  - [Summary records](#summary-records)
  - [Event records](#event-records)
    - [GUIActivityEvents](#guiactivityevents)
    - [Diagnostic error events](#diagnostic-error-events)
    - [CellularActivityEvents](#cellularactivityevents)
  - [TherapyOneMinutePeriodic records](#therapyoneminuteperiodic-records)
  - [Metric snapshot records](#metric-snapshot-records)
  - [DiagnosticTenMinutePeriodic records](#diagnostictenminuteperiodic-records)
  - [RC03 archived-signal records](#rc03-archived-signal-records)
  - [SoundcheckVector records](#soundcheckvector-records)
  - [Blob and audio records](#blob-and-audio-records)

## Spool registry

<!-- spool-registry: begin -->

### Families

| Family | Spool types | Notes |
|--------|-------------|-------|
| `summary` | `Summary` | Per-day/per-session summary records. |
| `profile` | `SettingProfilesCollection` | Profile snapshot stream (repeated records). |
| `config` | `ConfigurationProfilesCollection` | Configuration snapshot (single record). |
| `event` | `UsageEvents-TherapyStatusEvents`, `TherapyEvents-RespiratoryEvents`, `SystemActivityEvents-FrequentActivityEvents`, `SystemActivityEvents-SporadicActivityEvents`, `SystemExceptionEvents-SystemErrors`, `SystemExceptionEvents-RecoverableErrors`, `SystemExceptionEvents-HumidifierErrors`, `SystemExceptionEvents-HeatedTubeErrors`, `DiagnosticExceptionEvents-AppErrors`, `DiagnosticExceptionEvents-FatalErrors`, `DiagnosticExceptionEvents-ResettableErrors`, `DiagnosticExceptionEvents-AlarmAppErrors`, `GUIActivityEvents`, `SurveyEvents`, `alarmEvents`, `alarmDiagnosticEvents`, `CellularActivityEvents` | Repeated event records; most use type/start/end/duration, while GUI and survey records have dedicated layouts. |
| `periodic` | `TherapyOneMinutePeriodic` | Periodic measurement protobuf. |
| `periodic_compressed` | `DiagnosticTenMinutePeriodic`, `atmosphericPressure10min` | Two interleaved signal streams per record, each with its own compressed sample blob (not RC03). |
| `metric` | `MachineMetrics`, `MemoryMetrics`, `CellularDataUsage` | Single-record metric snapshot. |
| `rc03` | `RespiratoryFlow6p25Hz`, `MaskPressure6p25Hz`, `InspiratoryPressure0p5Hz`, `Leak0p5Hz` | Archived signal: protobuf wrapper around an RC03 compressed sample block. |
| `diag_vector` | `SoundcheckVector` | Multi-record diagnostic vector. |
| `diag_blob` | `AcousticSignatureV2` | Diagnostic blob; `AcousticSignatureV2` needs `maxFragmentSize >= 4096`. |
| `audio` | `RecordedSound` | Audio recording, gated by `SoundDownloadAllowed`. |

### Full enumeration

Known spool types accepted by `StartSpool`.

| Spool type | Family | Gate | Group |
|------------|--------|------|-------|
| `Summary` | `summary` | -- | session/profile data |
| `SettingProfilesCollection` | `profile` | -- | session/profile data |
| `ConfigurationProfilesCollection` | `config` | -- | session/profile data |
| `UsageEvents-TherapyStatusEvents` | `event` | -- | therapy data |
| `TherapyEvents-RespiratoryEvents` | `event` | -- | therapy data |
| `TherapyOneMinutePeriodic` | `periodic` | -- | therapy data |
| `SystemActivityEvents-FrequentActivityEvents` | `event` | -- | system and diagnostic events |
| `SystemActivityEvents-SporadicActivityEvents` | `event` | -- | system and diagnostic events |
| `SystemExceptionEvents-SystemErrors` | `event` | -- | system and diagnostic events |
| `SystemExceptionEvents-RecoverableErrors` | `event` | -- | system and diagnostic events |
| `SystemExceptionEvents-HumidifierErrors` | `event` | -- | system and diagnostic events |
| `SystemExceptionEvents-HeatedTubeErrors` | `event` | -- | system and diagnostic events |
| `DiagnosticExceptionEvents-AppErrors` | `event` | -- | system and diagnostic events |
| `DiagnosticExceptionEvents-FatalErrors` | `event` | -- | system and diagnostic events |
| `DiagnosticExceptionEvents-ResettableErrors` | `event` | -- | system and diagnostic events |
| `DiagnosticExceptionEvents-AlarmAppErrors` | `event` | -- | system and diagnostic events |
| `GUIActivityEvents` | `event` | -- | system and diagnostic events |
| `SurveyEvents` | `event` | -- | system and diagnostic events |
| `alarmEvents` | `event` | -- | system and diagnostic events |
| `alarmDiagnosticEvents` | `event` | -- | system and diagnostic events |
| `DiagnosticTenMinutePeriodic` | `periodic_compressed` | -- | periodic metrics |
| `MachineMetrics` | `metric` | -- | periodic metrics |
| `MemoryMetrics` | `metric` | -- | periodic metrics |
| `CellularActivityEvents` | `event` | -- | periodic metrics |
| `CellularDataUsage` | `metric` | -- | periodic metrics |
| `atmosphericPressure10min` | `periodic_compressed` | -- | archived signals |
| `RespiratoryFlow6p25Hz` | `rc03` | -- | archived signals |
| `MaskPressure6p25Hz` | `rc03` | -- | archived signals |
| `InspiratoryPressure0p5Hz` | `rc03` | -- | archived signals |
| `Leak0p5Hz` | `rc03` | -- | archived signals |
| `SoundcheckVector` | `diag_vector` | -- | diagnostic blobs |
| `AcousticSignatureV2` | `diag_blob` | -- | diagnostic blobs |
| `RecordedSound` | `audio` | `SoundDownloadAllowed` | diagnostic blobs |

<!-- spool-registry: end -->

## Inner record shapes

### Profile collection records

`SettingProfilesCollection` contains:

| Field | Meaning |
|-------|---------|
| `1` | attributes: applied timestamp, source, transaction id |
| `2` | active therapy profile and active feature-profile IDs |
| `3` | therapy profile snapshots |
| `4` | feature profile snapshots |

The active therapy profile uses the exported mode code, not the local
`ActiveTherapyProfile` option index. Feature-profile IDs `8..12` have no named
entries in the firmware formatter and remain numeric if encountered.

Known therapy-profile subrecords include `CpapProfile`, `AutoSetProfile`,
`VAutoProfile`, and `ASVProfile`. Feature-profile subrecords include
`EprFeature`, `AutoRampFeature`, `ClimateFeature`, and `DisplayFeature`.
Numeric pressure and time fields use profile-specific scales. Enum fields are
wire integers and require the corresponding firmware option mapping.

`ConfigurationProfilesCollection` contains attributes plus
`DataDeliveryControlV2`, whose fields map to spool families such as
`Summary`, `TherapyOneMinutePeriodic`, `RespiratoryFlow6p25Hz`, and
`CellularDataUsage`.

### Summary records

`Summary` returns repeated daily summary records. The outer payload is repeated
field `2`; each field `2` body is one record with this shape:

| Field | Name | Meaning |
|-------|------|---------|
| `1` | `InitMarker` | Record-present marker; value `1`. |
| `2` | `PeriodStart` | Summary bucket start, UTC milliseconds. |
| `3` | `PeriodEnd` | Summary bucket end, UTC milliseconds. |
| `4` | `TimeZoneOffsetMin` | Local timezone offset in minutes for the bucket. |
| `5` | `DurationMin` | Therapy duration in minutes. |
| `6` | `SessionDurationEntries` | Repeated session-duration subrecords. |
| `7` | `AHI` | Apnea/hypopnea index. |
| `8` | `ApneaIndex` | Apnea index. |
| `9` | `HypopneaIndex` | Hypopnea index. |
| `10` | `ObstructiveApneaIndex` | Obstructive apnea index. |
| `11` | `CentralApneaIndex` | Central apnea index. |
| `12` | `UnknownApneaIndex` | Unknown apnea index. |
| `13` | `ReraIndex` | RERA index. |
| `14` | `Leak` | Percentile metric subrecord. |
| `15` | `InspiratoryPressure` | Percentile metric subrecord. |
| `16` | `CSR` | CSR scalar. |
| `17` | `SpO2Thresh` | Time below SpO2 threshold, in minutes. |
| `18` | `SpontTriggerPercentage` | Spontaneous trigger percentage. |
| `19` | `SpontCyclePercentage` | Spontaneous cycle percentage. |
| `20` | `ExpiratoryPressure` | Percentile metric subrecord. |
| `21` | `MeanMaskPressure` | Percentile metric subrecord. |
| `22` | `TidalVolume` | Percentile metric subrecord. |
| `23` | `MinuteVentilation` | Percentile metric subrecord. |
| `24` | `TargetMinuteVentilation` | Percentile metric subrecord. |
| `25` | `RespiratoryRate` | Percentile metric subrecord. |
| `26` | `InspiratoryDuration` | Percentile metric subrecord. |
| `27` | `IeRatio` | Percentile metric subrecord. |
| `28` | `SpO2` | Percentile metric subrecord. |
| `29` | `AmbientHumidity` | Percentile metric subrecord. |
| `30` | `HumidifierTemperature` | Percentile metric subrecord. |
| `31` | `HeatedTubeTemperature` | Percentile metric subrecord. |
| `32` | `HumidifierPower` | Percentile metric subrecord. |
| `33` | `HeatedTubePower` | Percentile metric subrecord. |
| `34` | `HumidifierConnected` | Device-connected enum. |
| `35` | `TubeConnected` | Device-connected enum. |
| `36` | `BlowerPressure` | Percentile metric subrecord. |
| `37` | `RespiratoryFlow` | Percentile metric subrecord. |
| `38` | `BlowerFlow` | Percentile metric subrecord. |
| `39` | `SessionCount` | Number of session entries emitted into field `6`. |
| `40` | `RecordTimestamp` | Record/report timestamp. Empty buckets use `PeriodStart`; populated buckets use the record timestamp passed to the Summary header builder. |
| `41` | `HeartRate` | Percentile metric subrecord. |
| `42` | `AlveolarMinuteVentilation` | Alveolar minute ventilation percentile metric. |
| `43` | `SmdSmtTimestamp` | Optional timestamp encoded as an `SMD`/`SMT` date/time pair. |

Field `6` contains repeated field `1` subrecords:

| Subfield | Meaning |
|----------|---------|
| `1` | Session timestamp, UTC milliseconds. |
| `2` | Session duration in minutes. |

Metric subrecords use percentile-like subfields:

| Parent fields | Subfields |
|---------------|-----------|
| `14` Leak | `2`=p50, `3`=p70, `4`=p95, `5`=p100 |
| `15`, `20`, `21`, `22`, `23`, `24`, `25`, `26`, `27`, `28`, `41`, `42` | `2`=p50, `3`=p95, `4`=p100 |
| `29`, `30`, `31`, `32`, `33`, `38` | `2`=p50 |
| `36` BlowerPressure | `1`=p5, `3`=p95 |
| `37` RespiratoryFlow | `1`=p5, `3`=p95 |

The protobuf stores summary measurements as fixed-point integers. Divide each
encoded integer by the divisor below to obtain the physical value.

Direct scalar fields use these scales:

| Fields | Values | Divisor | Units |
|--------|--------|--------:|-------|
| `7..13` | AHI, apnea indexes, and RERA index | 100 | index |
| `18`, `19` | Spontaneous trigger and cycle percentages | 100 | percent |

Fields containing percentile metrics are nested messages. Apply the listed
divisor separately to each populated percentile subfield (`p5`, `p50`, `p70`,
`p95`, or `p100`):

| Fields | Metrics | Divisor | Units |
|--------|---------|--------:|-------|
| `14`, `37`, `38` | Leak, RespiratoryFlow, BlowerFlow | 100 | L/s |
| `15`, `20`, `21`, `36` | InspiratoryPressure, ExpiratoryPressure, MeanMaskPressure, BlowerPressure | 100 | cmH2O |
| `22` | TidalVolume | 100 | L |
| `23`, `24`, `42` | MinuteVentilation, TargetMinuteVentilation, AlveolarMinuteVentilation | 100 | L/min |
| `25`, `41` | RespiratoryRate, HeartRate | 100 | bpm |
| `26` | InspiratoryDuration | 1000 | seconds |
| `27`, `28`, `32`, `33` | IeRatio, SpO2, HumidifierPower, HeatedTubePower | 100 | percent |
| `29` | AmbientHumidity | 100 | mg/L |
| `30`, `31` | HumidifierTemperature, HeatedTubeTemperature | 100 | Celsius |

For example, an encoded `InspiratoryPressure.p50` value of `1040` represents
`10.40 cmH2O`. Fields `34` and `35` contain enum indexes and are not scaled.

### Event records

Most event spool records use the same inner record shape:

| Field | Meaning |
|-------|---------|
| `1` | event type/code |
| `2` | start timestamp, UTC milliseconds |
| `3` | end timestamp, UTC milliseconds |
| `4` | duration in milliseconds, when present |

The wrapper depth varies by spool family. Unknown event codes remain numeric
unless a selector-specific label table has been verified.

Field `1` stores the firmware enum value. Enum values may contain gaps:
`UsageEvents-TherapyStatusEvents` uses `10` and `11` for `LearnTargetsStart`
and `LearnTargetsStop`, while respiratory CSR boundaries use `8` and `9`.
The decoder therefore uses an explicit code map for each event family.

#### GUIActivityEvents

GUI records use a different inner shape:

| Field | Meaning |
|-------|---------|
| `1` | record kind: `1` ActiveScreen, `2` TouchItem, `3` Swipe, `4` Multitouch, `5` ScreenState |
| `2` | timestamp, UTC milliseconds |
| `3` | kind-specific value |

#### Diagnostic error events

`DiagnosticExceptionEvents-AppErrors`, `-FatalErrors`, `-ResettableErrors`,
and `-AlarmAppErrors` store a firmware error code in field `1`; it is not a
shared event enum. Its meaning is tied to the source-location error manifest
of the firmware build.

The decoder selects the matching manifest from the device
`ApplicationIdentifier`. For offline captures, `--app-version` accepts either
an APPX release such as `8.4.0` or a complete application identifier. Without
a version, the decoder compares every bundled manifest and preserves
version-specific differences.

An application error code may identify several direct reporting sites, a
mapped filesystem-backend status, or both. All matching candidates are shown;
`[ambiguous]` means the stored record does not identify one producer.

#### CellularActivityEvents

From firmware 8.6.0, this spool combines numeric records from
`CellularActivityEvents` with string records from the internal
`CellularActivityStringEvents` selector. `CellularActivityStringEvents` is not
a separate `StartSpool` type. String records use field `17` for their text.

`CellularActivityEvents` records use these confirmed event codes:

| Code | Event | Additional fields |
|-----:|-------|-------------------|
| `2` | Cellular components starting | -- |
| `3` | Cellular components stopping | -- |
| `5` | Network generation | field `5`: `1` = 2G, `2` = 3G, `3` = 4G, `4` = LTE-M |
| `6` | TCP connection started | -- |
| `10` | TCP connected | -- |
| `11` | TCP disconnected | -- |
| `12` | TCP connection failed | -- |
| `13` | HTTP response status | field `6`: HTTP status code |
| `14` | Device registration succeeded | -- |
| `15` | Device registration failed | -- |
| `16` | Session response valid | -- |
| `17` | Session response invalid | -- |
| `22` | Session expired | -- |
| `23` | Data spool read started | -- |
| `24` | Data send succeeded | field `16`: result code |
| `25` | Data send failed | field `16`: result code |
| `27` | Data spool read failed | -- |
| `33` | Cellular initializer started | -- |
| `60` | Mobile network code (MNC) | field `8`: numeric MNC |
| `61` | Mobile country code (MCC) | field `9`: numeric MCC |
| `62` | HTTP response timeout | -- |
| `87` | Network cell identifier | field `12`: cell identifier |
| `88` | Data mode changed to `SILENT` | -- |
| `89` | Data mode changed to `ACTIVE` | -- |
| `90` | CAL system error | field `13`: CAL error code |
| `91` | Cellular pre-initialization started | -- |
| `92` | Cellular pre-initialization completed | -- |
| `95` | Application log record | field `14`: packed error IDs; field `15`: report class |
| `108` | Network location | field `17`: `MCC-MNC-area-cell-id` |

For event `95`, field `14` is packed as:

```text
packed = ((error_id & 0x0fff) << 12) | (detail_id & 0x0fff)
```

Error ID `32` is `RpcResponseInvalid`. Unmapped error IDs and report classes are
reported numerically.

Other event codes and their additional fields remain numeric. The
`as11_config.py` decoder preserves their field numbers, wire types, and values.

### TherapyOneMinutePeriodic records

`TherapyOneMinutePeriodic` records contain one or more per-signal messages,
plus field `15`, which has been observed as the sample interval in minutes.

Each per-signal message has this shape:

| Field | Meaning |
|-------|---------|
| `1` | status/kind marker, observed as `1` |
| `2` | start timestamp, UTC milliseconds |
| `3` | sample block |

The sample block is an int16 series. Fields `1..7` and `21` are headerless
second-difference/Rice streams using the same reconstruction formula as RC03.
Fields `8` and `9`, when present, are raw little-endian int16 arrays.

Decoded fields:

| Field | Name | CSV column | Scale |
|-------|------|------------|-------|
| `1` | Leak | `leak_l_min` | `raw * 1.2` L/min |
| `2` | InspiratoryPressure | `insp_pressure_cmH2O` | `raw / 5` cmH2O |
| `3` | ExpiratoryPressure | `exp_pressure_cmH2O` | `raw / 5` cmH2O |
| `4` | MinuteVentilation | `minute_vent_l_min` | `raw / 8` L/min |
| `5` | InspiratoryDuration | `insp_duration_s` | `raw / 50` seconds |
| `6` | RespiratoryRate | `resp_rate_bpm` | `raw` bpm |
| `7` | IeRatio | `ie_ratio_pct` | `raw * 4` percent |
| `8` | SpO2 | `spo2_pct` | `raw` percent |
| `9` | HeartRate | `heart_rate_bpm` | `raw` bpm |
| `21` | MIS | `mis` | `raw / 50` |

The field mapping and scales are verified against `Summary` percentile
records and observed oximetry samples.

### Metric snapshot records

`MachineMetrics` contains one current snapshot:

| Field | Meaning |
|-------|---------|
| `1` | origin enum, observed `1` |
| `2` | attributes; subfield `1` is report timestamp |
| `3` | `LastTherapyUseDateTime` |
| `4` | `LastEraseDataDateTime` |
| `5` | `TherapyRunMeter`, milliseconds |
| `6` | `MotorRunMeter`, milliseconds |
| `7` | `MotorRunSinceLastServiceMeter`, milliseconds |
| `8` | `MachineRunMeter`, milliseconds |
| `9` | `LastMachineServiceDateTime` |

`CellularDataUsage` contains one current snapshot:

| Field | Meaning |
|-------|---------|
| `1` | origin enum, observed `1` |
| `2` | attributes; subfield `1` is report timestamp |
| `3` | `ApplicationTotalUpload`, bytes |
| `4` | `ApplicationTotalDownload`, bytes |

`MemoryMetrics` reports external NOR activity and FTL state; it does not
describe MCU RAM. Field `1` is attributes with report timestamp. Field `2`
repeats one metric set:

| Set | Volume | Subfield 2 | Subfield 3 | Subfield 4 |
|----:|--------|------------|------------|------------|
| `1` | `UPGRADE` | `FWC`: write requests >= 2048 B | `FE2`: 64 KiB erases | `FM2`: maximum erase generation |
| `2` | `SETTINGS` | `FW0`: write requests >= 2048 B | `FE0`: 64 KiB erases | `FM0`: maximum erase generation |
| `3` | `DATALOG` | `FW1`: write requests >= 2048 B | `FE1`: 64 KiB erases | `FM1`: maximum erase generation |

The write counter increments once per front-end write request whose original
length is at least 2048 bytes, not once per 256-byte flash page. The erase
counter covers 64 KiB erase operations; 4 KiB erases do not increment it. The
maximum erase generation is read from the mounted NOR FTL once per second. All
three values are raw integer counters, not byte counts or free-space values.

RTOS stack high-water marks are exposed separately as `_S10`, `_S20`, `_S40`,
`_S11`, `_SM0`, `_SM1`, `_SM2`, `_SEE`, `_SMC`, `_SPL`, and `_SCC`. Each value
is the maximum observed stack use for its task, in percent. Firmware records
AppError `0x2b2f` when a sample exceeds 80% and has less than 1000 bytes left.

### DiagnosticTenMinutePeriodic records

`DiagnosticTenMinutePeriodic` records have field `1` origin/kind and one or
more signal subrecords. Each signal subrecord contains:

| Field | Meaning |
|-------|---------|
| `1` | sample interval, minutes |
| `2` | start timestamp, UTC milliseconds |
| `3` | headerless signed int16 second-difference/Rice sample block |

Observed signal fields:

| Field | Name |
|-------|------|
| `2` | `CellularSignalStrength` |
| `3` | `CellularSignalQuality2G` |
| `4` | `CellularSignalQuality3G` |
| `5` | `CellularSignalQualityLTE` |

### RC03 archived-signal records

The RC03 signal records are protobuf wrappers around a compressed sample
block. The inner record fields observed so far are:

| Field | Meaning |
|-------|---------|
| `1` | sample interval in milliseconds |
| `2` | start timestamp, UTC milliseconds |
| `3` | end timestamp, UTC milliseconds |
| `4` | RC03 compressed sample block |

The first byte of field `4` is the RC03 header length, followed by ASCII
`RC03`, six zigzag-varint format parameters, and compressed sample data. The
body starts with one or two signed little-endian 16-bit sample seeds. Remaining
samples are Rice-coded zigzag second differences:

```
delta2[n] = sample[n] - 2 * sample[n - 1] + sample[n - 2]
sample[n] = 2 * sample[n - 1] - sample[n - 2] + delta2[n]
```

On decoded archived signal blocks, parameter 4 is the Rice modulus and
parameter 1 gives the scale exponent:

```text
value = raw * (2 * 10 ** param1)
```

### SoundcheckVector records

`SoundcheckVector` records contain:

| Field | Meaning |
|-------|---------|
| `1` | report timestamp, UTC milliseconds |
| `2` | sample rate, observed `18750` Hz |
| `3` | repeated vector/bin value |
| `4` | repeated two-value subrecord wrapper |

### Blob and audio records

`AcousticSignatureV2` and `RecordedSound` carry byte payloads rather than one
of the record families above. `RecordedSound` is gated by
`SoundDownloadAllowed` and may contain a `RIFF/WAVE` stream.

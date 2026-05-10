# AS11 RPC Stream Reference

This document lists known `StartStream` data IDs and the EDF-oriented
aliases used by `python/as11_config.py`. Protocol mechanics, request
fields, and interval limits are described in
[AS11 RPC Protocol](rpc_protocol.md).

## Contents

- [EDF aliases](#edf-aliases)
- [BRP/SA2 mapping](#brpsa2-mapping)
- [PLD mapping](#pld-mapping)
- [Notes](#notes)

## EDF aliases

`StartStream` uses firmware data IDs rather than EDF signal names. The helper
tool exposes the following EDF group aliases for live streaming:

| Alias | EDF file | Natural sample interval | RPC stream IDs |
|-------|----------|-------------------------|----------------|
| `BRP` | `BRP.edf` | 40 ms | `PatientFlow-100hz`, `MaskPressure-100hz` |
| `PLD` | `PLD.edf` | 2000 ms | direct stream names listed below |
| `SA2` | `SA2.edf` | 1000 ms | `HeartRate`, `SpO2` |

Example:

```sh
python3 python/as11_config.py -d can:can0 stream --edf BRP,PLD --sample-ms 40
```

## BRP/SA2 mapping

| EDF signal | RPC stream ID |
|------------|---------------|
| `Flow.40ms` | `PatientFlow-100hz` |
| `Press.40ms` | `MaskPressure-100hz` |
| `Pulse.1s` | `HeartRate` |
| `SpO2.1s` | `SpO2` |

## PLD mapping

| EDF signal | RPC stream ID |
|------------|---------------|
| `MaskPress.2s` | `MaskPressure-TwoSecond` |
| `Press.2s` | `InspiratoryPressure-TwoSecond` |
| `EprPress.2s` | `ExpiratoryPressure-TwoSecond` |
| `Leak.2s` | `Leak-50hz` |
| `RespRate.2s` | `RespiratoryRate-50hz` |
| `TidVol.2s` | `TidalVolume-50hz` |
| `MinVent.2s` | `MinuteVentilation-50hz` |
| `TgtVent.2s` | `TargetMinuteVentilation` |
| `IERatio.2s` | `IeRatio` |
| `Snore.2s` | `SnoreIndex-50hz` |
| `FlowLim.2s` | `FlowLimitation-50hz` |
| `Ti.2s` | `InspiratoryDuration` |

## Notes

- `STR.edf` is a session summary/settings file, not a live stream group.
- Oximetry stream IDs can be accepted by the parser even when no oximeter
  is connected; absence of data should not be treated as proof that the
  stream name is invalid.
- Some `Summary-*` statistic names are streamable individually, but they do
  not map cleanly to the low-rate EDF alias groups above.

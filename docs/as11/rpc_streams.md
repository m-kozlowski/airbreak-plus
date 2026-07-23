# Air11 RPC Stream Reference

This document is a compact map from EDF signals to useful `StartStream` data
IDs and the EDF aliases used by `python/as11_config.py`. General stream
mechanics, request fields, interval limits, and examples of other data IDs are
described in [Air11 RPC Protocol](rpc_protocol.md).

## Contents

- [EDF aliases](#edf-aliases)
- [BRP/TCV/SA2 mapping](#brptcvsa2-mapping)
- [PLD mapping](#pld-mapping)
- [Notes](#notes)

## EDF aliases

`StartStream` accepts both long data IDs and underscored short tags. The helper
tool exposes EDF group aliases using the same short-tag variables selected by
the on-card EDF schemas in CONF g[16].

| Alias | EDF file | Natural sample interval | RPC data IDs |
|-------|----------|-------------------------|--------------|
| `BRP` | `BRP.edf` | 40 ms | `_RFL` / `PatientFlow`, `_MKP` / `MaskPressure` |
| `PLD` | `PLD.edf` | 2000 ms | short/name pairs listed below |
| `SA2` | `SA2.edf` | 1000 ms | `_HRT` / `HeartRate`, `_SAO` / `SpO2` |
| `TCV` | `TCV.edf` | 40 ms | `_BYV` |

Example:

```sh
python3 python/as11_config.py -d can:can0 stream --edf BRP,PLD --sample-ms 40
```

## BRP/TCV/SA2 mapping

| EDF signal | short | name |
|------------|-------|------|
| `Flow.40ms` | `_RFL` | `PatientFlow` |
| `Press.40ms` | `_MKP` | `MaskPressure` |
| `TrigCycEvt.40ms` | `_BYV` | n/a |
| `Pulse.1s` | `_HRT` | `HeartRate` |
| `SpO2.1s` | `_SAO` | `SpO2` |

## PLD mapping

| EDF signal | short | name |
|------------|-------|------|
| `MaskPress.2s` | `_MKF` | `MaskPressure-TwoSecond` |
| `Press.2s` | `_MKI` | `InspiratoryPressure-TwoSecond` |
| `EprPress.2s` | `_MKE` | `ExpiratoryPressure-TwoSecond` |
| `Leak.2s` | `_LKF` | `Leak` |
| `RespRate.2s` | `_RR2` | n/a |
| `TidVol.2s` | `_TD2` | n/a |
| `MinVent.2s` | `_MV2` | n/a |
| `TgtVent.2s` | `_TGT` | n/a |
| `IERatio.2s` | `_IE2` | n/a |
| `Snore.2s` | `_SNI` | `SnoreIndex` |
| `FlowLim.2s` | `_FFL` | `FlowLimitation` |
| `Ti.2s` | `_INT` | `InspiratoryDuration` |

## Notes

- `STR.edf` is a session summary/settings file, not a live stream group.
- `TCV.edf` and its `_BYV` source are present from firmware 8.6.0.
- One `sampleIntervalMs` applies to every data ID in a stream. Requesting the
  `PLD` alias at 40 ms repeats or reports the underlying low-rate values more
  often; it does not turn the native two-second signals into 40 ms data.
- Oximetry stream IDs can be accepted by the parser even when no oximeter
  is connected; absence of data should not be treated as proof that the
  stream name is invalid.
- Some `Summary-*` statistic names are streamable individually, but they do
  not map cleanly to the low-rate EDF alias groups above.

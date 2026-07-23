# Air11 EDF Signal Reference

Live RPC stream names are documented separately in \
[Air11 RPC Stream Reference](rpc_streams.md). \
EDF fixed headers and ResMed patient/recording fields are documented in \
[Air11 EDF Header Reference](edf_header.md). \
Annotation-only `EVE.edf` and `CSL.edf` files are documented separately in \
[Air11 EDF Annotation Files](edf_annotations.md).

## Contents

- [Scope](#scope)
- [BRP.edf](#brpedf----breath-waveform-25-hz-60s-records)
- [TCV.edf](#tcvedf----triggercycle-events-25-hz-60s-records)
- [PLD.edf](#pldedf----two-second-therapy-signals-05-hz-60s-records)
- [SA2.edf](#sa2edf----spo2pulse-1-hz-60s-records)
- [STR.edf](#stredf----superset-session-statistics-1-record-per-86400s)
  - [STR scaling](#str-scaling)
  - [STR enum export maps](#str-enum-export-maps)
  - [STR variant provenance](#str-variant-provenance)

## Scope

The BRP, TCV, and SA2 tables match the checked stock schemas. `TCV.edf` and
its stream schema were introduced in firmware 8.6.0 and are absent from
earlier firmware. The PLD table is the 12-signal union installed by the
`patch-edf-superset` patch and marks which rows occur in each checked stock
product family.

Use the [`edf-streams` command](../tools/as11_descriptors.md#edf-streams) to
print the BRP, TCV, SA2, or PLD schema from any firmware dump.

The numbered STR tables describe the 134-signal output installed by the same
patch. Stock firmware carries a larger `SummaryRecord` inventory whose active
rows and populated labels vary by product variant. Dormant inventory rows are
not assigned an output signal number unless they are activated. The
[variant provenance table](#str-variant-provenance) identifies which official
15.8.4.0 variants supplied the active-row metadata used by the patch.


## BRP.edf -- Breath waveform (25 Hz, 60s records)

| # | Signal | name | short | samples/rec | rate |
|---|--------|------|-------|-------------|------|
| 0 | Flow.40ms | PatientFlow | RFL | 1500 | 25 Hz |
| 1 | Press.40ms | MaskPressure | MKP | 1500 | 25 Hz |

## TCV.edf -- Trigger/cycle events (25 Hz, 60s records)

`TCV.edf` is a standalone sampled file present from firmware 8.6.0.

| # | Signal | name | short | samples/rec | rate |
|---|--------|------|-------|-------------|------|
| 0 | TrigCycEvt.40ms | n/a | BYV | 1500 | 25 Hz |

Firmware writes each trigger/cycle event code to both
`TriggerCycleEvent` (`_BTE`) and `_BYV`. `_BYV` is the EDF source and returns
to `NoEvent` 200 ms after the event.

| Value | Meaning |
|------:|---------|
| 0 | `NoEvent` |
| 1 | `SpontaneousTrigger` |
| 2 | `TimedTrigger` |
| 3 | `SpontaneousCycle` |
| 4 | `SpontaneousTiMinCycle` |
| 5 | `TimedCycle` |

## PLD.edf -- Two-second therapy signals (0.5 Hz, 60s records)

The `#` column is the superset order. `x` means the signal is present in the
stock schema for that family; `.` means it is added by the superset patch.

| # | Signal | name | short | samples/rec | rate | AS | VA | ST | ASV |
|---|--------|------|-------|-------------|------|----|----|----|-----|
| 0 | MaskPress.2s | MaskPressure-TwoSecond | MKF | 30 | 0.5 Hz | x | x | x | x |
| 1 | Press.2s | InspiratoryPressure-TwoSecond | MKI | 30 | 0.5 Hz | x | x | x | x |
| 2 | EprPress.2s | ExpiratoryPressure-TwoSecond | MKE | 30 | 0.5 Hz | x | x | x | x |
| 3 | Leak.2s | Leak | LKF | 30 | 0.5 Hz | x | x | x | x |
| 4 | RespRate.2s | n/a | RR2 | 30 | 0.5 Hz | x | x | x | x |
| 5 | TidVol.2s | n/a | TD2 | 30 | 0.5 Hz | x | x | x | x |
| 6 | MinVent.2s | n/a | MV2 | 30 | 0.5 Hz | x | x | x | x |
| 7 | TgtVent.2s | n/a | TGT | 30 | 0.5 Hz | . | . | . | x |
| 8 | IERatio.2s | n/a | IE2 | 30 | 0.5 Hz | . | x | x | . |
| 9 | Snore.2s | SnoreIndex | SNI | 30 | 0.5 Hz | x | x | x | x |
| 10 | FlowLim.2s | FlowLimitation | FFL | 30 | 0.5 Hz | x | x | . | x |
| 11 | Ti.2s | InspiratoryDuration | INT | 30 | 0.5 Hz | . | x | x | . |

## SA2.edf -- SpO2/pulse (1 Hz, 60s records)

| # | Signal | name | short | samples/rec | rate |
|---|--------|------|-------|-------------|------|
| 0 | Pulse.1s | HeartRate | HRT | 60 | 1 Hz |
| 1 | SpO2.1s | SpO2 | SAO | 60 | 1 Hz |

## STR.edf -- Superset session statistics (1 record per 86400s)

Rows marked <sup>[map](#str-enum-export-maps)</sup> are exported through
an enum value map before being written to EDF.

### STR scaling

STR rows carry two scale fields in the firmware `SummaryRecord` schema:

| Field | Meaning |
|-------|---------|
| `logical_scale` | source-value scale used by the STR formatter |
| `edf_output_scale` | digital EDF sample scale used by the EDF header |

For setting snapshot rows, the source is the runtime CONF value. The
formatter first converts it to a logical value, then packs it with
`edf_output_scale`.

For summary statistic rows (`Summary-*` values), the source value is already
the Summary/statistic wire value. The firmware divides by `logical_scale`
before writing the EDF digital sample:

```text
edf_raw = round(summary_wire / logical_scale)
edf_value = edf_raw / edf_output_scale
```

Most statistic rows use `logical_scale * edf_output_scale == 100`, so the
Summary wire value is effectively centi-units. `Ti.*` rows use product
`1000`, because their Summary source is in milliseconds.

Examples:

| Signal | Summary wire | logical_scale | edf_output_scale | EDF raw | EDF value |
|--------|--------------|---------------|------------------|---------|-----------|
| `RespRate.50` | `1680` | `20` | `5` | `84` | `16.8 bpm` |
| `Flow.95` | `40` | `0.2` | `500` | `200` | `0.4 L/s` |
| `Ti.50` | `1000` | `20` | `50` | `50` | `1.0 seconds` |

### Session header [0-3]

| # | Signal | name | short |
|---|--------|------|-------|
| 0 | Date | n/a | n/a |
| 1 | MaskOn | n/a | n/a |
| 2 | MaskOff | n/a | n/a |
| 3 | MaskEvents | n/a | n/a |

### Session core [4-5]

| # | Signal | name | short |
|---|--------|------|-------|
| 4 | Duration | n/a | PPD |
| 5 | Mode <sup>[map](#str-enum-export-maps)</sup> | ActiveTherapyProfile | MOP |

### CPAP/AutoSet/HerAuto settings [6-13]

| # | Signal | name | short |
|---|--------|------|-------|
| 6 | S.C.StartPress | Cpap-StartPressure | STP |
| 7 | S.C.Press | Cpap-SetPressure | IPC |
| 8 | S.A.StartPress | AutoSet-StartPressure | STU |
| 9 | S.A.MaxPress | AutoSet-MaxPressure | MPA |
| 10 | S.A.MinPress | AutoSet-MinPressure | MPI |
| 11 | S.AFH.StartPress | HerAuto-StartPressure | HSP |
| 12 | S.AFH.MaxPress | HerAuto-MaxPressure | HMA |
| 13 | S.AFH.MinPress | HerAuto-MinPressure | HMI |

### VAuto settings [14-21]

| # | Signal | name | short |
|---|--------|------|-------|
| 14 | S.VA.StartPress | VAuto-StartPressure | XE0 |
| 15 | S.VA.MaxIPAP | VAuto-MaxInspiratoryPressure | XE1 |
| 16 | S.VA.MinEPAP | VAuto-MinExpiratoryPressure | XE2 |
| 17 | S.VA.PS | VAuto-SetPressureSupport | XE3 |
| 18 | S.VA.TiMax | VAuto-SetMaxInspiratoryTime | XE4 |
| 19 | S.VA.TiMin | VAuto-SetMinInspiratoryTime | XE5 |
| 20 | S.VA.Trigger <sup>[map](#str-enum-export-maps)</sup> | VAuto-TriggerSensitivity | XE6 |
| 21 | S.VA.Cycle <sup>[map](#str-enum-export-maps)</sup> | VAuto-CycleSensitivity | XE7 |

### Spont settings [22-32]

| # | Signal | name | short |
|---|--------|------|-------|
| 22 | S.S.StartPress | Spont-StartPressure | ZZ3 |
| 23 | S.S.IPAP | Spont-TargetInspiratoryPressure | ZZ1 |
| 24 | S.S.EPAP | Spont-TargetExpiratoryPressure | ZZ2 |
| 25 | S.S.EasyBreathe <sup>[map](#str-enum-export-maps)</sup> | Spont-EasyBreatheEnable | ZZ4 |
| 26 | S.S.RespRateEn <sup>[map](#str-enum-export-maps)</sup> | Spont-RespiratoryRateEnable | ZZ5 |
| 27 | S.S.TiMax | Spont-SetMaxInspiratoryTime | ZZ7 |
| 28 | S.S.TiMin | Spont-SetMinInspiratoryTime | ZZ8 |
| 29 | S.S.RiseEnable <sup>[map](#str-enum-export-maps)</sup> | Spont-RiseTimeEnable | ZZ9 |
| 30 | S.S.RiseTime | Spont-RiseTime | Z10 |
| 31 | S.S.Trigger <sup>[map](#str-enum-export-maps)</sup> | Spont-TriggerSensitivity | Z11 |
| 32 | S.S.Cycle <sup>[map](#str-enum-export-maps)</sup> | Spont-CycleSensitivity | Z12 |

### ST/Timed settings [33-49]

| # | Signal | name | short |
|---|--------|------|-------|
| 33 | S.ST.StartPress | ST-StartPressure | XA3 |
| 34 | S.ST.IPAP | ST-TargetInspiratoryPressure | XA1 |
| 35 | S.ST.EPAP | ST-TargetExpiratoryPressure | XA2 |
| 36 | S.ST.RespRate | ST-SetRespiratoryRate | XA6 |
| 37 | S.ST.TiMax | ST-SetMaxInspiratoryTime | XA7 |
| 38 | S.ST.TiMin | ST-SetMinInspiratoryTime | XA8 |
| 39 | S.ST.RiseEnable | ST-RiseTimeEnable | XA9 |
| 40 | S.ST.RiseTime | ST-RiseTime | XAA |
| 41 | S.ST.Trigger <sup>[map](#str-enum-export-maps)</sup> | ST-TriggerSensitivity | ZU1 |
| 42 | S.ST.Cycle | ST-CycleSensitivity | XAB |
| 43 | S.T.StartPress | Timed-StartPressure | XB0 |
| 44 | S.T.IPAP | Timed-TargetInspiratoryPressure | XB1 |
| 45 | S.T.EPAP | Timed-TargetExpiratoryPressure | XB2 |
| 46 | S.T.RespRate | Timed-SetRespiratoryRate | XB4 |
| 47 | S.T.Ti | Timed-SetInspiratoryTime | XB5 |
| 48 | S.T.RiseEnable <sup>[map](#str-enum-export-maps)</sup> | Timed-RiseTimeEnable | XB6 |
| 49 | S.T.RiseTime | Timed-RiseTime | XB7 |

### ASV/ASVAuto settings [50-58]

| # | Signal | name | short |
|---|--------|------|-------|
| 50 | S.AV.StartPress | ASV-StartPressure | XC0 |
| 51 | S.AV.EPAP | ASV-TargetExpiratoryPressure | XC1 |
| 52 | S.AV.MaxPS | ASV-MaxPressureSupport | XC2 |
| 53 | S.AV.MinPS | ASV-MinPressureSupport | XC3 |
| 54 | S.AA.StartPress | ASVAuto-StartPressure | XD0 |
| 55 | S.AA.MaxEPAP | ASVAuto-MaxExpiratoryPressure | XD1 |
| 56 | S.AA.MinEPAP | ASVAuto-MinExpiratoryPressure | XD2 |
| 57 | S.AA.MaxPS | ASVAuto-MaxPressureSupport | XD3 |
| 58 | S.AA.MinPS | ASVAuto-MinPressureSupport | XD4 |

### Common comfort/settings [59-77]

| # | Signal | name | short |
|---|--------|------|-------|
| 59 | S.AS.Comfort | AutoSetComfort | AFC |
| 60 | S.RampEnable | RampEnable | RMA |
| 61 | S.RampTime | RampTime | RMT |
| 62 | S.EPR.ClinEnable | EprEnablePatientAccess | EPA |
| 63 | S.EPR.EPREnable | EprEnable | EPX |
| 64 | S.EPR.Level | EprPressure | EPR |
| 65 | S.EPR.EPRType | EprType | EPT |
| 66 | S.SmartStart | SmartStart | SST |
| 67 | S.PtAccess | PatientView | ACC |
| 68 | S.ABFilter | AntiBacterialFilter | ABF |
| 69 | S.Mask | MaskType | MSK |
| 70 | S.Tube | TubeType | TBT |
| 71 | S.ClimateControl | ClimateControl | CCO |
| 72 | S.HumEnable | HumidifierSettingEnable | HMX |
| 73 | S.HumLevel | HumidifierLevel | HMS |
| 74 | S.TempEnable | HeatedTubeSettingEnable | HTX |
| 75 | S.Temp | HeatedTubeTemperature | HTS |
| 76 | HeatedTube <sup>[map](#str-enum-export-maps)</sup> | Summary-TubeConnected | ZHT |
| 77 | Humidifier <sup>[map](#str-enum-export-maps)</sup> | Summary-HumidifierConnected | HUC |

### Environment and oximetry stats [78-91]

| # | Signal | name | short |
|---|--------|------|-------|
| 78 | BlowPress.95 | Summary-BlowerPressure-95 | BP9 |
| 79 | BlowPress.5 | Summary-BlowerPressure-5 | BP5 |
| 80 | Flow.95 | Summary-RespiratoryFlow-95 | R95 |
| 81 | Flow.5 | Summary-RespiratoryFlow-5 | RFM |
| 82 | BlowFlow.50 | Summary-BlowerFlow-50 | BFM |
| 83 | AmbHumidity.50 | Summary-AmbientHumidity-50 | AUM |
| 84 | HumTemp.50 | Summary-HumidifierTemperature-50 | HHE |
| 85 | HTubeTemp.50 | Summary-HeatedTubeTemperature-50 | HTE |
| 86 | HTubePow.50 | Summary-HeatedTubePower-50 | AHM |
| 87 | HumPow.50 | Summary-HumidifierPower-50 | APM |
| 88 | SpO2.50 | Summary-SpO2-50 | SOM |
| 89 | SpO2.95 | Summary-SpO2-95 | SO9 |
| 90 | SpO2.Max | Summary-SpO2-100 | SOX |
| 91 | SpO2Thresh | n/a | SAU |

### Bilevel/ventilation summary stats [92-124]

| # | Signal | name | short |
|---|--------|------|-------|
| 92 | SpontTrig% | Summary-SpontTriggerPercentage | VSR |
| 93 | SpontCyc% | Summary-SpontCyclePercentage | VCR |
| 94 | MaskPress.50 | Summary-MeanMaskPressure-50 | MSP |
| 95 | MaskPress.95 | Summary-MeanMaskPressure-95 | PM9 |
| 96 | MaskPress.Max | Summary-MeanMaskPressure-100 | PMA |
| 97 | TgtIPAP.50 | Summary-InspiratoryPressure-50 | PIM |
| 98 | TgtIPAP.95 | Summary-InspiratoryPressure-95 | PI9 |
| 99 | TgtIPAP.Max | Summary-InspiratoryPressure-100 | PIA |
| 100 | TgtEPAP.50 | Summary-ExpiratoryPressure-50 | PEM |
| 101 | TgtEPAP.95 | Summary-ExpiratoryPressure-95 | PE9 |
| 102 | TgtEPAP.Max | Summary-ExpiratoryPressure-100 | PEA |
| 103 | Leak.50 | Summary-Leak-50 | LKM |
| 104 | Leak.95 | Summary-Leak-95 | LK9 |
| 105 | Leak.70 | Summary-Leak-75 | LK7 |
| 106 | Leak.Max | Summary-Leak-100 | LMX |
| 107 | MinVent.50 | Summary-MinuteVentilation-50 | VTM |
| 108 | MinVent.95 | Summary-MinuteVentilation-95 | VT9 |
| 109 | MinVent.Max | Summary-MinuteVentilation-100 | VTA |
| 110 | RespRate.50 | Summary-RespiratoryRate-50 | RRM |
| 111 | RespRate.95 | Summary-RespiratoryRate-95 | RR9 |
| 112 | RespRate.Max | Summary-RespiratoryRate-100 | RRA |
| 113 | TidVol.50 | Summary-TidalVolume-50 | TVM |
| 114 | TidVol.95 | Summary-TidalVolume-95 | TV9 |
| 115 | TidVol.Max | Summary-TidalVolume-100 | TVA |
| 116 | TgtVent.50 | Summary-TargetMinuteVentilation-50 | VAM |
| 117 | TgtVent.95 | Summary-TargetMinuteVentilation-95 | VA9 |
| 118 | TgtVent.Max | Summary-TargetMinuteVentilation-100 | VAA |
| 119 | IERatio.50 | Summary-IeRatio-50 | IEM |
| 120 | IERatio.95 | Summary-IeRatio-95 | IE9 |
| 121 | IERatio.Max | Summary-IeRatio-100 | IEA |
| 122 | Ti.50 | Summary-InspiratoryDuration-50 | ISM |
| 123 | Ti.95 | Summary-InspiratoryDuration-95 | IS9 |
| 124 | Ti.Max | Summary-InspiratoryDuration-100 | ISA |

### Indices and CSR [125-132]

| # | Signal | name | short |
|---|--------|------|-------|
| 125 | AHI | Summary-ApneaHypopneaIndex | AHI |
| 126 | HI | Summary-HypopneaIndex | HSC |
| 127 | AI | Summary-ApneaIndex | ASC |
| 128 | OAI | Summary-ObstructiveApneaIndex | CSC |
| 129 | CAI | Summary-CentralApneaIndex | OSC |
| 130 | UAI | Summary-UnknownApneaIndex | USC |
| 131 | RIN | Summary-ReraIndex | RCC |
| 132 | CSR | n/a | CSD |

### Tail [133]

| # | Signal | name | short |
|---|--------|------|-------|
| 133 | Crc16 | n/a | n/a |

### STR enum export maps

Some STR enum fields are not written as raw CONF option indexes. For these
rows, firmware writes `edf_value = map[raw_option_index]`. A dash in the
superset-number column means that the mapped row exists in the stock schema
inventory but is not activated by the current 134-signal superset patch.

| Superset # | Signal | name | short | map |
|-----------:|--------|------|-------|-----|
| 5 | Mode | ActiveTherapyProfile | MOP | [3,1,2,4,10,16,8,6,7,5,9] |
| 20 | S.VA.Trigger | VAuto-TriggerSensitivity | XE6 | [1,2,3,4,5,6,7] |
| 21 | S.VA.Cycle | VAuto-CycleSensitivity | XE7 | [1,2,3,4,5,6,7] |
| 25 | S.S.EasyBreathe | Spont-EasyBreatheEnable | ZZ4 | [1,2] |
| 26 | S.S.RespRateEn | Spont-RespiratoryRateEnable | ZZ5 | [1,3] |
| 29 | S.S.RiseEnable | Spont-RiseTimeEnable | ZZ9 | [1,2] |
| 31 | S.S.Trigger | Spont-TriggerSensitivity | Z11 | [1,2,3,4,5,6,7] |
| 32 | S.S.Cycle | Spont-CycleSensitivity | Z12 | [1,2,3,4,5,6,7] |
| -- | S.S.FallEnable | Spont-FallTimeEnable | Z16 | [1,2] |
| 41 | S.ST.Trigger | ST-TriggerSensitivity | ZU1 | [1,2,3,4,5,6,7] |
| -- | S.ST.FallEnable | ST-FallTimeEnable | XAM | [1,2] |
| 48 | S.T.RiseEnable | Timed-RiseTimeEnable | XB6 | [1,2] |
| -- | S.T.FallEnable | Timed-FallTimeEnable | XB9 | [1,2] |
| 76 | HeatedTube | Summary-TubeConnected | ZHT | [3,4,1,5,2] |
| 77 | Humidifier | Summary-HumidifierConnected | HUC | [1,2,3] |

### STR variant provenance

This table keeps only STR rows that were not present in every checked OEM
variant before the EDF superset patch. `x` means the row was present in
that OEM firmware; `.` means it is added by the superset merge.

| # | Signal | name | short | AS | VA | ST | ASV |
|---|--------|------|-------|----|----|----|-----|
| 8 | S.A.StartPress | AutoSet-StartPressure | STU | x | . | . | . |
| 9 | S.A.MaxPress | AutoSet-MaxPressure | MPA | x | . | . | . |
| 10 | S.A.MinPress | AutoSet-MinPressure | MPI | x | . | . | . |
| 11 | S.AFH.StartPress | HerAuto-StartPressure | HSP | x | . | . | . |
| 12 | S.AFH.MaxPress | HerAuto-MaxPressure | HMA | x | . | . | . |
| 13 | S.AFH.MinPress | HerAuto-MinPressure | HMI | x | . | . | . |
| 14 | S.VA.StartPress | VAuto-StartPressure | XE0 | . | x | . | . |
| 15 | S.VA.MaxIPAP | VAuto-MaxInspiratoryPressure | XE1 | . | x | . | . |
| 16 | S.VA.MinEPAP | VAuto-MinExpiratoryPressure | XE2 | . | x | . | . |
| 17 | S.VA.PS | VAuto-SetPressureSupport | XE3 | . | x | . | . |
| 18 | S.VA.TiMax | VAuto-SetMaxInspiratoryTime | XE4 | . | x | . | . |
| 19 | S.VA.TiMin | VAuto-SetMinInspiratoryTime | XE5 | . | x | . | . |
| 20 | S.VA.Trigger | VAuto-TriggerSensitivity | XE6 | . | x | . | . |
| 21 | S.VA.Cycle | VAuto-CycleSensitivity | XE7 | . | x | . | . |
| 22 | S.S.StartPress | Spont-StartPressure | ZZ3 | . | x | x | . |
| 23 | S.S.IPAP | Spont-TargetInspiratoryPressure | ZZ1 | . | x | x | . |
| 24 | S.S.EPAP | Spont-TargetExpiratoryPressure | ZZ2 | . | x | x | . |
| 25 | S.S.EasyBreathe | Spont-EasyBreatheEnable | ZZ4 | . | x | . | . |
| 26 | S.S.RespRateEn | Spont-RespiratoryRateEnable | ZZ5 | . | x | x | . |
| 27 | S.S.TiMax | Spont-SetMaxInspiratoryTime | ZZ7 | . | x | x | . |
| 28 | S.S.TiMin | Spont-SetMinInspiratoryTime | ZZ8 | . | x | x | . |
| 29 | S.S.RiseEnable | Spont-RiseTimeEnable | ZZ9 | . | x | x | . |
| 30 | S.S.RiseTime | Spont-RiseTime | Z10 | . | x | x | . |
| 31 | S.S.Trigger | Spont-TriggerSensitivity | Z11 | . | x | x | . |
| 32 | S.S.Cycle | Spont-CycleSensitivity | Z12 | . | x | x | . |
| 33 | S.ST.StartPress | ST-StartPressure | XA3 | . | . | x | . |
| 34 | S.ST.IPAP | ST-TargetInspiratoryPressure | XA1 | . | . | x | . |
| 35 | S.ST.EPAP | ST-TargetExpiratoryPressure | XA2 | . | . | x | . |
| 36 | S.ST.RespRate | ST-SetRespiratoryRate | XA6 | . | . | x | . |
| 37 | S.ST.TiMax | ST-SetMaxInspiratoryTime | XA7 | . | . | x | . |
| 38 | S.ST.TiMin | ST-SetMinInspiratoryTime | XA8 | . | . | x | . |
| 39 | S.ST.RiseEnable | ST-RiseTimeEnable | XA9 | . | . | x | . |
| 40 | S.ST.RiseTime | ST-RiseTime | XAA | . | . | x | . |
| 41 | S.ST.Trigger | ST-TriggerSensitivity | ZU1 | . | . | x | . |
| 42 | S.ST.Cycle | ST-CycleSensitivity | XAB | . | . | x | . |
| 43 | S.T.StartPress | Timed-StartPressure | XB0 | . | . | x | . |
| 44 | S.T.IPAP | Timed-TargetInspiratoryPressure | XB1 | . | . | x | . |
| 45 | S.T.EPAP | Timed-TargetExpiratoryPressure | XB2 | . | . | x | . |
| 46 | S.T.RespRate | Timed-SetRespiratoryRate | XB4 | . | . | x | . |
| 47 | S.T.Ti | Timed-SetInspiratoryTime | XB5 | . | . | x | . |
| 48 | S.T.RiseEnable | Timed-RiseTimeEnable | XB6 | . | . | x | . |
| 49 | S.T.RiseTime | Timed-RiseTime | XB7 | . | . | x | . |
| 50 | S.AV.StartPress | ASV-StartPressure | XC0 | . | . | . | x |
| 51 | S.AV.EPAP | ASV-TargetExpiratoryPressure | XC1 | . | . | . | x |
| 52 | S.AV.MaxPS | ASV-MaxPressureSupport | XC2 | . | . | . | x |
| 53 | S.AV.MinPS | ASV-MinPressureSupport | XC3 | . | . | . | x |
| 54 | S.AA.StartPress | ASVAuto-StartPressure | XD0 | . | . | . | x |
| 55 | S.AA.MaxEPAP | ASVAuto-MaxExpiratoryPressure | XD1 | . | . | . | x |
| 56 | S.AA.MinEPAP | ASVAuto-MinExpiratoryPressure | XD2 | . | . | . | x |
| 57 | S.AA.MaxPS | ASVAuto-MaxPressureSupport | XD3 | . | . | . | x |
| 58 | S.AA.MinPS | ASVAuto-MinPressureSupport | XD4 | . | . | . | x |
| 59 | S.AS.Comfort | AutoSetComfort | AFC | x | . | . | . |
| 62 | S.EPR.ClinEnable | EprEnablePatientAccess | EPA | x | x | . | . |
| 63 | S.EPR.EPREnable | EprEnable | EPX | x | x | . | . |
| 64 | S.EPR.Level | EprPressure | EPR | x | x | . | . |
| 65 | S.EPR.EPRType | EprType | EPT | x | x | . | . |
| 92 | SpontTrig% | Summary-SpontTriggerPercentage | VSR | . | x | x | . |
| 93 | SpontCyc% | Summary-SpontCyclePercentage | VCR | . | x | x | . |
| 116 | TgtVent.50 | Summary-TargetMinuteVentilation-50 | VAM | . | . | . | x |
| 117 | TgtVent.95 | Summary-TargetMinuteVentilation-95 | VA9 | . | . | . | x |
| 118 | TgtVent.Max | Summary-TargetMinuteVentilation-100 | VAA | . | . | . | x |
| 119 | IERatio.50 | Summary-IeRatio-50 | IEM | . | x | x | . |
| 120 | IERatio.95 | Summary-IeRatio-95 | IE9 | . | x | x | . |
| 121 | IERatio.Max | Summary-IeRatio-100 | IEA | . | x | x | . |
| 122 | Ti.50 | Summary-InspiratoryDuration-50 | ISM | . | x | x | . |
| 123 | Ti.95 | Summary-InspiratoryDuration-95 | IS9 | . | x | x | . |
| 124 | Ti.Max | Summary-InspiratoryDuration-100 | ISA | . | x | x | . |
| 128 | OAI | Summary-ObstructiveApneaIndex | CSC | x | x | . | . |
| 129 | CAI | Summary-CentralApneaIndex | OSC | x | x | . | . |
| 130 | UAI | Summary-UnknownApneaIndex | USC | x | x | . | . |
| 131 | RIN | Summary-ReraIndex | RCC | x | . | . | . |
| 132 | CSR | n/a | CSD | x | . | . | . |

Legend:

| Column | Source firmware |
|--------|-----------------|
| AS | vid03 AirSense 11 AutoSet-class firmware |
| VA | vid07 AirCurve 11 VAuto-class firmware |
| ST | vid10 S/ST/Timed-class firmware |
| ASV | vid12 ASV/ASVAuto-class firmware |

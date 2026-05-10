# AirSense 11 EDF Signal Reference

Var ID columns are version-local. The 8.4.0 column is the AS11
15.8.4.0 superset used by the EDF patcher; the 8.3.0 column is mapped
from the checked 14.8.3.0 vid03 dump. `n/a` means no matching short tag
exists in that version. See `docs/as11/var_reference.tsv` for the source map.

Live RPC stream names are documented separately in
[AS11 RPC Stream Reference](rpc_streams.md).

## BRP.edf -- Breath waveform (25 Hz, 60s records)

| # | Signal | var_id 8.3.0 | var_id 8.4.0 | short | samples/rec | rate |
|---|--------|--------------|--------------|-------|-------------|------|
| 0 | Flow.40ms | 0x0256 | 0x026B | RFL | 1500 | 25 Hz |
| 1 | Press.40ms | 0x01D4 | 0x01E7 | MKP | 1500 | 25 Hz |

## PLD.edf -- Per-breath stats (0.5 Hz, 60s records)

| # | Signal | var_id 8.3.0 | var_id 8.4.0 | short | samples/rec | rate |
|---|--------|--------------|--------------|-------|-------------|------|
| 0 | MaskPress.2s | 0x012F | 0x013D | MKF | 30 | 0.5 Hz |
| 1 | Press.2s | 0x00BB | 0x00C9 | MKI | 30 | 0.5 Hz |
| 2 | EprPress.2s | 0x011D | 0x012B | MKE | 30 | 0.5 Hz |
| 3 | Leak.2s | 0x012C | 0x013A | LKF | 30 | 0.5 Hz |
| 4 | RespRate.2s | 0x016B | 0x017C | RR2 | 30 | 0.5 Hz |
| 5 | TidVol.2s | 0x02E4 | 0x02FD | TD2 | 30 | 0.5 Hz |
| 6 | MinVent.2s | 0x00D3 | 0x00E1 | MV2 | 30 | 0.5 Hz |
| 7 | TgtVent.2s | 0x02B2 | 0x02CB | TGT | 30 | 0.5 Hz |
| 8 | IERatio.2s | 0x01A0 | 0x01AF | IE2 | 30 | 0.5 Hz |
| 9 | Snore.2s | 0x027D | 0x0294 | SNI | 30 | 0.5 Hz |
| 10 | FlowLim.2s | 0x0141 | 0x014F | FFL | 30 | 0.5 Hz |
| 11 | Ti.2s | 0x0180 | 0x018F | INT | 30 | 0.5 Hz |

## SA2.edf -- SpO2/pulse (1 Hz, 60s records)

| # | Signal | var_id 8.3.0 | var_id 8.4.0 | short | samples/rec | rate |
|---|--------|--------------|--------------|-------|-------------|------|
| 0 | Pulse.1s | 0x0157 | 0x0168 | HRT | 60 | 1 Hz |
| 1 | SpO2.1s | 0x0285 | 0x029C | SAO | 60 | 1 Hz |

## STR.edf -- Session statistics (1 record per session, 134 fields)

### Session header [0-3]

| # | Signal | var_id 8.3.0 | var_id 8.4.0 | short |
|---|--------|--------------|--------------|-------|
| 0 | Date | n/a | n/a | n/a |
| 1 | MaskOn | n/a | n/a | n/a |
| 2 | MaskOff | n/a | n/a | n/a |
| 3 | MaskEvents | n/a | n/a | n/a |

### Session core [4-5]

| # | Signal | var_id 8.3.0 | var_id 8.4.0 | short |
|---|--------|--------------|--------------|-------|
| 4 | Duration | 0x029E | 0x02B6 | PPD |
| 5 | Mode | 0x03F1 | 0x040E | MOP |

### CPAP/AutoSet/HerAuto settings [6-13]

| # | Signal | var_id 8.3.0 | var_id 8.4.0 | short |
|---|--------|--------------|--------------|-------|
| 6 | S.C.StartPress | 0x0290 | 0x02A8 | STP |
| 7 | S.C.Press | 0x00F7 | 0x0105 | IPC |
| 8 | S.A.StartPress | 0x028F | 0x02A7 | STU |
| 9 | S.A.MaxPress | 0x01DE | 0x01F1 | MPA |
| 10 | S.A.MinPress | 0x01F5 | 0x0208 | MPI |
| 11 | S.AFH.StartPress | 0x0074 | 0x007C | HSP |
| 12 | S.AFH.MaxPress | 0x0072 | 0x007A | HMA |
| 13 | S.AFH.MinPress | 0x0073 | 0x007B | HMI |

### VAuto settings [14-21]

| # | Signal | var_id 8.3.0 | var_id 8.4.0 | short |
|---|--------|--------------|--------------|-------|
| 14 | S.VA.StartPress | 0x0300 | 0x0319 | XE0 |
| 15 | S.VA.MaxIPAP | 0x02FD | 0x0316 | XE1 |
| 16 | S.VA.MinEPAP | 0x02FE | 0x0317 | XE2 |
| 17 | S.VA.PS | 0x02FF | 0x0318 | XE3 |
| 18 | S.VA.TiMax | 0x0301 | 0x031A | XE4 |
| 19 | S.VA.TiMin | 0x0302 | 0x031B | XE5 |
| 20 | S.VA.Trigger | 0x0479 | 0x049E | XE6 |
| 21 | S.VA.Cycle | 0x0478 | 0x049D | XE7 |

### Spont settings [22-32]

| # | Signal | var_id 8.3.0 | var_id 8.4.0 | short |
|---|--------|--------------|--------------|-------|
| 22 | S.S.StartPress | 0x02AF | 0x02C8 | ZZ3 |
| 23 | S.S.IPAP | 0x02AC | 0x02C5 | ZZ1 |
| 24 | S.S.EPAP | 0x02A7 | 0x02C0 | ZZ2 |
| 25 | S.S.EasyBreathe | 0x0456 | 0x047A | ZZ4 |
| 26 | S.S.RespRateEn | 0x0458 | 0x047C | ZZ5 |
| 27 | S.S.TiMax | 0x02B0 | 0x02C9 | ZZ7 |
| 28 | S.S.TiMin | 0x02B1 | 0x02CA | ZZ8 |
| 29 | S.S.RiseEnable | 0x0459 | 0x047D | ZZ9 |
| 30 | S.S.RiseTime | 0x02AE | 0x02C7 | Z10 |
| 31 | S.S.Trigger | 0x045A | 0x047E | Z11 |
| 32 | S.S.Cycle | 0x0454 | 0x0477 | Z12 |

### ST/Timed settings [33-49]

| # | Signal | var_id 8.3.0 | var_id 8.4.0 | short |
|---|--------|--------------|--------------|-------|
| 33 | S.ST.StartPress | 0x0299 | 0x02B1 | XA3 |
| 34 | S.ST.IPAP | 0x0296 | 0x02AE | XA1 |
| 35 | S.ST.EPAP | 0x0292 | 0x02AA | XA2 |
| 36 | S.ST.RespRate | 0x0297 | 0x02AF | XA6 |
| 37 | S.ST.TiMax | 0x029B | 0x02B3 | XA7 |
| 38 | S.ST.TiMin | 0x029C | 0x02B4 | XA8 |
| 39 | S.ST.RiseEnable | 0x044B | 0x046E | XA9 |
| 40 | S.ST.RiseTime | 0x0298 | 0x02B0 | XAA |
| 41 | S.ST.Trigger | 0x044C | 0x046F | ZU1 |
| 42 | S.ST.Cycle | 0x0447 | 0x0469 | XAB |
| 43 | S.T.StartPress | 0x02F4 | 0x030D | XB0 |
| 44 | S.T.IPAP | 0x02F1 | 0x030A | XB1 |
| 45 | S.T.EPAP | 0x02EE | 0x0307 | XB2 |
| 46 | S.T.RespRate | 0x02F2 | 0x030B | XB4 |
| 47 | S.T.Ti | 0x02F5 | 0x030E | XB5 |
| 48 | S.T.RiseEnable | 0x0470 | 0x0495 | XB6 |
| 49 | S.T.RiseTime | 0x02F3 | 0x030C | XB7 |

### ASV/ASVAuto settings [50-58]

| # | Signal | var_id 8.3.0 | var_id 8.4.0 | short |
|---|--------|--------------|--------------|-------|
| 50 | S.AV.StartPress | 0x0098 | 0x00A4 | XC0 |
| 51 | S.AV.EPAP | 0x0097 | 0x00A3 | XC1 |
| 52 | S.AV.MaxPS | 0x0095 | 0x00A1 | XC2 |
| 53 | S.AV.MinPS | 0x0096 | 0x00A2 | XC3 |
| 54 | S.AA.StartPress | 0x0094 | 0x00A0 | XD0 |
| 55 | S.AA.MaxEPAP | 0x0090 | 0x009C | XD1 |
| 56 | S.AA.MinEPAP | 0x0092 | 0x009E | XD2 |
| 57 | S.AA.MaxPS | 0x0091 | 0x009D | XD3 |
| 58 | S.AA.MinPS | 0x0093 | 0x009F | XD4 |

### Common comfort/settings [59-77]

| # | Signal | var_id 8.3.0 | var_id 8.4.0 | short |
|---|--------|--------------|--------------|-------|
| 59 | S.AS.Comfort | 0x0336 | 0x034F | AFC |
| 60 | S.RampEnable | 0x040C | 0x0429 | RMA |
| 61 | S.RampTime | 0x023D | 0x0250 | RMT |
| 62 | S.EPR.ClinEnable | 0x0380 | 0x039E | EPA |
| 63 | S.EPR.EPREnable | 0x0381 | 0x039F | EPX |
| 64 | S.EPR.Level | 0x0126 | 0x0134 | EPR |
| 65 | S.EPR.EPRType | 0x0382 | 0x03A0 | EPT |
| 66 | S.SmartStart | 0x043B | 0x045D | SST |
| 67 | S.PtAccess | 0x03FC | 0x0419 | ACC |
| 68 | S.ABFilter | 0x0321 | 0x033A | ABF |
| 69 | S.Mask | 0x03DF | 0x03FE | MSK |
| 70 | S.Tube | 0x03AA | 0x03CB | TBT |
| 71 | S.ClimateControl | 0x0352 | 0x036B | CCO |
| 72 | S.HumEnable | 0x03B7 | 0x03D6 | HMX |
| 73 | S.HumLevel | 0x0179 | 0x0188 | HMS |
| 74 | S.TempEnable | 0x03A5 | 0x03C4 | HTX |
| 75 | S.Temp | 0x0164 | 0x0175 | HTS |
| 76 | HeatedTube | 0x03AC | 0x03CD | ZHT |
| 77 | Humidifier | 0x03B2 | 0x03D1 | HUC |

### Environment and oximetry stats [78-91]

| # | Signal | var_id 8.3.0 | var_id 8.4.0 | short |
|---|--------|--------------|--------------|-------|
| 78 | BlowPress.95 | 0x00C4 | 0x00D2 | BP9 |
| 79 | BlowPress.5 | 0x00C3 | 0x00D1 | BP5 |
| 80 | Flow.95 | 0x00B1 | 0x00BF | R95 |
| 81 | Flow.5 | 0x00B0 | 0x00BE | RFM |
| 82 | BlowFlow.50 | 0x00A9 | 0x00B7 | BFM |
| 83 | AmbHumidity.50 | 0x009E | 0x00AB | AUM |
| 84 | HumTemp.50 | 0x00A4 | 0x00B2 | HHE |
| 85 | HTubeTemp.50 | 0x00A2 | 0x00B0 | HTE |
| 86 | HTubePow.50 | 0x00A0 | 0x00AE | AHM |
| 87 | HumPow.50 | 0x00A6 | 0x00B4 | APM |
| 88 | SpO2.50 | 0x0288 | 0x029F | SOM |
| 89 | SpO2.95 | 0x0286 | 0x029D | SO9 |
| 90 | SpO2.Max | 0x0287 | 0x029E | SOX |
| 91 | SpO2Thresh | 0x0289 | 0x02A0 | SAU |

### Bilevel/ventilation summary stats [92-124]

| # | Signal | var_id 8.3.0 | var_id 8.4.0 | short |
|---|--------|--------------|--------------|-------|
| 92 | SpontTrig% | 0x028D | 0x02A4 | VSR |
| 93 | SpontCyc% | 0x028C | 0x02A3 | VCR |
| 94 | MaskPress.50 | 0x01D8 | 0x01EB | MSP |
| 95 | MaskPress.95 | 0x01D6 | 0x01E9 | PM9 |
| 96 | MaskPress.Max | 0x01D5 | 0x01E8 | PMA |
| 97 | TgtIPAP.50 | 0x01A2 | 0x01B1 | PIM |
| 98 | TgtIPAP.95 | 0x019D | 0x01AC | PI9 |
| 99 | TgtIPAP.Max | 0x01A1 | 0x01B0 | PIA |
| 100 | TgtEPAP.50 | 0x0129 | 0x0137 | PEM |
| 101 | TgtEPAP.95 | 0x0127 | 0x0135 | PE9 |
| 102 | TgtEPAP.Max | 0x0128 | 0x0136 | PEA |
| 103 | Leak.50 | 0x01B2 | 0x01C4 | LKM |
| 104 | Leak.95 | 0x01AF | 0x01C1 | LK9 |
| 105 | Leak.70 | 0x01AE | 0x01C0 | LK7 |
| 106 | Leak.Max | 0x01B1 | 0x01C3 | LMX |
| 107 | MinVent.50 | 0x01F8 | 0x020B | VTM |
| 108 | MinVent.95 | 0x01F6 | 0x0209 | VT9 |
| 109 | MinVent.Max | 0x01F7 | 0x020A | VTA |
| 110 | RespRate.50 | 0x025B | 0x0270 | RRM |
| 111 | RespRate.95 | 0x0259 | 0x026E | RR9 |
| 112 | RespRate.Max | 0x025A | 0x026F | RRA |
| 113 | TidVol.50 | 0x0305 | 0x031E | TVM |
| 114 | TidVol.95 | 0x0303 | 0x031C | TV9 |
| 115 | TidVol.Max | 0x0304 | 0x031D | TVA |
| 116 | TgtVent.50 | 0x02B6 | 0x02CF | VAM |
| 117 | TgtVent.95 | 0x02B4 | 0x02CD | VA9 |
| 118 | TgtVent.Max | 0x02B5 | 0x02CE | VAA |
| 119 | IERatio.50 | 0x01A5 | 0x01B4 | IEM |
| 120 | IERatio.95 | 0x01A3 | 0x01B2 | IE9 |
| 121 | IERatio.Max | 0x01A4 | 0x01B3 | IEA |
| 122 | Ti.50 | 0x0184 | 0x0193 | ISM |
| 123 | Ti.95 | 0x0182 | 0x0191 | IS9 |
| 124 | Ti.Max | 0x0183 | 0x0192 | ISA |

### Indices and CSR [125-132]

| # | Signal | var_id 8.3.0 | var_id 8.4.0 | short |
|---|--------|--------------|--------------|-------|
| 125 | AHI | 0x0075 | 0x007D | AHI |
| 126 | HI | 0x016C | 0x017D | HSC |
| 127 | AI | 0x0077 | 0x007F | ASC |
| 128 | OAI | 0x00D6 | 0x00E4 | CSC |
| 129 | CAI | 0x0202 | 0x0215 | OSC |
| 130 | UAI | 0x02F6 | 0x030F | USC |
| 131 | RIN | 0x025D | 0x0272 | RCC |
| 132 | CSR | 0x00FC | 0x010A | CSD |

### Tail [133]

| # | Signal | var_id 8.3.0 | var_id 8.4.0 | short |
|---|--------|--------------|--------------|-------|
| 133 | Crc16 | n/a | n/a | n/a |

### STR variant provenance

This table keeps only STR rows that were not present in every checked OEM
variant before the EDF superset patch. `x` means the row was present in
that OEM firmware; `.` means it is added by the superset merge.

| # | Signal | short | AS | VA | ST | ASV |
|---|--------|-------|----|----|----|-----|
| 8 | S.A.StartPress | STU | x | . | . | . |
| 9 | S.A.MaxPress | MPA | x | . | . | . |
| 10 | S.A.MinPress | MPI | x | . | . | . |
| 11 | S.AFH.StartPress | HSP | x | . | . | . |
| 12 | S.AFH.MaxPress | HMA | x | . | . | . |
| 13 | S.AFH.MinPress | HMI | x | . | . | . |
| 14 | S.VA.StartPress | XE0 | . | x | . | . |
| 15 | S.VA.MaxIPAP | XE1 | . | x | . | . |
| 16 | S.VA.MinEPAP | XE2 | . | x | . | . |
| 17 | S.VA.PS | XE3 | . | x | . | . |
| 18 | S.VA.TiMax | XE4 | . | x | . | . |
| 19 | S.VA.TiMin | XE5 | . | x | . | . |
| 20 | S.VA.Trigger | XE6 | . | x | . | . |
| 21 | S.VA.Cycle | XE7 | . | x | . | . |
| 22 | S.S.StartPress | ZZ3 | . | x | x | . |
| 23 | S.S.IPAP | ZZ1 | . | x | x | . |
| 24 | S.S.EPAP | ZZ2 | . | x | x | . |
| 25 | S.S.EasyBreathe | ZZ4 | . | x | . | . |
| 26 | S.S.RespRateEn | ZZ5 | . | x | x | . |
| 27 | S.S.TiMax | ZZ7 | . | x | x | . |
| 28 | S.S.TiMin | ZZ8 | . | x | x | . |
| 29 | S.S.RiseEnable | ZZ9 | . | x | x | . |
| 30 | S.S.RiseTime | Z10 | . | x | x | . |
| 31 | S.S.Trigger | Z11 | . | x | x | . |
| 32 | S.S.Cycle | Z12 | . | x | x | . |
| 33 | S.ST.StartPress | XA3 | . | . | x | . |
| 34 | S.ST.IPAP | XA1 | . | . | x | . |
| 35 | S.ST.EPAP | XA2 | . | . | x | . |
| 36 | S.ST.RespRate | XA6 | . | . | x | . |
| 37 | S.ST.TiMax | XA7 | . | . | x | . |
| 38 | S.ST.TiMin | XA8 | . | . | x | . |
| 39 | S.ST.RiseEnable | XA9 | . | . | x | . |
| 40 | S.ST.RiseTime | XAA | . | . | x | . |
| 41 | S.ST.Trigger | ZU1 | . | . | x | . |
| 42 | S.ST.Cycle | XAB | . | . | x | . |
| 43 | S.T.StartPress | XB0 | . | . | x | . |
| 44 | S.T.IPAP | XB1 | . | . | x | . |
| 45 | S.T.EPAP | XB2 | . | . | x | . |
| 46 | S.T.RespRate | XB4 | . | . | x | . |
| 47 | S.T.Ti | XB5 | . | . | x | . |
| 48 | S.T.RiseEnable | XB6 | . | . | x | . |
| 49 | S.T.RiseTime | XB7 | . | . | x | . |
| 50 | S.AV.StartPress | XC0 | . | . | . | x |
| 51 | S.AV.EPAP | XC1 | . | . | . | x |
| 52 | S.AV.MaxPS | XC2 | . | . | . | x |
| 53 | S.AV.MinPS | XC3 | . | . | . | x |
| 54 | S.AA.StartPress | XD0 | . | . | . | x |
| 55 | S.AA.MaxEPAP | XD1 | . | . | . | x |
| 56 | S.AA.MinEPAP | XD2 | . | . | . | x |
| 57 | S.AA.MaxPS | XD3 | . | . | . | x |
| 58 | S.AA.MinPS | XD4 | . | . | . | x |
| 59 | S.AS.Comfort | AFC | x | . | . | . |
| 62 | S.EPR.ClinEnable | EPA | x | x | . | . |
| 63 | S.EPR.EPREnable | EPX | x | x | . | . |
| 64 | S.EPR.Level | EPR | x | x | . | . |
| 65 | S.EPR.EPRType | EPT | x | x | . | . |
| 92 | SpontTrig% | VSR | . | x | x | . |
| 93 | SpontCyc% | VCR | . | x | x | . |
| 116 | TgtVent.50 | VAM | . | . | . | x |
| 117 | TgtVent.95 | VA9 | . | . | . | x |
| 118 | TgtVent.Max | VAA | . | . | . | x |
| 119 | IERatio.50 | IEM | . | x | x | . |
| 120 | IERatio.95 | IE9 | . | x | x | . |
| 121 | IERatio.Max | IEA | . | x | x | . |
| 122 | Ti.50 | ISM | . | x | x | . |
| 123 | Ti.95 | IS9 | . | x | x | . |
| 124 | Ti.Max | ISA | . | x | x | . |
| 128 | OAI | CSC | x | x | . | . |
| 129 | CAI | OSC | x | x | . | . |
| 130 | UAI | USC | x | x | . | . |
| 131 | RIN | RCC | x | . | . | . |
| 132 | CSR | CSD | x | . | . | . |

Legend:

| Column | Source firmware |
|--------|-----------------|
| AS | vid03 AirSense 11 AutoSet-class firmware |
| VA | vid07 AirCurve 11 VAuto-class firmware |
| ST | vid10 S/ST/Timed-class firmware |
| ASV | vid12 ASV/ASVAuto-class firmware |

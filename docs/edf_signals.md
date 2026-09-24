# Air 10 EDF Signal Reference

## BRP.edf -- Breath waveform (25 Hz, 60s records)

| # | Signal | Name | samples/rec | rate | EL | AS | VA | ASV | ST-A |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | Flow.40ms | RFL | 1500 | 25 Hz | x | x | x | x | x |
| 1 | Press.40ms | MKP | 1500 | 25 Hz | x | x | x | x | x |
| 2 | TrigCycEvt.40ms | TCV | 1500 | 25 Hz | . | . | x | . | x |
| 3 | Crc16 | DCR | 1 | 1/rec | x | x | x | x | x |

## PLD.edf -- Per-breath stats (0.5 Hz, 60s records)

| # | Signal | Name | samples/rec | rate | EL | AS | VA | ASV | ST-A |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | MaskPress.2s | MKF | 30 | 0.5 Hz | x | x | x | x | x |
| 1 | Press.2s | MKI | 30 | 0.5 Hz | x | x | x | x | x |
| 2 | EprPress.2s | MKE | 30 | 0.5 Hz | x | x | x | x | x |
| 3 | Leak.2s | LKF | 30 | 0.5 Hz | x | x | x | x | x |
| 4 | RespRate.2s | RRR | 30 | 0.5 Hz | x | x | x | x | x |
| 5 | TidVol.2s | TDD | 30 | 0.5 Hz | x | x | x | x | x |
| 6 | MinVent.2s | MV5 | 30 | 0.5 Hz | x | x | x | x | x |
| 7 | TgtVent.2s | TGT | 30 | 0.5 Hz | . | . | . | x | . |
| 8 | IERatio.2s | IER | 30 | 0.5 Hz | . | . | x | . | x |
| 9 | Snore.2s | SNI | 30 | 0.5 Hz | x | x | x | x | . |
| 10 | FlowLim.2s | FFL | 30 | 0.5 Hz | x | x | x | x | . |
| 11 | B5ITime.2s | IN5 | 30 | 0.5 Hz | . | . | x | . | x |
| 12 | B5ETime.2s | EX5 | 30 | 0.5 Hz | . | . | x | . | x |
| 13 | Ti.2s | INT | 30 | 0.5 Hz | . | . | x | . | x |
| 14 | AlvMinVent.2s | AAV | 30 | 0.5 Hz | . | . | . | . | x |
| 15 | CLRatio.2s | RCR | 30 | 0.5 Hz | . | . | . | . | x |
| 16 | TRRatio.2s | RTR | 30 | 0.5 Hz | . | . | . | . | x |
| 17 | Crc16 | DCR | 1 | 1/rec | x | x | x | x | x |

## SAD.edf -- SpO2/pulse (1 Hz, 60s records)

| # | Signal | Name | samples/rec | rate | EL | AS | VA | ASV | ST-A |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | Pulse.1s | HRT | 60 | 1 Hz | x | x | x | x | x |
| 1 | SpO2.1s | SAO | 60 | 1 Hz | x | x | x | x | x |
| 2 | Crc16 | DCR | 1 | 1/rec | x | x | x | x | x |

## OXH -- Oximetry summary (g[28], per-session)

| # | Signal | Name | EL | AS | VA | ASV | ST-A |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | OXS | OXS | x | x | x | x | x |
| 1 | HRS | HRS | x | x | x | x | x |
| 2 | HRR | HRR | x | x | x | x | x |
| 3 | SAS | SAS | x | x | x | x | x |
| 4 | SAR | SAR | x | x | x | x | x |
| 5 | NVS | NVS | x | x | x | x | x |

## STR.edf - Daily summaries (152-field catalogue)

### Session header [0-3]

| # | Signal | Name | EL | AS | VA | ASV | ST-A |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | Date | LSD | x | x | x | x | x |
| 1 | MaskOn | ONT | x | x | x | x | x |
| 2 | MaskOff | OFT | x | x | x | x | x |
| 3 | MaskEvents | MSE | x | x | x | x | x |

### Session timing [4-7]

| # | Signal | Name | EL | AS | VA | ASV | ST-A |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 4 | Duration | OND | x | x | x | x | x |
| 5 | OnDuration | THD | x | x | x | x | x |
| 6 | PatientHours | PHM | x | x | x | x | x |
| 7 | Mode | MOP | x | x | x | x | x |

### CPAP/common settings [8-15]

| # | Signal | Name | EL | AS | VA | ASV | ST-A |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 8 | S.RampEnable | RMA | x | x | x | x | x |
| 9 | S.RampTime | RMT | x | x | x | x | x |
| 10 | S.C.StartPress | STP | x | x | x | x | x |
| 11 | S.C.Press | IPC | x | x | x | x | x |
| 12 | S.EPR.ClinEnable | EPA | x | x | x | . | . |
| 13 | S.EPR.EPREnable | EPX | x | x | x | . | . |
| 14 | S.EPR.Level | EPR | x | x | x | . | . |
| 15 | S.EPR.EPRType | EPT | x | x | x | . | . |

### Bilevel settings [16-29]

| # | Signal | Name | EL | AS | VA | ASV | ST-A |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 16 | S.BL.StartPress | EPS | . | . | x | . | x |
| 17 | S.BL.IPAP | IPP | . | . | x | . | x |
| 18 | S.BL.EPAP | EPP | . | . | x | . | x |
| 19 | S.EasyBreathe | EBE | . | . | x | . | . |
| 20 | S.VA.StartPress | STV | . | . | x | . | . |
| 21 | S.VA.MaxIPAP | MXI | . | . | x | . | . |
| 22 | S.VA.MinEPAP | MNE | . | . | x | . | . |
| 23 | S.VA.PS | SPT | . | . | x | . | . |
| 24 | S.RiseEnable | RSC | . | . | x | . | x |
| 25 | S.RiseTime | RST | . | . | x | . | x |
| 26 | S.Cycle | VCS | . | . | x | . | x |
| 27 | S.Trigger | VTS | . | . | x | . | x |
| 28 | S.TiMax | ITX | . | . | x | . | x |
| 29 | S.TiMin | ITN | . | . | x | . | x |

### AutoSet settings [30-33]

| # | Signal | Name | EL | AS | VA | ASV | ST-A |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 30 | S.AS.Comfort | AFC | . | x | . | . | . |
| 31 | S.AS.StartPress | STU | . | x | . | . | . |
| 32 | S.AS.MaxPress | MPA | . | x | . | . | . |
| 33 | S.AS.MinPress | MPI | . | x | . | . | . |

### ASV settings [34-42]

| # | Signal | Name | EL | AS | VA | ASV | ST-A |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 34 | S.AV.StartPress | STE | . | . | . | x | . |
| 35 | S.AV.EPAP | EEP | . | . | . | x | . |
| 36 | S.AV.MaxPS | MXS | . | . | . | x | . |
| 37 | S.AV.MinPS | MNS | . | . | . | x | . |
| 38 | S.AA.StartPress | EAS | . | . | . | x | . |
| 39 | S.AA.MaxEPAP | EAX | . | . | . | x | . |
| 40 | S.AA.MinEPAP | EAI | . | . | . | x | . |
| 41 | S.AA.MaxPS | AXS | . | . | . | x | . |
| 42 | S.AA.MinPS | ANS | . | . | . | x | . |

### Common tail settings [43-56]

| # | Signal | Name | EL | AS | VA | ASV | ST-A |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 43 | S.SmartStart | SST | x | x | x | x | x |
| 44 | S.PtAccess | ACC | x | x | x | x | x |
| 45 | S.ABFilter | ABF | x | x | x | x | x |
| 46 | S.LeakAlert | ALR | . | . | x | x | . |
| 47 | S.Mask | MSK | x | x | x | x | x |
| 48 | S.Tube | TBT | x | x | x | x | x |
| 49 | S.ClimateControl | CCO | x | x | x | x | x |
| 50 | S.HumEnable | HMX | x | x | x | x | x |
| 51 | S.HumLevel | HMS | x | x | x | x | x |
| 52 | S.TempEnable | HTX | x | x | x | x | x |
| 53 | S.Temp | HTS | x | x | x | x | x |
| 54 | S.ExternalHum | HME | . | . | . | x | x |
| 55 | HeatedTube | HTB | x | x | x | x | x |
| 56 | Humidifier | HUM | x | x | x | x | x |

### EVE block 1 -- environmental/hardware stats [57-69]

| # | Signal | Name | EL | AS | VA | ASV | ST-A |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 57 | BlowPress.95 | BP9 | x | x | x | x | x |
| 58 | BlowPress.5 | BP5 | x | x | x | x | x |
| 59 | Flow.95 | RF9 | x | x | x | x | x |
| 60 | Flow.5 | RF5 | x | x | x | x | x |
| 61 | BlowFlow.50 | BFM | x | x | x | x | x |
| 62 | AmbHumidity.50 | ABM | x | x | x | x | x |
| 63 | HumTemp.50 | HHM | x | x | x | x | x |
| 64 | HTubeTemp.50 | HTM | x | x | x | x | x |
| 65 | HTubePow.50 | TPM | x | x | x | x | x |
| 66 | HumPow.50 | HPM | x | x | x | x | x |
| 67 | SpO2.50 | SOM | x | x | x | x | x |
| 68 | SpO2.95 | SO9 | x | x | x | x | x |
| 69 | SpO2.Max | SOX | x | x | x | x | x |

### Standalone CSL fields [70-72]

| # | Signal | Name | EL | AS | VA | ASV | ST-A |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 70 | SpO2Thresh | SAU | x | x | x | x | x |
| 71 | CSR | CSD | x | x | . | . | . |
| 72 | SpontCyc% | VCR | . | . | x | . | x |

### EVE block 2 -- therapy stats percentiles [73-103]

| # | Signal | Name | EL | AS | VA | ASV | ST-A |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 73 | MaskPress.50 | MSP | x | x | x | x | x |
| 74 | MaskPress.95 | PM9 | x | x | x | x | x |
| 75 | MaskPress.Max | PMA | x | x | x | x | x |
| 76 | TgtIPAP.50 | PIM | x | x | x | x | x |
| 77 | TgtIPAP.95 | PI9 | x | x | x | x | x |
| 78 | TgtIPAP.Max | PIA | x | x | x | x | x |
| 79 | TgtEPAP.50 | PEM | x | x | x | x | x |
| 80 | TgtEPAP.95 | PE9 | x | x | x | x | x |
| 81 | TgtEPAP.Max | PEA | x | x | x | x | x |
| 82 | Leak.50 | LKM | x | x | x | x | x |
| 83 | Leak.95 | LK9 | x | x | x | x | x |
| 84 | Leak.70 | LK7 | x | x | x | x | x |
| 85 | Leak.Max | LMX | x | x | x | x | x |
| 86 | MinVent.50 | VTM | x | x | x | x | x |
| 87 | MinVent.95 | VT9 | x | x | x | x | x |
| 88 | MinVent.Max | VTA | x | x | x | x | x |
| 89 | RespRate.50 | RRM | x | x | x | x | x |
| 90 | RespRate.95 | RR9 | x | x | x | x | x |
| 91 | RespRate.Max | RRA | x | x | x | x | x |
| 92 | TidVol.50 | TVM | x | x | x | x | x |
| 93 | TidVol.95 | TV9 | x | x | x | x | x |
| 94 | TidVol.Max | TVA | x | x | x | x | x |
| 95 | IERatio.50 | IEM | . | . | x | . | x |
| 96 | IERatio.95 | IE9 | . | . | x | . | x |
| 97 | IERatio.Max | IEA | . | . | x | . | x |
| 98 | Ti.50 | ISM | . | . | x | . | x |
| 99 | Ti.95 | IS9 | . | . | x | . | x |
| 100 | Ti.Max | ISA | . | . | x | . | x |
| 101 | TgtVent.50 | VAM | . | . | . | x | . |
| 102 | TgtVent.95 | VA9 | . | . | . | x | . |
| 103 | TgtVent.Max | VAA | . | . | . | x | . |

### AEV -- apnea/hypopnea indices [104-110]

| # | Signal | Name | EL | AS | VA | ASV | ST-A |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 104 | AHI | AHI | x | x | x | x | x |
| 105 | HI | HIS | x | x | x | x | x |
| 106 | AI | AIS | x | x | x | x | x |
| 107 | OAI | CLI | x | x | x | . | . |
| 108 | CAI | OPI | x | x | x | . | . |
| 109 | UAI | UAI | x | x | x | . | . |
| 110 | RIN | RIN | . | x | . | . | . |

### Faults [111-114]

| # | Signal | Name | EL | AS | VA | ASV | ST-A |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 111 | Fault.Device | SYS | x | x | x | x | x |
| 112 | Fault.Alarm | SYT | x | x | x | x | x |
| 113 | Fault.Humidifier | SYC | x | x | x | x | x |
| 114 | Fault.HeatedTube | SYH | x | x | x | x | x |

### Bilevel settings and statistics [115-118]

| # | Signal | Name | EL | AS | VA | ASV | ST-A |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 115 | S.BL.BackupRate | BRR | . | . | . | . | x |
| 116 | S.BL.RespRate | RRT | . | . | . | . | x |
| 117 | S.Ti | ITT | . | . | . | . | x |
| 118 | SpontTrig% | VSR | . | . | . | . | x |

### Additional bilevel and iVAPS settings [119-131]

| # | Signal | Name | EL | AS | VA | ASV | ST-A |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 119 | S.RampDownEnable | RDA | - | - | - | - | x |
| 120 | S.BL.IBR | VBE | - | - | - | - | x |
| 121 | S.BL.TgtRR | TBR | - | - | - | - | x |
| 122 | S.i.StartPress | IVS | - | - | - | - | x |
| 123 | S.i.EPAP | EPI | - | - | - | - | x |
| 124 | S.i.EPAPAuto | IEU | - | - | - | - | x |
| 125 | S.i.MaxPS | WPA | - | - | - | - | x |
| 126 | S.i.MinPS | WPM | - | - | - | - | x |
| 127 | S.i.MinEPAP | IMN | - | - | - | - | x |
| 128 | S.i.MaxEPAP | IMX | - | - | - | - | x |
| 129 | S.i.Height | PHT | - | - | - | - | x |
| 130 | S.i.AlvMinVent | WMV | - | - | - | - | x |
| 131 | S.i.RespRate | IBR | - | - | - | - | x |

### Oximetry and alarm settings [132-141]

| # | Signal | Name | EL | AS | VA | ASV | ST-A |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 132 | ODIThreshold | ODT | - | - | - | - | x |
| 133 | NVMask.Alm.En | NMF | - | - | - | - | x |
| 134 | HiLeak.Alm.En | HLE | - | - | - | - | x |
| 135 | LowMV.Alm.Thres | LMA | - | - | - | - | x |
| 136 | LowMV.Alm.En | LMO | - | - | - | - | x |
| 137 | Apnea.Alm.Thres | APX | - | - | - | - | x |
| 138 | Apnea.Alm.En | APO | - | - | - | - | x |
| 139 | Alm.Vol | ALV | - | - | - | - | x |
| 140 | Spo2.Alm.Thres | SPX | - | - | - | - | x |
| 141 | Spo2.Alm.En | SPO | - | - | - | - | x |

### Additional statistics [142-150]

| # | Signal | Name | EL | AS | VA | ASV | ST-A |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 142 | HeartRate.50 | HR5 | - | - | - | - | x |
| 143 | HeartRate.Max | HRX | - | - | - | - | x |
| 144 | HeartRate.95 | HRM | - | - | - | - | x |
| 145 | SpO2.Min | SOZ | - | - | - | - | x |
| 146 | AlvMinVent.50 | AVM | - | - | - | - | x |
| 147 | AlvMinVent.95 | AV9 | - | - | - | - | x |
| 148 | AlvMinVent.Max | AVA | - | - | - | - | x |
| 149 | ODI | ODI | - | - | - | - | x |
| 150 | Oxy.Dur | ODD | - | - | - | - | x |

### Checksum [119 / 151]

| # | Signal | Name | EL | AS | VA | ASV | ST-A |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 119 / 151 | Crc16 | DCR | x | x | x | x | x |

## NPD - Periodic night profile

| # | Name | EL | AS | VA | ASV | ST-A |
| --- | --- | --- | --- | --- | --- | --- |
| 0 | LRP | x | x | x | x | x |
| 1 | LRE | x | x | x | x | x |
| 2 | LKP | x | x | x | x | x |
| 3 | MVT | x | x | x | x | x |
| 4 | ATI | x | x | x | x | x |
| 5 | RR1 | x | x | x | x | x |
| 6 | SAV | x | x | x | x | x |
| 7 | AIE | . | . | x | . | . |
| 8 | RCR | . | . | . | . | x |
| 9 | RTR | . | . | . | . | x |
| 10 | HAV | - | - | - | - | x |
| 11 | HMI | - | - | - | - | x |
| 12 | HMA | - | - | - | - | x |
| 13 | SMO | - | - | - | - | x |

EL = Elite (37117/37123), AS = AirSense 10 AutoSet class (37028/37031/37090/37101/37105), VA = AirCurve VAuto (37051/37164), ASV = AirCurve CS PaceWave (37113)
ST-A = Lumis VPAP 150 ST-A (28511, SX584-0204).

`x` = present in the checked OEM schema; `.` = added by the superset merge;
`-` = not included for this firmware family.

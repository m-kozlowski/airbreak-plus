# Air11 EDF Annotation Reference

This document describes the EDF+ annotation files Air11 writes alongside
the sampled signal files: `EVE.edf` (respiratory events) and `CSL.edf`
(Cheyne-Stokes interval boundaries). \
Sampled signal files are documented in \
[Air11 EDF Signal Reference](edf_signals.md). \
The matching live event vocabulary is documented in \
[Air11 RPC Event Reference](rpc_events.md). \
EDF fixed headers and ResMed patient/recording fields are documented in \
[Air11 EDF Header Reference](edf_header.md).

## Contents

- [File layout](#file-layout)
- [Annotation payload](#annotation-payload)
- [CRC channel](#crc-channel)
- [EVE.edf labels](#eveedf-labels)
- [CSL.edf labels](#csledf-labels)


## File layout

`EVE.edf` and `CSL.edf` share the same two-signal EDF+ container.

| Field | Value |
|-------|-------|
| EDF reserved field | `EDF+D` |
| EDF header size | `768` bytes |
| number of signals | `2` |
| record duration | `0.00` |
| signal 0 label | `EDF Annotations` |
| signal 1 label | `Crc16` |
| annotation samples per record | `31` |
| CRC samples per record | `1` |
| bytes per data record | `64` |

Signal metadata:

| Signal | Label | Unit | Physical min | Physical max | Digital min | Digital max | Samples/record |
|--------|-------|------|--------------|--------------|-------------|-------------|----------------|
| 0 | `EDF Annotations` | blank | `-32768.0` | `32767.00` | `-32768` | `32767` | `31` |
| 1 | `Crc16` | blank | `-32768.0` | `32767.00` | `-32768` | `32767` | `1` |

Although the annotation signal declares `31` int16 samples per record,
Air11 treats it as a 62-byte byte buffer. The trailing `Crc16` signal
contributes one little-endian 16-bit sample. Per data record:

```text
record:
  62 bytes  EDF+ TAL annotation payload
   2 bytes  little-endian CRC16 over the 62 payload bytes
```

## Annotation payload

Each 62-byte payload begins with an empty EDF+ timekeeping TAL, followed
by one event TAL, then `0x00` padding:

```text
+0 0x14 0x14 0x00 +<onset> 0x15 <duration> 0x14 <label> 0x14 0x00 0x00...
```

- `<onset>` and `<duration>` are integer ASCII seconds.
- `<onset>` is relative to the EDF header start time.
- `0x14` is the EDF+ TAL separator (delimits onset/duration/label/end).
- `0x15` is the duration separator.

Example payload, decoded:

```text
+0<14><14><00>+569<15>11<14>Obstructive Apnea<14><00>...
```

| Field | Value |
|-------|-------|
| onset | `569` seconds from EDF file start |
| duration | `11` seconds |
| label | `Obstructive Apnea` |

The first data record in both `EVE.edf` and `CSL.edf` is a fixed
"recording starts" marker:

```text
+0<14><14><00>+0<15>0<14>Recording starts<14><00>...
```

Records contain one event TAL each. Air11 does not pack multiple TALs
into a single record even though EDF+ allows it.

## CRC channel

`Crc16` is the project's standard CRC16-CCITT-FALSE, computed over the 62-byte
annotation payload only and stored **little-endian**.

## EVE.edf labels

Respiratory event annotations. The label set comes from the firmware
event-label table for `EVE` and maps to the
`TherapyEvents-RespiratoryEvents` RPC family.

| RPC event label | EDF annotation label |
|-----------------|----------------------|
| `HypopneaEnd` | `Hypopnea` |
| `CentralApneaEnd` | `Central Apnea` |
| `ObstructiveApneaEnd` | `Obstructive Apnea` |
| `ApneaEnd` | `Apnea` |
| `ReraEnd` | `Arousal` |

## CSL.edf labels

Cheyne-Stokes interval boundary annotations. The firmware
event-label table for `CSL` lists boundary records, not a single
interval-duration record:

| EDF annotation label | Meaning |
|----------------------|---------|
| `CSR Start` | start of a CSR/Cheyne-Stokes interval |
| `CSR End` | end of a CSR/Cheyne-Stokes interval |

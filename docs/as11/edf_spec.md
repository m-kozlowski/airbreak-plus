# AirSense 11 SD-Card EDF File Format

A complete, standalone specification of the EDF/EDF+ files that the ResMed
AirSense 11 (AutoSet-class, firmware 15.8.4.0 / 14.8.3.0) writes to its SD card
under `DATALOG/`. It contains everything needed to generate byte-faithful files:
header layout, exact per-signal scaling, the per-record CRC, the patient-field
checksum, the EDF+ annotation encoding, and the 60-second record cadence.

> **Provided for educational and interoperability purposes.** This document
> describes an on-disk file format produced by a device the author legally owns.
> It is published to enable the owner to read and reproduce their own therapy
> data with their own software, consistent with 17 U.S.C. § 1201(f) and
> equivalent interoperability provisions elsewhere. The author is not affiliated
> with ResMed. "ResMed", "AirSense", and related marks belong to their owners.

## How this was reverse-engineered

The format is **not officially published**. Every value below was derived
empirically from real device output and is reproducible:

- **Corpus:** 1925 original `.edf` files written by one AS11 across 123 nights,
  plus byte-level diffs of capture-vs-device files for the same therapy run.
- **Fields** (labels, units, digital/physical ranges, `dur`, `reserved`,
  filenames) were read directly from the device's own headers.
- **Per-record `Crc16`** was identified by treating the trailing signal as a
  checksum and brute-forcing the CRC catalogue until every record of every file
  matched (CRC-16/CCITT-FALSE; verified on all 5 file types).
- **Patient-field tokens** were cracked by observing that the token differs only
  by header content (not data), then a full 65536-polynomial CRC brute over the
  blanked header; the resulting formula reproduces the tokens on **1925/1925**
  files (see §6).

## Status

| Aspect | Status |
|---|---|
| Fixed 256-byte header layout | Verified, byte-exact |
| Per-signal header layout | Verified, byte-exact |
| BRP / PLD / SA2 signal specs (labels, units, ranges, rates) | Verified, byte-exact |
| EVE / CSL annotation (TAL) encoding | Verified, byte-exact |
| Per-record `Crc16` algorithm | Verified on all records of all 5 types |
| Patient-field `H1`/`H2` tokens | Verified on 1925/1925 files |
| 60 s record cadence + event anchoring | Verified from device timeline |
| `STR.edf` daily summary | Partially documented (see §11) |

---

## Table of contents

- [1. File set & directory layout](#1-file-set--directory-layout)
- [2. EDF container layout](#2-edf-container-layout)
- [3. Fixed 256-byte header](#3-fixed-256-byte-header)
- [4. Per-signal headers](#4-per-signal-headers)
- [5. Recording & patient text fields](#5-recording--patient-text-fields)
- [6. Patient-field tokens H1 / H2](#6-patient-field-tokens-h1--h2)
- [7. Data records & sample scaling](#7-data-records--sample-scaling)
- [8. The Crc16 signal](#8-the-crc16-signal)
- [9. Per-file signal specifications](#9-per-file-signal-specifications)
- [10. EVE / CSL annotations (EDF+ TAL)](#10-eve--csl-annotations-edf-tal)
- [11. STR.edf (daily summary)](#11-stredf-daily-summary)
- [12. Record cadence & anchoring](#12-record-cadence--anchoring)
- [13. Data sources (for live/offline generation)](#13-data-sources-for-liveoffline-generation)
- [14. End-to-end write procedure](#14-end-to-end-write-procedure)
- [15. Reference implementation](#15-reference-implementation)

---

## 1. File set & directory layout

```
<card root>/
├── Identification.json            # device identity (minified JSON)
├── Identification.crc             # CRC of Identification.json
├── STR.edf                        # daily cumulative summary (see §11)
├── SETTINGS/
│   ├── CurrentSettings.json       # active settings (minified JSON)
│   └── CurrentSettings.crc
└── DATALOG/
    └── <YYYYMMDD>/                # local date of the session
        ├── <YYYYMMDD_HHMMSS>_BRP.edf   # breath waveform (25 Hz)
        ├── <YYYYMMDD_HHMMSS>_PLD.edf   # per-breath stats (0.5 Hz)
        ├── <YYYYMMDD_HHMMSS>_SA2.edf   # pulse / SpO2 (1 Hz)
        ├── <YYYYMMDD_HHMMSS>_EVE.edf   # respiratory event annotations
        └── <YYYYMMDD_HHMMSS>_CSL.edf   # clinical/summary annotations
```

Key points:

- **Filenames** are `YYYYMMDD_HHMMSS_TYPE.edf` using **local time**, underscores
  between date, time, and type. The timestamp equals the file's header start
  time (§3).
- The AS11 emits **five** per-session file types: `BRP`, `PLD`, `SA2`, `EVE`,
  `CSL`. (`SAD`/`AEV` from older ResMed devices are not used.)
- **There are no per-`.edf` `.crc` files.** Integrity is an internal `Crc16`
  signal inside every EDF (§8). The only `.crc` files on the card are
  `Identification.crc` and `SETTINGS/CurrentSettings.crc`.
- `BRP`/`PLD`/`SA2` of one night share one timestamp (the MaskOn second);
  `EVE`/`CSL` share a slightly earlier one (the TherapyStart second). See §12.

---

## 2. EDF container layout

All files are EDF / EDF+ (`edfplus.info`). Byte order for samples is
**little-endian signed 16-bit**. Layout:

```
[ fixed header            : 256 bytes              ]
[ per-signal header block : ns × 256 bytes         ]   ns = signal count incl. Crc16
[ data records            : nrec × record_size     ]
```

- `ns` counts **every** signal, including the trailing `Crc16` signal and (for
  EVE/CSL) the `EDF Annotations` signal.
- `record_size = (Σ spr_i) × 2` bytes, where `spr_i` is samples-per-record of
  signal *i* (the `Crc16` signal has `spr = 1`).
- All header fields are **ASCII**, left-justified, **space-padded** to width.
- Integer/float header fields are decimal text (e.g. `"60.00   "`, `"1500    "`).

---

## 3. Fixed 256-byte header

| Offset | Len | Field | AS11 value |
|-------:|----:|-------|------------|
| 0   | 8  | version          | `"0"` |
| 8   | 80 | patient id       | `"X X X X <H1> <H2>"` (see §5, §6) |
| 88  | 80 | recording id     | `"Startdate DD-MMM-YYYY X X X SRN=… MID=… VID=…"` (§5) |
| 168 | 8  | start date       | `"DD.MM.YY"` (local) |
| 176 | 8  | start time       | `"HH.MM.SS"` (local) |
| 184 | 8  | header bytes     | `256 + ns × 256` |
| 192 | 44 | reserved         | `"EDF"` for BRP/PLD/SA2; `"EDF+D"` for EVE/CSL |
| 236 | 8  | num data records | `nrec` |
| 244 | 8  | record duration  | `"60.00"` for BRP/PLD/SA2; `"0.00"` for EVE/CSL |
| 252 | 4  | num signals (ns) | total signal count incl. `Crc16` |

Notes:

- **`reserved`** is `EDF` (plain) for the sampled files and `EDF+D`
  (discontinuous) for the annotation files — **not** `EDF+C`.
- Date/time are **local time with no timezone**; the start instant is the
  anchor second from §12.
- `header bytes` examples: BRP/SA2 `ns=3 → 1024`; PLD `ns=10 → 2816`;
  EVE/CSL `ns=2 → 768`.

---

## 4. Per-signal headers

The per-signal block stores each field for **all** signals before moving to the
next field (column-major). Field widths per signal:

| Field | Width | Notes |
|-------|------:|-------|
| label                | 16 | e.g. `"Flow.40ms"`, `"EDF Annotations"`, `"Crc16"` |
| transducer type      | 80 | blank |
| physical dimension   | 8  | unit string, e.g. `"L/s"`, `"cmH2O"`, `"bpm"`, `"%"`; blank if none |
| physical minimum     | 8  | decimal text (`pmin`) |
| physical maximum     | 8  | decimal text (`pmax`) |
| digital minimum      | 8  | decimal text (`dmin`) |
| digital maximum      | 8  | decimal text (`dmax`) |
| prefiltering         | 80 | blank |
| samples per record   | 8  | `spr` |
| reserved             | 32 | blank |

So the block is laid out as: all `ns` labels (16 B each), then all `ns`
transducer fields (80 B each), … then all `ns` reserved fields (32 B each).
Total `= ns × 256` bytes.

---

## 5. Recording & patient text fields

**Recording id** (offset 88, 80 bytes), verified template:

```
Startdate 08-JUN-2026 X X X SRN=22251436648 MID=46 VID=3
```

- `DD-MMM-YYYY` uppercase month, local date of the session start.
- `SRN=` device serial number, `MID=` platform id, `VID=` variant id.
- The three `X` tokens are literal placeholders the device writes verbatim.

**Patient id** (offset 8, 80 bytes):

```
X X X X <H1> <H2>
```

- Literal prefix `X X X X ` then two uppercase 4-hex-digit tokens separated by a
  space. Within the header these tokens occupy bytes **16..24**
  (`<H1>` = `[16:20]`, space `[20]`, `<H2>` = `[21:25]`).
- `H1` and `H2` are derived checksums — see §6.

---

## 6. Patient-field tokens H1 / H2

Both tokens are fully reproducible; verified byte-exact on all 1925 corpus files.

### H2 — per-type constant

| Type | BRP | PLD | SA2 | CSL | EVE |
|------|-----|-----|-----|-----|-----|
| H2   | `D4BA` | `A81F` | `6EAD` | `2B58` | `2B58` |

### H1 — CRC of the fixed header

```
H1 = CRC16_CCITT_FALSE( header[0:256] ) XOR 0x3A78
```

computed with the 9-byte token slot `header[16:25]` set to **spaces (0x20)**
before hashing. The CRC parameters are the same as §8
(`poly=0x1021, init=0xFFFF`, no reflection, `xorout=0`). The XOR constant
`0x3A78` is identical for all five file types.

Procedure when writing a file:

1. Build the full fixed header with `H1`/`H2` left blank (spaces at `[16:25]`).
2. Compute `H1` over `header[0:256]` per the formula above.
3. Write the text `"<H1> <H2>"` (e.g. `"A673 D4BA"`) into `header[16:25]`.

> **Why a header CRC (RE note):** the token is deterministic from
> `(date, time, type)` yet not a CRC of the timestamp text. `CSL` and `EVE`
> headers are identical except `nrec`, and their `H1` differed only as a
> function of `nrec` — proving the hashed input is the **header**, not the data.
> Only the first 256 bytes are hashed (the signal-descriptor block is not),
> which is why `BRP` and `SA2` (both `ns=3`, same `nbytes/nrec/dur`) usually
> share `H1`, and `SA2 ⊕ PLD` is a constant `0x9647` (the `ns=3` vs `ns=9`
> header-byte delta).

---

## 7. Data records & sample scaling

Each data record holds, in signal order, the samples of every signal
concatenated as little-endian int16, then the `Crc16` sample last. For sampled
files the order is: data signals (in the order of §9), then `Crc16`. For
EVE/CSL: `EDF Annotations`, then `Crc16`.

**Physical ↔ digital** uses the standard EDF affine map from the per-signal
ranges:

```
gain   = (pmax - pmin) / (dmax - dmin)
offset = pmax - gain * dmax
digital = round( (physical - offset) / gain )      # clamped to [dmin, dmax]
physical = gain * digital + offset
```

The device uses **asymmetric, signal-specific** digital ranges; copy them
exactly (§9) so quantisation matches. Stream→EDF unit conversions
(confirmed against raw stream vs stored values):

| EDF signal | Source stream | Conversion |
|---|---|---|
| `Flow.40ms`  | `PatientFlow-100hz` (L/s)            | as-is, decimate 100→25 Hz |
| `Press.40ms` | `MaskPressure-100hz` (cmH2O)         | as-is, decimate 100→25 Hz |
| `MaskPress.2s` | `MaskPressure-TwoSecond` (cmH2O)   | as-is |
| `Press.2s`   | `InspiratoryPressure-TwoSecond` (cmH2O) | as-is |
| `EprPress.2s`| `ExpiratoryPressure-TwoSecond` (cmH2O)  | as-is |
| `Leak.2s`    | `Leak-50hz` (L/min)                  | **÷ 60** → store L/s |
| `RespRate.2s`| `RespiratoryRate-50hz` (bpm)         | as-is |
| `TidVol.2s`  | `TidalVolume-50hz` (L)               | as-is (**litres, not mL**) |
| `MinVent.2s` | `MinuteVentilation-50hz` (L/min)     | as-is |
| `Snore.2s`   | `SnoreIndex-50hz`                    | as-is |
| `FlowLim.2s` | `FlowLimitation-50hz`                | as-is |
| `Pulse.1s`   | `HeartRate`                          | `null` → digital `-1` |
| `SpO2.1s`    | `SpO2`                               | `null` → digital `-1` |

---

## 8. The Crc16 signal

Every sampled and annotation file ends with a signal labelled **`Crc16`**
(`spr=1`, ranges `-32768..32767`, no unit). For **each data record** it stores
a single int16 = the checksum of that record's preceding bytes.

- Algorithm: **CRC-16/CCITT-FALSE** — `poly=0x1021`, `init=0xFFFF`, no input or
  output reflection, `xorout=0x0000`.
- Input: all bytes of the record **except** the final 2-byte CRC sample (i.e.
  the concatenated little-endian int16 samples of all preceding signals).
- Stored as a normal little-endian int16 in the `Crc16` slot (values ≥ 0x8000
  are written as the signed equivalent).

Reference implementation and test vector:

```python
def crc16_ccitt(data: bytes) -> int:
    crc = 0xFFFF
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if (crc & 0x8000) else (crc << 1) & 0xFFFF
    return crc

# The no-event EVE/CSL record (62 annotation bytes) -> 0xD794, stored as bytes 94 D7.
```

---

## 9. Per-file signal specifications

Ranges are exact device values. `spr` = samples per 60 s record. Every file's
last signal is the `Crc16` described in §8 (shown for completeness).

### 9.1 BRP.edf — `reserved=EDF`, `dur=60.00`, 25 Hz

| # | label | dim | pmin | pmax | dmin | dmax | spr | gain |
|---|-------|-----|-----:|-----:|-----:|-----:|----:|------|
| 0 | `Flow.40ms`  | `L/s`   | -2 | 3  | -1000 | 1500 | 1500 | 0.002 |
| 1 | `Press.40ms` | `cmH2O` | 0  | 40 | 0     | 2000 | 1500 | 0.02 |
| 2 | `Crc16`      |         | -32768 | 32767 | -32768 | 32767 | 1 | — |

Flow is stored in **L/s** (firmware flow is already L/s). 1500 samples / 60 s = 25 Hz.

### 9.2 PLD.edf — `reserved=EDF`, `dur=60.00`, 0.5 Hz (`spr=30`)

| # | label | dim | pmin | pmax | dmin | dmax | spr | gain |
|---|-------|-----|-----:|-----:|-----:|-----:|----:|------|
| 0 | `MaskPress.2s` | `cmH2O` | 0 | 40 | 0 | 2000 | 30 | 0.02 |
| 1 | `Press.2s`     | `cmH2O` | 0 | 50 | 0 | 2500 | 30 | 0.02 |
| 2 | `EprPress.2s`  | `cmH2O` | 0 | 30 | 0 | 1500 | 30 | 0.02 |
| 3 | `Leak.2s`      | `L/s`   | 0 | 2  | 0 | 100  | 30 | 0.02 |
| 4 | `RespRate.2s`  | `bpm`   | 0 | 90 | 0 | 450  | 30 | 0.2 |
| 5 | `TidVol.2s`    | `L`     | 0 | 4  | 0 | 200  | 30 | 0.02 |
| 6 | `MinVent.2s`   | `L/min` | 0 | 30 | 0 | 240  | 30 | 0.125 |
| 7 | `Snore.2s`     |         | 0 | 5  | 0 | 250  | 30 | 0.02 |
| 8 | `FlowLim.2s`   |         | 0 | 1  | 0 | 100  | 30 | 0.01 |
| 9 | `Crc16`        |         | -32768 | 32767 | -32768 | 32767 | 1 | — |

The AS11 AutoSet writes exactly these **9** data signals, in this order. The
firmware var table defines additional candidates (`TgtVent`, `IERatio`, `Ti`)
that this device does **not** emit.

### 9.3 SA2.edf — `reserved=EDF`, `dur=60.00`, 1 Hz (`spr=60`)

| # | label | dim | pmin | pmax | dmin | dmax | spr | gain |
|---|-------|-----|-----:|-----:|-----:|-----:|----:|------|
| 0 | `Pulse.1s` | `bpm` | 0 | 300 | 0 | 300 | 60 | 1 |
| 1 | `SpO2.1s`  | `%`   | 0 | 100 | 0 | 100 | 60 | 1 |
| 2 | `Crc16`    |       | -32768 | 32767 | -32768 | 32767 | 1 | — |

**SA2 is always written, even with no oximeter** — in that case every
`Pulse.1s`/`SpO2.1s` sample is the raw digital sentinel **`-1` (`0xFFFF`)**.

### 9.4 EVE.edf / CSL.edf — `reserved=EDF+D`, `dur=0.00`

| # | label | dim | pmin | pmax | dmin | dmax | spr |
|---|-------|-----|-----:|-----:|-----:|-----:|----:|
| 0 | `EDF Annotations` |  | -32768 | 32767 | -32768 | 32767 | 31 |
| 1 | `Crc16`           |  | -32768 | 32767 | -32768 | 32767 | 1  |

`spr=31` for the annotation signal → 62 bytes of TAL text per record. `nrec`
grows with the number of annotation records (§10). For a session with no events,
`nrec=1` and `EVE` equals `CSL` byte-for-byte.

---

## 10. EVE / CSL annotations (EDF+ TAL)

Annotations use EDF+ **TAL** (Time-stamped Annotation List) encoding with two
control bytes: `\x14` (0x14, field/annotation separator) and `\x15` (0x15,
onset/duration separator). The annotation signal area is **62 bytes per record**
(`spr=31 × 2`), zero-padded (`\x00`) after the TAL text.

**One annotation record per data record.** Each record begins with a mandatory
timekeeping TAL with onset `+0`, followed by one content TAL.

- **Record 0** (always present — "recording starts"):

  ```
  +0\x14\x14\x00 +0\x150\x14Recording starts\x14
  ```
  (timekeeping TAL `+0\x14\x14\x00`, then onset 0 / duration 0 /
  `Recording starts`).

- **Record k ≥ 1** (one respiratory event each):

  ```
  +0\x14\x14\x00 +<onset>\x15<dur>\x14<label>\x14
  ```
  where `<onset>` and `<dur>` are integer seconds (onset measured from the file
  anchor, §12), and `<label>` is the event name.

So `nrec = 1 + (number of events)`. Each 62-byte record is followed by its
2-byte `Crc16` sample. Common event labels: `Obstructive Apnea`,
`Central Apnea`, `Hypopnea`, `Apnea`, `RERA`, `Flow Limitation`,
`Vibratory Snore`, `Large Leak`, `CSR`.

`CSL.edf` uses the identical structure; it carries clinical/settings-change
annotations and, for a minimal session, is byte-identical to `EVE.edf`.

---

## 11. STR.edf (daily summary)

Root-level `STR.edf` is a **daily cumulative** file (not per-session):

- `reserved=EDF`, `dur=86400`, `nrec=64` (a rolling window of days).
- **134 signals**: a `Date`/`MaskOn`/`MaskOff`/`MaskEvents` header, session
  `Duration`/`Mode`, the full settings block (`S.*`), environment/oximetry and
  ventilation **percentile** stats (`.50`/`.95`/`.Max`), the indices
  (`AHI`/`AI`/`HI`/`OAI`/`CAI`/`UAI`/`CSR`), and a trailing `Crc16`.
- The `recording` field uses the device **commission** date, not the session
  date.
- It is built from the device's session-summary data, independent of the live
  waveform streams.

The exact 134-field ordering varies by therapy-mode variant; full byte-exact
replication of `STR.edf` is documented as a follow-up. It is **not required**
to import per-session DATALOG files.

---

## 12. Record cadence & anchoring

Observed from a real session timeline (event-driven, not clock-driven):

- **Anchor (file start second):**
  - `BRP`/`PLD`/`SA2` start at the **MaskOn** event, floored to the second.
  - `EVE`/`CSL` start at the **TherapyStart** event, floored to the second
    (typically a few seconds earlier than MaskOn).
- **Sampled files use whole 60 s records.** `nrec = floor((MaskOff − anchor) / 60 s)`.
  The trailing partial minute is **dropped**, not zero-padded. (A ~79 s session
  yields `nrec=1`.)
- **EVE/CSL** have `dur=0.00`; their `nrec` is event-count-driven (§10), not
  time-driven.

---

## 13. Data sources (for live/offline generation)

To populate the sampled files you need the live therapy streams. The AS11 BLE
RPC exposes streams by name; the EDF mapping is:

| EDF signal | Stream `dataId` | Native rate |
|------------|-----------------|------------:|
| `Flow.40ms`   | `PatientFlow-100hz`             | 100 Hz |
| `Press.40ms`  | `MaskPressure-100hz`            | 100 Hz |
| `MaskPress.2s`| `MaskPressure-TwoSecond`        | 0.5 Hz |
| `Press.2s`    | `InspiratoryPressure-TwoSecond` | 0.5 Hz |
| `EprPress.2s` | `ExpiratoryPressure-TwoSecond`  | 0.5 Hz |
| `Leak.2s`     | `Leak-50hz`                     | 50 Hz |
| `RespRate.2s` | `RespiratoryRate-50hz`          | 50 Hz |
| `TidVol.2s`   | `TidalVolume-50hz`              | 50 Hz |
| `MinVent.2s`  | `MinuteVentilation-50hz`        | 50 Hz |
| `Snore.2s`    | `SnoreIndex-50hz`               | 50 Hz |
| `FlowLim.2s`  | `FlowLimitation-50hz`           | 50 Hz |
| `Pulse.1s`    | `HeartRate`                     | 1 Hz |
| `SpO2.1s`     | `SpO2`                          | 1 Hz |

Practical notes (confirmed on-device):

- The stream RPC accepts **one global `sampleIntervalMs`** and only **one active
  subscription** at a time; it value-holds slower signals up to that rate. The
  workable approach is a single subscription at the fastest required rate
  (40 ms / 25 Hz for BRP); slower signals are then downsampled losslessly.
- Respiratory events arrive as live event notifications and/or the
  `TherapyEvents-RespiratoryEvents` spool; either is sufficient for EVE/CSL.
- No known post-session spool archives the waveform at ≥ 25 Hz, so BRP/PLD/SA2
  must be captured live; only event/summary data is reliably available
  post-session.

---

## 14. End-to-end write procedure

To emit one byte-faithful sampled file (BRP/PLD/SA2):

1. Determine the **anchor** second (MaskOn) and `nrec = floor((MaskOff − anchor)/60)`.
2. For each signal (§9), resample the source stream to `spr` samples per 60 s
   record, apply the unit conversion (§7), and quantise to int16 with the
   signal's exact `pmin/pmax/dmin/dmax`.
3. Assemble the **fixed header** (§3) and **per-signal header** (§4), leaving the
   patient token slot blank; set `reserved`, `dur`, `nrec`, `ns`, `header bytes`,
   start date/time, and the recording field (§5).
4. Compute `H1` over the blank-slot header and write `"<H1> <H2>"` (§6).
5. For each record: concatenate all signals' int16 samples, compute the
   record `Crc16` (§8) over those bytes, and append it as the final int16.
6. Concatenate header block + all records; write to
   `DATALOG/<YYYYMMDD>/<YYYYMMDD_HHMMSS>_TYPE.edf`.

For EVE/CSL: use `reserved=EDF+D`, `dur=0.00`, the `EDF Annotations` + `Crc16`
signal pair, anchor to TherapyStart, build record 0 as `Recording starts` and
one record per event (§10), each padded to 62 bytes and followed by its `Crc16`.

The whole procedure is verifiable: a correct writer reproduces the device's
files **byte-for-byte** in the header (including the patient tokens) and for all
non-waveform data; only the high-rate BRP/PLD waveform samples differ, bounded
by live-capture fidelity.

---

## 15. Reference implementation

Two working Python scripts in the repository implement the capture and write
pipeline described above. They are self-contained, use only the standard
library + ``bleak`` (for BLE), and can be run out-of-the-box against a paired
AirSense 11:

| Script | Purpose | Input | Output |
|--------|---------|-------|--------|
| `python/edf_capture_data.py` | Live BLE capture | AS11 BLE address | `RAW/<id>/` folder (JSONL + JSON + spools) |
| `python/edf_write.py` | Offline EDF builder | `RAW/<id>/` folder | `DATALOG/<day>/*.edf` + `Identification.json` |

Both scripts are the upstream-blessed versions (no proxy shim).  They implement
every algorithm and constant documented in this spec:

- **edf_capture_data.py** — sets up the `BleTransport`, subscribes to the 13
  required live streams at 40 ms (25 Hz), records all notifications to
  `notifications.jsonl`, and pulls post-session spools (`Summary`,
  `TherapyEvents-RespiratoryEvents`).
- **edf_write.py** — parses the RAW folder, builds `Capture` sessions from
  `TherapyStart`/`TherapyStop`/`MaskOn`/`MaskOff` events, and emits each of
  the five file types with the exact header layout, per-signal scaling, 60 s
  record cadence, EDF+ TAL annotations, per-record `Crc16`, and patient-field
  tokens H1/H2 documented in §6–§14.

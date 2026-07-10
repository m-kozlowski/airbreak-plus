# Config Variables

## Table of contents

- [globals[] array](#globals-array)
  - [Variable dispatch](#variable-dispatch)
- [g[0] -- device identity](#g0----device-identity)
- [g[1] -- timer scale table](#g1----timer-scale-table)
- [g[2] -- localized string table](#g2----localized-string-table)
- [g[3] -- identity/metadata descriptors](#g3----identitymetadata-variable-descriptors)
- [g[4] -- numeric variable descriptors](#g4----numeric-variable-descriptors)
- [g[5] -- alternate numeric labels](#g5----alternate-numeric-labels)
- [g[6] -- config/status variable descriptors](#g6----configstatus-variable-descriptors)
- [g[7] -- config byte-slice pool](#g7----config-byte-slice-pool)
- [g[8] -- enum/option variable descriptors](#g8----enumoption-variable-descriptors)
- [g[9] -- ANV apnea-event record](#g9----anv-apnea-event-record)
- [g[10] -- hardware-interface vectors](#g10----hardware-interface-vectors)
- [g[11] -- signal headers (BRP, PLD, SAD)](#g11----signal-headers-brp-pld-sad)
- [g[12] -- event channel headers](#g12----event-channel-headers)
- [g[13] -- STR channel descriptor](#g13----str-channel-descriptor)
- [g[14] -- NPD signal group](#g14----npd-signal-group)
- [g[15] -- aperiodic signal groups](#g15----aperiodic-signal-groups)
- [g[16] -- EEPROM-backed variable groups](#g16----eeprom-backed-variable-groups)
- [g[17] and g[18] -- date/time descriptors](#g17-and-g18----datetime-descriptors)
- [g[19] -- EEPROM stream table](#g19----eeprom-stream-table)
- [g[20] -- PDL persistent-state list](#g20----pdl-persistent-state-list)
- [g[21] -- derived-variable rules](#g21----derived-variable-rules)
- [g[22] -- identity TGT export list](#g22----identity-tgt-export-list)
- [g[23] -- UART name index](#g23----uart-name-index)
- [g[24] -- mode membership table](#g24----mode-membership-table)
- [g[26] -- live stream records](#g26----live-stream-records)
- [g[27] -- APN/CSN/BRH records](#g27----apncsnbrh-records)
- [g[28] -- OXH (oximetry header)](#g28----oxh-oximetry-header)
- [Flags bitmask](#flags-bitmask)
- [RAM shadow](#ram-shadow)
- [Dependency chain](#dependency-chain)

---

## globals[] array

`CCX+0x108` holds a 30-entry ABI vector, `g[0]` through `g[29]`. Most entries
are CCX pointers, `g[25]` is a record count, and `g[29]` is the `0xFFFFFFFF`
end marker.

### Variable dispatch

Variable IDs are implicitly encoded by table position: `var_id = id_base + record_index`.
These IDs are the numeric references stored inside the firmware image. For
cross-variant work, the 3-letter UART names in g[23] are the stable lookup key:
some IDs move across older SX567 catalog/build variants.

| globals | stride | id_base | id_range | content |
|---------|--------|---------|----------|---------|
| [3] | 10 | 0x000 | 0x000-0x01D | identity, metadata |
| [4] | 0x1C | 0x01E | 0x01E-0x1FC | numeric variables (pressure, therapy params) |
| [6] | 0x18 | 0x1FD | 0x1FD-0x20C | config/status |
| [8] | 0x14 | 0x20D | 0x20D-0x2B1 | enum/option variables |
| [9] | 0x18 | 0x2B2 | 0x2B2 | timer (single entry) |
| [10] | 0x24 | 0x2B3 | 0x2B3-0x2B5 | hardware-interface vectors |

Dispatch function at CDX 0x0806f3cc:
```
var_id < 0x1E           -> g[3]
0x1E  <= var_id < 0x1FD -> g[4]
0x1FD <= var_id < 0x20D -> g[6]
0x20D <= var_id < 0x2B2 -> g[8]
0x2B2                   -> g[9]
```

`g[10]` entries use a separate structured-variable handler path. On SX567
040x they map to `PCC`, `HPI`, and `HUI`. `g[17]` and `g[18]` continue the
object ID space with `DAC` and `TIC`. Named channel, group, and stream objects
continue after them; they are not handled by the scalar dispatcher above.

SX567 040x assigns the remaining object IDs as follows:

| globals | id range | objects |
|---------|----------|---------|
| [17] | 0x2B6 | DAC |
| [18] | 0x2B7 | TIC |
| [28] | 0x2B8 | OXH |
| [26] | 0x2B9-0x2C0 | TCE, PBT, PMD, FTX, RAW, DRT, CPU, SSK |
| [27] | 0x2C1-0x2C3 | APN, CSN, BRH |
| [11] | 0x2C4-0x2C6 | BRP, PLD, SAD |
| [12] | 0x2C7-0x2C9 | CSL, AEV, EVE |
| [13] | 0x2CA | STR |
| [19] | 0x2CB-0x2D4 | ABR, TXC, TXH, TXE, TXW, TRR, DLL, ERR, ELI, ZRL |
| [14] | 0x2D5 | NPD |
| [15] | 0x2D6 | NPA |
| [16] | 0x2D7-0x2E6 | AGL, CGL, RGL, DGL, IGL, EGL, QXH, QXJ, VGL, XGL, BGL, NGL, UGL, MGL, PGL, SGL |
| [20] | 0x2E7 | PDL |

These IDs continue the same UART-name namespace but the number and placement
of objects can change by platform. SX584 adds `MSD` to g[26] and `ALA` to
g[15], shifting the later object IDs.

---

## g[0] -- device identity

```
+0x00: u32[7]  CID components
+0x1C: u32     front-panel profile
+0x20: char[]  product code (e.g. "37101")
+0x30: char[]  product name (e.g. "AirSense 10 AutoSet")
```

The seven CID words form the `CID`/`COMMS_ID` reported by the serial protocol.
They are stored in a different order from the displayed identifier:

```
CX%03u-%03u-%03u-%03u-%03u-%03u-%03u
  +04   +00   +0C   +08   +14   +10   +18
```

| CID field | g[0] offset | Meaning |
|-----------|-------------|---------|
| 1 | +0x04 | Metadata ID. Matches the default value of `MID`. |
| 2 | +0x00 | Communication metadata version. This changes with the metadata generation, for example 24, 25, and 26 across known SX567 releases. |
| 3 | +0x0C | Region ID. Matches the default value of `RID`. |
| 4 | +0x08 | Variant ID. Matches the default value of `VID` and selects the corresponding `MetaData_M<mid>_V<vid>` definition. |
| 5 | +0x14 | Communication metadata revision component 1. |
| 6 | +0x10 | Communication metadata revision component 2. |
| 7 | +0x18 | Communication metadata revision component 3. |

Example (SX567 0402, AirSense 10 AutoSet product code 37101):

```text
stored_words=26,36,26,15,101,102,101  front_panel_profile=0
product_code="37101"  product="AirSense 10 AutoSet"
CID=CX036-026-015-026-102-101-101
```

The first four components identify metadata family 36, metadata version 26,
region 15, and device variant 26. The final three values form the communication
metadata compatibility/revision tuple carried by `COMMS_ID`.

The low byte of the front-panel profile at `+0x1C` selects the installed input
layout and its matching boot logo:

| Value | Button inputs | Rotary encoder | Boot logo |
|-------|---------------|----------------|-----------|
| 0 | 3-input map | initialized | default |
| 1 | 5-input map | not initialized | alternate wave logo |

The key scanner uses the selected button map. The rotary-input controller
configures its GPIO and interrupt lines only for profile `0`. The splash-screen
renderer uses the same value to select the logo bitmap. Values other than `0`
and `1` stop front-panel initialization. Known AirSense, AirCurve, and Lumis
images use profile `0`.

---

## g[1] -- timer scale table

14 timer profiles x 16 bytes. A profile combines a scheduler dispatch level
with the nominal duration represented by a channel or record.

| Offset | Size | Field |
|--------|------|-------|
| +0x00 | 1 | scheduler_level |
| +0x01 | 1 | pad |
| +0x02 | 2 | base_ticks_10ms |
| +0x04 | 4 | nominal_multiplier |
| +0x08 | 8 | nominal_period_seconds (f64) |

`scheduler_level` selects one of the scheduler's 11 dispatch queues. Periodic
recording objects register themselves in `queue[scheduler_level]`; the timer
manager invokes that queue when the corresponding cadence event occurs.

| Level | Base cadence represented by the table |
|-------|---------------------------------------|
| 0 | 10 ms |
| 1 | 20 ms |
| 2 | 40 ms |
| 3 | 100 ms |
| 4 | 200 ms |
| 5 | 1 s |
| 6 | 60 s |
| 10 | special/event-driven queue |

Several profiles share one scheduler level. For example, the 1 s, 2 s, 4 s,
and 20 s profiles all use level 5, while the 1 min, 5 min, and 20 min profiles
use level 6.

`base_ticks_10ms` is the base cadence expressed in 10 ms ticks. It remains 100
for every level-5 profile and 6000 for every level-6 profile. Level 10 uses zero
for the special/event-driven profiles.

`nominal_multiplier` identifies a cadence variant within a shared scheduler
level. Level-5 profiles use values 1, 2, 4, and 20. Level-6 profiles use values
1, 5, and 30. The complete logical duration remains explicitly stored in
`nominal_period_seconds`; the 20-minute profile therefore carries level 6,
6000 base ticks, multiplier 30, and a 1200-second duration.

`nominal_period_seconds` is the logical duration represented by the profile.
The EDF recorder divides it by the largest samples-per-record count to obtain
the interval represented by individual samples. Stored-record and event paths
use `scheduler_level` to select their dispatch queue.

| Index | Level | Base ticks | Mult | Period |
|-------|-------|------------|------|--------|
| 0 | 10 | 0 | 1 | 0 s |
| 1 | 0 | 1 | 1 | 10 ms |
| 2 | 1 | 2 | 1 | 20 ms |
| 3 | 2 | 4 | 1 | 40 ms |
| 4 | 3 | 10 | 1 | 100 ms |
| 5 | 4 | 20 | 1 | 200 ms |
| 6 | 5 | 100 | 1 | 1 s |
| 7 | 5 | 100 | 2 | 2 s |
| 8 | 5 | 100 | 4 | 4 s |
| 9 | 5 | 100 | 20 | 20 s |
| 10 | 6 | 6000 | 1 | 1 min |
| 11 | 6 | 6000 | 5 | 5 min |
| 12 | 6 | 6000 | 30 | 20 min |
| 13 | 10 | 0 | 1 | 24 h |

---

## g[2] -- localized string table

Array of 8-byte records, one per string ID:

| Offset | Size | Field |
|--------|------|-------|
| +0x00 | 2 | max string length across all locales |
| +0x02 | 2 | pad |
| +0x04 | 4 | pointer to locale index array |

Lookup: `string_lookup(str_id, locale)`:
```
locale_arr = u32(g[2] + str_id*8 + 4)
raw_index  = u16(locale_arr + locale*2)
str_ptr    = u32(raw_table + raw_index*4)
```

The compact `locale` slot is derived from the firmware language IDs enabled in
the `LAN` descriptor mask. It is the number of enabled language bits below the
selected language ID. This maps sparse ResMed language IDs onto the compact
locale arrays stored by g[2].

Example (SX567 0402, string ID `0x000C`):

```text
max_length=5  locale_indexes=84,85,86,87,88,89,90
EN="Mode"  DE="Modus"  PL="Tryb"
```

---

## g[3] -- identity/metadata variable descriptors

**Record stride:** 10 bytes, **Entry count:** 30, **var_id range:** 0x000-0x01D

Contains string-type variables (BID, SID, CID, PNA, SRN, etc.).

| Offset | Size | Field |
|--------|------|-------|
| +0x00 | 2 | flags |
| +0x02 | 1 | callback_id |
| +0x03 | 1 | -- |
| +0x04 | 2 | dependency_head_g4_idx (0x7FFF = none) |
| +0x06 | 2 | format_str_id (0xDE = none) |
| +0x08 | 2 | max_length |

Example (SX567 0402):

```text
SRN: flags=ACT|VIS|EDT  callback=0  dependency=g[4][0x014E]
     format=none  max_length=18
```

---

## g[4] -- numeric variable descriptors

**Record stride:** 0x1C (28 bytes), **Entry count:** 0x1DF (479)

### Record layout

| Offset | Size | Field | Description |
|--------|------|-------|-------------|
| +0x00 | 2 | flags | Status bitmask (see below) |
| +0x02 | 1 | callback_id | Post-change callback index. 0 = none |
| +0x03 | 1 | -- | |
| +0x04 | 2 | next_dependent_g4_idx | Linked-list pointer into g[4] for dependency chain. 0x7FFF = end |
| +0x06 | 2 | name_str_id | Localized display name via g[2] |
| +0x08 | 4 | default_value | Default value, copied to RAM on init |
| +0x0C | 4 | max_value | Upper numeric bound |
| +0x10 | 4 | min_value | Lower numeric bound |
| +0x14 | 1 | decimal_places | Display precision |
| +0x15 | 1 | -- | |
| +0x16 | 2 | scale_factor | Conversion factor for string<->value. Positive: divide. Negative: multiply by abs |
| +0x18 | 2 | step_size | Increment and quantization step when RAW is clear |
| +0x1A | 2 | units_str_id | Units label string via g[2] |

### Runtime handler selection

All g[4] entries use the descriptor layout above. On SX567 040x, the g[4] index
selects one of these implementations when firmware creates a runtime handler:

| Index range | var_id range | Runtime handler |
|-------------|--------------|-----------------|
| 0x000-0x1B3 | 0x01E-0x1D1 | Standard numeric value; bounds come directly from the descriptor |
| 0x1B4-0x1D3 | 0x1D2-0x1F1 | Numeric value with mutable runtime minimum and maximum; primarily therapy settings |
| 0x1D4-0x1D8 | 0x1F2-0x1F6 | Calendar date: `RDF`, `RDM`, `RDH`, `RDW`, `UDT` |
| 0x1D9-0x1DC | 0x1F7-0x1FA | Packed `0xHHMMSS` time: `ZIC`, `ZIT`, `RTI`, `UTI` |
| 0x1DD-0x1DE | 0x1FB-0x1FC | Indexed value proxy used by `AER` and `ELV` |

The mutable bounds table covers indexes `0x1B4-0x1DC`. Firmware initializes
each runtime minimum and maximum from the corresponding descriptor, then
constraint handlers can update them while preserving the descriptor's absolute
range. The date and time handlers use the same mutable bounds and add their
type-specific parsing and formatting.

Example (SX567 0402):

```text
MXS: flags=VIS|EDT  callback=0  next=g[4][0x0136]  name="Max PS"
     default=15.0  range=5.0..20.0  step=0.2  units=cmH2O
```

### g[5] -- alternate numeric labels

10 entries x 4 bytes. Each record is a pair of localized string IDs used by
g[4] indexes `0x1D3-0x1DC`. `alternate_str_a` replaces numeric formatting when
the current value is at the runtime minimum; `alternate_str_b` does the same at
the runtime maximum. An empty string ID leaves the boundary value numeric.

| Offset | Size | Field |
|--------|------|-------|
| +0x00 | 2 | alternate_str_a |
| +0x02 | 2 | alternate_str_b |

Example (SX567 0402):

```text
g[5][0] -> g[4][0x1D3]: alternate_str_a=0x014F "Min"
                         alternate_str_b=0x00DE none
```

---

## g[6] -- config/status variable descriptors

**Record stride:** 0x18 (24 bytes), **Entry count:** 16, **var_id range:** 0x1FD-0x20C

| Offset | Size | Field |
|--------|------|-------|
| +0x00 | 2 | flags |
| +0x02 | 1 | callback_id |
| +0x03 | 1 | -- |
| +0x04 | 2 | dependency_head_g4_idx |
| +0x06 | 2 | name_str_id |
| +0x08 | 4 | default_value |
| +0x0C | 4 | allowed_bits |
| +0x10 | 1 | item_count |
| +0x11 | 1 | display parameter |
| +0x12 | 2 | g[7] slice offset |
| +0x14 | 2 | base_string_id |
| +0x16 | 2 | -- |

Example (SX567 0402):

```text
LNC: flags=ACT|VIS|EDT  default=0x00048107  allowed=0x0004C107
     item_count=21  g[7]_offset=0x0041
```

### g[7] -- config byte-slice pool

Packed byte array referenced by g[6]. For each g[6] record, the slice starts
at `g[7] + slice_offset` and contains `item_count` bytes. The slices are packed
sequentially and contain small ascending values. The checked firmware images
allocate 132 bytes; the final one or two bytes are padding after the referenced
slices.

The pool supplies the packed per-item byte lists associated with g[6]
descriptors.

Example (SX567 0402):

```text
LNC slice: offset=0x0041  count=21  values=0,1,2,3,4,5,6,7,8,9,
           10,11,12,13,14,15,16,17,18,19,20
```

---

## g[8] -- enum/option variable descriptors

**Record stride:** 0x14 (20 bytes), **Entry count:** 0xA5 (165)

### Record layout

| Offset | Size | Field | Description |
|--------|------|-------|-------------|
| +0x00 | 2 | flags | Status bitmask (see below) |
| +0x02 | 1 | callback_id | Post-change callback index. 0 = none |
| +0x03 | 1 | -- | |
| +0x04 | 2 | dependency_head_g4_idx | Index into g[4] for dependency propagation. 0x7FFF = none |
| +0x06 | 2 | name_str_id | Localized display name via g[2] |
| +0x08 | 1 | default_value | Default state byte |
| +0x09 | 1 | num_options | Number of valid options |
| +0x0A | 2 | -- | |
| +0x0C | 4 | permission_bitmask | Allowed option indexes. Bit `n` enables option `n` |
| +0x10 | 2 | base_string_id | Base string ID for option labels. `base + option_idx` = label. 0xDE = none |
| +0x12 | 2 | -- | |

Therapy-mode visibility is controlled by g[24], not this mask.

Example (SX567 0402):

```text
MOP: flags=ACT|VIS|EDT  callback=11  dependency=g[4][0x0173]
     default=1  options=12  allowed_options=0x00000003
     name="Mode"  labels=CPAP,AutoSet,APAP,S,ST,T,VAuto,ASV,
                         ASVAuto,iVAPS,PAC,AutoSet for Her
```

---

## g[9] -- ANV apnea-event record

One 24-byte descriptor for `ANV`, an apnea-event record composed from `APT`,
`DUR`, and `AET`. Its runtime value is an 8-byte tuple:

```text
u32 event_time_seconds_of_day
u16 duration_deciseconds
u16 event_type
```

When `APT` changes, firmware captures the current time of day, converts `DUR`
from seconds to deciseconds, copies the `AET` event type, and updates `ANV`.
The handler accepts times below 86400 seconds, durations within the descriptor
range, and event types enabled by the descriptor mask.

`ANV` propagates through `ANT` and is the payload of the
`NIGHT_PROFILE_APNEA` (`NPA`) group. `NIGHT_PROFILE_PERIODIC` (`NPD`) is the
separate periodic night-profile signal group.

| Offset | Size | Field |
|--------|------|-------|
| +0x00 | 2 | flags |
| +0x02 | 2 | -- |
| +0x04 | 2 | dependency_head_g4_idx |
| +0x06 | 2 | name_str_id |
| +0x08 | 1 | default event type |
| +0x09 | 1 | event type count |
| +0x0A | 2 | -- |
| +0x0C | 4 | allowed event type mask |
| +0x10 | 2 | event type base string ID |
| +0x12 | 2 | minimum duration in deciseconds |
| +0x14 | 2 | maximum duration in deciseconds |
| +0x16 | 2 | duration units per second |

Example (SX567 0402):

```text
ANV: flags=ACT|VIS|EDT  dependency=g[4][0x0141]:ANT
     default_type=0  event_types=6  allowed_types=0x0000001F
     duration=0..1200 deciseconds  units_per_second=10
```

---

## g[10] -- hardware-interface vectors

Three 36-byte records. Their first 28 bytes use the g[4] numeric layout. The
tail selects a runtime vector and its element count. On SX567 040x the records
map to `PCC`, `HPI`, and `HUI` through a separate structured-variable handler.

These vectors bridge reports from the humidifier and heated-tube controllers
into the common variable system. Each UART name represents several numeric
elements held in a shared RAM array. The handler copies the complete vector
between that array and an indexed working buffer while holding the variable
lock. The values are runtime hardware data, not menu settings or
storage-backed configuration.

| Variable | Elements | Firmware use |
|----------|----------|--------------|
| `PCC` | 5 x u16 | Received through the humidifier-interface message path. Climate-control setup scales elements 0, 1, 3, and 4 to floating-point parameters; element 2 is not consumed there. |
| `HPI` | 3 binary values | Received through the heated-tube interface path, which also handles tube temperature and connection state. The values are published through the variable update and notification path. |
| `HUI` | 3 binary values | Received through the humidifier interface path and read by the climate-control subsystem as three inputs. |

| Offset | Size | Field |
|--------|------|-------|
| +0x00 | 0x1C | g[4]-compatible numeric descriptor |
| +0x1C | 4 | base element index in the shared runtime array |
| +0x20 | 1 | element count |
| +0x21 | 3 | -- |

Example (SX567 0402):

```text
PCC: flags=ACT|VIS|EDT  element_range=0..1000  step=1
     runtime_elements=0..4  element_count=5
```

---

## g[11] -- signal headers (BRP, PLD, SAD)

3 consecutive 32-byte headers defining periodic EDF signal channels.
Each channel stores a var_id array, samples-per-record array, and optional signal
name string pointer array.

| Offset | Size | Field |
|--------|------|-------|
| +0x08 | 1 | field_count |
| +0x09 | 3 | name (e.g. "BRP") |
| +0x10 | 4 | var_id array pointer |
| +0x14 | 4 | samples-per-record array pointer |
| +0x18 | 4 | g[1] timer index |
| +0x1C | 4 | name string array pointer |

Example (SX567 0402):

```text
BRP: field_count=3  timer=g[1][10]
     RFL x1500, MKP x1500, DCR x1
```

---

## g[12] -- event channel headers

Three headers defining the `CSL`, `AEV`, and `EVE` EDF event channels. SX567
uses 24-byte records. SX584 uses 28-byte records with one additional u32 tail
field.

Each header:

| Offset | Size | Field |
|--------|------|-------|
| +0x08 | 1 | field count |
| +0x09 | 3 | channel name |
| +0x10 | 4 | var_id array pointer |
| +0x18 | 4 | SX584-only tail field |

Example (SX567 0402):

```text
EVE: field_count=4  fields=ETI,DUR,AET,DCR
```

---

## g[13] -- STR channel descriptor

The primary header is 36 bytes. Its payload is stored after the g[12] headers
and consists of 10-byte field records, a var-ID array, a samples-per-record
array, and a field-name pointer array. Each payload array is aligned separately.

| Offset | Size | Field |
|--------|------|-------|
| +0x00 | 4 | config |
| +0x04 | 4 | config |
| +0x08 | 1 | field_record_count |
| +0x09 | 3 | "STR" |
| +0x0C | 4 | reserved |
| +0x10 | 4 | var_id array pointer |
| +0x14 | 4 | samples-per-record array pointer |
| +0x18 | 4 | g[1] timer index |
| +0x1C | 4 | field-name pointer array |
| +0x20 | 4 | 10-byte field-record array pointer |

Example (SX567 0402):

```text
STR: field_count=80  timer=g[1][13]
     first_fields=LSD,ONT,OFT,MSE,OND,THD,PHM,MOP
```

---

## g[14] -- NPD signal group

`NPD` is the `NIGHT_PROFILE_PERIODIC` signal group. Its 28-byte descriptor
selects the periodic pressure, leak, ventilation, respiratory-rate, and SpO2
signals recorded in the night profile.

| Offset | Size | Field |
|--------|------|-------|
| +0x00 | 4 | flags/id |
| +0x04 | 4 | param |
| +0x08 | 4 | threshold |
| +0x0C | 4 | session config |
| +0x10 | 1 | signal_count |
| +0x11 | 3 | "NPD" |
| +0x14 | 4 | reserved |
| +0x18 | 4 | var_id array pointer |

Example (SX567 0402):

```text
NPD (NIGHT_PROFILE_PERIODIC): signal_count=7
    signals=LRP,LRE,LKP,MVT,ATI,RR1,SAV
```

---

## g[15] -- aperiodic signal groups

24-byte signal-group records. `NPA` is `NIGHT_PROFILE_APNEA`; its single
signal is the `ANV` apnea-event tuple. SX584 Lumis also contains `ALA`,
`ALARM_LOG_APERIODIC`. Each record carries its own count, var-ID array pointer,
and linked notification variable.

| Offset | Size | Field |
|--------|------|-------|
| +0x00 | 4 | flags/id |
| +0x04 | 4 | channel parameters |
| +0x08 | 1 | signal count |
| +0x09 | 3 | group name |
| +0x0C | 4 | reserved |
| +0x10 | 4 | var_id array pointer |
| +0x14 | 2 | linked var_id |

Example (SX567 0402):

```text
NPA (NIGHT_PROFILE_APNEA): signal_count=1
    linked=0x015F:ANT  signals=0x02B2:ANV

SX584 additional group:

ALA (ALARM_LOG_APERIODIC): signal_count=1
    linked=0x0172:ALT  signals=0x02E6:ANE
```

---

## g[16] -- EEPROM-backed variable groups

16 entries x 16 bytes. Each entry defines one persistent variable group stored
in the EEPROM FAT filesystem as `SETTINGS/<group>.set`, for example
`SETTINGS/BGL.set`. The member array defines the variables and serialization
order used when the group is loaded and saved.

| Offset | Size | Field |
|--------|------|-------|
| +0x00 | 4 | group name (3 char + null) |
| +0x04 | 2 | g[4] group-tracker index |
| +0x06 | 2 | param |
| +0x08 | 4 | member var_id array pointer |
| +0x0C | 4 | member count |

The g[4] group tracker receives dependency update tokens and marks the group for
writing after a member changes.

Example (SX567 0402):

```text
BGL -> SETTINGS/BGL.set
     tracker=g[4][0x014E]  member_count=12
     members=PSH,PZH,FLG,FLZ,SNZ,SNB,PCB,PCD,SRN,PNA,CCP,CCS
```

---

## g[17] and g[18] -- date/time descriptors

Each root points to one 8-byte descriptor. `g[17]` maps to `DAC` (date) and
`g[18]` maps to `TIC` (time). Alignment bytes and the stream descriptor arrays
which follow `g[18]` are not additional g[17]/g[18] records.

Example (SX567 0402):

```text
g[17]: 0x02B6:DAC  flags=ACT|VIS|EDT  callback=0  dependency=none
g[18]: 0x02B7:TIC  flags=ACT|VIS|EDT  callback=0  dependency=none
```

---

## g[19] -- EEPROM stream table

10 entries x 28 bytes. Defines the stored record streams `ABR`, `TXC`, `TXH`,
`TXE`, `TXW`, `TRR`, `DLL`, `ERR`, `ELI`, and `ZRL`.

| Stream | Purpose | Stream-specific field |
|--------|---------|-----------------------|
| `ABR` | Abort error (`ABORT_ERR`) | `FAT` |
| `TXC` | Climate-control error log (`CLIMATE_CONTROL_ERR_LOG`) | `SYC` |
| `TXH` | Heated-tube error log (`HEATED_TUBE_ERROR_LOG`) | `SYH` |
| `TXE` | Transducer error log (`TRANSDR_ERR`) | `SYS` |
| `TXW` | Transducer error log 2 (`TRANSDR_ERR_TWO`) | `SYT` |
| `TRR` | Transient error log (`TRANSIENT_ERR_LOG`) | `TYS` (`TRANSIENT_SYSTEM_ERROR`) |
| `DLL` | `DLA` records | `DLA` |
| `ERR` | Application-error origin records | `AER` (`APP_ERR_ORI`) |
| `ELI` | `ELV` records | `ELV` |
| `ZRL` | Saved system-error records | `ZSE` (`SAVED_SYSTEM_ERROR`) |

At startup the firmware creates one runtime stream object for each entry. The
object watches its trigger variable, serializes the configured field list, and
stores bounded history records. The runtime record width is calculated from
the variable handlers for the listed fields; it is not stored directly in this
table.

| Offset | Size | Field |
|--------|------|-------|
| +0x00 | 4 | name (3 char + null) |
| +0x04 | 4 | field_var_ids | Pointer to the u16 fields serialized into each record |
| +0x08 | 1 | field_count | Number of entries in `field_var_ids` |
| +0x09 | 1 | reserved | Zero in checked firmware |
| +0x0A | 2 | capacity | Maximum number of stored records |
| +0x0C | 2 | trigger_var_id | Variable watched to decide when a new record is needed |
| +0x0E | 1 | timer_index | Index into g[1] used to configure the stream scheduler |
| +0x0F | 1 | flags | Zero in checked firmware |
| +0x10 | 2 | secondary_var_id | Secondary copy of `trigger_var_id` in stock definitions |
| +0x12 | 2 | secondary_param | Reserved; zero in stock definitions |
| +0x14 | 4 | trigger_idle_value | Trigger value which does not generate a new record; zero in stock definitions |
| +0x18 | 2 | state_g4_idx | Index of the g[4] stream state/cursor variable |
| +0x1A | 2 | -- | Alignment |

Stock SX567 entries have four record fields: `UDT`, `UTT`, `NOC`, and the
stream-specific source variable. The ten field arrays are physically stored
after the g[18] descriptor but belong to the g[19] stream definitions.

`UDT` and `UTT` provide the record date and minute-of-day. The firmware reads
the current date/time when constructing special records. `NOC` is the common
third field. The fourth field is also the trigger variable in all checked
definitions.

The g[4] state variables are `ZEV`, `ZEC`, `HET`, `ZET`, `ZEH`, `TEE`, `ZVT`,
`ZEU`, `ZTU`, and `ZEW`. They have 32-bit counter-like ranges and are used by
the stream manager to compare and track backend state. The table stores their
g[4] indexes, not their var IDs.

Example (SX567 0402):

```text
ABR: capacity=50  timer=g[1][3]  trigger=FAT  idle=0
     state=ZEV  fields=UDT,UTT,NOC,FAT
```

---

## g[20] -- PDL persistent-state list

`PDL` is a persistent device-state unit. Its member list contains 34 runtime
state variables such as usage dates, run meters, operating-hour counters,
service state, and the last data-erasure date. These values are maintained
across sessions but are separate from the user and therapy settings grouped
under g[16].

Firmware creates a dedicated PDL runtime object and schedules its processing
through the system work queue. Operations on the complete unit iterate the
member list and dispatch the same variable-handler operation for each member.

| Offset | Size | Field |
|--------|------|-------|
| +0x00 | 4 | name (`"PDL\0"`) |
| +0x04 | 4 | var_id array pointer |
| +0x08 | 4 | var_id count |

Example (SX567 0402):

```text
PDL: 34 members
FBD, FTD, DUS, ZD1, DUF, ZD2, HOU, MHR, MHU, MHS, ... ZSE, ZFE, CED
```

---

## g[21] -- derived-variable rules

Count and pointer for the rule records stored after the PDL header. Each rule
connects a destination variable to a source variable. The rule type and
optional parameters select the calculation applied when updating the
destination.

Firmware creates one runtime processor for each applicable rule. These
processors maintain derived statistics and status values from their source
variables. For example, the `MQD <- LK7` rule derives the mask-fit result from
the leak value. Firmware variants carry different rule sets according to the
statistics required by their supported therapy modes.

| Offset | Size | Field |
|--------|------|-------|
| +0x00 | 4 | rule count |
| +0x04 | 4 | rule record pointer |

Rule record:

| Offset | Size | Field |
|--------|------|-------|
| +0x00 | 2 | destination/stat var_id |
| +0x02 | 2 | source/input var_id |
| +0x04 | 4 | flags/type (`type = (flags >> 8) & 0xff`) |
| +0x08 | 4 | param_a (`0xffffffff` = unused) |
| +0x0C | 4 | param_b (`0xffffffff` = unused) |

Stock variants carry different rule counts.

Example (SX567 0402):

```text
rule_count=13  rule_pointer=PDL+0x0C
rule[10]: destination=0x0257:MQD  source=0x0092:LK7
          type=3  param_a=unused  param_b=unused
```

---

## g[22] -- identity TGT export list

The root contains 16 u16 var IDs:

`BID, FGT, MID, PCB, PCD, PNA, SID, SRN, VID, RID, CID, PVD, PVR, RIR, VIR, IMF`

Firmware serializes these variables in list order through its TGT text encoder.
The resulting block carries bootloader, hardware, product, software, serial,
variant, and module identity information.

Immediately after the 32-byte list begins a contiguous pool of 4-byte UART-name
records: `{u8 char2, u8 char3, u16 var_id}`. This adjacent pool is pointer-owned
by g[23]; it is not part of the g[22] identity list.

Example (SX567 0402):

```text
identity_ids[10]=0x0007:CID
```

---

## g[23] -- UART name index

26 entries x 8 bytes (one per letter A-Z):

| Offset | Size | Field |
|--------|------|-------|
| +0x00 | 4 | subtable pointer |
| +0x04 | 4 | entry count |

Each subtable entry (4 bytes): `{u8 char2, u8 char3, u16 var_id}`.

The bucket index supplies the first character, while each record stores the
remaining two characters and var_id. The non-empty buckets partition the pool
beginning at `g[22]+0x20`; their counts sum to the complete UART-name entry
count. Firmware uses this index for both `name -> var_id` and `var_id -> name`
lookups.

Example (SX567 0402):

```text
bucket 'M': {'O','P',0x020D} -> MOP = 0x020D
```

---

## g[24] -- mode membership table

Setting-to-mode membership table. g[25] holds the entry count.

Each entry is `2 + MOP.num_options` bytes:

| Offset | Size | Field |
|--------|------|-------|
| +0x00 | 2 | setting var_id |
| +0x02 | N | one byte per MOP option (`0x01` = member of that mode) |

The mode columns are taken from the `MOP` enum order, not from hardcoded mode
names.

This table describes which setting variables belong to each therapy mode. It is
a per-mode setting membership map: for example, it can answer "which settings
are part of VAuto?".

The g[8] `permission_bitmask` is stored inside one enum/option descriptor and
gates that variable's option/mode availability. It is local to that variable.
g[24] is the broader table mapping many setting variables across all `MOP`
modes.

Example (SX567 0402):

```text
MNE: CPAP=0 AutoSet=0 APAP=0 S=0 ST=0 T=0 VAuto=1
     ASV=0 ASVAuto=0 iVAPS=0 PAC=0 AutoSetForHer=0
```

---

## g[26] -- live stream records

8 records x 20 bytes. Defines live stream schemas such as `TCE`, `PBT`, `PMD`,
`FTX`, `RAW`, `DRT`, `CPU`, and `SSK`.

ResMed metadata names `TCE` as `TRIG_CYC`, `PBT` as
`PERIODIC_BREATH_TXLINK`, and `PMD` as `MASK_DATA`.

| Offset | Size | Field |
|--------|------|-------|
| +0x00 | 1 | field count |
| +0x01 | 3 | stream name |
| +0x04 | 4 | config |
| +0x08 | 4 | var_id array pointer |
| +0x0C | 4 | rate/scale array pointer |
| +0x10 | 4 | config |

Some stream arrays differ by therapy family. The count field describes only the
number of entries to read; the pointer fields define where the var_id/rate
arrays actually live.

Example (SX567 0402 AirSense AutoSet):

```text
PMD: field_count=3  fields=MKP,RFL,LYK
```

---

## g[27] -- APN/CSN/BRH records

3 records x 16 bytes (`APN`, `CSN`, `BRH`). The records point into packed
var-ID arrays stored near the g[26] payloads. OXH is a separate g[28] object.

| Channel | ResMed name | Fields |
|---------|-------------|--------|
| `APN` | `APNEA` | `AET` (`APN_EV_TYPE`), `DUR` (`APNEA_DUR`) |
| `CSN` | `CSR_EVENT_RT` | `CET` (`CSR_EVENT_TIME`), `CSR` (`CSR_EVENT_TYPE`) |
| `BRH` | `BREATH_TXLINK` | `TID` (`TIDAL_VOLUME`), `ATP` (`AUTO_PRESS`), `INT` (`INSPIRATION_TIME`), `EXT` (`EXPIRATION_TIME`) |

| Offset | Size | Field |
|--------|------|-------|
| +0x00 | 1 | field count |
| +0x01 | 3 | record name |
| +0x04 | 4 | config |
| +0x08 | 4 | var_id array pointer |
| +0x0C | 4 | rate/scale array pointer |

Observed maximum windows:

| Record | Vars |
|--------|---------------|
| APN | AET, DUR |
| CSN | CET, CSR |
| BRH | TID, ATP, INT, EXT |

Example (SX567 0402 AirSense AutoSet):

```text
BRH: field_count=2  fields=TID,ATP
```

Live stream reporting is enabled over UART with `P S &TAG 1` and disabled with
`P S &TAG 0`; see [serial_protocol.md](serial_protocol.md#live-stream-reporting).

Common live stream fields across checked SX567 Air 10 variants:

| Stream | Fields | Purpose |
|--------|--------|---------|
| PMD | MKP, RFL, LYK | Mask pressure, respiratory flow, and leak samples |
| FTX | BPR, BFL, NSE, TEM | Flow/pressure sensor diagnostics |
| RAW | PRS, FLW, NOS, TEZ | Raw pressure, flow, and temperature samples |
| DRT | D00, D01, D02, D03, D04, D05, D06, D07, D08, D09 | Internal diagnostic values |
| CPU | ALL, L01, L02, L03, L04, L05, L06, L07, L08, L09, L10, L11, L12, L13, L14, L15, L16, L17, L18, L19, L20 | CPU load counters |
| SSK | S10, S20, S40, S11, S22, S44, S1S, S1M, SMM, SEE, SPL, SLD | Internal status values |
| APN | AET, DUR | Apnea event type and duration |

Variant-dependent live stream fields:

| Stream | AirCurve VAuto | AirCurve CS | AirSense AutoSet/AfH | AirSense Elite | Purpose |
|--------|----------------|-------------|---------------------|---------------|---------|
| TCE | TCV, MKP, RFL, LYK | MKP, RFL, LYK | MKP, RFL, LYK | MKP, RFL, LYK | Trigger/cycle and therapy-control samples |
| PBT | MV5, RRR, LKF, TIP, TEP | MV5, TGT, RRR, LKF, TIP, TEP | MV5, RRR, LKF, TIP, TEP | MV5, RRR, LKF, TIP, TEP | Periodic breath TxLink summary |
| CSN | CSR | CSR | CET, CSR | CET, CSR | CSR event state and timing |
| BRH | TID, ATP, INT, EXT | TID, ATP | TID, ATP | TID | Per-breath TxLink summary |

---

## g[28] -- OXH (oximetry header)

| Offset | Size | Field |
|--------|------|-------|
| +0x00 | 1 | field_count |
| +0x01 | 3 | "OXH" |
| +0x04 | 4 | reserved |
| +0x08 | 4 | var_id array pointer |
| +0x0C | 4 | output array pointer |

Example (SX567 0402):

```text
OXH: field_count=6  fields=OXS,HRS,HRR,SAS,SAR,NVS
```

---

## Flags bitmask

Shared format at +0x00 of g[3], g[4], g[6], g[8] records. Copied from ROM to RAM shadow on init.

| Bit | Mask | Name | Description |
|-----|------|------|-------------|
| 0 | 0x01 | ACT | Active. Master enable gate. If clear, value changes are blocked |
| 1 | 0x02 | VIS | Visible in UI menus |
| 2 | 0x04 | EDT | Editable by user |
| 3 | 0x08 | SIGNED | g[4]: signed numeric representation |
| 4 | 0x10 | LOCK | Read-only lock |
| 5 | 0x20 | READY | Runtime initialized/ready gate |
| 6 | 0x40 | EXT | Harness/periodic external override |
| 7 | 0x80 | RAW | g[4]: use raw numeric handling instead of descriptor-step quantization |

For g[4] numeric variables, RAW changes several parts of the standard numeric
handler:

| Operation | RAW set | RAW clear |
|-----------|---------|-----------|
| Increment/decrement | one raw unit | `step_size` |
| In-range write | stored without step quantization | rounded to the nearest step relative to `min_value` |
| Out-of-range write | clamped to the descriptor bounds | rejected |
| Dynamic bound update | stored exactly, then bounded | step-quantized, then bounded |

One raw unit is converted for display through `scale_factor`. For example, one
raw unit is 0.2 cmH2O when the scale factor is 5.

---

## RAM shadow

### g[8] -- 4 bytes per entry

| Offset | Source | Content |
|--------|--------|---------|
| +0x00 | +0x00 | flags (mutable) |
| +0x02 | +0x08 | current value |
| +0x03 | -- | pad |

### g[4] -- 8 bytes per entry

| Offset | Source | Content |
|--------|--------|---------|
| +0x00 | +0x00 | flags (mutable) |
| +0x02 | -- | pad |
| +0x04 | +0x08 | current value (i32, mutable) |

---

## Dependency chain

The common update path for g[3], g[4], g[6], and g[8] variables walks a linked
list of dependent g[4] variables:

```
source descriptor +0x04: dependency_head_g4_idx
  -> g[4][dependency_head_g4_idx] +0x04: next_dependent_g4_idx
    -> g[4][next_dependent_g4_idx] +0x04: next_dependent_g4_idx
      -> ... (up to 4 deep, 0x7FFF terminates)
```

This is an update propagation chain, not a menu-visibility relationship.
Storage-backed settings commonly terminate at a group tracking variable. That
propagation marks the associated variable group for persistence in its `.set`
file.

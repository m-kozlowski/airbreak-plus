# AirSense/AirCurve 11 CONF Block Format

Reference for the S11 CONF block layout, globals[] master table, var-id
dispatch, descriptor record shapes, and per-table semantics. Cross-checked
against the official 14.8.3.0 vid03 dump, the official 15.8.4.0 variant
dumps (vid03 AirSense, vid07 AirCurve VAuto, vid10 AirCurve S/ST/T, vid12
AirCurve ASV), and Ghidra decompilation.

## Table of contents

- [globals[] map](#globals-map)
- [Conventions](#conventions)
- [Quick analysis workflow](#quick-analysis-workflow)
- [Physical packing and pointer-owned payloads](#physical-packing-and-pointer-owned-payloads)
- [Structure families](#structure-families)
- [Var-ID dispatch](#var-id-dispatch)
- [Flags field](#flags-field)
- [Common DataItem descriptor fields](#common-dataitem-descriptor-fields)
- [g[0] -- CONF header](#g0----conf-header)
- [g[1] -- scalar DataItem descriptors](#g1----scalar-dataitem-descriptors)
- [g[2] -- numeric DataItem descriptors](#g2----numeric-dataitem-descriptors)
- [g[3] -- bitfield DataItem descriptors](#g3----bitfield-dataitem-descriptors)
- [g[4] -- option/index byte-list pool](#g4----optionindex-byte-list-pool)
- [g[5] -- enum DataItem descriptors](#g5----enum-dataitem-descriptors)
- [g[6] -- named var-id list headers](#g6----named-var-id-list-headers)
- [g[7] -- PDL SettingsUnit header](#g7----pdl-settingsunit-header)
- [g[8] -- short-name bucket headers](#g8----short-name-bucket-headers)
- [g[9] -- short-name reverse table](#g9----short-name-reverse-table)
- [g[10] -- per-mode variable registration](#g10----per-mode-variable-registration)
- [g[11] -- record count for g[10]](#g11----record-count-for-g10)
- [g[12] -- event/log definitions](#g12----eventlog-definitions)
- [g[13] -- event route table](#g13----event-route-table)
- [g[14] -- periodic/session collections](#g14----periodicsession-collections)
- [g[15] -- STR.edf SummaryRecord schema](#g15----stredf-summaryrecord-schema)
- [g[16] -- EDF stream file schemas](#g16----edf-stream-file-schemas)
- [g[17] -- event label tables](#g17----event-label-tables)
- [g[18] -- RPC JSON node permission table](#g18----rpc-json-node-permission-table)
- [g[19] -- DDO/reporting source list](#g19----ddoreporting-source-list)
- [Hidden mode clusters](#hidden-mode-clusters)
- [Feature child settings](#feature-child-settings)
- [Cross-variant patching rules](#cross-variant-patching-rules)
- [Patcher implications](#patcher-implications)

---

## globals[] map

| Global | Meaning |
| ---: | ------- |
| g[0] | CONF header: product/platform, variant id, build/firmware strings, master-table trampoline |
| g[1] | scalar `DataItem` descriptors |
| g[2] | numeric `DataItem` descriptors |
| g[3] | bitfield `DataItem` descriptors |
| g[4] | option/index byte-list pool for g[3]/g[5], plus pointer-owned tables used by g[8]/g[16]/g[17] |
| g[5] | enum `DataItem` descriptors |
| g[6] | named var-id list headers (`BGL`, `DDO`, `DID`, `HST`, `MCA`, `MCF`, `TLP`) |
| g[7] | `PDL` `SettingsUnit` header; later bytes in its physical interval are pointer-owned payloads |
| g[8] | A-Z short-name bucket headers (3-char tag -> var_id) |
| g[9] | linear var-id -> 3-char short-tag pool |
| g[10] | per-mode variable registration rows |
| g[11] | scalar count for g[10], `0x67` / 103 |
| g[12] | event/log definitions; later bytes in its physical interval are pointer-owned payloads |
| g[13] | event route table root; the adjacent `DDO` var-id payload is pointed to by g[6] |
| g[14] | periodic/session collections (`CSF`, `TIP`, `MLK`, `MPD`, `RFD`, `NRF`, `APD`) |
| g[15] | `STR.edf` `SummaryRecord` schema header |
| g[16] | EDF stream file schemas (`BRP`, `SA2`, `PLD`) |
| g[17] | event label tables (`EVE`, `AEV`, `CSL`) |
| g[18] | CDX/RPC JSON node permission table; later bytes are g[8] short-name bucket payloads |
| g[19] | DDO/reporting snapshot source list, reporting tag/string/list pool, then erased tail |

---

## Conventions

- `g[n]` means `globals[n]`, the nth 32-bit entry in the CONF master table.
- Record-table offsets such as `+0x0c` are relative to the start of that
  record, not the start of the CONF block.
- File offsets such as `0x02d040` refer to a full firmware image with CONF at
  file offset `0x020000`. Runtime flash addresses use the `0x080xxxxx` form.
- Var IDs are firmware `DataItem` IDs, but they are **version-local**. They
  are assigned by descriptor array order and drift when records are inserted
  or removed. The three-letter tag (`MOP`, `LAN`, etc.) and CDX long name are
  better semantic anchors for cross-version work. RPC may expose long CDX
  names such as `ActiveTherapyProfile` and underscore aliases such as `_MOP`,
  but bare three-letter tags are internal names.
- `docs/as11/var_reference.tsv` lists the same variables against the known
  14.8.3.0 and 15.8.4.0 var IDs. Treat the ID columns as lookup results for
  those specific releases, not as portable constants. Its `notes` column is
  based on the 15.8.4.0 variant superset unless a row is explicitly marked
  `14.8.3.0 only`.
- Unless stated otherwise, record counts and examples are from 15.8.4.0
  variant dumps.

---

## Quick analysis workflow

Use this document as both a map and a decoder:

1. Start from [globals[] map](#globals-map) to identify the root table.
2. Use [Physical packing and pointer-owned payloads](#physical-packing-and-pointer-owned-payloads)
   before assuming bytes after a table are free or unrelated.
3. For settings and variables, derive the descriptor array from
   [Var-ID dispatch](#var-id-dispatch), then decode the row with g[1], g[2],
   g[3], or g[5].
4. For UI/RPC availability, combine descriptor flags, enum option masks,
   g[10] mode registration, g[18] RPC node visibility, and g[15]
   SummaryRecord activation.
5. For EDF/reporting work, use g[15] for `STR.edf`, g[16] for BRP/SA2/PLD,
   g[17] for event labels, and g[19] for DDO/reporting sources.
6. For cross-version or cross-variant patching, resolve names and table bases
   from the target image rather than importing offsets from another build.

---

## Physical packing and pointer-owned payloads

`globals[]` entries are accessor roots, not ownership boundaries. The sorted
address range from one global pointer to the next is useful for locality, but
it does not mean every byte in that range belongs to that global's primary
structure.

Most globals fall into one of two shapes:

- **Direct arrays**: the global points at a fixed-stride table and firmware
  knows the count from dispatch ranges or a nearby scalar. Examples: g[1],
  g[2], g[3], g[5], g[10], g[12], g[14], g[17].
- **Header objects**: the global points at a small header whose payload lives
  elsewhere by pointer. Examples: g[6], g[7], g[15], g[16], g[19].

The CONF block then packs many pointer-owned payloads into gaps after those
headers and arrays. Common payloads include:

- g[8] short-name bucket payloads
- g[6] var-id list payloads
- g[17] event label pointer tables
- g[16] EDF stream signal records
- g[14] periodic collection var-id lists and signal metadata
- string/unit/code pools referenced by pointer fields

Example from vid03 15.8.4.0:

| Physical location | Logical owner |
|-------------------|---------------|
| after g[2] descriptors at `0x025688` | g[15] `SummaryRecord` table |
| after g[3] descriptors | g[8] `Z`, `S`, and `A` short-name bucket payloads |
| after g[7] `PDL` header | g[17] `CSL` label table, g[8] `K`/`N` buckets, EDF strings referenced by other tables |
| after g[12] event definitions | g[8] `O` short-name bucket payload |
| inside the g[14] address interval | g[14] signal metadata, g[8] buckets, g[6] `HST` list |
| after g[18] permission table | g[8] `C`, `M`, `R`, and `H` bucket payloads |

So "tail" data after an array is often related, just not related through the
array's record stride. Patchers must follow pointers and known header counts
before treating any area as free or movable. Erased `0xff` slack is usable only
after confirming no known table, list, string, or pointer table references it.

Across the checked 15.8.4.0 images, the main pointer-owned payload split
points are stable:

| Physical interval | Pointer-owned payload start |
|-------------------|-----------------------------|
| g[2] | g[15] `SummaryRecord` table at g[2] + `0x5580` |
| g[12] | g[8].`O` bucket at g[12] + `0x33c` |
| g[14] | g[8].`D` bucket at g[14] + `0x16c` |
| g[18] | g[8].`M`/`R`/`H`/`C` buckets after the permission table |
| g[7] | g[17].`CSL`, g[8].`K`/`N`, and g[14].`CSF` payloads |
| g[13] | g[6].`DDO` list payload at g[13] + `0x80` |

### Address-sorted layout example

The master table order is logical, not physical. In vid03 15.8.4.0, the
address-sorted layout begins with g[0], g[2], g[5], g[9], g[10], then g[1].
Patchers must use the master-table roots and descriptor formats to identify
arrays, not physical order alone.

| Root | File range | Primary object |
|------|------------|----------------|
| g[0] | `0x020000..0x020108` | CONF header |
| g[2] | `0x020108..0x027188` | numeric descriptors, then pointer-owned payloads |
| g[5] | `0x027188..0x0287e8` | enum descriptors |
| g[9] | `0x0287e8..0x0295cc` | 3-char short-name reverse pool |
| g[10] | `0x0295cc..0x029b70` | mode registration rows |
| g[1] | `0x029b70..0x029ff8` | scalar descriptors |
| g[12] | `0x029ff8..0x02a5a0` | event definitions, then pointer-owned payloads |
| g[3] | `0x02a5a0..0x02acd0` | bitfield descriptors, then g[8] bucket payloads |
| g[14] | `0x02acd0..0x02b39c` | collection headers, then pointer-owned payloads |
| g[18] | `0x02b39c..0x02b8c0` | RPC node permissions, then g[8] bucket payloads |
| g[8] | `0x02b8c0..0x02ba54` | A-Z short-name bucket headers |
| g[17] | `0x02ba54..0x02bb68` | event label table headers |
| g[4] | `0x02bb68..0x02bff0` | option/index byte-list pool and pointer-owned tables |
| g[13] | `0x02bff0..0x02c0f0` | event route table, padding, then g[6].`DDO` list payload |
| g[6] | `0x02c0f0..0x02c468` | var-id list headers, then pointer-owned list payloads |
| g[16] | `0x02c468..0x02cce8` | EDF stream headers, then pointer-owned signal tables |
| g[15] | `0x02cce8..0x02cf60` | STR header, inline auxiliary key map, then EDF label strings |
| g[7] | `0x02cf60..0x02d040` | PDL header, then pointer-owned payloads |
| g[19] | `0x02d040..0x040000` | DDO/reporting header and pools |

---

## Structure families

Use this as the first-pass classifier when analyzing a byte range:

| Family | Typical root | How to find extent |
|--------|--------------|--------------------|
| Descriptor array | g[1]/g[2]/g[3]/g[5] | dispatch range count times stride |
| Fixed table | g[10]/g[12]/g[14]/g[17] | known count times stride, or stop at invalid pointers |
| Header + list pointer | g[6]/g[7]/g[19] | header count plus the pointed u16 list |
| Header + record pointer | g[15]/g[16] | header count plus pointed records and strings |
| Permission table | g[18] | highest APPL node id times 2; later bytes are owned through other roots |
| Pointer-owned payload | tails after many globals | only pointer references define ownership |

This is also the safest patching rule: update the object through its own
header fields and pointers, not by assuming everything between two adjacent
global roots is one object.

---

## Var-ID dispatch

`DataItemFactory_create` routes var IDs to descriptor arrays by range.
Implicit indexing: `record_index = var_id - id_base`. Those ranges are
computed from descriptor counts in the target image, so they drift across
firmware releases.

| Version | Table | var_id range | Stride | Records |
|---------|-------|--------------|---:|---:|
| 14.8.3.0 | g[1] | `0x0000..0x006e` | 10 | 111 |
| 14.8.3.0 | g[2] | `0x006f..0x0306` | 32 | 664 |
| 14.8.3.0 | g[3] | `0x0307..0x0320` | 20 | 26 |
| 14.8.3.0 | g[5] | `0x0321..0x047a` | 16 | 346 |
| 15.8.4.0 | g[1] | `0x0000..0x0073` | 10 | 116 |
| 15.8.4.0 | g[2] | `0x0074..0x031f` | 32 | 684 |
| 15.8.4.0 | g[3] | `0x0320..0x0339` | 20 | 26 |
| 15.8.4.0 | g[5] | `0x033a..0x049f` | 16 | 358 |

Example from 15.8.4.0: `TherapyLEDAlwaysOn` var_id `0x0484` ->
`g[5][0x0484 - 0x033a]` = `g[5][330]` -> file offset `0x28628`.

g[5]'s `id_base` shifts by version because it depends on the preceding table
counts:

```text
g[5] id_base = g[1] count + g[2] count + g[3] count
```

| Version | g[1]+g[2]+g[3] | g[5] id_base |
|---------|----------------|--------------|
| 14.8.3.0 | 111 + 664 + 26 | `0x0321` |
| 15.8.4.0 | 116 + 684 + 26 | `0x033a` |

Using a different version's `id_base` shifts every enum var onto the wrong
record. Patchers must recompute it from the target image's master table and
resolve variables by short/long name or descriptor shape before using a
var_id.

Observed examples:

| Variable | 14.8.3.0 | 15.8.4.0 |
|----------|---------:|---------:|
| `HeartRate` / `HRT` | `0x0157` | `0x0168` |
| `SpO2` / `SAO` | `0x0285` | `0x029c` |
| `LanguageConfiguration` / `LNC` | `0x0312` | `0x032b` |
| `BluetoothPassthrough` / `BNP` | `0x033e` | `0x0357` |
| `ActiveTherapyProfile` / `MOP` | `0x03f1` | `0x040e` |
| `PeripheralMsg` / `PMS` | `0x03fe` | `0x041b` |
| `RampEnablePatientAccess` / `RPE` | `0x0410` | `0x042d` |

---

## Flags field

The u16 at +0x00 of every g[1]/g[2]/g[3]/g[5] descriptor record. Encodes
descriptor capability bits and seeds runtime state bits.

The descriptor's data-item type (scalar/numeric/bitfield/enum) is not
encoded here -- it is implicit in which globals[] table holds the record;
`DataItemFactory_create` routes by var_id range alone (see
[Var-ID dispatch](#var-id-dispatch)).

### Bit map

Bit semantics derived from the DataItem base-class accessors at `0x08070dde`
.. `0x08070f26` and their callers. Bits with named meanings have been traced
to specific high-level callers; the rest are documented by their accessor
behavior only.

| Bit | Mask | Source | Name / role | Evidence |
|----:|------|--------|-------------|----------|
| 0 | `0x0001` | descriptor + shadow | **ACTIVE** -- master enable | universal precondition; cleared on inactive variant rows (`0x0606` etc.); seeded into shadow at boot |
| 1 | `0x0002` | descriptor AND shadow | **VISIBLE** -- UI/RPC node visibility | `therapy_profiles_update` writes from `node_isVisible(...)`; mirrored from `FeatureProfiles` permission state |
| 2 | `0x0004` | shadow | **ACTIVE_MODE_BOUND** -- mutated together with bit 10 in `ActiveTherapyProfile` enter/leave paths | toggled in pairs at `0x08151766` (clear) and `0x08151808` (set) |
| 3 | `0x0008` | descriptor only | **NUMERIC_SOURCE** -- g[2]-only source/reporting numeric marker | set on live/source/summary numeric rows such as RawFlow, 100 Hz pressure/flow, one-minute values, and D00-style source slots; absent from config settings |
| 4 | `0x0010` | shadow | runtime inhibit/state flag; accessor returns true when clear | test pattern at `0x08070e70` |
| 5 | `0x0020` | shadow | **HAS_VALUE** -- value present / set since reset | set by `FUN_08070db4` after every `setValue`; AND-checked across required-var lists to validate "all needed values present" |
| 6 | `0x0040` | shadow | **RUNTIME_FLAG_40** -- runtime-only shadow flag | no ROM descriptor in the checked 15.8.4.0 variants has this bit set; accessor exists at `0x08070df2` |
| 7 | `0x0080` | descriptor only | **NUMERIC_RUNTIME_VALUE** -- g[2]-only runtime/measurement numeric marker | set on most runtime/measurement numerics; absent from g[1]/g[3]/g[5] and from most therapy/config settings |
| 9 | `0x0200` | shadow | mutable; always set in ROM on observed records | accessor at `0x08070e3e` |
| 10 | `0x0400` | shadow + setter | toggled together with bit 2 in `ActiveTherapyProfile` enter/leave paths | accessor at `0x08070e46`, setter wrapper at `0x08070f26` |
| 11 | `0x0800` | descriptor + shadow | **SETTING_APPLY_CANDIDATE** -- persistent/apply-path candidate marker | set on most mutable HST setting rows and selected TLP/meter/reset rows; absent from passive display choices such as Language, TemperatureUnit, and ActiveTherapyProfile; accessor at `0x08070e4e` |

Bit 8 and bits 12-15 have not been observed set in any descriptor and have no
known accessor.

---

## Common DataItem descriptor fields

The g[1]/g[2]/g[3]/g[5] descriptors share the same flags, owner reference,
and factory tag fields. The u16 at +0x02 is array-specific: it behaves like a
grouping id in g[1]/g[2]/g[3], but in g[5] it is the enum option-pool offset
into g[4].

| Offset | Field | Meaning |
|--------|-------|---------|
| +0x00 | flags | active/visibility/runtime seed bits; see [Flags field](#flags-field) |
| +0x04 | owner_ref | named-list anchor or parent/source var reference; `0x7fff` means none |
| +0x06 | factory_tag | DataItem factory/class tag; normally `0x0017` |

### g[1]/g[2]/g[3] +0x02: ui_group_id

For g[1]/g[2]/g[3], non-zero `ui_group_id` values cluster settings that the
GUI/config/RPC layer treats as a small family. The role is inferred from
cross-record grouping and is consistent across the checked 15.8.4.0 variants.

Examples from vid03 15.8.4.0:

| ui_group_id | Records |
|------------:|---------|
| `0x04` | HerAuto pressure triplet |
| `0x05` | AutoSet pressure triplet |
| `0x0b` | climate numeric siblings, humidifier level, heated tube temperature |
| `0x0d` | CPAP pressure pair |
| `0x20` | iVAPS target rate and inspiratory time group |
| `0x28` | iVAPS EPAP/pressure-support group |
| `0x32` | PAC pressure/rate/time group |
| `0x43` | ST pressure/rate/time group |
| `0x46` | Spont pressure/time/rate-enable group |
| `0x49` | Timed pressure/rate/time group |
| `0x4d` | VAuto pressure/time/sensitivity group |

Singleton group ids also exist, for example `LanguageConfiguration` uses
`0x29`, `MaxRampDownTime` uses `0x2c`, and `MaxRampTime` uses `0x2d`.

### owner_ref

`owner_ref` has two observed modes:

1. If the value matches a g[6] list anchor (`BGL`, `DDO`, `DID`, `HST`,
   `MCA`, `MCF`, `TLP`), the DataItem belongs to that named list.
2. Otherwise, non-`0x7fff` values are actual var_ids used as parent/source
   references by small dependent records.

Known g[6] anchors:

| owner_ref | g[6] tag | Role |
|----------:|----------|------|
| `0x0071` | `BGL` | pressure and flow calibration coefficients: gain/offset pairs for flow, pressure, and pressure monitor conversion |
| `0x00a5` | `DDO` | data-delivery/reporting DataItems: event and periodic payload handles plus companion timestamp/status fields used by the DDO/reporting path |
| `0x00b2` | `DID` | identification profile fields: product, serial, UUID/UDI, geography, hardware, and cellular model/provider identity |
| `0x00c5` | `TLP` | telemetry/cloud control plane fields: APN/service endpoint, data mode, broker periods, OTA status/report periods, CAL/flight flags, and internal transport/log state |
| `0x010b` | `HST` | settings-history persistence set: therapy parameters, comfort/ramp/EPR/climate/circuit/language/reminder/alarm/display settings, including hidden modes |
| `0x0182` | `MCA` | single CAML broker/config blob (`CamlData`), an encoded cloud/update state payload |
| `0x0183` | `MCF` | single application-data blob (`ApplicationData`), companion opaque application config/state payload |


Examples of true parent/source references in g[5]:

| Record | owner_ref | Referenced var |
|--------|----------:|----------------|
| `TDS` TestDriveState | `0x0284` | `SMT` |
| `TZE` | `0x028c` | SetPressure-100hz |
| `ZSD` | `0x02ab` | ST-FallTime |
| `SCH` | `0x0224` | PAC-StartPressure |

### factory_tag

`factory_tag` is `0x0017` for all observed g[1]/g[2]/g[3] descriptors and
all normal g[5] descriptors. The checked 15.8.4.0 g[5] exception is `FSE` /
`SystemError`, which has `factory_tag = 0x0009`, 23 options, and
`option_mask = 0x007fffff`. Treat this as a factory/class discriminator, not
as a free constant.

### Descriptor role summary

| Array | Offset | Field | Role |
|-------|--------|-------|------|
| g[1]/g[2]/g[3] | +0x02 | ui_group_id | related-setting cluster id |
| g[5] | +0x02 | g4_options_offset | byte offset into the enum code-list pool in g[4] |
| g[1]/g[2]/g[3]/g[5] | +0x04 | owner_ref | g[6] list anchor or parent/source var reference |
| g[1]/g[2]/g[3]/g[5] | +0x06 | factory_tag | DataItem factory/class discriminator |
| g[2] | +0x1a | bounds_slot | dynamic numeric bounds slot; `0x3e` means use descriptor min/max directly |
| g[2] | +0x1b | sample_source_id | runtime sample-channel id on selected source numerics; zero on normal settings |
| g[2] | +0x1c | quantity_class | physical quantity/unit family used with scale/format |

---

## g[0] -- CONF header

Not a descriptor array; points to the start of the CONF block. Direct readers
populate platform/build identifiers.

| Offset | Size | Field | Description |
|--------|------|-------|-------------|
| +0x00 | 4 | DataVersionIdentifier (`_PVD`) | `0x0f` (15) on 15.8.4.0; major version field of the SW string |
| +0x04 | 4 | PlatformIdentifier (`_MID`) | `0x2e` (46); platform identifier |
| +0x08 | 4 | -- | zero |
| +0x0c | 4 | VariantIdentifier (`_VID`) | 3, 7, 10, 12 |
| +0x10 | 4 | -- | zero |
| +0x14 | 4 | ProfileVariantIdentifier ptr | UUID-format string |
| +0x18 | 16 | platform name | "SIMPLICITY" |
| +0x28 | 16 | model | "390XX" |
| +0x38 | 16 | codename | "Pacific" |
| +0x68 | char[] | application git hash | "791777c3b" |
| +0x72 | char[] | data model version | "v2.15.2" |
| +0x7e | char[] | data model git hash | "7fc2c6467" |
| +0x100 | -- | Thumb trampoline | returns master table pointer at +0x104 |
| +0x104 | 4 | master table pointer | |

### Runtime composite identifiers

The runtime RPC composes several identifiers from the header fields above:

| RPC field | Value (vid03 15.8.4.0) | Composition |
|-----------|------------------------|-------------|
| `_FGT` | `2e_M46_V3` | `<MID-hex>_M<MID-decimal>_V<VID>` |
| `ProfileVariantIdentifier` | `00000000-0000-3000-8000-000015046003` | UUID with trailing `<PVD:02d><MID:03d><VID:03d>` |
| `ApplicationIdentifier` | `SW04600.15.8.4.0.791777c3b` | `SW<04600>.<full SW version>.<+0x68>` |
| `DataModelVersionIdentifier` | `v2.15.2.7fc2c6467` | `<+0x72>.<+0x7e>` |
| `ConfigurationIdentifier` | `CF04600.15.03.00.791777c3b` | `CF<04600>.<PVD:02d>.<VID:02d>.00.<+0x68>` |

The `04600` token in `ApplicationIdentifier` and `ConfigurationIdentifier`
appears to be a fixed product-line marker derived from the platform identifier
(`0x2e * 100` = `4600`).

---

## g[1] -- scalar DataItem descriptors

**Record stride:** 10 bytes

Backs `VolatileTextDataItem` -- short text/identifier variables (CID, SID,
BID, PNA, SRN, PtAccess strings, etc.). The runtime value is a string buffer
in SRAM; this descriptor only describes its shape.

| Offset | Size | Field | Description |
|--------|------|-------|-------------|
| +0x00 | 2 | flags | see [Flags field](#flags-field) |
| +0x02 | 2 | ui_group_id | see [ui_group_id](#ui_group_id) |
| +0x04 | 2 | owner_ref | see [owner_ref](#owner_ref) |
| +0x06 | 2 | factory_tag | common descriptor field; `0x0017` in observed records |
| +0x08 | 2 | max_length | maximum string length in bytes (e.g. 30, 32, 50, 64, 192) |

---

## g[2] -- numeric DataItem descriptors

**Record stride:** 32 bytes

Backs `NumericDataItem` -- the numeric/ranged variables (pressures, times,
percentiles, counters). Values are i32 in raw units, displayed after dividing
by `scale`.

| Offset | Size | Field | Description |
|--------|------|-------|-------------|
| +0x00 | 2 | flags | see [Flags field](#flags-field) |
| +0x02 | 2 | ui_group_id | see [ui_group_id](#ui_group_id) |
| +0x04 | 2 | owner_ref | see [owner_ref](#owner_ref) |
| +0x06 | 2 | factory_tag | common descriptor field; `0x0017` in observed records |
| +0x08 | 4 | default_raw | factory default in raw units |
| +0x0c | 4 | max_raw | upper clamp |
| +0x10 | 4 | min_raw (i32) | lower clamp; negative on signed records |
| +0x14 | 2 | format_selector | display formatter index (`0` plain, `1` scaled, `2` ms, `3` h:m:s, `4` text/bool, ...) |
| +0x16 | 2 | scale | raw-to-display divisor (e.g. raw 500 / scale 50 = display 10.0) |
| +0x18 | 2 | step_raw | UI increment/decrement step in raw units |
| +0x1a | 1 | bounds_slot | dynamic min/max bounds slot; `0x00..0x3d` index the runtime bounds table, `0x3e` uses static descriptor bounds |
| +0x1b | 1 | sample_source_id | nonzero on selected runtime/source numerics; zero on normal settings |
| +0x1c | 4 | quantity_class | physical quantity / unit class used with formatter/reporting code |

Format-selector decoding lives in `FUN_08073426`. Selector values map to:

| Selector | Display |
|---------:|---------|
| 0 | raw integer (with `scale` for divisor) |
| 1 | raw / scale |
| 2 | raw * 1000, with scale (ms) |
| 3 | raw / 3600 (hours) |
| 4 | text/bool lookup |
| 5 | raw / 60 (minutes) |
| 6 | text/bool lookup, alt |
| 7 | raw * 60, with scale |
| 8 | raw * 1000, with scale (ms, signed) |
| 9 | raw as i8, with scale |

Code anchors:

| Function | Reads | Use |
|----------|-------|-----|
| `FUN_08073660` / `..737dc` / `..73838` / `..738a6` | record+0x18 | numeric step |
| `FUN_08073c2c` | record+0x16 | display scale |
| `FUN_08073426` | record+0x14 (via param) | format selector |
| `FUN_08073900` | record+0x0c, +0x10 | min/max bounds |

### bounds_slot and sample_source_id

`bounds_slot` selects the source of numeric min/max limits. The numeric
accessor code reads byte `+0x1a` as a signed byte and compares it with
`0x3e`.

- `0x00..0x3d` index a 62-entry RAM table of dynamic min/max bounds.
- `0x3e` selects the descriptor's own `min_raw` and `max_raw` fields.
- A numeric setting uses a dynamic slot when its legal range depends on other
  state; otherwise it usually uses `0x3e`.

Conceptually:

```c
struct DynamicBounds {
    int32_t min_raw;
    int32_t max_raw;
};

DynamicBounds dynamic_bounds[0x3e];  // slots 0x00..0x3d

if (descriptor.bounds_slot < 0x3e) {
    min_raw = dynamic_bounds[descriptor.bounds_slot].min_raw;
    max_raw = dynamic_bounds[descriptor.bounds_slot].max_raw;
} else {
    min_raw = descriptor.min_raw;
    max_raw = descriptor.max_raw;
}
```

For example, `RMT` / `RampTime` has `bounds_slot = 0x21`, so its active range
comes from `dynamic_bounds[0x21]`. `MRT` / `MaxRampTime` has
`bounds_slot = 0x3e`, so its active range comes from its own descriptor fields.


`sample_source_id` is byte `+0x1b`. It is zero on normal settings and nonzero
on a small group of ownerless runtime source numerics.
The nonzero values form a stable source-channel id namespace
used by periodic/session collection plumbing. g[14] collections select
DataItems by var_id and may use any subset of these source channels.

Observed nonzero source ids:

```text
01 AIP  02 LKP  03 AAH  04 RFA  05 AFL  06 LKR  07 BPA  08 BFL  09 BPR
10 AEP  11 AIE  12 MVT  13 RR1  14 ATI  15 QCN  16 QS2  17 QS3  18 QS4
19 SAV  20 HRV  21 MIS  22 A1M  23 BRF  24 BIP  25 BML  26 BMR  27 AAP
```

### quantity_class

`quantity_class` is a semantic unit family id used with `format_selector`,
`scale`, and sometimes stream-specific metadata to present or report numeric
values.

Across the 15.8.4.0 variants, the observed classes are:

| quantity_class | Observed family |
|---------------:|-----------------|
| `0x00` | pressure / pressure support, usually cmH2O |
| `0x01` | ventilation, usually L/min |
| `0x02` | duration, usually seconds |
| `0x03` | flow/leak, usually L/s |
| `0x04` | absolute humidity, mg/L |
| `0x05` | ratio, percent, or index-like scalar |
| `0x06` | temperature, Celsius |
| `0x07` | heart rate, bpm |
| `0x08` | respiratory rate, bpm |
| `0x09` | patient height |
| `0x0a` | tidal volume, L |
| `0x0b` | ramp/time minutes |
| `0x0c` | generic unitless/status/mixed scalar |

Example -- `Cpap-SetPressure`:

```text
default/min/max/step raw = 500/200/1000/10
scale = 50
displayed values = 10.0 / 4.0 / 20.0 / 0.2 cmH2O
```

---

## g[3] -- bitfield DataItem descriptors

**Record stride:** 20 bytes

Backs `BitFieldDataItem` -- multi-bit toggle variables (e.g.
`LanguageConfiguration`, `NodeAccessFlags`). The runtime value is a u32
bitmask masked through `editable_mask`. `LanguageConfiguration` (`LNC`,
var_id `0x032b`) lives here, not in the enum table.

| Offset | Size | Field | Description |
|--------|------|-------|-------------|
| +0x00 | 2 | flags | see [Flags field](#flags-field) |
| +0x02 | 2 | ui_group_id | see [ui_group_id](#ui_group_id) |
| +0x04 | 2 | owner_ref | see [owner_ref](#owner_ref) |
| +0x06 | 2 | factory_tag | common descriptor field; `0x0017` in observed records |
| +0x08 | 4 | fixed_mask | bits forced to default value outside `editable_mask`; ORed into the result |
| +0x0c | 4 | editable_mask | bits the user may set; values written by `setValue` are masked through this |
| +0x10 | 1 | bit_count | number of meaningful bits (popcount of `editable_mask` in observed records) |
| +0x11 | 1 | -- | always 0 |
| +0x12 | 2 | g4_list_offset | byte offset into `g[4]` for the bit-priority/index list used by the bit selector |

Apply rule:

```text
new_value = (requested & editable_mask) | (fixed_mask & ~editable_mask)
```

---

## g[4] -- option/index byte-list pool

g[4] is the base pointer for compact one-byte code lists used by g[3] and
g[5] descriptors. Those descriptors store small offsets, not absolute
pointers:

- g[3] `g4_list_offset` selects `bit_count` bytes. In the checked firmware
  these bytes are bit codes for each logical bit slot.
- g[5] `g4_options_offset` selects `n_options` bytes. Byte `j` is the enum
  option code for logical option slot `j`.

Firmware resolves those lists as `globals[4] + offset`. For g[5],
`default_option` and `option_mask` are indexed by logical slot number, while
the g[4] byte list supplies the option code attached to each slot. The code
values are not required to be `0..n_options-1`: for example,
`ActiveTherapyProfile` uses codes `8..18`, and `ClimateControl` uses codes
`6,0`.

The first `0x00b9` bytes form the g[3]/g[5] byte-list pool. Many g[5] records
reuse common prefixes of the same pool. Offset 0 starts at the global
ascending byte sequence `0,1,2,...`; descriptors can also point into the
middle of that pool or into later explicit code sequences.

15.8.4.0 vid03 layout example:

| g[4] rel range | Owner | Contents |
|---------------:|-------|----------|
| `+0x000..+0x0b9` | g[3]/g[5] | bitfield and enum option/index byte lists |
| `+0x0b9..+0x0bc` | padding | zero padding |
| `+0x0bc..+0x174` | g[8] | short-name bucket `T` entries |
| `+0x174..+0x22c` | g[8] | short-name bucket `X` entries |
| `+0x22c..+0x2e0` | g[8] | short-name bucket `I` entries |
| `+0x2e0..+0x374` | g[17] | `AEV` label pointer table |
| `+0x374..+0x404` | g[16] | `PLD` stream signal table |
| `+0x404..+0x488` | g[8] | short-name bucket `F` entries |

The byte-list pool and T/X/I bucket offsets are stable across the checked
15.8.4.0 variants. The AEV/PLD tail is variant-dependent: AirCurve-style
variants have a larger PLD table and pack PLD before AEV, shifting the final
F bucket. Follow the owning pointers from g[8], g[16], and g[17] instead of
hard-coding tail offsets.

---

## g[5] -- enum DataItem descriptors

**Record stride:** 16 bytes

Backs `EnumDataItem` -- single-selection variables drawn from a fixed option
list (mode toggles, comfort selectors, sensitivity levels, profile pickers).
The descriptor stores an option-slot count and an offset into the g[4] enum
code-list pool.

| Offset | Size | Field | Description |
|--------|------|-------|-------------|
| +0x00 | 2 | flags | see [Flags field](#flags-field) |
| +0x02 | 2 | g4_options_offset | byte offset into `g[4]`; read `n_options` one-byte enum codes from there |
| +0x04 | 2 | owner_ref | see [owner_ref](#owner_ref) |
| +0x06 | 2 | factory_tag | common descriptor field; `0x0017` on all but one record |
| +0x08 | 1 | default_option | factory default logical option slot (0..`n_options-1`) |
| +0x09 | 1 | n_options | number of logical option slots; also the number of bytes read from the g[4] code-list pool |
| +0x0a | 2 | -- | always 0 |
| +0x0c | 4 | option_mask | bitmask of logical option slots enabled in this variant; slot `i` is selectable only if `(option_mask >> i) & 1` |

To decode an enum descriptor, read `n_options` bytes at
`globals[4] + g4_options_offset`. The byte at position `i` is the enum code
for logical option slot `i`; `option_mask` decides whether that slot is
available in the current variant.

---

## g[6] -- named var-id list headers

Seven 16-byte records.

| Offset | Size | Field |
|--------|------|-------|
| +0x00 | 4 | tag (NUL-terminated 3-char) |
| +0x04 | 4 | list_id / anchor id |
| +0x08 | 4 | var_id_list_ptr |
| +0x0c | 4 | count |

Observed tags: `BGL`, `DDO`, `DID`, `HST`, `MCA`, `MCF`, `TLP`.

The field at +0x04 is not an arithmetic base for the following list. For
example, `DDO` has +0x04 = `0x00a5`, but its first list entry is `0x0022`.
Treat it as a list identifier or anchor used by the consuming subsystem.

Known list roles:

| Tag | Count | Role |
|-----|------:|------|
| `BGL` | 6 | pressure/flow calibration coefficients (`PressureGain`, `PressureOffset`, `PressureMonitorGain`, `PressureMonitorOffset`, `FlowGain`, `FlowOffset`) |
| `DDO` | 64 | data-delivery/reporting variables: event/periodic payload handles, timestamp/status siblings, and storage/report state used with g[12], g[13], g[14], and g[19] |
| `DID` | 13 | identification profile variables: product code/name, serial, UUID, UDI, geography, hardware ids, and cellular product identity |
| `HST` | 163 | settings-history persistence variables: all therapy/comfort/environment/display/alarm/reminder settings, including inactive or hidden therapy modes |
| `MCA` | 1 | CAML broker/config blob (`CamlData`) |
| `MCF` | 1 | application-data blob (`ApplicationData`) |
| `TLP` | 40 | telemetry/cloud control variables: service endpoint/APN, data mode, broker/contact periods, OTA lifecycle fields, CAL/flight mode, and internal transport/log state |

The list counts above also match descriptor `owner_ref` membership. For
example, `BGL` owns six g[2] numeric calibration descriptors, `DID` owns
thirteen g[1] text/id descriptors, and `HST` spans g[1], g[2], g[3], and g[5]
settings descriptors.

`HST` is a 163-entry settings/history list and includes all therapy setting
var_ids, including inactive modes. The list is identical across all four
15.8.4.0 variants - variant availability comes from descriptor activity,
option masks, and SummaryRecord activation, not by removing entries here.

---

## g[7] -- PDL SettingsUnit header

`PDL` is a small `SettingsUnit` header. Only the first 12 bytes are the PDL
object. Later bytes in the same physical interval are owned by other globals
through explicit pointers.

| Offset | Size | Field |
|--------|------|-------|
| +0x00 | 4 | tag ("PDL\0") |
| +0x04 | 4 | list_ptr (43 x u16 var ids) |
| +0x08 | 4 | count (43) |

Firmware caches g[7], reads count at +0x08, and returns `list_ptr[index]` from
+0x04. Implemented in the `SettingsUnit` path at `0x08166ff8`, `0x08167014`,
`0x081676cc`, `0x081676d8`, `0x081676de`.

15.8.4.0 pointers:

| VID | g7 | list | count |
|----:|------|------|---:|
| 3 | `0x0802cf60` | `0x0802c160` | 43 |
| 7 | `0x0802d050` | `0x0802c180` | 43 |
| 10 | `0x0802d064` | `0x0802c170` | 43 |
| 12 | `0x0802cf68` | `0x0802c170` | 43 |

The 43-entry list is identical across all four 15.8.4.0 variants:

```text
00 0x032c REM            22 0x0277 MHR 
01 0x0279 ZSE            23 0x0278 MHS 
02 0x027b ZDT            24 0x0276 MHU 
03 0x027a ZDD            25 0x01bb LMS LastMachineServiceDateTime
04 0x0143 FW0            26 0x01be LPD
05 0x0146 FW1            27 0x01bd LI9
06 0x0149 FWC            28 0x0420 PTF
07 0x0141 FE0            29 0x0262 RCM
08 0x0144 FE1            30 0x025a MDM
09 0x0147 FE2            31 0x0263 RCT
10 0x035a BTU            32 0x025b MDT
11 0x00db BUC            33 0x0264 RCH
12 0x0476 XSS            34 0x025c MDW
13 0x03f1 LRE            35 0x0261 RCF
14 0x0431 RFP            36 0x0259 MDF
15 0x01b9 ZFE            37 0x00f2 DTU
16 0x018a ILS            38 0x00f1 DTD
17 0x045b SMN            39 0x0366 CCT
18 0x045c SVN            40 0x0458 ABU
19 0x0274 CUD LastTherapyUseDateTime  41 0x0347 AUP
20 0x0101 CED LastEraseDataDateTime   42 0x02be SET
21 0x027d PHM TherapyRunMeter
```

PDL is the `SettingsUnit` persistent data list -- a device-state var list. It
is not a therapy visibility table, and it is not the EDF schema (see
[g[16]](#g16----edf-stream-file-schemas) for that). In vid03 the bytes after
the PDL header are referenced by other structures and pack:

```text
+0x0c  CSL event-label pointer table (used by g[17])
+0x18  short-name bucket K payload (used by g[8])
+0x24  short-name bucket N payload (used by g[8])
+0x30  string/unit pool ("min.", "Mode", "cmH2O", "S.Mask", ...)
```

Strings such as `seconds`, `Ti.50`, `Ti.95`, `Ti.Max`, `Ti.2s` that appear
near g[7] are string-pool entries referenced by other tables and are not part
of the PDL object itself.

---

## g[8] -- short-name bucket headers

26-entry A-Z bucket header table. `var_tag3_to_id` at `0x0806a878` selects the
bucket from the first character, then scans 4-byte entries.

Bucket header (8 bytes):

| Offset | Size | Field |
|--------|------|-------|
| +0x00 | 4 | entries pointer |
| +0x04 | 4 | count |

Each entry (4 bytes):

| Offset | Size | Field |
|--------|------|-------|
| +0x00 | 2 | suffix (chars 2 and 3) |
| +0x02 | 2 | var_id |

---

## g[9] -- short-name reverse table

Linear var_id -> 3-char short tag pool. Functions at `0x08071086` and
`0x080710ba` use `g[9] + var_id * 3`. Contains all 1180 A-Z bucket short names
plus four underscore-prefixed internal tags (`_UD`, `_HU`, `_HR`, `_HS`) and
zero tail.

---

## g[10] -- per-mode variable registration

**Record stride:** 14 bytes, **Entry count:** 103.

| Offset | Size | Field |
|--------|------|-------|
| +0x00 | 2 | var_id |
| +0x02 | 11 | per-mode membership bytes |
| +0x0d | 1 | reserved / zero in observed rows |

The mode membership fields are bytes, not a packed bitmask. A non-zero byte
means the row's var_id belongs to that therapy mode, so each row stores eleven
membership bytes instead of a compact u16 mode mask.

| Byte offset | Mode |
|------------:|------|
| +0x02 | CPAP |
| +0x03 | AutoSet |
| +0x04 | HerAuto |
| +0x05 | Spont |
| +0x06 | ST |
| +0x07 | Timed |
| +0x08 | VAuto |
| +0x09 | ASV |
| +0x0a | ASVAuto |
| +0x0b | iVAPS |
| +0x0c | PAC |

Variant gating does not happen by adding or removing g[10] rows; rows are
identical across all four 15.8.4.0 variants. The active mode set is controlled
by descriptor activity bits, enum option masks, and SummaryRecord activation.

---

## g[11] -- record count for g[10]

Not a pointer. Scalar value `0x67` / 103.

---

## g[12] -- event/log definitions

Begins with 23 36-byte event/log records:

| Offset | Size | Field | Description |
|--------|------|-------|-------------|
| +0x00 | 4 | name_ptr | event/log collection name |
| +0x04 | 4 | code_ptr | 3-char code string (`ASE`, `APE`, etc.) |
| +0x08 | 4 | event_class | small class/enable mask; powers of two and `0x40` observed |
| +0x0c | 4 | period_or_limit | scheduler/reporting period or record limit, interpretation depends on class |
| +0x10 | 4 | record_kind | emitter record family; values match storage/event payload families, not var type |
| +0x14 | 4 | flags_a | packed flags; high bytes often `0x0100..0x0101` |
| +0x18 | 4 | buffer_or_mask | buffer/route mask style value |
| +0x1c | 4 | retention_or_batch | small emitter parameter; `4`, `10`, and `20` observed |
| +0x20 | 4 | packed_ref | high16 source/ref (`0x7fff` = none); low16 event/report family id |

Examples:

| Tag | Name |
|-----|------|
| ASE | `_ACOUSTIC_SIGNATURE_EVENT` |
| APE | `DiagnosticExceptionEvents-AlarmAppErrors` |
| ADE | `alarmDiagnosticEvents` |
| AAE | `alarmEvents` |
| SHE | `_SETTINGS_HISTORY_EVENT` |
| BAT | `_TOUCH_ACTIVITY_EVENT` |

Bytes after the 23 records contain short-name bucket storage and packed
code/id data. Do not treat all of g[12] as homogeneous 36-byte event records.

The first two pointers enumerate event families. The remaining words are
stable scheduler/emitter parameters:

| Field | Observed values / pattern |
|-------|---------------------------|
| event_class | `1`, `4`, `8`, `16`, `64`; behaves like a broad event/storage class |
| period_or_limit | values such as `10`, `90`, `200`, `365`, `1000`, `2000`, `4000`, `6000`, `8000`, `16000` |
| record_kind | `7`, `8`, `9`, `11`, `51`, and `2044`; groups payload layout families |
| flags_a | packed little-endian flag words such as `0x01000002`, `0x01000201`, `0x01010101` |
| buffer_or_mask | `0x80`, `0x100`, `0x200`, `0x400`, `0x800` |
| retention_or_batch | mostly `10`; `4` on alarm/app diagnostic rows; `20` on GUI activity |
| packed_ref | usually `0x7fff00NN`; `_RPC_ACTIVITY_EVENT` and `_TOUCH_ACTIVITY_EVENT` use non-`0x7fff` high halves |

Preserve these fields byte-for-byte during patching until all event emitter
consumers are traced.

---

## g[13] -- event route table

The g[13] root points to an event route table. In the checked 15.8.4.0
images, the table occupies 21 6-byte route records (`0x7e` bytes), followed
by 2 bytes of zero padding to the next `0x80` boundary.

Route record (6 bytes):

| Offset | Size | Field |
|--------|------|-------|
| +0x00 | 2 | event_index (into g[12]) |
| +0x02 | 2 | subindex |
| +0x04 | 2 | route |

Consumed alongside g[12] via `FUN_0816a5f4` ->
`FUN_0816ac18(ctx, g[12], 0x17, g[13], 0x15)`.

Observed routes:

| Event | Tag | Name | Sub | Route |
|------:|-----|------|-----|------:|
| 5 | CAV | CellularActivityEvents | 0 | 6 |
| 11 | GAE | GUIActivityEvents | 0..4 | 6 |
| 16 | RNV | TherapyEvents-RespiratoryEvents | 2..4 | 3 |
| 16 | RNV | (cont.) | 6..7 | 4 |
| 17 | RAE | `_RPC_ACTIVITY_EVENT` | 0 | 6 |
| 22 | BAT | `_TOUCH_ACTIVITY_EVENT` | 0..5 | 6 |

At `g[13]+0x80`, the 64-entry `DDO` var-id list payload begins. That payload
is not identified by the g[13] route table; it is identified by the `DDO`
header in g[6], whose `list_ptr` points to `g[13]+0x80`.

Across the checked 15.8.4.0 variants, g[13] spans `0x100` bytes and
g[6].`DDO.list_ptr - g[13] == 0x80`.

---

## g[14] -- periodic/session collections

**Record stride:** 0x34 bytes, **Entry count:** 7.

| Offset | Size | Field |
|--------|------|-------|
| +0x00 | 4 | tag string ptr |
| +0x04 | 4 | period_ms |
| +0x08 | 4 | window_or_period |
| +0x0c | 4 | buffer_size |
| +0x10 | 4 | record_size |
| +0x14 | 4 | collection_param_a |
| +0x18 | 4 | collection_param_b |
| +0x1c | 4 | collection_kind |
| +0x20 | 4 | flags |
| +0x24 | 2 | active_bit |
| +0x26 | 2 | reserved_zero |
| +0x28 | 1 | signal_count |
| +0x29 | 3 | reserved_zero |
| +0x2c | 4 | signal_var_ids ptr (u16[]) |
| +0x30 | 4 | signal_metadata ptr (signal_count x 0x30) |

Signal metadata record (0x30 bytes):

| Offset | Size | Field | Description |
|--------|------|-------|-------------|
| +0x00 | 8 | min_value (f64) | lower reporting/source bound |
| +0x08 | 8 | max_value (f64) | upper reporting/source bound |
| +0x10 | 8 | resolution (f64) | reporting/source quantization; often but not always equal to descriptor step |
| +0x18 | 8 | scale (f64) | source/report scale; `1.0` in most rows |
| +0x20 | 4 | class_flags | small class/packing flags (`2`, `4`, `8` observed) |
| +0x24 | 4 | reserved_zero | always zero in checked rows |
| +0x28 | 4 | transform | small transform/filter id (`0`, `1`, `2`, `0x101`, `0x102` observed) |
| +0x2c | 4 | reserved_zero | always zero in checked rows |

Code support:

| Function | Behavior |
|----------|----------|
| `FUN_0818c8ce` | iterates 7 records, skips byte +0x28 == 0, reads var_ids from `*(record+0x2c)` |
| `FUN_081742d0` | checks byte +0x28 and a disable/active bit derived from +0x24 |

Decoded rows (common to vid03/07/10/12):

| Tag | period_ms | window | buffer | record_size | param_a | param_b | kind | flags | active_bit | signals |
|-----|----------:|-------:|-------:|------------:|--------:|--------:|-----:|------:|-----------:|--------:|
| CSF | 600000 | 600 | 2048 | 200 | 10 | 10 | 4 | `0x00ca0001` | 24 | 4 |
| TIP | 2000 | 600 | 512 | 40 | 1 | 10 | 3 | `0x00210101` | 27 | 1 |
| MLK | 2000 | 600 | 512 | 40 | 1 | 10 | 3 | `0x00210101` | 11 | 1 |
| MPD | 160 | 600 | 512 | 40 | 1 | 10 | 3 | `0x00210101` | 12 | 1 |
| RFD | 160 | 600 | 512 | 40 | 1 | 10 | 3 | `0x00210101` | 10 | 1 |
| NRF | 60000 | 600 | 2048 | 300 | 20 | 10 | 3 | `0x00210101` | 9 | 11 |
| APD | 600000 | 600 | 512 | 300 | 1 | 2 | 4 | `0x7fff0001` | 28 | 1 |

This table is not the EDF file schema. It describes runtime periodic/session
collections that feed reporting and cloud/DDO paths. The pointed var-id lists
name source DataItems; the 0x30-byte records at `signal_metadata ptr` are
per-signal runtime metadata.

`collection_param_a`, `collection_param_b`, and `collection_kind` are stable
across the downloaded 15.8.4.0 variants. `reserved_zero` bytes are zero in
every checked row.

---

## g[15] -- STR.edf SummaryRecord schema

The `STR.edf` literal file name lives in application code (`sdc:0:\STR.edf` at
`0x081859c0`), referenced from `FUN_0818568e` and `FUN_08185838`. The schema
itself comes from g[15]: `FUN_08185a20` reads g[15] and feeds it into the
SummarySync/EDF construction path.

### Header

| Offset | Size | Value |
|--------|------|-------|
| +0x00 | 2 | `0x016d` |
| +0x02 | 2 | `0x0014` |
| +0x04 | 2 | record_count = `0x00c0` (192) |
| +0x06 | 2 | special_key_count = 3 |
| +0x08 | 4 | `SummaryRecord*` = `0x08025688` |
| +0x0c | 4 | special_key_table_ptr |

The `SummaryRecord` table is not physically after this header; in the checked
15.8.4.0 images it starts at `0x08025688`, inside the g[2] physical interval.
The special-key table pointer also points elsewhere (`0x0802c970` in vid03,
inside the g[16] physical interval), where the three padded ASCII keys
`XA5`, `XB3`, and `ZZ6` are stored. The bytes immediately after the 16-byte
g[15] header are a small inline auxiliary key map: vid03 stores four
two-letter code plus var_id pairs (`PA`/`WPA`, `PM`/`WPM`, `UC`/`WUC`,
`UP`/`WUP`), followed by EDF label strings referenced by SummaryRecord rows.

### SummaryRecord layout

**Record stride:** 36 bytes, **Entry count:** 192, **start:** `0x08025688`.

| Offset | Size | Field | Description |
|--------|------|-------|-------------|
| +0x00 | 4 | field_id | output/order id |
| +0x04 | 4 | kind | controls record interpretation |
| +0x08 | 2 | var_a | selected when `kind >= 3` |
| +0x0a | 2 | var_b | selected when `kind < 3` |
| +0x0c | 2 | selector_a | usually `0x7fff` in checked rows |
| +0x0e | 2 | selector_b | statistic/filter selector (`0`, `5`, `50`, `70`, `95`, `100`, ...) |
| +0x10 | 4 | logical_scale (f32) | raw -> logical value scale |
| +0x14 | 1 | record_class | 0 = setting/snapshot, 1 = summary/status/measurement |
| +0x15 | 1 | active | SummarySync counts and writes only when non-zero |
| +0x16 | 2 | reserved16 | always 0 in active rows |
| +0x18 | 4 | edf_label | ASCII string ptr -> EDF signal label |
| +0x1c | 4 | edf_unit | ASCII string ptr -> EDF physical unit |
| +0x20 | 4 | edf_output_scale (f32) | logical -> EDF int16 packing scale |

`logical_scale` and `edf_output_scale` are independent: firmware applies
`logical_scale` for runtime value handling and `edf_output_scale` when packing
int16 EDF samples.

`record_class` is meaningful for active rows and for inactive rows after their
metadata is hydrated from an official active variant. Do not infer semantics
from stale inactive-row tails alone. `0x00` marks setting/snapshot rows:
mostly `S.*` one-shot settings plus `Mode` / `ActiveTherapyProfile`. `0x01`
marks summary/status/measurement rows: duration, AHI/HI/AI/OAI/CAI/UAI/RIN/CSR,
percentile tuples for SpO2, MaskPress, Leak, MinVent, RespRate, TidVol,
IERatio, Ti, SpO2Thresh, the `HeatedTube`/`Humidifier` connectivity flags, and
the n/a placeholder at `field_id=0`. The flag is an emitter hint for
snapshot-setting vs. session-aggregate output.

Important exception: `record_class` is not derived from `kind`. `HeatedTube`
and `Humidifier` are `kind=0` rows but have `record_class=1`.

Code support:

| Function | Behavior |
|----------|----------|
| `FUN_081468a6` | if `kind < 3`, uses u16 at +0x0a; else u16 at +0x08 |
| `FUN_081829d4` | iterates and counts only records where byte +0x15 is non-zero |
| `summary_record_populate_values` | populates output from active set |

Active SummaryRecord counts:

| VID | Active |
|----:|---:|
| 3  | 74 |
| 7  | 92 |
| 10 | 93 |
| 12 | 70 |

Representative active families:

| VID | Family |
|----:|--------|
| 3 | AutoSet-*, HerAuto-*, AutoSetComfort, Summary-ReraIndex, CSD/CSR-ish |
| 7 | Spont-*, VAuto-*, SpontTriggerPercentage, SpontCyclePercentage, IeRatio-*, InspiratoryDuration-* |
| 10 | Spont-*, ST-*, Timed-*, IeRatio-*, InspiratoryDuration-* |
| 12 | ASV-*, ASVAuto-* |

Matching EDF label strings in nearby pools:

```text
S.VA.StartPress  S.VA.MaxIPAP  S.VA.MinEPAP  S.VA.PS  S.VA.TiMax  S.VA.TiMin
S.VA.Trigger     S.VA.Cycle
S.S.StartPress   S.S.IPAP      S.S.EPAP      S.S.EasyBreathe
S.S.RespRateEn   S.S.RiseEnable S.S.RiseTime  S.S.TiMax  S.S.TiMin
S.S.Trigger      S.S.Cycle
IERatio.50  IERatio.95  IERatio.Max  Ti.50  Ti.95  Ti.Max
SpontTrig%  SpontCyc%
```

---

## g[16] -- EDF stream file schemas

Three stream/file headers (BRP, SA2, PLD).

Do not confuse `PLD` here with g[7] `PDL`. `PLD` is the 2-second EDF stream
file schema containing pressure/leak/respiratory signals. `PDL` is the
SettingsUnit persistent data list header.

### StreamFileHeader

| Offset | Size | Field |
|--------|------|-------|
| +0x00 | 2 | period_ms |
| +0x02 | 2 | samples_per_60s |
| +0x04 | 4 | signal_count |
| +0x08 | 4 | tag_string_ptr |
| +0x0c | 4 | signal_record_ptr |

### StreamSignal

| Offset | Size | Field |
|--------|------|-------|
| +0x00 | 4 | id |
| +0x04 | 4 | name ptr |
| +0x08 | 4 | unit ptr |
| +0x0c | 4 | scale (f32) |

### Stable signals (all variants)

| File | period_ms | samples | count | Signals |
|------|----------:|--------:|------:|---------|
| BRP | 40 | 1500 | 2 | Flow.40ms (L/s, scale 500), Press.40ms (cmH2O, scale 50) |
| SA2 | 1000 | 60 | 2 | Pulse.1s (bpm, scale 1), SpO2.1s (%, scale 1) |

### Variable PLD content

vid03 base set (count 9):

```text
MaskPress.2s   cmH2O   scale 50
Press.2s       cmH2O   scale 50
EprPress.2s    cmH2O   scale 50
Leak.2s        L/s     scale 50
RespRate.2s    bpm     scale 5
TidVol.2s      L       scale 50
MinVent.2s     L/min   scale 8
Snore.2s       --      scale 50
FlowLim.2s     --      scale 100
```

| VID | PLD count | Delta from vid03 |
|----:|----------:|------------------|
| 3 | 9 | -- |
| 7 | 11 | + IERatio.2s (%, 1), Ti.2s (s, 50) |
| 10 | 10 | drops FlowLim.2s; + IERatio.2s, Ti.2s |
| 12 | 10 | + TgtVent.2s (L/min, 8) |

EDF/signal differences are not limited to STR.edf -- PLD metadata also varies.

---

## g[17] -- event label tables

Three 28-byte label table headers. Labels are semantically identical across
the four-dump set; only pointers and one CSL flag bit differ.

| Offset | Size | Field |
|--------|------|-------|
| +0x00 | 2 | event_bound (EventQueue bounds check) |
| +0x02 | 2 | label_count |
| +0x04 | 4 | record_size |
| +0x08 | 4 | label_ptr_stride |
| +0x0c | 4 | flags |
| +0x10 | 4 | tag (`EVE` / `AEV` / `CSL`) |
| +0x14 | 4 | enabled_constant |
| +0x18 | 4 | label_table (char**) |

`label_ptr_stride` is `4` in all three tables, matching the 32-bit entries in
the `char**` label table. `enabled_constant` is `1` in all observed rows.

Observed tables:

| Tag | Labels |
|-----|--------|
| EVE | 6: "", Hypopnea, Central Apnea, Obstructive Apnea, Apnea, Arousal |
| AEV | 37: High Leak, Non Vented Mask, Low Min Ventilation, Apnea, Blocked Tube, Tube Disconnected, Tub Disconnected, Alarm Module Comms Error, Motor Stall HW, Slow Over Pressure, Fast Over Pressure, Over Temperature, Over Voltage, Motor Stall SW, Motor HW Fault, Motor Sticky, Motor FETs, Motor ESD, Motor HW Mitigation IC, No Flow Data, Settings Reset, Calibration Reset, Pressure Stuck High/Low/Mid, Flow Sensor Stuck Low/High, Pressure Sensor Drift, Pressure Sensors Plausibility, Implausible Supply Voltage, HW Fault Detection Circuitry, Self Test Initiated, Indicator Self Test Pass/Fail, Supercapacitor Self Test Pass/Fail, Alarm Mute |
| CSL | 3: "", CSR Start, CSR End |

CSL flags:

| VID | Flags |
|----:|------|
| 3 | `0x0101` |
| 7,10,12 | `0x0100` |

---

## g[18] -- RPC JSON node permission table

Begins with the CDX/RPC JSON node permission table. Direct code at
`0x0814e814` loads `g[18] + node_id * 2` and reads the low byte as the
permission/visibility flag.

```text
permission_offset = g[18] + node_id * 2
```

In the current APPL metadata, node ids run up to 141, so the logical table is
the first 144 two-byte entries. Observed values in those entries:

| Value | Meaning |
|-------|---------|
| `0x0000` | hidden |
| `0x0001` | visible (low byte = 1) |
| `0x0100` | hidden, high byte set |
| `0x0101` | visible, high byte set |

Profile and feature CDX nodes such as `TherapyProfiles`, individual therapy
profiles, and feature nodes become visible when their low byte is set to `1`.
This is a separate gate from descriptor ACT bits and enum option masks.

After the permission table, the same physical interval contains g[8]
short-name bucket payloads (`M`, `R`, `H`, and `C` in vid03). Those payloads
are reached through the g[8] bucket headers, not through the g[18] permission
table.

### Discovering node IDs

Node IDs are not stable across S11 firmware versions. They are discovered from
CDX metadata triples:

| Offset | Size | Field |
|--------|------|-------|
| +0x00 | 4 | node_name_string_ptr |
| +0x04 | 4 | "!<node_id>" string_ptr |
| +0x08 | 4 | `0x00007fff` |

### Therapy profile node IDs

| Node | 14.8.3.0 | 15.8.4.0 |
|------|---------:|---------:|
| ASVAutoProfile | `0x61` | `0x63` |
| ASVProfile | `0x62` | `0x64` |
| AutoSetForHerProfile | `0x63` | `0x65` |
| AutoSetProfile | `0x64` | `0x66` |
| CpapProfile | `0x65` | `0x67` |
| PACProfile | `0x66` | `0x68` |
| STProfile | `0x67` | `0x69` |
| SpontProfile | `0x68` | `0x6a` |
| TimedProfile | `0x69` | `0x6b` |
| VAutoProfile | `0x6a` | `0x6c` |
| iVAPSProfile | `0x6b` | `0x6d` |

### Feature profile node IDs

| Node | 14.8.3.0 | 15.8.4.0 |
|------|---------:|---------:|
| ConfirmStopFeature | `0x4d` | `0x4f` |
| HeightFeature | `0x51` | `0x53` |
| RampDownFeature | `0x55` | `0x57` |
| TherapyLEDFeature | `0x5d` | `0x5f` |

### Alarm profile nodes (kept disabled)

| Node | 15.8.4.0 |
|------|---------:|
| AlarmProfiles | `0x42` |
| AlarmVolume | `0x43` |
| ApneaAlarm | `0x44` |
| HighLeakAlarm | `0x45` |
| LowMinuteVentAlarm | `0x46` |
| NonVentedMaskAlarm | `0x47` |

---

## g[19] -- DDO/reporting source list

Reporting/DDO source header and reporting code/string pool. Startup at
`0x08167dcc` caches g[19]; consumer at
`0x08167eca` reads:

| Offset | Size | Field |
|--------|------|-------|
| +0x00 | 4 | var_id_list ptr (u16[]) |
| +0x04 | 1 | count |

Iterates those var ids, constructs `DataItem`s, checks visibility, emits
current values. In vid03 the count is 29 and the list maps event/collection
codes to internal DDO variables:

```text
ASE -> CP1   AEE -> DOP   ELV -> DTE   GAE -> DDS   REE -> SVA   SCE -> DAV
APE -> CP2   CAV -> DMM   FAE -> DDE   HEE -> DAS   RNV -> DSV   DAE -> DUC
ADE -> DDN   SCV -> DUE   XSE -> DDY   HEV -> DCA   RAE -> DMA   SRE -> DEG
AAE -> DDP   DAF -> DEE   MEV -> DGA   SHE -> DTP   BAT -> DEI   CSF -> DRF
TIP -> DMP   MLK -> DML   MPD -> DIP   RFD -> ADP   NRF -> DCP
```

After the 8-byte header, g[19]'s own pool contains 4-byte code tags (`ASE`,
`APE`, `ADE`, ...), units, and reporting strings (`L/s`, `bpm`, `AHI`, `BRP`,
`SA2`, `PLD`, `EVE`, `AEV`, `CSL`, ...). In the checked 15.8.4.0 images this
string pool ends at g[19] + `0x104`.

The next 14 bytes are pointer-owned u16 list payloads: g[14].`TIP`,
g[14].`MLK`, g[14].`MPD`, g[14].`RFD`, g[14].`APD`, g[6].`MCA`, and
g[6].`MCF`. The long erased run begins after those lists. Treat it as
allocation space only if the CONF CRC and all pointers are updated carefully.

---

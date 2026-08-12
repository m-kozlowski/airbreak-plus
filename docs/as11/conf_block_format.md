# Air11 CONF Block Format

Reference for the Air11 CONF block layout, globals[] master table, var-id
dispatch, descriptor record shapes, and per-table semantics.

## Table of contents

- [globals[] map](#globals-map)
- [Runtime consumers](#runtime-consumers)
- [Conventions](#conventions)
- [Structure families](#structure-families)
- [DataItem descriptor selection](#dataitem-descriptor-selection)
- [Flags field](#flags-field)
- [Common DataItem descriptor fields](#common-dataitem-descriptor-fields)
- [Data rule callbacks](#data-rule-callbacks)
- [g[0] -- CONF header](#g0----conf-header)
- [g[1] -- volatile-text DataItem descriptors](#g1----volatile-text-dataitem-descriptors)
- [g[2] -- numeric DataItem descriptors](#g2----numeric-dataitem-descriptors)
- [g[3] -- bitfield DataItem descriptors](#g3----bitfield-dataitem-descriptors)
- [g[4] -- bitfield GUI selection-order pool](#g4----bitfield-gui-selection-order-pool)
- [g[5] -- enum DataItem descriptors](#g5----enum-dataitem-descriptors)
- [g[6] -- external-NOR SettingsGroup schemas](#g6----external-nor-settingsgroup-schemas)
- [g[7] -- PDL backup-SRAM snapshot](#g7----pdl-backup-sram-snapshot)
- [g[8] -- short-name bucket headers](#g8----short-name-bucket-headers)
- [g[9] -- short-name reverse table](#g9----short-name-reverse-table)
- [g[10] -- per-mode baseline visibility](#g10----per-mode-baseline-visibility)
- [g[11] -- record count for g[10]](#g11----record-count-for-g10)
- [g[12] -- event spool definitions](#g12----event-spool-definitions)
- [g[13] -- EventNotification payload overrides](#g13----eventnotification-payload-overrides)
- [g[14] -- periodic collections](#g14----periodic-collections)
- [g[15] -- STR.edf SummaryRecord schema](#g15----stredf-summaryrecord-schema)
- [g[16] -- EDF stream file schemas](#g16----edf-stream-file-schemas)
- [g[17] -- event label tables](#g17----event-label-tables)
- [g[18] -- RPC JSON node permission table](#g18----rpc-json-node-permission-table)
- [g[19] -- ConfigurationProfiles change-watch list](#g19----configurationprofiles-change-watch-list)

---

## globals[] map

| Global | Meaning |
| ---: | ------- |
| g[0] | CONF header: product/platform, variant id, and build/data-model strings |
| g[1] | volatile-text `DataItem` descriptors |
| g[2] | numeric `DataItem` descriptors |
| g[3] | bitfield `DataItem` descriptors |
| g[4] | GUI bitfield-message selection order referenced by g[3] descriptors |
| g[5] | enum `DataItem` descriptors |
| g[6] | external-NOR `SettingsGroup` schemas (`BGL.set`, `DDO.set`, `DID.set`, `HST.set`, `MCA.set`, `MCF.set`, `TLP.set`) |
| g[7] | `PDL` backup-SRAM snapshot definition |
| g[8] | A-Z short-name bucket headers (3-char tag -> var_id) |
| g[9] | linear var-id -> 3-char short-tag pool |
| g[10] | per-mode baseline visibility rows |
| g[11] | scalar count for g[10] |
| g[12] | event spool definitions |
| g[13] | per-event `EventNotification` payload rules |
| g[14] | periodic collection schemas (`CSF`, `TIP`, `MLK`, `MPD`, `RFD`, `NRF`, `APD`) |
| g[15] | `STR.edf` `SummaryRecord` schema header |
| g[16] | EDF stream file schemas (`BRP`, `SA2`, `PLD`, `TCV`) |
| g[17] | event label tables (`EVE`, `AEV`, `CSL`) |
| g[18] | RPC JSON node permission table |
| g[19] | `ConfigurationProfiles` change-watch list (14.8.3.0 and later) |

---

## Runtime consumers

| Roots | Primary consumer | Relationship |
|-------|------------------|--------------|
| g[0] | identification/profile services | supplies platform, variant, build, and data-model identity |
| g[1], g[2], g[3], g[5] | `DataItemFactory` | maps each var ID to its runtime DataItem type and descriptor |
| g[4] | bitfield GUI/rule selection | orders candidate bits referenced by g[3] without changing the stored mask |
| g[6] | external-NOR settings storage | serializes active members of named `SettingsGroup` schemas into `/SETTINGS/*.set` |
| g[7] | power-loss state storage | serializes the PDL DataItem set into backup SRAM with CRC |
| g[8], g[9] | short-name resolver | maps three-character tags to var IDs and var IDs back to tags |
| g[10], g[11] | therapy-mode visibility updater | applies the active MOP column as baseline DataItem visibility |
| g[12], g[13] | event queue, spool files, and live event JSON | defines event storage and per-event JSON trailing payloads |
| g[14] | periodic-data sampler and spool writer | defines sampling, block closure, retention, compression, and source DataItems |
| g[15] | long-term summary and STR writer | defines retained therapy-day limits and STR rows |
| g[16] | sampled EDF writer | defines BRP, SA2, PLD, and TCV sampled-signal schemas |
| g[17] | EDF annotation writer | maps event values to EVE, AEV, and CSL annotation labels |
| g[18] | RPC profile JSON schema | independently gates node reads and writes |
| g[19] | configuration-profile change tracker | selects the DDO values that trigger a new configuration report |

---

## Conventions

- `g[n]` means `globals[n]`, the nth 32-bit entry in the CONF master table.
- Record-table offsets such as `+0x0c` are relative to the start of that
  record, not the start of the CONF block.
- File offsets such as `0x02d040` refer to a full firmware image with CONF at
  file offset `0x020000`. Runtime flash addresses use the `0x080xxxxx` form.
- Raw example bytes are shown in file order. Multi-byte fields decode as
  little-endian values.
- Var IDs are firmware `DataItem` IDs, but they are **version-local**. They
  are assigned by descriptor array order and drift when records are inserted
  or removed. Cross-version identity uses the three-letter tag (`MOP`, `LAN`,
  etc.) or RPC long name. RPC may expose long names such as
  `ActiveTherapyProfile` and underscore aliases such as `_MOP`; bare
  three-letter tags are internal names.
- [Variable reference](var_reference.tsv) lists variables and their
  release-specific var IDs for 14.8.3.0, 15.8.4.0, 16.8.5.0, and 17.8.6.0.
- Record layouts describe the structure shared by the listed firmware
  versions. Counts, addresses, IDs, masks, and example values belong to the
  version named in the adjacent table or example.

---

## Structure families

CONF roots use the following structure families and extent rules:

| Family | Roots | Extent rule |
|--------|-------|-------------|
| Descriptor array | g[1], g[2], g[3], g[5] | APPL dispatch count multiplied by record stride |
| Byte pool | g[4] | maximum `selection_order_offset + bit_count` referenced by g[3] |
| Fixed table with companion count | g[10] | g[11] multiplied by record stride |
| Fixed table | g[6], g[13] | fixed record count multiplied by record stride |
| Table with APPL-defined count | g[12], g[14], g[16], g[17] | consumer count multiplied by record stride |
| Header with referenced data | g[7], g[15], g[19] | header size; decode referenced objects through their pointer and count fields |
| Bucket headers | g[8] | 26 headers; each header carries its own entry pointer and count |
| Var-id indexed table | g[9] | number of DataItem IDs multiplied by three bytes |
| Node-id indexed table | g[18] | number of RPC node IDs multiplied by two bytes |

---

## DataItem descriptor selection

DataItem var IDs address the descriptor arrays as one contiguous sequence:

```text
g[1] base = 0
g[2] base = g[1] base + g[1] count
g[3] base = g[2] base + g[2] count
g[5] base = g[3] base + g[3] count

record_index = var_id - selected_array_base
```

Descriptor counts are release-specific. Three-letter tags and RPC long names
provide cross-release variable identity.

---

## Flags field

The u16 at `+0x00` of every g[1], g[2], g[3], and g[5] descriptor contains
the initial DataItem flags. Some bits describe immutable capabilities; others
seed mutable runtime shadow state.

| Bit | Mask | Name | Meaning |
|----:|------|------|---------|
| 0 | `0x0001` | `ACTIVE` | Item participates in normal use, settings loading, and writes. Factory dispatch is independent of this bit. |
| 1 | `0x0002` | `VISIBLE` | Baseline visible state. Effective visibility also depends on runtime shadow state. |
| 2 | `0x0004` | `MODE_BOUND` | Item participates in mode-dependent GUI binding. This is independent of visibility. |
| 3 | `0x0008` | `SIGNED` | Selects signed numeric conversion and serialization. g[2] default/min/max storage is always signed i32. |
| 4 | `0x0010` | `INHIBITED` | Suppresses runtime value availability without clearing the stored value. |
| 5 | `0x0020` | `HAS_VALUE` | The runtime value storage has been initialized. This bit does not by itself make the item available. |
| 6 | `0x0040` | `UPDATE_LOCK` | Blocks non-forced value commits and changes to `INHIBITED`. It is not part of the availability predicate. |
| 7 | `0x0080` | `RAW_NUMERIC` | g[2] input bypasses step quantization and is saturated to the active bounds. |
| 8 | `0x0100` | `MONITORED` | Runtime change monitoring is enabled; used by `ValueChange` subscriptions. |
| 9 | `0x0200` | `RPC_EXPOSED` | Item may be resolved and formatted through the RPC/name layer. |
| 10 | `0x0400` | `RPC_WRITABLE` | RPC `Set` may write the item. Firmware may change this bit at runtime. |
| 11 | `0x0800` | `PERSISTENT_SETTING` | Item belongs to the persistent-setting apply cohort used by settings-file loading, reset-to-default, and callback reapplication. |

Bits 12 through 15 have no defined use in the documented layouts.

The value-bearing availability predicate is:

```text
is_active() && HAS_VALUE && !INHIBITED
```

`HAS_VALUE` records that a producer or settings loader has supplied a value.
`INHIBITED` can temporarily hide that value from consumers while retaining it.
`UPDATE_LOCK` protects both the retained value and the inhibited state: a
non-forced commit or inhibit-state change is ignored while the lock is set,
while a forced operation still takes effect.

---

## Common DataItem descriptor fields

The fields below have the same layout and meaning in g[1], g[2], g[3], and
g[5].

| Offset | Size | Field | Meaning |
|--------|-----:|-------|---------|
| +0x00 | 2 | flags | active/visibility/runtime seed bits; see [Flags field](#flags-field) |
| +0x02 | 1 | data_rule_id | callback index in the APPL data-rule registry; zero means no callback |
| +0x03 | 1 | reserved | zero |
| +0x04 | 2 | linked_counter_index | g[2] descriptor index incremented when this item is committed; `0x7fff` means none |
| +0x06 | 1 | change_event_queue_index | g[12] queue receiving the item change event; the g[12] count is the no-queue sentinel for that release |
| +0x07 | 1 | reserved | zero |

Membership in a persistent settings group is defined by the var-id lists
referenced by g[6], not by these descriptor fields.

---

## Data rule callbacks

APPL maintains a fixed-size runtime registry indexed by `data_rule_id`. Its
constructor initializes every slot to an application-error callback;
subsystems replace the nonzero slots they own during startup. The IDs form a
release-specific interface between CONF descriptors and APPL code; they are
not pointers or indexes into another CONF root.

Normal DataItem commits process a rule in this order:

1. validate and store the new value;
2. increment `linked_counter_index`, when present;
3. invoke the callback selected by `data_rule_id`;
4. publish the monitored value change.

The callback therefore observes the committed value and can update dependent
bounds, values, or visibility before change processing finishes. Multiple
DataItems may select the same callback. A zero ID skips this step. A nonzero ID
whose callback was not registered reports a firmware application error.

For example, `ActiveTherapyProfile` (`MOP`) selects rule `0x34`. Its callback
applies the selected therapy mode's g[10] visibility column and then recomputes
the additional mode-dependent setting visibility.

This mechanism is independent of `change_event_queue_index`: a data rule
updates firmware state synchronously, while the queue index selects an event
spool for the committed change.

`as11_descriptors.py firmware.bin data-rules` reconstructs the APPL callback
map and lists the CONF variables assigned to each rule.

---

## g[0] -- CONF header

g[0] points to the start of the CONF block and supplies platform and build
identifiers.

| Offset | Size | Field | Description |
|--------|------|-------|-------------|
| +0x00 | 4 | DataVersionIdentifier (`_PVD`) | data/configuration schema generation |
| +0x04 | 4 | PlatformIdentifier (`_MID`) | platform identifier; 46 on Air11 |
| +0x08 | 4 | AID | application identity component |
| +0x0c | 4 | VariantIdentifier (`_VID`) | product variant |
| +0x10 | 4 | RegionIdentifier (`_RID`) | region identity component |
| +0x14 | 4 | ProfileVariationIdentifier ptr | UUID-format string |
| +0x18 | 16 | platform family text | "SIMPLICITY" |
| +0x28 | 16 | default ProductCode | copied to `PCD` when product identity is empty or reset |
| +0x38 | 16 | default ProductName | copied to `PNA` when product identity is empty or reset |
| +0x48 | 32 | reserved | zero |
| +0x68 | 10 | configuration build hash | NUL-terminated, e.g. "791777c3b" |
| +0x72 | 11 | data model version | NUL-terminated, e.g. "v2.15.2" |
| +0x7d | 11 | data model build hash | NUL-terminated, e.g. "7fc2c6467" |
| +0x88 | 120 | unused | erased (`0xff`) |

The header occupies `0x100` bytes. At `CONF+0x100`, a four-byte Thumb veneer
returns the pointer stored at `CONF+0x104`; that pointer addresses the
`globals[]` master table. Firmware 11.8.0.1 has 19 roots (`g[0]..g[18]`);
14.8.3.0 and later have 20 (`g[0]..g[19]`).

| APPX release | `_PVD` | `_MID` | `_AID` | Data model | Configuration hash | Data-model hash |
|--------------|-------:|-------:|-------:|------------|--------------------|-----------------|
| 8.0.1 | 11 | 46 | 0 | `v2.2.1` | `d43514eda` | `39783838c` |
| 8.3.0 | 14 | 46 | 0 | `v2.5.0` | `81371a5ed` | `2f569f795` |
| 8.4.0 | 15 | 46 | 0 | `v2.15.2` | `791777c3b` | `7fc2c6467` |
| 8.5.0 | 16 | 46 | 0 | `v2.15.3` | `9cd562102` | `53c1a73b8` |
| 8.6.0 | 17 | 46 | 0 | `v2.17.1` | `6c36d978a` | `e183d56e9` |

### Runtime composite identifiers

The runtime RPC composes several identifiers from the header fields above:

| RPC field | Value (vid03 15.8.4.0) | Composition |
|-----------|------------------------|-------------|
| `_FGT` | `2e_M46_V3` | `<MID-hex>_M<MID-decimal>_V<VID>` |
| `ProfileVariantIdentifier` | `00000000-0000-3000-8000-000015046003` | UUID with trailing `<PVD:02d><MID:03d><VID:03d>` |
| `ApplicationIdentifier` | `SW04600.15.8.4.0.791777c3b` | `SW<MID:03d><AID:02d>.<APPX version and hash>` |
| `DataModelVersionIdentifier` | `v2.15.2.7fc2c6467` | `<+0x72>.<+0x7d>` |
| `ConfigurationIdentifier` | `CF04600.15.03.00.791777c3b` | `CF<MID:03d><AID:02d>.<PVD:02d>.<VID:02d>.<RID:02d>.<+0x68>` |

The `04600` token is `PlatformIdentifier=046` followed by `AID=00`.

---

## g[1] -- volatile-text DataItem descriptors

**Record stride:** 10 bytes

Backs `VolatileTextDataItem` -- short text/identifier variables (CID, SID,
BID, PNA, SRN, PtAccess strings, etc.). The runtime value is a string buffer
in SRAM; this descriptor only describes its shape.

| Offset | Size | Field | Description |
|--------|------|-------|-------------|
| +0x00 | 2 | flags | see [Flags field](#flags-field) |
| +0x02 | 1 | data_rule_id | see [Common DataItem descriptor fields](#common-dataitem-descriptor-fields) |
| +0x03 | 1 | reserved | zero |
| +0x04 | 2 | linked_counter_index | linked g[2] update-counter descriptor |
| +0x06 | 1 | change_event_queue_index | g[12] queue index or no-queue sentinel |
| +0x07 | 1 | reserved | zero |
| +0x08 | 2 | buffer_capacity | allocated runtime string-buffer capacity in bytes (e.g. 30, 32, 50, 64, 192) |

Example -- `SID` / `ApplicationIdentifier` in 16.8.5.0:

| Offset | Raw bytes | Field | Decoded value |
|-------:|-----------|-------|---------------|
| `+0x00` | `07 02` | flags | `0x0207` |
| `+0x02` | `00` | data_rule_id | no rule callback |
| `+0x03` | `00` | reserved | 0 |
| `+0x04` | `FF 7F` | linked_counter_index | none |
| `+0x06` | `17` | change_event_queue_index | no-queue sentinel in this release |
| `+0x07` | `00` | reserved | 0 |
| `+0x08` | `40 00` | buffer_capacity | 64 bytes |

---

## g[2] -- numeric DataItem descriptors

**Record stride:** 32 bytes

Backs `NumericDataItem` -- the numeric/ranged variables (pressures, times,
percentiles, counters). Values are i32 in raw units, displayed after dividing
by `scale`.

| Offset | Size | Field | Description |
|--------|------|-------|-------------|
| +0x00 | 2 | flags | see [Flags field](#flags-field) |
| +0x02 | 1 | data_rule_id | DataItem rule callback id |
| +0x03 | 1 | reserved | zero |
| +0x04 | 2 | linked_counter_index | linked g[2] update-counter descriptor |
| +0x06 | 1 | change_event_queue_index | g[12] queue index or no-queue sentinel |
| +0x07 | 1 | reserved | zero |
| +0x08 | 4 | default_raw | factory default in raw units |
| +0x0c | 4 | max_raw | upper clamp |
| +0x10 | 4 | min_raw (i32) | lower clamp; negative on signed records |
| +0x14 | 1 | decimal_places | number of fractional digits emitted by numeric RPC/JSON formatting |
| +0x15 | 1 | reserved | zero |
| +0x16 | 2 | scale (i16) | raw-to-display divisor (e.g. raw 500 / scale 50 = display 10.0) |
| +0x18 | 2 | step_raw (i16) | UI increment/decrement step in raw units |
| +0x1a | 1 | bounds_slot | signed selector for a runtime bounds-table slot or the descriptor's static min/max fields |
| +0x1b | 1 | sample_block_signal_id | wire identifier for this value in a g[14] compressed sample block; zero means no periodic signal assignment |
| +0x1c | 1 | quantity_class | physical quantity / unit class used by RPC range metadata |
| +0x1d | 3 | reserved | zero |

RPC numeric output divides the raw value by `scale` and rounds it to
`decimal_places`. ISO duration, date/time, and timezone encodings are selected
by a separate APPL table keyed by var-id; they are not encoded by this field.

### bounds_slot

`bounds_slot` selects the source of numeric min/max limits. Firmware reads it
as signed i8. Nonnegative values below the release's runtime-table count select
dynamic bounds; larger nonnegative values select the descriptor's own
`min_raw` and `max_raw` fields.

| APPX | Dynamic slots | Canonical static marker |
|------|---------------|-------------------------|
| 8.0.1 through 8.4.0 | `0x00..0x3d` | `0x3e` |
| 8.5.0 and 8.6.0 | `0x00..0x3c` | `0x3d` |

The comparison also routes values between the static marker and `0x7f` to
static bounds. Descriptor tables in the listed releases use the canonical
marker. Values `0x80..0xff` are signed negative selectors and are invalid in a
CONF descriptor.

Conceptually:

```c
struct DynamicBounds {
    int32_t max_raw;
    int32_t min_raw;
};

size_t dynamic_bounds_count = release_dynamic_bounds_count;
int8_t slot = descriptor.bounds_slot;

if (slot < dynamic_bounds_count) {
    min_raw = dynamic_bounds[slot].min_raw;
    max_raw = dynamic_bounds[slot].max_raw;
} else {
    min_raw = descriptor.min_raw;
    max_raw = descriptor.max_raw;
}
```

For example, `RMT` / `RampTime` has `bounds_slot = 0x21`, so its active range
comes from `dynamic_bounds[0x21]`. In 16.8.5.0,
`Cpap-SetPressure` has `bounds_slot = 0x3d`, so its active range comes from its
own descriptor fields.

`as11_descriptors.py firmware.bin bounds-slots` lists the dynamic slots, their
g[2] users, and the descriptor values used to initialize each slot.

### sample_block_signal_id

g[14] selects each value to sample by var ID. The selected numeric DataItem's
`sample_block_signal_id` supplies the wire identifier stored with its compressed
payload. It does not select the DataItem, sampling interval, or codec.

Each encoded sample block contains a channel directory followed by the channel
payloads:

```text
channel directory:  { u8 signal_id, u16 payload_bytes } * signal_count
channel payloads:   payload[0] || payload[1] || ...
```

The decoder finds a channel by `signal_id`, then uses `payload_bytes` to locate
the corresponding compressed data. ID zero is reserved as no channel: the
lookup functions do not return a payload for it. Every DataItem referenced by
a stock g[14] collection has a nonzero ID, while other numeric DataItems may
carry IDs reserved for collections not enabled in that CONF image.

This ID belongs only to the g[14] periodic sample-block format. Other spool
families use their own record schemas. The `StartSpool` formatter consumes the
ID while mapping an internal sample block to output protobuf fields, so the ID
is not necessarily present in the returned RPC payload.

For example, the `RFD` collection selects `BRF` by var ID. `BRF` has
`sample_block_signal_id = 0x17`, so the saved block identifies its payload as
signal `0x17`. The spool formatter recognizes `0x17` as the respiratory-flow
channel used by `RespiratoryFlow6p25Hz`.

Periodic sample-block signal IDs:

```text
01 AIP  02 LKP  03 AAH  04 RFA  05 AFL  06 LKR  07 BPA  08 BFL  09 BPR
10 AEP  11 AIE  12 MVT  13 RR1  14 ATI  15 QCN  16 QS2  17 QS3  18 QS4
19 SAV  20 HRV  21 MIS  22 A1M  23 BRF  24 BIP  25 BML  26 BMR  27 AAP
```

### quantity_class

`quantity_class` identifies the physical quantity associated with the numeric
value. RPC range metadata emits units for the following classes:

| quantity_class | RPC unit |
|---------------:|----------|
| `0x00` | `cmH2O` |
| `0x01` | `litresPerMinute` |
| `0x02` | `seconds` |
| `0x03` | `litresPerSecond` |
| `0x05` | `%` |
| `0x07` | `beatsPerMinute` |
| `0x08` | `breathsPerMinute` |
| `0x0a` | `litres` |
| `0x0b` | `minutes` |

Classes `0x04`, `0x06`, `0x09`, and `0x0c` do not have an entry in the RPC
unit table.

Quantity classes:

| quantity_class | Value family |
|---------------:|--------------|
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

Example -- `Cpap-SetPressure` in 16.8.5.0:

| Offset | Raw bytes | Field | Decoded value |
|-------:|-----------|-------|---------------|
| `+0x00` | `07 0E` | flags | `0x0e07` |
| `+0x02` | `0E` | data_rule_id | `0x0e` |
| `+0x03` | `00` | reserved | 0 |
| `+0x04` | `13 01` | linked_counter_index | g[2] descriptor `0x0113` |
| `+0x06` | `17` | change_event_queue_index | no-queue sentinel in this release |
| `+0x07` | `00` | reserved | 0 |
| `+0x08` | `F4 01 00 00` | default_raw | 500 -> 10.0 cmH2O |
| `+0x0c` | `E8 03 00 00` | max_raw | 1000 -> 20.0 cmH2O |
| `+0x10` | `C8 00 00 00` | min_raw | 200 -> 4.0 cmH2O |
| `+0x14` | `01` | decimal_places | one fractional digit |
| `+0x15` | `00` | reserved | 0 |
| `+0x16` | `32 00` | scale | 50 |
| `+0x18` | `0A 00` | step_raw | 10 -> 0.2 cmH2O |
| `+0x1a` | `3D` | bounds_slot | static descriptor bounds in 16.8.5.0 |
| `+0x1b` | `00` | sample_block_signal_id | 0 |
| `+0x1c` | `00` | quantity_class | 0 (pressure) |
| `+0x1d` | `00 00 00` | reserved | 0 |

---

## g[3] -- bitfield DataItem descriptors

**Record stride:** 20 bytes

Backs `BitFieldDataItem` variables such as `LanguageConfiguration` and
`NodeAccessFlags`. The runtime value is a u32 bitmask constrained by
`editable_mask`. `LanguageConfiguration` (`LNC`) lives here, not in g[5].

| Offset | Size | Field | Description |
|--------|------|-------|-------------|
| +0x00 | 2 | flags | see [Flags field](#flags-field) |
| +0x02 | 1 | data_rule_id | DataItem rule callback id |
| +0x03 | 1 | reserved | zero |
| +0x04 | 2 | linked_counter_index | linked g[2] update-counter descriptor |
| +0x06 | 1 | change_event_queue_index | g[12] queue index or no-queue sentinel |
| +0x07 | 1 | reserved | zero |
| +0x08 | 4 | default_mask | default bitfield value and source of immutable bit values |
| +0x0c | 4 | editable_mask | bits the user may set; values written by `setValue` are masked through this |
| +0x10 | 1 | bit_count | number of logical bit positions |
| +0x11 | 1 | -- | always 0 |
| +0x12 | 2 | selection_order_offset | byte offset into g[4] for `bit_count` order bytes |

Apply rule:

```text
new_value = (requested & editable_mask) | (default_mask & ~editable_mask)
```

The core bitfield read/write path does not use this list and retains the value
as a u32 mask. The GUI bitfield-message selector intersects a candidate mask
with the current value, selects the set bit with the lowest corresponding
priority byte, and uses that bit index to select the message mapping row.

Example -- `LNC` / `LanguageConfiguration` in 16.8.5.0:

| Offset | Raw bytes | Field | Decoded value |
|-------:|-----------|-------|---------------|
| `+0x00` | `07 06` | flags | `0x0607` |
| `+0x02` | `2C` | data_rule_id | `0x2c` |
| `+0x03` | `00` | reserved | 0 |
| `+0x04` | `13 01` | linked_counter_index | g[2] descriptor `0x0113` |
| `+0x06` | `17` | change_event_queue_index | no-queue sentinel in this release |
| `+0x07` | `00` | reserved | 0 |
| `+0x08` | `A3 00 00 00` | default_mask | `0x000000a3` |
| `+0x0c` | `FF FF FF 07` | editable_mask | `0x07ffffff` |
| `+0x10` | `1B` | bit_count | 27 |
| `+0x11` | `00` | reserved | 0 |
| `+0x12` | `54 00` | selection_order_offset | `0x0054` |

---

## g[4] -- bitfield GUI selection-order pool

g[4] is the base address for compact byte lists referenced by g[3]
descriptors:

```text
selection_order = g[4] + selection_order_offset
```

The list contains `bit_count` bytes. Byte `i` gives the GUI message-selection
order of logical bit `i`; the set bit with the lowest value wins. It does not
change the stored bitfield value and does not order DataItems. Lists in the
documented releases are permutations of `0..bit_count-1`.

---

## g[5] -- enum DataItem descriptors

**Record stride:** 16 bytes

Backs `EnumDataItem` -- single-selection variables drawn from a fixed logical
option range (mode toggles, comfort selectors, sensitivity levels, profile
pickers). The runtime value is the selected option index in
`0..n_options-1`. That value lives in the DataItem value store and, for
persistent settings, the corresponding settings file; it is not a field of
this descriptor.

| Offset | Size | Field | Description |
|--------|------|-------|-------------|
| +0x00 | 2 | flags | see [Flags field](#flags-field) |
| +0x02 | 1 | data_rule_id | DataItem rule callback id |
| +0x03 | 1 | reserved | zero |
| +0x04 | 2 | linked_counter_index | linked g[2] update-counter descriptor |
| +0x06 | 1 | change_event_queue_index | g[12] queue index or no-queue sentinel |
| +0x07 | 1 | reserved | zero |
| +0x08 | 1 | default_option | factory default logical option slot (0..`n_options-1`) |
| +0x09 | 1 | n_options | number of logical option slots |
| +0x0a | 2 | -- | always 0 |
| +0x0c | 4 | option_mask | availability mask for logical option slots `0..31`; higher slots below `n_options` are implicitly enabled |

`default_option` supplies the initial value when no stored value is applied.
The generic GUI enum list and RPC enum metadata enumerate available choices as:

```text
for option in 0 .. n_options-1:
    enabled = option >= 32 || (option_mask & (1 << option)) != 0
    if DataItem == Language:
        enabled &= (current_LNC_mask & (1 << option)) != 0
    if enabled:
        include option
```

The 34-option `STC` descriptor therefore uses `option_mask` for its first 32
choices and exposes the final two without mask bits. `Language` is the only
special case in the core option-availability function; its options are also
gated by the current `LanguageConfiguration` (`LNC`) value. Descriptor flags
control the DataItem as a whole, not individual options. `data_rule_id` is not
consulted when constructing this list.

### Option meanings

The descriptor defines the numeric option range, default, and availability;
it does not define what an option means. APPL contains two independent
12-byte lookup tables keyed by the g[5] descriptor index and raw option value:

| Consumer | Record | Result |
|----------|--------|--------|
| JSON RPC | `u32 enum_index, u32 raw_option, char *symbol` | stable protocol value such as `Off`, `Auto`, or `VAutoProfile` |
| GUI | `u32 enum_index, u32 raw_option, i16 text_id` | localized GUI text selected from the active language table |

Known table locations are APPX virtual addresses. The corresponding full-image
file offset is the address minus `0x08000000`.

| APPX | RPC symbol table | Records | GUI text-ID table | Records |
|------|-----------------:|--------:|------------------:|--------:|
| 8.0.1 | `0x080fd764` | 893 | `0x08138d70` | 279 |
| 8.3.0 | `0x08105318` | 974 | `0x081417b4` | 319 |
| 8.4.0 | `0x081070a0` | 1027 | `0x0813f048` | 357 |
| 8.5.0 | `0x08107ba8` | 1032 | `0x0813fb5c` | 355 |
| 8.6.0 | `0x08108398` | 1041 | `0x08140450` | 355 |

The g[5] descriptor contains no table pointer. `DataItemFactory` derives the
lookup key from the var ID:

```text
g5_var_id_base = g1_count + g2_count + g3_count
enum_index = var_id - g5_var_id_base
```

Each lookup scans for a record whose first two fields match
`(enum_index, raw_option)`. RPC `Get` converts the stored raw value to the
matching symbol; RPC `Set` performs the reverse symbol lookup. The generic GUI
list resolves each available raw value to a text ID and then renders that text
in the current language.

For example, in 8.6.0 `MOP` has var ID `0x0426` and g[5] begins at var ID
`0x0349`, giving enum index `0x00dd`. Its RPC symbols occupy records 555..565
and its GUI labels records 192..202, but the lookup uses the two key fields
rather than those physical record numbers.

Raw values therefore have no universal boolean meaning. For example,
`RampEnable` maps `0`, `1`, and `2` to `Off`, `On`, and `Auto`, while
`ActiveTherapyProfile` maps `0` to `CpapProfile`. Specialized controls may
combine or format multiple DataItems instead of displaying this generic enum
list directly.

Example -- `MOP` / `ActiveTherapyProfile` in 16.8.5.0 vid03:

| Offset | Raw bytes | Field | Decoded value |
|-------:|-----------|-------|---------------|
| `+0x00` | `07 06` | flags | `0x0607` |
| `+0x02` | `34` | data_rule_id | `0x34` |
| `+0x03` | `00` | reserved | 0 |
| `+0x04` | `13 01` | linked_counter_index | g[2] descriptor `0x0113` |
| `+0x06` | `17` | change_event_queue_index | no-queue sentinel in this release |
| `+0x07` | `00` | reserved | 0 |
| `+0x08` | `01` | default_option | slot 1 (`AutoSetProfile`) |
| `+0x09` | `0B` | n_options | 11 |
| `+0x0a` | `00 00` | reserved | 0 |
| `+0x0c` | `07 00 00 00` | option_mask | slots 0, 1, and 2 enabled |

---

## g[6] -- external-NOR SettingsGroup schemas

Seven 16-byte records define the `SettingsGroup` schemas stored under
`nor:0:\\SETTINGS`. Each record supplies the filename stem, a g[2] update
counter, and an ordered candidate list of DataItems. Only active DataItems are
written to or applied from the corresponding file.

| Offset | Size | Field |
|--------|------|-------|
| +0x00 | 4 | filename stem (NUL-terminated 3-char) |
| +0x04 | 2 | update_counter_index (i16) |
| +0x06 | 2 | reserved; zero |
| +0x08 | 4 | var_id_list_ptr |
| +0x0c | 1 | count |
| +0x0d | 3 | reserved; zero |

The +0x04 field selects the g[2] counter updated when the set changes. It is
independent of the var IDs in the pointed list.

Example -- the 16.8.5.0 `BGL` header:

| Offset | Raw bytes | Field | Decoded value |
|-------:|-----------|-------|---------------|
| `+0x00` | `42 47 4C 00` | filename stem | `BGL` (`nor:0:\SETTINGS\BGL.set`) |
| `+0x04` | `73 00` | update_counter_index | g[2] descriptor `0x0073` |
| `+0x06` | `00 00` | reserved | 0 |
| `+0x08` | `08 D1 02 08` | var_id_list_ptr | `0x0802d108` |
| `+0x0c` | `06` | count | 6 u16 var IDs |
| `+0x0d` | `00 00 00` | reserved | 0 |

SettingsGroup membership:

| File | 8.0.1 | 8.3.0 | 8.4.0 | 8.5.0 | 8.6.0 | Contents |
|------|------:|------:|------:|------:|------:|----------|
| `BGL.set` | 6 | 6 | 6 | 6 | 6 | pressure/flow calibration coefficients (`PressureGain`, `PressureOffset`, `PressureMonitorGain`, `PressureMonitorOffset`, `FlowGain`, `FlowOffset`) |
| `DDO.set` | 48 | 61 | 64 | 64 | 64 | data-delivery/reporting state used by event and periodic storage |
| `DID.set` | 13 | 13 | 13 | 13 | 13 | product, device, and cellular identification profile values |
| `HST.set` | 159 | 162 | 163 | 162 | 162 | therapy, comfort, environment, display, alarm, and reminder settings, including inactive mode settings |
| `MCA.set` | 1 | 1 | 1 | 1 | 1 | `CamlData` blob |
| `MCF.set` | 1 | 1 | 1 | 1 | 1 | `ApplicationData` blob |
| `TLP.set` | 39 | 42 | 40 | 41 | 41 | telemetry/cloud configuration and transport state |

Membership and ordering are invariant among CONF variants of the same release.
Variant availability is controlled by descriptor activity, enum option masks,
mode visibility, and other schemas.

Each file uses this format:

```text
u16 days_since_1970
u32 milliseconds_since_midnight
u8  node_count
node_count x {
    u16 length_after_length
    char short_tag[3]
    byte payload[length_after_length - 3]
}
u32 crc32
```

The CRC is IEEE CRC-32 over all preceding bytes. Numeric nodes contain one
raw u32 value. Text nodes contain the descriptor-sized string buffer followed
by NUL. Files are limited to `0x7fa` bytes. Loading resolves nodes by short tag,
skips unknown tags, and applies only DataItems that are active in the current
CONF.

---

## g[7] -- PDL backup-SRAM snapshot

`PDL` is a 12-byte named var-list header. It defines the DataItems serialized
into the `0x400`-byte power-loss snapshot in backup SRAM.

| Offset | Size | Field |
|--------|------|-------|
| +0x00 | 4 | tag ("PDL\0") |
| +0x04 | 4 | var_id_list_ptr (`count` x u16) |
| +0x08 | 1 | count |
| +0x09 | 3 | reserved |

The snapshot has this layout:

```text
u16 member_count
member_count x { char short_tag[4]; u32 raw_value; }
u16 CRC16-CCITT-FALSE
u16 0x1234
```

The CRC covers the count and DataItem records. Records are resolved by short
tag, so their serialized order is not required and unknown tags are skipped.
The writer appends `0x1234`, but the normal loader does not validate it. The
unused tail of the `0x400`-byte window is left unchanged. This object describes
one backup-SRAM window, not the complete 4 KiB backup SRAM area.

| Backup SRAM offset | Size | Owner |
|-------------------:|-----:|-------|
| `0x000` | `0x400` | PDL snapshot selected by g[7] |
| `0x400` | `0x080` | fatal-error state |
| `0x480` | `0x134` | power-up auxiliary state |
| `0xc00` | `0x400` | PowerUpState snapshot with its own length, magic, and CRC |

The PDL list does not overlap any g[6] SettingsGroup list in the documented
releases. PowerUpState restoration can copy a PDL payload into the live PDL
window.

PDL membership and order are identical among the available variants of each
release. Cells contain the zero-based member index; `--` means absent.

| Tag | 11.8.0.1 | 14.8.3.0 | 15.8.4.0 | 16.8.5.0 | 17.8.6.0 |
|-----|----------:|---------:|---------:|---------:|---------:|
| **Members** | **59** | **60** | **43** | **49** | **49** |
| `REM` | 0 | 0 | 0 | 0 | 0 |
| `ZSE` | 1 | 1 | 1 | 1 | 1 |
| `ZDT` | 2 | 2 | 2 | 2 | 2 |
| `ZDD` | 3 | 3 | 3 | 3 | 3 |
| `FW0` | 4 | 4 | 4 | 4 | 4 |
| `FW1` | 5 | 5 | 5 | 5 | 5 |
| `FWC` | 6 | 6 | 6 | 6 | 6 |
| `FE0` | 7 | 7 | 7 | 7 | 7 |
| `FE1` | 8 | 8 | 8 | 8 | 8 |
| `FE2` | 9 | 9 | 9 | 9 | 9 |
| `BTU` | 10 | 10 | 10 | 10 | 10 |
| `BUC` | 11 | 11 | 11 | 11 | 11 |
| `XSS` | 12 | 12 | 12 | 12 | 12 |
| `LRE` | 13 | 13 | 13 | 13 | 13 |
| `RFP` | 14 | 14 | 14 | 14 | 14 |
| `ZFE` | 15 | 15 | 15 | 15 | 15 |
| `ILS` | 16 | 16 | 16 | 16 | 16 |
| `PST` | 17 | 17 | -- | -- | -- |
| `PSS` | 18 | 18 | -- | -- | -- |
| `PAH` | 19 | 19 | -- | -- | -- |
| `PL7` | 20 | 20 | -- | -- | -- |
| `PL9` | 21 | 21 | -- | -- | -- |
| `PPI` | 22 | 22 | -- | -- | -- |
| `PPE` | 23 | 23 | -- | -- | -- |
| `PAT` | 24 | 24 | -- | -- | -- |
| `PRR` | 25 | 25 | -- | -- | -- |
| `PVT` | 26 | 26 | -- | -- | -- |
| `PMT` | 27 | 27 | -- | -- | -- |
| `PIS` | 28 | 28 | -- | -- | -- |
| `PIE` | 29 | 29 | -- | -- | -- |
| `PVS` | 30 | 30 | -- | -- | -- |
| `PVC` | 31 | 31 | -- | -- | -- |
| `PAS` | 32 | 32 | -- | -- | -- |
| `POS` | 33 | 33 | -- | -- | -- |
| `PCI` | 34 | 34 | -- | -- | -- |
| `SMN` | 35 | 35 | 17 | 17 | 17 |
| `SVN` | 36 | 36 | 18 | 18 | 18 |
| `CUD` | 37 | 37 | 19 | 19 | 19 |
| `CED` | 38 | 38 | 20 | 20 | 20 |
| `PHM` | 39 | 39 | 21 | 21 | 21 |
| `MHR` | 40 | 40 | 22 | 22 | 22 |
| `MHS` | 41 | 41 | 23 | 23 | 23 |
| `MHU` | 42 | 42 | 24 | 24 | 24 |
| `LMS` | 43 | 43 | 25 | 25 | 25 |
| `LPD` | 44 | 44 | 26 | 26 | 26 |
| `LI9` | 45 | 45 | 27 | 27 | 27 |
| `PTF` | 46 | 46 | 28 | 28 | 28 |
| `RCM` | 47 | 47 | 29 | 29 | 29 |
| `MDM` | 48 | 48 | 30 | 30 | 30 |
| `RCT` | 49 | 49 | 31 | 31 | 31 |
| `MDT` | 50 | 50 | 32 | 32 | 32 |
| `RCH` | 51 | 51 | 33 | 33 | 33 |
| `MDW` | 52 | 52 | 34 | 34 | 34 |
| `RCF` | 53 | 53 | 35 | 35 | 35 |
| `MDF` | 54 | 54 | 36 | 36 | 36 |
| `DTU` | 55 | 55 | 37 | 37 | 37 |
| `DTD` | 56 | 56 | 38 | 38 | 38 |
| `CCT` | 57 | 57 | 39 | 39 | 39 |
| `ABU` | -- | 58 | 40 | 40 | 40 |
| `AUP` | 58 | 59 | 41 | 41 | 41 |
| `SET` | -- | -- | 42 | 42 | 42 |
| `BMS` | -- | -- | -- | 43 | 43 |
| `ZBM` | -- | -- | -- | 44 | 44 |
| `DME` | -- | -- | -- | 45 | 45 |
| `MTP` | -- | -- | -- | 46 | 46 |
| `TOC` | -- | -- | -- | 47 | 47 |
| `GBE` | -- | -- | -- | 48 | 48 |

---

## g[8] -- short-name bucket headers

26-entry A-Z bucket header table. Short-tag lookup selects the bucket from the
first character, then scans 4-byte entries.

Bucket header (8 bytes):

| Offset | Size | Field |
|--------|------|-------|
| +0x00 | 4 | entries pointer |
| +0x04 | 1 | count |
| +0x05 | 3 | reserved, zero |

Each entry (4 bytes):

| Offset | Size | Field |
|--------|------|-------|
| +0x00 | 2 | suffix (chars 2 and 3) |
| +0x02 | 2 | var_id |

Firmware uses this table only for four-character names of the form `_TAG`.
The first tag character must be `A..Z`; the remaining two may be `A..Z` or
`0..9`; the fourth input byte must be NUL or space. The selected bucket is
scanned linearly and returns `0x7fff` when no entry matches.

Example -- resolving `MOP` in 16.8.5.0:

| Step | Value |
|------|-------|
| Bucket index | `'M' - 'A' = 12` |
| Bucket header | `g[8] + 12 * 8` (file offset `0x02bb78`) |
| Entry table | `0x0802b630` |
| Matching entry | entry 69: suffix `OP`, var_id `0x0420` |

---

## g[9] -- short-name reverse table

Linear var_id -> 3-char short tag pool, indexed as `g[9] + var_id * 3`. Its
extent is exactly `(maximum var_id + 1) * 3` bytes. It contains the A-Z bucket
names plus four reverse-only internal tags (`_UD`, `_HU`, `_HR`, `_HS`).

Its consumers copy or compare exactly three case-sensitive bytes. They reject
only var ID `0x7fff`; callers are responsible for supplying an in-range ID.

| Version | A-Z names | Internal names | Indexed slots |
|---------|----------:|---------------:|--------------:|
| 11.8.0.1 | 1078 | 4 | 1082 |
| 14.8.3.0 | 1143 | 4 | 1147 |
| 15.8.4.0 | 1180 | 4 | 1184 |
| 16.8.5.0 | 1198 | 4 | 1202 |
| 17.8.6.0 | 1205 | 4 | 1209 |

Example -- `MOP` in 16.8.5.0:

| Input | Calculation | Result |
|-------|-------------|--------|
| var_id `0x0420` | `g[9] + 0x0420 * 3` | file offset `0x029560`, tag `MOP` |

---

## g[10] -- per-mode baseline visibility

**Record stride:** 14 bytes

| Offset | Size | Field |
|--------|------|-------|
| +0x00 | 2 | var_id |
| +0x02 | 11 | per-mode visibility bytes |
| +0x0d | 1 | reserved / zero |

The visibility fields are bytes, not a packed bitmask. During an MOP write,
firmware stores the new enum value and synchronously runs the MOP data rule.
That rule copies the active-mode byte into each listed DataItem's runtime
visibility field, then applies feature-specific visibility postprocessors.
The normal DataItem change notification and final value reload follow the
rule callback.

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

Example -- `Cpap-SetPressure` in 16.8.5.0:

| Offset | Raw bytes | Field | Decoded value |
|-------:|-----------|-------|---------------|
| `+0x00` | `0C 01` | var_id | `0x010c` (`Cpap-SetPressure`) |
| `+0x02` | `01 00 00 00 00 00 00 00 00 00 00` | visibility | visible in CPAP |
| `+0x0d` | `00` | reserved | 0 |

g[10] defines the baseline visibility applied during mode changes. It does not
activate a descriptor, enable an enum option, or define EDF output.

---

## g[11] -- record count for g[10]

g[11] stores the number of g[10] records as a scalar value.

| Version | g[10] records | g[11] value |
|---------|--------------:|------------:|
| 11.8.0.1 | 103 | `0x67` |
| 14.8.3.0 | 103 | `0x67` |
| 15.8.4.0 | 103 | `0x67` |
| 16.8.5.0 | 101 | `0x65` |
| 17.8.6.0 | 101 | `0x65` |

---

## g[12] -- event spool definitions

**Record stride:** 36 bytes

Each record defines one event family from producer admission through live RPC
delivery and persistent spool storage. The same record supplies the selector
name, two in-memory FIFO geometries, the circular-file geometry, erase class,
and producer gate.

| Offset | Size | Field | Description |
|--------|------|-------|-------------|
| +0x00 | 4 | name_ptr | selector accepted by `SubscribeEvent` and `StartSpool`; lookup returns the g[12] row index |
| +0x04 | 4 | code_ptr | 3-character stem of `nor:1:\\DATALOG\\<code>.EVN` |
| +0x08 | 4 | fifo_slots | requested capacity of both runtime event FIFOs |
| +0x0c | 4 | retained_record_target | logical record count used to size the circular file; not an exact capacity |
| +0x10 | 4 | event_record_bytes | fixed persisted record width and maximum producer-submitted record size |
| +0x14 | 1 | record_kind | generic event-code width or special spool-record format |
| +0x15 | 1 | default_json_payload_type | default handling of bytes following a generic event code; see [g[13]](#g13----eventnotification-payload-overrides) |
| +0x16 | 1 | erase_class | `EraseData` class: `0` = `Logs`, `1` = `SleepData` |
| +0x17 | 1 | logger_enabled | `1` enables draining, live notification, and persistence for this family |
| +0x18 | 4 | file_record_bytes | physical `.EVN` block width, including the block length and CRC fields |
| +0x1c | 4 | allocation_group_blocks | block-count rounding and extension quantum |
| +0x20 | 2 | file_init_flag_bit | bit in `FIF` representing successful initialization of this file |
| +0x22 | 2 | gate_g5_index | optional g[5] descriptor index controlling producer admission; `0x7fff` means unconditional |

### Queue and live-event path

Producers submit records using a g[12] index supplied by compiled code or by a
DataItem descriptor's `change_event_queue_index`. `name_ptr` is used by
`SubscribeEvent` to resolve a selector to that index and by the event-file
writer registry to associate a writer with the same event family.

Before accepting a produced record, firmware applies `gate_g5_index`: a
missing gate accepts the record, while a configured gate accepts it only when
that `EnumDataItem` has a nonzero raw value. The gate affects newly produced
records; it does not hide records already present in the `.EVN` file.

The producer rejects a submitted record longer than `event_record_bytes`.
Generic helpers prepend the six-byte firmware timestamp before queuing the
record. Each event family has two FIFOs:

1. a thread-safe producer FIFO
2. a pending-file FIFO used between live delivery and the file writer

Both request `fifo_slots` elements of `event_record_bytes + 4` bytes. The FIFO
implementation rounds a non-power-of-two capacity up to the next power of two.
When a FIFO lacks a free slot, the new record is not inserted; existing queued
records are retained.

The additional four bytes are RAM-only completion metadata. A producer may
place a pointer immediately after the persisted record bytes. The file writer
keeps these pointers outside the file block and writes `1` through each
non-null pointer after the containing batch completes.

The logger drains the producer FIFO only when `logger_enabled` is `1` and the
shared logged-data gate is active. For each accepted record it places the
record in the pending-file FIFO and publishes the live `EventNotification`.
Live delivery therefore does not imply that the corresponding `.EVN` write has
completed.

### Record formats

Generic records begin with a six-byte timestamp. `record_kind` determines what
follows it:

| Kind | Record interpretation |
|-----:|-----------------------|
| 1 | u8 event value followed by the payload selected by g[12]/g[13] |
| 2 | u16 event value followed by the payload selected by g[12]/g[13] |
| 3 | Settings History record (`SHE`) |
| 4 | Acoustic Signature record (`ASE`) |
| 5 | Sound Check record (`SCE`) |
| 6 | Cellular Activity String record (`CAS`, from 8.6.0) |

Kinds 1 and 2 use the generic `EventNotification` JSON formatter. Kinds 3
through 6 have selector-specific spool serializers and are not generic live
event records. `default_json_payload_type` applies only to kinds 1 and 2. The
formatter first searches g[13] for a matching `(g[12] index, event value)` and
uses the g[12] default only when no override matches.

Every on-disk slot is exactly `event_record_bytes` bytes. The writer copies
that complete width even when the producer populated a shorter prefix.

### Circular-file geometry

Each `.EVN` block contains:

```text
u16 used_record_bytes
fixed-width event records
unused block space
u16 crc16
```

The usable block payload is therefore `file_record_bytes - 4`. Firmware sizes
the file as:

```text
records_per_block = floor((file_record_bytes - 4) / event_record_bytes)
required_blocks = ceil(retained_record_target / records_per_block)
file_blocks = allocation_group_blocks
    * (ceil(required_blocks / allocation_group_blocks) + 2)
file_size = file_blocks * file_record_bytes
```

`retained_record_target` is consequently a lower sizing target. Rounding to
`allocation_group_blocks` and the two additional groups make the physical
record capacity larger. Once the circular block index wraps, newly written
blocks replace the oldest blocks.

For example, 8.6.0 `CellularActivityEvents` (`CAV`) uses 11-byte records,
512-byte blocks, a target of 2000 records, and ten-block allocation groups:

```text
records_per_block = 46
required_blocks = 44
file_blocks = 70
file_size = 35840 bytes
physical_capacity = 3220 records
```

`StartSpool` reads this block format and uses `file_record_bytes` as the event
spool transfer granularity.

### Initialization and erase

During startup the file initialiser opens or creates each `.EVN`, verifies its
size, scans valid CRC-protected blocks, and recovers the next circular write
index. It then sets `file_init_flag_bit` in `FIF`. Resetting that file clears
the bit. The logged-data service becomes ready only after the initialization
bits for every g[12] row are set.

`erase_class` selects which `EraseData` request resets the file. Class 0 files
belong to `Logs`; class 1 files belong to `SleepData`. This classification
affects deletion only and does not alter record encoding or retention.

| Release | Records |
|---------|--------:|
| 11.8.0.1 | 22 |
| 14.8.3.0 | 22 |
| 15.8.4.0 | 23 |
| 16.8.5.0 | 23 |
| 17.8.6.0 | 24 |

The count is a literal APPX loop bound and the return value for an unknown
selector. The same value is stored as the `change_event_queue_index` no-queue
sentinel in g[1], g[2], g[3], and g[5] descriptors; lower values select a
g[12] record. Firmware 8.4 adds `APE`; firmware 8.6 adds `CAS`.

Examples include `CellularActivityEvents` (`CAV`),
`TherapyEvents-RespiratoryEvents` (`RNV`),
`DiagnosticExceptionEvents-AppErrors` (`APE`), and
`_SETTINGS_HISTORY_EVENT` (`SHE`).

---

## g[13] -- EventNotification payload overrides

g[13] contains six-byte rules used when a stored event is rendered as an RPC
`EventNotification`. The rule controls how bytes following the event value are
consumed and whether they become an additional JSON property.

| Offset | Size | Field | Description |
|--------|------|-------|-------------|
| +0x00 | 1 | event_spool_index | g[12] record index |
| +0x01 | 1 | padding | zero in the documented releases |
| +0x02 | 2 | event_value | event value within the selected spool; `0xffff` matches every value |
| +0x04 | 1 | json_payload_type | replacement trailing-payload rule |
| +0x05 | 1 | padding | zero in the documented releases |

The formatter searches g[13] in table order for the first row whose
`event_spool_index` matches and whose `event_value` is either exact or
`0xffff`. If no row matches, it uses `default_json_payload_type` from the
corresponding g[12] record.

| Type | Trailing value | Additional JSON property |
|-----:|----------------|--------------------------|
| 0 | none | none |
| 1 | u16 | none |
| 2 | u32 | none |
| 3 | u16 | `durationSeconds` |
| 4 | u16 | `backdateSeconds` |
| 5 | u32 | `address` |
| 6 | u32 | `uint32Data` |

Types outside `0..6` make event formatting fail. Types `0..2` occur as g[12]
defaults; g[13] uses types `3..6`.

For example, `TherapyEvents-RespiratoryEvents` (`RNV`, g[12] index 16 in
16.8.5.0) has default type 1. Its g[13] rules select type 3 for
`CentralApneaEnd`, `ObstructiveApneaEnd`, and `ApneaEnd`, producing records
such as:

```json
{"reportTime":"2026-06-13T22:47:49.765Z","event":"ObstructiveApneaEnd","durationSeconds":15}
```

`CsrStart` and `CsrEnd` select type 4 instead:

```json
{"reportTime":"2026-06-13T22:47:49.765Z","event":"CsrStart","backdateSeconds":42}
```

Other `RNV` values use the default type and therefore expose no extra JSON
property.

---

## g[14] -- periodic collections

**Record stride:** 0x34 bytes

Each row defines one periodic collection stored in the circular NOR file
`nor:1:\\DATALOG\\<tag>.seg` and exposed through `StartSpool`.

| Offset | Size | Field | Description |
|--------|------|-------|-------------|
| +0x00 | 4 | tag string ptr | collection/file tag |
| +0x04 | 4 | sample_interval_ms | sampling period |
| +0x08 | 4 | max_block_duration_seconds | time limit for one encoded block |
| +0x0c | 4 | file_record_bytes | physical circular-file record size |
| +0x10 | 4 | retention_hours | requested retained duration |
| +0x14 | 4 | blocks_per_file_record | encoded sample blocks packed in one file record |
| +0x18 | 4 | file_allocation_granularity | file records in one allocation group |
| +0x1c | 4 | compression_ratio_estimate | assumed ratio of uncompressed i16 sample bytes to encoded bytes, used to size the circular file |
| +0x20 | 1 | initializer_byte | common logged-data initializer value; `1` in the documented releases |
| +0x21 | 1 | reset_request_class | `0` selects the log reset request; `1` selects the periodic-data reset request |
| +0x22 | 2 | gate_g5_index | g[5] descriptor index used as the collection gate; `0x7fff` means no gate |
| +0x24 | 2 | file_init_flag_bit | bit in `FIF` (`File Initialization Flags`) |
| +0x26 | 2 | reserved | zero |
| +0x28 | 1 | signal_count | zero disables the collection |
| +0x29 | 3 | reserved | zero |
| +0x2c | 4 | signal_var_ids ptr (u16[]) | ordered source DataItems |
| +0x30 | 4 | signal_metadata ptr | parallel codec metadata table |

Signal metadata record (0x30 bytes, 14.8.3.0 and later):

| Offset | Size | Field | Description |
|--------|------|-------|-------------|
| +0x00 | 8 | clamp_min (f64) | lower encoded source bound |
| +0x08 | 8 | clamp_max (f64) | upper encoded source bound |
| +0x10 | 8 | quantization_step (f64) | encoded sample step |
| +0x18 | 8 | multiplier_numerator (f64) | numerator applied before DataItem scale and quantization-step division |
| +0x20 | 1 | rice_modulus | Rice-coding modulus `M`; must be a power of two |
| +0x21 | 3 | reserved | zero |
| +0x24 | 4 | codec_revision | `0` = `RC03`, `1` = `RC04` |
| +0x28 | 1 | precision | precision parameter stored in the optional prefix |
| +0x29 | 1 | parameter_prefix | nonzero emits codec parameters before sample data |
| +0x2a | 2 | reserved | zero |
| +0x2c | 4 | reserved | zero |

Firmware 11.8.0.1 uses a 0x28-byte legacy record. Its first four `f64` fields
are identical; the tail is:

| Offset | Size | Field | Description |
|--------|------|-------|-------------|
| +0x20 | 1 | rice_modulus | Rice-coding modulus `M` |
| +0x21 | 7 | reserved | zero |

The legacy record does not carry codec revision, precision, or parameter-prefix
fields. Firmware 14.8.3.0 and later use the 0x30-byte layout.

| Release | Count | Metadata | Collections and spool selectors |
|---------|------:|---------:|---------------------------------|
| 11.8.0.1 | 2 | 0x28 | `CSF` = `DiagnosticTenMinutePeriodic`; `NRF` = `TherapyOneMinutePeriodic` |
| 14.8.3.0 | 6 | 0x30 | above plus `TIP` = `InspiratoryPressure0p5Hz`, `MLK` = `Leak0p5Hz`, `MPD` = `MaskPressure6p25Hz`, `RFD` = `RespiratoryFlow6p25Hz` |
| 15.8.4.0 and later | 7 | 0x30 | above plus `APD` = `atmosphericPressure10min` |

The number of g[14] collection rows is compiled into the APPX loops that
construct, register, and reset the collection pipelines. Each row separately
stores its own `signal_count` at `+0x28`.

The pointed var-id lists name the source DataItems. `gate_g5_index` is relative
to the first g[5] var ID:
`CSF` resolves to `QNC`, the therapy collections resolve to `ZLE`, and `APD`
has no gate.

A collection samples when its signal count is nonzero, its optional gate is
nonzero, and at least one source DataItem is available. The collector snapshots
which sources are available for the current block. A change in that set closes
the block so the channel list remains constant within one encoded block. A
block also closes at its time limit, when the destination has insufficient
space, when the gate closes, or when every source becomes unavailable.

The writer sets `file_init_flag_bit` after its file has been initialized or
scanned. Resetting the row's request class clears that bit, resets sampling and
compression state, and invalidates the source-availability snapshot.

For each collection, retained-sample demand is:

```text
ceil(3600000 * retention_hours / sample_interval_ms)
```

The estimated encoded capacity of one file record is:

```text
floor(compression_ratio_estimate
      * (file_record_bytes - 3 * blocks_per_file_record - 14)
      / (2 * blocks_per_file_record))
```

The circular file allocation is:

```text
file_record_count = file_allocation_granularity
    * (ceil(retained_samples
            / (file_allocation_granularity * samples_per_record)) + 2)
```

The `+2` is a two-allocation-group capacity margin added by the periodic
logger. The filesystem receives the resulting record count and does not add
this margin itself.

Each source sample is quantized as:

```text
multiplier = multiplier_numerator / (DataItem scale * quantization_step)
q = clamp_i16(
    round_away_from_zero(raw * multiplier),
    round(clamp_min / quantization_step),
    round(clamp_max / quantization_step))
```

The first two quantized samples are signed 16-bit predictor seeds. Subsequent
samples use the second-order delta `q[n] - 2*q[n-1] + q[n-2]`, signed zigzag
mapping, and Rice coding with `k = log2(rice_modulus)`. When
`parameter_prefix` is set, the block begins with its parameter-body length,
the `RC03` or `RC04` tag, and zigzag-ULEB128 parameters for step, exponent,
quantized bounds, Rice modulus, and precision.

---

## g[15] -- STR.edf SummaryRecord schema

g[15] defines the persistent per-day Summary record, the `Summary` spool
projection, and the signal rows written to `STR.edf`.

### Header

| Offset | Size | Field | Description |
|--------|------|-------|-------------|
| +0x00 | 2 | retention_days | maximum number of therapy-day records retained by the long-term Summary reader/writer |
| +0x02 | 2 | usage_interval_capacity | maximum mask-on/off intervals stored in one therapy-day record |
| +0x04 | 2 | record_count | number of 36-byte SummaryRecord rows |
| +0x06 | 2 | ignored_input_field_count | number of ignored input-field rows |
| +0x08 | 4 | `SummaryRecord*` | SummaryRecord table pointer |
| +0x0c | 4 | ignored_input_field_table_ptr | ignored input-field table pointer |

| Version | Records | SummaryRecord file offset | Ignored field count | Ignored fields |
|---------|--------:|--------------------------:|--------------------:|----------------|
| 11.8.0.1 | 142 | varies | 3 | `XA5`, `XB3`, `ZZ6` |
| 14.8.3.0 | 190 | `0x025408` | 3 | `XA5`, `XB3`, `ZZ6` |
| 15.8.4.0 | 192 | `0x025688` | 3 | `XA5`, `XB3`, `ZZ6` |
| 16.8.5.0 | 190 | `0x025768` | 5 | `XA5`, `XB3`, `ZZ6`, `XB9`, `XBA` |
| 17.8.6.0 | 190 | varies | 5 | `XA5`, `XB3`, `ZZ6`, `XB9`, `XBA` |

`retention_days` is 365 and `usage_interval_capacity` is 20 in these releases.

Each ignored input-field record is eight bytes:

| Offset | Size | Field | Description |
|--------|------|-------|-------------|
| +0x00 | 4 | short_tag | NUL-terminated three-character input tag |
| +0x04 | 4 | kind | value layout code using the same word-count rules as a SummaryRecord kind |

The summary reader checks this table before ordinary short-tag resolution. A
matching field is skipped according to `kind`. All listed fields use kind `0`,
which skips one value word after the tag.

### SummaryRecord layout

**Record stride:** 36 bytes

| Offset | Size | Field | Description |
|--------|------|-------|-------------|
| +0x00 | 4 | field_id | field number in the `Summary` protobuf; table order controls persistent and EDF order |
| +0x04 | 4 | kind | selects the accumulator implementation and stored word count |
| +0x08 | 2 | var_a | output var for derived rows; auxiliary output for kind 2 |
| +0x0a | 2 | var_b | direct/source var; persistent short tag for kinds 0..2 |
| +0x0c | 2 | var_c | second source for kind 5; otherwise `0x7fff` |
| +0x0e | 1 | percentile | percentile for kinds 6 and 7; zero otherwise |
| +0x0f | 1 | reserved | zero |
| +0x10 | 4 | summary_spool_multiplier (f32) | multiplier applied when encoding the integer value into the `Summary` protobuf |
| +0x14 | 1 | spool_enabled | non-zero includes the row in the `Summary` spool |
| +0x15 | 1 | edf_enabled | non-zero includes the row in `STR.edf` |
| +0x16 | 2 | reserved | zero |
| +0x18 | 4 | edf_label | ASCII string ptr -> EDF signal label |
| +0x1c | 4 | edf_unit | ASCII string ptr -> EDF physical unit |
| +0x20 | 4 | edf_physical_divisor (f32) | raw-to-physical divisor represented by the EDF signal header |

The stored Summary value remains a signed 32-bit raw DataItem value. The spool
encoder multiplies it by `summary_spool_multiplier` and rounds to an integer.
Before writing a non-interval STR row, firmware tests the row's `var_b`
DataItem type. Enum-backed rows dispatch by `field_id` to an APPL mapper that
re-reads a version-local source DataItem and converts its zero-based option
index through an APPL byte table. These maps are not stored in g[15] or
elsewhere in CONF. Rows in the documented releases keep `field_id` equal to
the table index and pair `var_b` with the source expected by that mapper.

`INT32_MIN` bypasses remapping and is written as digital `-1` without a
diagnostic. Any other resulting value outside `-32768..32767` is written as
`-1` and reports an application error. `edf_physical_divisor` affects the EDF
header and does not rescale the digital sample.
The conversion tables are listed in
[STR enum export maps](edf_signals.md#str-enum-export-maps).

Kinds select these accumulator forms:

| Kind | Stored words | Operation |
|-----:|-------------:|-----------|
| 0 | 1 | snapshot `var_b`; an unavailable source leaves the previous value unchanged |
| 1 | 1 | direct `var_b` value with output availability maintained by the accumulator |
| 2 | 1 | accumulate the interval value into `var_b` and publish the interval value through `var_a` |
| 3 | `usage_interval_capacity + 1` | mask interval count followed by `(start_minute, duration_minute)` pairs packed into 32-bit words |
| 4 | 2 | rate in `var_a`, derived from counter `var_b` and elapsed duration |
| 5 | 3 | percentage in `var_a`, derived as `var_b / (var_b + var_c)` |
| 6 | 1 | percentile output `var_a` calculated from source `var_b`, gated by `ZLE` |
| 7 | 1 | percentile output `var_a` calculated from source `var_b`, gated by `ZTE` |

The first SummaryRecord is kind 3. The STR writer uses its usage intervals to
emit the fixed `Date`, `MaskOn`, `MaskOff`, and `MaskEvents` fields before the
configured g[15] signal rows.

For kinds 6 and 7, `percentile` is passed directly to the histogram lookup.
The two kinds use the same percentile algorithm and differ in the runtime gate
that enables sample collection.

`spool_enabled` and `edf_enabled` are independent. Setting rows are commonly
excluded from the `Summary` spool while remaining enabled in STR; summary
metrics are commonly enabled in both. `HeatedTube` and `Humidifier` are kind 0
snapshots enabled in both outputs.

Enabled SummaryRecord counts:

| Version | VID | Summary spool | STR EDF | Total |
|---------|----:|--------------:|--------:|------:|
| 11.8.0.1 | 13 | 62 | 129 | 142 |
| 14.8.3.0 | 3 | 51 | 74 | 190 |
| 15.8.4.0 | 3 | 53 | 74 | 192 |
| 15.8.4.0 | 7 | 59 | 92 | 192 |
| 15.8.4.0 | 10 | 56 | 93 | 192 |
| 15.8.4.0 | 12 | 51 | 70 | 192 |
| 16.8.5.0 | 3 | 53 | 74 | 190 |
| 16.8.5.0 | 6 | 58 | 90 | 190 |
| 17.8.6.0 | 3 | 53 | 74 | 190 |
| 17.8.6.0 | 6 | 58 | 90 | 190 |

Active families in 15.8.4.0:

| VID | Family |
|----:|--------|
| 3 | AutoSet-*, HerAuto-*, AutoSetComfort, Summary-ReraIndex, central-apnea and CSR summaries |
| 7 | Spont-*, VAuto-*, SpontTriggerPercentage, SpontCyclePercentage, IeRatio-*, InspiratoryDuration-* |
| 10 | Spont-*, ST-*, Timed-*, IeRatio-*, InspiratoryDuration-* |
| 12 | ASV-*, ASVAuto-* |

---

## g[16] -- EDF stream file schemas

Firmware through 8.5.0 contains three stream/file headers (`BRP`, `SA2`, and
`PLD`). Firmware 8.6.0 adds `TCV` as a fourth header.

| APPX | Header count |
|------|-------------:|
| 8.0.1 through 8.5.0 | 3 |
| 8.6.0 | 4 |

The count is compiled into the APPX sampled-EDF pipeline; it is not stored in
the CONF rows.


### StreamFileHeader

| Offset | Size | Field | Description |
|--------|------|-------|-------------|
| +0x00 | 2 | period_ms | collection period for each signal sample |
| +0x02 | 2 | samples_per_record | samples of each signal in one EDF data record |
| +0x04 | 2 | signal_count | zero disables the file schema |
| +0x06 | 2 | reserved | zero |
| +0x08 | 4 | tag_string_ptr | EDF file-class tag |
| +0x0c | 4 | signal_record_ptr | StreamSignal table pointer |

### StreamSignal

| Offset | Size | Field | Description |
|--------|------|-------|-------------|
| +0x00 | 2 | var_id | source DataItem |
| +0x02 | 2 | reserved | zero |
| +0x04 | 4 | name ptr | EDF signal label |
| +0x08 | 4 | unit ptr | EDF physical unit |
| +0x0c | 4 | physical_scale (f32) | EDF physical scaling metadata |

At each `period_ms` tick, the collector reads the current raw value of every
source DataItem. An unavailable value is recorded as digital `-1`; available
values are stored as signed 16-bit raw samples. Names, units, and
`physical_scale` populate the EDF signal headers and do not rescale samples
during collection.

The collector produces chunks containing one tenth of an EDF data record. The
writer combines ten chunks into one record. In stock schemas,
`period_ms * samples_per_record` is 60000 ms, so each record spans one minute.
The record contains
`(signal_count * samples_per_record + 1) * 2` bytes; the final i16 is its CRC.
A partial record is discarded when the recording gate closes rather than
padded. Recording is enabled while `ZLE` is 1, SD logging is enabled by `SDS`
bit 4, and `CDT` is 1.

### Stable signals (all variants)

| File | period_ms | samples | count | Signals |
|------|----------:|--------:|------:|---------|
| BRP | 40 | 1500 | 2 | Flow.40ms (L/s, scale 500), Press.40ms (cmH2O, scale 50) |
| SA2 | 1000 | 60 | 2 | Pulse.1s (bpm, scale 1), SpO2.1s (%, scale 1) |

### TCV content

The `TCV` header is present from firmware 8.6.0. It has no signal in the stock
vid03 schema and one signal in the vid06 schema.

| File | period_ms | samples | count | Signals |
|------|----------:|--------:|------:|---------|
| TCV | 40 | 1500 | 0 or 1 | TrigCycEvt.40ms (--, scale 1; source g[5] `BYV`) when active |

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

| Release / VID | PLD count | Delta from vid03 base set |
|---------------|----------:|---------------------------|
| 11.8.0.1 vid13 | 12 | + TgtVent.2s, IERatio.2s, Ti.2s |
| 14.8.3.0 through 17.8.6.0 vid03 | 9 | -- |
| 15.8.4.0 vid07; 16.8.5.0/17.8.6.0 vid06 | 11 | + IERatio.2s, Ti.2s |
| 15.8.4.0 vid10 | 10 | drops FlowLim.2s; + IERatio.2s, Ti.2s |
| 15.8.4.0 vid12 | 10 | + TgtVent.2s |

---

## g[17] -- event label tables

These headers bind event values to EDF annotation labels and configure the
annotation writer.

| APPX | Schema count | Layout |
|------|-------------:|--------|
| 8.0.1 | 2 | 20-byte legacy records |
| 8.3.0 and later | 3 | 28-byte current records |

The count and record layout are selected by the APPX annotation-writer
pipeline; neither is stored in a separate CONF header.

### 28-byte layout

Firmware from 14.8.3.0 uses 28-byte records:

| Offset | Size | Field | Description |
|--------|------|-------|-------------|
| +0x00 | 2 | event_record_bytes | maximum source event record size |
| +0x02 | 2 | label_count | number of annotation-label pointers |
| +0x04 | 2 | edf_record_bytes | complete annotation-channel record size |
| +0x06 | 2 | reserved | zero |
| +0x08 | 4 | fifo_capacity | number of source event records |
| +0x0c | 1 | writer_enabled | nonzero constructs the writer |
| +0x0d | 1 | subtract_duration_from_onset | treats the u16 event value as onset backdate |
| +0x0e | 2 | reserved | zero |
| +0x10 | 4 | tag_ptr (`EVE`, `AEV`, or `CSL`) | EDF annotation file-class tag |
| +0x14 | 4 | constant_14 | `1` |
| +0x18 | 4 | label_table_ptr (`char **`) | annotation-label pointer table |

### Legacy layout

11.8.0.1 uses two 20-byte records (`EVE` and `CSL`):

| Offset | Size | Field |
|--------|------|-------|
| +0x00 | 2 | label_count |
| +0x02 | 2 | edf_record_bytes |
| +0x04 | 4 | fifo_capacity |
| +0x08 | 1 | writer_enabled |
| +0x09 | 1 | subtract_duration_from_onset |
| +0x0a | 2 | reserved |
| +0x0c | 4 | tag_ptr |
| +0x10 | 4 | label_table_ptr (`char **`) |

Schemas:

| Tag | Event bytes | EDF bytes | FIFO | Labels |
|-----|------------:|----------:|-----:|--------|
| EVE | 9 | 64 | 4 | 6: "", Hypopnea, Central Apnea, Obstructive Apnea, Apnea, Arousal |
| AEV | 11 | 64 | 4 | 37 alarm and system-error labels |
| CSL | 9 | 64 | 4 | 3: "", CSR Start, CSR End |

`event_record_bytes` is absent from the legacy layout. `AEV` is absent from
11.8.0.1.

The source event record begins with a six-byte timestamp. `EVE` and `CSL`
append an event-label index and a u16 duration/backdate value, producing a
nine-byte record. `AEV` appends an event-label index and a u32 payload,
producing an eleven-byte record. Producers may submit a shorter record, but
the reported size may not exceed `event_record_bytes`.

`writer_enabled` controls construction of the corresponding annotation writer.
For `EVE` and `CSL`, `subtract_duration_from_onset` changes the u16 value from
an EDF annotation duration into a backdate: the writer subtracts it from the
onset and emits zero duration. When the flag is clear, onset remains unchanged
and the value is emitted as the annotation duration. `AEV` uses its dedicated
u32 payload formatter.

`edf_record_bytes` is the complete annotation-channel record size, including
its CRC field. The 28-byte schemas use 64 bytes.

CSL writer configuration:

| Firmware | writer_enabled | subtract_duration_from_onset |
|----------|---------------:|---------------:|
| 11.8.0.1 vid13 | 1 | 1 |
| 14.8.3.0 vid03 | 1 | 1 |
| 15.8.4.0 vid03 | 1 | 1 |
| 15.8.4.0 vid07/10/12 | 0 | 1 |
| 16.8.5.0 vid03 | 1 | 1 |
| 16.8.5.0 vid06 | 0 | 1 |
| 17.8.6.0 vid03 | 1 | 1 |
| 17.8.6.0 vid06 | 0 | 1 |

---

## g[18] -- RPC JSON node permission table

Each RPC JSON node has a two-byte permission record:

```text
permission_offset = g[18] + node_id * 2
```

The low byte controls whether the node may be returned/read. The high byte
blocks writes when nonzero. These are independent gates.

| Value | Meaning |
|-------|---------|
| `0x0000` | read disabled; write not blocked by this table |
| `0x0001` | read enabled; write not blocked by this table |
| `0x0100` | read disabled; write blocked |
| `0x0101` | read enabled; write blocked |

Profile and feature RPC JSON nodes such as `TherapyProfiles`, individual therapy
profiles, and feature nodes become readable when their low byte is set to `1`.
This table is separate from DataItem flags and enum option masks.

The APPX `!NN` schema-reference resolver supplies the table's node count.

| Release | Permission records |
|---------|-------------------:|
| 11.8.0.1 | 135 |
| 14.8.3.0 | 141 |
| 15.8.4.0 | 143 |
| 16.8.5.0 | 144 |
| 17.8.6.0 | 144 |

### RPC node metadata

Node IDs are release-specific. RPC metadata stores each name and node ID as a
12-byte record:

| Offset | Size | Field |
|--------|------|-------|
| +0x00 | 4 | node_name_string_ptr |
| +0x04 | 4 | "!<node_id>" string_ptr |
| +0x08 | 4 | `0x00007fff` |

### Therapy profile node IDs

| Node | 14.8.3.0 | 15.8.4.0 | 16.8.5.0 | 17.8.6.0 |
|------|---------:|---------:|---------:|---------:|
| ASVAutoProfile | `0x61` | `0x63` | `0x64` | `0x64` |
| ASVProfile | `0x62` | `0x64` | `0x65` | `0x65` |
| AutoSetForHerProfile | `0x63` | `0x65` | `0x66` | `0x66` |
| AutoSetProfile | `0x64` | `0x66` | `0x67` | `0x67` |
| CpapProfile | `0x65` | `0x67` | `0x68` | `0x68` |
| PACProfile | `0x66` | `0x68` | `0x69` | `0x69` |
| STProfile | `0x67` | `0x69` | `0x6a` | `0x6a` |
| SpontProfile | `0x68` | `0x6a` | `0x6b` | `0x6b` |
| TimedProfile | `0x69` | `0x6b` | `0x6c` | `0x6c` |
| VAutoProfile | `0x6a` | `0x6c` | `0x6d` | `0x6d` |
| iVAPSProfile | `0x6b` | `0x6d` | `0x6e` | `0x6e` |

### Feature profile node IDs

| Node | 14.8.3.0 | 15.8.4.0 | 16.8.5.0 | 17.8.6.0 |
|------|---------:|---------:|---------:|---------:|
| ConfirmStopFeature | `0x4d` | `0x4f` | `0x50` | `0x50` |
| HeightFeature | `0x51` | `0x53` | `0x54` | `0x54` |
| RampDownFeature | `0x55` | `0x57` | `0x58` | `0x58` |
| TherapyLEDFeature | `0x5d` | `0x5f` | `0x60` | `0x60` |

### Alarm profile node IDs

| Node | 14.8.3.0 | 15.8.4.0 | 16.8.5.0 | 17.8.6.0 |
|------|---------:|---------:|---------:|---------:|
| AlarmProfiles | `0x40` | `0x42` | `0x43` | `0x43` |
| AlarmVolume | `0x41` | `0x43` | `0x44` | `0x44` |
| ApneaAlarm | `0x42` | `0x44` | `0x45` | `0x45` |
| HighLeakAlarm | `0x43` | `0x45` | `0x46` | `0x46` |
| LowMinuteVentAlarm | `0x44` | `0x46` | `0x47` | `0x47` |
| NonVentedMaskAlarm | `0x45` | `0x47` | `0x48` | `0x48` |

Example -- `AutoSetProfile` in 16.8.5.0:

| Step | Value |
|------|-------|
| APPL metadata value | `!103` |
| node_id | `103` / `0x67` |
| Permission offset | `g[18] + 0x67 * 2` = file offset `0x02b5de` |
| Permission value | `0x0001` (read enabled) |

---

## g[19] -- ConfigurationProfiles change-watch list

g[19] selects the DDO settings watched by the configuration-profile change
tracker. The list contains the profile-source fields `CP1` and `CP2` plus the
data-delivery controls that enable or disable individual spool families.

The DDO settings group uses the list as follows:

1. After loading DDO, firmware records the current values as its baseline.
2. Before a DDO write, it serializes every active g[19] DataItem and compares
   the resulting CRC with the baseline CRC.
3. A changed CRC sets `CP3` to the current time and marks the configuration
   profile dirty.
4. Completion of the DDO write increments `CCC`.
5. The data-collection/send manager observes `CCC` as one of its wake-up
   triggers.

`ConfigurationProfilesCollection` uses `CP3` as `AppliedDateTime`, `CP1` as
the source string, and `CP2` as the transaction value. Its
`DataDeliveryControlV2` body contains 25 delivery-control states selected by
the APPL formatter. The formatter's 25-field layout is defined separately in
APPL.

For example, changing `DDP`, the delivery state for
`TherapyOneMinutePeriodic`, changes the g[19] snapshot. The completed DDO write
records the change time in `CP3`, advances `CCC`, and wakes the data-collection
manager. A subsequent `ConfigurationProfilesCollection` record reports the
new `TherapyOneMinutePeriodic` state.

| Offset | Size | Field |
|--------|------|-------|
| +0x00 | 4 | var_id_list_ptr (`u16[]`) |
| +0x04 | 1 | count |
| +0x05 | 3 | reserved |

For change comparison, active volatile-text DataItems are serialized as text
and the other active DataItems as raw values. The serializer finalizes a
zero-filled `0x7fa`-byte buffer, and firmware compares its CRC-32/ISO-HDLC
(`0xedb88320` reflected polynomial, init and xorout `0xffffffff`).

| Release | Source count |
|---------|-------------:|
| 11.8.0.1 | absent |
| 14.8.3.0 | 28 |
| 15.8.4.0 | 29 |
| 16.8.5.0 | 29 |
| 17.8.6.0 | 29 |

The ordered 14.8.3.0 source list is:

```text
CP1 CP2 DDN DDP DOP DMM DUE DTE DDE DDY DEE DDS DAS DCA DGA SVA DSV
DMA DTP DAV DUC DEG DEI DRF DMP DML DIP DCP
```

Firmware 15.8.4.0 and later insert `ADP` immediately before `DCP`; the other
source tags retain their order. Var IDs are release-specific.

`ADP` is source entry 27 (`0x038a` in 16.8.5.0 and `0x0390` in 17.8.6.0) and
provides the `DataDeliveryControlV2.atmosphericPressure10min` state (protobuf
field 26). It is inactive in vid03 and vid06.

---

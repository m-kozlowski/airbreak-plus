# as11_descriptors

Offline CONF and descriptor explorer for AirSense 11 / AirCurve 11 firmware
images.

Use this tool to inspect variable descriptors, option masks, per-mode baseline
visibility, EDF metadata, event tables, persisted setting sets, and localized
GUI text. It does not connect to a device. Read commands do not modify
firmware; `edit` writes a separate output image and never overwrites the input
image.

## Output

Most listing commands emit one record per line using `key=value` fields
separated by `|`. This keeps the default output readable and easy to parse
with shell tools.

```
array=g5|idx=220|off=0x027FE0|addr=0x08027FE0|var=0x0420|short=MOP|long=ActiveTherapyProfile|flags=0x0607|flag_names=ACT,VIS,MOD,RPC,RPW|linked_counter=0x0113|event_queue=0x17|data_rule=0x34|default_option=1|option_count=11|option_mask=0x00000007|enabled_options=0,1,2|reserved=0x0000
```

`flag_names` uses `ACT`, `VIS`, `MOD`, `SGN`, `INH`, `VAL`, `ULK`, `RAW`,
`MON`, `RPC`, `RPW`, and `PST`. See the
[CONF flags field](../as11/conf_block_format.md#flags-field) for their full
meanings.

Use `--verbose` on commands that support it for multi-line details.

## Commands

### info

Show firmware and component identifiers, enabled therapy modes, and the
default language configuration.

```
as11_descriptors.py firmware.bin info
```

### var

Show one or more variable descriptors by numeric var id, long name, short tag,
or underscored short tag. Results follow the input order.

```
as11_descriptors.py firmware.bin var 0x0420
as11_descriptors.py firmware.bin var MOP
as11_descriptors.py firmware.bin var _MOP
as11_descriptors.py firmware.bin var MOP LNC AutoSet-MaxPressure
as11_descriptors.py firmware.bin var ActiveTherapyProfile --verbose
```

Bare numeric values are decimal. Use `0x` for hexadecimal.

### vars

List descriptor records. By default it scans `g1`, `g2`, `g3`, and `g5`.

```
as11_descriptors.py firmware.bin vars
as11_descriptors.py firmware.bin vars --array g5
as11_descriptors.py firmware.bin vars --array all
as11_descriptors.py firmware.bin vars --name Ramp
```

### var-options

Show option slots for an enum descriptor from `g5`. The output includes the
raw option index, enabled/default state, and resolved enum symbol when
available.

```
as11_descriptors.py firmware.bin var-options MOP
as11_descriptors.py firmware.bin var-options VAuto-CycleSensitivity
```

### edit

Edit one or more CONF descriptor fields and write a new firmware image.

```
as11_descriptors.py firmware.bin edit -o edited.bin \
    RMA.option_mask=0x7 PA0.default=5.0
```

Assignments use `VAR.FIELD=VALUE`. `VAR` may be a numeric var id, long name,
short tag, or underscored short tag. The command validates the input `CONF`
CRC, applies all assignments in memory, updates the `CONF` CRC, reloads the
modified image, and verifies the stored values before writing output.

Use `--dry-run` to validate and display the result without writing a file. Use
`--overwrite` to replace an existing output file. Use `--ignore-input-crc` for
research on an image whose `CONF` CRC is already invalid.

Editable descriptor arrays are `g1`, `g2`, `g3`, and `g5`. For variables that
have a `globals[10]` row, `FIELD=visibility` edits the per-mode baseline
visibility bytes. Run `edit --help` for the accepted fields.

Numeric `g2` fields `default`, `min`, `max`, and `step` use descriptor display
scaling:

```
PA0.default=5.0
PA0.default_raw=250
```

If `scale` and a scaled field are changed in one command, the scaled field uses
the new scale. Values that cannot be represented exactly are rejected.

### mode

List variables with baseline visibility in one therapy mode and variables in
that mode's long-name namespace. Runtime callbacks can further change
effective visibility.

```
as11_descriptors.py firmware.bin mode
as11_descriptors.py firmware.bin mode VAuto
as11_descriptors.py firmware.bin mode 6
as11_descriptors.py firmware.bin mode 0xa
```

Without an argument, `mode` lists the known modes. `baseline_variables` and
`name_scoped_variables` are counted independently; `total_variables` is their
union.

Known mode indexes:

| Index | Mode |
|-------|------|
| 0 | CPAP |
| 1 | AutoSet |
| 2 | HerAuto |
| 3 | Spont |
| 4 | ST |
| 5 | Timed |
| 6 | VAuto |
| 7 | ASV |
| 8 | ASVAuto |
| 9 | iVAPS |
| 10 | PAC |

### data-rules

Reconstruct the APPL DataItem rule callback registry and join each rule to the
CONF descriptors that use it.

```
as11_descriptors.py firmware.bin data-rules
as11_descriptors.py firmware.bin data-rules 0x34
```

`callback` is the normalized Thumb code address. `registration` identifies a
static registration table or a direct registration call, while `source_off`
is its firmware file offset. Optional positional arguments select rule IDs.

### bounds-slots

List the APPL runtime numeric-bounds slots and the g[2] descriptors assigned to
them.

```
as11_descriptors.py firmware.bin bounds-slots
as11_descriptors.py firmware.bin bounds-slots 0x21
```

The firmware initializes each slot from its assigned descriptor during
startup. `seed_*` identifies the last descriptor written to the slot and its
initial min/max pair. Runtime limit-update paths may subsequently replace
either bound. A slot with `use_count=0` is not initialized from CONF; this can
occur after a patch moves its former user to static descriptor bounds.

### globals / conf-layout

Inspect the CONF `globals[]` roots, dump one globals object, or list each root
object with its type-specific decoded size.

```
as11_descriptors.py firmware.bin globals
as11_descriptors.py firmware.bin globals 5
as11_descriptors.py firmware.bin conf-layout
```

Each index is decoded according to its CONF structure:

| Index | Decoder |
|-------|---------|
| `0` | CONF header |
| `1`, `2`, `3`, `5`, `10` | variable descriptors |
| `4` | bitfield GUI message-selection order |
| `6` | external-NOR SettingsGroup schemas |
| `7` | PDL backup-SRAM snapshot members |
| `8` | short-name buckets |
| `9` | short-name reverse table |
| `11` | `g[10]` record count |
| `12` | event spool definitions |
| `13` | event payload types |
| `14` | periodic collections |
| `15` | complete STR.edf schema |
| `16` | EDF stream schemas |
| `17` | event label tables |
| `18` | RPC JSON node permissions |
| `19` | configuration fingerprint sources |

### edf-str

List STR.edf `SummaryRecord` rows.

```
as11_descriptors.py firmware.bin edf-str
as11_descriptors.py firmware.bin edf-str --all
as11_descriptors.py firmware.bin edf-str --inactive
as11_descriptors.py firmware.bin edf-str --name HeartRate
```

### edf-streams

List EDF stream schemas from `globals[16]`. Optional positional arguments
filter by stream tag. A present header with zero signals is emitted as a
header-only record.

```
as11_descriptors.py firmware.bin edf-streams
as11_descriptors.py firmware.bin edf-streams BRP
as11_descriptors.py firmware.bin edf-streams BRP PLD --verbose
```

### events / event-payload-types / event-labels

Inspect event spool definitions, per-event `EventNotification` JSON payload
rules, and EDF annotation label tables.

```
as11_descriptors.py firmware.bin events
as11_descriptors.py firmware.bin events Pressure
as11_descriptors.py firmware.bin events --verbose
as11_descriptors.py firmware.bin event-payload-types RespiratoryEvents
as11_descriptors.py firmware.bin event-labels EVE CSL
```

`event-labels` detects both supported g[17] schema layouts and reports the
schema size, record sizes, FIFO capacity, writer/backdating flags, and labels.

These tables are useful when mapping `SubscribeEvent` selectors and spool/event
payload names used by `as11_config.py`.

### collections

List periodic collection tables from `globals[14]`. Default output contains
one line per signal with its source DataItem, clamps, quantization step,
encoded scale, codec class, and prefix flag. `--verbose` also emits collection
timing, buffering, g[5] gate, file-initialization flag, and reset class.

```
as11_descriptors.py firmware.bin collections
as11_descriptors.py firmware.bin collections NRF APD
as11_descriptors.py firmware.bin collections NRF --verbose
```

### storage-sets

List the external-NOR `SettingsGroup` schemas defined by `globals[6]`, including
their candidate DataItems and associated g[2] update counters. Active members
are stored in `nor:0:\\SETTINGS\\<name>.set`, for example `HST.set` and
`BGL.set`.

```
as11_descriptors.py firmware.bin storage-sets
as11_descriptors.py firmware.bin storage-sets HST BGL
as11_descriptors.py firmware.bin storage-sets --names-only
```

### text / text-search

Decode localized GUI text strings from the firmware's compressed text tables.

```
as11_descriptors.py firmware.bin text 0x151 --lang en
as11_descriptors.py firmware.bin text 0x151 --lang pl
as11_descriptors.py firmware.bin text-search humidifier --lang en
```

Both commands emit one `key=value` record per matching text.

`--lang` accepts a numeric language index or a short language code such as
`en`, `de`, `pl`, `ru`, `es-us`, or `pt-br`.

## Interactive Mode

Use `-i` to keep the firmware image loaded and run repeated descriptor queries.

```
as11_descriptors.py firmware.bin -i
```

Inside the shell, use the same command names without repeating the firmware
path:

```
as11> var MOP
as11> var-options MOP
as11> text-search ramp --lang en
as11> quit
```

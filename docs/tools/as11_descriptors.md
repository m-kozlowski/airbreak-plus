# as11_descriptors

## Name

`as11_descriptors.py` - inspect and edit Air11 CONF descriptors offline.

## Contents

- [Synopsis](#synopsis)
- [Description](#description)
- [Arguments](#arguments)
- [Options](#options)
- [Commands](#commands)
  - [info](#info)
  - [var](#var)
  - [vars](#vars)
  - [var-options](#var-options)
  - [edit](#edit)
  - [mode](#mode)
  - [data-rules](#data-rules)
  - [bounds-slots](#bounds-slots)
  - [globals / conf-layout](#globals--conf-layout)
  - [edf-str](#edf-str)
  - [edf-streams](#edf-streams)
  - [events / event-payload-types / event-labels](#events--event-payload-types--event-labels)
  - [collections](#collections)
  - [storage-sets](#storage-sets)
  - [text / text-search](#text--text-search)
- [Interactive Mode](#interactive-mode)
- [Output](#output)
- [Exit Status](#exit-status)
- [Examples](#examples)
- [See Also](#see-also)

## Synopsis

```text
as11_descriptors.py FIRMWARE [COMMAND [ARGUMENTS] [OPTIONS]]
as11_descriptors.py FIRMWARE -i
```

## Description

Decodes CONF structures, variable descriptors, enum options, per-mode visibility,
EDF schemas, event payloads, periodic collections, storage sets, and localized
GUI text. Resolves variable IDs, short tags, and long names, and connects
descriptors to APPL DataItem rules and runtime numeric-bounds slots.

Edits defaults, numeric limits, steps, scaling, flags, enum permissions, and
per-mode visibility. Validates changes and updates the CONF checksum when
writing the modified firmware image.

## Arguments

`FIRMWARE`: raw firmware image to inspect or edit.

Bare numeric arguments are decimal; `0x` denotes hexadecimal.

## Options

`-i`, `--interactive` opens the [interactive shell](#interactive-mode).
`-h`, `--help` shows global or command-specific help. Other options follow the
command to which they apply.

## Commands

The default command is `info`.

### info

```text
info
```

Show firmware and component identifiers, enabled therapy modes, and the
default language configuration.

```sh
as11_descriptors.py firmware.bin info
```

### var

```text
var VAR[.FIELD] ... [--verbose]
```

Show one or more variable descriptors. Each `VAR` is a numeric variable ID,
long name, short tag, or underscored short tag. Results follow the input order.
Append a field name from [edit](#edit) to print just its value. For numeric
fields such as `min` and `step`, use `min_raw` or `step_raw` for the stored
integer. For enums, `default` is the default option index.

| Option | Meaning | Default |
|--------|---------|---------|
| `--verbose` | Multi-line details | Off |

```sh
as11_descriptors.py firmware.bin var 0x0420 _MOP AutoSet-MaxPressure
as11_descriptors.py firmware.bin var tss.default RRR.visibility
as11_descriptors.py firmware.bin var ActiveTherapyProfile --verbose
```

### vars

```text
vars [--array ARRAY] [--name REGEX] [--verbose]
```

List descriptor records from the selected arrays.

| Option | Meaning | Default |
|--------|---------|---------|
| `--array ARRAY` | `g1`, `g2`, `g3`, `g5`, `g10`, or `all` | `all` (g1/g2/g3/g5) |
| `--name REGEX` | Case-insensitive filter over resolved names | No filter |
| `--verbose` | Multi-line details | Off |

```sh
as11_descriptors.py firmware.bin vars --array g5
as11_descriptors.py firmware.bin vars --name Ramp
```

### var-options

```text
var-options VAR [--verbose]
```

Show option slots for an enum descriptor from `g5`. The output includes the
raw option index, enabled/default state, and resolved enum symbol when
available; `VAR` is a numeric ID, long name, short tag, or underscored tag.

| Option | Meaning | Default |
|--------|---------|---------|
| `--verbose` | Multi-line enum details | Off |

```sh
as11_descriptors.py firmware.bin var-options MOP
as11_descriptors.py firmware.bin var-options VAuto-CycleSensitivity
```

### edit

```text
edit VAR.FIELD=VALUE ... [OPTIONS]
```

Edit one or more CONF descriptor fields and write a new firmware image.

Assignments use `VAR.FIELD=VALUE`. `VAR` may be a numeric var id, long name,
short tag, or underscored short tag. The command validates the input `CONF`
CRC, applies assignments, updates the `CONF` CRC, and reparses the result to
verify stored values before writing. The input image is never overwritten,
including with `--overwrite` or `--ignore-input-crc`.

| Option | Meaning | Default |
|--------|---------|---------|
| `-o`, `--output FILE` | Output image; required unless `--dry-run` | None |
| `--dry-run` | Validate and preview changes | Off |
| `--overwrite` | Replace an existing output file | Off |
| `--ignore-input-crc` | Accept an invalid input CONF CRC | Off |

Editable descriptor arrays are `g1`, `g2`, `g3`, and `g5`. For variables that
have a `globals[10]` row, `FIELD=visibility` edits the per-mode baseline
visibility bytes. Run `edit --help` for the accepted fields.

Numeric `g2` fields `default`, `min`, `max`, and `step` use display scaling;
fields with a `_raw` suffix use raw integers. For example, `PA0.default=5.0`
sets 5 cmH2O, while `PA0.default_raw=250` stores the integer 250.

If `scale` and a scaled field are changed in one command, the scaled field uses
the new scale. Values that cannot be represented exactly are rejected.

```sh
as11_descriptors.py firmware.bin edit -o edited.bin \
    RMA.option_mask=0x7 PA0.default=5.0
```

### mode

```text
mode [MODE]
```

List variables with baseline visibility in one therapy mode and variables in
that mode's long-name namespace. Runtime callbacks can further change
effective visibility.

`MODE` is a mode name or numeric index. The default is to list known modes.
`baseline_variables` and `name_scoped_variables` are counted independently;
`total_variables` is their union.

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

```sh
as11_descriptors.py firmware.bin mode VAuto
as11_descriptors.py firmware.bin mode 0xa
```

### data-rules

```text
data-rules [RULE ...]
```

Reconstruct the APPL DataItem rule callback registry and join each rule to the
CONF descriptors that use it.

`callback` is the normalized Thumb code address. `registration` identifies a
static registration table or a direct registration call, while `source_off`
is its firmware file offset. Each `RULE` selects a numeric rule ID; the default
is to list all rules.

```sh
as11_descriptors.py firmware.bin data-rules 0x34
```

### bounds-slots

```text
bounds-slots [SLOT ...]
```

List the APPL runtime numeric-bounds slots and the g[2] descriptors assigned to
them. Each `SLOT` selects a numeric slot index; the default is to list all slots.

The firmware initializes each slot from its assigned descriptor during
startup. `seed_*` identifies the last descriptor written to the slot and its
initial min/max pair. Runtime limit-update paths may subsequently replace
either bound. `use_count` counts assigned descriptors; zero means the slot
receives no CONF initialization, for example after a patch moves its users to
static descriptor bounds.

```sh
as11_descriptors.py firmware.bin bounds-slots 0x21
```

### globals / conf-layout

```text
globals [INDEX]
conf-layout
```

`globals` lists the CONF `globals[]` roots. `INDEX` selects one numeric globals
entry to decode. `conf-layout` lists every root object and its decoded size.

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

```sh
as11_descriptors.py firmware.bin globals 5
as11_descriptors.py firmware.bin conf-layout
```

### edf-str

```text
edf-str [--all | --inactive] [--name REGEX] [--verbose]
```

List STR.edf `SummaryRecord` rows.

| Option | Meaning | Default |
|--------|---------|---------|
| `--all` | Include inactive rows | Off; active rows only |
| `--inactive` | Select only inactive rows | Off |
| `--name REGEX` | Case-insensitive filter over resolved names | No filter |
| `--verbose` | Multi-line details | Off |

```sh
as11_descriptors.py firmware.bin edf-str --all
as11_descriptors.py firmware.bin edf-str --inactive --name HeartRate
```

### edf-streams

```text
edf-streams [TAG ...] [--verbose]
```

List EDF stream schemas from `globals[16]`, selected by case-insensitive
`TAG`; the default is all streams.

| Option | Meaning | Default |
|--------|---------|---------|
| `--verbose` | Include stream headers | Off |

A present header with zero signals is emitted as a header-only record.

```sh
as11_descriptors.py firmware.bin edf-streams BRP PLD --verbose
```

### events / event-payload-types / event-labels

```text
events [FILTER ...] [--verbose]
event-payload-types [FILTER ...]
event-labels [TAG ...]
```

`events` lists event spools, `event-payload-types` lists per-event
`EventNotification` JSON rules, and `event-labels` lists EDF annotation labels.

| Option | Command | Meaning | Default |
|--------|---------|---------|---------|
| `--verbose` | `events` | Multi-line details | Off |

Each `FILTER` is a case-insensitive substring of a code or name; rows matching
any filter are included. The default is all rows.

Each `TAG` selects an annotation table,
such as `EVE` or `CSL`; tags are case-insensitive and the default is all tables.

`event-labels` detects both supported g[17] schema layouts and reports the
schema size, record sizes, FIFO capacity, writer/backdating flags, and labels.

These tables map `SubscribeEvent` selectors and spool/event payload names used
by [as11_config](as11_config.md).

```sh
as11_descriptors.py firmware.bin event-payload-types RespiratoryEvents
as11_descriptors.py firmware.bin event-labels EVE CSL
```

### collections

```text
collections [TAG ...] [--verbose]
```

List periodic collection tables from `globals[14]`. Each `TAG` selects a
collection; tags are case-insensitive and the default is all collections.

| Option | Meaning | Default |
|--------|---------|---------|
| `--verbose` | Add collection timing, buffering, g[5] gate, file-initialization flag, and reset class | Off |

Each signal row includes the source DataItem, clamps, quantization step,
encoded scale, codec class, and prefix flag.

```sh
as11_descriptors.py firmware.bin collections NRF APD
as11_descriptors.py firmware.bin collections NRF --verbose
```

### storage-sets

```text
storage-sets [TAG ...] [--names-only]
```

List the external-NOR `SettingsGroup` schemas defined by `globals[6]`, including
their candidate DataItems and associated g[2] update counters.
Each `TAG` selects a set, case-insensitively; the default is all sets.

| Option | Meaning | Default |
|--------|---------|---------|
| `--names-only` | One row per set: member names, count, and update counter | Off |

Storage paths and active-member selection are in the
[SettingsGroup reference](../as11/conf_block_format.md#g6----external-nor-settingsgroup-schemas).

```sh
as11_descriptors.py firmware.bin storage-sets HST BGL --names-only
```

### text / text-search

```text
text ID [--lang LANG]
text-search QUERY ... [--lang LANG]
```

`text` decodes the numeric GUI text `ID` from compressed firmware text tables;
`text-search` joins `QUERY` words into a case-insensitive substring search.

Both commands emit one `key=value` record per matching text.

| Option | Meaning | Default |
|--------|---------|---------|
| `--lang LANG` | Numeric language index or short code: `en`, `de`, `pl`, `ru`, `es-us`, `pt-br`, etc. | Slot `0` |

```sh
as11_descriptors.py firmware.bin text 0x151 --lang pl
as11_descriptors.py firmware.bin text-search humidifier --lang en
```

## Interactive Mode

`-i` keeps the firmware image loaded across descriptor queries.

Shell commands use the syntax above without the firmware path; `quit` closes
the shell.

```sh
as11_descriptors.py firmware.bin -i
```

## Output

Most listings emit one record per line with `key=value` fields separated by `|`.
Commands with `--verbose` provide multi-line details.

```text
array=g5|idx=220|off=0x027FE0|addr=0x08027FE0|var=0x0420|short=MOP|long=ActiveTherapyProfile|flags=0x0607|flag_names=ACT,VIS,MOD,RPC,RPW|linked_counter=0x0113|event_queue=0x17|data_rule=0x34|default_option=1|option_count=11|option_mask=0x00000007|enabled_options=0,1,2|reserved=0x0000
```

`flag_names` uses `ACT`, `VIS`, `MOD`, `SGN`, `INH`, `VAL`, `ULK`, `RAW`,
`MON`, `RPC`, `RPW`, and `PST`; see the
[CONF flags field](../as11/conf_block_format.md#flags-field).
Errors go to stderr.

## Exit Status

| Status | Meaning |
|--------|---------|
| `0` | Successful command or closed output pipe |
| `1` | Image, lookup, edit, or file error |
| `2` | Invalid command-line syntax |

## Examples

Inspect an enum, edit its permissions, and verify the resulting options:

```sh
as11_descriptors.py firmware.bin var-options RMA
as11_descriptors.py firmware.bin edit RMA.option_mask=0x7 -o edited.bin
as11_descriptors.py edited.bin var-options RMA
```

## See Also

[CONF block format](../as11/conf_block_format.md),
[EDF signals](../as11/edf_signals.md), [resmed_image](resmed_image.md).

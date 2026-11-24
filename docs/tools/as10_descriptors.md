# as10_descriptors

## Name

`as10_descriptors.py` - inspect and edit Air 10 CCX descriptors offline.

## Contents

- [Synopsis](#synopsis)
- [Description](#description)
- [Arguments](#arguments)
- [Options](#options)
- [Commands](#commands)
  - [info](#info)
  - [var](#var)
  - [globals](#globals)
  - [mode](#mode)
  - [channels](#channels)
  - [strid / strinfo / search](#strid--strinfo--search)
  - [chain](#chain)
  - [edit](#edit)
  - [dump-tsv](#dump-tsv)
- [Interactive Mode](#interactive-mode)
- [Output](#output)
- [Exit Status](#exit-status)
- [Examples](#examples)
- [See Also](#see-also)

## Synopsis

```text
as10_descriptors.py FIRMWARE [OPTIONS] [COMMAND [ARGUMENTS]]
as10_descriptors.py FIRMWARE [OPTIONS] -i
```

## Description

Decodes the firmware configuration model: variable descriptors and dependencies,
therapy-mode assignments, EDF and EEPROM recording schemas, storage groups,
persistent-state rules, identity exports, and localized GUI text. Resolves UART
tags to variable IDs and exports descriptor tables as TSV.

Edits defaults, numeric limits, steps, scaling, flags, enum permissions, string
references, and dependency links. Validates changes and updates the CCX
checksum when writing the modified firmware image.

## Arguments

`FIRMWARE`: raw firmware image to inspect or edit.

Bare numeric values are decimal. Use `0x` for hexadecimal.

## Options

Global options precede the command.

| Option | Meaning | Default |
|--------|---------|---------|
| `-i`, `--interactive` | Start the interactive shell | Off |
| `-v`, `--verbose` | Multi-line variable details, including editable field names | Off |
| `--globals ADDRESS` | Override automatic `globals[]` discovery | Auto-detect |
| `-h`, `--help` | Show help | -- |

## Commands

The default command is `info`.

### info

```text
info
```

Show the firmware identity, language set, therapy modes, and variable count.

```sh
as10_descriptors.py firmware.bin info
```

### var

```text
var VAR[.FIELD] ...
```

Show variable descriptors by numeric ID or UART tag. Append a field name from
[edit](#edit) to print just that value. Results follow the input order.
For scaled fields, `MXS.max` gives the display value and `MXS.max_raw` the
stored integer.

For numeric variables the output includes the raw limits, display scaling,
step, units, and dependency-chain link if present. For enum variables it
includes option count, permission mask, option labels, and dependency-chain
head if present.

```sh
as10_descriptors.py firmware.bin var 0x020D
as10_descriptors.py firmware.bin var MOP.default MXS.max MXS.max_raw
as10_descriptors.py firmware.bin --verbose var MOP
```

### globals

```text
globals [SELECTOR ...]
```

Show the `globals[]` pointer map by default. Each `SELECTOR` selects one globals
entry for decoding; multiple selectors are processed in command-line order.

| Selector | Meaning |
|----------|---------|
| `TABLE` | Decode the globals entry at index `TABLE`; indexes are listed below |
| `TABLE:INDEX` | Show one zero-based descriptor row; applies to tables 3, 4, 6, 8, 9, 10 |
| `TABLE:FROM,TO` | Show descriptor rows from `FROM` inclusive to `TO` exclusive; same tables |
| `16:GROUP` | Show one EEPROM variable group by name |
| `22` | List the 16 variable IDs in the [identity TGT export list](../config_variables.md#g22----identity-tgt-export-list), with their UART tags |
| `23` | List all UART tags and their variable IDs |
| `23:QUERY` | Look up a full UART tag, two-character suffix, or numeric variable ID; tags are case-insensitive |

`INDEX`, `FROM`, and `TO` refer to descriptor rows within the selected table.
Use `var VAR` to select a descriptor by variable ID or UART tag.

Decoded globals:

| Index | Content |
|-------|---------|
| `0` | device identity |
| `1` | timer scale table |
| `2` | localized string table summary |
| `3` / `4` / `6` / `8` / `9` | scalar variable descriptor tables |
| `10` | PCC/HPI/HUI hardware-interface vector descriptors |
| `5` | alternate labels for specialized g[4] descriptors |
| `7` | packed g[6] byte-slice pool |
| `11` / `12` / `26` / `27` / `28` | signal channels |
| `13` | STR fields and calculation records, including source variables, percentiles and sampling gates |
| `14` | NPD signals, retained days, file slots, sampling interval and file-size budget parameters |
| `15` | NPA/ALA signals, retained days, file slots, event limits and extra block-header budgets |
| `16` | EEPROM-backed variable groups |
| `17` / `18` | DAC date and TIC time descriptors |
| `19` | EEPROM stream table |
| `20` / `21` | PDL persistent-state list and derived-variable rules |
| `22` | identity TGT export list |
| `23` | UART-name index |
| `24` | therapy-mode setting map |

```sh
as10_descriptors.py firmware.bin globals 0 2 24
as10_descriptors.py firmware.bin globals 8:0,0x10 16:MGL 22 23:OP
```

### mode

```text
mode [MODE]
```

List known therapy modes by default. `MODE` selects one mode by numeric index
or name and lists its mapped variables.

Known mode indexes are taken from the firmware's `MOP` enum.

| Index | Mode |
|-------|------|
| `0` | CPAP |
| `1` | AutoSet |
| `2` | APAP |
| `3` | S |
| `4` | ST |
| `5` | T |
| `6` | VAuto |
| `7` | ASV |
| `8` | ASVAuto |
| `9` | iVAPS |
| `10` | PAC |
| `11` | AutoSet for Her |

```sh
as10_descriptors.py firmware.bin mode 0xa
as10_descriptors.py firmware.bin mode "AutoSet for Her"
```

### channels

```text
channels [NAME]
```

List decoded signal channels. `NAME` selects one channel, such as `BRP` or `STR`.

Channel output maps EDF/live-stream fields to firmware signal descriptors.

```sh
as10_descriptors.py firmware.bin channels
as10_descriptors.py firmware.bin channels BRP
```

### strid / strinfo / search

```text
strid ID [LANG]
strinfo [ID]
search QUERY ...
```

`strid` decodes GUI string `ID`; `LANG` selects a numeric language slot.
`strinfo` shows the raw string-table record and locale pointers for `ID`
(default `0`). `search` joins the `QUERY` words into a descriptor-text search.

`strid` prints all detected languages by default.

```sh
as10_descriptors.py firmware.bin strid 0x000C 0
as10_descriptors.py firmware.bin search ramp time
```

### chain

```text
chain VAR
```

Walk the g[4] numeric dependency chain for variable ID or UART tag `VAR`,
stopping at `0x7FFF` or the firmware depth limit.

Link fields and index semantics are described in the
[dependency-chain reference](../config_variables.md#dependency-chain).

```sh
as10_descriptors.py firmware.bin chain MOP
```

### edit

```text
edit VAR.FIELD=VALUE ... [OPTIONS]
```

Edit one or more variable descriptors and write a new firmware image.

Assignments use `VAR.FIELD=VALUE`. `VAR` may be a UART tag or numeric var ID.
The command checks input BLX, CCX, and CDX checksums, validates assignments,
updates the CCX checksum, and reparses the result to verify stored values
before writing.

| Option | Meaning | Default |
|--------|---------|---------|
| `-o`, `--output FILE` | Output image; required unless `--dry-run` | None |
| `--dry-run` | Validate and preview changes | Off |
| `--overwrite` | Replace an existing output file | Off |
| `--ignore-input-crc` | Accept invalid input checksums | Off |

Editable tables are g[3], g[4], g[6], and g[8]. The command does not resize
tables, allocate strings, or change EEPROM groups and therapy-mode tables.
`edit --help` lists accepted fields; an invalid field reports that type's
accepted names. The input image is never overwritten, including with
`--overwrite` or `--ignore-input-crc`.

Numeric g[4] fields `default`, `min`, `max`, and `step` use display scaling;
fields with a `_raw` suffix use raw integers. For example, `MXS.max=25`
sets 25 cmH2O, while `MXS.max_raw=1250` stores the integer 1250. If `scale` and
a scaled field are changed in one command, the scaled field uses the new scale.
Values must be exactly representable.

Dependency fields accept `none`, a g[4] table index, or the UART name of a
g[4] variable. String fields accept an existing numeric string ID. Flags accept
a numeric mask or a quoted symbolic expression such as `MOP.flags='ACT|VIS|EDT'`.

```sh
as10_descriptors.py firmware.bin edit -o edited.bin \
    MXS.min=0 MXS.max=25 MXS.default=15 \
    MOP.flags='ACT|VIS|EDT' MOP.dependency=RGT
```

### dump-tsv

```text
dump-tsv FILE [--tables TABLE,...]
```

Export descriptor tables to `FILE` (`-` for stdout), including resolved
dependency-chain variable IDs and UART names for g[4] and g[8].
Separate tables include STR calculation records and NPD/NPA/ALA storage
parameters alongside the signal lists and PDL rules.

| Option | Meaning | Default |
|--------|---------|---------|
| `--tables TABLE,...` | Comma-separated descriptor table indexes | `3,4,6,8,9,10` |

```sh
as10_descriptors.py firmware.bin dump-tsv descriptors.tsv
as10_descriptors.py firmware.bin dump-tsv - --tables 4,8
```

## Interactive Mode

`-i` keeps the firmware image loaded across descriptor queries.

Inside the shell, use the same command names without repeating the firmware
path; `quit` closes the shell. Firmware editing is available only as a
non-interactive command.

```sh
as10_descriptors.py firmware.bin -i
```

## Output

Most listings emit one record per line. `--verbose var` prints multi-line
details and accepted `edit` fields.

```text
0x000 var=0x020D:MOP @0x08008584 +0x0000  fl=0x0007 [ACT|VIS|EDT]  def=1  opts=12  perm=0x00000003  dep=[4]0x0173->0x0191:SGT "Mode"
```

`dump-tsv` writes TSV to its output path or stdout (`-`). Errors go to stderr.

## Exit Status

| Status | Meaning |
|--------|---------|
| `0` | Successful command or closed output pipe |
| `1` | Image, lookup, edit, or file error |
| `2` | Invalid command-line syntax |

## Examples

Inspect a descriptor, edit its limit, and inspect the result:

```sh
as10_descriptors.py firmware.bin --verbose var MXS
as10_descriptors.py firmware.bin edit MXS.max=25 -o edited.bin
as10_descriptors.py edited.bin --verbose var MXS
```

## See Also

[Air 10 configuration variables](../config_variables.md),
[resmed_image](resmed_image.md), [resmed_config](resmed_config.md).

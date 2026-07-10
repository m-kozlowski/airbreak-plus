# as10_descriptors

Offline CCX descriptor explorer for AirSense 10 / AirCurve 10 firmware images.

Use this tool to inspect variable descriptors, option masks, therapy-mode
tables, EDF metadata, variable groups, dependency chains, and localized GUI
text. It does not connect to a device and does not modify the input image.

## Output

Most listing commands emit one record per line. Default `var` and table output
is compact and intended for scanning with shell tools.

```
0x000 var=0x020D:MOP @0x08008584 +0x0000  fl=0x0007 [ACT|VIS|EDT]  def=1  opts=12  perm=0x00000003  dep=[4]0x0173->0x0191:SGT "Mode"
```

Use `--verbose` with `var` for multi-line details.

Bare numeric values are decimal. Use `0x` for hexadecimal.

## Commands

### info

Show the firmware identity, language set, loaded `globals[]` tables, and
variable count.

```
as10_descriptors.py firmware.bin info
```

### var

Show one variable descriptor by numeric var id or UART tag.

```
as10_descriptors.py firmware.bin var 0x020D
as10_descriptors.py firmware.bin var MOP
as10_descriptors.py firmware.bin --verbose var MOP
```

For numeric variables the output includes the raw limits, display scaling,
step, units, and dependency-chain link if present. For enum variables it
includes option count, permission mask, option labels, and dependency-chain
head if present.

### globals

Show the `globals[]` pointer map, or decode selected globals entries.

```
as10_descriptors.py firmware.bin globals
as10_descriptors.py firmware.bin globals 0 2 24
as10_descriptors.py firmware.bin globals 8
as10_descriptors.py firmware.bin globals 8:0,0x10
as10_descriptors.py firmware.bin globals 16:MGL
as10_descriptors.py firmware.bin globals 22:OP
as10_descriptors.py firmware.bin globals 22:header
as10_descriptors.py firmware.bin globals 23:MOP
```

For descriptor tables `g[3]`, `g[4]`, `g[6]`, `g[8]`, `g[9]`, and `g[10]`,
the form is:

```
globals TABLE
globals TABLE:IDX
globals TABLE:FROM,TO
```

Useful decoded globals:

| Index | Content |
|-------|---------|
| `0` | device identity |
| `1` | timer scale table |
| `2` | localized string table summary |
| `3` / `4` / `6` / `8` / `9` | scalar variable descriptor tables |
| `10` | PCC/HPI/HUI hardware-interface vector descriptors |
| `5` | alternate labels for specialized g[4] descriptors |
| `7` | packed g[6] byte-slice pool |
| `11` / `12` / `13` / `26` / `27` / `28` | signal channels |
| `14` / `15` | NIGHT_PROFILE_PERIODIC and NPA/ALA aperiodic signal groups |
| `16` | EEPROM-backed variable groups |
| `17` / `18` | DAC date and TIC time descriptors |
| `19` | EEPROM stream table |
| `20` / `21` | PDL persistent-state list and derived-variable rules |
| `22` | identity TGT export list |
| `23` | UART-name index |
| `24` | therapy-mode setting map |

Use `--globals 0xADDR` if automatic `globals[]` discovery fails.

### mode

List variables mapped to one therapy mode.

```
as10_descriptors.py firmware.bin mode 1
as10_descriptors.py firmware.bin mode 0xa
as10_descriptors.py firmware.bin mode AutoSet
as10_descriptors.py firmware.bin mode "AutoSet for Her"
```

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

### channels

List decoded signal channels, or show one channel by name.

```
as10_descriptors.py firmware.bin channels
as10_descriptors.py firmware.bin channels BRP
as10_descriptors.py firmware.bin channels STR
```

This is useful when mapping EDF/live-stream fields back to firmware signal
descriptors.

### strid / strinfo / search

Decode localized GUI strings and search descriptor text.

```
as10_descriptors.py firmware.bin strid 0x000C
as10_descriptors.py firmware.bin strid 0x000C 0
as10_descriptors.py firmware.bin strinfo 0x000C
as10_descriptors.py firmware.bin search ramp time
```

`strid` without a language prints all detected languages. With a language
argument it prints that numeric language slot only. `strinfo` shows the raw
string table record and locale pointers.

### chain

Walk a variable descriptor's dependency chain into g[4] numeric variables.

```
as10_descriptors.py firmware.bin chain MOP
as10_descriptors.py firmware.bin chain 0x020D
```

For g[3], g[6], and g[8], the chain starts at descriptor offset `+0x04`. For a
g[4] source, `+0x04` is already its next link. These fields contain g[4]
indexes, not var IDs. Each g[4] record follows its own `+0x04` link until
`0x7FFF` or the firmware depth limit.

### dump-tsv

Write descriptor tables as TSV for spreadsheets or diffing between firmware
versions.

```
as10_descriptors.py firmware.bin dump-tsv descriptors.tsv
as10_descriptors.py firmware.bin dump-tsv descriptors.tsv --tables 4,8
as10_descriptors.py firmware.bin dump-tsv - --tables 8
```

Default tables are `3,4,6,8,9,10`. The g[4] and g[8] TSV output includes
resolved dependency-chain var ids and UART names.

## Interactive Mode

Use `-i` to keep the firmware image loaded and run repeated descriptor queries.

```
as10_descriptors.py firmware.bin -i
```

Inside the shell, use the same command names without repeating the firmware
path:

```
as10> var MOP
as10> globals 8:0,4
as10> mode ASV
as10> chain MOP
as10> quit
```

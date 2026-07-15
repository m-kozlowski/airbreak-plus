# as11_descriptors

Offline CONF and descriptor explorer for AirSense 11 / AirCurve 11 firmware
images.

Use this tool to inspect variable descriptors, option masks, therapy-mode
gates, EDF metadata, event tables, persisted setting sets, and localized GUI
text. It does not connect to a device and does not modify the input image.

## Output

Most listing commands emit one record per line using `key=value` fields
separated by `|`. This keeps the default output readable and easy to parse
with shell tools.

```
array=g5|idx=220|off=0x027FE0|addr=0x08027FE0|var=0x0420|short=MOP|long=ActiveTherapyProfile|act=ACT
```

Use `--verbose` on commands that support it for multi-line details.

## Commands

### info

Show the firmware identity, CONF master table address, descriptor array sizes,
name table status, and lazy-discovery status for optional data.

```
as11_descriptors.py firmware.bin info
```

### versions

Extract firmware version identifiers without disassembly. The output includes
the CONF data/platform/variant fields, bootloader version, APPX version, and
data-model identifier where present.

```
as11_descriptors.py firmware.bin versions
as11_descriptors.py firmware.bin versions fgbl
as11_descriptors.py firmware.bin versions bootloader
as11_descriptors.py firmware.bin versions fgcb
as11_descriptors.py firmware.bin versions conf
as11_descriptors.py firmware.bin versions appx
```

Example:

```
kind=appx|version=8.5.0.9cd562102|identifier=SW04600.16.8.5.0.9cd562102|offset=0x1FFCF8
```

### var

Show one variable descriptor by numeric var id, long name, short tag, or
underscored short tag.

```
as11_descriptors.py firmware.bin var 0x0420
as11_descriptors.py firmware.bin var MOP
as11_descriptors.py firmware.bin var _MOP
as11_descriptors.py firmware.bin var ActiveTherapyProfile --verbose
```

Bare numeric values are decimal. Use `0x` for hexadecimal.

### vars

List descriptor records. By default it scans `g1`, `g2`, `g3`, and `g5`.

```
as11_descriptors.py firmware.bin vars
as11_descriptors.py firmware.bin vars --array g5 --active
as11_descriptors.py firmware.bin vars --array all --inactive
as11_descriptors.py firmware.bin vars --name Ramp
```

### var-options

Show option slots for an enum descriptor from `g5`. The output includes the
option index, enabled/default state, raw `g4_code`, and resolved enum symbol
when available.

```
as11_descriptors.py firmware.bin var-options MOP
as11_descriptors.py firmware.bin var-options VAuto-CycleSensitivity
```

### mode

List settings associated with one therapy mode.

```
as11_descriptors.py firmware.bin mode 6
as11_descriptors.py firmware.bin mode 0xa
```

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

### globals / conf-layout

Inspect the CONF `globals[]` pointer table and the packed ranges inferred from
it.

```
as11_descriptors.py firmware.bin globals
as11_descriptors.py firmware.bin conf-layout
```

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
filter by stream tag.

```
as11_descriptors.py firmware.bin edf-streams
as11_descriptors.py firmware.bin edf-streams BRP
as11_descriptors.py firmware.bin edf-streams BRP PLD --verbose
```

### events / event-routes / event-labels

Inspect event definitions, route triples, and label tables.

```
as11_descriptors.py firmware.bin events
as11_descriptors.py firmware.bin events Pressure
as11_descriptors.py firmware.bin events --verbose
as11_descriptors.py firmware.bin event-routes SystemActivity
as11_descriptors.py firmware.bin event-labels EVE CSL
```

`event-labels` detects both supported g[17] schema layouts and reports the
schema size, record sizes, FIFO capacity, writer/backdating flags, and labels.

These tables are useful when mapping `SubscribeEvent` selectors and spool/event
payload names used by `as11_config.py`.

### collections

List periodic collection tables from `globals[14]`.

```
as11_descriptors.py firmware.bin collections
as11_descriptors.py firmware.bin collections NRF APD
as11_descriptors.py firmware.bin collections NRF --verbose
```

### storage-sets

List persisted setting sets from `globals[6]`. These sets map groups of
variables to storage-backed records such as history, calibration, identity,
and application data.

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

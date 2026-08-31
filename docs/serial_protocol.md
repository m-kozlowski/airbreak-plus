# Serial Protocol

AirSense 10 external service port (USART3). 57600 8N1, 3.3V logic.

## Frame Format

```
[0x55] [type] [len:3 hex-ASCII] [payload, 0x55-escaped] [crc:4 hex-ASCII]
```

| Field | Size | Encoding |
|-------|------|----------|
| Sync | 1 | `0x55` literal |
| Type | 1 | ASCII char: `E`, `f`, `K`, `L`, `O`, `P`, `Q`, `R`, `T` |
| Length | 3 | Hex-ASCII, total frame size in bytes (sync through CRC) |
| Payload | 1..502 | Binary. `0x55` in payload escaped as `0x55 0x55` |
| CRC-16 | 4 | Hex-ASCII, CRC-CCITT-FALSE over all preceding bytes |

CRC parameters: poly `0x1021`, init `0xFFFF`, no output XOR, MSB-first.

Any `0x55` byte inside the payload is escaped as `0x55 0x55`. The length field
counts the escaped wire bytes. CRC is computed over the escaped wire bytes.

Two host-to-device frame forms are immediate and have no length, payload, or
CRC:

| Type | Wire bytes | Purpose |
|------|------------|---------|
| `O` | `0x55 0x4F` | Abort an active stored-stream transfer and reset the parser |
| `P` | `0x55 0x50` | Parser reset |

Immediate `O` is distinct from the full `O` frame used by the patched SX577
bootloader.

## Frame Types

| Type | Direction | Format | Purpose |
|------|-----------|--------|---------|
| `Q` | host -> device | full | ASCII command |
| `R` | device -> host | full | Success response |
| `E` | device -> host | full | Error response |
| `K` | device -> host | full | Stored stream data response |
| `L` | host -> device | full | Oximetry adapter input |
| `L` | device -> host | full | Live stream report |
| `f` | host -> bootloader | full | Firmware transfer frame |
| `O` | host <-> patched SX577 bootloader | full | Firmware dump extension |
| `O` | host -> device | immediate | Stored-stream abort and parser reset |
| `P` | host -> device | immediate | Parser reset |
| `P` | bootloader -> host | full | Flash erase progress |
| `T` | -- | -- | Reserved; rejected with `0x6011` |

## Q-Frame Commands

Payload is ASCII command text. The CDX command dispatcher recognizes these
command families:

| Command | Purpose |
|---------|---------|
| `G S` | Read variables and `&` channel state |
| `P S` | Write variables and enable/disable live channels |
| `G C` | Read `#` variable capabilities and Airbreak `&` metadata |
| `G F` | Query stored EEPROM streams |
| `G V` | Read samples from stored signal records |

The first eight command characters are converted to uppercase. A value after
that prefix retains its original bytes.

Most commands return one of these forms:

```
R: REQUEST = VALUE
E: REQUEST = ERROR_CODE
```

`G F` and `G V` use the response paths described below.

### Variables

```
Q: G S #VAR
R: G S #VAR = VALUE

Q: P S #VAR VALUE
R: P S #VAR VALUE = VALUE
```

`VAR` is the three-character UART variable name. `G S #VAR` is exactly eight
characters. `P S` requires a space after the name. An empty value is accepted
only for g[3] text variables.

The value encoding depends on the variable table:

| Variable class | Exact `VALUE` format |
|----------------|----------------------|
| g[3] text | Raw text, up to the descriptor's maximum length |
| g[4] numeric | `W` uppercase hex digits containing the raw integer value |
| g[6] bitmask | `W` uppercase hex digits |
| g[8] enum | Four uppercase hex digits containing the option index |
| g[9] `ANV` | `TTTTTTTTDDDDEEEE` |
| g[17] `DAC` | `DDMMYYYY` in decimal digits |
| g[18] `TIC` | `HHMMSS` in decimal digits |

For g[4] and g[6], `W` is the same handler-selected width used by `G C`.
Signed g[4] values use `W * 4`-bit two's complement. Values are raw descriptor
values: scaling, decimal places, and units are not applied to the wire value.

The read-only `ANV` tuple contains an eight-digit time-of-day value in seconds,
a four-digit duration in deciseconds, and a four-digit event type. `P S` is not
available for g[9].

Hex writes accept one or more hex digits, but clients should use the width
returned by the corresponding read. `P S` passes the value through the normal
validation, callback, dependency, and persistence path. The success response
contains the value read back after that processing, which may differ from the
requested value.

An unknown `VAR` returns `0x6006`. `G S` with the wrong command length returns
`0x6008`. Bad `P S` syntax returns `0x600E`, a non-hex character in a hex value
returns `0x6031`, and a known object that is not available through the selected
`#` path returns `0x6009`.

### Variable Capabilities

```
Q: G C #VAR
R: G C #VAR = BASE

Q: G C #VAR II
R: G C #VAR II = OPTION
```

`II` is the zero-based g[8] option index. Hosts should send it as two uppercase
hexadecimal digits. The base response depends on the variable handler:

| Variable class | Exact `BASE` format |
|----------------|---------------------|
| g[3] text | `F` |
| g[4] numeric | `F MIN MAX` |
| g[6] bitmask | `F MIN MAX` |
| g[8] enum | `F` |
| g[9] `ANV` | `F` |
| g[17] `DAC` | `F` |
| g[18] `TIC` | `F` |

`F` is one uppercase hexadecimal digit containing the low four descriptor flag
bits. Bits 0, 1, and 2 are `ACT`, `VIS`, and `EDT`; bit 3 is reported without a
common interpretation.

For g[4], `MIN` and `MAX` have the same width `W`, from one to eight uppercase
hexadecimal digits. `W` is chosen from the descriptor's raw range and numeric
signedness; it is not sent as a separate field. The values are zero-padded and
signed values use `W * 4`-bit two's complement. Signedness itself is not
reported, so it cannot always be recovered from an arbitrary capability
response without metadata for that variable.

For g[6], `MIN` is zero and `MAX` is `0x7FFFFFFF`, both truncated and padded to
the handler-selected width `W`. For example, a six-digit handler returns
`000000 FFFFFF`.

Only g[8] provides an indexed response. Its exact format is:

```
NN P LABEL
```

`NN` is the total option count as two uppercase hexadecimal digits. `P` is one
hexadecimal digit containing the current permission result and is `1` for a
response accepted by the command handler. `LABEL` is the localized option text
through the end of the response and may be empty or contain spaces.

Index zero is the first option and has no special meaning. The command returns
`0x6033` if the index is outside the descriptor range or that option is
currently disallowed. These two cases cannot be distinguished from the error
response. A client must obtain `NN` from a successful indexed query, then query
every index below `NN`; it must not treat the first `0x6033` as the end of the
list.

Examples from an SX567-0402 image:

```
G C #MXS = 6 19 64
G C #MOP = 7
G C #MOP 00 = 0C 1 CPAP
G C #LNC = 7 000000 FFFFFF
```

The Airbreak custom-settings records below add the category, MOP visibility
mask, localized variable label, and numeric display metadata that are absent
from the stock response. Limits and enum option metadata remain available
through the stock commands and are not repeated in the custom records.

### Live Stream Schemas

Airbreak-patched firmware accepts `G C &TAG` for channels in g[26] and g[27]:

```
Q: G C &TAG
R: G C &TAG = NN VAR:WW VAR:WW ...
```

`NN` is the number of fields. Each `VAR:WW` pair gives the UART variable name
and its width in hexadecimal characters. Both `NN` and `WW` are encoded as two
uppercase hexadecimal digits. Fields are returned in the order used by the
channel's `L` frames.

The command reads the active g[26]/g[27] descriptors, including layouts changed
by the EDF signal merge. Stock firmware returns `0x6009` for this command.

### Custom Settings Registry

Airbreak-patched firmware uses the same `G C` extension to expose custom
settings. The header reports the protocol version and number of variables:

```
Q: G C &CSG
R: G C &CSG = VV NN
```

`VV` is the two-digit protocol version. Version `01` uses the records below.
`NN` is the two-digit record count. Records are read by a two-digit hexadecimal
index:

```
Q: G C &CSG II
R: G C &CSG II = ENTRY
```

The entry type is the first token:

```
V4 CC MMMMMMMM VAR SSSS TTTT DD UU:UNITS LABEL
V8 CC MMMMMMMM VAR LABEL
```

| Field | Content |
|-------|---------|
| `V4` | Numeric g[4] variable |
| `V8` | Enumerated g[8] variable |
| `CC` | Category, two hex digits |
| `MMMMMMMM` | One visibility bit per MOP option index |
| `VAR` | Three-character UART variable name |
| `SSSS` | Signed raw g[4] scale |
| `TTTT` | Signed raw g[4] step |
| `DD` | g[4] display precision |
| `UU` | Byte length of `UNITS` |
| `LABEL` | Localized label through the end of the response |

Category values `00` through `04` are Therapy, Comfort, Accessories, Options,
and Configuration. Variables placed on generated firmware pages report the
top-level category containing that page; page layout and static headings are
not part of this interface.

A positive `SSSS` means the displayed value is the raw value divided by the
scale. A negative scale means the displayed value is the raw value multiplied
by the absolute scale. `SSSS` and `TTTT` are signed 16-bit two's-complement
values encoded as four uppercase hex digits. `UU` allows the units string to
contain spaces.

Read numeric limits with `G C #VAR`. Read enum permissions and labels with the
stock `G C #VAR INDEX` command. Read and write current values through the normal
`G S #VAR` and `P S #VAR VALUE` commands.

`G C &CSG` does not replace the scalar `#CSG` variable path. Firmware with the
UART metadata patch but no generated custom menu reports version `01` and zero
records. A malformed index returns `0x600E`, non-hex index text returns
`0x6031`, and an unavailable index returns `0x6033`. Stock firmware returns
`0x6009`.

### Live Stream Reporting

Live stream reporting is controlled with the `P S` `&TAG` path:

```
Q: G S &PMD
R: G S &PMD = 0

Q: P S &PMD 1
R: P S &PMD 1 = 1
L: PMDSSDATA

Q: P S &PMD 0
R: P S &PMD 0 = 0
```

`G S &TAG` reads the current state. `P S &TAG` accepts exactly `0` or `1`; there
is no rate argument. Subscriptions are cleared by reboot.

Enabled channels emit device-to-host `L` frames. Their exact payload is:

```
TAGSSFIELD1FIELD2...
```

`TAG` is the three-character channel name. `SS` is an 8-bit rolling sequence
number encoded as two uppercase hex digits. The remaining fields are
concatenated without separators and use the widths reported by `G C &TAG`.

Subscribable Air 10 live roots are defined by g[26] and g[27]:
`TCE`, `PBT`, `PMD`, `FTX`, `RAW`, `DRT`, `CPU`, `SSK`, `APN`, `CSN`, and
`BRH`. Field lists and variant differences are documented in
[config_variables.md](config_variables.md#g26----live-stream-records).

### Stored Stream Query

Stored EEPROM streams use `G F &TAG` and return `K` frames.

```
Q: G F &ERR
R: G F &ERR
K: ERR...

Q: G F &ERR 0001
R: G F &ERR 0001
K: ERR...
```

The immediate `R` payload is the request itself, without ` = VALUE`.

The request is either exactly `G F &TAG`, or that text followed by one space and
one to four hexadecimal digits. More than four digits or a non-hexadecimal
argument returns an error.

Supported Air 10 stored stream tags are defined by g[19]:
`ABR`, `TXC`, `TXH`, `TXE`, `TXW`, `TRR`, `DLL`, `ERR`, `ELI`, and `ZRL`.

Argument handling:

| Argument | Query type |
|----------|------------|
| omitted | all current records, from logical index 0 upward |
| `0000` | close all active stored-stream readers |
| `0001`..`0FFF` | one record by reverse ordinal; `0001` is newest |
| `1000`..`FFFF` | records for the selected therapy day |

The date argument is a 16-bit day count from `1970-01-01`. The therapy day
changes at noon: before noon it is the previous calendar date, and from noon it
is the current date. Firmware seeks using the difference from the current
therapy day, then compares the resolved date of each record.

A new `G F` request closes the previous reader. Immediate `O` aborts an active
transfer. The transfer timeout uses `ATO`.

`STR.ssn`, `NPD`, and `NPA` signals are read with `G V`, not `G F`.

## K-Frame Payload

Normal stored records use this ASCII payload:

```
NAME SSSSS DDDD OOOOO DATA...
```

The spaces show field boundaries and are not transmitted.

| Field | Width | Description |
|-------|-------|-------------|
| `NAME` | 3 | Stored stream identifier |
| `SSSSS` | 5 | Sequence number, starting at `00000` |
| `DDDD` | 4 | Record therapy-day index |
| `OOOOO` | 5 | Record offset; `00000` for whole-record output |
| `DATA` | variable | Fields serialized according to the g[19] descriptor |

The transfer uses these control payloads:

```
NAMEFFFFFDDDD00001
NAME00000FFFF00000
NAME99999FFFFNNNN
```

The first marks transfer start and carries the reader's day cursor. The second
ends a transfer with no selected records. The third ends a nonempty transfer;
`NNNN` is the selected record count. `FFFF` is a control marker in the final two
forms, not a record date.

## Stored Signal Query

`G V` reads one signal from `STR.ssn`, `NPD`, or `NPA`:

```
Q: G V #VAR DDDD C
```

`VAR` is a three-character signal UART name. `DDDD` is exactly four hexadecimal
digits and must be at least `1000`. It is the same noon-to-noon therapy-day
index used by dated `G F` queries. `C` is a 1- to 4-digit hexadecimal cursor.
The spaces shown in the request are required.

The request is asynchronous and has no immediate success response. The result
arrives in an `R` frame:

```
R: G V #VAR DDDD C = VVVVNN[DATA]CCCC
```

| Field | Width | Description |
|-------|-------|-------------|
| `VVVV` | 4 | Numeric signal variable ID |
| `NN` | 2 | Number of returned samples |
| `DATA` | variable | Concatenated samples |
| `CCCC` | 4 | Next cursor, or `FFFF` when complete |

| Source | Selector and cursor | Sample format |
|--------|---------------------|---------------|
| g[13] `STR.ssn` | `DDDD` selects the therapy-day record; cursor must be zero | u16, 4 hex digits |
| g[14] `NPD` | `DDDD` selects the dated record; cursor zero starts at internal offset 2 | u8 expanded to 4 hex digits; `0xFF` becomes `FFFF` |
| g[15] `NPA` | Same dated-record cursor as NPD | 16 hex digits: u32, u16, u16 |

An unsupported signal returns `0x6009`, a busy worker returns `0x6001`, and an
invalid selector or argument returns `0x6034`.

## Oximetry L-Frame Input

The oximetry adapter sends host-to-device `L` frames. The device does not answer
these frames directly.

```
0x55 'L' len(3) O X H [seq:2] [OXS:2] [HRR:3] [SAS:2] [SAR:2] [NVS:2] crc(4)
```

Full OXH payload details are in [oximeter_protocol.md](oximeter_protocol.md).

## Bootloader Commands

Bootloader commands are sent as `Q` frames with ASCII command payloads.

Successful get and set commands use the same response grammar as CDX scalar
commands:

```
Q: G S #TAG
R: G S #TAG = VALUE

Q: P S #TAG VALUE
R: P S #TAG VALUE = VALUE
```

| Command | Effect |
|---------|--------|
| `G S #BID` | Read bootloader version |
| `G S #BLS` | Read bootloader state: `0` = CDX, `1`/`2` = bootloader |
| `G S #BLE` | Read bootloader error code |
| `G S #BDD` | Read current bootloader baud key when supported |
| `G S #SID` | Read CDX version string |
| `G S #CID` | Read CCX version string |
| `P S #BLL 0001` | Enter bootloader from CDX on Air 10 |
| `P S #RES 0001` | System reset |
| `P S #RES 0003` | Fast reset path on Air 10 |
| `P S #BDD KEY` | Set Air 10 bootloader baud |
| `P F *BLOCK ARG` | Select and erase flash block |
| `P S #PIP KEY` | Enter UART bridge mode |

`BLS`, `BLE`, and `BDD` return four uppercase hex digits. In the bootloader,
`BLS` is `0001` during the normal command window and `0002` when the
application image is unavailable. CDX reports `0000`. `BID`, `SID`, and `CID`
return text.

S9 bootloaders expose `G S #PST` instead of `BLE`. A clear status is returned
as `G S #PST = 0`; a nonzero status is returned as four hex digits.

Air 10 `BDD` baud keys:

| Key | Baud |
|-----|------|
| `0000` | 57600 |
| `0001` | 115200 |
| `0002` | 460800 |

The `P S #BDD` response is sent at the old baud. The bootloader changes baud
afterward.

SX577 accepts these four-digit `PIP` keys:

| Key | Bridge |
|-----|--------|
| `0000` | External USART3 at 460800 <-> internal USART1 at 460800 |
| `0001` | External USART3 at 460800 <-> internal USART2 at 19200 |
| `0002` | External USART3 at 57600 <-> internal USART1 at 57600 |
| `0003` | Internal USART1 at 57600 <-> internal USART2 at 9600 |
| `0004` | External USART3 at 230400 <-> internal USART1 at 230400 |
| `0005` | External USART3 at 345600 <-> internal USART1 at 345600 |

SX585 also accepts `0006`, which bridges external USART3 at 57600 to internal
USART2 at 9600.

Flash block select commands used by current tooling:

| Platform | Blocks | Selector suffix |
|----------|--------|-----------------|
| Air 10 SX577/SX585 | `BLX`, `CCX`, `CDX`, `CMX` | `0000` convention; block selector uses only `*BLOCK` |
| S9 SX525 | `BLX`, `CCX`, `CDX` | transfer baud value; current tooling uses `1C200` |

On S9, the selector suffix is parsed as a baud value. Observed bootloaders
accept `E100` and `1C200`; current tooling uses `1C200`. The erase response
also carries the bootloader transfer baud value, and the flash tool follows
that baud before sending data.

Block selection has no immediate response. While erase is active, the
bootloader sends repeated full `P` frames. The final `R` frame means erase has
completed:

```
Air 10 request:   Q: P F *CCX 0000
Air 10 progress:  P: P F *CCX
Air 10 complete:  R: P F *CCX

S9 request:       Q: P F *CCX 1C200
S9 progress:      P: P F *CCX
S9 complete:      R: P F *CCX = 1C200
S9 erase failure: E: P F *CCX
```

Air 10 ignores the selector suffix after the block name. S9 returns the
selected transfer baud in the completion response and changes to that baud
after sending the response.

## Flash Data Protocol

After `P F *BLOCK ARG` selects and erases the target block, firmware data is
sent in lower-case `f` frames with this payload:

```
BLOCK(3) marker(1) sequence(1) records(...)
```

| Field | Description |
|-------|-------------|
| `BLOCK` | ASCII block name: `BLX`, `CCX`, `CDX`, or `CMX` |
| `marker` | `0x00` for data, ASCII `F` for completion |
| `sequence` | One-byte frame sequence, wraps at `0xFF` |
| `records` | One or more binary flash records |

Data records are binary S3-like records, not ASCII Motorola S-record lines:

```
0x03 length address_be32 data... tail
```

`length` covers the 4-byte address, data bytes, and trailing byte. Current
tooling sends chunks up to 250 data bytes and uses `0x00` as the trailing byte.

After all data frames, the host sends an `f` frame with marker `F`.

Firmware data frames have no per-frame response. On Air 10, `G S #BLE` exposes
the retained bootloader status:

| Value | Meaning |
|-------|---------|
| `0000` | No retained bootloader error |
| `6006` | Data-frame block name does not match the selected block |
| `7003` | Flash byte programming failed |
| `7006` | Unexpected frame sequence byte |
| `7007` | Unsupported binary record type |
| `7009` | Record address lies outside the selected block |
| `700D` | Block selected; erase or transfer in progress |
| `7016` | Firmware integrity or CCX/CDX compatibility check failed at startup |

On Air 10, the completion marker sets the transfer-complete flag, clears `BLE`
to `0000`, and restarts the approximately two-second bootloader timeout. It does
not validate the written firmware. After reset, BLX checks firmware integrity
before entering the application. A failed CCX or CDX CRC leaves the device in
the bootloader with `BLE=7016`. The same status is used when the application
detects an incompatible CCX/CDX identity pair and requests the bootloader error
path.

The CRC in each full UART frame is checked by the frame parser. A bad frame CRC
produces parser error `0x6014`; it is separate from the firmware-region CRCs.

On S9, the marker verifies the selected block. Successful CDX completion starts
the application. Successful BLX or CCX completion stops protocol processing and
the watchdog resets the device.

## Patched Bootloader Dump Protocol

The Airbreak SX577-0200 bootloader extension uses full `O` frames. Flash
offsets are relative to the start of the 1 MB firmware image.

Request payload:

```
'D' offset_le32 length_le16
```

`length` must be between 1 and 240 bytes and the requested range must remain
inside the firmware image.

Successful response payload:

```
'd' offset_le32 length_le16 data...
```

An invalid range returns `E`, the requested offset, and a zero length. The host
checks the frame CRC, echoed offset, and echoed length before accepting a chunk.
Timeouts and mismatched responses are retried at the same offset.

## Error Codes

Command errors use four uppercase hex digits:

```
E: REQUEST = CCCC
```

Parser errors raised before a complete command exists may contain only:

```
E:  = CCCC
```

| Code | Meaning |
|------|---------|
| `0x6001` | Asynchronous `G V` worker busy |
| `0x6004` | Invalid or unsupported bootloader command or block selector |
| `0x6006` | Unknown variable/channel; Air 10 data-frame block mismatch |
| `0x6008` | Bad `G S` command length |
| `0x6009` | Command not available for this variable/channel context |
| `0x600C` | New sync byte interrupted an incomplete frame |
| `0x600E` | Bad command syntax |
| `0x6011` | Rejected frame type |
| `0x6012` | Invalid frame length |
| `0x6013` | Unexpected type byte in an incomplete frame |
| `0x6014` | CRC validation failed |
| `0x6031` | Bad hex argument |
| `0x6033` | Capability or custom-settings index not available |
| `0x6034` | Invalid `G V` selector or argument |
| `0x6052` | Response buffer overflow |

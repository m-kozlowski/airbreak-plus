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
| Payload | 0..502 | Binary. `0x55` in payload escaped as `0x55 0x55` |
| CRC-16 | 4 | Hex-ASCII, CRC-CCITT-FALSE over all preceding bytes |

CRC parameters: poly `0x1021`, init `0xFFFF`, no output XOR, MSB-first.

Any `0x55` byte inside the payload is escaped as `0x55 0x55`. The length field
counts the escaped wire bytes. CRC is computed over the escaped wire bytes.

Two frame types are immediate and have no length, payload, or CRC:

| Type | Wire bytes | Purpose |
|------|------------|---------|
| `O` | `0x55 0x4F` | Parser reset; sets `ZRO=1` when `ZLB` is active |
| `P` | `0x55 0x50` | Parser reset |

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
| `O` | host -> device | immediate | Parser reset; conditional `ZRO` marker |
| `P` | host -> device | immediate | Parser reset |
| `T` | -- | -- | Reserved; rejected with `0x6011` |

## Q-Frame Commands

Payload is ASCII command text. The CDX command dispatcher recognizes these
command families:

| Command | Purpose |
|---------|---------|
| `G S` | Read variables and `&` channel state |
| `P S` | Write variables and enable/disable live channels |
| `G C` | Read `#` variable capabilities |
| `G F` | Query stored EEPROM streams |
| `G V` | Date-filtered stored stream query path |

### Variables

```
Q: G S #VAR
R: G S #VAR = VALUE

Q: P S #VAR VALUE
R: P S #VAR VALUE = VALUE
```

`VALUE` is hex-encoded and zero-padded to the variable width.

### Variable Capabilities

```
Q: G C #VAR
R: G C #VAR = CAPABILITY_DATA

Q: G C #VAR INDEX
R: G C #VAR INDEX = CAPABILITY_DATA
```

### Live Stream Reporting

Live stream reporting is controlled with the `P S` `&TAG` path:

```
Q: P S &PMD 1
R: P S &PMD 1 = 1
L: PMD...

Q: P S &PMD 0
R: P S &PMD 0 = 0
```

`1` enables reports and `0` disables them. Enabled channels emit device-to-host
`L` frames. The payload starts with the 3-character channel name, followed by a
one-byte sequence and channel-specific hex fields.

Subscribable Air 10 live roots are defined by g[26] and g[27]:
`TCE`, `PBT`, `PMD`, `FTX`, `RAW`, `DRT`, `CPU`, `SSK`, `APN`, `CSN`, and
`BRH`. Field lists and variant differences are documented in
[config_variables.md](config_variables.md#g26----live-stream-records).

### Stored Stream Query

Stored EEPROM streams use `G F &TAG` and return `K` frames.

```
Q: G F &ERR
R: G F &ERR = ...
K: ERR...

Q: G F &ERR 0001
R: G F &ERR 0001 = ...
K: ERR...
```

Supported Air 10 stored stream tags are defined by g[19]:
`ABR`, `TXC`, `TXH`, `TXE`, `TXW`, `TRR`, `DLL`, `ERR`, `ELI`, and `ZRL`.

Argument handling:

| Argument | Query type |
|----------|------------|
| omitted | stream summary |
| `0000` | specific-record path; commonly no `K` payload |
| `0001`..`0FFF` | 1-based record/page index |
| `1000`..`FFFF` | date-filtered query |

Date-filtered queries use a 16-bit day count from `1970-01-01`, encoded as
hex. For example, `G F &ERR 5043` queries day `0x5043`
(`2026-04-04`).

For date queries, the firmware compares the requested day against the current
device day, seeks into the stored log using that day delta, and returns matching
`K` records. The response ends with the normal empty/end sentinel.

## K-Frame Payload

Normal paged records use this common ASCII payload prefix:

```
NAME(3) start_day(9 hex) end_day(9 hex) minute(3 hex) field(4 hex) data(variable)
```

| Field | Description |
|-------|-------------|
| `NAME` | Stored stream identifier, for example `DLL`, `ERR`, or `TXE` |
| `start_day` / `end_day` | Day count from `1970-01-01`, rendered as 9 hex chars |
| `minute` | Minutes since midnight |
| `field` | Stream field/version value; commonly `0001` in observed records |
| `data` | Stream-specific payload |

The day value itself fits in the low 16 bits, but the wire field is wider. For
example `000005043` is day `0x5043`, which is `2026-04-04`.

Empty/end responses use a sentinel payload beginning with:

```
NAME00000FFFF00000
```

`FFFF` is the empty date marker.

## Oximetry L-Frame Input

The oximetry adapter sends host-to-device `L` frames. The device does not answer
these frames directly.

```
0x55 'L' len(3) O X H [seq:2] [OXS:2] [HRR:3] [SAS:2] [SAR:2] [NVS:2] crc(4)
```

Full OXH payload details are in [oximeter_protocol.md](oximeter_protocol.md).

## Bootloader Commands

Bootloader commands are sent as `Q` frames with ASCII command payloads.

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

Air 10 `BDD` baud keys:

| Key | Baud |
|-----|------|
| `0000` | 57600 |
| `0001` | 115200 |
| `0002` | 460800 |

Flash block select commands used by current tooling:

| Platform | Blocks | Selector suffix |
|----------|--------|-----------------|
| Air 10 SX577/SX585 | `BLX`, `CCX`, `CDX`, `CMX` | `0000` convention; block selector uses only `*BLOCK` |
| S9 SX525 | `BLX`, `CCX`, `CDX` | transfer baud value; current tooling uses `1C200` |

On S9, the selector suffix is parsed as a baud value. Observed bootloaders
accept `E100` and `1C200`; current tooling uses `1C200`. The erase response
also carries the bootloader transfer baud value, and the flash tool follows
that baud before sending data.

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

After all data frames, the host sends an `f` frame with marker `F`. The
bootloader finalizes the selected block and resets or remains in bootloader
depending on the flashing sequence.

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

| Code | Meaning |
|------|---------|
| `0x6006` | Unknown variable/channel |
| `0x6008` | Bad command length |
| `0x6009` | Command not available for this variable/channel context |
| `0x600E` | Bad command syntax |
| `0x6011` | Rejected frame type |
| `0x6014` | CRC validation failed |
| `0x6031` | Bad hex argument |
| `0x6033` | Capability index not available |
| `0x6034` | Stored stream not found or bad stream query argument |

## O-Frame

Immediate `O` (`0x55 0x4F`) checks `ZLB`. If `ZLB` is nonzero, CDX sets
`ZRO=1`, then resets the UART parser state.

## P-Frame

Immediate `P` (`0x55 0x50`) resets the UART parser state.

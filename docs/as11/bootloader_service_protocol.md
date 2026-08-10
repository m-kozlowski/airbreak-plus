# Air11 Bootloader Service Protocol

The patched Air11 bootloader exposes a binary request/response service for
reading, erasing, and writing internal flash and physical SPI NOR, and reading
or writing backup SRAM. It is independent of the application JSON-RPC and
DatagramCan protocols.

This document describes protocol version 2 and the implementation profile of
service version 0.8.0. Requirements use `MUST`, `SHOULD`, and `MAY` as
normative terms. Text explicitly marked as an implementation profile describes
0.8.0 rather than a general protocol requirement.

## Contents

- [Transport](#transport)
- [Versioning and compatibility](#versioning-and-compatibility)
- [ISO-TP framing](#iso-tp-framing)
- [Service packet](#service-packet)
- [Transactions](#transactions)
- [Command space](#command-space)
- [Targets and geometry](#targets-and-geometry)
- [Commands](#commands)
  - [INFO](#info-0x02)
  - [READ](#read-0x03)
  - [ERASE](#erase-0x04)
  - [WRITE](#write-0x05)
  - [RESET](#reset-0x06)
- [Status values](#status-values)
- [Error mapping](#error-mapping)
- [AirCANnect TCP transport](#aircannect-tcp-transport)
- [Implementation checklist](#implementation-checklist)

## Transport

Direct communication uses classic CAN:

| Setting | Value |
|---------|-------|
| Bitrate | 1 Mbit/s |
| Identifier format | standard 11-bit |
| Frame type | data frame |
| Maximum CAN payload | 8 bytes |
| Host to service | `0x3c1` |
| Service to host | `0x3c0` |

A client MUST NOT have more than one active transaction. The service MUST NOT
send unsolicited packets. A normal, unpatched application does not implement
this endpoint.

## Versioning and compatibility

Three independent identifiers are exposed:

| Identifier | Location | Meaning |
|------------|----------|---------|
| protocol version | packet header byte 1 | compatibility of framing and existing command semantics |
| service version | first three INFO payload bytes | exact service implementation release |
| bootloader build ID | remaining INFO payload bytes | native bootloader build containing the service |

Protocol version is the compatibility boundary. An incompatible change to the
packet envelope, transport rules, or meaning of an existing command, target,
or status MUST use a new protocol version. A compatible implementation MAY add
new command, target, or status values while retaining the existing values and
semantics.

A receiver that can parse the header but does not support its protocol version
MUST return `BadVersion`. A client MUST reject a response carrying a protocol
version it does not support.

The service version is an implementation identity only. No ordering,
capability, or compatibility rule is assigned to its three components. A
client MAY display or log it but MUST NOT infer supported commands from it.
Unsupported commands are reported with `BadCommand`.

The bootloader build ID identifies the native bootloader used by the service.
It is diagnostic metadata and does not replace the packet protocol version.

## ISO-TP framing

Complete service packets are transported using normal-addressing ISO-TP with
12-bit First Frame lengths. There is no address byte before the ISO-TP PCI.
The maximum complete packet is 4095 bytes.

| Frame | PCI layout | Data |
|-------|------------|------|
| Single Frame | `0x0L` | `L` packet bytes, where `1 <= L <= 7` |
| First Frame | `0x1H LL` | first 6 packet bytes; length is `(H << 8) | LL` |
| Consecutive Frame | `0x2S` | up to 7 packet bytes; sequence `S` wraps modulo 16 |
| Flow Control | `0x3F BS ST` | flow status, block size, separation time |

The fixed service header and CRC occupy 10 bytes, so every valid service
packet uses a First Frame and at least one Consecutive Frame. Single Frame is
recognized by the transport decoder but cannot contain a complete service
packet.

The 0.8.0 service advertises `BS=32`, `STmin=0` while receiving requests. A
host MUST obey the values in each Flow Control frame rather than assume these
constants. It MUST stop after each nonzero `BS` block and wait for another
Continue To Send Flow Control frame.

When sending a response, the service MUST follow the `BS` supplied by the
host. `BS=0` permits sending the remainder of the packet without another Flow
Control frame. The 0.8.0 service transmitter supports only `STmin=0`; a
conforming host MUST advertise zero to that implementation. It accepts
Continue To Send and Wait flow statuses and rejects Overflow or unsupported
Flow Control values.

Flow Control frames use the same directional CAN ID as other traffic:

- the service sends request Flow Control on `0x3c0`;
- the host sends response Flow Control on `0x3c1`.

## Service packet

All integer fields MUST be serialized little-endian.

| Offset | Size | Field | Request value |
|--------|------|-------|---------------|
| `0x00` | 1 | magic | MUST be `0xa5` |
| `0x01` | 1 | protocol version | MUST be `2` |
| `0x02` | 1 | command | command ID |
| `0x03` | 1 | status | MUST be `0` |
| `0x04` | 2 | sequence | host-selected transaction value |
| `0x06` | 2 | payload length | number of payload bytes |
| `0x08` | variable | payload | command-specific |
| after payload | 2 | CRC16 | header and payload |

The CRC MUST use CRC16-CCITT-FALSE: polynomial `0x1021`, initial value
`0xffff`, and no final XOR. It is stored little-endian and covers the
eight-byte header followed by the payload. It does not include the CRC field
itself.

The payload MUST NOT exceed 4085 bytes. The complete packet size is:

```text
8 + payload_length + 2
```

For example, an INFO request with sequence `0x1234` is:

```text
a5 02 02 00 34 12 00 00 d1 df
```

## Transactions

For every accepted request, the service MUST return one response with the same
command and sequence. A client MUST validate both fields before accepting the
response.

Successful responses MUST use status `0x00`. Error responses MUST preserve the
command and sequence and MUST carry no payload. The service does not retry
failed transactions.

Sequence distinguishes a response from a delayed response to an earlier
transaction. A client SHOULD increment the 16-bit value for each request and
MUST NOT accept a response with a different value. Wrap from `0xffff` to
`0x0000` is permitted.

The protocol defines no operation deadline and provides no progress or
keepalive packets. ERASE and WRITE respond only after storage verification.
After a timeout, a client MUST treat the result as unknown. It MAY retry INFO
or READ. Before repeating ERASE or WRITE, it SHOULD reconnect and inspect the
affected storage when doing so is possible. It MUST NOT assume that absence of
a response means that a mutation did not occur.

Malformed ISO-TP traffic, a packet shorter than the fixed header and CRC, or a
packet with the wrong magic MAY be discarded without a response.

## Command space

The command field is one byte:

| Range | Assignment |
|-------|------------|
| `0x00` | reserved |
| `0x01` | reserved by the device; AirCANnect-local ENTER |
| `0x02` | INFO |
| `0x03` | READ |
| `0x04` | ERASE |
| `0x05` | WRITE |
| `0x06` | RESET |
| `0x07..0xff` | reserved for compatible extension |

A direct-CAN client MUST NOT send a reserved command or ENTER. The 0.8.0
service returns `BadCommand` for any command not listed above.

## Targets and geometry

Protocol version 2 assigns these one-byte target IDs:

| Target | Value | Address model |
|--------|-------|---------------|
| reserved | `0x00` | none |
| `FGCB` | `0x01` | absolute STM32 address |
| `SPIN` | `0x02` | offset from start of SPI NOR |
| `BKPS` | `0x03` | offset from start of backup SRAM |
| reserved | `0x04..0xff` | none |

The 0.8.0 implementation profile uses this geometry:

| Property | `FGCB` | `SPIN` | `BKPS` |
|----------|--------|--------|--------|
| Start | `0x08000000` | `0x00000000` | `0x00000000` |
| Size | `0x00200000` | `0x01000000` | `0x00001000` |
| Erase unit | `0x20000` | `0x1000` or `0x10000` | none |
| Program unit | 32 bytes | byte ranges, split at 256-byte pages | byte ranges |

The internal-flash regions commonly used by clients are:

| Region | Start | Length |
|--------|-------|--------|
| `FGBL` | `0x08000000` | `0x00020000` |
| `CONF` | `0x08020000` | `0x00020000` |
| `APPL` | `0x08040000` | `0x001c0000` |
| `FGCB` | `0x08000000` | `0x00200000` |

These region names are client conveniences, not additional protocol target
IDs.

## Commands

### INFO (`0x02`)

The request payload MUST be empty.

The response payload MUST contain exactly 19 bytes:

| Offset | Size | Field |
|--------|------|-------|
| `0x00` | 1 | service major version |
| `0x01` | 1 | service minor version |
| `0x02` | 1 | service patch version |
| `0x03` | 16 | bootloader build ID in ASCII |

The build-ID field is fixed-width; clients MUST stop at the first NUL if one
is present.

### READ (`0x03`)

Request payload:

| Offset | Type | Field |
|--------|------|-------|
| `0x00` | `u8` | target |
| `0x01` | `u32` | offset or absolute address |
| `0x05` | `u16` | requested data length |

The requested length MUST be between 1 and 4085 bytes. The response payload
MUST contain exactly that many data bytes and no metadata.

### ERASE (`0x04`)

Request payload:

| Offset | Type | Field |
|--------|------|-------|
| `0x00` | `u8` | target |
| `0x01` | `u32` | offset or absolute address |
| `0x05` | `u32` | erase length |

For `FGCB`, one request MUST select exactly one aligned 128 KiB sector. For
`SPIN`, one request MUST select one aligned 4 KiB or 64 KiB block. Before
returning success, the service MUST read the selected range back and verify
that every byte is `0xff`.

`BKPS` does not support ERASE and returns `BadTarget`.

The successful response payload MUST be empty.

### WRITE (`0x05`)

Request payload:

| Offset | Type | Field |
|--------|------|-------|
| `0x00` | `u8` | target |
| `0x01` | `u32` | offset or absolute address |
| `0x05` | bytes | data to program |

WRITE data MUST NOT exceed 4080 bytes. `FGCB` addresses and lengths
MUST be multiples of 32, so its largest request contains 4064 data bytes.
`SPIN` writes MAY cross page boundaries; the service splits them into physical
page-program operations. `BKPS` accepts unaligned byte ranges and does not
require an erase operation.

WRITE does not erase storage. Before programming `FGCB` or `SPIN`, the client
MUST issue suitable ERASE commands. `BKPS` is overwritten directly. Before
returning success, the service MUST read each written fragment back and compare
it with the request.

The successful response payload MUST be empty.

### RESET (`0x06`)

The request and successful response payloads MUST be empty. The service MUST
complete CAN transmission of the response before requesting an MCU system
reset.

## Status values

| Value | Name | Meaning |
|-------|------|---------|
| `0x00` | `OK` | command completed |
| `0x01` | `BadCommand` | command is not implemented |
| `0x02` | `BadLength` | packet or command payload is invalid |
| `0x03` | `BadCrc` | packet CRC does not match |
| `0x04` | `BadVersion` | protocol version is unsupported |
| `0x05` | `BadTarget` | target ID is unknown |
| `0x06` | `RangeError` | range or required alignment is invalid |
| `0x07` | `ReadFailure` | storage read failed |
| `0x08` | `EraseFailure` | erase or erase verification failed |
| `0x09` | `WriteFailure` | storage programming failed |
| `0x0a` | `VerifyFailure` | programmed data did not match readback |
| `0x0b` | `EntryTimeout` | AirCANnect did not enter service mode in time |

Values `0x0c..0xff` are reserved for compatible extension. A client MUST treat
every unknown nonzero status as command failure.

## Error mapping

The 0.8.0 service reports the first error reached in its validation order.
Malformed ISO-TP or a packet too short to contain the service header and CRC
produces no service response.

General packet validation:

| Condition | Result |
|-----------|--------|
| complete packet size differs from `8 + payload_length + 2` | `BadLength`, if magic is valid; otherwise no response |
| magic is not `0xa5` | no response |
| protocol version is not 2 | `BadVersion` |
| CRC16 does not match | `BadCrc` |
| request status is not zero | `BadLength` |
| command is not assigned | `BadCommand` |

Command validation:

| Command | Condition | Status |
|---------|-----------|--------|
| INFO | payload is not empty | `BadLength` |
| READ | payload size is not 7 bytes | `BadLength` |
| READ | length is zero or greater than 4085 | `BadLength` |
| READ | target is unknown | `BadTarget` |
| READ | requested range is outside the target | `RangeError` |
| READ | SPI-NOR transfer fails | `ReadFailure` |
| ERASE | payload size is not 9 bytes | `BadLength` |
| ERASE | target is unknown | `BadTarget` |
| ERASE | target is `BKPS` | `BadTarget` |
| ERASE | requested range is outside the target | `RangeError` |
| ERASE | `FGCB` length is not 128 KiB or address is not sector-aligned | `RangeError` |
| ERASE | `FGCB` erase or erased-state verification fails | `EraseFailure` |
| ERASE | `SPIN` length/alignment is not an aligned 4 KiB or 64 KiB block | `EraseFailure` |
| ERASE | `SPIN` erase or erased-state verification fails | `EraseFailure` |
| WRITE | payload contains no data or data exceeds 4080 bytes | `BadLength` |
| WRITE | target is unknown | `BadTarget` |
| WRITE | requested range is outside the target | `RangeError` |
| WRITE | `FGCB` address or data length is not 32-byte aligned | `RangeError` |
| WRITE | storage programming or required readback fails | `WriteFailure` |
| WRITE | readback data differs from request data | `VerifyFailure` |
| RESET | payload is not empty | `BadLength` |

If response transmission itself fails, the service cannot report a status.
RESET requests the MCU reset only after its successful response has completed
CAN transmission.

## AirCANnect TCP transport

AirCANnect exposes complete service packets over its TCP endpoint, normally on
port 39011. This bypasses host-side CAN framing:

1. connect to the TCP endpoint;
2. send one complete service request packet, beginning with `0xa5`;
3. read the eight-byte response header;
4. read `payload_length + 2` more bytes;
5. validate the service packet and CRC before sending the next request.

There is no TCP length prefix, delimiter, JSON encoding, or ISO-TP framing.
The service header provides the record length. A TCP client MUST receive the
complete response before sending another request. Binary service traffic is
separate from AirCANnect's line-oriented JSON-RPC behavior.

AirCANnect intercepts command `0x01` (`ENTER`) on this TCP endpoint and MUST
NOT forward it to the device. The request status and payload MUST be zero and
empty. AirCANnect uses the ENTER sequence for its internal INFO transaction.
Before sending `ResetDevice(Fast)`, it MUST block new bridge-managed RPC and
complete or cancel operations already in flight. It then transmits entry
traffic until the internal INFO succeeds or 30 seconds elapse.

On success, AirCANnect returns ENTER with status `OK`, the request sequence,
and exactly the 19-byte INFO payload. It leaves the connection open in normal
packet-bridge mode and MUST NOT forward the intercepted INFO response again.
CAN ownership remains exclusive to that service connection until it closes.
On timeout AirCANnect returns ENTER with `EntryTimeout`, closes the connection,
and releases ownership. A disconnect or other failure MUST also release it
immediately.

## Implementation checklist

A conforming client MUST:

1. serialize all integers little-endian;
2. select a 16-bit sequence per transaction;
3. reject responses with a different command or sequence;
4. validate packet length, magic, version, and CRC before using the payload;
5. obey Flow Control `BS` and `STmin` when using direct CAN;
6. enforce target bounds and erase/program alignment before mutation;
7. issue only one request at a time and treat timeouts as an unknown result.

The maintained reference codec is
[`python/lib/as11_service.py`](../../python/lib/as11_service.py).

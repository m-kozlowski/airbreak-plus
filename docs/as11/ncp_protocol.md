# Air11 NCP Binary RPC Protocol

Air11 RPC supports two encodings: the binary `NcpCommandBuffer` encoding
documented here and the JSON encoding documented in the
[RPC protocol](rpc_protocol.md). Both encodings use the same numeric command
IDs, service registry, command handlers, and per-channel permission table.

NCP can therefore invoke standard RPC services by command ID. It also exposes
binary-only command IDs for direct DataItem access, bounded memory windows,
periodic sample transfer, and diagnostics. These additional commands are only
one part of the NCP interface.

In this document, NCP means the `NcpCommandBuffer` encoding. It is unrelated
to the Bluetooth network coprocessor described in the
[Bluetooth protocol](bluetooth_protocol.md).

## Contents

- [RPC stack](#rpc-stack)
- [Transport channels](#transport-channels)
- [Record format](#record-format)
- [Command dispatch and permissions](#command-dispatch-and-permissions)
- [Standard RPC commands](#standard-rpc-commands)
- [DataItem access](#dataitem-access)
- [Runtime attributes](#runtime-attributes)
- [Memory windows](#memory-windows)
- [Periodic mappings](#periodic-mappings)
- [Diagnostic commands](#diagnostic-commands)

## RPC stack

The endpoint catalog assigns every RPC channel a transport role, an encoding,
a response VCID, and buffer capacities. Request processing then follows the
same path for both encodings:

1. The endpoint catalog selects buffer `0` for NCP or buffer `1` for JSON.
2. The selected decoder produces a numeric command ID. NCP carries the ID in
   the record header; JSON resolves a method name through the method table.
3. The permission table checks the command ID against the endpoint's response
   VCID.
4. The executor selects a registered service by command ID and transport role.
5. The selected buffer decodes the service request and encodes its response.

Service registrations use these executor roles:

| Role | Channel family |
|-----:|----------------|
| 0 | CAN |
| 1 | Bluetooth |
| 2 | Steehl local RPC |
| 3 | cellular/internal |
| `0xfe` | all roles |

The encoding is not part of the service-registry key. A service registered for
a role can be reached through either encoding assigned to that role, subject
to its command permission. Services registered with role `0xfe` are shared by
all channel families.

JSON-only names and NCP-only command IDs arise before service dispatch. The
JSON decoder can use only names present in its method table; the NCP decoder
accepts the numeric command ID directly.

## Transport channels

NCP occupies the small binary endpoint in each transport family. The even
VCID is the command-permission selector and device response channel; the
adjacent odd VCID carries host requests.

| Transport | Request VCID | Response VCID | Request capacity | Response capacity |
|-----------|-------------:|--------------:|-----------------:|------------------:|
| CAN | `0x0381` | `0x0380` | 600 bytes | 600 bytes |
| BLE plaintext | `0x0391` | `0x0390` | 600 bytes | 600 bytes |
| BLE encrypted | `0x0395` | `0x0394` | 600 bytes | 632 bytes |
| internal/cellular | `0x0781` | `0x0780` | 1024 bytes | 1024 bytes |

On CAN, the NCP payload uses the normal DatagramCan framing described in the
[CAN protocol](can_protocol.md#datagramcan-frame-format). BLE carries the same
payload in a FIG packet.

The adjacent large endpoints select the JSON buffer and do not accept NCP
records, even when the same command is permitted on both endpoint VCIDs.

## Record format

All integers are little-endian. A transport datagram can contain one or more
concatenated NCP records.

Request record:

| Offset | Size | Field | Meaning |
|--------|-----:|-------|---------|
| `0x00` | 2 | length | bytes from `command` through the end of `payload` |
| `0x02` | 1 | command | request command ID |
| `0x03` | 1 | request tag | caller-selected response tag; `0xff` suppresses the response |
| `0x04` | variable | payload | command-specific arguments |

The complete record occupies `length + 2` bytes. The minimum valid `length`
is 2.

Successful responses use the command's response ID, normally the
request ID plus `0x80`, and echo the request tag:

| Offset | Size | Field |
|--------|-----:|-------|
| `0x00` | 2 | length |
| `0x02` | 1 | response command |
| `0x03` | 1 | echoed request tag |
| `0x04` | variable | result payload |

Errors use response command `0xfd`. The error payload is:

| Field | Encoding |
|-------|----------|
| status | `u16` |
| message | `u16` byte length followed by UTF-8 bytes |
| detail | `u16` byte length followed by a JSON value; zero when absent |

The NCP record has no independent checksum. Integrity belongs to the outer
DatagramCan or FIG transport.

## Command dispatch and permissions

The command permission matrix is shared with JSON-RPC and is indexed by
numeric command ID and response VCID. Permission-set names in the
[RPC method index](rpc_protocol.md#method-index) map to the NCP channels as
follows:

| Stock access | Permitted NCP response VCIDs |
|--------------|------------------------------|
| all | `0x0380`, `0x0390`, `0x0394`, `0x0780` |
| application | `0x0380`, `0x0394`, `0x0780` |
| service | `0x0380`, `0x0780` |
| BLE plaintext | `0x0390` |
| BLE encrypted | `0x0394` |

The additional binary commands documented below use these stock permissions:

| Commands | CAN `0x0380` | BLE `0x0390` | BLE `0x0394` | Internal `0x0780` |
|----------|---------------|--------------|--------------|-------------------|
| `0x01`, `0x07..0x10`, `0x23`, `0x26..0x2d`, `0x37`, `0x38` | permitted | blocked | blocked | permitted |
| `0x2e..0x35` | blocked | blocked | blocked | permitted |

Permission is only the first dispatch gate. The command must also have a
registered service for the channel role, and its own parameter, state, and
hardware checks still apply.

## Standard RPC commands

NCP uses the numeric IDs in the `Command` column of the
[RPC method index](rpc_protocol.md#method-index). This applies to services
registered once for all roles as well as services with separate CAN,
Bluetooth, local, and cellular instances.

NCP request and result payloads use each service's binary schema; they are not
JSON `params` or JSON result objects embedded in an NCP record. This document
defines the common NCP envelope and the additional binary-only command ABI.
Standard method semantics and permissions remain in the
[RPC protocol](rpc_protocol.md).

Numeric command IDs without a JSON method-table entry remain reachable only
through NCP. The DataItem, memory-window, mapping, and diagnostic commands in
the following sections belong to this group.

## DataItem access

DataItem commands identify a variable by its three-byte short tag, without a
terminating zero. Firmware resolves the tag with `var_tag3_to_id()` and then
requires the DataItem's NCP-accessible flag. An unknown tag or a DataItem
without that flag is rejected.

| Command | Response | Request payload | Result |
|--------:|---------:|-----------------|--------|
| `0x07` | `0x87` | `tag[3]` | current raw value as `i32` |
| `0x08` | `0x88` | `tag[3]`, raw `i32`, runtime attribute `u8` | apply attribute, set raw value, commit |
| `0x09` | `0x89` | `tag[3]` | native text value as `u16` length and bytes |
| `0x0a` | `0x8a` | `tag[3]`, `u16` value length, value bytes, runtime attribute `u8` | apply attribute, set from native text, commit |
| `0x0b` | `0x8b` | `tag[3]` | one-byte runtime status mask |
| `0x0c` | `0x8c` | `tag[3]`, runtime attribute `u8` | apply a runtime attribute |
| `0x0f` | `0x8f` | numeric `tag[3]` | effective maximum in raw units as `i32` |
| `0x10` | `0x90` | numeric `tag[3]` | effective minimum in raw units as `i32` |
| `0x2b` | `0xab` | `tag[3]` | clear runtime flag `0x0040` |
| `0x2c` | `0xac` | none | clear runtime flag `0x0040` on all DataItems |

Commands `0x09` and `0x0a` use the DataItem implementation's native text
formatter and parser:

| DataItem family | Native text value |
|-----------------|-------------------|
| volatile text | literal string |
| numeric | descriptor-scaled decimal value, such as `12.4` |
| bitfield | decimal integer mask |
| enum | symbolic option name, or a decimal raw value when no symbol is available |

Numeric input is converted through the descriptor scale and rounded to the
underlying integer value. Enum input is resolved as a symbolic option name
first, with a base-10 integer accepted as a fallback. An unavailable numeric
or bitfield value is formatted as `--`.

Commands `0x08` and `0x0a` use the normal DataItem commit path with
persistence and change notification enabled. Persistence still depends on the
DataItem's backing implementation. These handlers do not test the JSON-RPC
writeable flag.

The `0x0b` status byte is assembled as follows:

| Bit | Meaning when set |
|----:|------------------|
| 0 | active |
| 1 | visible and active |
| 2 | mode-bound and active |
| 3 | reserved; written as zero |
| 4 | the valid-and-available predicate failed |
| 5 | available |
| 6 | runtime flag `0x0040` |
| 7 | reserved; written as zero |

Numeric limits returned by `0x0f` and `0x10` are the current effective limits,
including dynamic bounds, and are not converted through the descriptor scale.

## Runtime attributes

The attribute accepted by `0x08`, `0x0a`, and `0x0c` controls runtime DataItem
state. It does not edit the CONF descriptor.

| Value | Operation |
|------:|-----------|
| 0 | leave runtime attributes unchanged |
| 1 | clear active |
| 2 | set active |
| 3 | clear visible |
| 4 | set visible |
| 5 | clear mode-bound |
| 6 | set mode-bound |
| 7 | clear runtime flag `0x0040` |
| 8 | set runtime flag `0x0040` |
| 9 | clear runtime inhibit selector 1 |
| 10 | set runtime inhibit selector 1 |

Other attribute values are rejected.

## Memory windows

NCP exposes two bounded windows. These commands do not provide
arbitrary memory access.

| Selector | Storage | Size |
|---------:|---------|-----:|
| 1 | NCP shadow window | 2048 bytes |
| 2 | backup SRAM window | 4096 bytes |

### Write window (`0x26` / `0xa6`)

Request payload:

```text
selector:u8 offset:u16 length:u16 data[length]
```

The write must remain inside the selected window.

### Read window (`0x27` / `0xa7`)

Request payload:

```text
selector:u8 offset:u16 length:u16
```

The response is `u16 length` followed by the requested bytes. The result must
also fit in the remaining NCP response buffer.

## Periodic mappings

Periodic mappings transfer signed 16-bit raw samples between a DataItem and
the 2048-byte shadow window. Backup SRAM is not used by this mechanism.

| Command | Response | Direction |
|--------:|---------:|-----------|
| `0x28` | `0xa8` | shadow window to DataItem |
| `0x29` | `0xa9` | DataItem to shadow window |
| `0x2a` | `0xaa` | remove mapping |

Commands `0x28` and `0x29` use this payload:

```text
mapping:u8 offset:u16 samples:u16 period_ms:u16 tag[3] wrap:u8
```

Constraints:

- `mapping` is `0..30`;
- `offset + samples * 2` must fit in the 2048-byte shadow window;
- `period_ms` must be one of `10`, `20`, `40`, `100`, `160`, `200`, `1000`,
  `2000`, or `60000`;
- each transfer reads or writes one signed 16-bit raw sample;
- nonzero `wrap` restarts at sample zero after the configured sample count.

The window-to-DataItem direction sets runtime flag `0x0040` and commits every
transferred sample. The DataItem-to-window direction truncates the current raw
value to 16 bits.

Command `0x2a` takes:

```text
mapping:u8 clear_runtime_flag:u8
```

When removing a window-to-DataItem mapping, a nonzero second field clears the
DataItem's runtime flag `0x0040`.

## Diagnostic commands

| Command | Response | Request payload | Operation |
|--------:|---------:|-----------------|-----------|
| `0x01` | `0x81` | none | no-op |
| `0x0d` | `0x8d` | fatal-state slot `u8` | read slot as `u32` |
| `0x0e` | `0x8e` | slot `u8`, value `u32` | write fatal-state slot |
| `0x23` | `0xa3` | none | no-op |
| `0x37` | `0xb7` | `tag[3]`, index `u16` | lookup runtime fixed string `TAG_XXXX` |
| `0x38` | `0xb8` | fault selector `u8` | invoke a diagnostic fault path |

The `index` accepted by command `0x37` is `0..19`. The command formats its key
as the three-byte tag, an underscore, and four hexadecimal digits. The
response is a `u16` length followed by up to 100 value bytes; a missing key
returns an empty value.

Fault selectors are:

| Selector | Operation |
|---------:|-----------|
| 0 | report a fatal error |
| 1 | invalid-memory fault path |
| 2 | divide-by-zero fault path |
| 3 | undefined instruction |
| 4 | exhaust the task stack recursively |
| 5 | allocate and leak one heap byte |
| 6 | lock the scheduler and loop indefinitely |

Commands `0x2d` through `0x35` are parser-test slots. Their handlers either
consume test scalar/blob payloads or return a fixed result; they do not expose
an application operation. Commands `0x2e` through `0x35` are restricted to
the internal NCP permission channel in the stock table.

# Air11 OTA Protocol

Air11 firmware upgrades are staged through RPC, verified by the running
application, then applied after reboot by the lower updater path.

The local BLE and CAN upload flows use the same RPC methods and OTA container
formats.

## Contents

- [RPC sequence](#rpc-sequence)
- [Transfer blocks](#transfer-blocks)
- [Staged file](#staged-file)
- [Hash and authentication](#hash-and-authentication)
- [Retrieving the local OTA key](#retrieving-the-local-ota-key)
- [Common primary header](#common-primary-header)
- [Format 0005](#format-0005)
- [0005 targets](#0005-targets)
- [0005 compatibility fingerprints](#0005-compatibility-fingerprints)
- [Format 0006](#format-0006)
- [Format selection](#format-selection)
- [Error codes](#error-codes)

## RPC sequence

Upload:

```text
InitiateUpgrade({"upgradeFileSize": N})
  -> {"xferBlockSize": 500}

UpgradeDataBlock({
  "fileOffset": offset,
  "encoding": "AsciiHex",
  "data": "<hex bytes>"
})
  -> true

CheckUpgradeFile({"upgradeFileHash": "<SHA256 of full OTA file>"})
  -> true
```

Apply:

```text
ApplyAuthenticatedUpgrade({
  "upgradeFileHash": "<SHA256 of full OTA file>",
  "authentication": "<HMAC-SHA256 tag>"
})
```

Service transports can also expose:

```text
ApplyUpgrade({
  "upgradeFileHash": "<SHA256 of full OTA file>",
  "resetSettingsToDefault": false
})
```

Successful authenticated apply returns:

```json
{
  "confirmResult": "MatchingFileUpgradeTriggered",
  "estimatedApplySec": 40
}
```

The device then disconnects/reboots into the apply path.

## Transfer blocks

`InitiateUpgrade` returns `xferBlockSize`. On tested 15.8.4.0 firmware this is
500 raw bytes.

`UpgradeDataBlock.data` is ASCII hex, so the JSON string contains up to 1000
hex characters per 500-byte block.

Blocks are offset-addressed. Retrying the same block with the same
`fileOffset` and same bytes is safe.

## Staged file

The local upload path and cloud-style path converge on a staged file in NOR:

```text
nor:2:\UPGRADE\Upgrade.abc
```

`CheckUpgradeFile` verifies this staged file against the supplied SHA-256.

## Hash and authentication

`upgradeFileHash` is:

```text
SHA256(full OTA container bytes)
```

It is sent as uppercase hex.

`ApplyAuthenticatedUpgrade.authentication` is:

```text
HMAC-SHA256(ota_key, raw_sha256_digest)
```

The tag is sent as uppercase hex. The HMAC input is the raw 32-byte SHA-256
digest, not the ASCII hex string.

The OTA key is loaded at runtime by the firmware security-material provider.
Device dumps so far indicate the OTA key can vary per device.

## Retrieving the local OTA key

For a device connected over SWD/OpenOCD, the repository includes a small
read-only helper:

```text
tcl/as11-keys.tcl
```

It resets and halts the target, configures the SPI5 NOR pins used by the
device, reads a 32-byte slot from the firmware `SecurityData` area, prints it
as 64 uppercase hex characters, then resets/runs the target again. The OTA
key is selected by default.

At the OpenOCD prompt:

```tcl
as11_keys::key
```

`as11_keys::key OTA` selects the same identified OTA slot. Numeric indexes
`0..7` provide raw access to 32-byte chunks in the second half of
`SecurityData`:

```tcl
as11_keys::key OTA
as11_keys::key 0
```

Index `0` contains the OTA key. The individual roles of indexes `1..7` are not
identified.

The helper refuses all-00/all-ff reads as suspicious. Treat the printed value
as device secret material; do not paste it into logs or public docs.

`python/as11_config.py devices ota-key <alias> --key-file <path>` can store the
device's OTA key in the existing BLE credential record; see
[as11_config devices](../tools/as11_config.md#devices).  
`python/as11_flash.py` uses stored BLE `otaKey` values for authenticated apply
when `--key`, `--key-file`, and `AS11_OTA_KEY` are not set.  
Explicit command-line keys still take precedence.

## Common primary header

Both known OTA formats start with a 0x58-byte primary header:

| Offset | Size | Field |
|--------|------|-------|
| `0x00` | 4 | ASCII `OTA!` |
| `0x04` | 4 | ASCII format, `0005` or `0006` |
| `0x08` | 64 | format/component-specific reserved data |
| `0x48` | 16 | component string, NUL-padded |

Known component strings:

| Component | Notes |
|-----------|-------|
| `PacificFG` | main device firmware path |
| `PacificBT` | Bluetooth module path in app verifier |
| `AlarmModule` | accepted only on supported hardware/config paths |

## Format 0005

`0005` is the flexible partial/full firmware update format.

Layout:

| Offset | Size | Meaning |
|--------|------|---------|
| `0x000` | `0x58` | primary header |
| `0x058` | `0x50` | secondary descriptor |
| `0x0a8` | rest | segment table plus segment data |

Secondary descriptor:

| Offset | Size | Meaning |
|--------|------|---------|
| `0x00` | 4 | marker, must be `1` |
| `0x04` | 4 | target code: `CONF`, `APPL`, `APCX`, `FGBL`, or `FGCB` |
| `0x08` | 4 | CONF/APPL compatibility fingerprint |
| `0x0c` | 4 | FGBL/APPL compatibility fingerprint |
| `0x10` | 4 | flow-generator security fingerprint; checked against `_SKF` when `_SBA` is `Yes` |
| `0x40` | 4 | rest length |
| `0x44` | 4 | CRC32 over rest |
| `0x48` | 4 | segment count, required `1..0xff` for apply |
| `0x4c` | 4 | CRC32 over primary header plus descriptor bytes `0x00..0x4b` |

The rest begins with a segment table:

```text
rest = segment_count * {u32 length, u32 flash_start} || segment_data
```

Each segment destination is an absolute STM32 flash address. Segment data is
the concatenation of the segment payloads.

The application-side verifier can accept a descriptor with segment count 0 if
the rest CRC matches, but the lower apply path has no segment to write. Valid
containers should use at least one segment.

## 0005 targets

Known target codes:

| Code | Flash range | Size | Meaning |
|------|-------------|------|---------|
| `FGBL` | `0x08000000..0x08020000` | `0x020000` | low updater / boot region |
| `CONF` | `0x08020000..0x08040000` | `0x020000` | config/aux block |
| `APPL` | `0x08040000..0x08200000` | `0x1c0000` | main application |
| `APCX` | `0x08020000..0x08200000` | `0x1e0000` | `CONF` plus `APPL` |
| `FGCB` | `0x08000000..0x08200000` | `0x200000` | complete internal flash |

Primitive hardware regions carry CRC16-CCITT at the end of the region:

| Region | CRC coverage |
|--------|--------------|
| `FGBL` | bytes `0x00000..0x1fffd`, stored big-endian at `0x1fffe` |
| `CONF` | bytes `0x20000..0x3fffd`, stored big-endian at `0x3fffe` |
| `APPL` | bytes `0x40000..0x1ffffd`, stored big-endian at `0x1ffffe` |

When building partial containers, update the target region CRC16 before
wrapping it in the OTA container.

## 0005 compatibility fingerprints

The secondary descriptor carries compatibility fingerprints for the two
internal-flash component boundaries:

| CLI override | Boundary |
|--------------|----------|
| `--conf-appl-fingerprint` | CONF/APPL |
| `--fgbl-appl-fingerprint` | FGBL/APPL |

The application verifier checks a boundary fingerprint when an update replaces
only one side of that boundary. A target that replaces both sides does not need
that fingerprint.

| Target | CONF/APPL fingerprint | FGBL/APPL fingerprint |
|--------|-----------------------|-----------------------|
| `CONF` | checked | ignored |
| `APPL` | checked | checked |
| `APCX` | ignored | checked |
| `FGBL` | ignored | checked |
| `FGCB` | ignored | ignored |

The boundary fingerprints are compared with constants compiled into the
running APPL. They are independent of the payload and descriptor CRCs. The
SRAM updater does not repeat these checks.

The flow-generator security fingerprint at descriptor offset `0x10` is checked
separately. When `_SBA` is `Yes`, it must equal `_SKF`; a mismatch rejects the
container and emits `FgUpgradeFileFingerprintMismatch`. When `_SBA` is `No`,
the field is ignored. `_SBE` is populated from the same firmware security
record but does not participate in this comparison.

Known values:

| Firmware | CONF/APPL | FGBL/APPL |
|----------|-----------|-----------|
| 14.8.3.0 | `0x2D89E58F` | `0xBEB37EE2` |
| 15.8.4.0 | `0xD785ABA6` | `0xBEB37EE2` |
| 16.8.5.0 | `0x7862CBA7` | `0xBEB37EE2` |
| 17.8.6.0 | `0xBECBC5BC` | `0xBEB37EE2` |

## Format 0006

`0006` carries a component payload directly after the primary header.

Layout:

| Offset | Size | Meaning |
|--------|------|---------|
| `0x000` | `0x58` | primary header |
| `0x058` | rest | payload |

There is no secondary descriptor and no segment table.

Component handling:

| Component | Target code | Result |
|-----------|------------:|--------|
| `PacificFG` | 5 | accepted for staging, but rejected by the local SRAM updater |
| `AlarmModule` | 7 | forwarded to the external alarm module when its platform gate is enabled |
| `PacificBT` | none | rejected for `0006` |

The application can stage a `0006/PacificFG` container and successfully
validate its supplied SHA-256. The local SRAM updater accepts only
`0005/PacificFG` with a complete descriptor and segment table, and rejects the
`0006` file before erasing or programming internal flash.

For `AlarmModule`, Air11 forwards the staged file through the module upgrade
RPC sequence: `InitiateUpgrade`, `UpgradeDataBlock`, `CheckUpgradeFile`, and
`ApplyUpgrade`.

## Format selection

Use `0005` for real partial or full firmware flashing. It carries explicit
target information and the segment table consumed by the lower apply path.

Format `0006` is not an Air11 internal-flash format. It is not supported by
`as11_flash.py`.

## Error codes

Observed OTA errors:

| Code | Message | Confirmed stage or condition |
|------|---------|------------------------------|
| `-11001` | unknown | returned by an `InitiateUpgrade` pre-check; exact predicate not identified |
| `-11004` | unknown | returned by an `InitiateUpgrade` pre-check; exact predicate not identified |
| `-11305` | `UpgradeFileIntegrityFailure` | SHA-256, descriptor CRC, rest CRC, or region CRC verification failed |
| `-11306` | `UpgradeFileAuthenticationFailure` | authenticated-apply HMAC verification failed |
| `-11308` | `UpgradeFileIncompatible` | format, component, or target compatibility gate rejected the container |
| `-11309` | `UpgradeFileInvalid` | OTA container structure was rejected as malformed |

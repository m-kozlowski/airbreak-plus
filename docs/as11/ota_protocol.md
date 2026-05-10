# AS11 OTA Protocol

AS11 firmware upgrades are staged through RPC, verified by the running
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
- [0005 descriptor presets](#0005-descriptor-presets)
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

For a locally owned device attached over SWD/OpenOCD, the repo includes a
small read-only helper:

```text
tcl/as11-keys.tcl
```

It resets and halts the target, configures the SPI5 NOR pins used by the
device, reads one 32-byte provider key slot, prints it as 64 uppercase hex
characters, then resets/runs the target again.

OpenOCD usage after loading the normal target config:

```tcl
source tcl/as11-keys.tcl
as11_keys::key
```

`as11_keys::key` defaults to the OTA slot. Other provider key slots can be
read by numeric index when explicitly needed:

```tcl
as11_keys::key OTA
as11_keys::key 0
```

The helper refuses all-00/all-ff reads as suspicious. Treat the printed value
as device secret material; do not paste it into logs or public docs.

`python/as11_config.py devices ota-key <alias> --key-file <path>` can store
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
| `0x08` | 4 | `desc2`, firmware-version-specific |
| `0x0c` | 4 | `desc3`, firmware-version-specific |
| `0x10` | 4 | PCI value, checked when `_PRI == 1` |
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

## 0005 descriptor presets

`desc2` and `desc3` are version-specific constructor constants for several
targets.

| Firmware | `desc2` | `desc3` |
|----------|---------|---------|
| 14.8.3.0 | `0x2D89E58F` | `0xBEB37EE2` |
| 15.8.4.0 | `0xD785ABA6` | `0xBEB37EE2` |

`FGCB` does not require these descriptor fields. `CONF`, `APPL`, `APCX`, and
`FGBL` do.

## Format 0006

`0006` is a simplified app-verifier path seen in 15.8.4.0.

Layout:

| Offset | Size | Meaning |
|--------|------|---------|
| `0x000` | `0x58` | primary header |
| `0x058` | rest | payload |

There is no secondary descriptor and no segment table.

Observed 15.8.4.0 component handling:

| Component | App verifier marker | Result |
|-----------|---------------------|--------|
| `PacificFG` | 5 | accepted by app verifier |
| `AlarmModule` | 7 | accepted if platform gate passes |
| `PacificBT` | none | rejected |

Important caveat: 15.8.4.0 app-side `CheckUpgradeFile` and
`ApplyAuthenticatedUpgrade` can accept a minimal `0006/PacificFG` container,
but the low updater region found so far contains `OTA!0005` strings and no
nearby `0006` string. Treat `0006` as app-verifier-proven, not apply-proven.

## Format selection

Use `0005` for real partial or full firmware flashing. It carries explicit
target information and the segment table consumed by the lower apply path.

Use `0006` only for verifier experiments unless the lower updater has been
traced or a flash readback proves it applied correctly.

## Error codes

Observed OTA errors:

| Code | Message | Likely cause |
|------|---------|--------------|
| `-11001` | unknown | `InitiateUpgrade` pre-check |
| `-11004` | unknown | `InitiateUpgrade` pre-check |
| `-11305` | `UpgradeFileIntegrityFailure` | SHA-256, descriptor CRC, rest CRC, or region CRC mismatch |
| `-11306` | `UpgradeFileAuthenticationFailure` | authenticated apply HMAC mismatch |
| `-11308` | `UpgradeFileIncompatible` | format/component/target gate rejected |
| `-11309` | `UpgradeFileInvalid` | malformed OTA container |

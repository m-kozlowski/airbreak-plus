# as11_nor_tool

`as11_nor_tool.py` inspects and edits complete 16 MiB Air11 external SPI NOR
dumps.

## Layout

The first 64 KiB erase block contains raw security and manufacturing data. The
rest of the device is split into three Micrium uC/FS NOR devices:

| Device | Physical range | Logical filesystem |
|--------|----------------|--------------------|
| `nor:0` | `0x010000..0x06ffff` | settings |
| `nor:1` | `0x070000..0xa7ffff` | datalog |
| `nor:2` | `0xa80000..0xffffff` | firmware upgrade staging |

The physical ranges are wear-levelled. They are not directly mountable FAT
images. The tool rebuilds the native logical-to-physical sector map and then
exposes each logical FAT12 filesystem.

Named raw regions:

| Name | Offset | Size | Alias |
|------|-------:|-----:|-------|
| `security-data` | `0x000000` | `0x200` | `security` |
| `auth-key-ring` | `0x000000` | `0x100` | `auth-keys` |
| `ota-key` | `0x000100` | `0x20` | `ota` |
| `steehl-security-data` | `0x000180` | `0x80` | `steehl-security` |
| `manufacturing-data` | `0x00e000` | `0x400` | `md0`, `_md0` |
| `manufacturing-test-record` | `0x00f000` | `0x400` | `md1`, `_md1` |

## Inspection

```
python3 python/as11_nor_tool.py nor.bin info
python3 python/as11_nor_tool.py nor.bin info --json
python3 python/as11_nor_tool.py nor.bin region-list
```

`info` reports the FTL geometry, erase-count range, sector-state counts,
logical mapping coverage, CRC errors, and FAT geometry for every volume.
List commands use aligned tables by default and accept `--json` for structured
output.

## Raw Regions

```
python3 python/as11_nor_tool.py nor.bin region-get md0 MD0.bin
python3 python/as11_nor_tool.py nor.bin region-get md1 MD1.bin
```

Use `-` as the output name to write bytes to standard output.

## Security Data

The first `0x200` bytes form one `SecurityData` object. `StoreSecurityData`
replaces the complete object and `VerifySecurityData` verifies its SHA-256
digest.

The first `0x100` bytes are a cyclic key ring used by `GenerateAuthCode`. For
HMAC-SHA256, `keyLocation` selects the first byte of a 32-byte key. Reads that
cross offset `0x100` continue at offset `0x000`.

The device-specific OTA key occupies `0x100..0x11f`. The range
`0x180..0x1ff` is exposed to the Steehl service. The purpose of
`0x120..0x17f` is not identified.

`key-list` reports named keys without printing key material. Currently only
the OTA key has an independently confirmed name and range. `key-get` prints it
as 64 uppercase hex characters. `--output` writes the same hex text to a file:

```
python3 python/as11_nor_tool.py nor.bin key-list
python3 python/as11_nor_tool.py nor.bin key-get OTA
python3 python/as11_nor_tool.py nor.bin key-get OTA --output ota-key.txt
python3 python/as11_config.py devices ota-key bedroom --key-file ota-key.txt
```

`key-set` accepts hex directly or reads either 32 raw bytes or hex text from a
file. It updates the input image by default:

```
python3 python/as11_nor_tool.py nor.bin key-set OTA HEX64
python3 python/as11_nor_tool.py nor.bin key-set OTA --key-file ota-key.txt
```

Use `--output` to write a modified copy instead:

```
python3 python/as11_nor_tool.py nor.bin key-set OTA HEX64 \
    --output nor-with-key.bin
```

The key name is always explicit.

## FAT Filesystems

The `fat-*` commands require the optional `pyfatfs` package. They are not
registered when it is unavailable.

List files:

```
python3 python/as11_nor_tool.py nor.bin fat-ls settings /
python3 python/as11_nor_tool.py nor.bin fat-ls datalog / -r
python3 python/as11_nor_tool.py nor.bin fat-ls upgrade /
```

Extract a file or directory tree:

```
python3 python/as11_nor_tool.py nor.bin fat-get \
    datalog /Summary.bin Summary.bin
python3 python/as11_nor_tool.py nor.bin fat-getdir \
    settings /SETTINGS settings-backup/
```

Write one file or a directory tree:

```
python3 python/as11_nor_tool.py nor.bin fat-put \
    settings BGL.set /SETTINGS/BGL.set
python3 python/as11_nor_tool.py nor.bin fat-putdir \
    settings settings-backup/ /SETTINGS
```

Writes update the input image by default. Add `--output modified.bin` to write
a modified copy. `pyfatfs` handles directory entries and cluster allocation;
the NOR writer maps changed logical sectors into uC/FS records and updates the
sector data and header CRCs.

Volume arguments accept `settings`, `datalog`, `upgrade`, a numeric index, or
the native `nor:N` name.

## Staged Upgrade

`/UPGRADE/Upgrade.abc` is a fixed-size staging file with a four-byte used-size
prefix and zero-filled spare space. Use the upgrade commands to inspect or
extract the embedded OTA container itself:

```
python3 python/as11_nor_tool.py nor.bin upgrade-info
python3 python/as11_nor_tool.py nor.bin upgrade-get staged.abc
python3 python/as11_flash.py info staged.abc
```

## Logical Volume Images

`extract-volume` writes the reconstructed logical block device. The resulting
file starts with its FAT boot sector and can be inspected by other FAT tools.

```
python3 python/as11_nor_tool.py nor.bin extract-volume settings settings.fat
python3 python/as11_nor_tool.py nor.bin extract-volume datalog datalog.fat
python3 python/as11_nor_tool.py nor.bin extract-volume upgrade upgrade.fat
```

`extract-volume` does not provide a matching whole-volume import command. Use
`fat-put` or `fat-putdir` to replace files in the physical NOR image.

NOR dumps contain unit-specific manufacturing, settings, security, therapy,
and staged-upgrade data. Treat complete dumps and extracted trees as private.

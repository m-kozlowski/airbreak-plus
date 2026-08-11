# resmed_image

Offline block editor for Air10 and Air11 firmware images. It supports the
Air10 `SX577-0200` and `SX585-0200` layouts and known Air11 FGBL layouts. It
does not connect to a device.

| Platform | Full image | Blocks |
|----------|------------|--------|
| Air10 | 1 MiB | `BLX`, `CCX`, `CDX` |
| Air11 | 2 MiB | `FGBL`, `CONF`, `APPL` |

Each block source can be a complete image for its platform or a standalone
block of the expected size. Existing output files are overwritten without
warning.

## Inspect an image

```
resmed_image.py info firmware.bin
```

For a complete image, the output includes its bootloader identifier and the
offset, size, and stored CRC of each block. Standalone blocks are identified by
size and content and checked independently.

## Extract blocks from an image

```
resmed_image.py extract firmware.bin --blx bootloader.bin
resmed_image.py extract firmware.bin --blx bootloader.bin --cdx application.bin
resmed_image.py extract air11.bin --fgbl bootloader.bin \
    --conf configuration.bin --appl application.bin
```

The source must be a complete image and at least one block must be selected.
Each block CRC is checked before its output is written.

## Replace blocks in an image

```
resmed_image.py replace base.bin output.bin --blx bootloader.bin
resmed_image.py replace base.bin output.bin --ccx donor.bin --cdx donor.bin
resmed_image.py replace air11.bin output.bin --conf configuration.bin
```

Unspecified blocks are copied from `base.bin`.

## Compose an image

```
resmed_image.py compose output.bin \
    --blx bootloader.bin --ccx config.bin --cdx application.bin

resmed_image.py compose air11.bin \
    --fgbl bootloader.bin --conf configuration.bin --appl application.bin
```

All three blocks for one platform are required. Air10 and Air11 block options
cannot be mixed. BLX or FGBL selects the output layout.

## Compatibility checks

It rejects:

- unsupported or mismatched bootloader IDs
- block sizes that do not match the selected layout
- invalid block CRCs
- a CDX from the wrong platform family
- a CCX and CDX taken from full images with different software versions
- an unsupported Air11 FGBL ID

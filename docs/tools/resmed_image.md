# resmed_image

Offline block editor for Air 10 firmware images. It supports the `SX577-0200`
and `SX585-0200` layouts and does not connect to a device.

Each block source can be a complete 1 MB image or a standalone block of the
expected size. Existing output files are overwritten without warning.

## Inspect an image

```
resmed_image.py info firmware.bin
```

For a complete image, the output includes the bootloader ID, CDX software ID,
block offsets, sizes, and stored CRCs. Standalone blocks are identified by size
and checked independently.

## Extract blocks from an image

```
resmed_image.py extract firmware.bin --blx bootloader.bin
resmed_image.py extract firmware.bin --blx bootloader.bin --cdx application.bin
```

The source must be a complete image and at least one block must be selected.
Each block CRC is checked before its output is written.

## Replace blocks in an image

```
resmed_image.py replace base.bin output.bin --blx bootloader.bin
resmed_image.py replace base.bin output.bin --ccx donor.bin --cdx donor.bin
```

Unspecified blocks are copied from `base.bin`.

## Compose an image

```
resmed_image.py compose output.bin \
    --blx bootloader.bin --ccx config.bin --cdx application.bin
```

All three sources are required. The BLX selects the output layout.

## Compatibility checks

It rejects:

- unsupported or mismatched bootloader IDs
- block sizes that do not match the selected layout
- invalid block CRCs
- a CDX from the wrong platform family
- a CCX and CDX taken from full images with different software versions

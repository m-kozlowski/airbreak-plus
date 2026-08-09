#!/usr/bin/env python3
"""Inspect and extract complete Air11 external SPI NOR dumps."""

from __future__ import annotations

import argparse
import io
import json
import sys
import warnings
from pathlib import Path, PurePosixPath

from lib.as11_nor import (
    As11NorImage,
    NAMED_KEYS,
    NorFormatError,
    RAW_REGIONS,
)

try:
    from fs.errors import FSError
    from pyfatfs.PyFatFS import PyFatBytesIOFS
    HAVE_PYFATFS = True
except Exception:
    FSError = None
    PyFatBytesIOFS = None
    HAVE_PYFATFS = False

TOOL_ERRORS = (OSError, KeyError, ValueError)
if FSError is not None:
    TOOL_ERRORS += (FSError,)


def _hex_size(value: int) -> str:
    return f"0x{value:x}"


def _print_table(headers, rows, right=()):
    widths = [len(header) for header in headers]
    for row in rows:
        for index, value in enumerate(row):
            widths[index] = max(widths[index], len(value))

    def render(row):
        cells = []
        for index, value in enumerate(row):
            align = str.rjust if index in right else str.ljust
            cells.append(align(value, widths[index]))
        return "  ".join(cells).rstrip()

    print(render(headers))
    print(render(tuple("-" * width for width in widths)))
    for row in rows:
        print(render(row))


def _status_name(value: int) -> str:
    return {
        0xFFFF0000: "valid",
        0xFFFFFFFF: "erased",
        0xFFFFFF00: "writing",
        0x00000000: "discarded",
    }.get(value, f"0x{value:08x}")


def _fat_dict(volume):
    fat = volume.fat().info
    return {
        "oem": fat.oem,
        "volume_label": fat.volume_label,
        "fs_type": fat.fs_type,
        "bytes_per_sector": fat.bytes_per_sector,
        "sectors_per_cluster": fat.sectors_per_cluster,
        "reserved_sectors": fat.reserved_sectors,
        "fat_count": fat.fat_count,
        "root_entries": fat.root_entries,
        "sectors_per_fat": fat.sectors_per_fat,
        "total_sectors": fat.total_sectors,
        "fat_copy_state": fat.fat_copy_state,
    }


def _info_dict(image):
    raw_regions = []
    for region in RAW_REGIONS:
        data = image.read_region(region.name)
        raw_regions.append({
            "name": region.name,
            "offset": region.offset,
            "size": region.size,
            "non_ff_bytes": sum(value != 0xFF for value in data),
        })

    volumes = []
    for volume in image.volumes:
        headers = [h for h in volume.block_headers if h is not None]
        statuses = {
            _status_name(status): count
            for status, count in sorted(volume.status_counts.items())
        }
        entry = {
            "index": volume.index,
            "name": volume.name,
            "start": volume.start,
            "end": volume.end,
            "block_count": volume.block_count,
            "erase_count_min": min(h.erase_count for h in headers),
            "erase_count_max": max(h.erase_count for h in headers),
            "sector_size": volume.sector_size,
            "sectors_per_block": volume.sectors_per_block,
            "physical_sector_count": volume.physical_sector_count,
            "logical_sector_count": volume.logical_sector_count,
            "mapped_sector_count": volume.mapped_sector_count,
            "unmapped_sector_count": volume.unmapped_sector_count,
            "invalid_block_indexes": volume.invalid_block_indexes,
            "status_counts": statuses,
            "duplicate_valid_records": volume.duplicate_valid_records,
            "out_of_range_valid_records": volume.out_of_range_valid_records,
            "mapped_header_crc_errors": volume.mapped_header_crc_errors,
            "mapped_data_crc_errors": volume.mapped_data_crc_errors,
            "fat": _fat_dict(volume),
        }
        volumes.append(entry)

    return {
        "file": str(image.source) if image.source else None,
        "size": len(image.data),
        "sha256": image.sha256,
        "raw_regions": raw_regions,
        "volumes": volumes,
    }


def cmd_info(image, args):
    info = _info_dict(image)
    if args.json:
        print(json.dumps(info, indent=2))
        return

    print(f"File:   {info['file']}")
    print(f"Size:   {info['size']} bytes ({_hex_size(info['size'])})")
    print(f"SHA256: {info['sha256']}")
    print()
    print("Raw regions:")
    for region in info["raw_regions"]:
        print(
            f"  {region['name']:<27} "
            f"0x{region['offset']:06x}  {region['size']:5d} B  "
            f"non_ff={region['non_ff_bytes']}"
        )

    print()
    print("uC/FS NOR volumes:")
    for volume in info["volumes"]:
        invalid = (
            ",".join(str(i) for i in volume["invalid_block_indexes"])
            if volume["invalid_block_indexes"] else "none"
        )
        statuses = " ".join(
            f"{name}={count}"
            for name, count in volume["status_counts"].items()
        )
        fat = volume["fat"]
        print(
            f"  nor:{volume['index']} {volume['name']}  "
            f"0x{volume['start']:06x}..0x{volume['end'] - 1:06x}"
        )
        print(
            f"    blocks={volume['block_count']}  erase_count="
            f"{volume['erase_count_min']}..{volume['erase_count_max']}  "
            f"invalid_block={invalid}"
        )
        print(
            f"    sectors={volume['mapped_sector_count']}/"
            f"{volume['logical_sector_count']} mapped  "
            f"sector_size={volume['sector_size']}  {statuses}"
        )
        print(
            f"    crc_errors: header={volume['mapped_header_crc_errors']} "
            f"data={volume['mapped_data_crc_errors']}  "
            f"duplicates={volume['duplicate_valid_records']} "
            f"out_of_range={volume['out_of_range_valid_records']}"
        )
        print(
            f"    FAT: {fat['fs_type'] or 'FAT12'}  "
            f"label={fat['volume_label'] or 'n/a'}  "
            f"sectors={fat['total_sectors']}  "
            f"cluster={fat['sectors_per_cluster']} sectors  "
            f"fat_copies={fat['fat_copy_state']}"
        )


def cmd_region_list(image, args):
    regions = []
    for region in RAW_REGIONS:
        data = image.read_region(region.name)
        regions.append({
            "name": region.name,
            "offset": region.offset,
            "size": region.size,
            "non_ff": sum(value != 0xff for value in data),
            "aliases": list(region.aliases),
        })
    if args.json:
        print(json.dumps(regions, indent=2))
        return
    rows = [
        (
            region["name"],
            f"0x{region['offset']:06x}",
            str(region["size"]),
            str(region["non_ff"]),
            ", ".join(region["aliases"]) or "-",
        )
        for region in regions
    ]
    _print_table(("Name", "Offset", "Size", "Non-FF", "Aliases"), rows,
                 right=(2, 3))


def _write_bytes(data: bytes, output: str) -> None:
    if output == "-":
        sys.stdout.buffer.write(data)
        sys.stdout.buffer.flush()
        return
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    print(f"wrote {len(data)} bytes to {path}", file=sys.stderr)


def cmd_region_get(image, args):
    _write_bytes(image.read_region(args.region), args.output)


def _key_state(key: bytes) -> str:
    if key == bytes(len(key)):
        return "all-zero"
    if key == b"\xff" * len(key):
        return "erased"
    return "set"


def cmd_key_list(image, args):
    keys = []
    for definition in NAMED_KEYS:
        value = image.key(definition.name)
        keys.append({
            "name": definition.name,
            "offset": definition.offset,
            "size": definition.size,
            "state": _key_state(value),
        })
    if args.json:
        print(json.dumps(keys, indent=2))
        return
    rows = [
        (
            key["name"],
            f"0x{key['offset']:06x}",
            str(key["size"]),
            key["state"],
        )
        for key in keys
    ]
    _print_table(("Name", "Offset", "Size", "State"), rows, right=(2,))


def cmd_key_get(image, args):
    definition = image.named_key(args.name)
    value = image.key(definition.name)
    state = _key_state(value)
    if state != "set":
        raise NorFormatError(
            f"{definition.name} key is {state}; refusing extraction"
        )
    text = value.hex().upper() + "\n"
    if args.output:
        path = Path(args.output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="ascii")
        print(f"wrote {definition.name} key hex to {path}", file=sys.stderr)
    else:
        print(text, end="")


def _parse_key(text: str, size: int, source: str) -> bytes:
    clean = "".join(text.split())
    try:
        key = bytes.fromhex(clean)
    except ValueError as exc:
        raise ValueError(f"{source}: key must be hex: {exc}") from exc
    if len(key) != size:
        raise ValueError(
            f"{source}: key must be {size} bytes, "
            f"got {len(key)}"
        )
    return key


def _load_key(
        value: str | None, key_file: str | None, size: int) -> bytes:
    if bool(value) == bool(key_file):
        raise ValueError("pass exactly one of KEY or --key-file")
    if value:
        return _parse_key(value, size, "KEY")
    data = Path(key_file).read_bytes()
    if len(data) == size:
        return data
    try:
        text = data.decode("ascii")
    except UnicodeDecodeError as exc:
        raise ValueError(
            f"--key-file {key_file}: expected {size} raw bytes or hex text"
        ) from exc
    return _parse_key(text, size, f"--key-file {key_file}")


def cmd_key_set(image, args):
    definition = image.named_key(args.name)
    value = _load_key(args.key, args.key_file, definition.size)
    start = definition.offset
    target = Path(args.output) if args.output else image.source

    if args.output and target.resolve() != image.source.resolve():
        data = image.with_key(value, definition.name)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    else:
        with target.open("r+b") as handle:
            handle.seek(start)
            handle.write(value)

    with target.open("rb") as handle:
        handle.seek(start)
        written = handle.read(definition.size)
    if written != value:
        raise OSError(f"{definition.name} key verification failed for {target}")
    print(
        f"updated {definition.name} key in {target}",
        file=sys.stderr,
    )


def cmd_extract_volume(image, args):
    volume = image.volume(args.volume)
    _write_bytes(volume.logical_image(), args.output)


def cmd_upgrade_info(image, args):
    upgrade = image.staged_upgrade()
    info = {
        "allocated_size": upgrade.allocated_size,
        "container_size": upgrade.container_size,
        "format": upgrade.container[4:8].decode("ascii", errors="replace"),
        "sha256": upgrade.sha256,
        "trailing_nonzero_bytes": upgrade.trailing_nonzero_bytes,
    }
    if args.json:
        print(json.dumps(info, indent=2))
        return
    print(f"Allocated file: {info['allocated_size']} bytes")
    print(f"OTA container:  {info['container_size']} bytes")
    print(f"Format:         {info['format']}")
    print(f"SHA256:         {info['sha256']}")
    print(f"Trailing data:  {info['trailing_nonzero_bytes']} nonzero bytes")


def cmd_upgrade_get(image, args):
    _write_bytes(image.staged_upgrade().container, args.output)


def _fat_path(path):
    value = PurePosixPath("/" + path.lstrip("/"))
    if ".." in value.parts:
        raise ValueError("parent path components are not allowed")
    result = "/" + "/".join(
        part for part in value.parts if part not in ("/", ".")
    )
    return result.rstrip("/") or "/"


class _FatBuffer(io.BytesIO):
    """Keep the image readable after PyFat marks it clean during close."""

    def close(self):
        pass

    def release(self):
        super().close()


def _open_fat(volume):
    fp = _FatBuffer(bytearray(volume.logical_image()))
    try:
        with warnings.catch_warnings():
            warnings.filterwarnings(
                "ignore",
                message=(
                    "One or more FATs differ, filesystem most likely corrupted"
                ),
            )
            fs = PyFatBytesIOFS(fp=fp)
    except Exception:
        fp.release()
        raise
    return fp, fs


def _close_fat(fp, fs):
    try:
        fs.close()
        return fp.getvalue()
    finally:
        fp.release()


def _fat_walk(fs, path, recursive):
    base = _fat_path(path)
    for entry in fs.scandir(base):
        child = base.rstrip("/") + "/" + entry.name
        yield child, entry
        if recursive and entry.is_dir:
            yield from _fat_walk(fs, child, True)


def cmd_fat_ls(image, args):
    fp, fs = _open_fat(image.volume(args.volume))
    try:
        entries = [
            {
                "type": "dir" if entry.is_dir else "file",
                "size": entry.size or 0,
                "path": path,
            }
            for path, entry in _fat_walk(fs, args.path, args.recursive)
        ]
    finally:
        _close_fat(fp, fs)
    if args.json:
        print(json.dumps(entries, indent=2))
        return
    rows = [
        (
            entry["type"],
            "-" if entry["type"] == "dir" else str(entry["size"]),
            entry["path"],
        )
        for entry in entries
    ]
    _print_table(("Type", "Size", "Path"), rows, right=(1,))


def cmd_fat_get(image, args):
    fp, fs = _open_fat(image.volume(args.volume))
    try:
        with fs.openbin(_fat_path(args.path), "r") as handle:
            data = handle.read()
    finally:
        _close_fat(fp, fs)
    _write_bytes(data, args.output)


def _write_volume_update(image, volume, data, changed, output):
    target = Path(output) if output else image.source
    if output and target.resolve() != image.source.resolve():
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        return target

    with target.open("r+b") as handle:
        for start in changed:
            handle.seek(start)
            handle.write(data[start:start + volume.record_size])
    return target


def _commit_fat_update(image, volume, logical, output):
    data, changed = volume.with_logical_image(logical)
    target = _write_volume_update(image, volume, data, changed, output)
    return target, len(changed)


def _verify_fat_files(target, volume_index, expected):
    volume = As11NorImage.from_file(target).volume(volume_index)
    fp, fs = _open_fat(volume)
    try:
        for path, contents in expected:
            with fs.openbin(_fat_path(path), "r") as handle:
                if handle.read() != contents:
                    raise OSError(f"FAT write verification failed for {path}")
    finally:
        _close_fat(fp, fs)



def cmd_fat_put(image, args):
    data = (
        sys.stdin.buffer.read()
        if args.input == "-"
        else Path(args.input).read_bytes()
    )
    volume = image.volume(args.volume)
    path = _fat_path(args.path)
    fp, fs = _open_fat(volume)
    try:
        with fs.openbin(path, "w") as handle:
            handle.write(data)
    except Exception:
        _close_fat(fp, fs)
        raise
    logical = _close_fat(fp, fs)

    target, changed = _commit_fat_update(
        image, volume, logical, args.output
    )
    _verify_fat_files(target, volume.index, ((path, data),))
    print(
        f"updated {path} ({len(data)} bytes, "
        f"{changed} logical sectors) in {target}",
        file=sys.stderr,
    )


def _safe_host_name(name: str) -> str:
    if (
            not name
            or name in (".", "..")
            or "/" in name
            or "\\" in name
            or "\x00" in name):
        raise NorFormatError(f"unsafe FAT filename: {name!r}")
    return name


def cmd_fat_getdir(image, args):
    source = _fat_path(args.path)
    fp, fs = _open_fat(image.volume(args.volume))

    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    count = 0
    try:
        for fat_path, entry in _fat_walk(fs, source, True):
            relative = PurePosixPath(fat_path).relative_to(
                PurePosixPath(source)
            )
            host = output.joinpath(
                *(_safe_host_name(part) for part in relative.parts)
            )
            if entry.is_dir:
                host.mkdir(parents=True, exist_ok=True)
            else:
                host.parent.mkdir(parents=True, exist_ok=True)
                with fs.openbin(fat_path, "r") as handle:
                    host.write_bytes(handle.read())
                count += 1
    finally:
        _close_fat(fp, fs)
    print(f"extracted {count} files to {output}", file=sys.stderr)


def cmd_fat_putdir(image, args):
    source = Path(args.input)
    if not source.is_dir():
        raise NotADirectoryError(source)

    volume = image.volume(args.volume)
    destination = _fat_path(args.path)
    directories = sorted(
        (path for path in source.rglob("*") if path.is_dir()),
        key=lambda path: path.relative_to(source).as_posix(),
    )
    files = sorted(
        (path for path in source.rglob("*") if path.is_file()),
        key=lambda path: path.relative_to(source).as_posix(),
    )

    expected = []
    fp, fs = _open_fat(volume)
    try:
        if destination != "/":
            fs.makedirs(destination, recreate=True)
        for path in directories:
            relative = path.relative_to(source).as_posix()
            fs.makedirs(
                destination.rstrip("/") + "/" + relative,
                recreate=True,
            )
        for path in files:
            relative = path.relative_to(source).as_posix()
            fat_path = destination.rstrip("/") + "/" + relative
            contents = path.read_bytes()
            with fs.openbin(fat_path, "w") as handle:
                handle.write(contents)
            expected.append((fat_path, contents))
    except Exception:
        _close_fat(fp, fs)
        raise
    logical = _close_fat(fp, fs)

    target, changed = _commit_fat_update(
        image, volume, logical, args.output
    )
    _verify_fat_files(target, volume.index, expected)
    print(
        f"updated {len(expected)} files under {destination} "
        f"({changed} logical sectors) in {target}",
        file=sys.stderr,
    )


def build_parser():
    parser = argparse.ArgumentParser(
        description="Inspect and edit a complete Air11 external NOR dump"
    )
    parser.add_argument("image", help="16 MiB raw NOR dump")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("info", help="Show NOR, FTL, and FAT geometry")
    p.add_argument("--json", action="store_true", help="Emit JSON")
    p.set_defaults(func=cmd_info)

    p = sub.add_parser("region-list", help="List raw regions before the FTL")
    p.add_argument("--json", action="store_true", help="Emit JSON")
    p.set_defaults(func=cmd_region_list)

    p = sub.add_parser("region-get", help="Extract one raw region")
    p.add_argument("region", help="Region name or alias (for example md0)")
    p.add_argument("output", help="Output file, or - for stdout")
    p.set_defaults(func=cmd_region_get)

    p = sub.add_parser("key-list", help="List known keys")
    p.add_argument("--json", action="store_true", help="Emit JSON")
    p.set_defaults(func=cmd_key_list)

    p = sub.add_parser("key-get", help="Print or save one known key")
    p.add_argument("name", metavar="NAME", help="Key name, for example OTA")
    p.add_argument("-o", "--output", help="Write hex text to this file")
    p.set_defaults(func=cmd_key_get)

    p = sub.add_parser(
        "key-set", help="Set one known key"
    )
    p.add_argument("name", metavar="NAME", help="Key name, for example OTA")
    p.add_argument("key", nargs="?", metavar="KEY",
                   help="Key as 64 hex characters")
    p.add_argument("--key-file", help="Key as 32 raw bytes or hex text")
    p.add_argument("-o", "--output",
                   help="Write a modified copy instead of updating IMAGE")
    p.set_defaults(func=cmd_key_set)

    p = sub.add_parser(
        "extract-volume", help="Reconstruct one logical FAT block device"
    )
    p.add_argument("volume", help="settings, datalog, upgrade, or nor:N")
    p.add_argument("output", help="Output FAT image, or - for stdout")
    p.set_defaults(func=cmd_extract_volume)

    p = sub.add_parser(
        "upgrade-info", help="Inspect the staged OTA container"
    )
    p.add_argument("--json", action="store_true", help="Emit JSON")
    p.set_defaults(func=cmd_upgrade_info)

    p = sub.add_parser(
        "upgrade-get", help="Extract the staged OTA container"
    )
    p.add_argument("output", help="Output .abc file, or - for stdout")
    p.set_defaults(func=cmd_upgrade_get)

    if HAVE_PYFATFS:
        p = sub.add_parser("fat-ls", help="List a FAT directory")
        p.add_argument("volume", help="settings, datalog, upgrade, or nor:N")
        p.add_argument("path", nargs="?", default="/", help="FAT path")
        p.add_argument("-r", "--recursive", action="store_true")
        p.add_argument("--json", action="store_true", help="Emit JSON")
        p.set_defaults(func=cmd_fat_ls)

        p = sub.add_parser("fat-get", help="Extract one FAT file")
        p.add_argument("volume", help="settings, datalog, upgrade, or nor:N")
        p.add_argument("path", help="FAT file path")
        p.add_argument("output", help="Output file, or - for stdout")
        p.set_defaults(func=cmd_fat_get)

        p = sub.add_parser("fat-put", help="Write one FAT file")
        p.add_argument("volume", help="settings, datalog, upgrade, or nor:N")
        p.add_argument("input", help="Input file, or - for stdin")
        p.add_argument("path", help="FAT file path")
        p.add_argument("-o", "--output",
                       help="Write a modified copy instead of updating IMAGE")
        p.set_defaults(func=cmd_fat_put)

        p = sub.add_parser(
            "fat-getdir", help="Extract a FAT directory tree"
        )
        p.add_argument("volume", help="settings, datalog, upgrade, or nor:N")
        p.add_argument("path", help="FAT directory path")
        p.add_argument("output", help="Output directory")
        p.set_defaults(func=cmd_fat_getdir)

        p = sub.add_parser(
            "fat-putdir", help="Write a FAT directory tree"
        )
        p.add_argument("volume", help="settings, datalog, upgrade, or nor:N")
        p.add_argument("input", help="Input directory")
        p.add_argument("path", help="FAT directory path")
        p.add_argument("-o", "--output",
                       help="Write a modified copy instead of updating IMAGE")
        p.set_defaults(func=cmd_fat_putdir)
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        image = As11NorImage.from_file(args.image)
        args.func(image, args)
        return 0
    except TOOL_ERRORS as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

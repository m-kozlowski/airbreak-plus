#!/usr/bin/env python3

"""Inspect and assemble block-based Air 10 firmware images."""

import argparse
import binascii
import re
import sys
from dataclasses import dataclass
from pathlib import Path


FULL_IMAGE_SIZE = 0x100000
BID_OFFSET = 0x3F80
ID_SIZE = 16

LAYOUTS = {
    "SX577-0200": {
        "family": "SX567",
        "BLX": (0x00000, 0x04000),
        "CCX": (0x04000, 0x3C000),
        "CDX": (0x40000, 0xC0000),
    },
    "SX585-0200": {
        "family": "SX584",
        "BLX": (0x00000, 0x04000),
        "CCX": (0x04000, 0x1C000),
        "CDX": (0x20000, 0xE0000),
    },
}

BLOCK_NAMES = ("BLX", "CCX", "CDX")


class ImageError(Exception):
    pass


@dataclass
class BlockSource:
    data: bytes
    path: Path
    source_sid: str | None
    standalone: bool


def read_file(path):
    try:
        return Path(path).read_bytes()
    except OSError as exc:
        raise ImageError(f"cannot read {path}: {exc}") from exc


def read_ascii_id(data, offset):
    raw = data[offset:offset + ID_SIZE]
    if len(raw) != ID_SIZE:
        return None
    text = raw.split(b"\0", 1)[0]
    try:
        return text.decode("ascii")
    except UnicodeDecodeError:
        return None


def image_bid(data):
    return read_ascii_id(data, BID_OFFSET)


def layout_for_image(data):
    if len(data) != FULL_IMAGE_SIZE:
        raise ImageError(
            f"expected a {FULL_IMAGE_SIZE}-byte full image, got {len(data)} bytes")
    bid = image_bid(data)
    if bid not in LAYOUTS:
        raise ImageError(f"unsupported bootloader ID {bid!r}")
    return bid, LAYOUTS[bid]


def block_crc(block):
    if len(block) < 2:
        return None, None, False
    stored = int.from_bytes(block[-2:], "big")
    computed = binascii.crc_hqx(block[:-2], 0xFFFF)
    return stored, computed, stored == computed


def require_valid_crc(name, block, path):
    stored, computed, valid = block_crc(block)
    if not valid:
        raise ImageError(
            f"{path}: {name} CRC mismatch: stored=0x{stored:04X}, "
            f"computed=0x{computed:04X}")


def cdx_sid(block):
    sid = read_ascii_id(block, 0)
    if sid and re.fullmatch(r"SX\d{3}-\d{4}(?:[!+][A-Za-z0-9]{3,5})?", sid):
        return sid
    return None


def stock_sid(sid):
    return sid[:10] if sid else None


def extract_from_full(data, layout, name):
    offset, size = layout[name]
    return data[offset:offset + size]


def load_block_source(path, name, target_bid, target_layout):
    path = Path(path)
    data = read_file(path)
    source_sid = None
    standalone = len(data) != FULL_IMAGE_SIZE

    if not standalone:
        source_bid, source_layout = layout_for_image(data)
        if source_bid != target_bid:
            raise ImageError(
                f"{path}: {source_bid} image cannot supply {name} for {target_bid}")
        source_sid = cdx_sid(extract_from_full(data, source_layout, "CDX"))
        data = extract_from_full(data, source_layout, name)
    else:
        expected_size = target_layout[name][1]
        if len(data) != expected_size:
            raise ImageError(
                f"{path}: {name} must be {expected_size} bytes, got {len(data)}")

    require_valid_crc(name, data, path)

    if name == "BLX":
        bid = image_bid(data)
        if bid != target_bid:
            raise ImageError(f"{path}: BLX ID is {bid!r}, expected {target_bid}")
    elif name == "CDX":
        sid = cdx_sid(data)
        if not sid:
            raise ImageError(f"{path}: CDX software ID not found")
        if not stock_sid(sid).startswith(target_layout["family"] + "-"):
            raise ImageError(
                f"{path}: CDX {sid} does not match {target_bid} platform")
        source_sid = sid

    return BlockSource(data, path, source_sid, standalone)


def validate_source_versions(sources):
    selected_sid = sources["CDX"].source_sid
    cdx_version = stock_sid(selected_sid)
    source = sources["CCX"]
    source_version = stock_sid(source.source_sid)
    if source_version and source_version != cdx_version:
        raise ImageError(
            f"{source.path}: CCX came from {source_version}, "
            f"but the selected CDX is {cdx_version}")
    return selected_sid


def write_output(path, data):
    path = Path(path)
    try:
        path.write_bytes(data)
    except OSError as exc:
        raise ImageError(f"cannot write {path}: {exc}") from exc


def cmd_info(args):
    path = Path(args.image)
    data = read_file(path)

    if len(data) == FULL_IMAGE_SIZE:
        bid, layout = layout_for_image(data)
        sid = cdx_sid(extract_from_full(data, layout, "CDX"))
        print(f"Image: {path}")
        print(f"Size:  {len(data)} bytes")
        print(f"BID:   {bid}")
        print(f"SID:   {sid or 'unknown'}")
        valid_image = sid is not None
        for name in BLOCK_NAMES:
            offset, size = layout[name]
            block = extract_from_full(data, layout, name)
            stored, computed, valid = block_crc(block)
            state = "ok" if valid else f"bad, computed 0x{computed:04X}"
            print(f"{name}:   offset=0x{offset:05X} size={size:7d} "
                  f"crc=0x{stored:04X} ({state})")
            valid_image = valid_image and valid
        return 0 if valid_image else 1

    matches = []
    for bid, layout in LAYOUTS.items():
        for name in BLOCK_NAMES:
            if len(data) == layout[name][1]:
                if name != "BLX" or image_bid(data) == bid:
                    matches.append((bid, name))
    if not matches:
        raise ImageError(f"{path}: unrecognized image or block size {len(data)}")

    print(f"Image: {path}")
    print(f"Size:  {len(data)} bytes")
    stored, computed, valid = block_crc(data)
    for bid, name in matches:
        extra = ""
        if name == "BLX":
            extra = f" BID={image_bid(data)}"
        elif name == "CDX":
            extra = f" SID={cdx_sid(data) or 'unknown'}"
        print(f"Type:  {bid} {name}{extra}")
    state = "ok" if valid else f"bad, computed 0x{computed:04X}"
    print(f"CRC:   0x{stored:04X} ({state})")
    return 0 if valid else 1


def cmd_extract(args):
    data = read_file(args.image)
    bid, layout = layout_for_image(data)
    outputs = {"BLX": args.blx, "CCX": args.ccx, "CDX": args.cdx}
    if not any(outputs.values()):
        raise ImageError("extract requires at least one of --blx, --ccx, or --cdx")
    for name in BLOCK_NAMES:
        path = outputs[name]
        if not path:
            continue
        block = extract_from_full(data, layout, name)
        require_valid_crc(name, block, args.image)
        write_output(path, block)
        print(f"Wrote {name} from {bid}: {path} ({len(block)} bytes)")
    return 0


def compose_image(bid, layout, paths):
    sources = {
        name: load_block_source(paths[name], name, bid, layout)
        for name in BLOCK_NAMES
    }
    sid = validate_source_versions(sources)
    image = bytearray(b"\xFF" * FULL_IMAGE_SIZE)
    for name in BLOCK_NAMES:
        offset, size = layout[name]
        image[offset:offset + size] = sources[name].data
    return bytes(image), sources, sid


def report_output(output, bid, sid, sources):
    print(f"Wrote {output} ({FULL_IMAGE_SIZE} bytes)")
    print(f"  BID: {bid}")
    print(f"  SID: {sid}")
    for name in BLOCK_NAMES:
        print(f"  {name}: {sources[name].path}")
    if sources["CCX"].standalone:
        print("  Note: standalone CCX has no source SID; version compatibility "
              "could not be checked")


def cmd_compose(args):
    blx_data = read_file(args.blx)
    if len(blx_data) == FULL_IMAGE_SIZE:
        bid, layout = layout_for_image(blx_data)
    else:
        bid = image_bid(blx_data)
        layout = LAYOUTS.get(bid)
        if not layout:
            raise ImageError(f"{args.blx}: unsupported BLX ID {bid!r}")
    paths = {"BLX": args.blx, "CCX": args.ccx, "CDX": args.cdx}
    image, sources, sid = compose_image(bid, layout, paths)
    write_output(args.output, image)
    report_output(args.output, bid, sid, sources)
    return 0


def cmd_replace(args):
    base_data = read_file(args.image)
    bid, layout = layout_for_image(base_data)
    paths = {name: args.image for name in BLOCK_NAMES}
    replacements = {"BLX": args.blx, "CCX": args.ccx, "CDX": args.cdx}
    if not any(replacements.values()):
        raise ImageError("replace requires at least one of --blx, --ccx, or --cdx")
    for name, path in replacements.items():
        if path:
            paths[name] = path
    image, sources, sid = compose_image(bid, layout, paths)
    write_output(args.output, image)
    report_output(args.output, bid, sid, sources)
    return 0


def build_parser():
    parser = argparse.ArgumentParser(
        description="Inspect, extract, replace, and compose Air 10 firmware blocks")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("info", help="show image layout, IDs, and block CRCs")
    p.add_argument("image")
    p.set_defaults(func=cmd_info)

    p = sub.add_parser("extract", help="extract one or more blocks from a full image")
    p.add_argument("image")
    p.add_argument("--blx", metavar="PATH", help="write BLX to PATH")
    p.add_argument("--ccx", metavar="PATH", help="write CCX to PATH")
    p.add_argument("--cdx", metavar="PATH", help="write CDX to PATH")
    p.set_defaults(func=cmd_extract)

    p = sub.add_parser("compose", help="compose a full image from three block sources")
    p.add_argument("output")
    p.add_argument("--blx", required=True,
                   help="BLX block or full image supplying BLX")
    p.add_argument("--ccx", required=True,
                   help="CCX block or full image supplying CCX")
    p.add_argument("--cdx", required=True,
                   help="CDX block or full image supplying CDX")
    p.set_defaults(func=cmd_compose)

    p = sub.add_parser("replace", help="replace selected blocks in a full image")
    p.add_argument("image", help="base full image")
    p.add_argument("output")
    p.add_argument("--blx", help="BLX block or full image supplying BLX")
    p.add_argument("--ccx", help="CCX block or full image supplying CCX")
    p.add_argument("--cdx", help="CDX block or full image supplying CDX")
    p.set_defaults(func=cmd_replace)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except ImageError as exc:
        print(f"[!] {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""AS11 Flash / OTA Tool.

Build, upload and apply firmware images on AirSense 11 / AirCurve 11
devices. Works over BLE and CAN; transport selected with -d/--device:

    -d ble:<mac|alias>     BLE
    -d can:<target>        CAN adapter target (Waveshare, CANable SLCAN, SocketCAN)
    --addr <x>             same as -d ble:<x>
    -p/--port <x>          same as -d can:<target>

Offline subcommands (no device needed):
    targets    list known block regions
    build      assemble a .abc container from firmware bytes
    info       inspect a .abc container

Device-touching subcommands:
    upload     push a pre-built .abc; verify-only unless --apply / --apply-plain
    flash      build .abc from firmware, optionally apply

Apply-mode decision:
    --apply-plain          ApplyUpgrade (unauthenticated)
    --apply-authenticated  ApplyAuthenticatedUpgrade (+HMAC)
    --apply                alias for --apply-authenticated
    (no flag)              verify-only; stop after CheckUpgradeFile

Authenticated apply key resolution: --key HEX32, --key-file PATH, $AS11_OTA_KEY,
or stored BLE device otaKey.

"""

from __future__ import annotations

import argparse
import binascii
import hashlib
import hmac
import json
import logging
import os
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path


_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_HERE / "lib"))

try:  # optional: only used to register CAN-specific CLI args
    import as11_can_transport as _can_transport  # noqa: E402
except ModuleNotFoundError as exc:  # pragma: no cover - dev setups may omit CAN support
    if exc.name == "as11_can_transport":
        _can_transport = None
    else:
        raise

from as11_rpc import (  # noqa: E402
    Transport, TransportError, FramingError,
)


log = logging.getLogger("as11.flash")


_FORCE_HELP = ("override local validation warnings (input image HW CRC "
               "mismatch, descriptor CRC mismatch, unexpected payload size)")


MAGIC          = b"OTA!"
FORMAT_0005    = b"0005"
FORMAT_0006    = b"0006"
PRIMARY_SIZE   = 0x58
DESCRIPTOR_SIZE = 0x50
PAYLOAD_OFFSET_0005 = PRIMARY_SIZE + DESCRIPTOR_SIZE   # 0xa8
PAYLOAD_OFFSET_0006 = PRIMARY_SIZE                     # 0x58
SEGMENT_ENTRY_SIZE = 8

OFF_MAGIC      = 0x00
OFF_FORMAT     = 0x04
OFF_COMPONENT  = 0x48
COMPONENT_LEN  = 0x10

DEFAULT_COMPONENT_0005 = "PacificFG"
COMPONENTS_0006 = ("PacificFG", "AlarmModule")

XFER_RAW_BYTES    = 500
LONG_RPC_TIMEOUT  = 120.0
BLOCK_RPC_TIMEOUT = 15.0

FLASH_BASE       = 0x08000000
FULL_FLASH_SIZE  = 0x00200000



@dataclass(frozen=True)
class TargetRegion:
    code: str
    flash_start: int
    size: int
    desc2_required: bool = False
    desc3_required: bool = False
    danger_flag: str | None = None
    notes: str = ""
    # True for primitive HW regions that each carry their own CRC16-CCITT
    atomic: bool = False

    def __post_init__(self) -> None:
        if len(self.code.encode("ascii")) != 4:
            raise ValueError(
                f"TargetRegion code must be exactly 4 ASCII bytes, "
                f"got {self.code!r}")

    @property
    def full_image_offset(self) -> int:
        return self.flash_start - FLASH_BASE

    @property
    def flash_end(self) -> int:
        return self.flash_start + self.size


@dataclass(frozen=True)
class SegmentEntry:
    length: int
    flash_start: int

    @property
    def flash_end(self) -> int:
        return self.flash_start + self.length


TARGETS: dict[str, TargetRegion] = {
    "APPL": TargetRegion(
        "APPL", flash_start=0x08040000, size=0x001C0000,
        desc2_required=True, desc3_required=True,
        atomic=True,
        notes="main app image"),
    "CONF": TargetRegion(
        "CONF", flash_start=0x08020000, size=0x00020000,
        desc2_required=True,
        atomic=True,
        notes="config/aux block before app"),
    "APCX": TargetRegion(
        "APCX", flash_start=0x08020000, size=0x001E0000,
        desc3_required=True,
        notes="combined CONF+APPL range"),
    "FGBL": TargetRegion(
        "FGBL", flash_start=0x08000000, size=0x00020000,
        desc3_required=True,
        atomic=True,
        danger_flag="include_bootloader",
        notes="bootloader / low updater region"),
    "FGCB": TargetRegion(
        "FGCB", flash_start=0x08000000, size=0x00200000,
        danger_flag="include_full_flash",
        notes="complete internal flash image"),
}


BLOCK_ALIASES: dict[str, str] = {
    # canonical codes always accepted, any case
    **{code.lower(): code for code in TARGETS},
    # friendly names
    "config":          "CONF",
    "firmware":        "APPL",
    "app":             "APPL",
    "conf+app":        "APCX",
    "config+firmware": "APCX",
    "bootloader":      "FGBL",
    "full":            "FGCB",
    "all":             "FGCB",
}

# Per-firmware descriptor presets for 0005 containers. 
# Only CONF/APPL/APCX/FGBL targets need them. FGCB (and all of format 0006)
# ignores these fields.
DESC_PRESETS = {
    "14.8.3.0": {
        "desc2": 0x2D89E58F,
        "desc3": 0xBEB37EE2,
    },
    "15.8.4.0": {
        "desc2": 0xD785ABA6,
        "desc3": 0xBEB37EE2,
    },
}

BLE_CRED_FILE = Path.home() / ".as11_ble.json"



def u32_le(value: int) -> bytes:
    if not 0 <= value <= 0xFFFFFFFF:
        raise ValueError(f"u32 out of range: {value!r}")
    return value.to_bytes(4, "little")


def get_u32(buf: bytes, off: int) -> int:
    return int.from_bytes(buf[off:off + 4], "little")


def put_u32(buf: bytearray, off: int, value: int) -> None:
    buf[off:off + 4] = u32_le(value)


def crc32_final(data: bytes) -> int:
    return binascii.crc32(data) & 0xFFFFFFFF


def crc16_ccitt(data: bytes) -> int:
    crc = 0xFFFF
    for b in data:
        crc ^= b << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021 if crc & 0x8000 else crc << 1) & 0xFFFF
    return crc


def regions_in_payload(target: TargetRegion) -> list[tuple[str, int, int]]:
    t_start = target.full_image_offset
    t_end   = t_start + target.size
    atomics = sorted((t for t in TARGETS.values() if t.atomic),
                     key=lambda t: t.full_image_offset)
    return [(hw.code, hw.full_image_offset - t_start, hw.size)
            for hw in atomics
            if hw.full_image_offset >= t_start
            and hw.full_image_offset + hw.size <= t_end]


def verify_payload_crcs(payload: bytes, target: TargetRegion
                        ) -> list[tuple[str, int, int, bool]]:
    out = []
    for (name, off, size) in regions_in_payload(target):
        if off + size > len(payload):
            continue
        stored   = int.from_bytes(payload[off + size - 2:off + size], "big")
        computed = crc16_ccitt(payload[off:off + size - 2])
        out.append((name, stored, computed, stored == computed))
    return out


def fix_payload_crcs(payload: bytes, target: TargetRegion
                     ) -> tuple[bytes, list[tuple[str, int]]]:
    """Return (patched_payload, [(region, new_crc), ...])."""
    buf = bytearray(payload)
    fixed = []
    for (name, off, size) in regions_in_payload(target):
        if off + size > len(buf):
            continue
        crc = crc16_ccitt(bytes(buf[off:off + size - 2]))
        buf[off + size - 2] = (crc >> 8) & 0xFF
        buf[off + size - 1] = crc & 0xFF
        fixed.append((name, crc))
    return bytes(buf), fixed


def build_segment_table(segments: list[SegmentEntry]) -> bytes:
    if not 1 <= len(segments) <= 0xFF:
        raise ValueError(f"0005 segment count must be 1..255, got {len(segments)}")
    out = bytearray()
    for seg in segments:
        out += u32_le(seg.length)
        out += u32_le(seg.flash_start)
    return bytes(out)


def build_0005_rest(target: TargetRegion, payload: bytes
                    ) -> tuple[bytes, list[SegmentEntry]]:
    segments = [SegmentEntry(length=len(payload), flash_start=target.flash_start)]
    return build_segment_table(segments) + payload, segments


def parse_0005_segments(descriptor: bytes, rest: bytes,
                        *, absolute_payload_offset: int = PAYLOAD_OFFSET_0005
                        ) -> dict:
    """Decode the SRAM-updater segment table stored at descriptor+0x48.

        segment_count * {u32 length, u32 destination} + concatenated data.
    """
    count = get_u32(descriptor, 0x48)
    table_size = count * SEGMENT_ENTRY_SIZE
    table_ok = 1 <= count <= 0xFF and table_size <= len(rest)
    segments = []
    data_cursor = 0

    if table_ok:
        for idx in range(count):
            off = idx * SEGMENT_ENTRY_SIZE
            length = get_u32(rest, off)
            flash_start = get_u32(rest, off + 4)
            segments.append({
                "index": idx,
                "length": length,
                "flash_start": flash_start,
                "flash_end": flash_start + length,
                "data_offset": absolute_payload_offset + table_size + data_cursor,
                "rest_data_offset": table_size + data_cursor,
            })
            data_cursor += length

    segment_data_size = len(rest) - table_size if table_ok else None
    segment_data_len_ok = (segment_data_size is not None
                           and data_cursor == segment_data_size)
    return {
        "segment_count": count,
        "segment_table_size": table_size,
        "segment_table_ok": table_ok,
        "segment_data_size": segment_data_size,
        "segment_data_expected_size": data_cursor if table_ok else None,
        "segment_data_len_ok": segment_data_len_ok,
        "segments": segments,
    }


def target_payload_slice(info: dict) -> tuple[int, int] | None:
    off = info.get("target_payload_offset")
    size = info.get("target_payload_size")
    if off is None or size is None:
        return None
    return int(off), int(size)


def parse_u32(text: str | None, *, name: str) -> int | None:
    if text is None:
        return None
    s = text.strip().replace("_", "")
    if not s:
        return None
    try:
        if s.lower().startswith("0x"):
            value = int(s, 16)
        elif any(c in "abcdefABCDEF" for c in s):
            value = int(s, 16)
        else:
            value = int(s, 10)
    except ValueError as e:
        raise argparse.ArgumentTypeError(
            f"{name} is not an integer: {text!r}") from e
    if not 0 <= value <= 0xFFFFFFFF:
        raise argparse.ArgumentTypeError(
            f"{name} does not fit in u32: {text!r}")
    return value


_VERSION_RE = re.compile(r"(?<!\d)(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})(?!\d)")


def normalize_version(raw: str | None) -> str | None:
    """Extract the first 4-dotted-digit semver-like prefix"""
    if not raw:
        return None
    m = _VERSION_RE.search(str(raw))
    return m.group(1) if m else None


def fetch_pci(t: Transport) -> int | None:
    """Query the device's PCI value. Returns None on any failure.

    Also queries `_PRI` for log context. If PRI==0 the device doesn't
    actually check PCI, so the fallback to 0 is harmless on that device.
    """
    try:
        resp = t.rpc("Get", ["_PCI", "_PRI"], timeout=10.0)
    except Exception as e:
        log.warning("Get(_PCI,_PRI) failed: %s", e)
        return None
    result = resp.get("result")
    if not isinstance(result, dict):
        log.warning("Get(_PCI,_PRI) returned unexpected shape: %r", result)
        return None

    pri = result.get("_PRI")
    pci = result.get("_PCI")
    log.info("device reports _PRI=%r  _PCI=%r", pri, pci)

    if pci is None:
        return None
    try:
        return int(pci) & 0xFFFFFFFF
    except (TypeError, ValueError):
        log.warning("Get(_PCI) returned %r; can't coerce to int", pci)
        return None


def fetch_firmware_version(t: Transport) -> str | None:
    """Query the device's ApplicationIdentifier; normalized version or None."""
    try:
        resp = t.rpc("Get", ["ApplicationIdentifier"], timeout=10.0)
    except Exception as e:
        log.warning("Get(ApplicationIdentifier) failed: %s", e)
        return None
    result = resp.get("result")
    if isinstance(result, dict):
        return normalize_version(result.get("ApplicationIdentifier"))
    if isinstance(result, str):
        return normalize_version(result)
    return None


def resolve_block(raw: str) -> TargetRegion:
    code = BLOCK_ALIASES.get(raw.lower())
    if code is None:
        canon = sorted(TARGETS)
        aliases = sorted(k for k in BLOCK_ALIASES if k not in {c.lower() for c in TARGETS})
        raise SystemExit(f"unknown block {raw!r}. "
                         f"Canonical codes: {', '.join(canon)}. "
                         f"Aliases: {', '.join(aliases)}.")
    return TARGETS[code]


def normalize_key_hex(text: str, *, source: str) -> bytes:
    clean = "".join(text.split())
    try:
        raw = bytes.fromhex(clean)
    except ValueError as exc:
        raise SystemExit(f"{source}: K_ota must be hex: {exc}") from exc
    if len(raw) != 32:
        raise SystemExit(f"K_ota must be exactly 32 bytes, got {len(raw)} "
                         f"(source: {source})")
    return raw


def load_ble_credentials_for_keys() -> dict:
    if not BLE_CRED_FILE.exists():
        return {}
    try:
        data = json.loads(BLE_CRED_FILE.read_text())
    except json.JSONDecodeError as exc:
        raise SystemExit(f"{BLE_CRED_FILE}: invalid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise SystemExit(f"{BLE_CRED_FILE}: expected object at top level")
    return data


def find_credential_target(creds: dict, target: str) -> tuple[str, dict] | None:
    target_upper = target.upper()
    for addr, data in creds.items():
        if addr.upper() == target_upper:
            return addr, data
        if isinstance(data, dict) and data.get("alias") == target:
            return addr, data
    return None


def stored_ota_key_for_device(args) -> tuple[str, str] | None:
    """Return (hex_key, source_label) for a BLE device credential otaKey."""
    try:
        spec = _resolve_device_spec(args)
    except SystemExit:
        return None
    if not spec.startswith("ble:"):
        return None
    target = spec[4:]
    if not target:
        return None

    found = find_credential_target(load_ble_credentials_for_keys(), target)
    if found is None:
        return None
    addr, data = found
    if not isinstance(data, dict):
        return None
    key_hex = data.get("otaKey")
    if not key_hex:
        return None
    alias = data.get("alias")
    label = f"stored otaKey for {alias or addr}"
    return key_hex, label


def parse_key(key_hex: str | None, key_file: str | None,
              stored_key: tuple[str, str] | None = None) -> bytes:
    """Resolve K_ota.

    Precedence: --key > --key-file > AS11_OTA_KEY > stored BLE otaKey.
    """
    if key_hex and key_file:
        raise SystemExit("pass only one of --key / --key-file")
    if key_hex:
        raw = normalize_key_hex(key_hex, source="--key")
        source = "--key"
    elif key_file:
        data = Path(key_file).read_bytes()
        if len(data) == 32:
            raw = data
        else:
            raw = normalize_key_hex(
                data.decode("ascii"), source=f"--key-file {key_file}"
            )
        source = f"--key-file {key_file}"
    elif os.environ.get("AS11_OTA_KEY"):
        raw = normalize_key_hex(os.environ["AS11_OTA_KEY"],
                                source="AS11_OTA_KEY")
        source = "AS11_OTA_KEY"
    elif stored_key:
        key_hex, source = stored_key
        raw = normalize_key_hex(key_hex, source=source)
        log.info("using %s", source)
    else:
        raise SystemExit(
            "authenticated apply needs an OTA key: pass --key, --key-file, "
            "set AS11_OTA_KEY, store one with `as11_config.py devices "
            "ota-key <alias>` for BLE aliases."
        )
    return raw



def load_payload(args, target: TargetRegion) -> bytes:
    """Resolve the firmware input per args.from_full / args.payload / args.file.

    - --from-full: treat the file as a 2 MiB full internal dump and slice
      the target region out.
    - --payload: treat the file as already the target region's bytes.
    - -f/--file (auto): inspect file size, choose full-dump vs pre-sliced.
    """
    sources = [name for name, v in (
        ("--from-full", getattr(args, "from_full", None)),
        ("--payload",   getattr(args, "payload", None)),
        ("-f/--file",   getattr(args, "file", None)),
    ) if v]
    if len(sources) == 0:
        raise SystemExit("source file required: pass -f/--file, --from-full, or --payload")
    if len(sources) > 1:
        raise SystemExit(f"conflicting source args: {', '.join(sources)}; pick one")

    allow_mismatch = getattr(args, "force", False)

    if getattr(args, "from_full", None):
        full = Path(args.from_full).read_bytes()
        start, end = target.full_image_offset, target.full_image_offset + target.size
        if len(full) < end:
            raise SystemExit(f"{args.from_full}: too short for {target.code}; "
                             f"need at least 0x{end:x} bytes, got 0x{len(full):x}")
        if len(full) != FULL_FLASH_SIZE:
            print(f"warning: {args.from_full} is {len(full)} bytes, "
                  f"expected {FULL_FLASH_SIZE} for a full internal flash image",
                  file=sys.stderr)
        return full[start:end]

    if getattr(args, "payload", None):
        data = Path(args.payload).read_bytes()
        if len(data) != target.size and not allow_mismatch:
            raise SystemExit(
                f"{args.payload}: {target.code} payload must be {target.size} "
                f"bytes (got {len(data)}). Pass --force to override.")
        return data

    # auto-detect from -f/--file
    path = args.file
    data = Path(path).read_bytes()
    if len(data) == target.size:
        return data
    if len(data) == FULL_FLASH_SIZE:
        start, end = target.full_image_offset, target.full_image_offset + target.size
        return data[start:end]
    if allow_mismatch:
        print(f"warning: {path} is {len(data)} bytes - neither {target.size} "
              f"nor {FULL_FLASH_SIZE}; --force in effect", file=sys.stderr)
        return data
    raise SystemExit(
        f"{path}: cannot auto-detect source for {target.code}; got {len(data)} bytes. "
        f"Expected a {target.size}-byte {target.code} payload or a "
        f"{FULL_FLASH_SIZE}-byte full internal dump. Use --from-full or "
        f"--payload to force non-standard interpretation.")


def _auto_preset_needed(args, target: TargetRegion) -> bool:
    """
    False when the target ignores desc2/desc3 (FGCB), when the format is 0006
    (no secondary descriptor at all), or when the user already supplied
    explicit overrides for every required slot.
    """
    if getattr(args, "format", "0005") != "0005":
        return False
    if not target.desc2_required and not target.desc3_required:
        return False
    have_desc2 = parse_u32(getattr(args, "desc2", None), name="desc2") is not None
    have_desc3 = parse_u32(getattr(args, "desc3", None), name="desc3") is not None
    if target.desc2_required and not have_desc2: return True
    if target.desc3_required and not have_desc3: return True
    return False


def resolve_descriptor_words(args, target: TargetRegion,
                             *, detected_preset: str | None = None
                             ) -> tuple[int, int, int]:
    """Combine --desc-preset with explicit --desc2/--desc3/--pci"""

    desc2     = parse_u32(args.desc2,     name="desc2")
    desc3     = parse_u32(args.desc3,     name="desc3")
    pci = parse_u32(getattr(args, "pci", None), name="pci")

    preset_key = args.desc_preset
    if preset_key == "auto":
        preset_key = detected_preset

    if preset_key and preset_key != "none" and preset_key in DESC_PRESETS:
        p = DESC_PRESETS[preset_key]
        if desc2 is None: desc2 = p["desc2"]
        if desc3 is None: desc3 = p["desc3"]

    if desc2 is None:     desc2 = 0
    if desc3 is None:     desc3 = 0
    if pci is None: pci = 0

    missing = []
    if target.desc2_required and desc2 == 0: missing.append("--desc2")
    if target.desc3_required and desc3 == 0: missing.append("--desc3")
    if missing:
        known = ", ".join(sorted(DESC_PRESETS))
        raise SystemExit(
            f"{target.code} needs descriptor word(s) {', '.join(missing)}. "
            f"Use --desc-preset (one of {known}) or pass explicit "
            f"--desc2/--desc3.")
    return desc2, desc3, pci



def build_primary_header(*, fmt: bytes, component: str) -> bytes:
    hdr = bytearray(PRIMARY_SIZE)
    hdr[OFF_MAGIC:OFF_MAGIC + 4]   = MAGIC
    hdr[OFF_FORMAT:OFF_FORMAT + 4] = fmt
    comp_bytes = component.encode("ascii")
    if len(comp_bytes) > COMPONENT_LEN:
        raise ValueError(f"component too long: {component!r}")
    hdr[OFF_COMPONENT:OFF_COMPONENT + len(comp_bytes)] = comp_bytes
    return bytes(hdr)


def build_descriptor(target: TargetRegion, rest: bytes,
                     *, primary_header: bytes,
                     desc2: int, desc3: int, pci: int,
                     segment_count: int) -> bytes:
    if len(primary_header) != PRIMARY_SIZE:
        raise ValueError(f"primary header must be {PRIMARY_SIZE} bytes")
    if not 1 <= segment_count <= 0xFF:
        raise SystemExit(
            f"0005 segment count out of range: {segment_count}")
    desc = bytearray(DESCRIPTOR_SIZE)
    put_u32(desc, 0x00, 1)
    desc[0x04:0x08] = target.code.encode("ascii")
    put_u32(desc, 0x08, desc2)
    put_u32(desc, 0x0C, desc3)
    put_u32(desc, 0x10, pci)    # PCI (var 0x232); enforced when PRI (var 0x111) == 1
    put_u32(desc, 0x40, len(rest))
    put_u32(desc, 0x44, crc32_final(rest))
    put_u32(desc, 0x48, segment_count)
    # Descriptor CRC (0x4c) covers primary header + descriptor[0:0x4c]
    put_u32(desc, 0x4C, crc32_final(primary_header + bytes(desc[:0x4C])))
    return bytes(desc)


def build_0005(target: TargetRegion, payload: bytes,
               *, desc2: int, desc3: int, pci: int = 0,
               ) -> bytes:
    primary = build_primary_header(fmt=FORMAT_0005,
                                   component=DEFAULT_COMPONENT_0005)
    rest, segments = build_0005_rest(target, payload)
    descriptor = build_descriptor(target, rest,
                                  primary_header=primary,
                                  desc2=desc2, desc3=desc3,
                                  pci=pci,
                                  segment_count=len(segments))
    return primary + descriptor + rest


def target_for_container(info: dict) -> TargetRegion | None:
    """Return the TargetRegion this container targets, or None if it can't
    be inferred. 0005 reads it from the descriptor's `code` field; 0006 is
    implicitly a full-flash (FGCB) payload per the app verifier's marker=5
    path."""
    if info["format"] == FORMAT_0005:
        return TARGETS.get(info.get("code"))
    if info["format"] == FORMAT_0006:
        return TARGETS["FGCB"]
    return None


def build_0006(payload: bytes, component: str) -> bytes:
    if component not in COMPONENTS_0006:
        raise SystemExit(f"format 0006: component must be one of "
                         f"{list(COMPONENTS_0006)}; got {component!r}")
    primary = build_primary_header(fmt=FORMAT_0006, component=component)
    return primary + payload



def inspect_container(data: bytes) -> dict:
    if len(data) < PRIMARY_SIZE:
        raise ValueError(f"file too short for OTA container: {len(data)} bytes")
    primary   = data[:PRIMARY_SIZE]
    magic     = primary[OFF_MAGIC:OFF_MAGIC + 4]
    fmt       = primary[OFF_FORMAT:OFF_FORMAT + 4]
    comp_raw  = primary[OFF_COMPONENT:OFF_COMPONENT + COMPONENT_LEN]
    component = comp_raw.split(b"\x00", 1)[0].decode("ascii", "replace")

    info = {
        "file_size":  len(data),
        "magic":      magic,
        "magic_ok":   magic == MAGIC,
        "format":     fmt,
        "component":  component,
        "sha256":     hashlib.sha256(data).hexdigest().upper(),
    }

    if fmt == FORMAT_0005:
        if len(data) < PAYLOAD_OFFSET_0005:
            raise ValueError(f"0005 container too short: {len(data)} bytes")
        descriptor = data[PRIMARY_SIZE:PAYLOAD_OFFSET_0005]
        rest       = data[PAYLOAD_OFFSET_0005:]
        exp_payload_len = get_u32(descriptor, 0x40)
        exp_payload_crc = get_u32(descriptor, 0x44)
        exp_desc_crc    = get_u32(descriptor, 0x4C)
        act_payload_crc = crc32_final(rest)
        act_desc_crc    = crc32_final(primary + descriptor[:0x4C])
        seg_info = parse_0005_segments(descriptor, rest)
        info.update({
            "payload_offset":     PAYLOAD_OFFSET_0005,
            "payload_size":       len(rest),
            "rest_size":          len(rest),
            "code":               descriptor[0x04:0x08].decode("ascii", "replace"),
            "marker":             get_u32(descriptor, 0x00),
            "desc2":              get_u32(descriptor, 0x08),
            "desc3":              get_u32(descriptor, 0x0C),
            "pci":                get_u32(descriptor, 0x10),
            "payload_len_ok":     len(rest) == exp_payload_len,
            "expected_payload_len": exp_payload_len,
            "payload_crc":        act_payload_crc,
            "expected_payload_crc": exp_payload_crc,
            "payload_crc_ok":     act_payload_crc == exp_payload_crc,
            "descriptor_crc":     act_desc_crc,
            "expected_desc_crc":  exp_desc_crc,
            "descriptor_crc_ok":  act_desc_crc == exp_desc_crc,
        })
        info.update(seg_info)
        if (seg_info["segment_count"] == 1
                and seg_info["segment_table_ok"]
                and seg_info["segment_data_len_ok"]):
            seg = seg_info["segments"][0]
            info["target_payload_offset"] = seg["data_offset"]
            info["target_payload_size"] = seg["length"]
    elif fmt == FORMAT_0006:
        info.update({
            "payload_offset":     PAYLOAD_OFFSET_0006,
            "payload_size":       len(data) - PAYLOAD_OFFSET_0006,
            "target_payload_offset": PAYLOAD_OFFSET_0006,
            "target_payload_size": len(data) - PAYLOAD_OFFSET_0006,
        })

    # HW-region CRC check inside the target image bytes, not the 0005
    # segment table that precedes them.
    target = target_for_container(info)
    target_slice = target_payload_slice(info)
    if target is not None and target_slice is not None:
        off, size = target_slice
        payload = data[off:off + size]
        info["hw_crc_results"] = verify_payload_crcs(payload, target)
    else:
        info["hw_crc_results"] = []
    return info


def print_info(info: dict, path: str | None = None) -> None:
    if path:
        print(f"File:          {path}")
    print(f"Total size:    {info['file_size']} bytes")
    print(f"Magic:         {info['magic']!r}  "
          f"({'ok' if info['magic_ok'] else 'INVALID - expected OTA!'})")
    print(f"Format:        {info['format']!r}")
    print(f"Component:     {info['component']!r}")
    print(f"Payload size:  {info.get('payload_size', '?')}")
    if info["format"] == FORMAT_0005:
        print(f"Code:          {info['code']}  marker={info['marker']}")
        print(f"Descriptor:    desc2=0x{info['desc2']:08X}  "
              f"desc3=0x{info['desc3']:08X}  "
              f"pci=0x{info['pci']:08X}  "
              f"segments={info['segment_count']}")
        table_tag = "ok" if info["segment_table_ok"] else "INVALID"
        data_tag = "ok" if info["segment_data_len_ok"] else "MISMATCH"
        print(f"Segments:      table={info['segment_table_size']} B {table_tag}; "
              f"data={info.get('segment_data_size')} B {data_tag}")
        for seg in info.get("segments", []):
            print(f"  [{seg['index']:02d}] len=0x{seg['length']:08X} "
                  f"dest=0x{seg['flash_start']:08X}..0x{seg['flash_end']:08X}")
        print(f"Rest CRC:      0x{info['payload_crc']:08X}  "
              f"({'ok' if info['payload_crc_ok'] else 'MISMATCH, desc says 0x'+format(info['expected_payload_crc'],'08X')})")
        print(f"Desc CRC:      0x{info['descriptor_crc']:08X}  "
              f"({'ok' if info['descriptor_crc_ok'] else 'MISMATCH, desc says 0x'+format(info['expected_desc_crc'],'08X')})")
        print(f"Desc CRC span: primary[0:0x58] + descriptor[0:0x4c]")

    hw = info.get("hw_crc_results") or []
    if hw:
        print(f"HW region CRC16-CCITT ({len(hw)} region(s) in payload):")
        for (name, stored, computed, ok) in hw:
            tag = "ok" if ok else "MISMATCH"
            print(f"  {name}: stored=0x{stored:04X} computed=0x{computed:04X} {tag}")
    print(f"SHA256(file):  {info['sha256']}")



BLOCK_ATTEMPTS = 3  # per-UpgradeDataBlock retry budget


def _send_block(t: Transport, params: dict) -> None:
    """Send one UpgradeDataBlock. Retries up to BLOCK_ATTEMPTS times on FramingError / TimeoutError.
       UpgradeDataBlock is offset-addressed, so retrying is safe
    """
    last_exc: Exception | None = None
    for attempt in range(1, BLOCK_ATTEMPTS + 1):
        try:
            resp = t.rpc("UpgradeDataBlock", params,
                         timeout=BLOCK_RPC_TIMEOUT,
                         post_send_delay=0.0)
            if resp.get("result") is True:
                return
            raise RuntimeError(
                f"UpgradeDataBlock @0x{params['fileOffset']:08x} rejected "
                f"by device (result={resp.get('result')!r}). Restart the "
                f"upload with a fresh InitiateUpgrade.")
        except (TimeoutError, FramingError) as exc:
            last_exc = exc
            if attempt < BLOCK_ATTEMPTS:
                log.warning("block @0x%08x attempt %d/%d: %s; retrying",
                            params['fileOffset'], attempt, BLOCK_ATTEMPTS, exc)
                continue
            raise
    assert last_exc is not None
    raise last_exc



ApplyMode = str
APPLY_NONE          = "none"
APPLY_PLAIN         = "plain"
APPLY_AUTHENTICATED = "authenticated"


def resolve_apply_mode(args, t: Transport | None = None) -> ApplyMode:
    """Pick an apply disposition:
        --apply-plain               -> PLAIN   (ApplyUpgrade)
        --apply / --apply-authenticated -> AUTHENTICATED (ApplyAuthenticatedUpgrade + HMAC)
        (nothing)                   -> NONE    (verify-only, stop after CheckUpgradeFile)
    """
    want_auth = bool(getattr(args, "apply", False)
                     or getattr(args, "apply_authenticated", False))
    want_plain = bool(getattr(args, "apply_plain", False))
    if want_auth and want_plain:
        raise SystemExit("pass only one of --apply / --apply-authenticated / --apply-plain")
    if want_plain:
        return APPLY_PLAIN
    if want_auth:
        return APPLY_AUTHENTICATED
    return APPLY_NONE


def build_transport_for_flash(args) -> Transport:
    spec = _resolve_device_spec(args)

    if spec.startswith("ble:"):
        target = spec[4:]
        if not target:
            raise SystemExit("ble: spec needs MAC / UUID / alias")
        from as11_ble import BleTransport
        t = BleTransport.from_args(target, args)
        t.connect()
        return t

    if spec.startswith("can:"):
        target = spec[4:]
        if not target:
            raise SystemExit("can: spec needs adapter target (serial path or interface name)")
        if _can_transport is not None:
            t = _can_transport.from_args(target, args)
        else:
            from as11_can_transport import from_args as can_transport_from_args
            t = can_transport_from_args(target, args)
        t.connect()
        return t

    raise SystemExit(
        f"unrecognised device spec {spec!r}; expected ble:<addr> or can:<port>"
    )


def _resolve_device_spec(args) -> str:
    if getattr(args, "device", None):
        return args.device
    if getattr(args, "addr", None):
        return f"ble:{args.addr}"
    if getattr(args, "port", None):
        return f"can:{args.port}"
    if os.environ.get("AS11_ADDR"):
        return f"ble:{os.environ['AS11_ADDR']}"
    if os.environ.get("AS11_CAN_PORT"):
        return f"can:{os.environ['AS11_CAN_PORT']}"
    raise SystemExit(
        "no device: pass -d/--device ble:<addr> or can:<port>, "
        "--addr <ble>, -p <can-port>, or set AS11_ADDR / AS11_CAN_PORT"
    )


def transport_supports_encrypted(t: Transport) -> bool:
    return bool(getattr(t, "supports_encrypted", False))


# Upload phases. Synchronous, transport-backed.

def phase_initiate(t: Transport, total: int) -> int:
    """InitiateUpgrade -> device-advertised raw-bytes-per-block."""
    print(f"[1/3] InitiateUpgrade size={total}")
    resp = t.rpc("InitiateUpgrade",
                 {"upgradeFileSize": total},
                 timeout=BLOCK_RPC_TIMEOUT)
    raw_block = int(resp.get("result", {}).get("xferBlockSize", XFER_RAW_BYTES))
    if raw_block <= 0 or raw_block > XFER_RAW_BYTES:
        raise RuntimeError(f"device returned suspicious xferBlockSize={raw_block}")
    if raw_block != XFER_RAW_BYTES:
        print(f"  device advertised xferBlockSize={raw_block}")
    return raw_block


def phase_stream(t: Transport, abc: bytes,
                 raw_block: int, *,
                 block_delay_s: float) -> None:
    """UpgradeDataBlock loop with progress bar."""
    total = len(abc)
    n_blocks = (total + raw_block - 1) // raw_block
    print(f"[2/3] UpgradeDataBlock x{n_blocks} "
          f"({raw_block} raw B/block, {raw_block * 2} hex chars/block)")

    # Silence noisy per-frame debug logs so the progress line stays readable.
    noisy_loggers = [logging.getLogger(n) for n in
                     ("as11_ble", "as11.ble",
                      "as11.can_waveshare", "as11.flash")]
    prev_levels = [(lg, lg.level) for lg in noisy_loggers]
    for lg, _ in prev_levels:
        if lg.level < logging.WARNING:
            lg.setLevel(logging.WARNING)

    t0 = time.monotonic()
    last_print = t0
    try:
        for i in range(n_blocks):
            off = i * raw_block
            chunk = abc[off:off + raw_block]
            _send_block(
                t,
                {"fileOffset": off, "encoding": "AsciiHex",
                 "data": chunk.hex().upper()})
            if block_delay_s > 0:
                time.sleep(block_delay_s)

            now = time.monotonic()
            if now - last_print >= 1.0 or i == n_blocks - 1:
                done = min(off + raw_block, total)
                elapsed = max(now - t0, 0.001)
                rate = done / elapsed
                eta = (total - done) / rate if rate > 0 else 0
                print(f"  block {i+1}/{n_blocks}  {done}/{total} B  "
                      f"{100.0 * done / total:5.1f}%  "
                      f"{rate/1024:.1f} KiB/s  ETA {eta:4.0f}s",
                      end="\r", flush=True)
                last_print = now
    finally:
        for lg, lvl in prev_levels:
            lg.setLevel(lvl)
    print()


def phase_check(t: Transport, file_hash: str,
                *, verify_timeout: float) -> None:
    """CheckUpgradeFile. can take tens of seconds."""

    print(f"[3/3] CheckUpgradeFile hash={file_hash[:16]}...  "
          f"(timeout {verify_timeout:.0f}s)")
    resp = t.rpc("CheckUpgradeFile",
                 {"upgradeFileHash": file_hash},
                 timeout=verify_timeout)
    print(f"  result: {resp.get('result')!r}")


def phase_apply(t: Transport, *,
                mode: ApplyMode,
                file_hash: str, file_hash_bytes: bytes,
                key: bytes,
                reset_settings: bool,
                verify_timeout: float) -> None:
    """ApplyUpgrade or ApplyAuthenticatedUpgrade."""
    if mode == APPLY_PLAIN:
        params = {
            "upgradeFileHash": file_hash,
            "resetSettingsToDefault": bool(reset_settings),
        }
        print(f"[apply] ApplyUpgrade  (timeout {verify_timeout:.0f}s)")
        resp = t.rpc("ApplyUpgrade", params, timeout=verify_timeout)
        print(f"  result: {resp.get('result')!r}")
        return

    if mode == APPLY_AUTHENTICATED:
        tag = hmac.new(key, file_hash_bytes, hashlib.sha256).hexdigest().upper()
        print(f"[apply] ApplyAuthenticatedUpgrade tag={tag[:16]}...  "
              f"(timeout {verify_timeout:.0f}s)")
        resp = t.rpc("ApplyAuthenticatedUpgrade",
                     {"upgradeFileHash": file_hash,
                      "authentication":  tag},
                     timeout=verify_timeout)
        print(f"  result: {resp.get('result')!r}")
        print("Device should reboot and hand off to the bootloader/apply stage.")
        return

    raise ValueError(f"phase_apply called with mode={mode!r}; caller bug")


def run_upload(t: Transport, abc: bytes, *,
               apply_mode: ApplyMode,
               reset_settings: bool,
               key: bytes,
               block_delay_s: float,
               verify_timeout: float) -> int:

    total = len(abc)
    file_hash_bytes = hashlib.sha256(abc).digest()
    file_hash = file_hash_bytes.hex().upper()

    raw_block = phase_initiate(t, total)
    phase_stream(t, abc, raw_block, block_delay_s=block_delay_s)
    phase_check(t, file_hash, verify_timeout=verify_timeout)

    if apply_mode == APPLY_NONE:
        print()
        print("CheckUpgradeFile succeeded. Not committing (no --apply /")
        print("--apply-plain). Pass --apply once you're ready to reboot.")
        return 0

    phase_apply(t,
                mode=apply_mode,
                file_hash=file_hash,
                file_hash_bytes=file_hash_bytes,
                key=key, reset_settings=reset_settings,
                verify_timeout=verify_timeout)
    return 0



def check_danger_ack(args, target: TargetRegion) -> None:
    if not target.danger_flag:
        return
    if getattr(args, target.danger_flag, False):
        return
    flag = "--" + target.danger_flag.replace("_", "-")
    raise SystemExit(
        f"{target.code} targets {target.notes} "
        f"({target.flash_start:#010x}..{target.flash_end:#010x}); "
        f"pass {flag} to continue.")



def check_and_maybe_fix_hw_crcs(payload: bytes, target: TargetRegion,
                                *, fix: bool, force: bool,
                                label: str = "input image") -> bytes:
    """Verify CRC16-CCITT footers on HW regions inside `payload`
    Returns the payload (possibly patched if `fix=True`)
    Raises SystemExit on mismatch when neither fix nor force is set
    """
    crc_results = verify_payload_crcs(payload, target)
    if not crc_results:
        log.info("no HW CRC region fits inside this payload; skipping check")
        return payload

    print(f"CRC16-CCITT check ({len(crc_results)} region(s) in payload):")
    for (name, stored, computed, ok) in crc_results:
        tag = "ok" if ok else "MISMATCH"
        print(f"  {name}: stored=0x{stored:04X} computed=0x{computed:04X} {tag}")

    if all(ok for (_, _, _, ok) in crc_results):
        return payload

    if fix:
        payload, fixed = fix_payload_crcs(payload, target)
        for (name, new_crc) in fixed:
            print(f"  fixed {name} CRC -> 0x{new_crc:04X}")
        return payload
    if force:
        return payload
    raise SystemExit(
        f"CRC mismatch in {label}. Use --fix-crc to patch CRCs "
        f"in memory, or --force to proceed with the bad CRCs as-is.")


def _build_container(args, *,
                     detected_preset: str | None = None
                     ) -> tuple[bytes, TargetRegion, bytes]:
    """Assemble the .abc container"""

    target = resolve_block(args.block)
    check_danger_ack(args, target)
    payload = load_payload(args, target)
    payload = check_and_maybe_fix_hw_crcs(
        payload, target,
        fix=getattr(args, "fix_crc", False),
        force=getattr(args, "force", False))

    fmt = args.format.encode("ascii")
    if fmt == FORMAT_0006:
        # 0006 is implicitly a full-image shortcut; only FGCB makes semantic sense
        if target.code != "FGCB":
            raise SystemExit(
                f"format 0006 is a full-image shortcut; --block must resolve "
                f"to FGCB (e.g. --block full). Got --block {args.block} "
                f"({target.code}).")
        component = getattr(args, "component_0006", "PacificFG")
        abc = build_0006(payload, component)
        return abc, target, FORMAT_0006

    # 0005
    desc2, desc3, pci = resolve_descriptor_words(args, target,
                                                 detected_preset=detected_preset)
    abc = build_0005(target, payload,
                     desc2=desc2, desc3=desc3,
                     pci=pci)
    return abc, target, FORMAT_0005


def cmd_targets(_args) -> int:
    print(f"{'Code':5s} {'Range':26s} {'Size':>12s}  Notes")
    for t in TARGETS.values():
        flag = ""
        if t.danger_flag == "include_bootloader":
            flag = "  (needs --include-bootloader)"
        elif t.danger_flag == "include_full_flash":
            flag = "  (needs --include-full-flash)"
        print(f"{t.code:5s} {t.flash_start:#010x}..{t.flash_end:#010x}  "
              f"{t.size:>10d} B  {t.notes}{flag}")
    print()
    print("Block aliases: config->CONF, firmware/app->APPL, conf+app->APCX,")
    print("               bootloader->FGBL, full/all->FGCB")
    return 0


def cmd_build(args) -> int:
    # auto-detect is a runtime (device-query) concept and doesn't apply to
    # offline builds. Error early if the target actually needs a preset.
    tgt = resolve_block(args.block)
    if args.desc_preset == "auto" and _auto_preset_needed(args, tgt):
        known = "/".join(sorted(DESC_PRESETS))
        raise SystemExit(
            f"{tgt.code} needs descriptor preset, and `build` can't query a "
            f"device. Pass --desc-preset {known} (or --desc2/--desc3), or use "
            f"the `flash` subcommand which can auto-detect.")
    abc, target, fmt = _build_container(args)
    out = Path(args.output)
    out.write_bytes(abc)
    print(f"Wrote {out} ({len(abc)} bytes, format {fmt.decode('ascii')}, "
          f"target {target.code})")
    print_info(inspect_container(abc))
    return 0


def cmd_info(args) -> int:
    data = Path(args.file).read_bytes()
    print_info(inspect_container(data), path=args.file)
    return 0


def detect_preset_for_descriptor(t: Transport) -> str:
    """Query the device's ApplicationIdentifier and map it to DESC_PRESETS.
    Raises SystemExit with a clean message on any failure path."""
    print("[auto] querying device firmware version...")
    detected = fetch_firmware_version(t)
    if detected is None:
        raise SystemExit(
            "auto-detect failed: device didn't return ApplicationIdentifier. "
            "Pass --desc-preset or --desc2/--desc3 explicitly.")
    if detected not in DESC_PRESETS:
        known = ", ".join(sorted(DESC_PRESETS))
        raise SystemExit(
            f"device reports firmware {detected!r} which isn't in "
            f"DESC_PRESETS ({known}). Pass --desc-preset explicitly, or "
            f"extract the new version's desc2/desc3 constants "
            f"(see docs/s11_ota.md).")
    print(f"[auto] device reports {detected}; using matching preset")
    return detected


def _upload_kwargs_from_args(args) -> dict:
    """Build the keyword args to run_upload() from parsed CLI args."""
    apply_mode = resolve_apply_mode(args)
    if apply_mode == APPLY_AUTHENTICATED:
        key = parse_key(getattr(args, "key", None),
                        getattr(args, "key_file", None),
                        stored_key=stored_ota_key_for_device(args))
    else:
        key = b""   # unused downstream; phase_apply guards on mode
    return dict(
        apply_mode=apply_mode,
        reset_settings=bool(getattr(args, "reset_settings", False)),
        key=key,
        block_delay_s=args.block_delay,
        verify_timeout=args.verify_timeout,
    )


def cmd_upload(args) -> int:
    resolve_apply_mode(args)

    abc = Path(args.file).read_bytes()
    info = inspect_container(abc)
    path = args.file

    if not info["magic_ok"]:
        raise SystemExit(f"{path}: bad magic {info['magic']!r}, "
                         f"expected {MAGIC!r}")
    if info["format"] not in (FORMAT_0005, FORMAT_0006):
        raise SystemExit(f"{path}: unknown format {info['format']!r}; "
                         f"expected {FORMAT_0005!r} or {FORMAT_0006!r}")

    def _soft(msg: str) -> None:
        if args.force:
            log.warning("ignoring: %s (--force)", msg)
        else:
            raise SystemExit(
                f"{path}: {msg} (pass --force to upload anyway)")

    known_components = {DEFAULT_COMPONENT_0005, *COMPONENTS_0006, "PacificBT"}
    if info["component"] not in known_components:
        _soft(f"unknown component string {info['component']!r}; "
              f"known: {sorted(known_components)}")

    if info["format"] == FORMAT_0005:
        if info.get("code") not in TARGETS:
            _soft(f"0005 descriptor code {info.get('code')!r} not in "
                  f"TARGETS ({sorted(TARGETS)})")
        if info.get("marker") != 1:
            _soft(f"0005 descriptor marker={info.get('marker')} "
                  f"(verifier requires 1)")
        legacy_raw_0005 = (info.get("segment_count") == 0
                           and args.fix_crc
                           and info.get("code") in TARGETS)
        if not legacy_raw_0005:
            if not 1 <= info.get("segment_count", 0) <= 0xFF:
                _soft(f"0005 descriptor segment_count="
                      f"{info.get('segment_count')} "
                      f"(bootloader requires 1..255)")
            if not info.get("segment_table_ok", False):
                _soft("0005 segment table is missing or truncated")
            if not info.get("segment_data_len_ok", False):
                _soft("0005 segment data length doesn't match the "
                      "descriptor segment table")

        target = target_for_container(info)
        if target is not None and info.get("segments"):
            total = 0
            for seg in info["segments"]:
                total += seg["length"]
                if seg["flash_start"] < target.flash_start:
                    _soft(f"segment {seg['index']} starts before "
                          f"{target.code}: 0x{seg['flash_start']:08X}")
                if seg["flash_end"] > target.flash_end:
                    _soft(f"segment {seg['index']} ends after "
                          f"{target.code}: 0x{seg['flash_end']:08X}")
            if total != target.size:
                _soft(f"0005 segment data totals {total} bytes, "
                      f"but {target.code} target size is {target.size} bytes")

        if not info.get("payload_len_ok", True) and not args.fix_crc:
            _soft("descriptor rest length field doesn't match "
                  "actual payload size")

        if not info.get("payload_crc_ok", True) and not args.fix_crc:
            _soft("descriptor rest CRC mismatch "
                  "(pass --fix-crc to recompute)")
        if not info.get("descriptor_crc_ok", True) and not args.fix_crc:
            _soft("descriptor CRC mismatch (pass --fix-crc to recompute)")

    if info["format"] == FORMAT_0006 and resolve_apply_mode(args) != APPLY_NONE:
        _soft("format 0006 can pass the app verifier, but the SRAM updater "
              "path found so far only applies OTA!0005 containers")

    # HW-region CRC check inside the target image bytes. May return a patched
    # image when --fix-crc repaired a broken footer.
    target = target_for_container(info)
    if info["format"] == FORMAT_0006 and target is not None:
        if info.get("payload_size") != target.size:
            _soft(f"0006 payload is {info.get('payload_size')} bytes, "
                  f"but {target.code} target size is {target.size} bytes")
    target_slice = target_payload_slice(info)
    if target_slice is not None:
        off, size = target_slice
        payload = abc[off:off + size]
    elif (info["format"] == FORMAT_0005 and args.fix_crc
          and info.get("segment_count") == 0 and target is not None):
        # Repair older app-verifier-valid containers that omitted the
        # bootloader segment table and stored raw image bytes directly.
        payload = abc[PAYLOAD_OFFSET_0005:]
        print("  treating legacy 0005 raw payload as one bootloader segment")
    else:
        payload = None

    if target is not None and payload is not None:
        payload = check_and_maybe_fix_hw_crcs(
            payload, target,
            fix=args.fix_crc, force=args.force,
            label=f"{args.file} target image")

    if args.fix_crc and target is not None:
        if info["format"] == FORMAT_0005:
            desc = abc[PRIMARY_SIZE:PAYLOAD_OFFSET_0005]
            desc2 = get_u32(desc, 0x08)
            desc3 = get_u32(desc, 0x0C)
            pci = get_u32(desc, 0x10)
            if payload is None:
                raise SystemExit(
                    f"{path}: cannot --fix-crc because this 0005 container "
                    "does not expose a single target-image payload")
            abc = build_0005(target, payload,
                             desc2=desc2, desc3=desc3, pci=pci)
            print("  rebuilt 0005 descriptor + segment table "
                  "(rest-len / rest-CRC / descriptor-CRC refreshed)")
        elif info["format"] == FORMAT_0006:
            abc = abc[:PRIMARY_SIZE] + payload

    if args.dry_run:
        print("dry-run: validated container, not contacting device")
        print_info(inspect_container(abc), path=args.file)
        return 0

    upload_kwargs = _upload_kwargs_from_args(args)

    t = build_transport_for_flash(args)
    try:
        return run_upload(t, abc, **upload_kwargs)
    finally:
        t.close()


def cmd_flash(args) -> int:
    # Fail fast on things we can check without hitting the device.
    resolve_apply_mode(args)
    target = resolve_block(args.block)
    check_danger_ack(args, target)

    need_detect = (args.desc_preset == "auto"
                   and _auto_preset_needed(args, target))

    if args.dry_run:
        # dry-run can't query the device, so auto-detect isn't possible.
        if need_detect:
            known = "/".join(sorted(DESC_PRESETS))
            raise SystemExit(
                f"--dry-run can't query the device. For auto-detect, remove "
                f"--dry-run, or pass --desc-preset {known} (or "
                f"--desc2/--desc3) explicitly.")
        abc, _, fmt = _build_container(args)
        print(f"Built {fmt.decode('ascii')} container for {target.code}  "
              f"({target.flash_start:#010x}..{target.flash_end:#010x}, "
              f"{len(abc)} bytes)")
        if args.save_abc:
            Path(args.save_abc).write_bytes(abc)
            print(f"Saved built container to {args.save_abc}")
        print("dry-run: not contacting device")
        print_info(inspect_container(abc))
        return 0

    # Live flash path: connect, maybe detect version, build, upload.
    upload_kwargs = _upload_kwargs_from_args(args)

    # If user didn't supply --pci and we're building a 0005 container,
    # we'll try to fetch it from the device after connecting. Irrelevant
    # for 0006 (no secondary descriptor at all).
    pci_fetch_needed = (args.format == "0005" and args.pci is None)

    t = build_transport_for_flash(args)
    try:
        detected_preset = None
        if need_detect:
            detected_preset = detect_preset_for_descriptor(t)

        if pci_fetch_needed:
            print("[auto] querying device _PCI (and _PRI for context)...")
            pci_val = fetch_pci(t)
            if pci_val is None:
                log.warning("could not read _PCI from device; falling "
                            "back to 0. If CheckUpgradeFile rejects "
                            "with -11309 it's likely this device has "
                            "_PRI=1 and enforces the check. Query "
                            "manually (e.g. `as11_config.py get _PCI "
                            "_PRI`) and pass --pci.")
            else:
                print(f"[auto] using _PCI=0x{pci_val:08X} in descriptor")
                args.pci = f"0x{pci_val:08X}"

        abc, _, fmt = _build_container(args, detected_preset=detected_preset)
        print(f"Built {fmt.decode('ascii')} container for {target.code}  "
              f"({target.flash_start:#010x}..{target.flash_end:#010x}, "
              f"{len(abc)} bytes)")
        if args.save_abc:
            Path(args.save_abc).write_bytes(abc)
            print(f"Saved built container to {args.save_abc}")

        return run_upload(t, abc, **upload_kwargs)
    finally:
        t.close()



def _add_input_args(p: argparse.ArgumentParser) -> None:
    """-f/--file + optional --from-full / --payload force-overrides."""
    p.add_argument("-f", "--file", metavar="PATH",
                   help="firmware input (full 2 MiB flash dump or pre-sliced "
                        "block payload; auto-detected by size)")
    p.add_argument("--from-full", metavar="PATH",
                   help="force: treat this file as a full 2 MiB flash dump "
                        "and slice the selected block out of it")
    p.add_argument("--payload", metavar="PATH",
                   help="force: treat this file as the already-sliced payload "
                        "for the selected block")


def _add_build_args(p: argparse.ArgumentParser) -> None:
    """All build-side options: block, format, descriptor."""
    p.add_argument("--block", required=True, metavar="NAME",
                   help="target block (aliases: config, firmware/app, "
                        "conf+app, bootloader, full/all; or raw codes "
                        "CONF, APPL, APCX, FGBL, FGCB)")
    p.add_argument("--format", default="0005", choices=("0005", "0006"),
                   help="container format (default: 0005). 0006 is only "
                        "valid for --block full and is the PacificFG/AlarmModule "
                        "full-image shortcut.")
    p.add_argument("--component-0006", default="PacificFG",
                   choices=list(COMPONENTS_0006),
                   help="(format 0006 only) primary header component string "
                        "(default: PacificFG)")
    # 0005 descriptor knobs
    p.add_argument("--desc-preset", default="auto",
                   choices=["auto"] + sorted(DESC_PRESETS) + ["none"],
                   help="fill 0005 descriptor words from a known firmware "
                        "preset (default: auto). With `auto`, `flash` queries "
                        "the device's ApplicationIdentifier and matches it to "
                        "DESC_PRESETS; `build` requires an explicit version.")
    p.add_argument("--desc2", metavar="U32",
                   help="0005 descriptor word at offset 0x08 (hex or decimal); "
                        "overrides preset")
    p.add_argument("--desc3", metavar="U32",
                   help="0005 descriptor word at offset 0x0c; overrides preset")
    p.add_argument("--pci", default=None, metavar="U32",
                   help="0005 descriptor word at offset 0x10: the device's "
                        "PCI code (firmware var 0x0232). The app verifier "
                        "checks it only when PRI (var 0x0111) == 1 - a "
                        "runtime gate. To fetch from a live device: "
                        "`as11_config.py --addr <dev> get _PCI _PRI`. "
                        "`flash` auto-fetches _PCI (and logs _PRI for "
                        "context) when this is omitted; `build` defaults "
                        "to 0 since it can't query a device.")
    # safety
    p.add_argument("--include-bootloader", action="store_true",
                   help="permit building/uploading FGBL (bootloader region)")
    p.add_argument("--include-full-flash", action="store_true",
                   help="permit building/uploading FGCB (complete 2 MiB flash)")
    # CRC handling (resmed_flash-style)
    p.add_argument("--fix-crc", action="store_true",
                   help="recompute and patch CRC16-CCITT footers in memory "
                        "before building (for hand-edited payloads where "
                        "the patcher didn't fix up footers)")


def _add_upload_args(p: argparse.ArgumentParser) -> None:
    """Upload + apply options."""
    p.add_argument("--apply", action="store_true",
                   help="after CheckUpgradeFile succeeds, call "
                        "ApplyAuthenticatedUpgrade (uses --key, "
                        "AS11_OTA_KEY, or stored BLE otaKey)")
    p.add_argument("--apply-authenticated", action="store_true",
                   help="synonym for --apply")
    p.add_argument("--apply-plain", action="store_true",
                   help="after CheckUpgradeFile succeeds, call "
                        "unauthenticated ApplyUpgrade.")
    p.add_argument("--reset-settings", action="store_true",
                   help="send resetSettingsToDefault=true with --apply-plain "
                        "(default sends false to preserve settings)")
    p.add_argument("--key", metavar="HEX32",
                   help="K_ota as 64 hex chars")
    p.add_argument("--key-file", metavar="PATH",
                   help="K_ota as a 32-byte binary file or a hex-text file")
    p.add_argument("--block-delay", type=float, default=0.0, metavar="SECONDS",
                   help="optional delay after each UpgradeDataBlock "
                        "(default: 0)")
    p.add_argument("--verify-timeout", type=float, default=LONG_RPC_TIMEOUT,
                   metavar="SECONDS",
                   help=(f"timeout for CheckUpgradeFile and Apply* "
                         f"(default: {int(LONG_RPC_TIMEOUT)}). "
                         f"The device drains NOR staging before replying."))
    p.add_argument("--dry-run", action="store_true",
                   help="validate the container and print the plan; "
                        "do not contact the device")
    p.add_argument("--force", action="store_true",
                   help=_FORCE_HELP)


def _add_device_args(p: argparse.ArgumentParser) -> None:
    """Device-selection args, matching as11_config.py conventions."""
    suppr = argparse.SUPPRESS
    g = p.add_argument_group("device selection")
    g.add_argument("-d", "--device", default=suppr,
                   help="device spec: ble:<mac|alias>, can:<port>")
    g.add_argument("--addr", default=suppr,
                   help="BLE target (compat for -d ble:<x>; env: AS11_ADDR)")
    g.add_argument("-p", "--port", default=suppr,
                   help="CAN target (compat for -d can:<x>; "
                        "env: AS11_CAN_PORT)")
    if _can_transport is not None:
        _can_transport.add_args(p)


def main(argv=None) -> int:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(name)s %(levelname)s %(message)s")

    ap = argparse.ArgumentParser(
        prog="as11_flash",
        description="AirSense 11 flash / OTA tool (BLE + CAN).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__)
    ap.add_argument("--debug", action="store_true",
                    help="verbose transport-level packet logging")
    sub = ap.add_subparsers(dest="cmd", required=True)

    # targets
    p_t = sub.add_parser("targets", help="list block targets")
    p_t.set_defaults(func=cmd_targets)

    # build
    p_b = sub.add_parser("build", help="build an .abc container locally")
    _add_input_args(p_b)
    _add_build_args(p_b)
    p_b.add_argument("-o", "--output", required=True,
                     help="output .abc path")
    p_b.add_argument("--force", action="store_true",
                     help=_FORCE_HELP)
    p_b.set_defaults(func=cmd_build)

    # info
    p_i = sub.add_parser("info", help="inspect an .abc container")
    p_i.add_argument("file", help=".abc file to inspect")
    p_i.set_defaults(func=cmd_info)

    # upload
    p_u = sub.add_parser("upload",
                         help="push a pre-built .abc; CheckUpgradeFile only "
                              "unless --apply / --apply-plain is given")
    _add_device_args(p_u)
    p_u.add_argument("file", help=".abc file to upload")
    p_u.add_argument("--fix-crc", action="store_true",
                     help="recompute and patch CRC16-CCITT HW-region footers "
                          "in the target image; for 0005, also refresh the "
                          "descriptor and add the bootloader segment table "
                          "when repairing an older raw-payload container")
    _add_upload_args(p_u)
    p_u.set_defaults(func=cmd_upload)

    # flash (build + upload)
    p_f = sub.add_parser("flash",
                         help="build .abc from firmware and upload in one step; "
                              "CheckUpgradeFile only unless --apply / "
                              "--apply-plain is given")
    _add_device_args(p_f)
    _add_input_args(p_f)
    _add_build_args(p_f)
    p_f.add_argument("--save-abc", metavar="PATH",
                     help="also write the built .abc to this path")
    _add_upload_args(p_f)
    p_f.set_defaults(func=cmd_flash)

    args = ap.parse_args(argv)

    # shared arg validation
    if getattr(args, "block_delay", 0.0) < 0:
        raise SystemExit("--block-delay must be non-negative")
    if getattr(args, "reset_settings", False) and not getattr(args, "apply_plain", False):
        raise SystemExit("--reset-settings only applies with --apply-plain")
    # apply-mode mutual exclusion is enforced inside resolve_apply_mode() now.

    return args.func(args)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\ninterrupted.", file=sys.stderr)
        sys.exit(130)
    except SystemExit:
        raise
    except argparse.ArgumentTypeError as e:
        print(f"\nerror: {e}", file=sys.stderr)
        sys.exit(2)
    except TimeoutError as e:
        print(f"\ntimeout: {e}", file=sys.stderr)
        sys.exit(1)
    except TransportError as e:
        print(f"\ntransport error: {e}", file=sys.stderr)
        sys.exit(1)
    except RuntimeError as e:
        if str(e).startswith("RPC error "):
            print(f"\n{e}", file=sys.stderr)
            sys.exit(1)
        raise
    except Exception as e:
        log.exception("fatal: %s", e)
        sys.exit(1)

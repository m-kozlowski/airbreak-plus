#!/usr/bin/env python3
"""AS11 Flash / OTA Tool.

Build, upload and apply firmware images on AirSense 11 / AirCurve 11
devices. Works over BLE, CAN, and AirCANnect TCP; transport selected with
-d/--device:

    -d ble:<mac|alias>          BLE
    -d can:<target>             CAN target (slcan, socketcan, or waveshare)
    -d tcp:<host>[:<port>]      AirCANnect TCP bridge (default port 39011)
    --addr <x>                  same as -d ble:<x>
    -p/--port <x>               same as -d can:<target>

Offline subcommands (no device needed):
    targets    list base firmware input combinations and inferred targets
    build      assemble a .abc container from firmware bytes
    info       inspect a .abc container

Device-touching subcommands:
    upload     push and verify a pre-built .abc; apply only when requested
    flash      build .abc from firmware, upload, and apply by transport default
    apply      apply a previously uploaded and verified .abc by file or hash
    service    use the bootloader service over CAN or AirCANnect TCP

Apply-mode flags, highest precedence first:
    --apply-plain          ApplyUpgrade (unauthenticated)
    --apply-authenticated  ApplyAuthenticatedUpgrade (+HMAC)
    --apply                alias for --apply-authenticated

When no apply-mode flag is given:
    upload                 stop after CheckUpgradeFile
    flash on BLE           authenticated apply (uses stored otaKey)
    flash on CAN / TCP     plain ApplyUpgrade
    apply on BLE           authenticated apply (uses stored otaKey)
    apply on CAN / TCP     plain ApplyUpgrade

Authenticated apply key resolution: --key HEX64, --key-file PATH, $AS11_OTA_KEY,
or stored BLE device otaKey.

"""

from __future__ import annotations

import argparse
import binascii
import hashlib
import hmac
import io
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

try:  # optional: AirCANnect TCP bridge
    import as11_aircannect as _aircannect_transport  # noqa: E402
except ModuleNotFoundError as exc:  # pragma: no cover
    if exc.name == "as11_aircannect":
        _aircannect_transport = None
    else:
        raise

from as11_rpc import (  # noqa: E402
    Transport, TransportError, FramingError, build_request,
)
from lib.as11_patch_versions import (  # noqa: E402
    AS11_OTA_COMPATIBILITY_FINGERPRINT_PRESETS,
)


log = logging.getLogger("as11.flash")


_FORCE_HELP = "override local container and image validation failures"


MAGIC          = b"OTA!"
FORMAT_0005    = b"0005"
PRIMARY_SIZE   = 0x58
DESCRIPTOR_SIZE = 0x50
PAYLOAD_OFFSET_0005 = PRIMARY_SIZE + DESCRIPTOR_SIZE   # 0xa8
SEGMENT_ENTRY_SIZE = 8

OFF_MAGIC      = 0x00
OFF_FORMAT     = 0x04
OFF_COMPONENT  = 0x48
COMPONENT_LEN  = 0x10

DEFAULT_COMPONENT_0005 = "PacificFG"

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
    conf_appl_compatibility_fingerprint_required: bool = False
    fgbl_appl_compatibility_fingerprint_required: bool = False
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
        conf_appl_compatibility_fingerprint_required=True,
        fgbl_appl_compatibility_fingerprint_required=True,
        atomic=True,
        notes="main app image"),
    "CONF": TargetRegion(
        "CONF", flash_start=0x08020000, size=0x00020000,
        conf_appl_compatibility_fingerprint_required=True,
        atomic=True,
        notes="config/aux block before app"),
    "APCX": TargetRegion(
        "APCX", flash_start=0x08020000, size=0x001E0000,
        fgbl_appl_compatibility_fingerprint_required=True,
        notes="combined CONF+APPL range"),
    "FGBL": TargetRegion(
        "FGBL", flash_start=0x08000000, size=0x00020000,
        fgbl_appl_compatibility_fingerprint_required=True,
        atomic=True,
        danger_flag="include_bootloader",
        notes="bootloader / low updater region"),
    "FGCB": TargetRegion(
        "FGCB", flash_start=0x08000000, size=0x00200000,
        danger_flag="include_bootloader",
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

# Per-firmware compatibility fingerprint presets for 0005 containers.
# Only CONF/APPL/APCX/FGBL targets need them. FGCB ignores these fields.
COMPATIBILITY_FINGERPRINT_PRESETS = AS11_OTA_COMPATIBILITY_FINGERPRINT_PRESETS

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


def fetch_fg_security_fingerprint(t: Transport) -> int | None:
    """Resolve descriptor offset 0x10 through the public RPC tags."""
    try:
        resp = t.rpc("Get", ["_SBA", "_SKF"], timeout=10.0)
    except Exception as e:
        log.warning("Get(_SBA,_SKF) failed: %s", e)
        return None
    result = resp.get("result")
    if not isinstance(result, dict):
        log.warning("Get(_SBA,_SKF) returned unexpected shape: %r", result)
        return None

    enabled = result.get("_SBA")
    fingerprint = result.get("_SKF")
    log.info("device reports _SBA=%r  _SKF=%r", enabled, fingerprint)

    if enabled == "No":
        return 0
    if enabled != "Yes" or fingerprint is None:
        log.warning("unexpected FG security values: _SBA=%r _SKF=%r",
                    enabled, fingerprint)
        return None
    try:
        value = (int(fingerprint, 0) if isinstance(fingerprint, str)
                 else int(fingerprint))
        return value & 0xFFFFFFFF
    except (TypeError, ValueError):
        log.warning("Get(_SKF) returned %r; can't coerce to int", fingerprint)
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


FIRMWARE_SOURCE_ARGS = (
    ("fgbl", "--fgbl", "FGBL"),
    ("conf", "--conf", "CONF"),
    ("appl", "--appl", "APPL"),
    ("full", "--full", "FGCB"),
)

TARGET_BY_SOURCE_SET = {
    frozenset(("FGBL",)): "FGBL",
    frozenset(("CONF",)): "CONF",
    frozenset(("APPL",)): "APPL",
    frozenset(("CONF", "APPL")): "APCX",
    frozenset(("FGBL", "CONF", "APPL")): "FGCB",
    # A full image defaults to the normal application update range. `flash`
    # can promote it to FGCB with --include-bootloader.
    frozenset(("FGCB",)): "APCX",
}


def firmware_source_set_label(source_set: frozenset[str]) -> str:
    return " + ".join(
        label for _attr, label, code in FIRMWARE_SOURCE_ARGS
        if code in source_set
    )


def firmware_sources(args) -> list[tuple[str, str, TargetRegion]]:
    return [
        (label, value, TARGETS[code])
        for attr, label, code in FIRMWARE_SOURCE_ARGS
        if (value := getattr(args, attr, None))
    ]


def contained_region_codes(region: TargetRegion) -> tuple[str, ...]:
    return tuple(name for name, _off, _size in regions_in_payload(region))


def resolve_target_from_args(args) -> TargetRegion:
    sources = firmware_sources(args)
    if not sources:
        raise SystemExit(
            "firmware source required: pass --fgbl, --conf, --appl, or --full")

    if (block := getattr(args, "block", None)) is not None:
        target = resolve_block(block)
        required = set(contained_region_codes(target))
        available = {
            code
            for _label, _path, source_region in sources
            for code in contained_region_codes(source_region)
        }
        missing = required - available
        if missing:
            labels = {
                code: label for _attr, label, code in FIRMWARE_SOURCE_ARGS
                if code != "FGCB"
            }
            missing_args = ", ".join(labels[code] for code in sorted(missing))
            raise SystemExit(
                f"--block {target.code} needs additional input: {missing_args}")
        return target

    source_set = frozenset(region.code for _label, _path, region in sources)
    if "FGCB" in source_set:
        # A full image defaults to the application update range. Explicitly
        # acknowledging the bootloader promotes it to the complete image.
        target_code = (
            "FGCB" if getattr(args, "include_bootloader", False) else "APCX"
        )
    else:
        target_code = TARGET_BY_SOURCE_SET.get(source_set)
    if target_code is None:
        selected = " + ".join(label for label, _path, _region in sources)
        supported = ", ".join(
            firmware_source_set_label(combination)
            for combination in TARGET_BY_SOURCE_SET
        )
        raise SystemExit(
            f"unsupported firmware source combination: {selected}. "
            f"Use one of {supported}")
    return TARGETS[target_code]


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
    """Load the selected regions and assemble the inferred target range."""
    sources = firmware_sources(args)
    required = contained_region_codes(target)
    cache: dict[str, bytes] = {}
    pieces: dict[str, bytes] = {}

    def read_source(path: str) -> bytes:
        try:
            if path not in cache:
                cache[path] = Path(path).read_bytes()
            return cache[path]
        except OSError as exc:
            raise SystemExit(f"{path}: {exc}") from exc

    # A full image supplies every region not replaced by an explicit source.
    for label, path, region in sources:
        if region.code != "FGCB":
            continue
        data = read_source(path)
        if len(data) != FULL_FLASH_SIZE:
            raise SystemExit(
                f"{path}: {label} expects a {FULL_FLASH_SIZE}-byte full "
                f"internal image; got {len(data)} bytes")
        for code in required:
            part = TARGETS[code]
            start = part.full_image_offset
            pieces[code] = data[start:start + part.size]

    # Regional arguments override the corresponding slice from --full.
    for label, path, region in sources:
        if region.code == "FGCB" or region.code not in required:
            continue
        data = read_source(path)
        if len(data) == region.size:
            pieces[region.code] = data
            continue
        if len(data) == FULL_FLASH_SIZE:
            start = region.full_image_offset
            pieces[region.code] = data[start:start + region.size]
            continue

        expected = (f"a {region.size}-byte raw {region.code} region or "
                    f"a {FULL_FLASH_SIZE}-byte full internal image")
        raise SystemExit(
            f"{path}: {label} expects {expected}; got {len(data)} bytes")

    return b"".join(pieces[code] for code in required)


def _auto_preset_needed(args, target: TargetRegion) -> bool:
    """
    False when the target ignores both compatibility fingerprints, or when
    the user supplied explicit overrides for every required fingerprint.
    """
    if (not target.conf_appl_compatibility_fingerprint_required
            and not target.fgbl_appl_compatibility_fingerprint_required):
        return False
    have_conf_appl = parse_u32(
        getattr(args, "conf_appl_compatibility_fingerprint", None),
        name="conf_appl_compatibility_fingerprint",
    ) is not None
    have_fgbl_appl = parse_u32(
        getattr(args, "fgbl_appl_compatibility_fingerprint", None),
        name="fgbl_appl_compatibility_fingerprint",
    ) is not None
    if (target.conf_appl_compatibility_fingerprint_required
            and not have_conf_appl):
        return True
    if (target.fgbl_appl_compatibility_fingerprint_required
            and not have_fgbl_appl):
        return True
    return False


def resolve_descriptor_fingerprints(
        args, target: TargetRegion, *, detected_preset: str | None = None
        ) -> tuple[int, int, int]:
    """Combine a release preset with explicit fingerprint overrides."""

    conf_appl_compatibility_fingerprint = parse_u32(
        args.conf_appl_compatibility_fingerprint,
        name="conf_appl_compatibility_fingerprint",
    )
    fgbl_appl_compatibility_fingerprint = parse_u32(
        args.fgbl_appl_compatibility_fingerprint,
        name="fgbl_appl_compatibility_fingerprint",
    )
    fg_security_fingerprint = parse_u32(
        getattr(args, "fg_security_fingerprint", None),
        name="fg_security_fingerprint",
    )

    preset_key = args.fingerprint_preset
    if preset_key == "auto":
        preset_key = detected_preset

    if (preset_key and preset_key != "none"
            and preset_key in COMPATIBILITY_FINGERPRINT_PRESETS):
        preset = COMPATIBILITY_FINGERPRINT_PRESETS[preset_key]
        if conf_appl_compatibility_fingerprint is None:
            conf_appl_compatibility_fingerprint = preset[
                "conf_appl_compatibility_fingerprint"]
        if fgbl_appl_compatibility_fingerprint is None:
            fgbl_appl_compatibility_fingerprint = preset[
                "fgbl_appl_compatibility_fingerprint"]

    if conf_appl_compatibility_fingerprint is None:
        conf_appl_compatibility_fingerprint = 0
    if fgbl_appl_compatibility_fingerprint is None:
        fgbl_appl_compatibility_fingerprint = 0
    if fg_security_fingerprint is None:
        fg_security_fingerprint = 0

    missing = []
    if (target.conf_appl_compatibility_fingerprint_required
            and conf_appl_compatibility_fingerprint == 0):
        missing.append("--conf-appl-fingerprint")
    if (target.fgbl_appl_compatibility_fingerprint_required
            and fgbl_appl_compatibility_fingerprint == 0):
        missing.append("--fgbl-appl-fingerprint")
    if missing:
        known = ", ".join(sorted(COMPATIBILITY_FINGERPRINT_PRESETS))
        raise SystemExit(
            f"{target.code} needs {', '.join(missing)}. "
            f"Use --fingerprint-preset (one of {known}) or pass explicit "
            "compatibility fingerprints.")
    return (conf_appl_compatibility_fingerprint,
            fgbl_appl_compatibility_fingerprint,
            fg_security_fingerprint)



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
                     conf_appl_compatibility_fingerprint: int,
                     fgbl_appl_compatibility_fingerprint: int,
                     fg_security_fingerprint: int,
                     segment_count: int) -> bytes:
    if len(primary_header) != PRIMARY_SIZE:
        raise ValueError(f"primary header must be {PRIMARY_SIZE} bytes")
    if not 1 <= segment_count <= 0xFF:
        raise SystemExit(
            f"0005 segment count out of range: {segment_count}")
    desc = bytearray(DESCRIPTOR_SIZE)
    put_u32(desc, 0x00, 1)
    desc[0x04:0x08] = target.code.encode("ascii")
    put_u32(desc, 0x08, conf_appl_compatibility_fingerprint)
    put_u32(desc, 0x0C, fgbl_appl_compatibility_fingerprint)
    put_u32(desc, 0x10, fg_security_fingerprint)
    put_u32(desc, 0x40, len(rest))
    put_u32(desc, 0x44, crc32_final(rest))
    put_u32(desc, 0x48, segment_count)
    # Descriptor CRC (0x4c) covers primary header + descriptor[0:0x4c]
    put_u32(desc, 0x4C, crc32_final(primary_header + bytes(desc[:0x4C])))
    return bytes(desc)


def build_0005(target: TargetRegion, payload: bytes,
               *, conf_appl_compatibility_fingerprint: int,
               fgbl_appl_compatibility_fingerprint: int,
               fg_security_fingerprint: int = 0,
               ) -> bytes:
    primary = build_primary_header(fmt=FORMAT_0005,
                                   component=DEFAULT_COMPONENT_0005)
    rest, segments = build_0005_rest(target, payload)
    descriptor = build_descriptor(
        target, rest,
        primary_header=primary,
        conf_appl_compatibility_fingerprint=conf_appl_compatibility_fingerprint,
        fgbl_appl_compatibility_fingerprint=fgbl_appl_compatibility_fingerprint,
        fg_security_fingerprint=fg_security_fingerprint,
        segment_count=len(segments),
    )
    return primary + descriptor + rest


def target_for_container(info: dict) -> TargetRegion | None:
    """Return the target named by a 0005 container descriptor."""
    if info["format"] == FORMAT_0005:
        return TARGETS.get(info.get("code"))
    return None


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

    if fmt != FORMAT_0005:
        raise ValueError(
            f"unsupported OTA format {fmt!r}; expected {FORMAT_0005!r}")
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
        "conf_appl_compatibility_fingerprint": get_u32(descriptor, 0x08),
        "fgbl_appl_compatibility_fingerprint": get_u32(descriptor, 0x0C),
        "fg_security_fingerprint": get_u32(descriptor, 0x10),
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
        print("Compatibility: "
              f"CONF/APPL=0x{info['conf_appl_compatibility_fingerprint']:08X}  "
              f"FGBL/APPL=0x{info['fgbl_appl_compatibility_fingerprint']:08X}")
        print("FG security:   "
              f"0x{info['fg_security_fingerprint']:08X}")
        print(f"Segment count: {info['segment_count']}")
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


def resolve_apply_mode(args, *, default: ApplyMode = APPLY_NONE) -> ApplyMode:
    """Pick an apply disposition:
        --apply-plain               -> PLAIN   (ApplyUpgrade)
        --apply / --apply-authenticated -> AUTHENTICATED (ApplyAuthenticatedUpgrade + HMAC)
        (nothing)                   -> caller-supplied default
    """
    want_auth = bool(getattr(args, "apply", False)
                     or getattr(args, "apply_authenticated", False)
                     or getattr(args, "authentication", None))
    want_plain = bool(getattr(args, "apply_plain", False))
    if want_auth and want_plain:
        raise SystemExit(
            "pass only one of --apply / --apply-authenticated / "
            "--apply-plain")
    if want_plain:
        return APPLY_PLAIN
    if want_auth:
        return APPLY_AUTHENTICATED
    return default


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

    if spec.startswith("tcp:"):
        target = spec[4:]
        if not target:
            raise SystemExit("tcp: spec needs host[:port]")
        if _aircannect_transport is not None:
            t = _aircannect_transport.from_args(target, args)
        else:
            from as11_aircannect import from_args as aircannect_from_args
            t = aircannect_from_args(target, args)
        t.connect()
        return t

    raise SystemExit(
        f"unrecognised device spec {spec!r}; "
        "expected ble:<addr>, can:<port>, or tcp:<host>[:<port>]"
    )


def build_service_client(args):
    from as11_service import (
        ISOTP_RX_BLOCK_SIZE,
        ServiceCanClient,
        ServicePacketClient,
    )

    spec = _resolve_device_spec(args)
    if spec.startswith("can:"):
        target = spec[4:]
        if not target:
            raise SystemExit(
                "can: spec needs adapter target (serial path or interface name)"
            )
        if _can_transport is not None:
            transport = _can_transport.from_args(target, args)
        else:
            from as11_can_transport import from_args as can_transport_from_args
            transport = can_transport_from_args(target, args)
        transport.connect()
        client = ServiceCanClient(
            transport.dev,
            block_size=(args.block_size if args.block_size is not None
                        else ISOTP_RX_BLOCK_SIZE),
        )
        return client, transport

    if spec.startswith("tcp:"):
        if args.block_size is not None:
            raise SystemExit("--block-size applies only to direct CAN service transport")
        target = spec[4:]
        if not target:
            raise SystemExit("tcp: spec needs host[:port]")
        if _aircannect_transport is not None:
            transport = _aircannect_transport.service_from_args(target, args)
        else:
            from as11_aircannect import service_from_args
            transport = service_from_args(target, args)
        transport.connect()
        return ServicePacketClient(transport), transport

    raise SystemExit(
        "service mode requires -d can:<target> or tcp:<host>[:<port>]"
    )


def _service_storage(kind: str):
    from as11_service import (
        BKPSRAM_SIZE,
        FLASH_BASE,
        FLASH_ERASE_SIZE,
        FLASH_PROGRAM_SIZE,
        FLASH_SIZE,
        NOR_ERASE_SIZE,
        NOR_SIZE,
        TARGET_BKPS,
        TARGET_FGCB,
        TARGET_SPIN,
    )

    if kind == "flash":
        return (
            TARGET_FGCB, "FGCB", FLASH_BASE, FLASH_SIZE,
            FLASH_ERASE_SIZE, FLASH_PROGRAM_SIZE,
        )
    if kind == "nor":
        return TARGET_SPIN, "SPIN", 0, NOR_SIZE, NOR_ERASE_SIZE, 1
    return TARGET_BKPS, "BKPS", 0, BKPSRAM_SIZE, 0, 1


def _service_range(kind: str, selection: list[str]):
    (target, target_name, target_start, target_size,
     erase_size, program_size) = _service_storage(kind)

    if not selection:
        offset = target_start
        length = target_size
    elif kind == "flash" and len(selection) == 1:
        region = resolve_block(selection[0])
        offset = region.flash_start
        length = region.size
        target_name = region.code
    elif len(selection) == 2:
        try:
            offset = _service_u32(selection[0])
            length = _service_length(selection[1])
        except argparse.ArgumentTypeError as exc:
            raise SystemExit(str(exc)) from exc
    else:
        expected = (
            "[REGION | OFFSET LENGTH]" if kind == "flash"
            else "[OFFSET LENGTH]"
        )
        raise SystemExit(f"expected {expected}")

    target_end = target_start + target_size
    if offset < target_start or offset >= target_end:
        raise SystemExit(
            f"{target_name} offset 0x{offset:08X} is outside "
            f"0x{target_start:08X}..0x{target_end:08X}"
        )
    if length > target_end - offset:
        raise SystemExit(
            f"{target_name} range 0x{offset:08X}+0x{length:X} "
            "extends past the target"
        )
    return (
        target, target_name, offset, length, target_start, target_size,
        erase_size, program_size,
    )


def _explicit_device_spec(args) -> str | None:
    explicit = [
        ("-d/--device", getattr(args, "device", None)),
        ("--addr", getattr(args, "addr", None)),
        ("-p/--port", getattr(args, "port", None)),
    ]
    selected = [(name, value) for name, value in explicit if value]
    if len(selected) > 1:
        names = ", ".join(name for name, _ in selected)
        raise SystemExit(f"conflicting device selectors: {names}; pass one")
    if selected:
        name, value = selected[0]
        if name == "--addr":
            return f"ble:{value}"
        if name == "-p/--port":
            return f"can:{value}"
        return value
    return None


def _resolve_device_spec(args) -> str:
    explicit = _explicit_device_spec(args)
    if explicit:
        return explicit
    if os.environ.get("AS11_ADDR"):
        return f"ble:{os.environ['AS11_ADDR']}"
    if os.environ.get("AS11_CAN_PORT"):
        return f"can:{os.environ['AS11_CAN_PORT']}"
    if os.environ.get("AS11_AIRCANNECT"):
        return f"tcp:{os.environ['AS11_AIRCANNECT']}"
    raise SystemExit(
        "no device: pass -d/--device ble:<addr>, can:<port>, or "
        "tcp:<host>[:<port>]; or --addr <ble>, -p <can-port>, "
        "or set AS11_ADDR / AS11_CAN_PORT / AS11_AIRCANNECT"
    )


def default_device_apply_mode(args) -> ApplyMode:
    spec = _resolve_device_spec(args)
    if spec.startswith("ble:"):
        return APPLY_AUTHENTICATED
    if spec.startswith("can:"):
        return APPLY_PLAIN
    if spec.startswith("tcp:"):
        # AirCANnect bridges over CAN; same security policy as plaintext CAN.
        return APPLY_PLAIN
    return APPLY_NONE


def default_apply_mode_for_command(args) -> ApplyMode:
    if args.cmd == "flash":
        if getattr(args, "dry_run", False):
            return APPLY_NONE
        return default_device_apply_mode(args)
    if args.cmd == "apply":
        return default_device_apply_mode(args)
    return APPLY_NONE


def resolved_apply_mode_for_command(args) -> ApplyMode:
    return resolve_apply_mode(
        args, default=default_apply_mode_for_command(args))


def validate_reset_settings(args) -> None:
    if not getattr(args, "reset_settings", False):
        return
    if resolved_apply_mode_for_command(args) != APPLY_PLAIN:
        raise SystemExit(
            "--reset-settings only applies with plain ApplyUpgrade")


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


def phase_stream(t: Transport, abc: bytes, raw_block: int) -> None:
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
    result = resp.get("result")
    print(f"  result: {result!r}")
    if result is not True:
        raise SystemExit(
            f"CheckUpgradeFile rejected the staged file (result={result!r})")


def phase_apply(t: Transport, *,
                mode: ApplyMode,
                file_hash: str, file_hash_bytes: bytes,
                key: bytes,
                authentication: str | None,
                reset_settings: bool,
                timeout: float) -> None:
    """ApplyUpgrade or ApplyAuthenticatedUpgrade."""
    if mode == APPLY_PLAIN:
        params = {
            "upgradeFileHash": file_hash,
            "resetSettingsToDefault": bool(reset_settings),
        }
        print(f"[apply] ApplyUpgrade  (timeout {timeout:.0f}s)")
        resp = t.rpc("ApplyUpgrade", params, timeout=timeout)
        print(f"  result: {resp.get('result')!r}")
        return

    if mode == APPLY_AUTHENTICATED:
        tag = authentication
        if tag is None:
            tag = hmac.new(
                key, file_hash_bytes, hashlib.sha256).hexdigest().upper()
        print(f"[apply] ApplyAuthenticatedUpgrade tag={tag[:16]}...  "
              f"(timeout {timeout:.0f}s)")
        resp = t.rpc("ApplyAuthenticatedUpgrade",
                     {"upgradeFileHash": file_hash,
                      "authentication":  tag},
                     timeout=timeout)
        print(f"  result: {resp.get('result')!r}")
        print("Device should reboot and hand off to the bootloader/apply stage.")
        return

    raise ValueError(f"phase_apply called with mode={mode!r}; caller bug")


def run_upload(t: Transport, abc: bytes, *,
               apply_mode: ApplyMode,
               reset_settings: bool,
               key: bytes,
               verify_timeout: float) -> int:

    total = len(abc)
    file_hash_bytes = hashlib.sha256(abc).digest()
    file_hash = file_hash_bytes.hex().upper()

    raw_block = phase_initiate(t, total)
    phase_stream(t, abc, raw_block)
    phase_check(t, file_hash, verify_timeout=verify_timeout)

    if apply_mode == APPLY_NONE:
        print()
        print("CheckUpgradeFile succeeded. Not committing.")
        print("Use `apply FILE.abc` or `apply --hash HASH` once you're ready "
              "to reboot.")
        return 0

    phase_apply(t,
                mode=apply_mode,
                file_hash=file_hash,
                file_hash_bytes=file_hash_bytes,
                key=key, authentication=None,
                reset_settings=reset_settings,
                timeout=verify_timeout)
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
        f"CRC mismatch in {label}. Use `build` or `flash --fix-crc` to "
        f"repair the image, or --force to proceed with the bad CRCs as-is.")


def _build_container(args, *,
                     target: TargetRegion | None = None,
                     detected_preset: str | None = None
                     ) -> tuple[bytes, TargetRegion, bytes]:
    """Assemble the .abc container"""

    if target is None:
        target = resolve_target_from_args(args)
    payload = load_payload(args, target)
    payload = check_and_maybe_fix_hw_crcs(
        payload, target,
        fix=getattr(args, "fix_crc", False),
        force=getattr(args, "force", False))

    (conf_appl_compatibility_fingerprint,
     fgbl_appl_compatibility_fingerprint,
     fg_security_fingerprint) = resolve_descriptor_fingerprints(
         args, target, detected_preset=detected_preset)
    abc = build_0005(
        target, payload,
        conf_appl_compatibility_fingerprint=conf_appl_compatibility_fingerprint,
        fgbl_appl_compatibility_fingerprint=fgbl_appl_compatibility_fingerprint,
        fg_security_fingerprint=fg_security_fingerprint,
    )
    return abc, target, FORMAT_0005


def build_container_with_live_defaults(args, t: Transport,
                                       target: TargetRegion
                                       ) -> tuple[bytes, TargetRegion, bytes]:
    need_detect = (args.fingerprint_preset == "auto"
                   and _auto_preset_needed(args, target))
    fg_security_fetch_needed = args.fg_security_fingerprint is None

    detected_preset = None
    if need_detect:
        detected_preset = detect_compatibility_fingerprint_preset(t)

    if fg_security_fetch_needed:
        print("[auto] querying device _SBA and _SKF...")
        fingerprint = fetch_fg_security_fingerprint(t)
        if fingerprint is None:
            raise SystemExit(
                "could not resolve the device FG security fingerprint; "
                "pass --fg-security-fingerprint explicitly")
        print("[auto] using FG security fingerprint "
              f"0x{fingerprint:08X} in descriptor")
        args.fg_security_fingerprint = f"0x{fingerprint:08X}"

    abc, target, fmt = _build_container(
        args, target=target, detected_preset=detected_preset)
    print(f"Built {fmt.decode('ascii')} container for {target.code}  "
          f"({target.flash_start:#010x}..{target.flash_end:#010x}, "
          f"{len(abc)} bytes)")
    return abc, target, fmt


def cmd_targets(_args) -> int:
    print(f"{'Input':30s} {'Target':6s} {'Range':26s} {'Size':>12s}")
    for source_set, code in TARGET_BY_SOURCE_SET.items():
        source = firmware_source_set_label(source_set)
        t = TARGETS[code]
        flag = ""
        if t.danger_flag:
            option = t.danger_flag.replace("_", "-")
            flag = f"  (flash needs --{option})"
        print(f"{source:30s} {code:6s} "
              f"{t.flash_start:#010x}..{t.flash_end:#010x}  "
              f"{t.size:>10d} B{flag}")
    t = TARGETS["FGCB"]
    print(f"{'--full + --include-bootloader':30s} {'FGCB':6s} "
          f"{t.flash_start:#010x}..{t.flash_end:#010x}  "
          f"{t.size:>10d} B")
    return 0


def _prepare_service_flash(args) -> tuple[TargetRegion, bytes]:
    target = resolve_target_from_args(args)
    check_danger_ack(args, target)
    payload = load_payload(args, target)
    payload = check_and_maybe_fix_hw_crcs(
        payload, target,
        fix=args.fix_crc,
        force=args.force,
        label="firmware image",
    )
    return target, payload


def _connect_service_or_enter(args, *, entry_timeout: float):
    client, transport = build_service_client(args)
    try:
        info = client.info(timeout=min(args.timeout, 1.0))
    except (TimeoutError, TransportError) as exc:
        log.debug("service INFO probe failed: %s", exc)
        transport.close()
        client, transport = build_service_client(args)
        try:
            _service_enter(client, transport, entry_timeout=entry_timeout)
        except Exception:
            transport.close()
            raise
    else:
        print("Service mode already active.")
        _print_service_identity(info)
    return client, transport


def cmd_service(args) -> int:
    service_flash = None
    if args.service_cmd == "flash":
        service_flash = _prepare_service_flash(args)

    if args.service_cmd in ("enter", "flash"):
        entry_timeout = args.timeout if args.service_cmd == "enter" else 30.0
        client, transport = _connect_service_or_enter(
            args, entry_timeout=entry_timeout
        )
    else:
        client, transport = build_service_client(args)
    try:
        if args.service_cmd == "info":
            info = client.info(timeout=args.timeout)
            _print_service_identity(info)
            return 0

        if args.service_cmd == "enter":
            return 0

        if args.service_cmd == "flash":
            from as11_service import MAX_WRITE_DATA

            target_region, payload = service_flash
            (service_target, _target_name, target_start, target_size,
             erase_size, program_size) = _service_storage("flash")
            _service_write(
                client, service_target, target_region.code,
                target_region.flash_start, target_region.size,
                payload,
                target_start=target_start,
                target_size=target_size,
                erase_size=erase_size,
                program_size=program_size,
                max_write_data=MAX_WRITE_DATA,
                timeout=args.timeout,
            )
            client.reset(timeout=args.timeout)
            time.sleep(0.1)
            print("Reset requested.")
            return 0

        if args.service_cmd == "reset":
            client.reset(timeout=args.timeout)
            print("Reset requested.")
            return 0

        if args.service_cmd in ("read-flash", "read-nor", "read-bkpsram"):
            (target, target_name, offset, length, _target_start, _target_size,
             _erase_size, _program_size) = _service_range(
                args.service_cmd.removeprefix("read-"), args.selection
            )
            _service_read_to_file(
                client, target, target_name, offset, length,
                Path(args.file), timeout=args.timeout,
            )
            return 0

        if args.service_cmd in ("write-flash", "write-nor", "write-bkpsram"):
            from as11_service import MAX_WRITE_DATA

            (target, target_name, offset, length, target_start, target_size,
             erase_size, program_size) = _service_range(
                args.service_cmd.removeprefix("write-"), args.selection
            )

            _service_write(
                client, target, target_name, offset, length,
                Path(args.file), target_start=target_start,
                target_size=target_size, erase_size=erase_size,
                program_size=program_size,
                max_write_data=MAX_WRITE_DATA,
                timeout=args.timeout,
            )
            return 0

        raise SystemExit(f"unknown service command {args.service_cmd!r}")
    finally:
        transport.close()


def _print_service_identity(info) -> None:
    version = ".".join(str(part) for part in info.service_version)
    print(f"Service: {version}")
    print(f"FGBL:    {info.fgbl_build_id}")


def _service_enter(client, transport, *, entry_timeout: float) -> None:
    from as11_can_common import CanTxBufferFull

    if not hasattr(client, "raw_can"):
        info = client.enter(timeout=entry_timeout + 5.0)
        _print_service_identity(info)
        return

    request = build_request(
        "ResetDevice", {"type": "Fast"},
        int(time.time() * 1000) & 0x7FFFFFFF,
    )
    try:
        transport.send_payload(request)
    except CanTxBufferFull:
        pass
    else:
        print("ResetDevice(Fast) sent.")

    burst_frame = b"\x00" * 8
    def burst(duration):
        deadline = time.monotonic() + duration
        while time.monotonic() < deadline:
            try:
                client.raw_can.send_frame(
                    0x7FF, burst_frame, extended=False, remote=False
                )
            except CanTxBufferFull:
                time.sleep(0.001)
                continue
            time.sleep(0.0005)

    print(f"CAN entry burst (up to {entry_timeout:g} s)...")
    info = client.info_during_activity(burst, timeout=entry_timeout)
    _print_service_identity(info)


def _service_read_to_file(client, target: int, target_name: str,
                          offset: int, length: int, output: Path, *,
                          timeout: float) -> None:
    done = 0
    started = time.monotonic()
    next_report = started + 1.0

    print(
        f"\rREAD {target_name}: 0/{length} bytes (  0.0%, 0 B/s)",
        end="",
        file=sys.stderr,
        flush=True,
    )

    with output.open("wb") as stream:
        for chunk in client.iter_read(
                target, offset, length, timeout=timeout):
            stream.write(chunk)
            done += len(chunk)
            now = time.monotonic()
            if done == length or now >= next_report:
                elapsed = max(now - started, 0.001)
                print(
                    f"\rREAD {target_name}: {done}/{length} bytes "
                    f"({done * 100.0 / length:5.1f}%, "
                    f"{done / elapsed:.0f} B/s)",
                    end="" if done != length else "\n",
                    file=sys.stderr,
                    flush=True,
                )
                next_report = now + 1.0

    elapsed = max(time.monotonic() - started, 0.001)
    print(
        f"Saved {length} bytes from {target_name} "
        f"0x{offset:08X} to {output} ({length / elapsed:.0f} B/s)"
    )


def _service_write(client, target: int, target_name: str,
                   offset: int, length: int, input_source: Path | bytes, *,
                   target_start: int, target_size: int,
                   erase_size: int, program_size: int,
                   max_write_data: int, timeout: float) -> None:
    if isinstance(input_source, bytes):
        input_size = len(input_source)
        input_label = "firmware image"
        stream = io.BytesIO(input_source)
    else:
        if not input_source.is_file():
            raise SystemExit(f"write input is not a file: {input_source}")
        input_size = input_source.stat().st_size
        input_label = str(input_source)
        stream = input_source.open("rb")
    if input_size == length:
        input_offset = 0
    elif input_size == target_size:
        input_offset = offset - target_start
    else:
        raise SystemExit(
            f"{target_name} write requires a {length}-byte range image or a "
            f"{target_size}-byte complete target image; {input_label} has "
            f"{input_size} bytes"
        )
    if erase_size and (offset % erase_size or length % erase_size):
        raise SystemExit(
            f"{target_name} write range must be aligned to the "
            f"{erase_size}-byte erase unit"
        )
    chunk_size = max_write_data - (max_write_data % program_size)
    if chunk_size <= 0:
        raise SystemExit(
            f"service write limit {max_write_data} is smaller than "
            f"the {target_name} program unit {program_size}"
        )

    done = 0
    started = time.monotonic()
    next_report = started
    unit_size = erase_size or length
    sector_count = length // unit_size
    status_width = 0

    def report_progress(detail: str, *, final: bool = False) -> None:
        nonlocal status_width
        elapsed = max(time.monotonic() - started, 0.001)
        line = (
            f"WRITE {target_name}: {done}/{length} bytes "
            f"({done * 100.0 / length:5.1f}%, {done / elapsed:.0f} B/s; "
            f"{detail})"
        )
        status_width = max(status_width, len(line))
        print(
            f"\r{line:<{status_width}}",
            end="\n" if final else "",
            file=sys.stderr,
            flush=True,
        )

    with stream:
        stream.seek(input_offset)
        for sector_relative in range(0, length, unit_size):
            sector_length = unit_size
            sector_offset = offset + sector_relative
            if erase_size:
                sector_index = sector_relative // unit_size + 1
                report_progress(
                    f"erasing sector {sector_index}/{sector_count}"
                )
                client.erase(
                    target, sector_offset, sector_length, timeout=timeout
                )
            sector_done = 0
            while sector_done < sector_length:
                write_length = min(chunk_size, sector_length - sector_done)
                if write_length % program_size:
                    raise SystemExit(
                        f"{target_name} write tail is not aligned to "
                        f"the {program_size}-byte program unit"
                    )
                data = stream.read(write_length)
                if len(data) != write_length:
                    raise SystemExit(
                        f"write input ended at "
                        f"{sector_relative + sector_done} bytes"
                    )
                client.write(
                    target, sector_offset + sector_done, data,
                    timeout=timeout,
                )
                sector_done += write_length
                done = sector_relative + sector_done
                now = time.monotonic()
                if now >= next_report or done == length:
                    report_progress("programming", final=done == length)
                    next_report = now + 1.0

    elapsed = max(time.monotonic() - started, 0.001)
    print(
        f"Wrote {length} bytes to {target_name} at 0x{offset:08X} "
        f"({length / elapsed:.0f} B/s)"
    )


def cmd_build(args) -> int:
    # auto-detect is a runtime (device-query) concept and doesn't apply to
    # offline builds. Error early if the target actually needs a preset.
    tgt = resolve_target_from_args(args)
    if args.fingerprint_preset == "auto" and _auto_preset_needed(args, tgt):
        known = "/".join(sorted(COMPATIBILITY_FINGERPRINT_PRESETS))
        raise SystemExit(
            f"{tgt.code} needs compatibility fingerprints, and `build` "
            f"can't query a device. Pass --fingerprint-preset {known} or explicit "
            "compatibility fingerprints, or use `flash` for auto-detection.")
    abc, target, fmt = _build_container(args, target=tgt)
    out = Path(args.output)
    out.write_bytes(abc)
    print(f"Wrote {out} ({len(abc)} bytes, format {fmt.decode('ascii')}, "
          f"target {target.code})")
    print_info(inspect_container(abc))
    return 0


def cmd_info(args) -> int:
    _data, info = read_container(args.file)
    print_info(info, path=args.file)
    return 0


def read_container(path: str) -> tuple[bytes, dict]:
    try:
        data = Path(path).read_bytes()
    except OSError as exc:
        raise SystemExit(f"{path}: {exc}") from exc
    try:
        return data, inspect_container(data)
    except ValueError as exc:
        raise SystemExit(f"{path}: {exc}") from exc


def detect_compatibility_fingerprint_preset(t: Transport) -> str:
    """Map the device's ApplicationIdentifier to a reviewed preset."""
    print("[auto] querying device firmware version...")
    detected = fetch_firmware_version(t)
    if detected is None:
        raise SystemExit(
            "auto-detect failed: device didn't return ApplicationIdentifier. "
            "Pass --fingerprint-preset or explicit compatibility fingerprints.")
    if detected not in COMPATIBILITY_FINGERPRINT_PRESETS:
        known = ", ".join(sorted(COMPATIBILITY_FINGERPRINT_PRESETS))
        raise SystemExit(
            f"device reports firmware {detected!r} which isn't in "
            f"the compatibility presets ({known}). Pass explicit "
            "compatibility fingerprints or add a reviewed preset; see "
            "docs/as11/ota_protocol.md.")
    print(f"[auto] device reports {detected}; using matching preset")
    return detected


def _upload_kwargs_from_args(args, *,
                             apply_mode: ApplyMode | None = None,
                             default_apply_mode: ApplyMode = APPLY_NONE
                             ) -> dict:
    """Build the keyword args to run_upload() from parsed CLI args."""
    if apply_mode is None:
        apply_mode = resolve_apply_mode(args, default=default_apply_mode)
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
        verify_timeout=args.verify_timeout,
    )


def parse_sha256_arg(value: str, option: str) -> tuple[str, bytes]:
    clean = (value or "").strip()
    if re.fullmatch(r"[0-9A-Fa-f]{64}", clean) is None:
        raise SystemExit(f"{option} must be exactly 64 hex chars")
    raw = bytes.fromhex(clean)
    return clean.upper(), raw


def apply_hash_from_args(args) -> tuple[str, bytes]:
    has_abc_file = bool(getattr(args, "file", None))
    has_hash = bool(getattr(args, "hash", None))
    if has_abc_file == has_hash:
        raise SystemExit("pass either an .abc file or --hash")
    if has_hash:
        return parse_sha256_arg(args.hash, "--hash")

    data, _info = read_container(args.file)
    digest = hashlib.sha256(data).digest()
    return digest.hex().upper(), digest


def _apply_kwargs_from_args(args, *,
                            apply_mode: ApplyMode | None = None) -> dict:
    if apply_mode is None:
        apply_mode = resolved_apply_mode_for_command(args)
    authentication = None
    if apply_mode == APPLY_AUTHENTICATED:
        if getattr(args, "authentication", None):
            if getattr(args, "key", None) or getattr(args, "key_file", None):
                raise SystemExit(
                    "--authentication cannot be combined with --key or --key-file")
            authentication, _ = parse_sha256_arg(
                args.authentication, "--authentication")
            key = b""
        else:
            key = parse_key(getattr(args, "key", None),
                            getattr(args, "key_file", None),
                            stored_key=stored_ota_key_for_device(args))
    else:
        key = b""
    return dict(
        mode=apply_mode,
        key=key,
        authentication=authentication,
        reset_settings=bool(getattr(args, "reset_settings", False)),
        timeout=LONG_RPC_TIMEOUT,
    )


def cmd_apply(args) -> int:
    file_hash, file_hash_bytes = apply_hash_from_args(args)
    apply_mode = resolved_apply_mode_for_command(args)
    kwargs = _apply_kwargs_from_args(args, apply_mode=apply_mode)

    t = build_transport_for_flash(args)
    with t:
        phase_apply(t,
                    file_hash=file_hash,
                    file_hash_bytes=file_hash_bytes,
                    **kwargs)
    return 0


def cmd_upload(args) -> int:
    resolve_apply_mode(args)

    abc, info = read_container(args.file)
    path = args.file

    if not info["magic_ok"]:
        raise SystemExit(f"{path}: bad magic {info['magic']!r}, "
                         f"expected {MAGIC!r}")
    def _soft(msg: str) -> None:
        if args.force:
            log.warning("ignoring: %s (--force)", msg)
        else:
            raise SystemExit(
                f"{path}: {msg} (pass --force to upload anyway)")

    if info["component"] != DEFAULT_COMPONENT_0005:
        _soft(f"unknown component string {info['component']!r}; "
              f"expected {DEFAULT_COMPONENT_0005!r}")

    if info.get("code") not in TARGETS:
        _soft(f"0005 descriptor code {info.get('code')!r} not in "
              f"TARGETS ({sorted(TARGETS)})")
    if info.get("marker") != 1:
        _soft(f"0005 descriptor marker={info.get('marker')} "
              f"(verifier requires 1)")
    if not 1 <= info.get("segment_count", 0) <= 0xFF:
        _soft(f"0005 descriptor segment_count={info.get('segment_count')} "
              f"(bootloader requires 1..255)")
    if not info.get("segment_table_ok", False):
        _soft("0005 segment table is missing or truncated")
    if not info.get("segment_data_len_ok", False):
        _soft("0005 segment data length doesn't match the descriptor segment table")

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

    if not info.get("payload_len_ok", True):
        _soft("descriptor rest length field doesn't match actual payload size")
    if not info.get("payload_crc_ok", True):
        _soft("descriptor rest CRC mismatch")
    if not info.get("descriptor_crc_ok", True):
        _soft("descriptor CRC mismatch")

    # HW-region CRC check inside the target image bytes.
    target_slice = target_payload_slice(info)
    if target_slice is not None:
        off, size = target_slice
        payload = abc[off:off + size]
    else:
        payload = None

    if target is not None and payload is not None:
        check_and_maybe_fix_hw_crcs(
            payload, target,
            fix=False, force=args.force,
            label=f"{args.file} target image")

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
    target = resolve_target_from_args(args)
    check_danger_ack(args, target)

    if args.dry_run:
        # dry-run can't query the device, so auto-detect isn't possible.
        if (args.fingerprint_preset == "auto"
                and _auto_preset_needed(args, target)):
            known = "/".join(sorted(COMPATIBILITY_FINGERPRINT_PRESETS))
            raise SystemExit(
                f"--dry-run can't query the device. For auto-detect, remove "
                f"--dry-run, or pass --fingerprint-preset {known} or explicit "
                "compatibility fingerprints.")
        abc, _, fmt = _build_container(args, target=target)
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
    apply_mode = resolved_apply_mode_for_command(args)
    upload_kwargs = _upload_kwargs_from_args(args, apply_mode=apply_mode)

    t = build_transport_for_flash(args)
    try:
        abc, _, _ = build_container_with_live_defaults(args, t, target)
        if args.save_abc:
            Path(args.save_abc).write_bytes(abc)
            print(f"Saved built container to {args.save_abc}")

        return run_upload(t, abc, **upload_kwargs)
    finally:
        t.close()



def _add_input_args(p: argparse.ArgumentParser) -> None:
    """Firmware sources. Their combination determines the OTA target."""
    p.add_argument("--fgbl", metavar="PATH",
                   help="FGBL source: raw region or full 2 MiB image")
    p.add_argument("--conf", metavar="PATH",
                   help="CONF source: raw region or full 2 MiB image")
    p.add_argument("--appl", metavar="PATH",
                   help="APPL source: raw region or full 2 MiB image")
    p.add_argument("-f", "--full", metavar="PATH",
                   help="complete 2 MiB internal image")


def _add_build_args(p: argparse.ArgumentParser) -> None:
    """Descriptor and image-validation options."""
    # 0005 descriptor knobs
    p.add_argument("--fingerprint-preset", default="auto",
                   choices=(["auto"] +
                            sorted(COMPATIBILITY_FINGERPRINT_PRESETS) +
                            ["none"]),
                   help="fill compatibility fingerprints from a known firmware "
                        "preset (default: auto). With `auto`, `flash` queries "
                        "the device's ApplicationIdentifier and matches it to "
                        "the preset table; `build` requires an explicit version.")
    p.add_argument("--conf-appl-fingerprint",
                   dest="conf_appl_compatibility_fingerprint", metavar="U32",
                   help="override the CONF/APPL compatibility fingerprint")
    p.add_argument("--fgbl-appl-fingerprint",
                   dest="fgbl_appl_compatibility_fingerprint", metavar="U32",
                   help="override the FGBL/APPL compatibility fingerprint")
    p.add_argument("--fg-security-fingerprint", default=None, metavar="U32",
                   help="override the FG security fingerprint normally "
                        "resolved from _SBA and _SKF; offline build defaults "
                        "to 0")
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
                   help="send resetSettingsToDefault=true with plain ApplyUpgrade "
                        "(default sends false to preserve settings)")
    p.add_argument("--key", metavar="HEX64",
                   help="K_ota as 64 hex chars")
    p.add_argument("--key-file", metavar="PATH",
                   help="K_ota as a 32-byte binary file or a hex-text file")
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


def _add_apply_args(p: argparse.ArgumentParser) -> None:
    """Apply-only options."""
    p.add_argument("--apply", action="store_true",
                   help="call ApplyAuthenticatedUpgrade (uses --key, "
                        "AS11_OTA_KEY, or stored BLE otaKey)")
    p.add_argument("--apply-authenticated", action="store_true",
                   help="synonym for --apply")
    p.add_argument("--apply-plain", action="store_true",
                   help="call unauthenticated ApplyUpgrade")
    p.add_argument("--reset-settings", action="store_true",
                   help="send resetSettingsToDefault=true with plain ApplyUpgrade "
                        "(default sends false to preserve settings)")
    p.add_argument("--key", metavar="HEX64",
                   help="K_ota as 64 hex chars")
    p.add_argument("--key-file", metavar="PATH",
                   help="K_ota as a 32-byte binary file or a hex-text file")
    p.add_argument("--authentication", metavar="HEX64",
                   help="precomputed ApplyAuthenticatedUpgrade authentication; "
                        "implies authenticated apply")


def _add_debug_arg(p: argparse.ArgumentParser) -> None:
    p.add_argument("--debug", action="store_true", default=argparse.SUPPRESS,
                   help="verbose transport-level packet logging")


def _add_device_args(p: argparse.ArgumentParser, *, show_help: bool = True) -> None:
    """Device-selection args, matching as11_config.py conventions."""
    suppr = argparse.SUPPRESS
    _add_debug_arg(p)
    g = p.add_argument_group("device selection")
    g.add_argument("-d", "--device", default=suppr,
                   help=("device spec: ble:<mac|alias>, can:<port>, "
                         "tcp:<host>[:<port>]") if show_help else suppr)
    g.add_argument("--addr", default=suppr,
                   help=("BLE target (compat for -d ble:<x>; env: AS11_ADDR)"
                         if show_help else suppr))
    g.add_argument("-p", "--port", default=suppr,
                   help=("CAN target (compat for -d can:<x>; "
                         "env: AS11_CAN_PORT)" if show_help else suppr))
    if _can_transport is not None:
        _can_transport.add_args(p, show_help=show_help)
    if _aircannect_transport is not None:
        _aircannect_transport.add_args(p)


def _service_u32(text: str) -> int:
    try:
        value = int(text.replace("_", ""), 0)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid integer {text!r}") from exc
    if not 0 <= value <= 0xFFFFFFFF:
        raise argparse.ArgumentTypeError("value must be in range 0..0xffffffff")
    return value


def _service_length(text: str) -> int:
    value = _service_u32(text)
    if value == 0:
        raise argparse.ArgumentTypeError("length must be positive")
    return value


def _service_block_size(text: str) -> int:
    try:
        value = int(text, 0)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid block size {text!r}") from exc
    if not 0 <= value <= 0xFF:
        raise argparse.ArgumentTypeError("block size must be in range 0..255")
    return value


def _service_timeout(text: str) -> float:
    try:
        value = float(text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid timeout {text!r}") from exc
    if value <= 0:
        raise argparse.ArgumentTypeError("timeout must be positive")
    return value


def _add_service_link_args(p: argparse.ArgumentParser, *, defaults: bool,
                           timeout_help: str =
                           "service response timeout (default: 5)") -> None:
    p.add_argument(
        "--timeout", type=_service_timeout,
        default=None if defaults else argparse.SUPPRESS,
        metavar="SECONDS", help=timeout_help,
    )
    p.add_argument(
        "--block-size", type=_service_block_size,
        default=None if defaults else argparse.SUPPRESS,
        metavar="FRAMES",
        help="direct CAN receive block size, 0 for unlimited (default: 255)",
    )


def main(argv=None) -> int:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(name)s %(levelname)s %(message)s")

    ap = argparse.ArgumentParser(
        description="Air11 firmware upgrade and service tool.")
    _add_device_args(ap)
    sub = ap.add_subparsers(dest="cmd", required=True)

    # targets
    p_t = sub.add_parser(
        "targets", help="list base firmware input combinations")
    _add_debug_arg(p_t)
    p_t.set_defaults(func=cmd_targets)

    # build
    p_b = sub.add_parser("build", help="build an .abc container locally")
    _add_debug_arg(p_b)
    _add_input_args(p_b)
    p_b.add_argument("--block", metavar="NAME",
                     help="select CONF, APPL, APCX, FGBL, or FGCB from the "
                          "supplied firmware regions")
    _add_build_args(p_b)
    p_b.add_argument("-o", "--output", required=True,
                     help="output .abc path")
    p_b.add_argument("--force", action="store_true",
                     help=_FORCE_HELP)
    p_b.set_defaults(func=cmd_build)

    # info
    p_i = sub.add_parser("info", help="inspect an .abc container")
    _add_debug_arg(p_i)
    p_i.add_argument("file", help=".abc file to inspect")
    p_i.set_defaults(func=cmd_info)

    # upload
    p_u = sub.add_parser("upload",
                         help="push a pre-built .abc; CheckUpgradeFile only "
                              "unless an apply mode is selected")
    _add_device_args(p_u, show_help=False)
    p_u.add_argument("file", help=".abc file to upload")
    _add_upload_args(p_u)
    p_u.set_defaults(func=cmd_upload)

    # apply only
    p_a = sub.add_parser("apply",
                         help="apply a previously uploaded and verified .abc")
    _add_device_args(p_a, show_help=False)
    p_a.add_argument("file", nargs="?", metavar="ABC",
                     help="matching .abc file; SHA-256 is computed locally")
    p_a.add_argument("--hash", metavar="HEX64",
                     help="SHA-256 reported by the earlier upload/flash run")
    _add_apply_args(p_a)
    p_a.set_defaults(func=cmd_apply)

    # flash (build + upload)
    p_f = sub.add_parser("flash",
                         help="build .abc from firmware and upload in one step; "
                               "applies by default (BLE authenticated, "
                              "CAN/TCP plain)")
    _add_device_args(p_f, show_help=False)
    _add_input_args(p_f)
    p_f.add_argument("--block", metavar="NAME",
                     help="select CONF, APPL, APCX, FGBL, or FGCB from the "
                          "supplied firmware regions")
    _add_build_args(p_f)
    p_f.add_argument("--include-bootloader", action="store_true",
                     help="include FGBL; with --full and no --block, select "
                          "the complete FGCB target")
    p_f.add_argument("--save-abc", metavar="PATH",
                     help="also write the built .abc to this path")
    _add_upload_args(p_f)
    p_f.set_defaults(func=cmd_flash)

    # Bootloader service mode
    p_s = sub.add_parser(
        "service", help="communicate with the bootloader service"
    )
    _add_device_args(p_s, show_help=False)
    _add_service_link_args(p_s, defaults=True)
    service_sub = p_s.add_subparsers(dest="service_cmd", required=True)

    p_s_info = service_sub.add_parser("info", help="query service identity")
    _add_device_args(p_s_info, show_help=False)
    _add_service_link_args(p_s_info, defaults=False)

    p_s_enter = service_sub.add_parser(
        "enter", help="enter service mode during a reset"
    )
    _add_device_args(p_s_enter, show_help=False)
    _add_service_link_args(
        p_s_enter, defaults=False,
        timeout_help="CAN entry window (default: 30)",
    )
    p_s_reset = service_sub.add_parser("reset", help="leave service mode and reset")
    _add_device_args(p_s_reset, show_help=False)
    _add_service_link_args(p_s_reset, defaults=False)

    p_s_flash = service_sub.add_parser(
        "flash", help="enter service mode, program firmware, and reset"
    )
    _add_device_args(p_s_flash, show_help=False)
    _add_service_link_args(p_s_flash, defaults=False)
    _add_input_args(p_s_flash)
    p_s_flash.add_argument(
        "--block", metavar="NAME",
        help="select CONF, APPL, APCX, FGBL, or FGCB from the supplied "
             "firmware regions",
    )
    p_s_flash.add_argument(
        "--include-bootloader", action="store_true",
        help="include FGBL; with --full and no --block, select the complete "
             "FGCB target",
    )
    p_s_flash.add_argument(
        "--fix-crc", action="store_true",
        help="recompute and patch CRC16-CCITT footers in memory before "
             "programming",
    )
    p_s_flash.add_argument(
        "--force", action="store_true",
        help="override local image validation failures",
    )

    for command, selection_help in (
            ("read-flash", "optional REGION or absolute OFFSET LENGTH"),
            ("read-nor", "optional physical OFFSET LENGTH"),
            ("read-bkpsram", "optional OFFSET LENGTH")):
        p_s_read = service_sub.add_parser(
            command, help="read storage to a raw file"
        )
        _add_device_args(p_s_read, show_help=False)
        _add_service_link_args(p_s_read, defaults=False)
        p_s_read.add_argument("file", help="output file")
        p_s_read.add_argument(
            "selection", nargs="*", metavar="RANGE",
            help=f"{selection_help}; omit for the complete target",
        )

    for command, selection_help in (
            ("write-flash", "optional REGION or absolute OFFSET LENGTH"),
            ("write-nor", "optional physical OFFSET LENGTH"),
            ("write-bkpsram", "optional OFFSET LENGTH")):
        p_s_write = service_sub.add_parser(
            command, help="write storage from a raw file"
        )
        _add_device_args(p_s_write, show_help=False)
        _add_service_link_args(p_s_write, defaults=False)
        p_s_write.add_argument("file", help="input file")
        p_s_write.add_argument(
            "selection", nargs="*", metavar="RANGE",
            help=f"{selection_help}; omit for the complete target",
        )
    p_s.set_defaults(func=cmd_service)

    args = ap.parse_args(argv)
    _explicit_device_spec(args)
    if args.cmd == "service" and args.timeout is None:
        args.timeout = 30.0 if args.service_cmd == "enter" else 5.0
    if getattr(args, "debug", False):
        logging.getLogger().setLevel(logging.DEBUG)

    validate_reset_settings(args)
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
    except OSError as e:
        print(f"\nerror: {e}", file=sys.stderr)
        sys.exit(1)
    except RuntimeError as e:
        if str(e).startswith("RPC error "):
            print(f"\n{e}", file=sys.stderr)
            sys.exit(1)
        raise
    except Exception as e:
        log.exception("fatal: %s", e)
        sys.exit(1)

"""Image-scoped decoding for AS11 diagnostic exception records."""

from __future__ import annotations

from collections import Counter
from functools import lru_cache
import gzip
import json
from pathlib import Path
import re


MANIFEST_SCHEMA = "as11-diagnostic-error-manifest-v4"
MANIFEST_DIR = Path(__file__).with_name("data") / "diagnostic_errors"

SELECTOR_BY_SPOOL = {
    "DiagnosticExceptionEvents-AlarmAppErrors": "APE",
    "DiagnosticExceptionEvents-AppErrors": "AEE",
    "DiagnosticExceptionEvents-FatalErrors": "FAE",
    "DiagnosticExceptionEvents-ResettableErrors": "SRE",
}

FS_API_OPERATIONS = {
    1187: "fopen",
    1278: "fread",
    1357: "fseek",
    1801: "fwrite",
    1832: "close",
}


def normalize_app_version(value: str | None) -> str | None:
    """Extract APPX release/hash from an ApplicationIdentifier-like value."""
    if value is None:
        return None
    parts = str(value).strip().split(".")
    if len(parts) >= 4 and re.fullmatch(r"[0-9a-fA-F]{7,}", parts[-1]):
        candidate = ".".join(parts[-4:])
    elif len(parts) >= 3:
        candidate = ".".join(parts[-3:])
    else:
        return None
    if not re.fullmatch(
            r"\d+\.\d+\.\d+(?:\.[0-9a-fA-F]{7,})?", candidate):
        return None
    return candidate.lower()


def _release(version: str) -> str:
    return ".".join(version.split(".")[:3])


@lru_cache(maxsize=1)
def diagnostic_manifests() -> dict[str, dict]:
    """Load bundled manifests keyed by exact APPX version."""
    manifests = {}
    if not MANIFEST_DIR.is_dir():
        return manifests
    for path in sorted(MANIFEST_DIR.glob("*.json.gz")):
        with gzip.open(path, "rt", encoding="ascii") as src:
            manifest = json.load(src)
        if manifest.get("schema") != MANIFEST_SCHEMA:
            raise ValueError(
                f"{path}: expected {MANIFEST_SCHEMA}, "
                f"got {manifest.get('schema')!r}"
            )
        version = normalize_app_version(
            manifest.get("firmware", {}).get("appx_version")
        )
        if version is None:
            raise ValueError(f"{path}: invalid APPX version")
        if version in manifests:
            raise ValueError(f"duplicate diagnostic manifest for {version}")
        manifests[version] = manifest
    return manifests


def _selected_manifests(app_version: str | None) -> list[tuple[str, dict]]:
    manifests = diagnostic_manifests()
    if app_version is None:
        return sorted(manifests.items())
    normalized = normalize_app_version(app_version)
    if normalized is None:
        return []
    if normalized in manifests:
        return [(normalized, manifests[normalized])]
    release = _release(normalized)
    return [
        (version, manifest)
        for version, manifest in sorted(manifests.items())
        if _release(version) == release
    ]


def _signed(value: int, bits: int) -> int:
    mask = (1 << bits) - 1
    value &= mask
    sign = 1 << (bits - 1)
    return value - (1 << bits) if value & sign else value


def _decode_dynamic_mapper(code: int, mapper: dict) -> list[dict]:
    bits = mapper["input"]["bits"]
    threshold = mapper["condition"]["value"]
    transform = mapper["transform"]
    candidates = []
    if code == mapper["overflow_code"]:
        candidates.append({
            "kind": "dynamic_status_overflow",
            "status_min": threshold,
            "status_max": (1 << (bits - 1)) - 1,
            "callers": mapper["callers"],
        })
    status = _signed(code - transform["addend"], bits)
    if status < threshold:
        candidates.append({
            "kind": "dynamic_status",
            "status": status,
            "callers": mapper["callers"],
        })
    return candidates


def _decode_aee(section: dict, code: int) -> list[dict]:
    candidates = []
    for site in section["static_sites"]:
        if site["code"] == code:
            candidates.append({"kind": "static_site", **site})
    for site in section.get("special_sites", []):
        if site["code"] == code:
            candidates.append(dict(site))
    for mapper in section["dynamic_mappers"]:
        candidates.extend(_decode_dynamic_mapper(code, mapper))
    return candidates


def _decode_fae(section: dict, code: int) -> list[dict]:
    return [
        {"kind": "fatal_site", **site}
        for site in section["static_sites"]
        if site["code"] == code
    ]


def _decode_sre(section: dict, code: int) -> list[dict]:
    candidates = [
        dict(site) for site in section.get("direct_sites", [])
        if site["code"] == code
    ]
    for table in section["mapping"]["tables"]:
        for entry in table["entries"]:
            if entry["code"] == code:
                candidates.append({
                    "kind": "ps_transfer_status_group",
                    "bit_offset": table["bit_offset"],
                    "bit_width": table["bit_width"],
                    "priority": table["priority"],
                    "input_value": entry["input_value"],
                })
    return candidates


def _decode_ape(section: dict, code: int) -> list[dict]:
    if section.get("present") is False:
        return []
    return [{
        "kind": "raw_alarm_application_event_code",
        "message_type": section["source"]["message_type"],
        "field": section["source"]["field"],
        "code": code,
    }]


def _decode_section(selector: str, section: dict, code: int) -> list[dict]:
    if selector == "AEE":
        return _decode_aee(section, code)
    if selector == "FAE":
        return _decode_fae(section, code)
    if selector == "SRE":
        return _decode_sre(section, code)
    if selector == "APE":
        return _decode_ape(section, code)
    return []


def decode_diagnostic_code(spool_type: str, code: int,
                           app_version: str | None = None) -> dict:
    """Return every firmware-backed candidate for a diagnostic code."""
    selector = SELECTOR_BY_SPOOL.get(spool_type)
    rows = []
    selected = _selected_manifests(app_version)
    if selector is not None:
        for version, manifest in selected:
            section = manifest.get("selectors", {}).get(selector)
            if section is None or section.get("present") is False:
                continue
            rows.append({
                "version": version,
                "candidates": _decode_section(selector, section, code),
            })
    return {
        "selector": selector,
        "code": code,
        "requested_version": normalize_app_version(app_version),
        "selected_versions": [version for version, _manifest in selected],
        "versions": rows,
    }


def _source_location(candidate: dict) -> str | None:
    source = candidate.get("source_file")
    line = candidate.get("source_line")
    if source and line is not None:
        return f"{source}:{line}"
    return source


def _named_function(candidate: dict) -> str | None:
    name = candidate.get("function")
    if not name or name.startswith(("FUN_", "thunk_FUN_")):
        return None
    return name


def _backend_operations(candidate: dict) -> str:
    operations = []
    for caller in candidate.get("callers", []):
        operation = FS_API_OPERATIONS.get(caller.get("source_line"))
        if operation and operation not in operations:
            operations.append(operation)
    return ",".join(operations)


def _candidate_label(candidate: dict, *, details: bool) -> str:
    kind = candidate["kind"]
    if kind in ("static_site", "fatal_site"):
        prefix = "fatal" if kind == "fatal_site" else "direct"
        location = _source_location(candidate)
        function = _named_function(candidate)
        if location and function:
            label = f"{prefix} {location} ({function})"
        elif location:
            label = f"{prefix} {location}"
        elif function:
            label = f"{prefix} {function}"
        else:
            label = f"{prefix} application site"
        if details and candidate.get("callsite"):
            label += f" @{candidate['callsite']}"
        return label
    if kind == "event_flood_marker":
        return f"event flood marker {_source_location(candidate)}"
    if kind == "dynamic_status":
        operations = _backend_operations(candidate)
        suffix = f" via {operations}" if operations else ""
        return f"backend status {candidate['status']}{suffix}"
    if kind == "dynamic_status_overflow":
        return (
            f"backend status {candidate['status_min']}.."
            f"{candidate['status_max']}"
        )
    if kind == "direct_internal_code":
        function = _named_function(candidate)
        if candidate.get("static_linkage") == "no_function_xrefs":
            label = "direct writer with no static function xrefs"
        else:
            label = "direct internal producer"
        if function:
            label += f" ({function})"
        if details:
            label += f" @{candidate['producer_address']}"
        return label
    if kind == "ps_transfer_status_group":
        high = candidate["bit_offset"] + candidate["bit_width"] - 1
        return (
            f"PsTransfer status bits {candidate['bit_offset']}..{high} "
            f"value {candidate['input_value']}"
        )
    if kind == "raw_alarm_application_event_code":
        return "raw alarm-application EventCode"
    return kind


def _candidate_labels(candidates: list[dict], *, details: bool) -> tuple[str, ...]:
    labels = [_candidate_label(candidate, details=details)
              for candidate in candidates]
    counts = Counter(labels)
    ordered = []
    seen = set()
    for label in labels:
        if label in seen:
            continue
        seen.add(label)
        count = counts[label]
        ordered.append(f"{label} ({count} sites)" if count > 1 else label)
    return tuple(ordered)


def summarize_diagnostic_code(spool_type: str, code: int,
                              app_version: str | None = None,
                              *, details: bool = False) -> str:
    """Format candidate sources, retaining cross-version differences."""
    decoded = decode_diagnostic_code(spool_type, code, app_version)
    rows = decoded["versions"]
    if not rows:
        requested = decoded["requested_version"]
        if not decoded["selected_versions"]:
            return f"no manifest for {requested}" if requested else "no manifest"
        versions = "/".join(
            _release(version) for version in decoded["selected_versions"]
        )
        return f"selector absent in {versions}"

    grouped: dict[tuple[tuple[str, ...], bool], list[str]] = {}
    for row in rows:
        candidates = row["candidates"]
        labels = _candidate_labels(candidates, details=details)
        key = (labels, len(candidates) > 1)
        grouped.setdefault(key, []).append(_release(row["version"]))

    rendered = []
    show_versions = len(grouped) > 1
    for (labels, ambiguous), versions in grouped.items():
        value = "; ".join(labels) if labels else "not mapped"
        if ambiguous:
            value += " [ambiguous]"
        if show_versions:
            value = f"{'/'.join(versions)}: {value}"
        rendered.append(value)
    return " | ".join(rendered)


__all__ = [
    "SELECTOR_BY_SPOOL", "decode_diagnostic_code",
    "diagnostic_manifests", "normalize_app_version",
    "summarize_diagnostic_code",
]

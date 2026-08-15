#!/usr/bin/env python3

"""Prepare the version-specific inputs needed for a new Air11 APPX release."""

from __future__ import annotations

import argparse
from collections import defaultdict
from dataclasses import dataclass
import hashlib
from pathlib import Path
import re
import struct
import sys


PYTHON_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = PYTHON_DIR.parent
sys.path.insert(0, str(PYTHON_DIR))

from as11_descriptors import APPX_BASE, AS11Firmware, FLASH_BASE  # noqa: E402
from lib.as11_patch_versions import (  # noqa: E402
    AS11_OTA_DESCRIPTOR_PRESETS,
    AS11_PATCH_VERSIONS,
)


PATCHES_DIR = REPO_ROOT / "patches" / "as11"
MAKEFILE_PATH = REPO_ROOT / "Makefile.as11"
CODE_CAVES_PATH = REPO_ROOT / "patches" / "as11_code_caves.tsv"

STUB_RE = re.compile(
    r"^NSTUB\((0x[0-9A-Fa-f]+),\s*([A-Za-z_]\w*)\)\s*$",
    re.MULTILINE,
)


# Results retain both the selected value and the evidence used to select it.
# Generated files can therefore distinguish reviewed-looking candidates from
# unresolved addresses without silently promoting either to known metadata.
@dataclass(frozen=True)
class Identity:
    path: Path
    appx_version: str
    appx_key: str
    firmware_release: str
    application_id: str
    sha256: str
    appx_offset: int


@dataclass(frozen=True)
class RawCandidate:
    address: int
    score: int
    support: int
    widths: tuple[int, ...]


@dataclass(frozen=True)
class AddressResult:
    source_address: int
    address: int | None
    quality: str
    evidence: str
    alternatives: tuple[int, ...] = ()


@dataclass(frozen=True)
class MopCandidates:
    writeback: AddressResult
    vtable_slot: int | None
    pointer_refs: tuple[int, ...]


@dataclass
class HeaderClockCandidates:
    sites: dict[str, AddressResult]
    text_ids: dict[str, int | None]


@dataclass
class TimezoneWriteCandidates:
    sites: dict[str, AddressResult]


@dataclass
class CustomSettingsCandidates:
    sites: dict[str, AddressResult]
    row_constructor: AddressResult
    scheduler_target: AddressResult
    reference_reminders: dict


@dataclass(frozen=True)
class AsvCandidates:
    vtable_slot: int | None
    pointer_refs: tuple[int, ...]
    reference_label: str | None
    label_ids: tuple[int, ...]

    @property
    def label_id(self) -> int | None:
        return self.label_ids[0] if len(self.label_ids) == 1 else None


@dataclass(frozen=True)
class OtaDescriptorCandidates:
    table: AddressResult
    desc2: int | None
    desc3: int | None


@dataclass
class PortCandidates:
    stubs: dict[str, AddressResult]
    mop: MopCandidates
    timezone_write: TimezoneWriteCandidates
    header_clock: HeaderClockCandidates
    custom_settings: CustomSettingsCandidates
    asv: AsvCandidates
    ota_descriptor: OtaDescriptorCandidates


@dataclass(frozen=True)
class CandidateValue:
    value: object | None
    quality: str
    evidence: str = ""


@dataclass(frozen=True)
class SelfCheckItem:
    component: str
    status: str
    expected: object
    actual: object | None
    detail: str = ""


def appx_key(version: str) -> str:
    match = re.match(r"^(\d+)\.(\d+)\.(\d+)(?:\.|$)", version)
    if match is None:
        raise ValueError("cannot derive APPX key from %r" % version)
    return "_".join(match.groups())


def image_identity(path: Path, fw: AS11Firmware) -> Identity:
    records = {record["kind"]: record for record in fw.version_records()}
    appx = records.get("appx")
    conf = records.get("conf")
    if appx is None or conf is None or "offset" not in appx:
        raise ValueError("firmware does not contain a located APPX identity")

    release = "%d.%s" % (
        conf["data_version"], ".".join(appx["version"].split(".")[:3])
    )
    return Identity(
        path=path,
        appx_version=appx["version"],
        appx_key=appx_key(appx["version"]),
        firmware_release=release,
        application_id=appx["identifier"],
        sha256=hashlib.sha256(fw.data).hexdigest(),
        appx_offset=appx["offset"],
    )


def parse_stubs(version_key: str) -> dict[str, int]:
    path = PATCHES_DIR / ("stubs_%s.S" % version_key)
    if not path.is_file():
        raise ValueError("reference stubs do not exist: %s" % path)
    stubs = {
        name: int(address, 16)
        for address, name in STUB_RE.findall(path.read_text(encoding="ascii"))
    }
    if not stubs:
        raise ValueError("no NSTUB definitions found in %s" % path)
    return stubs


class AddressMatcher:
    """Transfer source addresses through unchanged code and data islands.

    Windows before and after a source address independently vote for a target
    address. This tolerates changed literals and inserted code while rewarding
    a consistent local layout. ``site`` returns the voted instruction/data
    location; ``function`` additionally tries to recover the function entry.

    A ``strong`` result means that the automated evidence met this tool's
    threshold. It is still a candidate until reviewed against the target image.
    """

    WIDTHS = ((48, 8), (32, 6), (24, 5), (16, 3), (12, 2))

    def __init__(self, source: bytes, target: bytes):
        self.source = source
        self.target = target
        self._find_cache: dict[bytes, int | None] = {}

    @staticmethod
    def _useful(chunk: bytes) -> bool:
        size = len(chunk)
        return (
            len(set(chunk)) >= 5
            and chunk.count(0) <= size * 0.7
            and chunk.count(0xFF) <= size * 0.7
        )

    def _unique_find(self, chunk: bytes) -> int | None:
        if chunk in self._find_cache:
            return self._find_cache[chunk]
        first = self.target.find(chunk, APPX_BASE)
        if first < 0 or self.target.find(chunk, first + 1) >= 0:
            first = None
        self._find_cache[chunk] = first
        return first

    def raw_candidates(self, address: int) -> list[RawCandidate]:
        source_off = address - FLASH_BASE
        scores: dict[int, list] = defaultdict(lambda: [0, 0, set()])

        # A matching window at source_off + relative implies a target base at
        # found - relative. Wider unique windows contribute more confidence.
        for width, weight in self.WIDTHS:
            for relative in range(-96, 193, 2):
                start = source_off + relative
                if start < APPX_BASE or start + width > len(self.source):
                    continue
                chunk = bytes(self.source[start:start + width])
                if not self._useful(chunk):
                    continue
                found = self._unique_find(chunk)
                if found is None:
                    continue
                candidate = found - relative
                if not APPX_BASE <= candidate < len(self.target):
                    continue
                if candidate % 2 != source_off % 2:
                    continue
                scores[candidate][0] += weight
                scores[candidate][1] += 1
                scores[candidate][2].add(width)

        ranked = sorted(
            scores.items(),
            key=lambda item: (item[1][0], item[1][1]),
            reverse=True,
        )
        return [
            RawCandidate(
                address=FLASH_BASE + offset,
                score=values[0],
                support=values[1],
                widths=tuple(sorted(values[2], reverse=True)),
            )
            for offset, values in ranked[:5]
        ]

    def _local_prefix_matches(
            self, source_address: int, around: int) -> tuple[list[int], int]:
        source_off = source_address - FLASH_BASE
        target_off = around - FLASH_BASE
        low = max(APPX_BASE, target_off - 128)
        high = min(len(self.target), target_off + 128)

        for width in (16, 14, 12, 10, 8, 6, 4):
            prefix = self.source[source_off:source_off + width]
            matches = []
            pos = low
            while True:
                pos = self.target.find(prefix, pos, high + width)
                if pos < 0:
                    break
                if pos % 2 == source_off % 2:
                    matches.append(FLASH_BASE + pos)
                pos += 1
            if matches:
                return matches, width
        return [], 0

    @staticmethod
    def _raw_quality(candidates: list[RawCandidate]) -> str:
        if not candidates:
            return "missing"
        first = candidates[0]
        second_score = candidates[1].score if len(candidates) > 1 else 0
        if (first.score >= 80 and first.support >= 15 and
                (second_score == 0 or first.score >= second_score * 2)):
            return "strong"
        if first.score >= 20 and first.support >= 6:
            return "weak"
        return "missing"

    def site(self, source_address: int) -> AddressResult:
        candidates = self.raw_candidates(source_address)
        quality = self._raw_quality(candidates)
        if not candidates:
            return AddressResult(
                source_address, None, "missing", "no unique local byte islands"
            )
        first = candidates[0]
        alternatives = tuple(item.address for item in candidates[1:])
        evidence = "score=%d support=%d widths=%s" % (
            first.score,
            first.support,
            ",".join(map(str, first.widths)),
        )
        if quality == "missing":
            alternatives = (first.address,) + alternatives
        return AddressResult(
            source_address,
            first.address if quality != "missing" else None,
            quality,
            evidence,
            alternatives,
        )

    def function(self, source_address: int) -> AddressResult:
        candidates = self.raw_candidates(source_address)
        quality = self._raw_quality(candidates)
        if not candidates:
            return AddressResult(
                source_address, None, "missing", "no unique local byte islands"
            )

        first = candidates[0]
        starts, width = self._local_prefix_matches(
            source_address, first.address
        )
        alternatives = [item.address for item in candidates[1:]]
        if len(starts) == 1:
            # The transferred context and the source entry prefix agree on one
            # function start, which is the strongest fully automatic case.
            address = starts[0]
            evidence = (
                "score=%d support=%d, unique %d-byte entry prefix" %
                (first.score, first.support, width)
            )
            if first.score >= 80 and first.support >= 15:
                quality = "strong"
        elif first.address in starts:
            # Short prologues are commonly shared. Keep the unique contextual
            # result and expose the other prefix matches for manual review.
            address = first.address
            alternatives = [item for item in starts if item != address] + alternatives
            evidence = (
                "score=%d support=%d, unique contextual match; "
                "%d-byte entry prefix has %d matches" %
                (first.score, first.support, width, len(starts))
            )
            if quality != "strong":
                quality = "weak"
        elif starts:
            # Context points nearby, but it does not identify which matching
            # entry owns that context. Do not pick one arbitrarily.
            address = None
            alternatives = starts + alternatives
            evidence = "%d possible function entries near best byte match" % len(starts)
            quality = "weak"
        else:
            # Some functions have a changed entry but a highly stable body.
            # Report that body-derived address as weak even when its vote was
            # strong, because the entry could not be checked independently.
            address = first.address if quality == "strong" else None
            evidence = (
                "score=%d support=%d, function entry not independently matched" %
                (first.score, first.support)
            )
            if address is not None:
                quality = "weak"

        return AddressResult(
            source_address,
            address,
            quality,
            evidence,
            tuple(
                value for value in dict.fromkeys(alternatives)
                if value != address
            ),
        )


# Thumb-2 and firmware-structure helpers used to corroborate generic matches.
def thumb2_bl_target(data: bytes, address: int) -> int | None:
    off = address - FLASH_BASE
    if off < 0 or off + 4 > len(data):
        return None
    first, second = struct.unpack_from("<HH", data, off)
    if (first & 0xF800) != 0xF000 or (second & 0xD000) != 0xD000:
        return None
    sign = (first >> 10) & 1
    j1 = (second >> 13) & 1
    j2 = (second >> 11) & 1
    i1 = (~(j1 ^ sign)) & 1
    i2 = (~(j2 ^ sign)) & 1
    immediate = (
        (sign << 24)
        | (i1 << 23)
        | (i2 << 22)
        | ((first & 0x03FF) << 12)
        | ((second & 0x07FF) << 1)
    )
    if immediate & (1 << 24):
        immediate -= 1 << 25
    return address + 4 + immediate


def thumb2_movw_immediate(
        data: bytes, address: int, register: int | None = None) -> int | None:
    """Decode a Thumb-2 MOVW immediate, optionally for one register."""
    off = address - FLASH_BASE
    if off < 0 or off + 4 > len(data):
        return None
    first, second = struct.unpack_from("<HH", data, off)
    if (first & 0xFBF0) != 0xF240:
        return None
    target = (second >> 8) & 0x0F
    if register is not None and target != register:
        return None
    return (
        ((first & 0x000F) << 12)
        | (((first >> 10) & 1) << 11)
        | (((second >> 12) & 7) << 8)
        | (second & 0x00FF)
    )


def thumb2_bw_target(data: bytes, address: int) -> int | None:
    """Decode an unconditional Thumb-2 B.W target."""
    off = address - FLASH_BASE
    if off < 0 or off + 4 > len(data):
        return None
    first, second = struct.unpack_from("<HH", data, off)
    if (first & 0xF800) != 0xF000 or (second & 0xD000) != 0x9000:
        return None
    sign = (first >> 10) & 1
    j1 = (second >> 13) & 1
    j2 = (second >> 11) & 1
    i1 = (~(j1 ^ sign)) & 1
    i2 = (~(j2 ^ sign)) & 1
    immediate = (
        (sign << 24)
        | (i1 << 23)
        | (i2 << 22)
        | ((first & 0x03FF) << 12)
        | ((second & 0x07FF) << 1)
    )
    if immediate & (1 << 24):
        immediate -= 1 << 25
    return address + 4 + immediate


def unique_pointer(data: bytes, value: int) -> tuple[int | None, tuple[int, ...]]:
    needle = struct.pack("<I", value)
    matches = []
    pos = APPX_BASE
    while True:
        pos = data.find(needle, pos)
        if pos < 0:
            break
        matches.append(FLASH_BASE + pos)
        pos += 1
    return (matches[0] if len(matches) == 1 else None, tuple(matches))


def thumb2_bl_calls_to(data: bytes, target: int) -> tuple[int, ...]:
    calls = []
    for off in range(APPX_BASE, len(data) - 3, 2):
        address = FLASH_BASE + off
        if thumb2_bl_target(data, address) == target:
            calls.append(address)
    return tuple(calls)


def decode_str_row_index(data: bytes, address: int) -> int | None:
    off = address - FLASH_BASE
    if off < 0 or off + 4 > len(data):
        return None
    first, second = struct.unpack_from("<HH", data, off)
    if (first & 0xFFF0) != 0xF8C0:
        return None
    immediate = second & 0x0FFF
    if immediate % 4:
        return None
    return immediate // 4


def find_row_label_load(data: bytes, call_address: int) -> tuple[int, int] | None:
    """Find the immediate load into r1 used as the row's GUI text ID."""
    candidates = []
    call_off = call_address - FLASH_BASE
    for off in range(max(APPX_BASE, call_off - 12), call_off, 2):
        first = struct.unpack_from("<H", data, off)[0]
        if (first & 0xF800) == 0x2000 and ((first >> 8) & 7) == 1:
            candidates.append((FLASH_BASE + off, 2))
        if off + 4 > call_off:
            continue
        second = struct.unpack_from("<H", data, off + 2)[0]
        register = (second >> 8) & 0x0F
        is_movw = (first & 0xFBF0) == 0xF240
        is_mov_immediate = (first & 0xFBFF) == 0xF04F
        if register == 1 and (is_movw or is_mov_immediate):
            candidates.append((FLASH_BASE + off, 4))
    return candidates[-1] if candidates else None


def find_row_array_store(data: bytes, call_address: int) -> int | None:
    """Find the post-constructor STR.W r0 into the clinical item array."""
    start = call_address - FLASH_BASE + 4
    end = min(len(data) - 3, start + 16)
    for off in range(start, end, 2):
        first, second = struct.unpack_from("<HH", data, off)
        if ((first & 0xFFF0) == 0xF8C0 and (first & 0x0F) == 11 and
                ((second >> 12) & 0x0F) == 0):
            return FLASH_BASE + off
    return None


def exact_gui_text_ids(fw: AS11Firmware, text: str) -> list[int]:
    if not fw._ensure_gui_text_decoder():
        return []
    matches = []
    for text_id in range(fw.gui_text_count):
        try:
            if fw.decode_gui_text(text_id, 0) == text:
                matches.append(text_id)
        except (IndexError, UnicodeError, ValueError, struct.error):
            continue
    return matches


def corroborate(result: AddressResult, evidence: str) -> AddressResult:
    if result.address is None:
        return result
    return AddressResult(
        source_address=result.source_address,
        address=result.address,
        quality="strong",
        evidence=result.evidence + "; " + evidence,
        alternatives=result.alternatives,
    )


def resolve_callsite(
        data: bytes,
        site: AddressResult,
        target: AddressResult,
        target_name: str) -> AddressResult:
    """Corroborate a transferred callsite using its transferred BL target."""
    if target.address is None:
        return site

    calls = thumb2_bl_calls_to(data, target.address)
    if site.address is not None and site.address in calls:
        return corroborate(site, "BL target matches transferred %s" % target_name)

    hints = []
    if site.address is not None:
        hints.append(site.address)
    hints.extend(site.alternatives)
    nearby = [
        call for call in calls
        if any(abs(call - hint) <= 32 for hint in hints)
    ]
    if len(nearby) == 1:
        return AddressResult(
            source_address=site.source_address,
            address=nearby[0],
            quality="strong",
            evidence="BL to transferred %s near local byte candidates" % target_name,
            alternatives=tuple(
                value for value in dict.fromkeys(hints) if value != nearby[0]
            ),
        )
    if len(calls) == 1:
        return AddressResult(
            source_address=site.source_address,
            address=calls[0],
            quality="strong",
            evidence="unique BL reference to transferred %s" % target_name,
            alternatives=tuple(dict.fromkeys(hints)),
        )
    return site


def resolve_mop_candidates(
        data: bytes,
        matcher: AddressMatcher,
        reference: dict) -> MopCandidates:
    """Locate the MOP writeback callback and its vtable registration slot."""
    writeback = matcher.function(reference["writeback"])
    vtable_slot = None
    pointer_refs: tuple[int, ...] = ()
    if writeback.address is not None:
        vtable_slot, pointer_refs = unique_pointer(
            data, writeback.address | 1
        )
    return MopCandidates(writeback, vtable_slot, pointer_refs)


def find_exact_gui_text_id(fw: AS11Firmware, value: str) -> int | None:
    """Return the unique English GUI text ID for an exact string."""
    if not fw._ensure_gui_text_decoder():
        return None
    matches = []
    for text_id in range(fw.gui_text_count):
        try:
            text = fw.decode_gui_text(text_id, 0)
        except (ValueError, UnicodeError, IndexError, struct.error):
            continue
        if text == value:
            matches.append(text_id)
    return matches[0] if len(matches) == 1 else None


def resolve_header_clock_candidates(
        fw: AS11Firmware,
        matcher: AddressMatcher,
        stubs: dict[str, AddressResult],
        reference: dict) -> HeaderClockCandidates:
    """Locate the title draw, root constructor, and owned-timer callback."""
    data = fw.data
    sites = {
        name: matcher.site(reference[name])
        for name in ("draw_call", "root_ctor_call", "timer_callback_slot")
    }

    draw_stub = stubs["GuiPaint_DrawLocalizedTextById"]
    ctor_stub = stubs["user_interface_root_widget_ctor"]
    sites["draw_call"] = resolve_callsite(
        data, sites["draw_call"], draw_stub, "GuiPaint_DrawLocalizedTextById"
    )
    sites["root_ctor_call"] = resolve_callsite(
        data, sites["root_ctor_call"], ctor_stub, "root-widget constructor"
    )

    callback_name = (
        "user_interface_root_widget_status_blink_timer_callback_adjustor"
    )
    callback = stubs[callback_name]
    if callback.address is not None:
        slot, refs = unique_pointer(data, callback.address | 1)
        if slot is not None:
            sites["timer_callback_slot"] = AddressResult(
                reference["timer_callback_slot"],
                slot,
                "strong",
                "unique pointer to transferred root-widget timer callback",
                tuple(value for value in refs if value != slot),
            )

        branches = [
            target
            for address in range(callback.address, callback.address + 0x50, 2)
            if (target := thumb2_bw_target(data, address)) is not None
        ]
        if len(branches) == 1:
            old = stubs[
                "thunk_gui_timer_handle_reschedule_with_optional_delay"
            ]
            stubs[
                "thunk_gui_timer_handle_reschedule_with_optional_delay"
            ] = AddressResult(
                old.source_address,
                branches[0],
                "strong",
                "tail branch from transferred root-widget timer callback",
                old.alternatives,
            )

    localized = stubs["GuiPaint_DrawLocalizedTextById"]
    raw_draw = stubs["GuiPaint_DrawStringInRect"]
    if localized.address is not None and raw_draw.address is not None:
        calls = [
            (address, target)
            for address in range(localized.address, localized.address + 0x60, 2)
            if (target := thumb2_bl_target(data, address)) is not None
        ]
        raw_calls = [
            index for index, (_address, target) in enumerate(calls)
            if target == raw_draw.address
        ]
        if len(raw_calls) == 1 and raw_calls[0] > 0:
            old = stubs["gui_localized_text_font_slot_for_id"]
            stubs["gui_localized_text_font_slot_for_id"] = AddressResult(
                old.source_address,
                calls[raw_calls[0] - 1][1],
                "strong",
                "call immediately before localized text reaches raw drawing",
                old.alternatives,
            )

    text_ids = {
        "home_text_id": find_exact_gui_text_id(fw, "Home"),
        "empty_text_id": find_exact_gui_text_id(fw, ""),
    }
    return HeaderClockCandidates(sites, text_ids)


def resolve_custom_settings_candidates(
        data: bytes,
        matcher: AddressMatcher,
        stubs: dict[str, AddressResult],
        reference: dict) -> CustomSettingsCandidates:
    """Locate the clinical-menu hook and the stock Reminders resources."""
    reminders = reference["reclaim"]["reminders"]
    sites = {
        "scroller_call": matcher.site(reference["menu"]["scroller_call"]),
    }
    for name in ("row_call", "row_label", "row_store", "scheduler_call"):
        value = reminders[name]
        sites[name] = matcher.site(
            value[0] if isinstance(value, tuple) else value
        )

    row_constructor = matcher.function(reminders["row_call"][1])
    scheduler_target = matcher.function(reminders["scheduler_call"][1])

    # Calls provide stronger identities than surrounding bytes. In particular,
    # the scroller call can recover GuiScroller_ctor when its entry itself moved
    # too far for the generic function matcher.
    scroller_stub = stubs.get("GuiScroller_ctor")
    if scroller_stub is not None:
        sites["scroller_call"] = resolve_callsite(
            data,
            sites["scroller_call"],
            scroller_stub,
            "GuiScroller_ctor",
        )
        scroller_site = sites["scroller_call"]
        if scroller_stub.address is None and scroller_site.address is None:
            valid_calls = []
            for candidate in scroller_site.alternatives:
                target = thumb2_bl_target(data, candidate)
                if target is not None:
                    valid_calls.append((candidate, target))
            if len(valid_calls) == 1:
                call, target = valid_calls[0]
                sites["scroller_call"] = AddressResult(
                    source_address=scroller_site.source_address,
                    address=call,
                    quality="strong",
                    evidence="only local byte candidate that decodes as BL",
                    alternatives=tuple(
                        value for value in scroller_site.alternatives
                        if value != call
                    ),
                )
                stubs["GuiScroller_ctor"] = AddressResult(
                    source_address=scroller_stub.source_address,
                    address=target,
                    quality="strong",
                    evidence="target of transferred clinical scroller BL",
                    alternatives=scroller_stub.alternatives,
                )

    sites["row_call"] = resolve_callsite(
        data, sites["row_call"], row_constructor, "Reminders row constructor"
    )
    sites["scheduler_call"] = resolve_callsite(
        data, sites["scheduler_call"], scheduler_target, "reminder scheduler"
    )

    row_call = sites["row_call"].address
    if row_call is not None:
        # Recover the label load and array store from their roles around the
        # transferred constructor call instead of transferring them separately.
        label_load = find_row_label_load(data, row_call)
        if label_load is not None:
            current = sites["row_label"]
            sites["row_label"] = AddressResult(
                source_address=current.source_address,
                address=label_load[0],
                quality="strong",
                evidence=(
                    "immediate GUI label load before transferred row constructor"
                ),
                alternatives=tuple(
                    value for value in dict.fromkeys(
                        ([current.address] if current.address is not None else [])
                        + list(current.alternatives)
                    )
                    if value != label_load[0]
                ),
            )

        row_store = find_row_array_store(data, row_call)
        if row_store is not None:
            current = sites["row_store"]
            sites["row_store"] = AddressResult(
                source_address=current.source_address,
                address=row_store,
                quality="strong",
                evidence=(
                    "STR.W r0 into clinical item array after row constructor"
                ),
                alternatives=tuple(
                    value for value in dict.fromkeys(
                        ([current.address] if current.address is not None else [])
                        + list(current.alternatives)
                    )
                    if value != row_store
                ),
            )

    row_cluster = ("row_label", "row_call", "row_store")
    if all(sites[name].address is not None for name in row_cluster):
        # The three instructions form one menu-row construction sequence. Its
        # preserved geometry is independent corroboration for all three sites.
        reference_addresses = {name: reminders[name][0] for name in row_cluster}
        target_addresses = {name: sites[name].address for name in row_cluster}
        reference_deltas = {
            name: reference_addresses[name] - reference_addresses["row_call"]
            for name in row_cluster
        }
        target_deltas = {
            name: target_addresses[name] - target_addresses["row_call"]
            for name in row_cluster
        }
        if target_deltas == reference_deltas:
            for name in row_cluster:
                sites[name] = corroborate(
                    sites[name],
                    "Reminders row cluster preserves reference geometry",
                )

    return CustomSettingsCandidates(
        sites=sites,
        row_constructor=row_constructor,
        scheduler_target=scheduler_target,
        reference_reminders=reminders,
    )


def resolve_asv_candidates(
        target_fw: AS11Firmware,
        reference_fw: AS11Firmware,
        stubs: dict[str, AddressResult],
        reference: dict) -> AsvCandidates:
    """Locate the native ASV callback slot and matching GUI label ID."""
    asv_stub = stubs.get("AsvFeature_update")
    vtable_slot = None
    pointer_refs: tuple[int, ...] = ()
    if asv_stub is not None and asv_stub.address is not None:
        vtable_slot, pointer_refs = unique_pointer(
            target_fw.data, asv_stub.address | 1
        )

    reference_label = None
    label_ids: tuple[int, ...] = ()
    if reference_fw._ensure_gui_text_decoder():
        reference_label = reference_fw.decode_gui_text(
            reference["label_id"], 0
        )
        label_ids = tuple(exact_gui_text_ids(target_fw, reference_label))
    return AsvCandidates(
        vtable_slot=vtable_slot,
        pointer_refs=pointer_refs,
        reference_label=reference_label,
        label_ids=label_ids,
    )


def resolve_ota_descriptor_candidates(
        target_data: bytes,
        reference_data: bytes,
        matcher: AddressMatcher,
        reference_release: str) -> OtaDescriptorCandidates:
    """Recover desc2/desc3 from the application upgrade-verifier table."""
    preset = AS11_OTA_DESCRIPTOR_PRESETS.get(reference_release)
    if preset is None:
        return OtaDescriptorCandidates(
            AddressResult(
                0, None, "missing",
                "reference release has no reviewed OTA descriptor preset",
            ),
            None,
            None,
        )

    # The verifier table stores the reviewed words in memory order desc3,desc2.
    # Their values change with the release, so the unchanged table suffix is a
    # better anchor than either value. Generic address transfer is the fallback.
    pair = struct.pack("<II", preset["desc3"], preset["desc2"])
    source_off = reference_data.find(pair, APPX_BASE)
    if source_off < 0:
        return OtaDescriptorCandidates(
            AddressResult(
                0, None, "missing",
                "reviewed descriptor pair not found in reference firmware",
            ),
            None,
            None,
        )
    source_address = FLASH_BASE + source_off
    if reference_data.find(pair, source_off + 1) >= 0:
        return OtaDescriptorCandidates(
            AddressResult(
                source_address, None, "missing",
                "reviewed descriptor pair is not unique in reference firmware",
            ),
            None,
            None,
        )

    table = None
    for width in (32, 24, 16, 12):
        suffix = reference_data[source_off + 8:source_off + 8 + width]
        if len(suffix) != width or not matcher._useful(suffix):
            continue
        found = target_data.find(suffix, APPX_BASE)
        if found < 0 or target_data.find(suffix, found + 1) >= 0:
            continue
        target_off = found - 8
        if target_off % 4 != source_off % 4:
            continue
        table = AddressResult(
            source_address,
            FLASH_BASE + target_off,
            "strong",
            "unique %d-byte verifier-table suffix" % width,
        )
        break
    if table is None:
        table = matcher.site(source_address)
    if table.address is None:
        return OtaDescriptorCandidates(table, None, None)
    target_off = table.address - FLASH_BASE
    if target_off < APPX_BASE or target_off + 8 > len(target_data):
        return OtaDescriptorCandidates(
            AddressResult(
                source_address, None, "missing",
                "transferred descriptor pair lies outside APPX",
                table.alternatives,
            ),
            None,
            None,
        )
    desc3, desc2 = struct.unpack_from("<II", target_data, target_off)
    return OtaDescriptorCandidates(table, desc2, desc3)


def resolve_timezone_menu_warning_action(
        target_fw: AS11Firmware,
        matcher: AddressMatcher,
        source_address: int) -> AddressResult:
    """Corroborate the Time Zone row's saved-history warning action."""
    direct = matcher.site(source_address)
    tzg_var_id = target_fw._resolve_var_ident("TZG")
    dispatch = (
        target_fw.dispatch_var_id(tzg_var_id)
        if tzg_var_id is not None else None
    )
    if dispatch is None or dispatch[0] != "g[5]":
        return AddressResult(
            source_address, None, "missing",
            "TZG does not resolve to a g[5] descriptor",
            direct.alternatives,
        )

    seeds = []
    if direct.address is not None:
        seeds.append(direct.address)
    seeds.extend(direct.alternatives)
    seeds.extend(
        candidate.address
        for candidate in matcher.raw_candidates(source_address)
    )

    matches = []
    data = target_fw.data
    for seed in dict.fromkeys(seeds):
        start = max(FLASH_BASE + APPX_BASE, seed - 0x10)
        end = min(FLASH_BASE + len(data) - 4, seed + 0x12)
        for address in range(start & ~1, end + 1, 2):
            first_target = thumb2_bl_target(data, address)
            off = address - FLASH_BASE
            if first_target is None or struct.unpack_from(
                    "<H", data, off + 4)[0] != 0x200C:
                continue

            tzg_loads = []
            row_alloc_setups = []
            for candidate in range(address + 4, address + 0x30, 2):
                candidate_off = candidate - FLASH_BASE
                if struct.unpack_from("<H", data, candidate_off)[0] == 0x2050:
                    row_alloc_setups.append(candidate)
                if (thumb2_movw_immediate(data, candidate, register=1) ==
                        tzg_var_id):
                    tzg_loads.append(candidate)
            if len(tzg_loads) != 1 or len(row_alloc_setups) != 1:
                continue
            load_off = tzg_loads[0] - FLASH_BASE
            if struct.unpack_from("<H", data, load_off - 2)[0] != 0x2201:
                continue
            later_targets = [
                target
                for candidate in range(
                    row_alloc_setups[0] - 8, row_alloc_setups[0], 2
                )
                if (target := thumb2_bl_target(data, candidate)) is not None
            ]
            if later_targets == [first_target]:
                matches.append(address)

    matches = list(dict.fromkeys(matches))
    if len(matches) != 1:
        return AddressResult(
            source_address, None, "missing",
            "found %d structurally matching Time Zone warning actions" %
            len(matches),
            tuple(matches) or direct.alternatives,
        )
    evidence = (
        "unique warning-action prepend followed by resolved TZG=1 action"
    )
    if direct.address == matches[0] or matches[0] in direct.alternatives:
        evidence += "; generic site transfer agrees"
    return AddressResult(source_address, matches[0], "strong", evidence)


def resolve_timezone_write_candidates(
        target_fw: AS11Firmware,
        matcher: AddressMatcher,
        reference: dict) -> TimezoneWriteCandidates:
    """Transfer the time-zone metadata, data-rule, and menu-action sites."""
    metadata = matcher.site(reference["metadata_gate"]["address"])
    source_gate = reference["data_rule_gate"]["address"]
    direct_data_rule_gate = matcher.site(source_gate)
    source_gate_off = source_gate - FLASH_BASE
    prologues = []
    for signature in (bytes.fromhex("f0b58db0"), bytes.fromhex("78b58db0")):
        start = max(APPX_BASE, source_gate_off - 0x60)
        while True:
            found = matcher.source.find(signature, start, source_gate_off)
            if found < 0:
                break
            prologues.append(found)
            start = found + 1
    if len(prologues) != 1:
        data_rule_gate = AddressResult(
            source_gate, None, "missing",
            "reference time-zone data-rule prologue is not unique",
        )
        return TimezoneWriteCandidates({
            "metadata_gate": metadata,
            "data_rule_gate": data_rule_gate,
            "menu_warning_action": resolve_timezone_menu_warning_action(
                target_fw, matcher,
                reference["menu_warning_action"]["address"]
            ),
        })

    source_callback = FLASH_BASE + prologues[0]
    callback = matcher.function(source_callback)
    body_candidates = matcher.raw_candidates(source_callback)
    body_strong = bool(
        body_candidates
        and body_candidates[0].score >= 80
        and body_candidates[0].support >= 15
    )
    matches = []
    callback_candidates = []
    if callback.address is not None:
        callback_candidates.append(callback.address)
    callback_candidates.extend(callback.alternatives)
    for callback_address in dict.fromkeys(callback_candidates):
        callback_off = callback_address - FLASH_BASE
        end = min(len(matcher.target), callback_off + 0x80)
        patterns = (
            bytes.fromhex("17ead47f0ed06846"),
            bytes.fromhex("16ead47f0ed06846"),
            bytes.fromhex("002f00bf0ed06846"),
            bytes.fromhex("002e00bf0ed06846"),
        )
        for pattern in patterns:
            start = callback_off
            while True:
                found = matcher.target.find(pattern, start, end)
                if found < 0:
                    break
                matches.append(FLASH_BASE + found)
                start = found + 1
    matches = list(dict.fromkeys(matches))
    if len(matches) == 1:
        direct_agreement = (
            direct_data_rule_gate.address == matches[0]
            or matches[0] in direct_data_rule_gate.alternatives
        )
        quality = (
            "strong" if direct_agreement or body_strong else callback.quality
        )
        evidence = "unique FTS gate in transferred time-zone data rule: %s" % callback.evidence
        if direct_agreement:
            evidence += "; direct site transfer agrees"
        elif body_strong:
            evidence += "; strong body transfer"
        data_rule_gate = AddressResult(
            source_gate,
            matches[0],
            quality,
            evidence,
        )
    else:
        data_rule_gate = AddressResult(
            source_gate,
            None,
            "missing",
            "found %d FTS gates in transferred time-zone data rule" %
            len(matches),
            tuple(matches),
        )
    return TimezoneWriteCandidates({
        "metadata_gate": metadata,
        "data_rule_gate": data_rule_gate,
        "menu_warning_action": resolve_timezone_menu_warning_action(
            target_fw, matcher,
            reference["menu_warning_action"]["address"]
        ),
    })


def resolve_port_candidates(
        target_fw: AS11Firmware,
        reference_fw: AS11Firmware,
        reference_key: str,
        reference_release: str) -> PortCandidates:
    """Resolve every version-specific input represented by the shared registry."""
    reference = AS11_PATCH_VERSIONS.get(reference_key)
    if reference is None:
        raise ValueError(
            "no reviewed patch data for reference APPX %s" % reference_key
        )
    required = (
        ("MOP dispatcher", "mop_callback_dispatcher"),
        ("time-zone write", "timezone_write"),
        ("header clock", "header_clock"),
        ("custom settings", "custom_settings"),
        ("ASV backup rate", "asv_backup_rate"),
    )
    for label, feature in required:
        if feature not in reference:
            raise ValueError(
                "%s is not ported to reference APPX %s" %
                (label, reference_key)
            )
        if reference[feature] is None:
            raise ValueError(
                "%s does not apply to reference APPX %s; use another "
                "reference image" % (label, reference_key)
            )

    matcher = AddressMatcher(reference_fw.data, target_fw.data)
    stubs = {
        name: matcher.function(address)
        for name, address in parse_stubs(reference_key).items()
    }
    mop = resolve_mop_candidates(
        target_fw.data, matcher, reference["mop_callback_dispatcher"]
    )
    timezone_write = resolve_timezone_write_candidates(
        target_fw, matcher, reference["timezone_write"]
    )
    header_clock = resolve_header_clock_candidates(
        target_fw, matcher, stubs, reference["header_clock"]
    )
    custom_settings = resolve_custom_settings_candidates(
        target_fw.data, matcher, stubs, reference["custom_settings"]
    )
    asv = resolve_asv_candidates(
        target_fw, reference_fw, stubs, reference["asv_backup_rate"]
    )
    ota_descriptor = resolve_ota_descriptor_candidates(
        target_fw.data,
        reference_fw.data,
        matcher,
        reference_release,
    )
    return PortCandidates(
        stubs, mop, timezone_write, header_clock, custom_settings, asv,
        ota_descriptor
    )


# Inputs generated directly from target firmware layout and descriptor data.
def generate_vars_header(fw: AS11Firmware, identity: Identity) -> str:
    """Generate the complete three-letter tag to var_id namespace."""
    by_tag: dict[str, int] = {}
    for var_id, tag in fw.name_buckets.items():
        if not re.fullmatch(r"[A-Z0-9]{3}", tag):
            raise ValueError("short tag %r cannot form a VAR_ID macro" % tag)
        previous = by_tag.get(tag)
        if previous is not None and previous != var_id:
            raise ValueError(
                "short tag %s maps to both 0x%04X and 0x%04X" %
                (tag, previous, var_id)
            )
        by_tag[tag] = var_id

    guard = "AS11_VARS_%s_H" % identity.appx_key.upper()
    lines = [
        "#ifndef %s" % guard,
        "#define %s" % guard,
        "",
        "/* Generated from the Air11 APPX %s descriptor namespace. */" %
        ".".join(identity.appx_version.split(".")[:3]),
    ]
    lines.extend(
        "#define VAR_ID_%s 0x%04Xu" % (tag, var_id)
        for tag, var_id in sorted(by_tag.items())
    )
    lines.extend(("", "#endif", ""))
    return "\n".join(lines)


def generated_cave(identity: Identity, data: bytes) -> tuple[int, int]:
    """Return the aligned erased APPL tail immediately before its identity."""
    end = identity.appx_offset
    start = end
    while start > APPX_BASE and data[start - 1] == 0xFF:
        start -= 1
    start = (start + 3) & ~3
    if start >= end or any(value != 0xFF for value in data[start:end]):
        raise ValueError("no contiguous erased APPL tail before APPX identity")
    return FLASH_BASE + start, FLASH_BASE + end


def image_bytes_at(
        data: bytes, address: int | None, size: int) -> str | None:
    if address is None:
        return None
    off = address - FLASH_BASE
    if off < 0 or off + size > len(data):
        return None
    return data[off:off + size].hex()


def parse_code_caves() -> dict[str, tuple[int, int]]:
    caves = {}
    for line in CODE_CAVES_PATH.read_text(encoding="ascii").splitlines():
        line = line.partition("#")[0].strip()
        if not line:
            continue
        version, region, start, end, _image_base, _runtime_base = line.split()
        if region != "appl":
            continue
        caves[version] = (int(start, 0), int(end, 0))
    return caves


# Known-answer checks compare candidates against metadata already reviewed for
# a target version. They measure autoporter coverage; they do not replace the
# manual review required for a genuinely new release.
def derived_candidate(
        value: object | None,
        source: AddressResult,
        evidence: str) -> CandidateValue:
    quality = source.quality if value is not None else "missing"
    return CandidateValue(value, quality, evidence)


def compare_candidate(
        component: str,
        expected: object,
        candidate: CandidateValue) -> SelfCheckItem:
    if candidate.value is None or candidate.quality != "strong":
        detail = candidate.quality
        if candidate.evidence:
            detail += ": " + candidate.evidence
        return SelfCheckItem(
            component, "missed", expected, candidate.value, detail
        )
    status = "recovered" if candidate.value == expected else "wrong"
    return SelfCheckItem(
        component, status, expected, candidate.value, candidate.evidence
    )


def self_check_candidates(
        target_fw: AS11Firmware,
        target_id: Identity,
        candidates: PortCandidates,
        vars_text: str,
        cave: tuple[int, int]) -> list[SelfCheckItem]:
    """Compare a generated bundle with the repository's reviewed target data."""
    expected_version = AS11_PATCH_VERSIONS.get(target_id.appx_key)
    if expected_version is None:
        raise ValueError(
            "self-check requires reviewed data for target APPX %s" %
            target_id.appx_key
        )

    checks = []
    expected_stubs = parse_stubs(target_id.appx_key)
    for name, expected in expected_stubs.items():
        result = candidates.stubs.get(name)
        candidate = (
            CandidateValue(result.address, result.quality, result.evidence)
            if result is not None
            else CandidateValue(None, "missing", "not present in reference stubs")
        )
        checks.append(compare_candidate("stub.%s" % name, expected, candidate))

    expected_vars_path = PATCHES_DIR / ("vars_%s.h" % target_id.appx_key)
    if not expected_vars_path.is_file():
        raise ValueError("self-check vars file does not exist: %s" % expected_vars_path)
    expected_vars = expected_vars_path.read_text(encoding="ascii")
    expected_vars_hash = hashlib.sha256(expected_vars.encode("ascii")).hexdigest()
    actual_vars_hash = hashlib.sha256(vars_text.encode("ascii")).hexdigest()
    checks.append(compare_candidate(
        "vars",
        expected_vars_hash,
        CandidateValue(actual_vars_hash, "strong", "SHA256 of generated header"),
    ))

    expected_caves = parse_code_caves()
    if target_id.appx_key not in expected_caves:
        raise ValueError(
            "self-check has no code cave for APPX %s" % target_id.appx_key
        )
    expected_cave = expected_caves[target_id.appx_key]
    cave_status = (
        "recovered"
        if cave[0] <= expected_cave[0] and cave[1] >= expected_cave[1]
        else "wrong"
    )
    checks.append(SelfCheckItem(
        "code_cave",
        cave_status,
        expected_cave,
        cave,
        "generated erased tail must contain the reviewed allocation range",
    ))

    mop_expected = expected_version.get("mop_callback_dispatcher")
    if mop_expected is not None:
        writeback = candidates.mop.writeback
        checks.append(compare_candidate(
            "mop_callback_dispatcher.writeback",
            mop_expected["writeback"],
            CandidateValue(writeback.address, writeback.quality, writeback.evidence),
        ))
        checks.append(compare_candidate(
            "mop_callback_dispatcher.vtable_slot",
            mop_expected["vtable_slot"],
            derived_candidate(
                candidates.mop.vtable_slot,
                writeback,
                "unique pointer to transferred writeback",
            ),
        ))

    timezone_expected = expected_version.get("timezone_write")
    if timezone_expected is not None:
        for name in ("metadata_gate", "data_rule_gate", "menu_warning_action"):
            result = candidates.timezone_write.sites[name]
            checks.append(compare_candidate(
                "timezone_write.%s" % name,
                timezone_expected[name]["address"],
                CandidateValue(result.address, result.quality, result.evidence),
            ))

    header_clock_expected = expected_version.get("header_clock")
    if header_clock_expected is not None:
        for name in ("draw_call", "root_ctor_call", "timer_callback_slot"):
            expected = header_clock_expected[name]
            result = candidates.header_clock.sites[name]
            checks.append(compare_candidate(
                "header_clock.%s" % name,
                expected,
                CandidateValue(result.address, result.quality, result.evidence),
            ))
        for name in ("home_text_id", "empty_text_id"):
            value = candidates.header_clock.text_ids[name]
            checks.append(compare_candidate(
                "header_clock.%s" % name,
                header_clock_expected[name],
                CandidateValue(
                    value,
                    "strong" if value is not None else "missing",
                    "unique exact English GUI text match",
                ),
            ))

    custom_expected = expected_version.get("custom_settings")
    if custom_expected is not None:
        sites = candidates.custom_settings.sites
        reminders = custom_expected["reclaim"]["reminders"]
        scroller = sites["scroller_call"]
        checks.append(compare_candidate(
            "custom_settings.menu.scroller_call",
            custom_expected["menu"]["scroller_call"],
            CandidateValue(scroller.address, scroller.quality, scroller.evidence),
        ))

        for name in ("row_call", "row_label", "row_store", "scheduler_call"):
            result = sites[name]
            checks.append(compare_candidate(
                "custom_settings.reminders.%s" % name,
                reminders[name][0],
                CandidateValue(result.address, result.quality, result.evidence),
            ))

        row_call = sites["row_call"]
        row_call_target = (
            thumb2_bl_target(target_fw.data, row_call.address)
            if row_call.address is not None else None
        )
        checks.append(compare_candidate(
            "custom_settings.reminders.row_constructor",
            reminders["row_call"][1],
            derived_candidate(
                row_call_target, row_call, "BL target at transferred row call"
            ),
        ))

        scheduler_call = sites["scheduler_call"]
        scheduler_target = (
            thumb2_bl_target(target_fw.data, scheduler_call.address)
            if scheduler_call.address is not None else None
        )
        checks.append(compare_candidate(
            "custom_settings.reminders.scheduler_target",
            reminders["scheduler_call"][1],
            derived_candidate(
                scheduler_target,
                scheduler_call,
                "BL target at transferred scheduler call",
            ),
        ))

        row_store = sites["row_store"]
        row_index = (
            decode_str_row_index(target_fw.data, row_store.address)
            if row_store.address is not None else None
        )
        checks.append(compare_candidate(
            "custom_settings.reminders.row_index",
            reminders["row_index"],
            derived_candidate(
                row_index, row_store, "decoded clinical item-array store"
            ),
        ))

        for name in ("row_label", "row_store"):
            result = sites[name]
            expected_hex = reminders[name][1]
            actual_hex = image_bytes_at(
                target_fw.data, result.address, len(bytes.fromhex(expected_hex))
            )
            checks.append(compare_candidate(
                "custom_settings.reminders.%s_bytes" % name,
                expected_hex,
                derived_candidate(
                    actual_hex, result, "bytes at transferred instruction"
                ),
            ))

    asv_expected = expected_version.get("asv_backup_rate")
    if asv_expected is not None:
        asv_stub = candidates.stubs.get("AsvFeature_update")
        asv_quality = asv_stub or AddressResult(
            0, None, "missing", "AsvFeature_update was not transferred"
        )
        checks.append(compare_candidate(
            "asv_backup_rate.vtable_slot",
            asv_expected["vtable_slot"],
            derived_candidate(
                candidates.asv.vtable_slot,
                asv_quality,
                "unique pointer to transferred AsvFeature_update",
            ),
        ))
        label_quality = "strong" if candidates.asv.label_id is not None else "missing"
        checks.append(compare_candidate(
            "asv_backup_rate.label_id",
            asv_expected["label_id"],
            CandidateValue(
                candidates.asv.label_id,
                label_quality,
                "unique exact GUI-text match",
            ),
        ))

    ota_expected = AS11_OTA_DESCRIPTOR_PRESETS.get(target_id.firmware_release)
    if ota_expected is not None:
        ota = candidates.ota_descriptor
        for field in ("desc2", "desc3"):
            checks.append(compare_candidate(
                "ota_descriptor.%s" % field,
                ota_expected[field],
                derived_candidate(
                    getattr(ota, field),
                    ota.table,
                    "word at transferred verifier table",
                ),
            ))

    return checks


def format_address(value: int | None) -> str:
    return "TODO" if value is None else "0x%08X" % value


def format_text_id(value: int | None) -> str:
    return "TODO" if value is None else "0x%04X" % value


def format_check_value(value: object | None) -> str:
    if value is None:
        return ""
    if isinstance(value, int):
        return "0x%X" % value
    if isinstance(value, tuple):
        return ",".join(format_check_value(item) for item in value)
    return str(value)


def result_line(kind: str, name: str, result: AddressResult) -> str:
    alternatives = ",".join("0x%08X" % item for item in result.alternatives)
    return "\t".join((
        kind,
        name,
        "0x%08X" % result.source_address,
        "" if result.address is None else "0x%08X" % result.address,
        result.quality,
        result.evidence,
        alternatives,
    ))


def prepare(args) -> int:
    # Identify both images before consulting versioned patch metadata. APPX is
    # authoritative for native addresses; the full release selects OTA words.
    target_path = Path(args.firmware).resolve()
    reference_path = Path(args.reference).resolve()
    target_fw = AS11Firmware(target_path)
    reference_fw = AS11Firmware(reference_path)
    target_id = image_identity(target_path, target_fw)
    reference_id = image_identity(reference_path, reference_fw)
    if target_id.appx_key == reference_id.appx_key:
        print("warning: target and reference use the same APPX key", file=sys.stderr)

    # Refuse to mix a new bundle with arbitrary old output. --force replaces
    # only files owned by this tool and leaves unrelated files untouched.
    output = (
        Path(args.output).resolve()
        if args.output
        else REPO_ROOT / "tmp" / ("as11-version-%s" % target_id.appx_key)
    )
    if output.exists() and not output.is_dir():
        raise ValueError("output path is not a directory: %s" % output)
    if output.exists() and any(output.iterdir()) and not args.force:
        raise ValueError("output directory is not empty; use --force: %s" % output)
    output.mkdir(parents=True, exist_ok=True)
    if args.force:
        generated_names = (
            "REPORT.txt",
            "address_candidates.tsv",
            "integration.txt",
            "patcher_snippets.py",
            "patcher_snippets.txt",
            "self_check.tsv",
            "stubs_%s.S" % target_id.appx_key,
            "vars_%s.h" % target_id.appx_key,
        )
        for name in generated_names:
            path = output / name
            if path.is_file():
                path.unlink()

    # Transfer all reviewed, version-specific patch inputs in one pass so the
    # generated reports share a consistent candidate set.
    candidates = resolve_port_candidates(
        target_fw,
        reference_fw,
        reference_id.appx_key,
        reference_id.firmware_release,
    )
    stub_results = candidates.stubs
    mop_writeback = candidates.mop.writeback
    mop_vtable = candidates.mop.vtable_slot
    mop_vtable_matches = candidates.mop.pointer_refs
    timezone_write_sites = candidates.timezone_write.sites
    header_clock_sites = candidates.header_clock.sites
    custom_site_results = candidates.custom_settings.sites
    row_ctor_result = candidates.custom_settings.row_constructor
    scheduler_target_result = candidates.custom_settings.scheduler_target
    reminder_ref = candidates.custom_settings.reference_reminders
    asv_vtable = candidates.asv.vtable_slot
    asv_vtable_matches = candidates.asv.pointer_refs
    reference_label = candidates.asv.reference_label
    target_label_ids = candidates.asv.label_ids
    target_label_id = candidates.asv.label_id
    ota_descriptor = candidates.ota_descriptor

    address_rows: list[tuple[str, str, AddressResult]] = [
        ("mop", "writeback", mop_writeback),
        ("ota", "descriptor_words", ota_descriptor.table),
    ]
    address_rows.extend(
        ("timezone_write", name, result)
        for name, result in timezone_write_sites.items()
    )
    address_rows.extend(
        ("header_clock", name, result)
        for name, result in header_clock_sites.items()
    )
    address_rows.extend(
        ("custom_settings", name, result)
        for name, result in custom_site_results.items()
    )
    address_rows.extend((
        ("custom_settings", "row_constructor", row_ctor_result),
        ("custom_settings", "scheduler_target", scheduler_target_result),
    ))

    # Files below are direct build inputs. They intentionally remain candidates
    # until copied into the repository after target-image review.
    cave_start, cave_end = generated_cave(target_id, target_fw.data)

    vars_text = generate_vars_header(target_fw, target_id)
    vars_path = output / ("vars_%s.h" % target_id.appx_key)
    vars_path.write_text(
        vars_text, encoding="ascii", newline="\n"
    )

    stubs_lines = [
        "// Candidate Air11 APPX %s native function addresses." %
        ".".join(target_id.appx_version.split(".")[:3]),
        "// Review every address and its call ABI before installing this file.",
        "",
        "#define NSTUB(addr, name) \\",
        "\t.global name; \\",
        "\t.type name, %function; \\",
        "\tname = addr",
        "",
        ".text",
        "",
    ]
    for name, result in stub_results.items():
        if result.address is None or result.quality != "strong":
            values = []
            if result.address is not None:
                values.append(result.address)
            values.extend(result.alternatives)
            candidate_text = ", ".join(
                "0x%08X" % value for value in dict.fromkeys(values)
            ) or "none"
            stubs_lines.append(
                "// TODO NSTUB(..., %s) %s candidates: %s" %
                (name, result.quality, candidate_text)
            )
        else:
            stubs_lines.append(
                "// %s candidate: %s" % (result.quality, result.evidence)
            )
            stubs_lines.append("NSTUB(0x%08X, %s)" % (result.address, name))
    stubs_path = output / ("stubs_%s.S" % target_id.appx_key)
    stubs_path.write_text("\n".join(stubs_lines) + "\n", encoding="ascii", newline="\n")

    # Convert semantic candidates into the exact compact values consumed by the
    # shared version registry: call targets, row index, and expected bytes.
    row_call = custom_site_results["row_call"].address
    row_label = custom_site_results["row_label"].address
    row_store = custom_site_results["row_store"].address
    scheduler_call = custom_site_results["scheduler_call"].address
    row_ctor = thumb2_bl_target(target_fw.data, row_call) if row_call else None
    scheduler_target = (
        thumb2_bl_target(target_fw.data, scheduler_call)
        if scheduler_call else None
    )
    row_index = decode_str_row_index(target_fw.data, row_store) if row_store else None
    label_load = find_row_label_load(target_fw.data, row_call) if row_call else None
    label_size = label_load[1] if label_load is not None else len(
        bytes.fromhex(reminder_ref["row_label"][1])
    )
    store_size = len(bytes.fromhex(reminder_ref["row_store"][1]))

    reviewed_timezone = AS11_PATCH_VERSIONS.get(
        target_id.appx_key, {}
    ).get("timezone_write")
    timezone_snippet_lines = ["    \"timezone_write\": {"]
    for name in ("metadata_gate", "data_rule_gate", "menu_warning_action"):
        result = timezone_write_sites[name]
        if reviewed_timezone is not None:
            before = reviewed_timezone[name]["before"]
            after = reviewed_timezone[name]["after"]
        elif result.address is not None:
            width = 2 if name == "metadata_gate" else 4
            off = result.address - FLASH_BASE
            before = bytes(target_fw.data[off:off + width]).hex()
            if name == "metadata_gate":
                after = "0121" if before == "e10f" else "TODO"
            elif name == "menu_warning_action":
                after = "00bf00bf"
            else:
                after = {
                    "17ead47f": "002f00bf",
                    "16ead47f": "002e00bf",
                }.get(before, "TODO")
        else:
            before = after = "TODO"
        timezone_snippet_lines.extend((
            "        \"%s\": {" % name,
            "            \"address\": %s," % format_address(result.address),
            "            \"before\": \"%s\"," % before,
            "            \"after\": \"%s\"," % after,
            "        },",
        ))
    timezone_snippet_lines.append("    },")

    snippets = [
        "# Candidate entry for AS11_PATCH_VERSIONS.",
        "# Verify against the target firmware before copying.",
        "",
        "%r: {" % target_id.appx_key,
        "    \"mop_callback_dispatcher\": {",
        "        \"writeback\": %s," % format_address(mop_writeback.address),
        "        \"vtable_slot\": %s," % format_address(mop_vtable),
        "    },",
        *timezone_snippet_lines,
        "    \"header_clock\": {",
        "        \"draw_call\": %s," % format_address(
            header_clock_sites["draw_call"].address
        ),
        "        \"root_ctor_call\": %s," % format_address(
            header_clock_sites["root_ctor_call"].address
        ),
        "        \"timer_callback_slot\": %s," % format_address(
            header_clock_sites["timer_callback_slot"].address
        ),
        "        \"home_text_id\": %s," % format_text_id(
            candidates.header_clock.text_ids["home_text_id"]
        ),
        "        \"empty_text_id\": %s," % format_text_id(
            candidates.header_clock.text_ids["empty_text_id"]
        ),
        "    },",
        "    \"custom_settings\": {",
        "        \"menu\": {",
        "            \"scroller_call\": %s," % format_address(
            custom_site_results["scroller_call"].address
        ),
        "        },",
        "        \"reclaim\": {",
        "            \"reminders\": {",
        "                \"row_index\": %s," % (
            "TODO" if row_index is None else "0x%X" % row_index
        ),
        "                \"row_call\": (%s, %s)," %
        (format_address(row_call), format_address(row_ctor)),
        "                \"row_label\": (%s, %r)," %
        (format_address(row_label), image_bytes_at(
            target_fw.data, row_label, label_size
        )),
        "                \"row_store\": (%s, %r)," %
        (format_address(row_store), image_bytes_at(
            target_fw.data, row_store, store_size
        )),
        "                \"scheduler_call\": (%s, %s)," %
        (format_address(scheduler_call), format_address(scheduler_target)),
        "            },",
        "        },",
        "    },",
        "    \"asv_backup_rate\": {",
        "        \"vtable_slot\": %s," % format_address(asv_vtable),
        "        \"label_id\": %s," % (
            "TODO" if target_label_id is None else "0x%04X" % target_label_id
        ),
        "    },",
        "},",
        "",
    ]
    snippets_path = output / "patcher_snippets.txt"
    snippets_path.write_text("\n".join(snippets), encoding="ascii", newline="\n")

    # Integration notes cover every repository location needed to make the new
    # version buildable; the tool never edits those locations itself.
    makefile = MAKEFILE_PATH.read_text(encoding="ascii")
    versions_match = re.search(
        r"^AS11_PAYLOAD_LAYOUT_VERSIONS\s*:=\s*(.+)$", makefile, re.MULTILINE
    )
    versions = versions_match.group(1).split() if versions_match else []
    versions_with_target = versions + (
        [] if target_id.appx_key in versions else [target_id.appx_key]
    )
    ota_ready = (
        ota_descriptor.table.quality == "strong"
        and ota_descriptor.desc2 is not None
        and ota_descriptor.desc3 is not None
    )
    ota_desc2 = (
        "0x%08X" % ota_descriptor.desc2 if ota_ready else "TODO"
    )
    ota_desc3 = (
        "0x%08X" % ota_descriptor.desc3 if ota_ready else "TODO"
    )
    integration = [
        "Generated integration snippets; review before applying.",
        "",
        "Makefile.as11:",
        "AS11_PAYLOAD_LAYOUT_VERSIONS := %s" % " ".join(versions_with_target),
        "AS11_PAYLOADS_%s := $(AS11_PAYLOADS_%s)" %
        (target_id.appx_key, reference_id.appx_key),
        "",
        "patches/as11/vars.h:",
        "#elif defined(APPX_VER_%s)" % target_id.appx_key,
        "#include \"vars_%s.h\"" % target_id.appx_key,
        "",
        "patches/as11_code_caves.tsv:",
        "%s\tappl\t0x%08X\t0x%08X\t0x%08X\t0x%08X" %
        (target_id.appx_key, cave_start, cave_end, FLASH_BASE, FLASH_BASE),
        "",
        "python/lib/as11_patch_versions.py AS11_OTA_DESCRIPTOR_PRESETS:",
        "%r: {\"desc2\": %s, \"desc3\": %s}," %
        (target_id.firmware_release, ota_desc2, ota_desc3),
        "",
        "Copy after review:",
        "  %s -> patches/as11/%s" % (vars_path.name, vars_path.name),
        "  %s -> patches/as11/%s" % (stubs_path.name, stubs_path.name),
        "  patcher_snippets.txt -> python/lib/as11_patch_versions.py",
        "",
    ]
    (output / "integration.txt").write_text(
        "\n".join(integration), encoding="ascii", newline="\n"
    )

    # Machine-readable evidence is kept separate from copy-ready snippets so a
    # reviewer can inspect alternatives and weak matches before integration.
    address_rows = [
        ("stub", name, result) for name, result in stub_results.items()
    ] + address_rows
    candidate_lines = [
        "kind\tname\treference\tcandidate\tquality\tevidence\talternatives"
    ]
    candidate_lines.extend(
        result_line(kind, name, result)
        for kind, name, result in address_rows
    )
    (output / "address_candidates.tsv").write_text(
        "\n".join(candidate_lines) + "\n", encoding="ascii", newline="\n"
    )

    self_checks = []
    if args.self_check:
        self_checks = self_check_candidates(
            target_fw,
            target_id,
            candidates,
            vars_text,
            (cave_start, cave_end),
        )
        check_lines = ["status\tcomponent\texpected\tactual\tdetail"]
        check_lines.extend(
            "\t".join((
                item.status,
                item.component,
                format_check_value(item.expected),
                format_check_value(item.actual),
                item.detail,
            ))
            for item in self_checks
        )
        (output / "self_check.tsv").write_text(
            "\n".join(check_lines) + "\n", encoding="ascii", newline="\n"
        )

    # REPORT.txt is the review entry point and summarizes the generated inputs,
    # structural cross-checks, and any known-answer self-check results.
    strong_stubs = sum(
        result.address is not None and result.quality == "strong"
        for result in stub_results.values()
    )
    unresolved_stubs = len(stub_results) - strong_stubs
    report = [
        "# Air11 APPX %s preparation report" % target_id.appx_key,
        "",
        "Target:",
        "  file: %s" % target_id.path,
        "  application: %s" % target_id.application_id,
        "  sha256: %s" % target_id.sha256,
        "",
        "Reference:",
        "  file: %s" % reference_id.path,
        "  application: %s" % reference_id.application_id,
        "  sha256: %s" % reference_id.sha256,
        "",
        "Generated:",
        "  %s: %d short-name definitions" %
        (vars_path.name, len(target_fw.name_buckets)),
        "  %s: %d strong candidates, %d unresolved" %
        (stubs_path.name, strong_stubs, unresolved_stubs),
        "  code cave candidate: 0x%08X..0x%08X (%d bytes)" %
        (cave_start, cave_end, cave_end - cave_start),
        "",
        "Cross-checks:",
        "  MOP writeback pointer refs: %s" % (
            ", ".join("0x%08X" % value for value in mop_vtable_matches)
            or "none"
        ),
        "  ASV update pointer refs: %s" % (
            ", ".join("0x%08X" % value for value in asv_vtable_matches)
            or "none"
        ),
        "  ASV label text: %r -> %s" % (
            reference_label,
            ", ".join("0x%04X" % value for value in target_label_ids)
            or "not found",
        ),
        "  OTA descriptor words: %s -> desc2=%s desc3=%s" % (
            format_address(ota_descriptor.table.address),
            ota_desc2,
            ota_desc3,
        ),
    ]
    if self_checks:
        recovered = sum(item.status == "recovered" for item in self_checks)
        missed = sum(item.status == "missed" for item in self_checks)
        wrong = sum(item.status == "wrong" for item in self_checks)
        report.extend((
            "",
            "Self-check:",
            "  recovered: %d" % recovered,
            "  missed: %d" % missed,
            "  wrong: %d" % wrong,
            "  details: %s" % (output / "self_check.tsv"),
        ))
    else:
        wrong = 0
    report.extend((
        "",
        "Manual review required:",
        "  - confirm every native function entry and ABI",
        "  - confirm each hook/callsite and expected stock bytes",
        "  - confirm the erased APPL tail is unused by the release",
        "  - confirm desc2/desc3 at the transferred verifier table",
        "  - build all payloads and run the patcher against a disposable copy",
        "",
    ))
    (output / "REPORT.txt").write_text(
        "\n".join(report), encoding="ascii", newline="\n"
    )

    print("APPX %s -> %s" % (reference_id.appx_key, target_id.appx_key))
    print("output: %s" % output)
    print("vars: %d definitions" % len(target_fw.name_buckets))
    print(
        "stubs: %d strong candidates, %d unresolved" %
        (strong_stubs, unresolved_stubs)
    )
    print("code cave candidate: 0x%08X..0x%08X" % (cave_start, cave_end))
    if self_checks:
        print(
            "self-check: %d recovered, %d missed, %d wrong" %
            (recovered, missed, wrong)
        )
    print("review: %s" % (output / "REPORT.txt"))
    return 1 if wrong else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Generate candidate stubs, variable IDs, patcher snippets, and "
            "integration notes for a new Air11 APPX version."
        )
    )
    parser.add_argument("firmware", help="new 2 MiB Air11 firmware image")
    parser.add_argument(
        "--reference",
        required=True,
        help="known firmware image whose registered version should be ported",
    )
    parser.add_argument(
        "-o", "--output",
        help="output directory (default: tmp/as11-version-APPX_KEY)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="replace files in an existing output directory",
    )
    parser.add_argument(
        "--self-check",
        action="store_true",
        help="compare candidates with reviewed data for a known target version",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        return prepare(args)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    raise SystemExit(main())

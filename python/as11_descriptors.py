#!/usr/bin/env python3

import argparse
import os
import math
import re
import shlex
import struct
import sys
import tempfile
import textwrap
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation


# Keep CONF discovery local so this file remains usable as a standalone tool.
@dataclass(frozen=True)
class DataItemLayout:
    g1_count: int
    g2_base: int
    g2_count: int
    g3_base: int
    g3_count: int
    g5_base: int
    g5_count: int

    @property
    def g1_base(self):
        return 0

    @property
    def max_var_id(self):
        return self.g5_base + self.g5_count - 1


@dataclass(frozen=True)
class EdfSchemaLayout:
    stream_count: int
    event_count: int
    event_stride: int


@dataclass(frozen=True)
class DataRuleRegistration:
    rule_id: int
    callback: int
    source_kind: str
    source_offset: int


def _u16(data, off):
    return data[off] | (data[off + 1] << 8)


def _u32(data, off):
    return (_u16(data, off) | (_u16(data, off + 2) << 16))


def discover_conf_global_count(data, master_table_off,
                               flash_base=0x08000000,
                               conf_offset=0x20000,
                               conf_size=0x20000):
    """Return the number of CONF globals[] roots present in the image.

    Releases through data version 11 end at g[18]. Later releases append the
    g[19] ConfigurationProfiles source-list header. Validate that optional
    root by its pointer and header instead of consuming the following table.
    """
    if not 0 <= master_table_off <= len(data) - 19 * 4:
        raise ValueError("CONF globals table is outside the image")

    conf_end = min(len(data), conf_offset + conf_size)
    for index in range(19):
        if index == 11:
            continue
        pointer = _u32(data, master_table_off + index * 4)
        off = pointer - flash_base
        if not conf_offset <= off < conf_end:
            raise ValueError(
                "CONF globals[%d] is not a CONF pointer" % index
            )

    has_g19 = False
    if master_table_off <= len(data) - 20 * 4:
        pointer = _u32(data, master_table_off + 19 * 4)
        header_off = pointer - flash_base
        if conf_offset <= header_off <= conf_end - 8:
            count = data[header_off + 4]
            list_off = _u32(data, header_off) - flash_base
            has_g19 = (
                data[header_off + 5:header_off + 8] == b"\x00\x00\x00" and
                conf_offset <= list_off <= conf_end - count * 2
            )
    if has_g19:
        return 20
    if _u32(data, conf_offset) >= 14:
        raise ValueError("CONF globals[19] header is missing or invalid")
    return 19


def _decode_thumb2_branch(data, off, flash_base=0x08000000):
    hw1 = _u16(data, off)
    hw2 = _u16(data, off + 2)
    if (hw1 & 0xF800) != 0xF000:
        raise ValueError("not a Thumb-2 branch instruction")
    branch_class = hw2 & 0xD000
    if branch_class == 0xD000:
        kind = "bl"
    elif branch_class == 0x9000:
        kind = "b.w"
    else:
        raise ValueError("not a Thumb-2 BL/B.W instruction")

    sign = (hw1 >> 10) & 1
    j1 = (hw2 >> 13) & 1
    j2 = (hw2 >> 11) & 1
    i1 = 1 ^ (j1 ^ sign)
    i2 = 1 ^ (j2 ^ sign)
    immediate = (
        (sign << 24) | (i1 << 23) | (i2 << 22) |
        ((hw1 & 0x03FF) << 12) | ((hw2 & 0x07FF) << 1)
    )
    if sign:
        immediate -= 1 << 25
    target_address = flash_base + off + 4 + immediate
    return target_address - flash_base, kind


def _decode_thumb_bl_target(data, off, flash_base=0x08000000):
    target, kind = _decode_thumb2_branch(data, off, flash_base)
    if kind != "bl":
        raise ValueError("not a Thumb-2 BL instruction")
    return target


_THUMB_BL_CANDIDATE = re.compile(
    rb"(?=.[\xf0-\xf7].[\xd0-\xdf\xf0-\xff])", re.DOTALL
)


def _thumb_bl_offsets(data, start=0):
    for match in _THUMB_BL_CANDIDATE.finditer(data, start):
        if not match.start() & 1:
            yield match.start()


def _globals_table_from_call(data, call_off, conf_offset, conf_size,
                             flash_base):
    getter = _decode_thumb_bl_target(data, call_off, flash_base)
    conf_end = min(len(data), conf_offset + conf_size)
    if (not conf_offset <= getter <= conf_end - 8 or
            data[getter:getter + 4] != b"\x00\x48\x70\x47"):
        raise ValueError("call does not resolve to the CONF globals getter")
    master_table = _u32(data, getter + 4) - flash_base
    if not conf_offset <= master_table <= conf_end - 0x50:
        raise ValueError("CONF globals table is outside the image")
    return master_table


_DATA_RULE_REGISTER_RANGE_PATTERN = re.compile(
    rb"\x70\xb5\x04\x46\x0d\x46\x16\x46\x05\xe0"
    rb"\x6a\x68\x15\xf9\x08\x1b\x20\x46"
    rb".{4}\xb5\x42\xf7\xd1\x70\xbd",
    re.DOTALL,
)

_DYNAMIC_BOUNDS_COUNT_PATTERN = re.compile(
    rb"\x90\xf9\x1a\x00(.)\x28\x01\xda"
    rb"\x01\x20\x00\xe0\x00\x20\xc0\xb2\x10\xbd",
    re.DOTALL,
)


def discover_dynamic_bounds_count(data, appx_offset=0x40000):
    """Recover the runtime numeric-bounds slot count from its APPL test."""
    matches = list(_DYNAMIC_BOUNDS_COUNT_PATTERN.finditer(data, appx_offset))
    if len(matches) != 1:
        raise ValueError(
            "expected one dynamic-bounds count test, found %d" % len(matches)
        )
    count = matches[0].group(1)[0]
    if count == 0 or count >= 0x80:
        raise ValueError("dynamic-bounds slot count is outside 1..127")
    return count


def _thumb2_branches_to(data, target, start):
    for off in range(start, len(data) - 3, 2):
        try:
            branch_target, kind = _decode_thumb2_branch(data, off)
        except (IndexError, ValueError):
            continue
        if branch_target == target:
            yield off, kind


def _decode_pc_relative_address(data, end_off, register):
    """Decode the ADR/ADDW immediately ending at end_off."""
    off = end_off - 2
    hw = _u16(data, off)
    if (hw & 0xF800) == 0xA000 and ((hw >> 8) & 7) == register:
        return ((off + 4) & ~3) + ((hw & 0xFF) << 2)

    off = end_off - 4
    hw1 = _u16(data, off)
    hw2 = _u16(data, off + 2)
    if ((hw1 & 0xFBFF) == 0xF20F and
            ((hw2 >> 8) & 0xF) == register):
        return ((off + 4) & ~3) + _thumb_imm12(hw1, hw2)
    raise ValueError("unrecognized PC-relative address instruction")


def _decode_add_immediate(data, off, dest, source):
    hw = _u16(data, off)
    if (hw & 0xFE00) == 0x1C00:
        if (hw & 7) == dest and ((hw >> 3) & 7) == source:
            return (hw >> 6) & 7, off + 2

    hw1 = hw
    hw2 = _u16(data, off + 2)
    if ((hw1 & 0xFBF0) == 0xF100 and (hw1 & 0xF) == source and
            ((hw2 >> 8) & 0xF) == dest):
        return _thumb_imm12(hw1, hw2), off + 4
    raise ValueError("unrecognized ADD-immediate instruction")


def _decode_data_rule_table_bounds(data, branch_off):
    size, end_off = _decode_add_immediate(
        data, branch_off - 8, dest=2, source=1
    )
    if end_off != branch_off - 4:
        raise ValueError("data-rule table size instruction is misplaced")

    start = _decode_pc_relative_address(data, branch_off - 8, register=1)

    end = start + size
    if size == 0 or size % 8:
        raise ValueError("data-rule table size is not a nonzero multiple of 8")
    if not APPX_BASE <= start < end <= len(data):
        raise ValueError("data-rule table is outside APPX")
    return start, end


def _decode_data_rule_record(data, off):
    rule_id = data[off]
    callback = _u32(data, off + 4)
    if rule_id == 0 or rule_id >= 0x80:
        raise ValueError("data-rule id is outside signed-byte range")
    if data[off + 1:off + 4] != b"\x00\x00\x00":
        raise ValueError("data-rule record has nonzero padding")
    callback_off = (callback & ~1) - 0x08000000
    if not callback & 1 or not APPX_BASE <= callback_off < len(data):
        raise ValueError("data-rule callback is not a Thumb APPX pointer")
    return rule_id, callback


def _decode_direct_data_rule_call(data, branch_off):
    mov_off = None
    rule_id = None
    for off in range(branch_off - 2, max(APPX_BASE, branch_off - 18), -2):
        hw = _u16(data, off)
        if (hw & 0xF800) == 0x2000 and ((hw >> 8) & 7) == 1:
            mov_off = off
            rule_id = hw & 0xFF
            break
    if mov_off is None or rule_id == 0 or rule_id >= 0x80:
        raise ValueError("direct data-rule registration has no static rule id")

    callback = None
    for off in range(mov_off - 2, max(APPX_BASE, mov_off - 10), -2):
        hw = _u16(data, off)
        if (hw & 0xF800) == 0x4800 and ((hw >> 8) & 7) == 2:
            literal = ((off + 4) & ~3) + ((hw & 0xFF) << 2)
            if 0 <= literal <= len(data) - 4:
                callback = _u32(data, literal)
                break
        if off + 4 <= mov_off:
            hw1 = hw
            hw2 = _u16(data, off + 2)
            if ((hw1 & 0xFBFF) == 0xF20F and
                    ((hw2 >> 8) & 0xF) == 2):
                callback = (
                    0x08000000 + ((off + 4) & ~3) +
                    _thumb_imm12(hw1, hw2)
                )
                break
    if callback is None:
        raise ValueError("direct data-rule registration has no static callback")

    callback_off = (callback & ~1) - 0x08000000
    if not callback & 1 or not APPX_BASE <= callback_off < len(data):
        raise ValueError("direct data-rule callback is not a Thumb APPX pointer")
    return rule_id, callback


def discover_data_rule_registrations(data, appx_offset=0x40000):
    """Recover the APPL data-rule callback map from registration code."""
    matches = list(_DATA_RULE_REGISTER_RANGE_PATTERN.finditer(data, appx_offset))
    if len(matches) != 1:
        raise ValueError(
            "expected one data-rule range registrar, found %d" % len(matches)
        )
    range_off = matches[0].start()
    set_rule_off = _decode_thumb_bl_target(data, range_off + 18)

    registrations = []
    # Most subsystems tail-call the range registrar with the start and end of
    # an inline array of {u8 rule_id, padding, u32 callback} records.
    for branch_off, _kind in _thumb2_branches_to(data, range_off, appx_offset):
        start, end = _decode_data_rule_table_bounds(data, branch_off)
        for off in range(start, end, 8):
            rule_id, callback = _decode_data_rule_record(data, off)
            registrations.append(DataRuleRegistration(
                rule_id, callback, "table", off
            ))

    internal_call = range_off + 18
    # A few singleton subsystems register one literal ID/callback pair.
    for branch_off, _kind in _thumb2_branches_to(
            data, set_rule_off, appx_offset):
        if branch_off == internal_call:
            continue
        rule_id, callback = _decode_direct_data_rule_call(data, branch_off)
        registrations.append(DataRuleRegistration(
            rule_id, callback, "direct", branch_off
        ))

    by_id = {}
    for registration in registrations:
        previous = by_id.get(registration.rule_id)
        if previous is not None:
            raise ValueError(
                "data-rule id 0x%02X is registered more than once" %
                registration.rule_id
            )
        by_id[registration.rule_id] = registration
    if not by_id:
        raise ValueError("no data-rule registrations found")
    return by_id


def _ror32(value, count):
    count &= 31
    if count == 0:
        return value & 0xFFFFFFFF
    return ((value >> count) | (value << (32 - count))) & 0xFFFFFFFF


def _thumb_expand_imm12(imm12):
    imm8 = imm12 & 0xFF
    mode = (imm12 >> 8) & 3
    if (imm12 >> 10) == 0:
        if mode == 0:
            return imm8
        if imm8 == 0:
            raise ValueError("invalid Thumb modified immediate")
        if mode == 1:
            return (imm8 << 16) | imm8
        if mode == 2:
            return (imm8 << 24) | (imm8 << 8)
        return imm8 * 0x01010101

    unrotated = 0x80 | (imm12 & 0x7F)
    return _ror32(unrotated, (imm12 >> 7) & 0x1F)


def _thumb_imm12(hw1, hw2):
    return (((hw1 >> 10) & 1) << 11) | (((hw2 >> 12) & 7) << 8) | (hw2 & 0xFF)


def _decode_sub_r1_imm(data, off):
    if data[off + 1] == 0x39:
        return data[off], off + 2

    hw1 = _u16(data, off)
    hw2 = _u16(data, off + 2)
    if hw1 == 0xF2A1 and ((hw2 >> 8) & 0xF) == 1:
        return _thumb_imm12(hw1, hw2), off + 4
    if hw1 == 0xF5B1 and ((hw2 >> 8) & 0xF) == 1:
        return _thumb_expand_imm12(_thumb_imm12(hw1, hw2)), off + 4
    raise ValueError("unrecognized DataItem range-base instruction")


def _decode_cmp_r1_imm(data, off):
    if data[off + 1] == 0x29:
        return data[off], off + 2

    hw1 = _u16(data, off)
    hw2 = _u16(data, off + 2)
    if hw1 == 0xF240 and ((hw2 >> 8) & 0xF) == 2:
        if data[off + 4:off + 6] != b"\x91\x42":
            raise ValueError("DataItem range count is not compared through r2")
        imm = ((hw1 & 0xF) << 12) | _thumb_imm12(hw1, hw2)
        return imm, off + 6
    if hw1 == 0xF5B1 and ((hw2 >> 8) & 0xF) == 0xF:
        return _thumb_expand_imm12(_thumb_imm12(hw1, hw2)), off + 4
    raise ValueError("unrecognized DataItem range-count instruction")


def _decode_sub_r0_imm(data, off):
    if data[off + 1] == 0x38:
        return data[off], off + 2

    hw1 = _u16(data, off)
    hw2 = _u16(data, off + 2)
    if hw1 == 0xF240 and ((hw2 >> 8) & 0xF) == 1:
        if data[off + 4:off + 6] != b"\x40\x1a":
            raise ValueError("DataItem range base is not subtracted through r1")
        imm = ((hw1 & 0xF) << 12) | _thumb_imm12(hw1, hw2)
        return imm, off + 6
    if hw1 == 0xF5B0 and ((hw2 >> 8) & 0xF) == 0:
        return _thumb_expand_imm12(_thumb_imm12(hw1, hw2)), off + 4
    raise ValueError("unrecognized DataItem index subtraction")


def _parse_range_mapper(data, off):
    if data[off:off + 4] != b"\x01\x00\x09\xb2":
        raise ValueError("not a DataItem range mapper")
    off += 4

    base, off = _decode_sub_r1_imm(data, off)
    count, off = _decode_cmp_r1_imm(data, off)
    if data[off:off + 6] != b"\x02\xd3\x47\xf6\xff\x70":
        raise ValueError("DataItem range rejection does not match")
    off += 6
    if data[off + 1] != 0xE0:
        raise ValueError("DataItem range rejection branch does not match")
    off += 2

    subtract_base, off = _decode_sub_r0_imm(data, off)
    if subtract_base != base or data[off:off + 4] != b"\x00\xb2\x70\x47":
        raise ValueError("DataItem range mapper return path does not match")
    return base, count, off + 4


def _parse_g1_mapper(data, off, expected_count):
    expected = b"\x01\x00\x09\xb2" + bytes((expected_count, 0x29))
    tail = b"\x01\xdb\x47\xf6\xff\x70\x00\xb2\x70\x47"
    if expected_count > 0xFF or data[off:off + 6] != expected:
        raise ValueError("DataItem g1 boundary does not match")
    if data[off + 6:off + 16] != tail:
        raise ValueError("DataItem g1 rejection path does not match")
    return off + 16


def discover_dataitem_layout(data, appx_offset=0x40000):
    """Recover DataItem var-id ranges from the APPX factory mappers.

    The four adjacent mapper functions are the firmware's authoritative type
    dispatch boundaries for g[1], g[2], g[3], and g[5].
    """
    marker = b"\x01\x00\x09\xb2"
    matches = []
    off = data.find(marker, appx_offset)
    while off >= 0:
        try:
            g2_base, g2_count, next_off = _parse_range_mapper(data, off)
            g3_base, g3_count, next_off = _parse_range_mapper(data, next_off)
            g5_base, g5_count, next_off = _parse_range_mapper(data, next_off)
            _parse_g1_mapper(data, next_off, g2_base)
            if g3_base != g2_base + g2_count:
                raise ValueError("g2 and g3 var-id ranges are not contiguous")
            if g5_base != g3_base + g3_count:
                raise ValueError("g3 and g5 var-id ranges are not contiguous")
            if min(g2_count, g3_count, g5_count) <= 0:
                raise ValueError("empty DataItem descriptor range")
            matches.append(DataItemLayout(
                g1_count=g2_base,
                g2_base=g2_base,
                g2_count=g2_count,
                g3_base=g3_base,
                g3_count=g3_count,
                g5_base=g5_base,
                g5_count=g5_count,
            ))
        except (IndexError, ValueError):
            pass
        off = data.find(marker, off + 2)

    unique = list(dict.fromkeys(matches))
    if len(unique) != 1:
        raise ValueError(
            "expected one DataItem factory range-map cluster, found %d" % len(unique)
        )
    return unique[0]


def discover_rpc_json_permission_count(data, appx_offset=0x40000):
    """Recover the g[18] node count from the RPC `!NN` resolver bound."""
    pattern = re.compile(
        rb"\x00\x9a\x61\x19\x91\x42\x06\xd1"
        rb"(.)\x28\x04\xd2\x0c\x21\x03\xa3\x48\x43\x18\x44"
        rb"\x00\xe0\x00\x20",
        re.DOTALL,
    )
    counts = {
        match.group(1)[0]
        for match in pattern.finditer(data, appx_offset)
        if match.group(1)[0] != 0
    }
    if len(counts) != 1:
        raise ValueError(
            "expected one RPC schema-reference node bound, found %d" %
            len(counts)
        )
    return counts.pop()


_G12_COUNT_PATTERN = re.compile(
    rb"\x3e\xb5\x01\x46\x68\x46"
    rb".{4}(?P<bl_globals>.{4})"
    rb"\x04\x6b\x00\x25\x24\x20\x68\x43\x21\x58\x68\x46"
    rb".{4}"
    rb"\x20\xb9\x6d\x1c"
    rb"(?P<count>[\x01-\x7f])\x2d\xf5\xdb(?P=count)\x20"
    rb"\x3e\xbd\x68\xb2\x3e\xbd",
    re.DOTALL,
)


def discover_event_definition_count(
        data, appx_offset=0x40000, conf_offset=0x20000,
        conf_size=0x20000, flash_base=0x08000000):
    """Recover the g[12] row count from the APPX selector resolver."""
    matches = list(_G12_COUNT_PATTERN.finditer(data, appx_offset))
    if len(matches) != 1:
        raise ValueError(
            "expected one g[12] selector resolver, found %d" % len(matches)
        )
    match = matches[0]
    _globals_table_from_call(
        data, match.start("bl_globals"), conf_offset, conf_size, flash_base
    )
    return match.group("count")[0]


_G14_ENABLED_PATTERN = re.compile(
    rb"\x10\xb5\x0c\x46(?P<bl_globals>.{4})"
    rb"\x34\x21\x80\x6b\x14\xfb\x01\xf1\x01\x44"
    rb"\x91\xf8\x28\x00\x00\xb1\x01\x20\x10\xbd",
    re.DOTALL,
)


def _call_site_loop_count(data, call_off, search_bytes, compare_bytes,
                          branch_conditions):
    end = min(len(data) - 4, call_off + search_bytes)
    for add_off in range(call_off + 4, end, 2):
        add = _u16(data, add_off)
        if (add & 0xFE00) != 0x1C00 or ((add >> 6) & 7) != 1:
            continue
        source = (add >> 3) & 7
        dest = add & 7
        if source != dest:
            continue
        for cmp_off in range(
                add_off + 2, min(end, add_off + compare_bytes), 2):
            compare = _u16(data, cmp_off)
            if (compare & 0xF800) != 0x2800 or ((compare >> 8) & 7) != dest:
                continue
            immediate = compare & 0xFF
            branch = _u16(data, cmp_off + 2)
            condition = (branch >> 8) & 0xF
            if ((branch & 0xF000) != 0xD000 or
                    condition not in branch_conditions):
                continue
            displacement = branch & 0xFF
            if displacement & 0x80:
                displacement -= 0x100
            target = cmp_off + 4 + displacement * 2
            if target <= call_off <= cmp_off:
                return immediate + (condition in (0x9, 0xD))
    return None


def _accessor_call_counts(data, accessors, appx_offset, flash_base,
                          min_calls, search_bytes, compare_bytes,
                          branch_conditions):
    names_by_target = {target: name for name, target in accessors.items()}
    counts = {name: [] for name in accessors}
    for call_off in _thumb_bl_offsets(data, appx_offset):
        try:
            target = _decode_thumb_bl_target(data, call_off, flash_base)
        except (IndexError, ValueError):
            continue
        name = names_by_target.get(target)
        if name is None:
            continue
        count = _call_site_loop_count(
            data, call_off, search_bytes, compare_bytes, branch_conditions
        )
        if count is not None and 1 <= count <= 32:
            counts[name].append(count)

    resolved = {}
    for name, values in counts.items():
        if len(values) < min_calls or len(set(values)) != 1:
            raise ValueError(
                "%s accessor loops do not agree on one count: %r" %
                (name, values)
            )
        resolved[name] = values[0]
    return resolved


def discover_periodic_collection_count(
        data, appx_offset=0x40000, conf_offset=0x20000,
        conf_size=0x20000, flash_base=0x08000000):
    """Recover the g[14] row count from its APPX pipeline loops."""
    helpers = list(_G14_ENABLED_PATTERN.finditer(data, appx_offset))
    if len(helpers) != 1:
        raise ValueError(
            "expected one g[14] enabled helper, found %d" % len(helpers)
        )
    helper_match = helpers[0]
    helper_off = helper_match.start()
    _globals_table_from_call(
        data, helper_match.start("bl_globals"),
        conf_offset, conf_size, flash_base
    )
    return _accessor_call_counts(
        data, {"g[14]": helper_off}, appx_offset, flash_base,
        min_calls=3, search_bytes=0x120, compare_bytes=10,
        branch_conditions=(0xB, 0xD),
    )["g[14]"]


_G16_SCHEMA_ACCESSOR_PATTERN = re.compile(
    rb"\x10\xb5\x0c\x46(?P<bl_globals>.{4})"
    rb"\x00\x6c\x00\xeb\x04\x11\xb1\xf9\x04\x20"
    rb"\x01\x2a\x01\xdb\x01\x20\x10\xbd\x00\x20\x10\xbd",
    re.DOTALL,
)

_G17_SCHEMA_ACCESSOR_PATTERN = re.compile(
    rb"\x10\xb5\x0c\x46(?P<bl_globals>.{4})"
    rb"(?P<stride>\x14|\x1c)\x21\x40\x6c\x14\xfb\x01\xf1"
    rb"\x01\x44(?P<enable_load>\x08\x7a|\x08\x7b)\x10\xbd",
    re.DOTALL,
)


def _one_schema_accessor(data, pattern, appx_offset, name):
    matches = list(pattern.finditer(data, appx_offset))
    if len(matches) != 1:
        raise ValueError(
            "expected one %s schema accessor, found %d" %
            (name, len(matches))
        )
    return matches[0]


def discover_edf_schema_layout(
        data, appx_offset=0x40000, conf_offset=0x20000,
        conf_size=0x20000, flash_base=0x08000000):
    """Recover g[16]/g[17] counts and the g[17] stride from APPX loops."""
    stream = _one_schema_accessor(
        data, _G16_SCHEMA_ACCESSOR_PATTERN, appx_offset, "g[16]"
    )
    event = _one_schema_accessor(
        data, _G17_SCHEMA_ACCESSOR_PATTERN, appx_offset, "g[17]"
    )

    master_tables = {
        _globals_table_from_call(
            data, match.start("bl_globals"),
            conf_offset, conf_size, flash_base
        )
        for match in (stream, event)
    }
    if len(master_tables) != 1:
        raise ValueError("g[16] and g[17] accessors use different globals getters")
    counts = _accessor_call_counts(
        data, {"g[16]": stream.start(), "g[17]": event.start()},
        appx_offset, flash_base, min_calls=2, search_bytes=0x180,
        compare_bytes=12, branch_conditions=(0x3, 0x9, 0xB, 0xD),
    )

    event_stride = event.group("stride")[0]
    enable_load = event.group("enable_load")
    expected_load = b"\x08\x7a" if event_stride == 0x14 else b"\x08\x7b"
    if enable_load != expected_load:
        raise ValueError("g[17] stride and writer-enable offset do not agree")
    return EdfSchemaLayout(
        stream_count=counts["g[16]"],
        event_count=counts["g[17]"],
        event_stride=event_stride,
    )


try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

FLASH_BASE = 0x08000000
CONF_BASE = 0x20000
CONF_SIZE = 0x20000
APPX_BASE = 0x40000
LONG_NAME_SEARCH_BASE = APPX_BASE

BOOT_VERSION_OFF = 0x4000
BOOT_VERSION_SIZE = 0x20
CONF_GIT_OFF = CONF_BASE + 0x68
CONF_GIT_SIZE = 0x0A
CONF_VID_OFF = CONF_BASE + 0x0C
CONF_DATA_MODEL_OFF = CONF_BASE + 0x72
CONF_DATA_MODEL_SIZE = 0x0B
CONF_DATA_MODEL_HASH_OFF = CONF_BASE + 0x7D
CONF_DATA_MODEL_HASH_SIZE = 0x0B
ENUM_SYMBOL_SEARCH_BASE = 0xF0000
LONG_NAME_PRIMARY_RUN_MIN = 500
ENUM_SYMBOL_PRIMARY_RUN_MIN = 500

G1_STRIDE = 10
G2_STRIDE = 32
G3_STRIDE = 20
G5_STRIDE = 16
G6_STORAGE_SET_COUNT = 7
G6_STORAGE_SET_STRIDE = 16
G7_PDL_HEADER_SIZE = 12
G8_BUCKET_COUNT = 26
G8_BUCKET_HEADER_STRIDE = 8
G10_STRIDE = 14
G12_EVENT_DEFINITION_STRIDE = 36
G13_JSON_PAYLOAD_OVERRIDE_STRIDE = 6
G13_JSON_PAYLOAD_OVERRIDE_COUNT = 21
G14_COLLECTION_STRIDE = 0x34
G15_SUMMARY_HEADER_SIZE = 16
G16_STREAM_SCHEMA_STRIDE = 16
G17_EVENT_SCHEMA_SIZE = 28
G17_LEGACY_EVENT_SCHEMA_SIZE = 20
G18_PERMISSION_STRIDE = 2
G19_CHANGE_SOURCE_HEADER_SIZE = 8
CONF_HEADER_SIZE = 0x100
SUMMARY_STRIDE = 36

MODE_NAMES = [
    "CPAP", "AutoSet", "HerAuto", "Spont", "ST",
    "Timed", "VAuto", "ASV", "ASVAuto", "iVAPS", "PAC",
]

MODE_PREFIXES = {
    0: "Cpap-",
    1: "AutoSet-",
    2: "HerAuto-",
    3: "Spont-",
    4: "ST-",
    5: "Timed-",
    6: "VAuto-",
    7: "ASV-",
    8: "ASVAuto-",
    9: "iVAPS-",
    10: "PAC-",
}

DATAITEM_FLAG_NAMES = (
    (0x0001, "ACT"),
    (0x0002, "VIS"),
    (0x0004, "MOD"),
    (0x0008, "SGN"),
    (0x0010, "INH"),
    (0x0020, "VAL"),
    (0x0040, "ULK"),
    (0x0080, "RAW"),
    (0x0100, "MON"),
    (0x0200, "RPC"),
    (0x0400, "RPW"),
    (0x0800, "PST"),
)

LANGUAGE_NAMES = [
    "English", "French", "German", "Italian", "SpanishEU", "SpanishUS",
    "PortugueseEU", "PortugueseUS", "Dutch", "Swedish", "Danish",
    "Norwegian", "Finnish", "Russian", "Turkish", "Polish", "Czech",
    "Greek", "Estonian", "ChineseTraditional", "ChineseSimplified",
    "Japanese", "Korean", "Croatian", "Hungarian", "Romanian", "Slovenian",
]

LANGUAGE_CODES = {
    "en": 0,
    "fr": 1,
    "de": 2,
    "it": 3,
    "es": 4,
    "es-es": 4,
    "es-us": 5,
    "pt": 6,
    "pt-pt": 6,
    "pt-br": 7,
    "nl": 8,
    "sv": 9,
    "da": 10,
    "no": 11,
    "nb": 11,
    "fi": 12,
    "ru": 13,
    "tr": 14,
    "pl": 15,
    "cs": 16,
    "el": 17,
    "et": 18,
    "zh-tw": 19,
    "zh": 20,
    "zh-cn": 20,
    "ja": 21,
    "jp": 21,
    "ko": 22,
    "kr": 22,
    "hr": 23,
    "hu": 24,
    "ro": 25,
    "sl": 26,
}

GUI_TEXT_RECORD_BITS = 20
GUI_TEXT_CODE_BITS = 17

GUI_TEXT_POOL_MODEL_C_OFF = 8
GUI_TEXT_POOL_MODEL_A_OFF = 16
GUI_TEXT_POOL_MODEL_B_OFF = 24
GUI_TEXT_POOL_STATE_OFF = 36
GUI_TEXT_POOL_TRANSITION_OFF = 48
GUI_TEXT_POOL_STRING_PTR_OFF = 52
GUI_TEXT_POOL_RECORD_BASE_OFF = 60

def crc16_ccitt_false(data, crc=0xFFFF):
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            if crc & 0x8000:
                crc = ((crc << 1) ^ 0x1021) & 0xFFFF
            else:
                crc = (crc << 1) & 0xFFFF
    return crc


class DescriptorEditField:
    def __init__(self, name, attr, offset, fmt=None, kind="int",
                 aliases=()):
        self.name = name
        self.attr = attr
        self.offset = offset
        self.fmt = fmt
        self.kind = kind
        self.aliases = tuple(aliases)

    @property
    def size(self):
        if self.kind == "mode_visibility":
            return len(MODE_NAMES)
        return struct.calcsize("<" + self.fmt)

    @property
    def signed(self):
        return self.fmt in ("b", "h", "i")

    def read_storage(self, fw, rec):
        off = rec["offset"] + self.offset
        if self.kind == "mode_visibility":
            fw._check_range(off, self.size)
            return bytes(fw.data[off:off + self.size])
        if self.size == 1:
            return fw.u8(off)
        if self.fmt == "H":
            return fw.u16(off)
        if self.fmt == "h":
            return fw.i16(off)
        if self.fmt == "I":
            return fw.u32(off)
        if self.fmt == "i":
            return fw.i32(off)
        raise ValueError("unsupported edit field format %r" % self.fmt)

    def write_storage(self, fw, rec, value):
        off = rec["offset"] + self.offset
        if self.kind == "mode_visibility":
            if len(value) != self.size:
                raise ValueError(
                    "mode visibility field requires %d bytes" % self.size
                )
            fw.write_bytes(off, value)
            return
        fw.write_struct(off, self.fmt, value)

    def normalize_int(self, value):
        bits = self.size * 8
        if self.signed:
            minimum = -(1 << (bits - 1))
            maximum = (1 << (bits - 1)) - 1
            if maximum < value < (1 << bits):
                value -= 1 << bits
        else:
            minimum = 0
            maximum = (1 << bits) - 1
        if not minimum <= value <= maximum:
            raise ValueError(
                "%s value %d does not fit %d-bit %s storage" %
                (self.name, value, bits,
                 "signed" if self.signed else "unsigned")
            )
        return value


AS11_DESCRIPTOR_FIELDS = {
    "g1": (
        DescriptorEditField("flags", "flags", 0x00, "H", "hex16"),
        DescriptorEditField("data_rule", "data_rule_id", 0x02, "B",
                            "hex8", aliases=("data_rule_id",)),
        DescriptorEditField("linked_counter", "linked_counter_index", 0x04,
                            "H", "hex16", aliases=("linked_counter_index",)),
        DescriptorEditField("event_queue", "change_event_queue_index", 0x06,
                            "B", "hex8",
                            aliases=("change_event_queue_index",)),
        DescriptorEditField("buffer_capacity", "buffer_capacity", 0x08, "H",
                            aliases=("max_len", "max_length")),
    ),
    "g2": (
        DescriptorEditField("flags", "flags", 0x00, "H", "hex16"),
        DescriptorEditField("data_rule", "data_rule_id", 0x02, "B",
                            "hex8", aliases=("data_rule_id",)),
        DescriptorEditField("linked_counter", "linked_counter_index", 0x04,
                            "H", "hex16", aliases=("linked_counter_index",)),
        DescriptorEditField("event_queue", "change_event_queue_index", 0x06,
                            "B", "hex8",
                            aliases=("change_event_queue_index",)),
        DescriptorEditField("default", "default", 0x08, "i", "scaled"),
        DescriptorEditField("max", "max", 0x0C, "i", "scaled"),
        DescriptorEditField("min", "min", 0x10, "i", "scaled"),
        DescriptorEditField("decimal_places", "decimal_places", 0x14, "B"),
        DescriptorEditField("scale", "scale", 0x16, "h"),
        DescriptorEditField("step", "step", 0x18, "h", "scaled"),
        DescriptorEditField("bounds_slot", "bounds_slot", 0x1A, "B", "hex8"),
        DescriptorEditField(
            "sample_block_signal_id", "sample_block_signal_id", 0x1B, "B",
            aliases=("sample_source", "sample_source_id"),
        ),
        DescriptorEditField("quantity_class", "quantity_class", 0x1C, "B",
                            "hex8"),
    ),
    "g3": (
        DescriptorEditField("flags", "flags", 0x00, "H", "hex16"),
        DescriptorEditField("data_rule", "data_rule_id", 0x02, "B",
                            "hex8", aliases=("data_rule_id",)),
        DescriptorEditField("linked_counter", "linked_counter_index", 0x04,
                            "H", "hex16", aliases=("linked_counter_index",)),
        DescriptorEditField("event_queue", "change_event_queue_index", 0x06,
                            "B", "hex8",
                            aliases=("change_event_queue_index",)),
        DescriptorEditField("default_mask", "default_mask", 0x08, "I",
                            "mask", aliases=("default",)),
        DescriptorEditField("editable_mask", "editable_mask", 0x0C, "I",
                            "mask", aliases=("editable",)),
        DescriptorEditField("bit_count", "bit_count", 0x10, "B"),
        DescriptorEditField("selection_order", "selection_order_offset", 0x12,
                            "H", "hex16",
                            aliases=("priority_list", "priority_list_offset")),
    ),
    "g5": (
        DescriptorEditField("flags", "flags", 0x00, "H", "hex16"),
        DescriptorEditField("data_rule", "data_rule_id", 0x02, "B",
                            "hex8", aliases=("data_rule_id",)),
        DescriptorEditField("linked_counter", "linked_counter_index", 0x04,
                            "H", "hex16", aliases=("linked_counter_index",)),
        DescriptorEditField("event_queue", "change_event_queue_index", 0x06,
                            "B", "hex8",
                            aliases=("change_event_queue_index",)),
        DescriptorEditField("default_option", "default_option", 0x08, "B",
                            aliases=("default_opt",)),
        DescriptorEditField("option_count", "n_options", 0x09, "B",
                            aliases=("n_opts", "n_options")),
        DescriptorEditField("reserved", "reserved", 0x0A, "H", "hex16"),
        DescriptorEditField("option_mask", "option_mask", 0x0C, "I", "mask",
                            aliases=("mask",)),
    ),
    "g10": (
        DescriptorEditField("visibility", "mode_visibility", 0x02, None,
                            "mode_visibility"),
    ),
}


def editable_fields(arr):
    return AS11_DESCRIPTOR_FIELDS.get(arr, ())


def editable_field_map(arr):
    out = {}
    for field in editable_fields(arr):
        out[field.name.lower()] = field
        for alias in field.aliases:
            out[alias.lower()] = field
        if field.kind == "scaled":
            out[(field.name + "_raw").lower()] = field
            for alias in field.aliases:
                out[(alias + "_raw").lower()] = field
    return out


def edit_field_names(arr):
    names = []
    for field in editable_fields(arr):
        names.append(field.name)
        if field.kind == "scaled":
            names.append(field.name + "_raw")
    return names


def edit_fields_help():
    lines = [
        "assignments use VAR.FIELD=VALUE; bare numbers are decimal and 0x is hex",
        "",
        "editable fields:",
    ]
    for arr in ("g1", "g2", "g3", "g5", "g10"):
        lines.append("  %s  %s" % (arr, " ".join(edit_field_names(arr))))
    lines.extend((
        "",
        "scaled g2 fields accept display values; *_raw writes stored integers",
        "g10 visibility accepts comma/pipe/plus separated mode names or indices",
    ))
    return "\n".join(lines)


class AS11Firmware:
    def __init__(self, path, data=None):
        if data is None:
            with open(path, "rb") as f:
                self.data = bytearray(f.read())
        else:
            self.data = bytearray(data)
        self.path = path
        if len(self.data) < CONF_BASE + 0x108:
            raise ValueError("firmware image is too small for an AS11 CONF block")

        self.data_version = self.u32(CONF_BASE)
        mt_ptr = self.u32(CONF_BASE + 0x104)
        self.mt_off = self._off_for_addr(mt_ptr, 20 * 4)
        if self.mt_off is None:
            raise ValueError("globals table pointer 0x%08X is outside this image" % mt_ptr)

        self.global_count = discover_conf_global_count(self.data, self.mt_off)
        self.g = {}
        for i in range(self.global_count):
            val = self.u32(self.mt_off + i * 4)
            if FLASH_BASE <= val < FLASH_BASE + len(self.data):
                self.g[i] = val - FLASH_BASE
            else:
                self.g[i] = val
        for index in (1, 2, 3, 5):
            if not self._file_range_ok(self.g.get(index), 1):
                raise ValueError("globals[%d] does not point inside this image" % index)

        item_layout = discover_dataitem_layout(self.data, APPX_BASE)
        self.g1_count = item_layout.g1_count
        self.g2_count = item_layout.g2_count
        self.g3_count = item_layout.g3_count
        self.g5_count = item_layout.g5_count
        self.g10_count = self.g[11]

        # S11 DataItemFactory order: globals[1], globals[2], globals[3], globals[5].
        self.g1_id_base = 0
        self.g2_id_base = self.g1_count
        self.g3_id_base = self.g2_id_base + self.g2_count
        self.g5_id_base = self.g3_id_base + self.g3_count
        self.max_var_id = self.g5_id_base + self.g5_count - 1

        self.long_name_table_off = None
        self.long_name_table_count = 0
        self._long_names = None
        self.name_buckets = self._build_name_buckets()
        self.opt_table_off = None
        self.opt_table_count = 0
        self.opt_entries = None
        self.opt_by_type = {}
        self.gui_text_cache = {}
        self.gui_text_pool_addr = None
        self.gui_text_record_base = None
        self.gui_text_markov_stream = None
        self.gui_text_model_a = None
        self.gui_text_model_b = None
        self.gui_text_model_c = None
        self.gui_text_state_table = None
        self.gui_text_transition_table = None
        self.gui_text_lang_stride = None
        self.gui_text_count = None
        self.gui_text_available = None
        self._edf_schema_layout = None
        self._data_rule_registrations = None
        self._dynamic_bounds_count = None

    @property
    def long_names(self):
        if self._long_names is None:
            self._long_names = self._build_long_names()
        return self._long_names

    def _file_range_ok(self, off, size=1):
        return isinstance(off, int) and size >= 0 and 0 <= off <= len(self.data) - size

    def _check_range(self, off, size):
        if not self._file_range_ok(off, size):
            raise ValueError("file offset %r size %d is outside this image" %
                             (off, size))

    def u8(self, off):
        self._check_range(off, 1)
        return self.data[off]

    def i8(self, off):
        self._check_range(off, 1)
        return struct.unpack_from("<b", self.data, off)[0]

    def u16(self, off):
        self._check_range(off, 2)
        return struct.unpack_from("<H", self.data, off)[0]

    def i16(self, off):
        self._check_range(off, 2)
        return struct.unpack_from("<h", self.data, off)[0]

    def i32(self, off):
        self._check_range(off, 4)
        return struct.unpack_from("<i", self.data, off)[0]

    def u32(self, off):
        self._check_range(off, 4)
        return struct.unpack_from("<I", self.data, off)[0]

    def write_struct(self, off, fmt, value):
        self._check_range(off, struct.calcsize("<" + fmt))
        struct.pack_into("<" + fmt, self.data, off, value)

    def write_bytes(self, off, value):
        self._check_range(off, len(value))
        self.data[off:off + len(value)] = value

    def conf_crc(self):
        crc_off = CONF_BASE + CONF_SIZE - 2
        stored = int.from_bytes(self.data[crc_off:crc_off + 2], "big")
        computed = crc16_ccitt_false(self.data[CONF_BASE:crc_off])
        return stored, computed, stored == computed

    def validate_conf_crc(self):
        stored, computed, ok = self.conf_crc()
        if not ok:
            raise ValueError(
                "CONF CRC mismatch: stored=0x%04X computed=0x%04X" %
                (stored, computed)
            )

    def fix_conf_crc(self):
        crc_off = CONF_BASE + CONF_SIZE - 2
        crc = crc16_ccitt_false(self.data[CONF_BASE:crc_off])
        self.data[crc_off] = (crc >> 8) & 0xFF
        self.data[crc_off + 1] = crc & 0xFF
        return crc

    def write_output(self, path, overwrite=False):
        input_path = os.path.normcase(os.path.abspath(self.path))
        output_path = os.path.normcase(os.path.abspath(path))
        if input_path == output_path:
            raise ValueError("output path must differ from the input image")
        if os.path.exists(path) and not overwrite:
            raise FileExistsError("output file already exists: %s" % path)

        output_dir = os.path.dirname(os.path.abspath(path)) or "."
        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(
                    mode="wb", dir=output_dir, prefix=".as11-edit-",
                    delete=False) as tmp:
                tmp_path = tmp.name
                tmp.write(self.data)
                tmp.flush()
                os.fsync(tmp.fileno())
            os.replace(tmp_path, path)
        finally:
            if tmp_path and os.path.exists(tmp_path):
                os.unlink(tmp_path)

    def f32(self, off):
        self._check_range(off, 4)
        return struct.unpack_from("<f", self.data, off)[0]

    def f64(self, off):
        self._check_range(off, 8)
        return struct.unpack_from("<d", self.data, off)[0]

    def off_to_addr(self, off):
        return FLASH_BASE + off

    def ptr_to_off(self, ptr, size=1):
        return self._off_for_addr(ptr, size)

    def _off_for_addr(self, addr, size=1):
        if FLASH_BASE <= addr <= FLASH_BASE + len(self.data) - size:
            return addr - FLASH_BASE
        return None

    def _u32_addr(self, addr):
        off = self._off_for_addr(addr, 4)
        if off is None:
            raise ValueError("flash address 0x%08X is outside this image" % addr)
        return self.u32(off)

    def _string_at_ptr(self, ptr, max_len=96, allow_empty=False):
        off = self._off_for_addr(ptr)
        if off is None:
            return None
        end = self.data.find(b"\x00", off)
        if end < 0 or end - off > max_len:
            return None
        if end == off and not allow_empty:
            return None
        raw = self.data[off:end]
        if any(b < 0x20 or b > 0x7E for b in raw):
            return None
        return raw.decode("ascii")

    def _init_gui_text_decoder(self):
        if not self._discover_gui_text_tables():
            return False
        try:
            return bool(self.decode_gui_text(0, 0))
        except (ValueError, UnicodeError, IndexError, struct.error):
            self.gui_text_cache.clear()
            self.gui_text_pool_addr = None
            return False

    def _ensure_gui_text_decoder(self):
        if self.gui_text_available is None:
            self.gui_text_available = self._init_gui_text_decoder()
        return self.gui_text_available

    def _discover_gui_text_tables(self):
        best = None
        data = self.data
        data_len = len(data)
        unpack_u32 = struct.Struct("<I").unpack_from
        addr_max = FLASH_BASE + data_len - 4

        def addr_ok(addr):
            return FLASH_BASE <= addr <= addr_max

        def token_pool_ok(addr):
            off = addr - FLASH_BASE
            return (
                0 <= off <= data_len - 3
                and data[off] == 0x00
                and data[off + 1] == 0x0A
                and data[off + 2] == 0x20
            )

        for pos in range(0, data_len - 64, 4):
            markov_stream = unpack_u32(data, pos)[0]
            if not addr_ok(markov_stream):
                continue
            model_c = unpack_u32(data, pos + GUI_TEXT_POOL_MODEL_C_OFF)[0]
            model_a = unpack_u32(data, pos + GUI_TEXT_POOL_MODEL_A_OFF)[0]
            model_b = unpack_u32(data, pos + GUI_TEXT_POOL_MODEL_B_OFF)[0]
            state_table = unpack_u32(data, pos + GUI_TEXT_POOL_STATE_OFF)[0]
            transition_table = unpack_u32(
                data, pos + GUI_TEXT_POOL_TRANSITION_OFF)[0]
            pool_ptr = unpack_u32(data, pos + GUI_TEXT_POOL_STRING_PTR_OFF)[0]
            record_base = unpack_u32(data, pos + GUI_TEXT_POOL_RECORD_BASE_OFF)[0]
            needed = (
                markov_stream, model_a, model_b, model_c, state_table,
                transition_table, pool_ptr, record_base,
            )
            if any(not addr_ok(addr) for addr in needed):
                continue
            pool = unpack_u32(data, pool_ptr - FLASH_BASE)[0]
            if not (FLASH_BASE <= pool < FLASH_BASE + data_len):
                continue
            if not token_pool_ok(pool):
                continue

            for stride in self._discover_gui_text_lang_strides(record_base):
                text_count = (stride * 8) // GUI_TEXT_RECORD_BITS
                if text_count <= 0:
                    continue

                candidate = (
                    markov_stream, model_a, model_b, model_c, state_table,
                    transition_table, record_base, pool, stride, text_count,
                )
                score = self._score_gui_text_candidate(candidate)
                if score <= 0:
                    continue
                if best is None or score > best[0]:
                    best = (score, candidate)

        if best is None:
            return False

        (
            _score,
            (
                markov_stream, model_a, model_b, model_c, state_table,
                transition_table, record_base, pool, stride, text_count,
            ),
        ) = best
        self.gui_text_markov_stream = markov_stream
        self.gui_text_model_a = model_a
        self.gui_text_model_b = model_b
        self.gui_text_model_c = model_c
        self.gui_text_state_table = state_table
        self.gui_text_transition_table = transition_table
        self.gui_text_record_base = record_base
        self.gui_text_pool_addr = pool
        self.gui_text_lang_stride = stride
        self.gui_text_count = text_count
        self.gui_text_cache.clear()
        return True

    def _discover_gui_text_lang_strides(self, record_base):
        data = self.data
        data_len = len(data)
        unpack_u32 = struct.Struct("<I").unpack_from

        def first_record_value(stride, lang):
            off = record_base + lang * stride - FLASH_BASE
            if off < 0 or off + 4 > data_len:
                raise ValueError("record offset outside image")
            return unpack_u32(data, off)[0] >> (32 - GUI_TEXT_RECORD_BITS)

        viable = []
        max_stride = min(
            0x10000,
            (FLASH_BASE + data_len - record_base) // (len(LANGUAGE_NAMES) - 1),
        )
        for stride in range(0x80, max_stride):
            try:
                first_values = [
                    first_record_value(stride, lang)
                    for lang in range(min(5, len(LANGUAGE_NAMES)))
                ]
            except (ValueError, IndexError, struct.error):
                continue
            if first_values[0] != 0 or max(first_values) - min(first_values) > 1000:
                continue
            try:
                values = [
                    first_record_value(stride, lang)
                    for lang in range(len(LANGUAGE_NAMES))
                ]
            except (ValueError, IndexError, struct.error):
                continue
            spread = max(values) - min(values)
            if values[0] == 0 and spread < 5000:
                viable.append((spread, stride))
        return [stride for _spread, stride in sorted(viable)]

    def _score_gui_text_candidate(self, candidate):
        saved = (
            self.gui_text_markov_stream, self.gui_text_model_a,
            self.gui_text_model_b, self.gui_text_model_c,
            self.gui_text_state_table, self.gui_text_transition_table,
            self.gui_text_record_base, self.gui_text_pool_addr,
            self.gui_text_lang_stride, self.gui_text_count,
        )
        (
            self.gui_text_markov_stream, self.gui_text_model_a,
            self.gui_text_model_b, self.gui_text_model_c,
            self.gui_text_state_table, self.gui_text_transition_table,
            self.gui_text_record_base, self.gui_text_pool_addr,
            self.gui_text_lang_stride, self.gui_text_count,
        ) = candidate
        self.gui_text_cache.clear()
        score = 0
        try:
            for lang in range(min(3, len(LANGUAGE_NAMES))):
                for text_id in range(min(16, self.gui_text_count)):
                    text = self.decode_gui_text(text_id, lang)
                    if text and all(ch.isprintable() or ch in "\r\n\t"
                                    for ch in text):
                        score += 1
        except (ValueError, UnicodeError, IndexError, struct.error):
            score = 0
        (
            self.gui_text_markov_stream, self.gui_text_model_a,
            self.gui_text_model_b, self.gui_text_model_c,
            self.gui_text_state_table, self.gui_text_transition_table,
            self.gui_text_record_base, self.gui_text_pool_addr,
            self.gui_text_lang_stride, self.gui_text_count,
        ) = saved
        self.gui_text_cache.clear()
        return score

    def _gui_extract_bits(self, addr, start, n_bits):
        value = 0
        for k in range(n_bits):
            pos = start + k
            word = self._u32_addr(addr + (pos // 32) * 4)
            value = (value << 1) | ((word >> (31 - (pos % 32))) & 1)
        return value

    def _gui_select_record(self, addr, record_bits, index):
        return self._gui_extract_bits(addr, index * record_bits, record_bits)

    def _gui_decode_symbol(self, bitoff):
        bits = self._gui_extract_bits(self.gui_text_markov_stream, bitoff,
                                      GUI_TEXT_CODE_BITS)
        lo = 0
        hi = GUI_TEXT_CODE_BITS
        length = None
        while hi - lo > 0:
            mid = (hi + lo) // 2
            lower = self._gui_select_record(self.gui_text_model_b,
                                            GUI_TEXT_CODE_BITS, mid)
            if mid < GUI_TEXT_CODE_BITS - 1:
                upper = self._gui_select_record(self.gui_text_model_b,
                                                GUI_TEXT_CODE_BITS, mid + 1)
            else:
                upper = 0xFFFFFFFF
            prefix = bits >> (GUI_TEXT_CODE_BITS - (mid + 1))
            if prefix < lower:
                hi = mid
            elif prefix < (upper >> 1):
                length = mid + 1
                break
            else:
                lo = mid
        if length is None:
            length = lo + 1

        idx = ((bits >> (GUI_TEXT_CODE_BITS - length))
               + self._gui_select_record(self.gui_text_model_a, 9, length - 1)
               - self._gui_select_record(self.gui_text_model_b,
                                         GUI_TEXT_CODE_BITS, length - 1))
        symbol = self._gui_select_record(self.gui_text_model_c, 9, idx)
        return symbol, length

    def _gui_token_len(self, token):
        if token < 0x50:
            return 1
        if token < 0xF6:
            return 2
        return 3

    def _gui_token_off(self, token):
        if token < 0x50:
            return token
        if token < 0xF6:
            return token * 2 - 0x50
        return token * 3 - 0xF6 - 0x50

    def decode_gui_text(self, text_id, lang=0):
        key = (text_id, lang)
        if key in self.gui_text_cache:
            return self.gui_text_cache[key]
        if self.gui_text_count is None or self.gui_text_lang_stride is None:
            raise ValueError("GUI text decoder is not available")
        if not 0 <= text_id < self.gui_text_count:
            raise ValueError("GUI text id 0x%X is outside 0x000..0x%03X" %
                             (text_id, self.gui_text_count - 1))
        if not 0 <= lang < len(LANGUAGE_NAMES):
            raise ValueError("language index %d is outside 0..%d" %
                             (lang, len(LANGUAGE_NAMES) - 1))
        if self.gui_text_pool_addr is None:
            raise ValueError("GUI text decoder is not available")

        record_addr = self.gui_text_record_base + lang * self.gui_text_lang_stride
        bitoff = self._gui_select_record(record_addr, GUI_TEXT_RECORD_BITS,
                                         text_id)
        state = 0
        raw = bytearray()
        for _ in range(240):
            state_base = self._gui_select_record(self.gui_text_state_table, 14,
                                                 state)
            symbol, n_bits = self._gui_decode_symbol(bitoff)
            token = self._gui_select_record(self.gui_text_transition_table, 11,
                                            state_base + symbol)
            length = self._gui_token_len(token)
            offset = self._gui_token_off(token)
            pool_off = self._off_for_addr(self.gui_text_pool_addr + offset,
                                          length)
            if pool_off is None:
                raise ValueError("GUI text pool offset is outside this image")
            raw += self.data[pool_off:pool_off + length]
            if token == 0:
                break
            bitoff += n_bits
            state = token
            if len(raw) > 240:
                break

        text = raw.rstrip(b"\x00").decode("utf-8", errors="replace")
        self.gui_text_cache[key] = text
        return text

    def _build_long_names(self):
        data = self.data
        data_len = len(data)
        unpack_entry = struct.Struct("<IHH").unpack_from

        def string_at_ptr(ptr, max_len=96, allow_empty=False):
            off = ptr - FLASH_BASE
            if off < 0 or off >= data_len:
                return None
            end = data.find(b"\x00", off)
            if end < 0 or end - off > max_len:
                return None
            if end == off and not allow_empty:
                return None
            raw = data[off:end]
            if any(b < 0x20 or b > 0x7E for b in raw):
                return None
            return raw.decode("ascii")

        def valid_entry(off):
            if off < 0 or off + 8 > data_len:
                return None
            ptr, vid, pad = unpack_entry(data, off)
            if pad != 0:
                return None
            if not (vid < 0x1000 or vid == 0x7FFF):
                return None
            name = string_at_ptr(ptr, allow_empty=True)
            if name is None:
                return None
            if not name and vid != 0x7FFF:
                return None
            return ptr, vid, name

        best = (0, 0, None)
        for start in range(LONG_NAME_SEARCH_BASE, data_len - 8, 4):
            entry = valid_entry(start)
            if entry is None:
                continue
            if valid_entry(start - 8) is not None:
                continue

            count = 0
            named = 0
            off = start
            while True:
                entry = valid_entry(off)
                if entry is None:
                    break
                if entry[2]:
                    named += 1
                count += 1
                off += 8

            if count >= 100 and named >= 50 and (named, count) > (best[0], best[1]):
                best = (named, count, start)
                if count >= LONG_NAME_PRIMARY_RUN_MIN:
                    break

        named, count, start = best
        self.long_name_table_off = start
        self.long_name_table_count = count
        nodes = {}
        if start is None:
            return nodes

        for i in range(count):
            off = start + i * 8
            ptr, vid, _pad = unpack_entry(data, off)
            if vid >= 0x1000:
                continue
            name = string_at_ptr(ptr, allow_empty=True)
            if name:
                nodes[vid] = name
        return nodes

    def _build_name_buckets(self):
        tags = {}
        tag_ids = {}
        g8_base = self.g[8]
        self._check_range(g8_base, G8_BUCKET_COUNT * G8_BUCKET_HEADER_STRIDE)
        for bucket_idx in range(G8_BUCKET_COUNT):
            off = g8_base + bucket_idx * 8
            ptr = self.u32(off)
            count = self.u8(off + 4)
            if bytes(self.data[off + 5:off + 8]) != b"\x00\x00\x00":
                raise ValueError(
                    "globals[8] bucket %d has nonzero reserved bytes" % bucket_idx
                )
            if ptr == 0 and count == 0:
                continue
            table_off = self._off_for_addr(ptr, count * 4)
            if table_off is None:
                raise ValueError(
                    "globals[8] bucket %d entries are outside the image" % bucket_idx
                )
            prefix = chr(ord("A") + bucket_idx)
            for j in range(count):
                eoff = table_off + j * 4
                c1 = self.u8(eoff)
                c2 = self.u8(eoff + 1)
                vid = self.u16(eoff + 2)
                if not (0x20 < c1 < 0x7F and 0x20 < c2 < 0x7F):
                    raise ValueError(
                        "globals[8] bucket %d entry %d has an invalid suffix" %
                        (bucket_idx, j)
                    )
                if vid > self.max_var_id:
                    raise ValueError(
                        "globals[8] bucket %d entry %d names var 0x%04X past 0x%04X" %
                        (bucket_idx, j, vid, self.max_var_id)
                    )
                tag = prefix + chr(c1) + chr(c2)
                if vid in tags and tags[vid] != tag:
                    raise ValueError(
                        "globals[8] assigns both %s and %s to var 0x%04X" %
                        (tags[vid], tag, vid)
                    )
                if tag in tag_ids and tag_ids[tag] != vid:
                    raise ValueError(
                        "globals[8] assigns tag %s to vars 0x%04X and 0x%04X" %
                        (tag, tag_ids[tag], vid)
                    )
                tags[vid] = tag
                tag_ids[tag] = vid
        return tags

    def _build_option_table(self):
        """Locate and parse the enum symbol table used by RPC formatters.

        Layout: 12-byte entries, each
            +0  u32  enum_index  (g[5] descriptor index)
            +4  u32  raw_value
            +8  u32  symbol_ptr  (flash address of a NUL-terminated symbol)

        Raw values can be sparse, so entries must retain their explicit value.
        Returns (offset, count, flat_entries, by_type_dict).
        """

        data = self.data
        data_len = len(data)
        unpack_entry = struct.Struct("<III").unpack_from
        option_counts = [
            data[self.g[5] + idx * G5_STRIDE + 0x09]
            for idx in range(self.g5_count)
        ]
        string_cache = {}

        def string_at_ptr(ptr, max_len=96):
            if ptr in string_cache:
                return string_cache[ptr]
            off = ptr - FLASH_BASE
            if off < 0 or off >= data_len:
                string_cache[ptr] = None
                return None
            end = data.find(b"\x00", off)
            if end <= off or end - off > max_len:
                string_cache[ptr] = None
                return None
            raw = data[off:end]
            if any(b < 0x20 or b > 0x7E for b in raw):
                string_cache[ptr] = None
                return None
            string_cache[ptr] = raw.decode("ascii")
            return string_cache[ptr]

        def valid_entry(off, previous=None):
            if off + 12 > data_len:
                return None
            typ, raw_value, symbol_ptr = unpack_entry(data, off)
            if not (0 <= typ < self.g5_count):
                return None
            if not (0 <= raw_value < option_counts[typ]):
                return None
            if previous is not None and (typ, raw_value) <= previous:
                return None
            symbol = string_at_ptr(symbol_ptr)
            if symbol is None:
                return None
            return typ, raw_value, symbol

        # The table moves between builds; 8.0.x places it just below 1 MiB.
        best_start = None
        best_entries = []
        off = ENUM_SYMBOL_SEARCH_BASE
        while off + 12 <= data_len:
            if valid_entry(off) is None:
                off += 4
                continue
            start = off
            entries = []
            previous = None
            while True:
                entry = valid_entry(off, previous)
                if entry is None:
                    break
                entries.append(entry)
                previous = entry[:2]
                off += 12
            if len(entries) > len(best_entries):
                best_start = start
                best_entries = entries
            if len(entries) >= ENUM_SYMBOL_PRIMARY_RUN_MIN:
                break
            off = max(off + 4, start + 4)
        if len(best_entries) < 50:
            return (None, 0, [], {})

        by_type = {}
        for typ, raw_value, symbol in best_entries:
            by_type.setdefault(typ, {})[raw_value] = symbol
        return (best_start, len(best_entries), best_entries, by_type)

    def _ensure_option_table(self):
        if self.opt_entries is not None:
            return
        (
            self.opt_table_off, self.opt_table_count, self.opt_entries,
            self.opt_by_type,
        ) = self._build_option_table()

    def option_symbols_for_g5_index(self, idx, n_options):
        """Return RPC enum symbols indexed by their explicit raw values."""
        if n_options <= 0:
            return []
        self._ensure_option_table()
        symbols = self.opt_by_type.get(idx, {})
        return [symbols.get(raw_value) for raw_value in range(n_options)]

    def dispatch_var_id(self, vid):
        if self.g1_id_base <= vid < self.g2_id_base:
            return ("g[1]", self.g[1], G1_STRIDE, vid - self.g1_id_base)
        if self.g2_id_base <= vid < self.g3_id_base:
            return ("g[2]", self.g[2], G2_STRIDE, vid - self.g2_id_base)
        if self.g3_id_base <= vid < self.g5_id_base:
            return ("g[3]", self.g[3], G3_STRIDE, vid - self.g3_id_base)
        if self.g5_id_base <= vid < self.g5_id_base + self.g5_count:
            return ("g[5]", self.g[5], G5_STRIDE, vid - self.g5_id_base)
        return None

    def name_namespace_matches_descriptor(self, vid):
        disp = self.dispatch_var_id(vid)
        if disp is None:
            return False
        return True

    def descriptor_specs(self):
        return {
            "g1": {
                "base": self.g[1], "stride": G1_STRIDE,
                "count": self.g1_count, "id_base": self.g1_id_base,
            },
            "g2": {
                "base": self.g[2], "stride": G2_STRIDE,
                "count": self.g2_count, "id_base": self.g2_id_base,
            },
            "g3": {
                "base": self.g[3], "stride": G3_STRIDE,
                "count": self.g3_count, "id_base": self.g3_id_base,
            },
            "g5": {
                "base": self.g[5], "stride": G5_STRIDE,
                "count": self.g5_count, "id_base": self.g5_id_base,
            },
            "g10": {
                "base": self.g[10], "stride": G10_STRIDE,
                "count": self.g10_count, "id_base": None,
            },
        }

    def g10_index_for_var(self, vid):
        spec = self.descriptor_specs()["g10"]
        for idx in range(spec["count"]):
            off = spec["base"] + idx * spec["stride"]
            if self.u16(off) == vid:
                return idx
        return None

    def conf_end(self):
        return min(len(self.data), CONF_BASE + CONF_SIZE)

    def conf_header(self):
        self._check_range(CONF_BASE, CONF_HEADER_SIZE)
        if self.g.get(0) != CONF_BASE:
            raise ValueError("globals[0] does not point to the CONF header")
        if bytes(self.data[CONF_BASE + 0x48:CONF_BASE + 0x68]) != b"\x00" * 0x20:
            raise ValueError("globals[0] reserved area is nonzero")
        if bytes(self.data[CONF_BASE + 0x88:CONF_BASE + 0x100]) != b"\xff" * 0x78:
            raise ValueError("globals[0] unused tail is not erased")
        if bytes(self.data[CONF_BASE + 0x100:CONF_BASE + 0x104]) != b"\x00\x48\x70\x47":
            raise ValueError("CONF globals accessor veneer does not match")

        profile_variation_identifier = self._string_at_ptr(
            self.u32(CONF_BASE + 0x14)
        )
        if not profile_variation_identifier:
            raise ValueError("globals[0] has no profile variation identifier")
        return {
            "offset": CONF_BASE,
            "data_version": self.data_version,
            "platform_id": self.u32(CONF_BASE + 4),
            "aid": self.u32(CONF_BASE + 8),
            "variant_id": self.u32(CONF_VID_OFF),
            "region_id": self.u32(CONF_BASE + 0x10),
            "profile_variation_identifier": profile_variation_identifier,
            "platform_text": self.ascii_field(CONF_BASE + 0x18, 0x10),
            "default_product_code": self.ascii_field(CONF_BASE + 0x28, 0x10),
            "default_product_name": self.ascii_field(CONF_BASE + 0x38, 0x10),
            "configuration_build_hash": self.ascii_version_field(
                CONF_GIT_OFF, CONF_GIT_SIZE
            ),
            "data_model_version": self.ascii_version_field(
                CONF_DATA_MODEL_OFF, CONF_DATA_MODEL_SIZE
            ),
            "data_model_build_hash": self.ascii_version_field(
                CONF_DATA_MODEL_HASH_OFF, CONF_DATA_MODEL_HASH_SIZE
            ),
        }

    def edf_schema_layout(self):
        if self._edf_schema_layout is None:
            self._edf_schema_layout = discover_edf_schema_layout(
                self.data, APPX_BASE
            )
        return self._edf_schema_layout

    def bitfield_selection_pool_size(self):
        size = 0
        for idx in range(self.g3_count):
            off = self.g[3] + idx * G3_STRIDE
            bit_count = self.u8(off + 0x10)
            if bit_count > 31:
                raise ValueError(
                    "globals[3] row %d bit_count exceeds 31" % idx
                )
            size = max(
                size,
                self.u16(off + 0x12) + bit_count,
            )
        if (not self._file_range_ok(self.g[4], size) or
                self.g[4] + size > self.conf_end()):
            raise ValueError("globals[4] selection-order pool exceeds CONF")
        return size

    def event_definition_count(self):
        count = discover_event_definition_count(self.data, APPX_BASE)
        sentinel = max(
            self.read_descriptor(array, idx)["change_event_queue_index"]
            for array in ("g1", "g2", "g3", "g5")
            for idx in range(self.descriptor_specs()[array]["count"])
        )
        if sentinel != count:
            raise ValueError(
                "globals[12] APPX count %d does not match DataItem no-queue "
                "sentinel %d" % (count, sentinel)
            )
        return count

    def rpc_json_permission_count(self):
        base = self.g.get(18)
        if not isinstance(base, int):
            return 0
        count = discover_rpc_json_permission_count(self.data, APPX_BASE)
        self._check_range(base, count * G18_PERMISSION_STRIDE)
        for node_id in range(count):
            off = base + node_id * G18_PERMISSION_STRIDE
            if self.u8(off) not in (0, 1) or self.u8(off + 1) not in (0, 1):
                raise ValueError(
                    "globals[18] permission %d is not a boolean pair" % node_id
                )
        return count

    def conf_layout(self):
        """Describe each globals[] root object without inferring ownership gaps."""
        self.conf_header()
        storage_sets = self.storage_sets()
        self.pdl_snapshot_schema()
        selection_pool_size = self.bitfield_selection_pool_size()
        reverse_names = self.short_name_reverse_entries()
        events = self.event_defs()
        payload_overrides = self.event_json_payload_overrides()
        collections = self.periodic_collections()
        event_fif_bits = {row["file_init_flag_bit"] for row in events}
        collection_fif_bits = {
            row["file_init_flag_bit"] for row in collections
        }
        overlap = event_fif_bits & collection_fif_bits
        if overlap:
            raise ValueError(
                "globals[12]/globals[14] reuse FIF bits %s" %
                ", ".join(str(bit) for bit in sorted(overlap))
            )
        self.edf_str_records()
        streams = self.edf_streams()
        g17_rows = self.event_labels()
        g17_stride = g17_rows[0]["schema_bytes"] if g17_rows else None
        permission_count = self.rpc_json_permission_count()
        self.configuration_change_sources()
        objects = {
            0: ("conf_header", 1, CONF_HEADER_SIZE),
            1: ("volatile_text_descriptors", self.g1_count,
                self.g1_count * G1_STRIDE),
            2: ("numeric_descriptors", self.g2_count,
                self.g2_count * G2_STRIDE),
            3: ("bitfield_descriptors", self.g3_count,
                self.g3_count * G3_STRIDE),
            4: ("bitfield_gui_selection_order", selection_pool_size,
                selection_pool_size),
            5: ("enum_descriptors", self.g5_count,
                self.g5_count * G5_STRIDE),
            6: ("nor_settings_groups", len(storage_sets),
                len(storage_sets) * G6_STORAGE_SET_STRIDE),
            7: ("backup_sram_power_loss_snapshot", 1,
                G7_PDL_HEADER_SIZE),
            8: ("short_name_bucket_headers", G8_BUCKET_COUNT,
                G8_BUCKET_COUNT * G8_BUCKET_HEADER_STRIDE),
            9: ("short_name_reverse_table", self.max_var_id + 1,
                len(reverse_names) * 3),
            10: ("mode_visibility", self.g10_count,
                 self.g10_count * G10_STRIDE),
            11: ("mode_visibility_count", self.g10_count, None),
            12: ("event_spool_definitions", len(events),
                 len(events) * G12_EVENT_DEFINITION_STRIDE),
            13: ("event_json_payload_overrides",
                 len(payload_overrides),
                 len(payload_overrides) *
                 G13_JSON_PAYLOAD_OVERRIDE_STRIDE),
            14: ("periodic_collections", len(collections),
                 len(collections) * G14_COLLECTION_STRIDE),
            15: ("summary_schema_header", 1, G15_SUMMARY_HEADER_SIZE),
            16: ("edf_stream_schemas", len(streams),
                 len(streams) * G16_STREAM_SCHEMA_STRIDE),
            17: ("edf_event_schemas", len(g17_rows),
                 None if g17_stride is None else len(g17_rows) * g17_stride),
            18: ("rpc_json_permissions", permission_count,
                 permission_count * G18_PERMISSION_STRIDE),
            19: ("configuration_change_source_header", 1,
                 G19_CHANGE_SOURCE_HEADER_SIZE),
        }
        out = []
        for index in range(self.global_count):
            value = self.g.get(index)
            off = (
                value
                if index != 11 and self._file_range_ok(value, 1)
                else None
            )
            kind, count, size = objects[index]
            if off is None and index != 11:
                size = None
                count = 0
            out.append({
                "index": index,
                "value": value,
                "offset": off,
                "kind": kind,
                "count": count,
                "size": size,
            })
        return out

    def var_short_name(self, vid):
        if not self.name_namespace_matches_descriptor(vid):
            return ""
        return self.name_buckets.get(vid, "")

    def short_name_reverse_entries(self):
        base = self.g[9]
        count = self.max_var_id + 1
        self._check_range(base, count * 3)
        entries = []
        for vid in range(count):
            off = base + vid * 3
            raw = bytes(self.data[off:off + 3])
            if raw == b"\x00\x00\x00":
                short_name = ""
            else:
                if any(byte < 0x20 or byte > 0x7e for byte in raw):
                    raise ValueError(
                        "globals[9] entry %d is not a three-character tag" %
                        vid
                    )
                short_name = raw.decode("ascii")
            bucket_name = self.name_buckets.get(vid)
            if bucket_name is not None and short_name != bucket_name:
                raise ValueError(
                    "globals[8]/globals[9] disagree for var 0x%04X" % vid
                )
            entries.append({
                "index": vid,
                "offset": off,
                "var_id": vid,
                "short_name": short_name,
            })
        return entries

    def var_long_name(self, vid):
        if not self.name_namespace_matches_descriptor(vid):
            return ""
        return self.long_names.get(vid, "")

    def read_descriptor(self, arr, idx):
        arr = normalize_array_name(arr)
        specs = self.descriptor_specs()
        if arr not in specs:
            raise ValueError("unknown descriptor array: %s" % arr)
        spec = specs[arr]
        if idx < 0 or idx >= spec["count"]:
            raise IndexError("%s[%d] outside 0..%d" %
                             (arr, idx, spec["count"] - 1))
        off = spec["base"] + idx * spec["stride"]
        vid = self.u16(off) if spec["id_base"] is None else spec["id_base"] + idx
        raw = self.data[off:off + spec["stride"]]
        rec = {
            "array": arr,
            "index": idx,
            "offset": off,
            "address": self.off_to_addr(off),
            "var_id": vid,
            "short_name": self.var_short_name(vid),
            "long_name": self.var_long_name(vid),
            "name": self.var_name(vid),
            "raw": raw,
        }
        if arr == "g1":
            flags = self.u16(off)
            rec.update({
                "flags": flags,
                "active": bool(flags & 1),
                "data_rule_id": self.u8(off + 2),
                "reserved_03": self.u8(off + 3),
                "linked_counter_index": self.u16(off + 4),
                "change_event_queue_index": self.u8(off + 6),
                "reserved_07": self.u8(off + 7),
                "buffer_capacity": self.u16(off + 8),
            })
        elif arr == "g2":
            flags = self.u16(off)
            scale = self.i16(off + 22)
            step = self.i16(off + 24)
            bounds_slot = self.u8(off + 26)
            if bounds_slot >= 0x80:
                raise ValueError(
                    "globals[2] row %d has negative bounds-table index 0x%02X" %
                    (idx, bounds_slot)
                )
            rec.update({
                "flags": flags,
                "active": bool(flags & 1),
                "data_rule_id": self.u8(off + 2),
                "reserved_03": self.u8(off + 3),
                "linked_counter_index": self.u16(off + 4),
                "change_event_queue_index": self.u8(off + 6),
                "reserved_07": self.u8(off + 7),
                "default": self.i32(off + 8),
                "max": self.i32(off + 12),
                "min": self.i32(off + 16),
                "decimal_places": self.u8(off + 20),
                "reserved_15": self.u8(off + 21),
                "scale": scale,
                "step": step,
                "bounds_slot": bounds_slot,
                "sample_block_signal_id": self.u8(off + 27),
                "quantity_class": self.u8(off + 28),
                "reserved_1d_1f": bytes(self.data[off + 29:off + 32]),
            })
            if scale:
                rec["scaled_default"] = rec["default"] / scale
                rec["scaled_min"] = rec["min"] / scale
                rec["scaled_max"] = rec["max"] / scale
                rec["scaled_step"] = step / scale
        elif arr == "g3":
            flags = self.u16(off)
            default_mask = self.u32(off + 8)
            editable_mask = self.u32(off + 12)
            bit_count = self.u8(off + 16)
            list_offset = self.u16(off + 18)
            g4_base = self.g.get(4)
            list_file_off = None
            selection_order = []
            if isinstance(g4_base, int):
                list_file_off = g4_base + list_offset
                pool_size = self.bitfield_selection_pool_size()
                if list_offset + bit_count > pool_size:
                    raise ValueError(
                        "globals[3] row %d selection list exceeds globals[4]"
                        % idx
                    )
                if self._file_range_ok(list_file_off, bit_count):
                    selection_order = list(
                        self.data[list_file_off:list_file_off + bit_count]
                    )
            rec.update({
                "flags": flags,
                "active": bool(flags & 1),
                "data_rule_id": self.u8(off + 2),
                "reserved_03": self.u8(off + 3),
                "linked_counter_index": self.u16(off + 4),
                "change_event_queue_index": self.u8(off + 6),
                "reserved_07": self.u8(off + 7),
                "default_mask": default_mask,
                "editable_mask": editable_mask,
                "editable_bits": [
                    i for i in range(32) if (editable_mask >> i) & 1
                ],
                "bit_count": bit_count,
                "selection_order_offset": list_offset,
                "selection_order_file_offset": list_file_off,
                "selection_order": selection_order,
            })
        elif arr == "g5":
            flags = self.u16(off)
            n_options = self.u8(off + 9)
            option_mask = self.u32(off + 12)
            rec.update({
                "flags": flags,
                "active": bool(flags & 1),
                "data_rule_id": self.u8(off + 2),
                "reserved_03": self.u8(off + 3),
                "linked_counter_index": self.u16(off + 4),
                "change_event_queue_index": self.u8(off + 6),
                "reserved_07": self.u8(off + 7),
                "default_option": self.u8(off + 8),
                "n_options": n_options,
                "reserved": self.u16(off + 10),
                "option_mask": option_mask,
                "enabled_options": [
                    i for i in range(n_options)
                    if i >= 32 or (option_mask >> i) & 1
                ],
            })
        elif arr == "g10":
            mode_visibility = self.data[off + 2:off + 13]
            if (any(value not in (0, 1) for value in mode_visibility) or
                    self.u8(off + 13) != 0):
                raise ValueError(
                    "globals[10] row %d has invalid visibility bytes" % idx
                )
            rec.update({
                "visible_in_modes": [
                    MODE_NAMES[i]
                    for i, value in enumerate(
                        mode_visibility
                    )
                    if value
                ],
                "mode_visibility": mode_visibility,
            })

        if arr in ("g1", "g2", "g3", "g5"):
            if rec["reserved_03"] != 0 or rec["reserved_07"] != 0:
                raise ValueError(
                    "globals[%s] row %d has nonzero common reserved bytes" %
                    (arr[1:], idx)
                )
            counter = rec["linked_counter_index"]
            if counter != 0x7FFF and counter >= self.g2_count:
                raise ValueError(
                    "globals[%s] row %d has invalid linked g[2] counter %d" %
                    (arr[1:], idx, counter)
                )
        if arr == "g1" and rec["buffer_capacity"] == 0:
            raise ValueError("globals[1] row %d has zero buffer capacity" % idx)
        if arr == "g2":
            if (rec["reserved_15"] != 0 or
                    rec["reserved_1d_1f"] != b"\x00\x00\x00"):
                raise ValueError(
                    "globals[2] row %d has nonzero reserved bytes" % idx
                )
            if (rec["scale"] == 0 or rec["step"] == 0 or
                    rec["min"] > rec["max"] or
                    not rec["min"] <= rec["default"] <= rec["max"]):
                raise ValueError(
                    "globals[2] row %d has invalid numeric bounds/scale" % idx
                )
        if arr == "g3":
            if self.u8(off + 0x11) != 0 or not 1 <= rec["bit_count"] <= 31:
                raise ValueError(
                    "globals[3] row %d has invalid bit-count metadata" % idx
                )
            valid_mask = (1 << rec["bit_count"]) - 1
            if ((rec["default_mask"] | rec["editable_mask"]) & ~valid_mask):
                raise ValueError(
                    "globals[3] row %d has mask bits above bit_count" % idx
                )
        if arr == "g5":
            if (rec["reserved"] != 0 or rec["n_options"] == 0 or
                    rec["default_option"] >= rec["n_options"]):
                raise ValueError(
                    "globals[5] row %d has invalid option metadata" % idx
                )
            valid_mask = (1 << min(rec["n_options"], 32)) - 1
            if rec["option_mask"] & ~valid_mask:
                raise ValueError(
                    "globals[5] row %d has mask bits above option count" % idx
                )
        return rec

    def edf_str_records(self):
        schema = self.summary_schema()
        if schema is None:
            return []
        count = schema["record_count"]
        rec_base = schema["record_table"]
        out = []
        for i in range(count):
            off = rec_base + i * SUMMARY_STRIDE
            field_id = self.u32(off)
            kind = self.u32(off + 4)
            if field_id != i or kind > 7:
                raise ValueError(
                    "globals[15] row %d has invalid field/kind %d/%d" %
                    (i, field_id, kind)
                )
            var_a = self.u16(off + 8)
            var_b = self.u16(off + 10)
            var_c = self.u16(off + 12)
            if any(
                    vid != 0x7FFF and vid > self.max_var_id
                    for vid in (var_a, var_b, var_c)):
                raise ValueError(
                    "globals[15] row %d references an invalid var ID" % i
                )
            selected = var_b if kind < 3 else var_a
            if self.u8(off + 15) != 0 or self.u16(off + 22) != 0:
                raise ValueError(
                    "globals[15] row %d has nonzero reserved fields" % i
                )
            if self.u8(off + 20) not in (0, 1) or self.u8(off + 21) not in (0, 1):
                raise ValueError(
                    "globals[15] row %d has invalid output flags" % i
                )
            label_ptr = self.u32(off + 24)
            unit_ptr = self.u32(off + 28)
            edf_label = self._string_at_ptr(label_ptr, allow_empty=True)
            edf_unit = self._string_at_ptr(unit_ptr, allow_empty=True)
            summary_spool_multiplier = self.f32(off + 16)
            edf_physical_divisor = self.f32(off + 32)
            if (not math.isfinite(summary_spool_multiplier) or
                    not math.isfinite(edf_physical_divisor)):
                raise ValueError(
                    "globals[15] row %d has non-finite scaling" % i
                )
            out.append({
                "index": i,
                "offset": off,
                "field_id": field_id,
                "kind": kind,
                "var_a": var_a,
                "var_b": var_b,
                "selected_var": selected,
                "var_c": var_c,
                "percentile": self.i8(off + 14),
                "reserved_0f": self.u8(off + 15),
                "summary_spool_multiplier": summary_spool_multiplier,
                "spool_enabled": bool(self.u8(off + 20)),
                "edf_enabled": bool(self.u8(off + 21)),
                "reserved16": self.u16(off + 22),
                "edf_label": edf_label,
                "edf_unit": edf_unit,
                "edf_physical_divisor": edf_physical_divisor,
                "short_name": self.var_short_name(selected),
                "long_name": self.var_long_name(selected),
                "name": self.var_name(selected),
                "raw": self.data[off:off + SUMMARY_STRIDE],
            })
        return out

    def summary_schema(self):
        base = self.g.get(15)
        if not isinstance(base, int):
            return None
        self._check_range(base, G15_SUMMARY_HEADER_SIZE)
        retention_days = self.u16(base)
        usage_interval_capacity = self.u16(base + 2)
        record_count = self.u16(base + 4)
        ignored_field_count = self.u16(base + 6)
        if (retention_days == 0 or usage_interval_capacity == 0 or
                record_count == 0 or ignored_field_count == 0):
            raise ValueError("globals[15] header has an empty dimension")
        record_table = self.ptr_to_off(
            self.u32(base + 8), record_count * SUMMARY_STRIDE
        )
        ignored_field_table = self.ptr_to_off(
            self.u32(base + 0x0c), ignored_field_count * 8
        )
        if record_table is None or ignored_field_table is None:
            raise ValueError("globals[15] referenced table is outside the image")
        ignored_fields = []
        short_tags = set()
        for index in range(ignored_field_count):
            off = ignored_field_table + index * 8
            raw_tag = bytes(self.data[off:off + 4])
            short_tag = raw_tag[:3].decode("ascii", errors="replace")
            kind = self.u32(off + 4)
            if (raw_tag[3] != 0 or
                    any(byte < 0x20 or byte > 0x7e for byte in raw_tag[:3]) or
                    short_tag in short_tags or kind > 7):
                raise ValueError(
                    "globals[15] ignored field %d is invalid" % index
                )
            short_tags.add(short_tag)
            ignored_fields.append({
                "index": index,
                "offset": off,
                "short_tag": short_tag,
                "kind": kind,
            })
        return {
            "offset": base,
            "retention_days": retention_days,
            "usage_interval_capacity": usage_interval_capacity,
            "record_count": record_count,
            "record_table": record_table,
            "ignored_input_field_count": ignored_field_count,
            "ignored_input_field_table": ignored_field_table,
            "ignored_input_fields": ignored_fields,
        }

    def edf_streams(self):
        base = self.g.get(16)
        if not isinstance(base, int):
            return []
        out = []
        stream_count = self.edf_schema_layout().stream_count
        out_tags = set()
        for i in range(stream_count):
            off = base + i * G16_STREAM_SCHEMA_STRIDE
            self._check_range(off, G16_STREAM_SCHEMA_STRIDE)
            period = self.u16(off)
            samples = self.u16(off + 2)
            signal_count = self.u16(off + 4)
            reserved = self.u16(off + 6)
            tag_ptr = self.u32(off + 8)
            table_ptr = self.u32(off + 12)
            if period == 0 or samples == 0 or tag_ptr == 0:
                raise ValueError(
                    "globals[16] stream %d has an empty timing or tag" % i
                )
            tag = self._string_at_ptr(tag_ptr)
            table_off = None if table_ptr == 0 else self.ptr_to_off(table_ptr)
            if not tag or tag in out_tags:
                raise ValueError(
                    "globals[16] stream %d has an invalid/duplicate tag" % i
                )
            out_tags.add(tag)
            if signal_count and table_off is None:
                raise ValueError(
                    "globals[16] stream %s has an invalid signal table" % tag
                )
            if reserved != 0:
                raise ValueError(
                    "globals[16] stream %s has a nonzero reserved field" % tag
                )
            signals = []
            signal_ids = set()
            for j in range(signal_count):
                roff = table_off + j * 16
                self._check_range(roff, 16)
                signal_reserved = self.u16(roff + 2)
                if signal_reserved != 0:
                    raise ValueError(
                        "globals[16] stream %s signal %d has a nonzero "
                        "reserved field" % (tag, j)
                    )
                var_id = self.u16(roff)
                scale = self.f32(roff + 12)
                if (var_id > self.max_var_id or var_id in signal_ids or
                        not math.isfinite(scale)):
                    raise ValueError(
                        "globals[16] stream %s signal %d has invalid metadata" %
                        (tag, j)
                    )
                signal_ids.add(var_id)
                signals.append({
                    "index": j,
                    "offset": roff,
                    "var_id": var_id,
                    "reserved": signal_reserved,
                    "name": self._string_at_ptr(self.u32(roff + 4)) or "",
                    "unit": self._string_at_ptr(self.u32(roff + 8),
                                                allow_empty=True) or "",
                    "scale": scale,
                })
            out.append({
                "index": i,
                "offset": off,
                "tag": tag,
                "period_ms": period,
                "samples_per_record": samples,
                "signal_count": signal_count,
                "reserved": reserved,
                "signals": signals,
            })
        return out

    def event_defs(self):
        base = self.g.get(12)
        if not isinstance(base, int):
            return []
        count = self.event_definition_count()
        out = []
        file_init_bits = set()
        names = set()
        codes = set()
        for i in range(count):
            off = base + i * G12_EVENT_DEFINITION_STRIDE
            if off + G12_EVENT_DEFINITION_STRIDE > self.conf_end():
                raise ValueError("globals[12] event table exceeds CONF")
            name_ptr = self.u32(off)
            code_ptr = self.u32(off + 4)
            if name_ptr == 0 or code_ptr == 0:
                raise ValueError("globals[12] event %d has a null name" % i)
            name = self._string_at_ptr(name_ptr)
            code = self._string_at_ptr(code_ptr)
            if not name or not code:
                raise ValueError("globals[12] event %d has invalid strings" % i)
            if (name in names or code in codes or len(code) != 3 or
                    not code.isascii() or not code.isprintable()):
                raise ValueError(
                    "globals[12] event %d has invalid/duplicate names" % i
                )
            names.add(name)
            codes.add(code)
            fifo_slots = self.u32(off + 8)
            event_record_bytes = self.u32(off + 0x10)
            record_kind = self.u8(off + 0x14)
            default_json_payload_type = self.u8(off + 0x15)
            erase_class = self.u8(off + 0x16)
            logger_enabled = self.u8(off + 0x17)
            file_record_bytes = self.u32(off + 0x18)
            allocation_group_blocks = self.u32(off + 0x1c)
            file_init_flag_bit = self.u16(off + 0x20)
            gate_index = self.u16(off + 0x22)
            if fifo_slots == 0 or event_record_bytes == 0:
                raise ValueError(
                    "globals[12] event %s has an empty FIFO or record" % code
                )
            if not 1 <= record_kind <= 6:
                raise ValueError(
                    "globals[12] event %s has invalid record kind %d" %
                    (code, record_kind)
                )
            if (default_json_payload_type > 6 or
                    erase_class not in (0, 1) or
                    logger_enabled not in (0, 1)):
                raise ValueError(
                    "globals[12] event %s has invalid JSON/logger/reset class" %
                    code
                )
            if (file_record_bytes < event_record_bytes + 4 or
                    allocation_group_blocks == 0):
                raise ValueError(
                    "globals[12] event %s has invalid file allocation" % code
                )
            if file_init_flag_bit >= 32 or file_init_flag_bit in file_init_bits:
                raise ValueError(
                    "globals[12] event %s has invalid/duplicate FIF bit %d" %
                    (code, file_init_flag_bit)
                )
            file_init_bits.add(file_init_flag_bit)
            if gate_index == 0x7FFF:
                gate_var_id = None
            elif gate_index < self.g5_count:
                gate_var_id = self.g5_id_base + gate_index
            else:
                raise ValueError(
                    "globals[12] event %s has invalid g[5] gate index 0x%04X" %
                    (code, gate_index)
                )
            out.append({
                "index": i,
                "offset": off,
                "name": name,
                "code": code,
                "fifo_slots": fifo_slots,
                "retained_record_target": self.u32(off + 0x0c),
                "event_record_bytes": event_record_bytes,
                "record_kind": record_kind,
                "default_json_payload_type": default_json_payload_type,
                "erase_class": erase_class,
                "logger_enabled": logger_enabled,
                "file_record_bytes": file_record_bytes,
                "allocation_group_blocks": allocation_group_blocks,
                "file_init_flag_bit": file_init_flag_bit,
                "gate_descriptor_index": gate_index,
                "gate_var_id": gate_var_id,
                "gate_short_name": (
                    None if gate_var_id is None
                    else self.var_short_name(gate_var_id)
                ),
                "gate_long_name": (
                    None if gate_var_id is None
                    else self.var_long_name(gate_var_id)
                ),
                "raw": self.data[off:off + G12_EVENT_DEFINITION_STRIDE],
            })
        return out

    def event_json_payload_overrides(self):
        base = self.g.get(13)
        if not isinstance(base, int):
            return []
        events = self.event_defs()
        out = []
        for i in range(G13_JSON_PAYLOAD_OVERRIDE_COUNT):
            off = base + i * G13_JSON_PAYLOAD_OVERRIDE_STRIDE
            self._check_range(off, G13_JSON_PAYLOAD_OVERRIDE_STRIDE)
            event_spool_index = self.u8(off)
            if event_spool_index >= len(events):
                raise ValueError(
                    "globals[13] override %d references event spool %d, "
                    "but globals[12] has %d records" %
                    (i, event_spool_index, len(events))
                )
            json_payload_type = self.u8(off + 4)
            if json_payload_type > 6:
                raise ValueError(
                    "globals[13] override %d has unsupported JSON payload "
                    "type %d" % (i, json_payload_type)
                )
            event = events[event_spool_index]
            out.append({
                "index": i,
                "offset": off,
                "event_spool_index": event_spool_index,
                "event_code": None if event is None else event["code"],
                "event_name": None if event is None else event["name"],
                "padding_01": self.u8(off + 1),
                "event_value": self.u16(off + 2),
                "json_payload_type": json_payload_type,
                "padding_05": self.u8(off + 5),
                "raw": self.data[
                    off:off + G13_JSON_PAYLOAD_OVERRIDE_STRIDE
                ],
            })
        return out

    def _event_label_schema(self, off, schema_bytes):
        if schema_bytes == G17_EVENT_SCHEMA_SIZE:
            event_record_bytes = self.u16(off)
            label_count = self.u16(off + 2)
            edf_record_bytes = self.u16(off + 4)
            reserved_06 = self.u16(off + 6)
            fifo_capacity = self.u32(off + 8)
            flags_off = off + 0x0c
            tag_ptr = self.u32(off + 0x10)
            unknown_constant_14 = self.u32(off + 0x14)
            label_table = self.u32(off + 0x18)
            if event_record_bytes == 0:
                return None
            if reserved_06 != 0:
                return None
        else:
            event_record_bytes = None
            label_count = self.u16(off)
            edf_record_bytes = self.u16(off + 2)
            reserved_06 = None
            fifo_capacity = self.u32(off + 4)
            flags_off = off + 8
            tag_ptr = self.u32(off + 0x0c)
            unknown_constant_14 = None
            label_table = self.u32(off + 0x10)

        tag = self._string_at_ptr(tag_ptr)
        table_off = self.ptr_to_off(label_table)
        if (not tag or label_count == 0 or table_off is None or
                not self._file_range_ok(table_off, label_count * 4) or
                edf_record_bytes < 2 or edf_record_bytes > 66 or
                edf_record_bytes & 1 or fifo_capacity == 0):
            return None

        labels = []
        for index in range(label_count):
            label = self._string_at_ptr(
                self.u32(table_off + index * 4), allow_empty=True)
            if label is None:
                return None
            labels.append(label)
        flags = self.u32(flags_off)
        if (self.u8(flags_off) not in (0, 1) or
                self.u8(flags_off + 1) not in (0, 1) or
                self.u16(flags_off + 2) != 0 or
                (schema_bytes == G17_EVENT_SCHEMA_SIZE and
                 unknown_constant_14 != 1)):
            return None
        return {
            "schema_bytes": schema_bytes,
            "event_record_bytes": event_record_bytes,
            "label_count": label_count,
            "edf_record_bytes": edf_record_bytes,
            "reserved_06": reserved_06,
            "fifo_capacity": fifo_capacity,
            "writer_enabled": int(self.u8(flags_off) != 0),
            "subtract_duration_from_onset": int(
                self.u8(flags_off + 1) != 0
            ),
            "flags": flags,
            "tag": tag,
            "unknown_constant_14": unknown_constant_14,
            "label_table": label_table,
            "labels": labels,
        }

    def event_labels(self):
        base = self.g.get(17)
        if not isinstance(base, int):
            return []
        layout = self.edf_schema_layout()
        stride = layout.event_stride
        out = []
        tags = set()
        for index in range(layout.event_count):
            off = base + index * stride
            row = self._event_label_schema(off, stride)
            if row is None:
                raise ValueError(
                    "globals[17] event schema %d is invalid" % index
                )
            if row["tag"] in tags:
                raise ValueError(
                    "globals[17] event schema %d has a duplicate tag" % index
                )
            tags.add(row["tag"])
            row["index"] = index
            row["offset"] = off
            out.append(row)
        return out

    def _periodic_metadata_layout_valid(self, headers, stride):
        for row in headers:
            meta_off = self.ptr_to_off(
                row["metadata_ptr"], row["signal_count"] * stride
            )
            if meta_off is None:
                return False
            for index in range(row["signal_count"]):
                off = meta_off + index * stride
                values = (
                    self.f64(off),
                    self.f64(off + 8),
                    self.f64(off + 0x10),
                    self.f64(off + 0x18),
                )
                if (not all(math.isfinite(value) for value in values) or
                        values[0] > values[1] or values[2] <= 0 or
                        values[3] <= 0):
                    return False
                quantized_min = round(values[0] / values[2])
                quantized_max = round(values[1] / values[2])
                if not (-0x8000 <= quantized_min <= quantized_max <= 0x7fff):
                    return False
                if stride == 0x28:
                    rice_modulus = self.u8(off + 0x20)
                    if bytes(self.data[off + 0x21:off + 0x28]) != b"\x00" * 7:
                        return False
                else:
                    rice_modulus = self.u8(off + 0x20)
                    if (bytes(self.data[off + 0x21:off + 0x24]) !=
                            b"\x00\x00\x00" or
                            self.u32(off + 0x24) not in (0, 1) or
                            bytes(self.data[off + 0x2a:off + 0x30]) !=
                            b"\x00" * 6):
                        return False
                if (rice_modulus == 0 or
                        rice_modulus & (rice_modulus - 1)):
                    return False
        return True

    def _periodic_metadata_stride(self, headers):
        candidates = [
            stride for stride in (0x28, 0x30)
            if self._periodic_metadata_layout_valid(headers, stride)
        ]
        if len(candidates) != 1:
            raise ValueError(
                "globals[14] expected one signal metadata layout, found %d" %
                len(candidates)
            )
        return candidates[0]

    def periodic_collections(self):
        base = self.g.get(14)
        if not isinstance(base, int):
            return []

        headers = []
        tags = set()
        count = discover_periodic_collection_count(self.data, APPX_BASE)
        for index in range(count):
            off = base + index * G14_COLLECTION_STRIDE
            self._check_range(off, G14_COLLECTION_STRIDE)
            tag_ptr = self.u32(off)
            signal_count = self.u8(off + 0x28)
            id_list_ptr = self.u32(off + 0x2c)
            if tag_ptr == 0 or id_list_ptr == 0:
                raise ValueError(
                    "globals[14] collection %d has a null pointer" % index
                )
            tag = self._string_at_ptr(tag_ptr)
            id_list_off = self.ptr_to_off(id_list_ptr, signal_count * 2)
            if not tag or tag in tags or id_list_off is None:
                raise ValueError(
                    "globals[14] collection %d has invalid references" % index
                )
            tags.add(tag)
            sample_interval_ms = self.u32(off + 4)
            if sample_interval_ms == 0 or sample_interval_ms % 40:
                raise ValueError(
                    "globals[14] collection %s has invalid sample interval" %
                    tag
                )
            if (self.u16(off + 0x26) != 0 or
                    bytes(self.data[off + 0x29:off + 0x2c]) !=
                    b"\x00\x00\x00"):
                raise ValueError(
                    "globals[14] collection %s has nonzero reserved bytes" % tag
                )
            headers.append({
                "index": index,
                "offset": off,
                "tag": tag,
                "signal_count": signal_count,
                "id_list_off": id_list_off,
                "metadata_ptr": self.u32(off + 0x30),
            })

        metadata_stride = self._periodic_metadata_stride(headers)
        file_init_bits = set()
        for row in headers:
            off = row["offset"]
            reset_request_class = self.u8(off + 0x21)
            file_init_flag_bit = self.u16(off + 0x24)
            if reset_request_class not in (0, 1):
                raise ValueError(
                    "globals[14] collection %s has invalid reset class %d" %
                    (row["tag"], reset_request_class)
                )
            if (file_init_flag_bit >= 32 or
                    file_init_flag_bit in file_init_bits):
                raise ValueError(
                    "globals[14] collection %s has invalid/duplicate FIF "
                    "bit %d" % (row["tag"], file_init_flag_bit)
                )
            file_init_bits.add(file_init_flag_bit)
            gate_index = self.u16(off + 0x22)
            if gate_index == 0x7FFF:
                gate_var_id = None
            elif gate_index < self.g5_count:
                gate_var_id = self.g5_id_base + gate_index
            else:
                raise ValueError(
                    "globals[14] collection %s has invalid g[5] gate index "
                    "0x%04X" % (row["tag"], gate_index)
                )
            meta_base = self.ptr_to_off(
                row["metadata_ptr"], row["signal_count"] * metadata_stride
            )
            if row["signal_count"] and meta_base is None:
                raise ValueError(
                    "globals[14] collection %s metadata is outside the image" %
                    row["tag"]
                )
            signals = []
            signal_ids = set()
            for index in range(row["signal_count"]):
                vid = self.u16(row["id_list_off"] + index * 2)
                if vid > self.max_var_id or vid in signal_ids:
                    raise ValueError(
                        "globals[14] collection %s has invalid/duplicate "
                        "source 0x%04X" % (row["tag"], vid)
                    )
                signal_ids.add(vid)
                meta_off = meta_base + index * metadata_stride
                legacy = metadata_stride == 0x28
                signals.append({
                    "index": index,
                    "var_id": vid,
                    "short_name": self.var_short_name(vid),
                    "long_name": self.var_long_name(vid),
                    "name": self.var_name(vid),
                    "metadata_offset": meta_off,
                    "metadata": {
                        "stride": metadata_stride,
                        "clamp_min": self.f64(meta_off),
                        "clamp_max": self.f64(meta_off + 8),
                        "quantization_step": self.f64(meta_off + 0x10),
                        "multiplier_numerator": self.f64(meta_off + 0x18),
                        "rice_modulus": self.u8(meta_off + 0x20),
                        "codec_revision": (
                            None if legacy else self.u32(meta_off + 0x24)
                        ),
                        "precision": (
                            None if legacy else self.u8(meta_off + 0x28)
                        ),
                        "parameter_prefix": (
                            0 if legacy else self.u8(meta_off + 0x29)
                        ),
                    },
                })
            row.update({
                "sample_interval_ms": self.u32(off + 4),
                "max_block_duration_seconds": self.u32(off + 8),
                "file_record_bytes": self.u32(off + 0x0c),
                "retention_hours": self.u32(off + 0x10),
                "blocks_per_file_record": self.u32(off + 0x14),
                "file_allocation_granularity": self.u32(off + 0x18),
                "compression_ratio_estimate": self.u32(off + 0x1c),
                "initializer_byte": self.u8(off + 0x20),
                "reset_request_class": reset_request_class,
                "gate_descriptor_index": gate_index,
                "gate_var_id": gate_var_id,
                "gate_short_name": (
                    None if gate_var_id is None
                    else self.var_short_name(gate_var_id)
                ),
                "gate_long_name": (
                    None if gate_var_id is None
                    else self.var_long_name(gate_var_id)
                ),
                "file_init_flag_bit": file_init_flag_bit,
                "metadata_stride": metadata_stride,
                "signals": signals,
                "raw": self.data[off:off + G14_COLLECTION_STRIDE],
            })
        return headers

    def storage_sets(self):
        base = self.g.get(6)
        if not isinstance(base, int):
            return []
        out = []
        tags = set()
        for i in range(G6_STORAGE_SET_COUNT):
            off = base + i * G6_STORAGE_SET_STRIDE
            self._check_range(off, G6_STORAGE_SET_STRIDE)
            tag_raw = self.data[off:off + 4]
            if tag_raw[3] != 0 or any(b < 0x20 or b > 0x7E for b in tag_raw[:3]):
                raise ValueError("globals[6] SettingsGroup %d has an invalid tag" % i)
            ptr = self.u32(off + 8)
            count = self.u8(off + 12)
            tag = tag_raw[:3].decode("ascii")
            if tag in tags:
                raise ValueError(
                    "globals[6] SettingsGroup %s is duplicated" % tag
                )
            tags.add(tag)
            if (bytes(self.data[off + 6:off + 8]) != b"\x00\x00" or
                    bytes(self.data[off + 13:off + 16]) != b"\x00\x00\x00"):
                raise ValueError(
                    "globals[6] SettingsGroup %s has nonzero reserved bytes" %
                    tag
                )
            counter = self.i16(off + 4)
            if counter < 0 or counter >= self.g2_count:
                raise ValueError(
                    "globals[6] SettingsGroup %s has invalid g[2] counter" %
                    tag
                )
            counter_var_id = self.g2_id_base + counter
            list_off = self.ptr_to_off(ptr, count * 2)
            if list_off is None:
                raise ValueError(
                    "globals[6] SettingsGroup %s list is outside the image" %
                    tag
                )
            vars_out = []
            member_ids = set()
            for j in range(count):
                vid = self.u16(list_off + j * 2)
                if vid > self.max_var_id or vid in member_ids:
                    raise ValueError(
                        "globals[6] SettingsGroup %s has invalid/duplicate "
                        "member 0x%04X" % (tag, vid)
                    )
                member_ids.add(vid)
                vars_out.append({
                    "index": j,
                    "var_id": vid,
                    "short_name": self.var_short_name(vid),
                    "long_name": self.var_long_name(vid),
                    "name": self.var_name(vid),
                })
            out.append({
                "index": i,
                "offset": off,
                "tag": tag,
                "update_counter_index": counter,
                "update_counter_short_name": self.var_short_name(
                    counter_var_id
                ),
                "reserved0": bytes(self.data[off + 6:off + 8]),
                "list_ptr": ptr,
                "count": count,
                "reserved1": bytes(self.data[off + 13:off + 16]),
                "vars": vars_out,
            })
        return out

    def pdl_snapshot_schema(self):
        base = self.g.get(7)
        self._check_range(base, G7_PDL_HEADER_SIZE)
        if bytes(self.data[base:base + 4]) != b"PDL\x00":
            raise ValueError("globals[7] tag is not PDL")
        if bytes(self.data[base + 9:base + 12]) != b"\x00\x00\x00":
            raise ValueError("globals[7] header has nonzero reserved bytes")
        count = self.u8(base + 8)
        list_off = self.ptr_to_off(self.u32(base + 4), count * 2)
        if count == 0 or list_off is None:
            raise ValueError("globals[7] PDL var-id list is invalid")
        members = []
        member_ids = set()
        for index in range(count):
            vid = self.u16(list_off + index * 2)
            if vid > self.max_var_id or vid in member_ids:
                raise ValueError(
                    "globals[7] PDL has invalid/duplicate member 0x%04X" % vid
                )
            member_ids.add(vid)
            members.append({
                "index": index,
                "offset": list_off + index * 2,
                "var_id": vid,
                "short_name": self.var_short_name(vid),
                "long_name": self.var_long_name(vid),
            })
        return {
            "offset": base,
            "list_offset": list_off,
            "members": members,
        }

    def configuration_change_sources(self):
        base = self.g.get(19)
        if base is None:
            return []
        self._check_range(base, G19_CHANGE_SOURCE_HEADER_SIZE)
        if bytes(self.data[base + 5:base + 8]) != b"\x00\x00\x00":
            raise ValueError("globals[19] header has nonzero reserved bytes")
        count = self.u8(base + 4)
        list_off = self.ptr_to_off(self.u32(base), count * 2)
        if count == 0 or list_off is None:
            raise ValueError(
                "globals[19] configuration source list is invalid"
            )
        out = []
        source_ids = set()
        for index in range(count):
            vid = self.u16(list_off + index * 2)
            if vid > self.max_var_id or vid in source_ids:
                raise ValueError(
                    "globals[19] has invalid/duplicate source 0x%04X" % vid
                )
            source_ids.add(vid)
            out.append({
                "index": index,
                "offset": list_off + index * 2,
                "var_id": vid,
                "short_name": self.var_short_name(vid),
                "long_name": self.var_long_name(vid),
            })
        return out

    def fmt_raw(self, raw_bytes):
        return " ".join(f"{b:02X}" for b in raw_bytes)

    def ascii_field(self, off, size):
        self._check_range(off, size)
        raw = self.data[off:off + size].split(b"\x00")[0]
        return raw.decode("ascii", errors="replace")

    def ascii_version_field(self, off, size):
        self._check_range(off, size)
        raw = self.data[off:off + size]
        raw = raw.split(b"\x00")[0].rstrip(b"\xff")
        if not raw:
            return ""
        if any(b < 0x20 or b > 0x7E for b in raw):
            return ""
        return raw.decode("ascii")

    def find_appx_version(self, git=""):
        start = APPX_BASE
        end = len(self.data)
        if start >= end:
            return None, None

        appx = bytes(self.data[start:end])
        pattern = rb"(?<![0-9A-Za-z])(\d+\.\d+\.\d+\.[0-9a-f]{7,40})(?![0-9A-Za-z])"

        if git:
            git_bytes = git.encode("ascii")
            pos = len(appx)
            while True:
                pos = appx.rfind(git_bytes, 0, pos)
                if pos < 0:
                    break
                left = pos
                while left > 0 and appx[left - 1] in b"0123456789.":
                    left -= 1
                candidate = appx[left:pos + len(git_bytes)]
                match = re.fullmatch(pattern, candidate)
                if match is not None:
                    return match.group(1).decode("ascii"), start + left
                pos = left

        last = None
        for match in re.finditer(pattern, appx):
            last = (match.group(1).decode("ascii"), start + match.start(1))
        if last is not None:
            return last

        text = appx.decode("latin1", errors="ignore")
        last = None
        for match in re.finditer(
                r"SW\d+\.(\d+\.\d+\.\d+\.\d+(?:\.[0-9a-f]{7,40})?)",
                text):
            last = (match.group(1), None)
        if last is not None:
            return last

        for match in re.finditer(
                r"(?<!\d)(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})(?!\d)",
                text):
            last = (match.group(1), None)
        return last if last is not None else (None, None)

    def version_records(self):
        data_version = self.data_version
        platform_id = self.u32(CONF_BASE + 4)
        variant_id = self.u32(CONF_VID_OFF)
        git = self.ascii_version_field(CONF_GIT_OFF, CONF_GIT_SIZE)
        boot_version = self.ascii_version_field(BOOT_VERSION_OFF,
                                                BOOT_VERSION_SIZE)
        appx_version, appx_off = self.find_appx_version(git)
        dm_base = self.ascii_version_field(CONF_DATA_MODEL_OFF,
                                           CONF_DATA_MODEL_SIZE)
        dm_hash = self.ascii_version_field(CONF_DATA_MODEL_HASH_OFF,
                                           CONF_DATA_MODEL_HASH_SIZE)
        dm_identifier = ".".join(v for v in (dm_base, dm_hash) if v)

        records = [
            {
                "kind": "conf",
                "data_version": data_version,
                "platform_id": platform_id,
                "variant_id": variant_id,
                "git": git,
            },
        ]
        if boot_version:
            records.append({
                "kind": "bootloader",
                "version": boot_version,
                "identifier": "SW%03d01.00.%s" % (platform_id, boot_version),
                "offset": BOOT_VERSION_OFF,
            })
        if appx_version:
            rec = {
                "kind": "appx",
                "version": appx_version,
                "identifier": "SW%03d00.%d.%s" %
                              (platform_id, data_version, appx_version),
            }
            if appx_off is not None:
                rec["offset"] = appx_off
            records.append(rec)
        if dm_base or dm_hash:
            records.append({
                "kind": "data_model",
                "version": dm_base,
                "hash": dm_hash,
                "identifier": dm_identifier,
                "offset": CONF_DATA_MODEL_OFF,
            })
        return records

    def var_name(self, vid):
        return self.var_long_name(vid) or self.var_short_name(vid)

    def _descriptor_for_tag(self, tag, array):
        vid = self._resolve_var_ident(tag)
        if vid is None:
            return None
        dispatch = self.dispatch_var_id(vid)
        if dispatch is None or _array_from_dispatch(dispatch) != array:
            return None
        return self.read_descriptor(array, dispatch[3])

    def data_rule_registrations(self):
        if self._data_rule_registrations is None:
            registrations = discover_data_rule_registrations(
                self.data, APPX_BASE
            )
            used_ids = {
                rec["data_rule_id"]
                for array in ("g1", "g2", "g3", "g5")
                for rec in (
                    self.read_descriptor(array, index)
                    for index in range(
                        self.descriptor_specs()[array]["count"]
                    )
                )
                if rec["data_rule_id"]
            }
            missing = sorted(used_ids - registrations.keys())
            if missing:
                raise ValueError(
                    "data-rule registry is missing CONF rule ids %s" %
                    ", ".join("0x%02X" % rule_id for rule_id in missing)
                )
            self._data_rule_registrations = registrations
        return self._data_rule_registrations

    def data_rule_uses(self):
        uses = {}
        for array in ("g1", "g2", "g3", "g5"):
            count = self.descriptor_specs()[array]["count"]
            for index in range(count):
                rec = self.read_descriptor(array, index)
                if rec["data_rule_id"]:
                    uses.setdefault(rec["data_rule_id"], []).append(rec)
        return uses

    def dynamic_bounds_count(self):
        if self._dynamic_bounds_count is None:
            self._dynamic_bounds_count = discover_dynamic_bounds_count(
                self.data, APPX_BASE
            )
        return self._dynamic_bounds_count

    def dynamic_bounds_slots(self):
        count = self.dynamic_bounds_count()
        slots = {slot: [] for slot in range(count)}
        for index in range(self.g2_count):
            rec = self.read_descriptor("g2", index)
            if rec["bounds_slot"] < count:
                slots[rec["bounds_slot"]].append(rec)
        return slots

    def cmd_info(self):
        platform_text = self.ascii_field(CONF_BASE + 0x18, 0x10)
        default_product_code = self.ascii_field(CONF_BASE + 0x28, 0x10)
        default_product_name = self.ascii_field(CONF_BASE + 0x38, 0x10)
        data_version = self.data_version
        platform_id = self.u32(CONF_BASE + 4)
        aid = self.u32(CONF_BASE + 8)
        variant_id = self.u32(CONF_VID_OFF)
        region_id = self.u32(CONF_BASE + 0x10)

        print(f"  File:     {self.path}")
        print(f"  Platform: {platform_text}")
        print(
            "  Product defaults: code=%s name=%s" %
            (default_product_code, default_product_name)
        )
        print(
            "  Firmware: data_version=%d platform_id=%d aid=%d "
            "variant_id=%d region_id=%d" %
            (data_version, platform_id, aid, variant_id, region_id)
        )
        versions = {rec["kind"]: rec for rec in self.version_records()}
        print("  Versions:")
        if "bootloader" in versions:
            print("    Bootloader:  %s" % versions["bootloader"]["identifier"])
        if "appx" in versions:
            print("    Application: %s" % versions["appx"]["identifier"])
        if "data_model" in versions:
            print("    Data model:  %s" % versions["data_model"]["identifier"])

        mop = self._descriptor_for_tag("MOP", "g5")
        therapy_modes = []
        if mop is not None:
            therapy_modes = [
                MODE_NAMES[idx]
                for idx in range(min(mop["n_options"], len(MODE_NAMES)))
                if mop["option_mask"] & (1 << idx)
            ]

        lnc = self._descriptor_for_tag("LNC", "g3")
        languages = []
        if lnc is not None:
            languages = [
                LANGUAGE_NAMES[idx]
                for idx in range(min(lnc["bit_count"], len(LANGUAGE_NAMES)))
                if lnc["default_mask"] & (1 << idx)
            ]

        print()
        print(format_info_list("Therapy modes:", therapy_modes))
        print(format_info_list("Languages:", languages))

    def cmd_data_rules(self, rule_ids=None):
        registrations = self.data_rule_registrations()
        uses = self.data_rule_uses()
        selected = sorted(set(rule_ids or registrations))
        for rule_id in selected:
            if not 1 <= rule_id < 0x80:
                raise ValueError(
                    "data-rule id 0x%X is outside 0x01..0x7F" % rule_id
                )
            registration = registrations.get(rule_id)
            if registration is None:
                raise ValueError(
                    "data-rule id 0x%02X is not registered" % rule_id
                )
            descriptors = sorted(
                uses.get(rule_id, ()), key=lambda rec: rec["var_id"]
            )
            emit_line(
                rule="0x%02X" % rule_id,
                callback=fmt_addr(registration.callback & ~1),
                registration=registration.source_kind,
                source_off=fmt_off(registration.source_offset),
                use_count=len(descriptors),
                vars=[
                    rec["short_name"] or "0x%04X" % rec["var_id"]
                    for rec in descriptors
                ],
            )

    def cmd_bounds_slots(self, slot_ids=None):
        slots = self.dynamic_bounds_slots()
        selected = sorted(set(slot_ids or slots))
        for slot in selected:
            if slot not in slots:
                raise ValueError(
                    "dynamic bounds slot 0x%X is outside 0x00..0x%02X" %
                    (slot, len(slots) - 1)
                )
            records = slots[slot]
            fields = {
                "slot": "0x%02X" % slot,
                "use_count": len(records),
                "vars": [
                    rec["short_name"] or "0x%04X" % rec["var_id"]
                    for rec in records
                ],
            }
            if not records:
                fields.update(
                    seed_var="n/a",
                    seed_short="n/a",
                    seed_long="n/a",
                    seed_min="n/a",
                    seed_max="n/a",
                    scale="n/a",
                    seed_min_raw="n/a",
                    seed_max_raw="n/a",
                )
            else:
                seed = records[-1]
                fields.update(
                    seed_var="0x%04X" % seed["var_id"],
                    seed_short=fmt_text(seed["short_name"]),
                    seed_long=fmt_text(seed["long_name"]),
                )
                if seed["scale"]:
                    fields.update(
                        seed_min=fmt_number(seed["scaled_min"]),
                        seed_max=fmt_number(seed["scaled_max"]),
                        scale=seed["scale"],
                    )
                else:
                    fields.update(
                        seed_min=seed["min"],
                        seed_max=seed["max"],
                        scale=0,
                    )
                fields.update(
                    seed_min_raw=seed["min"],
                    seed_max_raw=seed["max"],
                )
            emit_line(**fields)

    def descriptor_line_fields(self, rec):
        fields = {
            "array": rec["array"],
            "idx": rec["index"],
            "off": fmt_off(rec["offset"]),
            "addr": fmt_addr(rec["address"]),
            "var": "0x%04X" % rec["var_id"],
            "short": fmt_text(rec["short_name"]),
            "long": fmt_text(rec["long_name"]),
        }
        if rec["array"] != "g10":
            fields.update({
                "flags": "0x%04X" % rec.get("flags", 0),
                "flag_names": dataitem_flag_names(rec.get("flags", 0)),
                "linked_counter": "0x%04X" % rec["linked_counter_index"],
                "event_queue": "0x%02X" % rec["change_event_queue_index"],
            })
            fields["data_rule"] = "0x%02X" % rec["data_rule_id"]
        if rec["array"] == "g1":
            fields.update({
                "buffer_capacity": rec["buffer_capacity"],
            })
        elif rec["array"] == "g2":
            if rec.get("scale"):
                fields.update({
                    "default": fmt_number(rec["scaled_default"]),
                    "min": fmt_number(rec["scaled_min"]),
                    "max": fmt_number(rec["scaled_max"]),
                    "step": fmt_number(rec["scaled_step"]),
                    "scale": rec["scale"],
                })
            else:
                fields.update({
                    "default": rec["default"],
                    "min": rec["min"],
                    "max": rec["max"],
                    "step": rec["step"],
                    "scale": rec["scale"],
                })
            fields.update({
                "default_raw": rec["default"],
                "min_raw": rec["min"],
                "max_raw": rec["max"],
                "step_raw": rec["step"],
                "decimal_places": rec["decimal_places"],
                "bounds_slot": "0x%02X" % rec["bounds_slot"],
                "sample_block_signal_id": rec["sample_block_signal_id"],
                "quantity_class": "0x%02X" % rec["quantity_class"],
            })
        elif rec["array"] == "g3":
            fields.update({
                "selection_order": rec["selection_order"],
                "selection_order_offset": (
                    "+0x%04X" % rec["selection_order_offset"]
                ),
                "selection_order_off": fmt_off(
                    rec["selection_order_file_offset"]
                ),
                "bit_count": rec["bit_count"],
                "default_mask": "0x%08X" % rec["default_mask"],
                "editable_mask": "0x%08X" % rec["editable_mask"],
                "editable_bits": rec["editable_bits"],
            })
        elif rec["array"] == "g5":
            fields.update({
                "default_option": rec["default_option"],
                "option_count": rec["n_options"],
                "option_mask": "0x%08X" % rec["option_mask"],
                "enabled_options": rec["enabled_options"],
                "reserved": "0x%04X" % rec["reserved"],
            })
        elif rec["array"] == "g10":
            fields.update({
                "visible_in": rec["visible_in_modes"],
                "visibility": " ".join(
                    "%02X" % b for b in rec["mode_visibility"]
                ),
            })
        return fields

    def emit_descriptor_line(self, rec):
        emit_line(**self.descriptor_line_fields(rec))

    def cmd_var(self, vid, verbose=False):
        if not verbose:
            disp = self.dispatch_var_id(vid)
            if not disp:
                emit_line(var="0x%04X" % vid,
                          short=fmt_text(self.var_short_name(vid)),
                          long=fmt_text(self.var_long_name(vid)),
                          status="missing")
                return
            arr, _base, _stride, idx = disp
            self.emit_descriptor_line(self.read_descriptor(arr, idx))
            return

        tag = self.var_short_name(vid)
        name = self.var_long_name(vid)
        print(f"  var_id:    0x{vid:04X} ({vid})")
        print(f"  short:     {fmt_text(tag)}")
        print(f"  long:      {fmt_text(name)}")

        disp = self.dispatch_var_id(vid)
        if not disp:
            print(f"  Dispatch:  *** NO DESCRIPTOR (max var_id 0x{self.max_var_id:04X}) ***")
            return

        arr, base, stride, idx = disp
        rec = self.read_descriptor(arr, idx)
        print(f"  Dispatch:  {arr}[{idx}]  ({fmt_off(base + idx * stride)})")
        print()
        for key, value in self.descriptor_line_fields(rec).items():
            print(f"  {key}: {line_value(value)}")
        print(f"  raw: {self.fmt_raw(rec['raw'])}")
        if edit_field_names(rec["array"]):
            print("  editable_fields: %s" %
                  " ".join(edit_field_names(rec["array"])))
        print()
        self._print_related_g10(vid)
        if rec["array"] == "g5":
            self.cmd_var_options_by_id(vid, verbose=True)

    def _print_related_g10(self, vid):
        for i in range(self.g10_count):
            g10 = self.read_descriptor("g10", i)
            if g10["var_id"] == vid:
                modes = ",".join(g10["visible_in_modes"])
                print(f"  g10[{i:3d}]:  visible_in={modes}")
                print(
                    "             visibility=%s" % " ".join(
                        f"{b:02X}" for b in g10["mode_visibility"][:11]
                    )
                )
                break
        else:
            print("  g10:       (no baseline visibility row)")

    def _mode_var_sources(self, mode_idx):
        mode_name = MODE_NAMES[mode_idx]
        prefix = MODE_PREFIXES.get(mode_idx)
        vids = {}
        for i in range(self.g10_count):
            g10 = self.read_descriptor("g10", i)
            if mode_name in g10["visible_in_modes"]:
                vids.setdefault(g10["var_id"], set()).add(
                    "baseline_visibility"
                )
        if prefix:
            for vid, name in self.long_names.items():
                if (self.name_namespace_matches_descriptor(vid)
                        and name.startswith(prefix)):
                    vids.setdefault(vid, set()).add("name_scope")
        return vids

    def cmd_mode(self, mode_idx=None):
        if mode_idx is None:
            for idx, mode_name in enumerate(MODE_NAMES):
                sources = self._mode_var_sources(idx)
                emit_line(
                    mode=idx,
                    mode_name=mode_name,
                    baseline_variables=sum(
                        "baseline_visibility" in source_set
                        for source_set in sources.values()
                    ),
                    name_scoped_variables=sum(
                        "name_scope" in source_set
                        for source_set in sources.values()
                    ),
                    total_variables=len(sources),
                )
            return

        if mode_idx < 0 or mode_idx >= len(MODE_NAMES):
            raise ValueError("mode index must be 0..%d" % (len(MODE_NAMES) - 1))

        mode_name = MODE_NAMES[mode_idx]
        vids = self._mode_var_sources(mode_idx)

        for vid in sorted(vids):
            fields = {
                "mode": mode_idx,
                "mode_name": mode_name,
                "var": "0x%04X" % vid,
                "short": fmt_text(self.var_short_name(vid)),
                "long": fmt_text(self.var_long_name(vid)),
            }
            disp = self.dispatch_var_id(vid)
            if disp is None:
                fields.update(array="n/a", idx="n/a", flags="n/a",
                              flag_names="n/a")
            else:
                arr = _array_from_dispatch(disp)
                idx = disp[3]
                rec = self.read_descriptor(arr, idx)
                fields.update(
                    array=arr,
                    idx=idx,
                    flags="0x%04X" % rec.get("flags", 0),
                    flag_names=dataitem_flag_names(rec.get("flags", 0)),
                )
            emit_line(**fields)

    def cmd_var_options(self, ident, verbose=False):
        """Print enum option slots for a var_id, long name, or 3-char tag."""
        vid = self._resolve_var_ident(ident)
        if vid is None:
            raise ValueError(
                "could not resolve %r to a var_id; use a numeric id, long name, "
                "3-char tag, or underscored short name" % ident)
        self.cmd_var_options_by_id(vid, verbose)

    def enum_option_enabled(self, rec, option):
        if not 0 <= option < rec["n_options"]:
            return False
        if option < 32 and not (rec["option_mask"] & (1 << option)):
            return False
        if rec["short_name"] == "LAN":
            lnc = self._descriptor_for_tag("LNC", "g3")
            if lnc is None or option >= lnc["bit_count"]:
                return False
            return bool(lnc["default_mask"] & (1 << option))
        return True

    def cmd_var_options_by_id(self, vid, verbose=False):
        """Print enum option slots for an already resolved var_id."""
        name = self.var_long_name(vid)
        tag = self.var_short_name(vid)
        d = self.dispatch_var_id(vid)
        if d is None:
            raise ValueError("var 0x%04X has no descriptor" % vid)
        arr = d[0]
        if arr != "g[5]":
            raise ValueError(
                "var 0x%04X (%s / %s) dispatches via %s; only g[5] vars "
                "have enum option slots" % (vid, tag, name, arr))
        idx = d[3]
        rec = self.read_descriptor("g5", idx)
        symbols = self.option_symbols_for_g5_index(idx, rec["n_options"])
        if not verbose:
            for opt in range(rec["n_options"]):
                emit_line(
                    var="0x%04X" % vid,
                    short=fmt_text(tag),
                    long=fmt_text(name),
                    idx=idx,
                    opt=opt,
                    enabled=1 if self.enum_option_enabled(rec, opt) else 0,
                    default=1 if opt == rec["default_option"] else 0,
                    symbol=fmt_text(symbols[opt] if opt < len(symbols) else None),
                )
            return

        print("  var_id:   0x%04X  tag=%s  name=%s" %
              (vid, fmt_text(tag), fmt_text(name)))
        print(
            "  dispatch: g[5][%d]   option_count=%d   "
            "default_option=%d   option_mask=0x%08X"
            % (idx, rec["n_options"], rec["default_option"],
               rec["option_mask"])
        )
        print("  options:")
        for opt in range(rec["n_options"]):
            flags = []
            if self.enum_option_enabled(rec, opt):
                flags.append("enabled")
            if opt == rec["default_option"]:
                flags.append("default")
            suffix = " [%s]" % ",".join(flags) if flags else ""
            symbol = symbols[opt] if opt < len(symbols) else "n/a"
            print(f"    {opt:3d}: symbol={symbol!r}{suffix}")

    def cmd_text(self, text_id, lang=0):
        if not self._ensure_gui_text_decoder():
            raise ValueError("GUI text decoder is not available for this image")
        text = self.decode_gui_text(text_id, lang)
        lang_name = LANGUAGE_NAMES[lang] if 0 <= lang < len(LANGUAGE_NAMES) else "n/a"
        emit_line(
            text_id="0x%03X" % text_id,
            lang=lang,
            language=lang_name,
            text=text if text else "(empty)",
        )

    def cmd_text_search(self, query, lang=0):
        if not self._ensure_gui_text_decoder():
            raise ValueError("GUI text decoder is not available for this image")
        if not 0 <= lang < len(LANGUAGE_NAMES):
            raise ValueError("language index %d is outside 0..%d" %
                             (lang, len(LANGUAGE_NAMES) - 1))
        q = query.lower()
        found = []
        for text_id in range(self.gui_text_count):
            try:
                text = self.decode_gui_text(text_id, lang)
            except Exception:
                continue
            if q in text.lower():
                found.append((text_id, text))
        for text_id, text in found:
            emit_line(
                text_id="0x%03X" % text_id,
                lang=lang,
                language=LANGUAGE_NAMES[lang],
                text=text if text else "(empty)",
            )

    def _resolve_var_ident(self, ident):
        """Resolve a var_id, long name, or 3-char tag to var_id (int)."""
        s = ident.strip()
        if s.startswith("_"):
            s = s[1:]
        s_upper = s.upper()
        for vid, tag in self.name_buckets.items():
            if self.name_namespace_matches_descriptor(vid) and tag == s_upper:
                return vid
        for vid, name in self.long_names.items():
            if self.name_namespace_matches_descriptor(vid) and name == s:
                return vid
        s_lower = s.lower()
        for vid, name in self.long_names.items():
            if (self.name_namespace_matches_descriptor(vid)
                    and name.lower() == s_lower):
                return vid
        if re.fullmatch(r"[0-9]+", s) or re.fullmatch(r"0[xX][0-9a-fA-F]+", s):
            return parse_numeric_arg(s, "var_id")
        return None

    def filter_rows(self, rows, active=False, inactive=False, name=None):
        out = list(rows)
        if active:
            out = [row for row in out
                   if row.get("active", row.get("edf_enabled")) is True]
        if inactive:
            out = [row for row in out
                   if row.get("active", row.get("edf_enabled")) is False]
        if name:
            rx = re.compile(name, re.IGNORECASE)
            out = [row for row in out if rx.search(descriptor_filter_text(row))]
        return out

    def cmd_conf_header(self):
        header = self.conf_header()
        emit_line(
            global_index=0,
            off=fmt_off(header["offset"]),
            data_version=header["data_version"],
            platform_id=header["platform_id"],
            aid=header["aid"],
            variant_id=header["variant_id"],
            region_id=header["region_id"],
            profile_variation_identifier=fmt_text(
                header["profile_variation_identifier"]
            ),
            platform_text=fmt_text(header["platform_text"]),
            default_product_code=fmt_text(header["default_product_code"]),
            default_product_name=fmt_text(header["default_product_name"]),
            configuration_build_hash=fmt_text(
                header["configuration_build_hash"]
            ),
            data_model_version=fmt_text(header["data_model_version"]),
            data_model_build_hash=fmt_text(
                header["data_model_build_hash"]
            ),
        )

    def cmd_g4_lists(self):
        for idx in range(self.g3_count):
            row = self.read_descriptor("g3", idx)
            selection_order = row["selection_order"]
            if selection_order == list(range(row["bit_count"])):
                selection_order = "natural"
            emit_line(
                global_index=4,
                kind="gui_selection_order",
                array="g3",
                idx=idx,
                off=fmt_off(row["selection_order_file_offset"]),
                var="0x%04X" % row["var_id"],
                short=fmt_text(row["short_name"]),
                long=fmt_text(row["long_name"]),
                list_offset="0x%04X" % row["selection_order_offset"],
                count=row["bit_count"],
                values=selection_order,
            )

    def cmd_pdl_list(self):
        schema = self.pdl_snapshot_schema()
        for member in schema["members"]:
            emit_line(
                global_index=7,
                list="PDL",
                idx=member["index"],
                off=fmt_off(member["offset"]),
                var="0x%04X" % member["var_id"],
                short=fmt_text(member["short_name"]),
                long=fmt_text(member["long_name"]),
            )

    def cmd_short_name_buckets(self):
        base = self.g[8]
        self._check_range(base, 26 * 8)
        for bucket_idx in range(26):
            header_off = base + bucket_idx * 8
            bucket = chr(ord("A") + bucket_idx)
            count = self.u8(header_off + 4)
            if bytes(self.data[header_off + 5:header_off + 8]) != b"\x00\x00\x00":
                raise ValueError(
                    "globals[8] bucket %s has nonzero reserved bytes" % bucket
                )
            if count == 0:
                emit_line(
                    global_index=8,
                    bucket=bucket,
                    bucket_idx=bucket_idx,
                    header_off=fmt_off(header_off),
                    count=0,
                )
                continue
            table_off = self.ptr_to_off(self.u32(header_off), count * 4)
            if table_off is None:
                raise ValueError(
                    "globals[8] bucket %s entries are outside the image" %
                    bucket
                )
            for entry_idx in range(count):
                off = table_off + entry_idx * 4
                suffix = bytes(self.data[off:off + 2]).decode("ascii")
                vid = self.u16(off + 2)
                emit_line(
                    global_index=8,
                    bucket=bucket,
                    bucket_idx=bucket_idx,
                    header_off=fmt_off(header_off),
                    entry_idx=entry_idx,
                    off=fmt_off(off),
                    var="0x%04X" % vid,
                    short=bucket + suffix,
                    long=fmt_text(self.var_long_name(vid)),
                )

    def cmd_short_name_reverse_table(self):
        for entry in self.short_name_reverse_entries():
            short = entry["short_name"] or None
            emit_line(
                global_index=9,
                idx=entry["index"],
                off=fmt_off(entry["offset"]),
                var="0x%04X" % entry["var_id"],
                short=fmt_text(short),
                long=fmt_text(self.var_long_name(entry["var_id"])),
            )

    def _rpc_json_node_names(self):
        nodes = {}
        for off in range(APPX_BASE, len(self.data) - 12, 4):
            if self.u32(off + 8) != 0x00007fff:
                continue
            marker = self._string_at_ptr(self.u32(off + 4))
            match = re.fullmatch(r"!(\d+)", marker or "")
            if match is None:
                continue
            name = self._string_at_ptr(self.u32(off))
            if name:
                nodes.setdefault(int(match.group(1)), []).append(name)
        return nodes

    def cmd_rpc_json_permissions(self):
        base = self.g[18]
        count = self.rpc_json_permission_count()
        if count == 0:
            raise ValueError("globals[18] contains no permission records")
        names = self._rpc_json_node_names()
        for node_id in range(count):
            off = base + node_id * G18_PERMISSION_STRIDE
            emit_line(
                global_index=18,
                node_id=node_id,
                off=fmt_off(off),
                name=names.get(node_id) or "n/a",
                read_enabled=self.u8(off),
                write_blocked=self.u8(off + 1),
            )

    def cmd_configuration_change_sources(self):
        for source in self.configuration_change_sources():
            emit_line(
                global_index=19,
                idx=source["index"],
                off=fmt_off(source["offset"]),
                var="0x%04X" % source["var_id"],
                short=fmt_text(source["short_name"]),
                long=fmt_text(source["long_name"]),
            )

    def cmd_globals(self, index=None):
        if index is not None:
            if index not in self.g:
                raise ValueError("globals index %d is not present" % index)
            if index == 0:
                self.cmd_conf_header()
            elif index in (1, 2, 3, 5, 10):
                self.cmd_vars("g%d" % index)
            elif index == 4:
                self.cmd_g4_lists()
            elif index == 6:
                self.cmd_storage_sets()
            elif index == 7:
                self.cmd_pdl_list()
            elif index == 8:
                self.cmd_short_name_buckets()
            elif index == 9:
                self.cmd_short_name_reverse_table()
            elif index == 11:
                emit_line(global_index=11, record_count=self.g[11])
            elif index == 12:
                self.cmd_events()
            elif index == 13:
                self.cmd_event_payload_types()
            elif index == 14:
                self.cmd_collections(include_headers=True)
            elif index == 15:
                self.cmd_summary_schema()
            elif index == 16:
                self.cmd_edf_streams()
            elif index == 17:
                self.cmd_event_labels()
            elif index == 18:
                self.cmd_rpc_json_permissions()
            elif index == 19:
                self.cmd_configuration_change_sources()
            return

        layout = {row["index"]: row for row in self.conf_layout()}
        for i in sorted(self.g):
            sec = layout.get(i, {})
            value = self.g.get(i)
            if isinstance(value, int) and CONF_BASE <= value < CONF_BASE + CONF_SIZE:
                value_text = "0x%08X" % self.off_to_addr(value)
            elif isinstance(value, int):
                value_text = "0x%08X" % value
            else:
                value_text = "n/a"
            emit_line(
                global_index=i,
                value=value_text,
                off=fmt_off(sec.get("offset")),
                kind=sec.get("kind", "n/a"),
                count=sec.get("count", "n/a"),
                size=(
                    "0x%X" % sec["size"]
                    if sec.get("size") is not None else "n/a"
                ),
            )

    def cmd_conf_layout(self):
        for sec in sorted(self.conf_layout(),
                           key=lambda row: row["offset"] or 0xFFFFFFFF):
            if sec["offset"] is None:
                continue
            emit_line(
                global_index=sec["index"],
                off=fmt_off(sec["offset"]),
                addr=fmt_addr(self.off_to_addr(sec["offset"])),
                kind=sec["kind"],
                count=sec["count"],
                size=("0x%X" % sec["size"]
                      if sec["size"] is not None else "n/a"),
            )

    def cmd_vars(self, arr_name, name=None, verbose=False):
        arr = normalize_array_name(arr_name)
        specs = self.descriptor_specs()
        if arr == "all":
            arrays = ("g1", "g2", "g3", "g5")
        elif arr in specs:
            arrays = (arr,)
        else:
            raise ValueError("unknown descriptor array: %s" % arr_name)

        for current_arr in arrays:
            spec = specs[current_arr]
            rows = [self.read_descriptor(current_arr, idx)
                    for idx in range(spec["count"])]
            rows = self.filter_rows(rows, name=name)
            for row in rows:
                if verbose:
                    print("[%s %d]" % (row["array"], row["index"]))
                    for key, value in self.descriptor_line_fields(row).items():
                        print("  %s: %s" % (key, line_value(value)))
                    print("  raw: %s" % self.fmt_raw(row["raw"]))
                else:
                    self.emit_descriptor_line(row)

    def cmd_edf_str(self, all_rows=False, inactive=False, name=None,
                    verbose=False):
        rows = self.edf_str_records()
        if inactive:
            rows = self.filter_rows(rows, inactive=True, name=name)
        elif not all_rows:
            rows = self.filter_rows(rows, active=True, name=name)
        else:
            rows = self.filter_rows(rows, name=name)
        for row in rows:
            fields = {
                "idx": row["index"],
                "off": fmt_off(row["offset"]),
                "edf_enabled": int(row["edf_enabled"]),
                "field": row["field_id"],
                "kind": row["kind"],
                "spool_enabled": int(row["spool_enabled"]),
                "selected_var": "0x%04X" % row["selected_var"],
                "short": fmt_text(row["short_name"]),
                "long": fmt_text(row["long_name"]),
                "edf_label": fmt_text(row["edf_label"]),
                "edf_unit": fmt_text(row["edf_unit"]),
                "summary_spool_multiplier":
                    fmt_number(row["summary_spool_multiplier"]),
                "edf_physical_divisor":
                    fmt_number(row["edf_physical_divisor"]),
            }
            if verbose:
                print("[edf-str %d]" % row["index"])
                for key, value in fields.items():
                    print("  %s: %s" % (key, line_value(value)))
                print("  var_a: 0x%04X %s/%s" %
                      (row["var_a"], fmt_text(self.var_short_name(row["var_a"])),
                       fmt_text(self.var_long_name(row["var_a"]))))
                print("  var_b: 0x%04X %s/%s" %
                      (row["var_b"], fmt_text(self.var_short_name(row["var_b"])),
                       fmt_text(self.var_long_name(row["var_b"]))))
                print("  var_c: 0x%04X %s/%s" %
                      (row["var_c"], fmt_text(self.var_short_name(row["var_c"])),
                       fmt_text(self.var_long_name(row["var_c"]))))
                print("  percentile: %d" % row["percentile"])
            else:
                emit_line(**fields)

    def cmd_edf_streams(self, names=None, verbose=False):
        wanted = {name.upper().lstrip("&") for name in (names or [])}
        for item in self.edf_streams():
            if wanted and item["tag"].upper().lstrip("&") not in wanted:
                continue
            if verbose:
                print("[%s]" % item["tag"])
                print("  off: %s" % fmt_off(item["offset"]))
                print("  period_ms: %d" % item["period_ms"])
                print("  samples_per_record: %d" % item["samples_per_record"])
                print("  signal_count: %d" % item["signal_count"])
            elif not item["signals"]:
                emit_line(
                    stream=item["tag"],
                    stream_idx=item["index"],
                    period_ms=item["period_ms"],
                    samples_per_record=item["samples_per_record"],
                    signal_count=0,
                )
            for sig in item["signals"]:
                emit_line(
                    stream=item["tag"],
                    stream_idx=item["index"],
                    signal_idx=sig["index"],
                    off=fmt_off(sig["offset"]),
                    var="0x%04X" % sig["var_id"],
                    name=fmt_text(sig["name"]),
                    unit=fmt_text(sig["unit"]),
                    scale=fmt_number(sig["scale"]),
                    period_ms=item["period_ms"],
                    samples_per_record=item["samples_per_record"],
                )

    def cmd_events(self, filters=None, verbose=False):
        wanted = [f.lower() for f in (filters or [])]
        for row in self.event_defs():
            if wanted:
                haystack = "%s %s" % (row["code"], row["name"])
                if not any(f in haystack.lower() for f in wanted):
                    continue
            fields = {
                "idx": row["index"],
                "off": fmt_off(row["offset"]),
                "code": row["code"],
                "name": row["name"],
                "fifo_slots": row["fifo_slots"],
                "retained_record_target": row["retained_record_target"],
                "event_record_bytes": row["event_record_bytes"],
                "default_json_payload_type":
                    row["default_json_payload_type"],
                "file_record_bytes": row["file_record_bytes"],
            }
            if verbose:
                print("[event %d]" % row["index"])
                for key, value in fields.items():
                    print("  %s: %s" % (key, line_value(value)))
                print("  record_kind: %s" % row["record_kind"])
                print("  erase_class: %s" % row["erase_class"])
                print("  logger_enabled: %s" % row["logger_enabled"])
                print(
                    "  allocation_group_blocks: %s" %
                    row["allocation_group_blocks"]
                )
                print("  file_init_flag_bit: %s" % row["file_init_flag_bit"])
                print(
                    "  gate_descriptor_index: %s" %
                    ("none" if row["gate_descriptor_index"] == 0x7FFF
                     else "0x%04X" % row["gate_descriptor_index"])
                )
                print("  gate_var: %s/%s" %
                      (fmt_text(row["gate_short_name"]),
                       fmt_text(row["gate_long_name"])))
            else:
                emit_line(**fields)

    def cmd_event_payload_types(self, filters=None):
        wanted = [f.lower() for f in (filters or [])]
        for row in self.event_json_payload_overrides():
            if wanted:
                haystack = "%s %s" % (
                    fmt_text(row["event_code"]), fmt_text(row["event_name"]))
                if not any(f in haystack.lower() for f in wanted):
                    continue
            emit_line(
                idx=row["index"],
                off=fmt_off(row["offset"]),
                event_spool_idx=row["event_spool_index"],
                event_value=row["event_value"],
                json_payload_type=row["json_payload_type"],
                code=fmt_text(row["event_code"]),
                name=fmt_text(row["event_name"]),
            )

    def cmd_event_labels(self, names=None):
        wanted = {name.upper().lstrip("&") for name in (names or [])}
        for table in self.event_labels():
            if wanted and table["tag"].upper().lstrip("&") not in wanted:
                continue
            for idx, label in enumerate(table["labels"]):
                emit_line(
                    table=table["tag"],
                    table_idx=table["index"],
                    schema_bytes=table["schema_bytes"],
                    label_idx=idx,
                    label=label,
                    event_record_bytes=table["event_record_bytes"],
                    edf_record_bytes=table["edf_record_bytes"],
                    fifo_capacity=table["fifo_capacity"],
                    writer_enabled=table["writer_enabled"],
                    subtract_duration_from_onset=(
                        table["subtract_duration_from_onset"]
                    ),
                    unknown_constant_14=(
                        "n/a" if table["unknown_constant_14"] is None
                        else "0x%08X" % table["unknown_constant_14"]
                    ),
                )

    def cmd_summary_schema(self):
        schema = self.summary_schema()
        if schema is None:
            raise ValueError("globals[15] summary schema is not present")
        emit_line(
            global_index=15,
            kind="header",
            off=fmt_off(schema["offset"]),
            retention_days=schema["retention_days"],
            usage_interval_capacity=schema["usage_interval_capacity"],
            record_count=schema["record_count"],
            record_table_off=fmt_off(schema["record_table"]),
            ignored_input_field_count=schema["ignored_input_field_count"],
            ignored_input_field_table_off=fmt_off(
                schema["ignored_input_field_table"]
            ),
        )
        for field in schema["ignored_input_fields"]:
            emit_line(
                global_index=15,
                kind="ignored_input_field",
                idx=field["index"],
                off=fmt_off(field["offset"]),
                short=field["short_tag"],
                value_kind=field["kind"],
            )
        self.cmd_edf_str(all_rows=True)

    def cmd_collections(self, names=None, include_headers=False):
        wanted = {name.upper().lstrip("&") for name in (names or [])}
        for row in self.periodic_collections():
            if wanted and row["tag"].upper().lstrip("&") not in wanted:
                continue
            collection_fields = {}
            if include_headers:
                collection_fields = dict(
                    off=fmt_off(row["offset"]),
                    sample_interval_ms=row["sample_interval_ms"],
                    max_block_duration_seconds=(
                        row["max_block_duration_seconds"]
                    ),
                    file_record_bytes=row["file_record_bytes"],
                    retention_hours=row["retention_hours"],
                    blocks_per_file_record=row["blocks_per_file_record"],
                    file_allocation_granularity=(
                        row["file_allocation_granularity"]
                    ),
                    compression_ratio_estimate=(
                        row["compression_ratio_estimate"]
                    ),
                    initializer_byte="0x%02X" % row["initializer_byte"],
                    reset_request_class=row["reset_request_class"],
                    gate_g5_index=(
                        "none" if row["gate_descriptor_index"] == 0x7FFF
                        else "0x%04X" % row["gate_descriptor_index"]
                    ),
                    gate_var=(
                        "n/a" if row["gate_var_id"] is None
                        else "0x%04X" % row["gate_var_id"]
                    ),
                    gate_short=fmt_text(row["gate_short_name"]),
                    gate_long=fmt_text(row["gate_long_name"]),
                    file_init_flag_bit=row["file_init_flag_bit"],
                    signal_count=row["signal_count"],
                    signal_var_ids_off=fmt_off(row["id_list_off"]),
                    signal_metadata_off=fmt_off(self.ptr_to_off(
                        row["metadata_ptr"]
                    )),
                    metadata_stride=row["metadata_stride"],
                )
            if not row["signals"]:
                emit_line(
                    collection=row["tag"],
                    collection_idx=row["index"],
                    **collection_fields
                )
            for sig in row["signals"]:
                meta = sig["metadata"]
                fields = dict(
                    collection=row["tag"],
                    collection_idx=row["index"],
                )
                fields.update(collection_fields)
                fields.update(
                    signal_idx=sig["index"],
                    var="0x%04X" % sig["var_id"],
                    short=fmt_text(sig["short_name"]),
                    long=fmt_text(sig["long_name"]),
                    clamp_min=fmt_number(meta["clamp_min"]),
                    clamp_max=fmt_number(meta["clamp_max"]),
                    quantization_step=fmt_number(meta["quantization_step"]),
                    multiplier_numerator=fmt_number(
                        meta["multiplier_numerator"]
                    ),
                    rice_modulus=meta["rice_modulus"],
                    codec_revision=(
                        "n/a" if meta["codec_revision"] is None
                        else meta["codec_revision"]
                    ),
                    precision=(
                        "n/a" if meta["precision"] is None
                        else meta["precision"]
                    ),
                    parameter_prefix=meta["parameter_prefix"],
                    metadata_off=fmt_off(sig["metadata_offset"]),
                )
                emit_line(**fields)

    def cmd_storage_sets(self, names=None, names_only=False):
        wanted = {name.upper().lstrip("&") for name in (names or [])}
        rows = self.storage_sets()
        if wanted:
            rows = [row for row in rows
                    if row["tag"].upper().lstrip("&") in wanted]
        for row in rows:
            if names_only:
                emit_line(
                    set=row["tag"],
                    idx=row["index"],
                    update_counter="0x%04X:%s" % (
                        row["update_counter_index"],
                        fmt_text(row["update_counter_short_name"]),
                    ),
                    count=row["count"],
                    names=[
                        "%s/%s" % (fmt_text(v["short_name"]),
                                   fmt_text(v["long_name"]))
                        for v in row["vars"]
                    ],
                )
                continue
            for v in row["vars"]:
                emit_line(
                    set=row["tag"],
                    set_idx=row["index"],
                    item_idx=v["index"],
                    update_counter="0x%04X:%s" % (
                        row["update_counter_index"],
                        fmt_text(row["update_counter_short_name"]),
                    ),
                    var="0x%04X" % v["var_id"],
                    short=fmt_text(v["short_name"]),
                    long=fmt_text(v["long_name"]),
                )


def _array_from_dispatch(dispatch):
    return dispatch[0].replace("[", "").replace("]", "")


def _parse_edit_int(value, what):
    text = value.strip()
    if not text:
        raise ValueError("%s requires a value" % what)
    signless = text[1:] if text[:1] in "+-" else text
    base = 16 if signless.lower().startswith("0x") else 10
    try:
        return int(text, base)
    except ValueError as exc:
        raise ValueError(
            "%s must be decimal or explicit hexadecimal" % what
        ) from exc


def _parse_edit_decimal(value, what):
    text = value.strip()
    signless = text[1:] if text[:1] in "+-" else text
    if signless.lower().startswith("0x"):
        return Decimal(_parse_edit_int(text, what))
    try:
        result = Decimal(text)
    except InvalidOperation as exc:
        raise ValueError("%s must be numeric" % what) from exc
    if not result.is_finite():
        raise ValueError("%s must be finite" % what)
    return result


def _parse_mode_visibility(value):
    text = value.strip()
    if text.lower() in ("none", "off", ""):
        return bytearray(len(MODE_NAMES))
    if text.lower() == "all":
        return bytearray([1] * len(MODE_NAMES))

    out = bytearray(len(MODE_NAMES))
    parts = [part.strip() for part in re.split(r"[,|+]", text)]
    if not parts or any(not part for part in parts):
        raise ValueError(
            "visibility requires mode names/indices, none, or all"
        )
    mode_by_name = {name.lower(): idx for idx, name in enumerate(MODE_NAMES)}
    for part in parts:
        key = part.lower()
        if key in mode_by_name:
            idx = mode_by_name[key]
        else:
            idx = _parse_edit_int(part, "mode")
        if not 0 <= idx < len(out):
            raise ValueError("mode %d outside 0..%d" % (idx, len(out) - 1))
        out[idx] = 1
    return bytes(out)


def _format_mode_visibility(mode_bytes):
    names = [
        MODE_NAMES[idx] if idx < len(MODE_NAMES) else str(idx)
        for idx, enabled in enumerate(mode_bytes)
        if enabled
    ]
    return ",".join(names) if names else "none"


def _encode_scaled_edit(value, scale, field):
    if scale == 0:
        raise ValueError(
            "%s display value cannot be encoded with scale 0; use %s_raw" %
            (field.name, field.name)
        )
    display = _parse_edit_decimal(value, field.name)
    raw = display * scale
    integral = raw.to_integral_value()
    if raw != integral:
        raise ValueError(
            "%s=%r is not exactly representable with scale %d; use %s_raw" %
            (field.name, value, scale, field.name)
        )
    return field.normalize_int(int(integral))


def _parse_edit_assignment(fw, text):
    if "=" not in text:
        raise ValueError("invalid assignment %r; expected VAR.FIELD=VALUE" % text)
    target, value = text.split("=", 1)
    if "." not in target:
        raise ValueError(
            "invalid assignment target %r; expected VAR.FIELD" % target)
    ident, field_name = target.rsplit(".", 1)
    ident = ident.strip()
    field_key = field_name.strip().lower()
    if not ident or not field_key:
        raise ValueError(
            "invalid assignment target %r; expected VAR.FIELD" % target)

    raw = field_key.endswith("_raw")
    base_field_key = field_key[:-4] if raw else field_key
    vid = resolve_var_arg(fw, ident)
    dispatch = fw.dispatch_var_id(vid)
    if dispatch is None:
        raise ValueError("var 0x%04X has no descriptor" % vid)

    arr = _array_from_dispatch(dispatch)
    fields = editable_field_map(arr)
    field = fields.get(field_key)
    if field is not None:
        if raw and field.kind != "scaled":
            field = None
        else:
            idx = dispatch[3]
            return {
                "text": text,
                "vid": vid,
                "array": arr,
                "index": idx,
                "rec": fw.read_descriptor(arr, idx),
                "field": field,
                "field_name": field_name.strip(),
                "value_text": value.strip(),
                "raw": raw,
                "target_key": (arr, idx),
            }

    g10_fields = editable_field_map("g10")
    field = g10_fields.get(base_field_key)
    if field is not None and not raw:
        idx = fw.g10_index_for_var(vid)
        if idx is not None:
            return {
                "text": text,
                "vid": vid,
                "array": "g10",
                "index": idx,
                "rec": fw.read_descriptor("g10", idx),
                "field": field,
                "field_name": field_name.strip(),
                "value_text": value.strip(),
                "raw": False,
                "target_key": ("g10", idx),
            }

    available = ", ".join(edit_field_names(arr))
    g10_idx = fw.g10_index_for_var(vid)
    if g10_idx is not None:
        available += ", " + ", ".join(edit_field_names("g10"))
    raise ValueError(
        "field %s is not editable for 0x%04X; available fields: %s" %
        (field_name.strip(), vid, available)
    )


def _initial_edit_state(fw, rec):
    state = {}
    for field in editable_fields(rec["array"]):
        state[field.attr] = field.read_storage(fw, rec)
    return state


def _parse_edit_value(edit, state):
    field = edit["field"]
    value = edit["value_text"]
    if field.kind == "mode_visibility":
        return _parse_mode_visibility(value)
    if field.kind == "scaled" and not edit["raw"]:
        return _encode_scaled_edit(value, state["scale"], field)
    return field.normalize_int(_parse_edit_int(value, field.name))


def _g4_pool_limit(fw):
    if not isinstance(fw.g.get(4), int):
        return None
    return fw.bitfield_selection_pool_size()


def _validate_edit_state(fw, target, state, touched):
    warnings = []
    arr = target["array"]
    name = target["name"]
    if arr == "g2" and touched & {"default", "min", "max", "scale"}:
        if state["min"] > state["max"]:
            raise ValueError("%s has min greater than max" % name)
        if not state["min"] <= state["default"] <= state["max"]:
            raise ValueError("%s default is outside min..max" % name)
    if arr == "g2":
        if "scale" in touched and state["scale"] == 0:
            raise ValueError("%s scale must be nonzero" % name)
        if "step" in touched and state["step"] == 0:
            raise ValueError("%s step must be nonzero" % name)
        if "bounds_slot" in touched:
            static_marker = 0x3D if fw.data_version >= 16 else 0x3E
            if not 0 <= state["bounds_slot"] <= static_marker:
                raise ValueError(
                    "%s bounds_slot 0x%02X is outside canonical range "
                    "0x00..0x%02X" %
                    (name, state["bounds_slot"], static_marker)
                )

    if arr == "g3":
        if state["bit_count"] > 31:
            raise ValueError("%s bit_count exceeds 31" % name)
        outside = (state["default_mask"] | state["editable_mask"]) & ~(
            (1 << state["bit_count"]) - 1 if state["bit_count"] else 0
        )
        if outside:
            warnings.append(
                "%s default/editable masks contain bits outside bit_count: "
                "0x%08X" % (name, outside)
            )
        limit = _g4_pool_limit(fw)
        if limit is not None:
            end = state["selection_order_offset"] + state["bit_count"]
            if end > limit:
                raise ValueError(
                    "%s g4 list ends at +0x%X beyond globals[4] size 0x%X" %
                    (name, end, limit)
                )

    if arr == "g5":
        if state["n_options"] and state["default_option"] >= state["n_options"]:
            raise ValueError(
                "%s default_option is outside option_count" % name
            )
        if state["n_options"] == 0 and state["default_option"] != 0:
            raise ValueError(
                "%s has nonzero default_option with no options" % name
            )
        outside = (
            state["option_mask"] & ~((1 << state["n_options"]) - 1)
            if 0 < state["n_options"] < 32 else
            state["option_mask"] if state["n_options"] == 0 else 0
        )
        if outside:
            warnings.append(
                "%s option_mask contains bits outside option_count: 0x%08X" %
                (name, outside)
            )
    return warnings


def prepare_edits(fw, assignments):
    edits = [_parse_edit_assignment(fw, text) for text in assignments]
    seen = {}
    states = {}
    targets = {}
    touched = {}

    for edit in edits:
        field = edit["field"]
        key = (edit["target_key"], field.attr)
        if key in seen:
            raise ValueError(
                "duplicate assignment for %s.%s" %
                (seen[key]["target_name"], field.name)
            )
        target_key = edit["target_key"]
        if target_key not in states:
            rec = edit["rec"]
            name = fw.var_name(edit["vid"]) or "0x%04X" % edit["vid"]
            target_name = "%s[%d] %s" % (rec["array"], rec["index"], name)
            targets[target_key] = {
                "array": edit["array"],
                "index": edit["index"],
                "rec": rec,
                "name": target_name,
            }
            states[target_key] = _initial_edit_state(fw, rec)
            touched[target_key] = set()
        seen[key] = {**edit, "target_name": targets[target_key]["name"]}

    # Structural assignments go first; display-scale edits then use final scale.
    for edit in edits:
        if edit["field"].kind == "scaled" and not edit["raw"]:
            continue
        state = states[edit["target_key"]]
        edit["new_value"] = _parse_edit_value(edit, state)
        state[edit["field"].attr] = edit["new_value"]
        touched[edit["target_key"]].add(edit["field"].attr)
    for edit in edits:
        if "new_value" in edit:
            continue
        state = states[edit["target_key"]]
        edit["new_value"] = _parse_edit_value(edit, state)
        state[edit["field"].attr] = edit["new_value"]
        touched[edit["target_key"]].add(edit["field"].attr)

    warnings = []
    for key, state in states.items():
        warnings.extend(_validate_edit_state(fw, targets[key], state, touched[key]))
    return edits, warnings


def _format_edit_value(fw, rec, field, value):
    if field.kind == "mode_visibility":
        return _format_mode_visibility(value)
    if field.kind == "scaled":
        scale = rec.get("scale") or 0
        if scale:
            return "%s (raw %d)" % (fmt_number(value / scale), value)
        return str(value)
    if field.kind == "hex8":
        return "0x%02X" % value
    if field.kind == "hex16":
        return "0x%04X" % value
    if field.kind == "mask":
        return "0x%0*X" % (field.size * 2, value)
    return str(value)


def _run_edit(fw, args):
    if not args.dry_run and not args.output:
        raise ValueError("edit requires -o/--output unless --dry-run is used")
    if not args.ignore_input_crc:
        fw.validate_conf_crc()

    edits, warnings = prepare_edits(fw, args.assignments)
    conf_end = CONF_BASE + CONF_SIZE - 2
    for edit in edits:
        field = edit["field"]
        start = edit["rec"]["offset"] + field.offset
        if start < CONF_BASE or start + field.size > conf_end:
            raise ValueError(
                "%s.%s is outside editable CONF data" %
                (fw.var_name(edit["vid"]) or "0x%04X" % edit["vid"],
                 field.name)
            )

    work_fw = AS11Firmware(fw.path, data=fw.data)
    for edit in edits:
        rec = work_fw.read_descriptor(edit["array"], edit["index"])
        edit["field"].write_storage(work_fw, rec, edit["new_value"])

    crc = work_fw.fix_conf_crc()
    new_fw = AS11Firmware(fw.path, data=work_fw.data)
    for edit in edits:
        rec = new_fw.read_descriptor(edit["array"], edit["index"])
        actual = edit["field"].read_storage(new_fw, rec)
        if actual != edit["new_value"]:
            raise ValueError(
                "failed to verify %s.%s: wrote %r, read %r" %
                (new_fw.var_name(edit["vid"]) or "0x%04X" % edit["vid"],
                 edit["field"].name, edit["new_value"], actual)
            )
        edit["new_rec"] = rec

    if not args.dry_run:
        work_fw.write_output(args.output, overwrite=args.overwrite)

    for warning in warnings:
        print("warning: %s" % warning, file=sys.stderr)
    for edit in edits:
        # edit["rec"] still identifies the old location, but the buffer has
        # changed. Re-read the original value from the saved raw descriptor.
        old_storage = edit["rec"]["raw"][
            edit["field"].offset:edit["field"].offset + edit["field"].size]
        if edit["field"].kind == "mode_visibility":
            old_value = bytes(old_storage)
        elif edit["field"].size == 1:
            old_value = old_storage[0]
        else:
            old_value = struct.unpack_from(
                "<" + edit["field"].fmt, bytes(old_storage), 0)[0]
        old_text = _format_edit_value(
            fw, edit["rec"], edit["field"], old_value)
        new_text = _format_edit_value(
            new_fw, edit["new_rec"], edit["field"], edit["new_value"])
        name = new_fw.var_name(edit["vid"]) or "0x%04X" % edit["vid"]
        print("  %s.%s: %s -> %s" %
              (name, edit["field_name"], old_text, new_text))
    print("  CONF CRC: 0x%04X" % crc)
    if args.dry_run:
        print("  Dry run; output not written")
    else:
        print("  Wrote %s" % args.output)


def parse_numeric_arg(value, what="number"):
    text = value.strip()
    if re.fullmatch(r"[0-9]+", text):
        return int(text, 10)
    if re.fullmatch(r"0[xX][0-9a-fA-F]+", text):
        return int(text, 16)
    raise argparse.ArgumentTypeError(
        "invalid %s %r; use decimal or explicit hex like 0x10" %
        (what, value)
    )


def parse_mode_arg(value):
    key = re.sub(r"[^a-z0-9]", "", value.lower())
    for idx, name in enumerate(MODE_NAMES):
        if key == re.sub(r"[^a-z0-9]", "", name.lower()):
            return idx
    try:
        mode = parse_numeric_arg(value, "mode")
    except argparse.ArgumentTypeError as exc:
        raise argparse.ArgumentTypeError(
            "invalid mode %r; use a mode name, decimal 0..%d, or explicit "
            "hex like 0x6" %
            (value, len(MODE_NAMES) - 1)
        ) from exc
    if not 0 <= mode < len(MODE_NAMES):
        raise argparse.ArgumentTypeError(
            "mode %d outside 0..%d" % (mode, len(MODE_NAMES) - 1)
        )
    return mode


def parse_lang_arg(value):
    text = value.strip()
    if re.fullmatch(r"[0-9]+", text) or re.fullmatch(r"0[xX][0-9a-fA-F]+", text):
        return parse_numeric_arg(text, "language")

    key = text.lower().replace("_", "-")
    if key in LANGUAGE_CODES:
        return LANGUAGE_CODES[key]
    raise argparse.ArgumentTypeError(
        "invalid language %r; use an index or code like en, de, es-us, pl" %
        value
    )


def normalize_array_name(name):
    lowered = name.strip().lower()
    if lowered.startswith("g[") and lowered.endswith("]"):
        lowered = "g" + lowered[2:-1]
    return lowered


def dataitem_flag_names(flags):
    return [name for mask, name in DATAITEM_FLAG_NAMES if flags & mask]


def fmt_off(value):
    return "n/a" if value is None else "0x%06X" % value


def fmt_addr(value):
    return "n/a" if value is None else "0x%08X" % value


def fmt_text(value):
    return value if value not in (None, "") else "n/a"


def fmt_number(value):
    if isinstance(value, int):
        return str(value)
    if not math.isfinite(value):
        return str(value)
    rounded_int = round(value)
    if abs(value - rounded_int) <= max(1e-9, abs(value) * 1e-7):
        return str(rounded_int)
    for places in range(1, 9):
        rounded = round(value, places)
        if abs(value - rounded) <= max(1e-9, abs(value) * 1e-6):
            text = f"{rounded:.{places}f}".rstrip("0").rstrip(".")
            return "0" if text in ("", "-0") else text
    text = f"{value:.8f}".rstrip("0").rstrip(".")
    return "0" if text in ("", "-0") else text


def format_info_list(label, values):
    prefix = "  %-16s" % label
    return textwrap.fill(
        ", ".join(values) if values else "n/a",
        width=100,
        initial_indent=prefix,
        subsequent_indent=" " * len(prefix),
        break_long_words=False,
        break_on_hyphens=False,
    )


def line_value(value):
    if value is None or value == "":
        return "n/a"
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, bytes):
        return value.hex()
    if isinstance(value, float):
        return fmt_number(value)
    if isinstance(value, (list, tuple)):
        return ",".join(line_value(item) for item in value) or "n/a"
    text = str(value)
    return (
        text.replace("\\", "\\\\")
        .replace("|", "\\|")
        .replace("\r", "\\r")
        .replace("\n", "\\n")
    )


def emit_line(**fields):
    print("|".join("%s=%s" % (key, line_value(value))
                   for key, value in fields.items()))


def descriptor_filter_text(row):
    return " ".join(str(row.get(key) or "") for key in (
        "name", "short_name", "long_name", "edf_label", "edf_unit",
    ))


def parse_text_id_arg(value):
    return parse_numeric_arg(value, "text id")


def resolve_var_arg(fw, ident):
    vid = fw._resolve_var_ident(ident)
    if vid is None:
        raise ValueError(
            "could not resolve %r to a var_id; use a numeric id, long name, "
            "3-char tag, or underscored short name" % ident)
    return vid


def add_command_parsers(subparsers):
    subparsers.add_parser("info", help="show firmware summary")

    p = subparsers.add_parser(
        "var",
        help="show variable descriptors by id, long name, or short tag",
    )
    p.add_argument(
        "ident",
        nargs="+",
        help="one or more var_ids, long names, tags, or _TAG aliases",
    )
    p.add_argument("--verbose", action="store_true", help="show multi-line details")

    p = subparsers.add_parser(
        "mode",
        help="show settings visible or name-scoped for a therapy mode",
    )
    p.add_argument(
        "mode",
        nargs="?",
        type=parse_mode_arg,
        help="mode name or index 0..10; omit to list modes",
    )

    p = subparsers.add_parser(
        "data-rules",
        help="list APPL DataItem rule callbacks and their CONF users",
    )
    p.add_argument(
        "rule",
        nargs="*",
        type=parse_numeric_arg,
        help="optional rule ids",
    )

    p = subparsers.add_parser(
        "bounds-slots",
        help="list APPL runtime numeric-bounds slots and their CONF users",
    )
    p.add_argument(
        "slot",
        nargs="*",
        type=parse_numeric_arg,
        help="optional slot indexes",
    )

    p = subparsers.add_parser(
        "globals",
        help="list globals[] values or dump one globals table",
    )
    p.add_argument(
        "index",
        nargs="?",
        type=parse_numeric_arg,
        help="optional globals index",
    )

    subparsers.add_parser(
        "conf-layout", help="list globals[] root objects and their decoded sizes"
    )

    p = subparsers.add_parser("vars", help="list variables")
    p.add_argument(
        "--array",
        choices=("all", "g1", "g2", "g3", "g5", "g10"),
        default="all",
        help="descriptor array to list; default scans g1/g2/g3/g5",
    )
    p.add_argument("--name", help="case-insensitive regex over resolved names")
    p.add_argument("--verbose", action="store_true", help="show multi-line details")

    p = subparsers.add_parser("var-options", help="show enum option slots for a g5 variable")
    p.add_argument("ident", help="var_id, long name, tag, or _TAG")
    p.add_argument("--verbose", action="store_true", help="show multi-line enum details")

    p = subparsers.add_parser("edf-str", help="list STR.edf SummaryRecord rows")
    p.add_argument("--all", action="store_true", help="include inactive STR rows")
    p.add_argument("--inactive", action="store_true", help="only inactive records")
    p.add_argument("--name", help="case-insensitive regex over resolved names")
    p.add_argument("--verbose", action="store_true", help="show multi-line details")

    p = subparsers.add_parser("edf-streams", help="list globals[16] EDF stream signal tables")
    p.add_argument("stream", nargs="*", help="optional stream tag filter, e.g. BRP PLD")
    p.add_argument("--verbose", action="store_true", help="show stream headers")

    p = subparsers.add_parser(
        "events", help="list globals[12] event spool definitions"
    )
    p.add_argument("filter", nargs="*", help="optional code/name substring filter")
    p.add_argument("--verbose", action="store_true", help="show multi-line details")

    p = subparsers.add_parser(
        "event-payload-types",
        help="list globals[13] EventNotification JSON payload rules",
    )
    p.add_argument("filter", nargs="*", help="optional code/name substring filter")

    p = subparsers.add_parser("event-labels", help="list globals[17] event label tables")
    p.add_argument("table", nargs="*", help="optional table tag filter, e.g. EVE CSL")

    p = subparsers.add_parser("collections", help="list globals[14] collection tables")
    p.add_argument("collection", nargs="*", help="optional collection tag filter, e.g. NRF APD")
    p.add_argument("--verbose", action="store_true", help="include collection rows")

    p = subparsers.add_parser(
        "storage-sets", help="list globals[6] external-NOR SettingsGroup schemas"
    )
    p.add_argument("set", nargs="*", help="optional set tag filter, e.g. HST BGL")
    p.add_argument("--names-only", action="store_true")

    p = subparsers.add_parser("text", help="decode one localized GUI text id")
    p.add_argument("text_id", type=parse_text_id_arg,
                   help="GUI text id, decimal or explicit hex")
    p.add_argument("--lang", type=parse_lang_arg, default=0,
                   help="language index or code, e.g. en, de, pl")

    p = subparsers.add_parser("text-search", help="search localized GUI text strings")
    p.add_argument("query", nargs="+")
    p.add_argument("--lang", type=parse_lang_arg, default=0, help="language index or code")

    p = subparsers.add_parser(
        "edit",
        help="edit CONF descriptors in a new firmware image",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=edit_fields_help(),
    )
    p.add_argument("assignments", nargs="+", help="VAR.FIELD=VALUE")
    p.add_argument("-o", "--output", help="output firmware image")
    p.add_argument("--dry-run", action="store_true",
                   help="validate and show changes without writing output")
    p.add_argument("--overwrite", action="store_true",
                   help="allow replacing an existing output file")
    p.add_argument("--ignore-input-crc", action="store_true",
                   help="allow editing an image with a bad CONF CRC")


def build_command_parser(prog="as11"):
    parser = argparse.ArgumentParser(prog=prog)
    subparsers = parser.add_subparsers(dest="command")
    add_command_parsers(subparsers)
    return parser


def build_main_parser():
    parser = argparse.ArgumentParser(
        description="Air11 CONF block navigator",
    )
    parser.add_argument("firmware", help="firmware image")
    parser.add_argument(
        "-i", "--interactive",
        action="store_true",
        help="start interactive descriptor shell",
    )
    subparsers = parser.add_subparsers(dest="command")
    add_command_parsers(subparsers)
    return parser


def run_command(fw, args):
    command = args.command or "info"
    if command == "info":
        fw.cmd_info()
    elif command == "var":
        vids = [resolve_var_arg(fw, ident) for ident in args.ident]
        for idx, vid in enumerate(vids):
            if args.verbose and idx:
                print()
            fw.cmd_var(vid, args.verbose)
    elif command == "globals":
        fw.cmd_globals(args.index)
    elif command == "conf-layout":
        fw.cmd_conf_layout()
    elif command == "vars":
        fw.cmd_vars(args.array, args.name, args.verbose)
    elif command == "mode":
        fw.cmd_mode(args.mode)
    elif command == "data-rules":
        fw.cmd_data_rules(args.rule)
    elif command == "bounds-slots":
        fw.cmd_bounds_slots(args.slot)
    elif command == "var-options":
        fw.cmd_var_options(args.ident, args.verbose)
    elif command == "edf-str":
        if args.all and args.inactive:
            raise ValueError("--all and --inactive are mutually exclusive")
        fw.cmd_edf_str(args.all, args.inactive, args.name, args.verbose)
    elif command == "edf-streams":
        fw.cmd_edf_streams(args.stream, args.verbose)
    elif command == "events":
        fw.cmd_events(args.filter, args.verbose)
    elif command == "event-payload-types":
        fw.cmd_event_payload_types(args.filter)
    elif command == "event-labels":
        fw.cmd_event_labels(args.table)
    elif command == "collections":
        fw.cmd_collections(args.collection, args.verbose)
    elif command == "storage-sets":
        fw.cmd_storage_sets(args.set, args.names_only)
    elif command == "text":
        fw.cmd_text(args.text_id, args.lang)
    elif command == "text-search":
        fw.cmd_text_search(" ".join(args.query), args.lang)
    elif command == "edit":
        _run_edit(fw, args)
    else:
        raise ValueError(f"unknown command: {command}")


def run_repl(fw):
    parser = build_command_parser()
    print()
    print("  AS11 Descriptor Navigator")
    print("  " + "-" * 40)
    fw.cmd_info()
    print()
    print('  Type "help" for commands, "quit" to exit.')
    print()

    while True:
        try:
            line = input("as11> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not line:
            continue
        if line.lower() in ("quit", "exit", "q"):
            break
        if line.lower() == "help":
            parser.print_help()
            print()
            continue
        if line.lower().startswith("help "):
            parts = shlex.split(line)
            if len(parts) == 2:
                try:
                    parser.parse_args([parts[1], "--help"])
                except SystemExit:
                    pass
                print()
                continue
        try:
            parts = shlex.split(line)
            args = parser.parse_args(parts)
            run_command(fw, args)
        except SystemExit:
            pass
        except Exception as exc:
            print(f"  Error: {exc}")
        print()


def main():
    parser = build_main_parser()
    try:
        args = parser.parse_args()
        fw = AS11Firmware(args.firmware)
        if args.interactive:
            if args.command is not None:
                raise ValueError("--interactive cannot be combined with a subcommand")
            run_repl(fw)
        else:
            run_command(fw, args)
        return 0
    except BrokenPipeError:
        return 0
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

"""Shared Air11 CONF structure discovery helpers."""

from dataclasses import dataclass
import re


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


def _decode_thumb_bl_target(data, off, flash_base=0x08000000):
    hw1 = _u16(data, off)
    hw2 = _u16(data, off + 2)
    if (hw1 & 0xF800) != 0xF000 or (hw2 & 0xD000) != 0xD000:
        raise ValueError("not a Thumb-2 BL instruction")

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
    return target_address - flash_base


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

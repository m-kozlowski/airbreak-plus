#!/usr/bin/env python3

import argparse
import os
import math
import re
import shlex
import struct
import sys
import tempfile
from decimal import Decimal, InvalidOperation

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
CONF_GIT_SIZE = 0x10
CONF_VID_OFF = CONF_BASE + 0x0C
CONF_DATA_MODEL_OFF = CONF_BASE + 0x72
CONF_DATA_MODEL_SIZE = 0x10
CONF_DATA_MODEL_HASH_OFF = CONF_BASE + 0x7D
CONF_DATA_MODEL_HASH_SIZE = 0x10
ENUM_SYMBOL_SEARCH_BASE = 0x100000
OLD_ENUM_SYMBOL_SEARCH_BASE = 0xF0000
OLD_ENUM_SYMBOL_SEARCH_END = 0x100000
OLD_ENUM_SYMBOL_MAX_DATA_VERSION = 13
LONG_NAME_PRIMARY_RUN_MIN = 500
ENUM_SYMBOL_PRIMARY_RUN_MIN = 500

G1_STRIDE = 10
G2_STRIDE = 32
G3_STRIDE = 20
G5_STRIDE = 16
G10_STRIDE = 14
G13_ROUTE_STRIDE = 6
G14_COLLECTION_STRIDE = 0x34
G17_EVENT_SCHEMA_SIZE = 28
G17_LEGACY_EVENT_SCHEMA_SIZE = 20
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

VERSION_BLOCK_ALIASES = {
    "boot": ("bootloader",),
    "bootloader": ("bootloader",),
    "fgbl": ("bootloader",),
    "app": ("appx",),
    "appl": ("appx",),
    "appx": ("appx",),
    "firmware": ("appx",),
    "conf": ("conf", "data_model"),
    "config": ("conf", "data_model"),
    "fgcb": ("conf", "bootloader", "appx", "data_model"),
    "full": ("conf", "bootloader", "appx", "data_model"),
    "all": ("conf", "bootloader", "appx", "data_model"),
    "data": ("data_model",),
    "data-model": ("data_model",),
    "datamodel": ("data_model",),
}


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
        if self.kind == "modes":
            return G10_STRIDE - 2
        return struct.calcsize("<" + self.fmt)

    @property
    def signed(self):
        return self.fmt in ("b", "h", "i")

    def read_storage(self, fw, rec):
        off = rec["offset"] + self.offset
        if self.kind == "modes":
            fw._check_range(off, self.size)
            return bytes(fw.data[off:off + self.size])
        if self.size == 1:
            return fw.u8(off)
        if self.fmt == "H":
            return fw.u16(off)
        if self.fmt == "I":
            return fw.u32(off)
        if self.fmt == "i":
            return fw.i32(off)
        raise ValueError("unsupported edit field format %r" % self.fmt)

    def write_storage(self, fw, rec, value):
        off = rec["offset"] + self.offset
        if self.kind == "modes":
            if len(value) != self.size:
                raise ValueError("modes field requires %d bytes" % self.size)
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
        DescriptorEditField("vt", "vid_type", 0x00, "H", "hex16",
                            aliases=("vid_type",)),
        DescriptorEditField("active", "vid_type", 0x00, "H", "active"),
        DescriptorEditField("subtype", "subtype", 0x02, "H", "hex16"),
        DescriptorEditField("linked_var", "linked_var_id", 0x04, "H", "hex16",
                            aliases=("linked_var_id",)),
        DescriptorEditField("class_tag", "class_tag", 0x06, "H", "hex16"),
        DescriptorEditField("max_len", "max_length", 0x08, "H",
                            aliases=("max_length",)),
    ),
    "g2": (
        DescriptorEditField("vt", "vid_type", 0x00, "H", "hex16",
                            aliases=("vid_type",)),
        DescriptorEditField("active", "vid_type", 0x00, "H", "active"),
        DescriptorEditField("enum_ref", "enum_ref", 0x02, "H", "hex16"),
        DescriptorEditField("source_index", "source_index", 0x04, "H", "hex16"),
        DescriptorEditField("storage_class", "storage_class", 0x06, "H",
                            "hex16"),
        DescriptorEditField("default", "default", 0x08, "I", "scaled"),
        DescriptorEditField("max", "max", 0x0C, "I", "scaled"),
        DescriptorEditField("min", "min", 0x10, "i", "scaled"),
        DescriptorEditField("format", "format", 0x14, "H", "hex16"),
        DescriptorEditField("scale", "scale", 0x16, "H"),
        DescriptorEditField("step", "step", 0x18, "H", "scaled"),
        DescriptorEditField("bounds_slot", "bounds_slot", 0x1A, "B", "hex8"),
        DescriptorEditField("sample_source", "sample_source_id", 0x1B, "B",
                            aliases=("sample_source_id",)),
        DescriptorEditField("quantity_class", "quantity_class", 0x1C, "I",
                            "mask"),
    ),
    "g3": (
        DescriptorEditField("vt", "vid_type", 0x00, "H", "hex16",
                            aliases=("vid_type",)),
        DescriptorEditField("active", "vid_type", 0x00, "H", "active"),
        DescriptorEditField("subtype", "subtype", 0x02, "H", "hex16"),
        DescriptorEditField("linked_var", "linked_var_id", 0x04, "H", "hex16",
                            aliases=("linked_var_id",)),
        DescriptorEditField("class_tag", "class_tag", 0x06, "H", "hex16"),
        DescriptorEditField("fixed", "fixed_mask", 0x08, "I", "mask",
                            aliases=("fixed_mask",)),
        DescriptorEditField("editable", "editable_mask", 0x0C, "I", "mask",
                            aliases=("editable_mask",)),
        DescriptorEditField("bit_count", "bit_count", 0x10, "B"),
        DescriptorEditField("g4_list", "g4_list_offset", 0x12, "H", "hex16",
                            aliases=("g4_list_offset",)),
    ),
    "g5": (
        DescriptorEditField("vt", "vid_type", 0x00, "H", "hex16",
                            aliases=("vid_type",)),
        DescriptorEditField("active", "vid_type", 0x00, "H", "active"),
        DescriptorEditField("g4_opts", "g4_options_offset", 0x02, "H", "hex16",
                            aliases=("g4_options_offset",)),
        DescriptorEditField("owner_ref", "owner_ref", 0x04, "H", "hex16"),
        DescriptorEditField("item_class", "item_class", 0x06, "H", "hex16"),
        DescriptorEditField("default_opt", "default_option", 0x08, "B",
                            aliases=("default_option",)),
        DescriptorEditField("n_opts", "n_options", 0x09, "B",
                            aliases=("n_options",)),
        DescriptorEditField("zero", "zero", 0x0A, "H", "hex16"),
        DescriptorEditField("mask", "option_mask", 0x0C, "I", "mask",
                            aliases=("option_mask",)),
    ),
    "g10": (
        DescriptorEditField("modes", "mode_bytes", 0x02, None, "modes"),
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
        "active accepts on/off, true/false, yes/no, 1/0",
        "g10 modes accepts comma/pipe/plus separated mode names or indices",
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

        mt_ptr = self.u32(CONF_BASE + 0x104)
        self.mt_off = self._off_for_addr(mt_ptr, 20 * 4)
        if self.mt_off is None:
            raise ValueError("globals table pointer 0x%08X is outside this image" % mt_ptr)

        self.g = {}
        for i in range(20):
            val = self.u32(self.mt_off + i * 4)
            if FLASH_BASE <= val < FLASH_BASE + len(self.data):
                self.g[i] = val - FLASH_BASE
            else:
                self.g[i] = val
        for index in (1, 2, 3, 5):
            if not self._file_range_ok(self.g.get(index), 1):
                raise ValueError("globals[%d] does not point inside this image" % index)

        self.g1_count = self._count_records(self.g[1], G1_STRIDE)
        self.g2_count = self._count_records(self.g[2], G2_STRIDE)
        # Some CONF layouts place g[5] immediately after g[2]. g[5] rows can
        # look like g[2] rows when stepped at 32 bytes, so stop g[2] at the
        # physical g[5] boundary when it appears before the scanned terminator.
        if self.g[2] < self.g[5]:
            physical_g2_count = (self.g[5] - self.g[2]) // G2_STRIDE
            if physical_g2_count > 0:
                self.g2_count = min(self.g2_count, physical_g2_count)
        self.g3_count = self._count_records(self.g[3], G3_STRIDE)
        self.g5_count = self._count_records(self.g[5], G5_STRIDE)
        self.g10_count = self.g[11] if isinstance(self.g[11], int) and self.g[11] < 0x1000 else 103

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
        self.opt_symbol_ptrs = []
        self.opt_first_by_type = {}
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

    def u16(self, off):
        self._check_range(off, 2)
        return struct.unpack_from("<H", self.data, off)[0]

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

    def _count_records(self, base, stride):
        count = 0
        while base + count * stride + stride <= len(self.data):
            vt = self.u16(base + count * stride)
            if vt < 0x0200 or vt > 0x0FFF:
                break
            count += 1
        return count

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
        g8_base = self.g[8]
        for bucket_idx in range(26):
            off = g8_base + bucket_idx * 8
            if off + 8 > len(self.data):
                break
            ptr = self.u32(off)
            count = self.u32(off + 4)
            if ptr == 0 and count == 0:
                continue
            if ptr < FLASH_BASE or ptr >= FLASH_BASE + len(self.data) or count > 300:
                continue
            prefix = chr(ord("A") + bucket_idx)
            table_off = ptr - FLASH_BASE
            for j in range(count):
                eoff = table_off + j * 4
                if eoff + 4 > len(self.data):
                    break
                c1 = self.u8(eoff)
                c2 = self.u8(eoff + 1)
                vid = self.u16(eoff + 2)
                if 0x20 < c1 < 0x7F and 0x20 < c2 < 0x7F and vid < 0x1000:
                    tags[vid] = prefix + chr(c1) + chr(c2)
        return tags

    def _build_option_table(self):
        """Locate and parse the enum option symbol stream.

        Layout: 12-byte entries, each
            +0  u32  symbol_ptr  (flash address of a NUL-terminated symbol)
            +4  u32  type_id     (g5 index boundary marker)
            +8  u32  option      (symbol slot inside that type)

        Returns (offset, count, flat_entries, by_type_dict, symbol_ptrs).
        """

        data = self.data
        data_len = len(data)
        unpack_entry = struct.Struct("<III").unpack_from

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
            if off + 12 > data_len:
                return None
            symbol_ptr, typ, opt = unpack_entry(data, off)
            symbol = string_at_ptr(symbol_ptr)
            if symbol is None:
                return None
            if not (0 <= typ < 0x200):
                return None
            if not (0 <= opt < 0x40):
                return None
            return symbol_ptr, typ, opt, symbol

        # Scan for the longest run of valid entries. The table moves between
        # firmware builds; older 8.0.x images place it just below 1 MiB.
        best = (0, 0)  # (count, start_offset)
        off = ENUM_SYMBOL_SEARCH_BASE
        while off + 12 <= data_len:
            if valid_entry(off) is None:
                off += 4
                continue
            start = off
            count = 0
            while valid_entry(off) is not None:
                count += 1
                off += 12
            if count > best[0]:
                best = (count, start)
            if count >= ENUM_SYMBOL_PRIMARY_RUN_MIN:
                break
        count, start = best
        if count < 50:
            return (None, 0, [], {}, [])

        entries = []
        by_type = {}
        for i in range(count):
            o = start + i * 12
            _symbol_ptr, typ, opt, symbol = valid_entry(o)
            entries.append((typ, opt, symbol))
            by_type.setdefault(typ, []).append((opt, symbol))
        for typ in by_type:
            by_type[typ].sort()

        symbol_ptrs = []
        i = 0
        while start + i * 12 + 4 <= data_len:
            ptr = struct.unpack_from("<I", data, start + i * 12)[0]
            if string_at_ptr(ptr) is None:
                break
            symbol_ptrs.append(ptr)
            i += 1
        return (start, count, entries, by_type, symbol_ptrs)

    def _option_symbols_from_window(self, idx, n_options, start, end):
        data = self.data
        data_len = len(data)
        end = min(end, data_len)
        unpack_entry = struct.Struct("<III").unpack_from

        def string_at_ptr(ptr, max_len=96):
            off = ptr - FLASH_BASE
            if off < 0 or off >= data_len:
                return None
            nul = data.find(b"\x00", off)
            if nul < 0 or nul - off > max_len or nul == off:
                return None
            raw = data[off:nul]
            if any(b < 0x20 or b > 0x7E for b in raw):
                return None
            return raw.decode("ascii")

        def valid_entry(off):
            if off + 12 > end:
                return None
            ptr, typ, opt = unpack_entry(data, off)
            if string_at_ptr(ptr) is None:
                return None
            if not (0 <= typ < 0x200):
                return None
            if not (0 <= opt < 0x40):
                return None
            return ptr, typ, opt

        off = start
        while off + 12 <= end:
            entry = valid_entry(off)
            if entry is None:
                off += 4
                continue
            run_start = off
            while True:
                entry = valid_entry(off)
                if entry is None:
                    break
                _ptr, typ, _opt = entry
                if typ == idx:
                    symbols = []
                    slot = off + 12
                    for _ in range(n_options):
                        next_entry = valid_entry(slot)
                        if next_entry is None:
                            break
                        ptr = next_entry[0]
                        symbols.append(string_at_ptr(ptr))
                        slot += 12
                    return symbols
                off += 12
            off = max(off + 4, run_start + 4)
        return []

    def _old_option_symbols_for_g5_index(self, idx, n_options):
        data = self.data
        data_len = len(data)
        unpack_entry = struct.Struct("<III").unpack_from
        symbols = {}

        def string_at_ptr(ptr, max_len=96):
            off = ptr - FLASH_BASE
            if off < 0 or off >= data_len:
                return None
            nul = data.find(b"\x00", off)
            if nul < 0 or nul - off > max_len or nul == off:
                return None
            raw = data[off:nul]
            if any(b < 0x20 or b > 0x7E for b in raw):
                return None
            return raw.decode("ascii")

        end = min(OLD_ENUM_SYMBOL_SEARCH_END, data_len)
        for off in range(OLD_ENUM_SYMBOL_SEARCH_BASE, end - 12 + 1, 4):
            key, opt, ptr = unpack_entry(data, off)
            if key != idx or not (0 <= opt < n_options):
                continue
            symbol = string_at_ptr(ptr)
            if symbol is None:
                continue
            symbols[opt] = symbol
            if len(symbols) == n_options:
                break

        return [symbols.get(opt) for opt in range(n_options)]

    def _ensure_option_table(self):
        if self.opt_entries is not None:
            return
        (
            self.opt_table_off, self.opt_table_count, self.opt_entries,
            self.opt_by_type, self.opt_symbol_ptrs,
        ) = self._build_option_table()
        self.opt_first_by_type = {}
        for pos, entry in enumerate(self.opt_entries):
            self.opt_first_by_type.setdefault(entry[0], pos)

    def option_symbols_for_g5_index(self, idx, n_options):
        """Return decoded option symbols for g5[idx], if the flat table covers it."""
        if n_options <= 0:
            return []
        use_old_primary = self.u32(CONF_BASE) <= OLD_ENUM_SYMBOL_MAX_DATA_VERSION
        if use_old_primary:
            old_symbols = self._old_option_symbols_for_g5_index(idx, n_options)
            if any(sym is not None for sym in old_symbols):
                return old_symbols
        symbols = self._option_symbols_from_window(
            idx, n_options, OLD_ENUM_SYMBOL_SEARCH_BASE,
            OLD_ENUM_SYMBOL_SEARCH_END)
        if len(symbols) >= n_options:
            return symbols
        self._ensure_option_table()
        pos = self.opt_first_by_type.get(idx)
        if pos is None:
            return self._option_symbols_from_window(
                idx, n_options, OLD_ENUM_SYMBOL_SEARCH_BASE,
                OLD_ENUM_SYMBOL_SEARCH_END)

        # The table is a flat enum-symbol stream. The first row carrying a g5
        # index is the previous enum's tail; the current enum starts at the
        # following row and may continue into the next index boundary row.
        symbols = []
        for slot in range(pos + 1, pos + 1 + n_options):
            if slot >= len(self.opt_symbol_ptrs):
                break
            symbols.append(self._string_at_ptr(self.opt_symbol_ptrs[slot]))
        if len(symbols) < n_options:
            fallback = self._option_symbols_from_window(
                idx, n_options, OLD_ENUM_SYMBOL_SEARCH_BASE,
                OLD_ENUM_SYMBOL_SEARCH_END)
            if len(fallback) > len(symbols):
                return fallback
        return symbols

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

    def conf_layout(self):
        pointer_offsets = sorted(
            off for off in self.g.values()
            if isinstance(off, int) and CONF_BASE <= off < CONF_BASE + CONF_SIZE
        )
        out = []
        for index in range(20):
            off = self.g.get(index)
            if not isinstance(off, int) or not (
                    CONF_BASE <= off < CONF_BASE + CONF_SIZE):
                out.append({
                    "index": index, "value": off,
                    "offset": None, "end": None, "size": None,
                })
                continue
            end = CONF_BASE + CONF_SIZE
            for candidate in pointer_offsets:
                if candidate > off:
                    end = candidate
                    break
            out.append({
                "index": index, "value": off, "offset": off,
                "end": end, "size": end - off,
            })
        return out

    def section_end(self, index):
        for sec in self.conf_layout():
            if sec["index"] == index:
                return sec["end"]
        return None

    def var_short_name(self, vid):
        if not self.name_namespace_matches_descriptor(vid):
            return ""
        return self.name_buckets.get(vid, "")

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
            vt = self.u16(off)
            rec.update({
                "vid_type": vt,
                "active": bool(vt & 1),
                "subtype": self.u16(off + 2),
                "linked_var_id": self.u16(off + 4),
                "class_tag": self.u16(off + 6),
                "max_length": self.u16(off + 8),
            })
        elif arr == "g2":
            vt = self.u16(off)
            scale = self.u16(off + 22)
            step = self.u16(off + 24)
            rec.update({
                "vid_type": vt,
                "active": bool(vt & 1),
                "enum_ref": self.u16(off + 2),
                "source_index": self.u16(off + 4),
                "storage_class": self.u16(off + 6),
                "default": self.u32(off + 8),
                "max": self.u32(off + 12),
                "min": self.i32(off + 16),
                "format": self.u16(off + 20),
                "scale": scale,
                "step": step,
                "bounds_slot": self.u8(off + 26),
                "sample_source_id": self.u8(off + 27),
                "quantity_class": self.u32(off + 28),
            })
            if scale:
                rec["scaled_default"] = rec["default"] / scale
                rec["scaled_min"] = rec["min"] / scale
                rec["scaled_max"] = rec["max"] / scale
                rec["scaled_step"] = step / scale
        elif arr == "g3":
            vt = self.u16(off)
            fixed_mask = self.u32(off + 8)
            editable_mask = self.u32(off + 12)
            bit_count = self.u8(off + 16)
            list_offset = self.u16(off + 18)
            g4_base = self.g.get(4)
            list_file_off = None
            g4_codes = []
            if isinstance(g4_base, int):
                list_file_off = g4_base + list_offset
                if list_file_off + bit_count <= len(self.data):
                    g4_codes = list(self.data[list_file_off:list_file_off + bit_count])
            rec.update({
                "vid_type": vt,
                "active": bool(vt & 1),
                "subtype": self.u16(off + 2),
                "linked_var_id": self.u16(off + 4),
                "class_tag": self.u16(off + 6),
                "fixed_mask": fixed_mask,
                "editable_mask": editable_mask,
                "mask_bits": [i for i in range(32) if (editable_mask >> i) & 1],
                "bit_count": bit_count,
                "g4_list_offset": list_offset,
                "g4_list_file_offset": list_file_off,
                "g4_codes": g4_codes,
            })
        elif arr == "g5":
            vt = self.u16(off)
            options_offset = self.u16(off + 2)
            n_options = self.u8(off + 9)
            option_mask = self.u32(off + 12)
            g4_base = self.g.get(4)
            options_file_off = None
            g4_codes = []
            if isinstance(g4_base, int):
                options_file_off = g4_base + options_offset
                if options_file_off + n_options <= len(self.data):
                    g4_codes = list(self.data[options_file_off:options_file_off + n_options])
            rec.update({
                "vid_type": vt,
                "active": bool(vt & 1),
                "g4_options_offset": options_offset,
                "g4_options_file_offset": options_file_off,
                "g4_codes": g4_codes,
                "owner_ref": self.u16(off + 4),
                "item_class": self.u16(off + 6),
                "default_option": self.u8(off + 8),
                "n_options": n_options,
                "zero": self.u16(off + 10),
                "option_mask": option_mask,
                "enabled_options": [i for i in range(32) if (option_mask >> i) & 1],
            })
        elif arr == "g10":
            mode_bytes = self.data[off + 2:off + G10_STRIDE]
            rec.update({
                "modes": [
                    MODE_NAMES[i]
                    for i, value in enumerate(mode_bytes[:len(MODE_NAMES)])
                    if value
                ],
                "mode_bytes": mode_bytes,
            })
        return rec

    def edf_str_records(self):
        base = self.g.get(15)
        if not isinstance(base, int):
            return []
        count = self.u16(base + 4)
        rec_base = self.ptr_to_off(self.u32(base + 8))
        if rec_base is None:
            return []
        out = []
        for i in range(count):
            off = rec_base + i * SUMMARY_STRIDE
            if off + SUMMARY_STRIDE > len(self.data):
                break
            kind = self.u32(off + 4)
            var_a = self.u16(off + 8)
            var_b = self.u16(off + 10)
            selected = var_b if kind < 3 else var_a
            label_ptr = self.u32(off + 24)
            unit_ptr = self.u32(off + 28)
            edf_label = self._string_at_ptr(label_ptr, allow_empty=True)
            edf_unit = self._string_at_ptr(unit_ptr, allow_empty=True)
            out.append({
                "index": i,
                "offset": off,
                "field_id": self.u32(off),
                "kind": kind,
                "var_a": var_a,
                "var_b": var_b,
                "selected_var": selected,
                "selector_a": self.u16(off + 12),
                "selector_b": self.u16(off + 14),
                "scale": self.f32(off + 16),
                "record_class": self.u8(off + 20),
                "active": bool(self.u8(off + 21)),
                "reserved16": self.u16(off + 22),
                "edf_label": edf_label,
                "edf_unit": edf_unit,
                "hydrated": edf_label not in (None, ""),
                "edf_output_scale": self.f32(off + 32),
                "short_name": self.var_short_name(selected),
                "long_name": self.var_long_name(selected),
                "name": self.var_name(selected),
                "raw": self.data[off:off + SUMMARY_STRIDE],
            })
        return out

    def edf_streams(self):
        base = self.g.get(16)
        if not isinstance(base, int):
            return []
        out = []
        end = self.section_end(16) or len(self.data)
        i = 0
        while True:
            off = base + i * 16
            if off + 16 > end:
                break
            period = self.u16(off)
            samples = self.u16(off + 2)
            count = self.u32(off + 4)
            tag_ptr = self.u32(off + 8)
            table_ptr = self.u32(off + 12)
            if period == 0 or tag_ptr == 0 or table_ptr == 0:
                break
            tag = self._string_at_ptr(tag_ptr)
            table_off = self.ptr_to_off(table_ptr)
            if not tag or table_off is None:
                break
            signals = []
            for j in range(count):
                roff = table_off + j * 16
                signals.append({
                    "index": j,
                    "offset": roff,
                    "id": self.u32(roff),
                    "name": self._string_at_ptr(self.u32(roff + 4)) or "",
                    "unit": self._string_at_ptr(self.u32(roff + 8),
                                                allow_empty=True) or "",
                    "scale": self.f32(roff + 12),
                })
            out.append({
                "index": i,
                "offset": off,
                "tag": tag,
                "period_ms": period,
                "samples_per_60s": samples,
                "signal_count": count,
                "signals": signals,
            })
            i += 1
        return out

    def event_defs(self):
        base = self.g.get(12)
        if not isinstance(base, int):
            return []
        out = []
        end = self.section_end(12) or len(self.data)
        i = 0
        while True:
            off = base + i * 36
            if off + 36 > end:
                break
            name_ptr = self.u32(off)
            code_ptr = self.u32(off + 4)
            if name_ptr == 0 or code_ptr == 0:
                break
            name = self._string_at_ptr(name_ptr)
            code = self._string_at_ptr(code_ptr)
            if not name or not code:
                break
            out.append({
                "index": i,
                "offset": off,
                "name": name,
                "code": code,
                "event_class": self.u32(off + 8),
                "period_or_limit": self.u32(off + 0x0c),
                "record_kind": self.u32(off + 0x10),
                "flags_a": self.u32(off + 0x14),
                "buffer_or_mask": self.u32(off + 0x18),
                "retention_or_batch": self.u32(off + 0x1c),
                "packed_ref": self.u32(off + 0x20),
                "raw": self.data[off:off + 36],
            })
            i += 1
        return out

    def event_routes(self):
        base = self.g.get(13)
        if not isinstance(base, int):
            return []
        end = self.section_end(13) or len(self.data)
        count = max(0, (end - base) // G13_ROUTE_STRIDE)
        events = self.event_defs()
        out = []
        for i in range(count):
            off = base + i * G13_ROUTE_STRIDE
            event_index = self.u16(off)
            event = events[event_index] if 0 <= event_index < len(events) else None
            out.append({
                "index": i,
                "offset": off,
                "event_index": event_index,
                "event_code": None if event is None else event["code"],
                "event_name": None if event is None else event["name"],
                "subindex": self.u16(off + 2),
                "route": self.u16(off + 4),
                "raw": self.data[off:off + G13_ROUTE_STRIDE],
            })
        return out

    def _event_label_schema(self, off, schema_bytes):
        if schema_bytes == G17_EVENT_SCHEMA_SIZE:
            event_record_bytes = self.u16(off)
            label_count = self.u16(off + 2)
            edf_record_bytes = self.u32(off + 4)
            fifo_capacity = self.u32(off + 8)
            flags_off = off + 0x0c
            tag_ptr = self.u32(off + 0x10)
            constant = self.u32(off + 0x14)
            label_table = self.u32(off + 0x18)
            if event_record_bytes == 0:
                return None
        else:
            event_record_bytes = None
            label_count = self.u16(off)
            edf_record_bytes = self.u16(off + 2)
            fifo_capacity = self.u32(off + 4)
            flags_off = off + 8
            tag_ptr = self.u32(off + 0x0c)
            constant = None
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
        return {
            "schema_bytes": schema_bytes,
            "event_record_bytes": event_record_bytes,
            "label_count": label_count,
            "edf_record_bytes": edf_record_bytes,
            "fifo_capacity": fifo_capacity,
            "writer_enabled": int(self.u8(flags_off) != 0),
            "backdate_onset": int(self.u8(flags_off + 1) != 0),
            "flags": flags,
            "tag": tag,
            "constant": constant,
            "label_table": label_table,
            "labels": labels,
        }

    def event_labels(self):
        base = self.g.get(17)
        if not isinstance(base, int):
            return []
        end = self.section_end(17) or len(self.data)
        for stride in (G17_EVENT_SCHEMA_SIZE, G17_LEGACY_EVENT_SCHEMA_SIZE):
            if (base + stride <= end and
                    self._event_label_schema(base, stride) is not None):
                break
        else:
            return []

        out = []
        off = base
        while off + stride <= end:
            row = self._event_label_schema(off, stride)
            if row is None:
                break
            row["index"] = len(out)
            row["offset"] = off
            out.append(row)
            off += stride
        return out

    def periodic_collections(self):
        base = self.g.get(14)
        if not isinstance(base, int):
            return []
        out = []
        end = self.section_end(14) or len(self.data)
        i = 0
        while True:
            off = base + i * G14_COLLECTION_STRIDE
            if off + G14_COLLECTION_STRIDE > end:
                break
            tag_ptr = self.u32(off)
            signal_count = self.u8(off + 0x28)
            id_list_ptr = self.u32(off + 0x2c)
            if tag_ptr == 0 or id_list_ptr == 0:
                break
            tag = self._string_at_ptr(tag_ptr)
            id_list_off = self.ptr_to_off(id_list_ptr)
            meta_off = self.ptr_to_off(self.u32(off + 0x30))
            if not tag or id_list_off is None:
                break
            signals = []
            for j in range(signal_count):
                vid = self.u16(id_list_off + j * 2)
                meta_file_off = None if meta_off is None else meta_off + j * 0x30
                meta = None
                if meta_file_off is not None and meta_file_off + 0x30 <= len(self.data):
                    meta = {
                        "min": self.f64(meta_file_off),
                        "max": self.f64(meta_file_off + 8),
                        "resolution": self.f64(meta_file_off + 0x10),
                        "scale": self.f64(meta_file_off + 0x18),
                        "class_flags": self.u32(meta_file_off + 0x20),
                        "transform": self.u32(meta_file_off + 0x28),
                    }
                signals.append({
                    "index": j,
                    "var_id": vid,
                    "short_name": self.var_short_name(vid),
                    "long_name": self.var_long_name(vid),
                    "name": self.var_name(vid),
                    "metadata_offset": meta_file_off,
                    "metadata": meta,
                })
            out.append({
                "index": i,
                "offset": off,
                "tag": tag,
                "period_ms": self.u32(off + 4),
                "window_or_period": self.u32(off + 8),
                "buffer_size": self.u32(off + 0x0c),
                "record_size": self.u32(off + 0x10),
                "collection_param_a": self.u32(off + 0x14),
                "collection_param_b": self.u32(off + 0x18),
                "collection_kind": self.u32(off + 0x1c),
                "flags": self.u32(off + 0x20),
                "active_bit": self.u16(off + 0x24),
                "signal_count": signal_count,
                "signals": signals,
                "raw": self.data[off:off + G14_COLLECTION_STRIDE],
            })
            i += 1
        return out

    def storage_sets(self):
        base = self.g.get(6)
        if not isinstance(base, int):
            return []
        out = []
        end = self.section_end(6) or len(self.data)
        i = 0
        while True:
            off = base + i * 16
            if off + 16 > end:
                break
            tag_raw = self.data[off:off + 4]
            if tag_raw[3] != 0 or any(b < 0x20 or b > 0x7E for b in tag_raw[:3]):
                break
            ptr = self.u32(off + 8)
            count = self.u32(off + 12)
            list_off = self.ptr_to_off(ptr)
            if list_off is None:
                break
            vars_out = []
            for j in range(count):
                vid = self.u16(list_off + j * 2)
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
                "tag": tag_raw[:3].decode("ascii"),
                "set_id": self.u32(off + 4),
                "list_ptr": ptr,
                "count": count,
                "vars": vars_out,
            })
            i += 1
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
        data_version = self.u32(CONF_BASE)
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

    def descriptor_status(self, vid):
        disp = self.dispatch_var_id(vid)
        if not disp:
            return "MISSING", None
        arr, base, stride, idx = disp
        vt = self.u16(base + idx * stride)
        return f"{arr}[{idx}] {'ACT' if vt & 1 else 'INACT'}", disp

    def cmd_info(self):
        platform = self.ascii_field(CONF_BASE + 0x18, 0x10)
        model = self.ascii_field(CONF_BASE + 0x28, 0x10)
        codename = self.ascii_field(CONF_BASE + 0x38, 0x10)
        git = self.ascii_field(CONF_BASE + 0x68, 0x10)
        data_version = self.u32(CONF_BASE)
        platform_id = self.u32(CONF_BASE + 4)
        variant_id = self.u32(CONF_VID_OFF)

        print(f"  File:     {self.path}")
        print(f"  Platform: {platform} / {model} / {codename}")
        print("  Firmware: data_version=%d platform_id=%d variant_id=%d" %
              (data_version, platform_id, variant_id))
        print(f"  Git:      {git}")
        versions = {rec["kind"]: rec for rec in self.version_records()}
        if "bootloader" in versions:
            print(f"  Boot:     {versions['bootloader']['version']}")
        if "appx" in versions:
            print(f"  APPX:     {versions['appx']['version']}")
        if "data_model" in versions:
            print(f"  Data:     {versions['data_model']['identifier']}")
        print(f"  MT:       0x{self.mt_off:05X} (CONF+0x{self.mt_off - CONF_BASE:04X})")
        print()
        print("  Descriptor arrays:")
        print("    globals[1]: %4d records x %dB  var_ids 0x%04X-0x%04X" %
              (self.g1_count, G1_STRIDE, self.g1_id_base,
               self.g2_id_base - 1))
        print("    globals[2]: %4d records x %dB  var_ids 0x%04X-0x%04X" %
              (self.g2_count, G2_STRIDE, self.g2_id_base,
               self.g3_id_base - 1))
        print("    globals[3]: %4d records x %dB  var_ids 0x%04X-0x%04X" %
              (self.g3_count, G3_STRIDE, self.g3_id_base,
               self.g5_id_base - 1))
        print("    globals[5]: %4d records x %dB  var_ids 0x%04X-0x%04X" %
              (self.g5_count, G5_STRIDE, self.g5_id_base,
               self.g5_id_base + self.g5_count - 1))
        print(f"    Max var_id with descriptor: 0x{self.max_var_id:04X}")
        print(f"  globals[10]: {self.g10_count:4d} per-mode variable enables")
        if self._long_names is None:
            print("  Long names:  not probed until needed")
        elif self.long_name_table_off is None:
            print(f"  Long names:  {len(self.long_names):4d} active bindings (table not found)")
        else:
            print("  Long names:  %4d active bindings @ 0x%05X (%d entries)" %
                  (len(self.long_names), self.long_name_table_off,
                   self.long_name_table_count))
        print(f"  Name table:  {len(self.name_buckets):4d} 3-char tags")
        if self.opt_entries is None:
            print("  Enum symbols: not probed until var-options")
        elif self.opt_table_off is None:
            print("  Enum symbols:(table not found)")
        else:
            print("  Enum symbols:%4d flat (symbol,type,opt) entries @ 0x%05X" %
                  (self.opt_table_count, self.opt_table_off))
        if self.gui_text_available is None:
            print("  GUI text:    not probed until text/text-search")
        elif self.gui_text_available:
            print("  GUI text:    decoder ready (%d ids/lang, stride 0x%X)" %
                  (self.gui_text_count, self.gui_text_lang_stride))
        else:
            print("  GUI text:    decoder not available for this image")

    def cmd_versions(self, block=None):
        wanted = None
        if block is not None:
            key = block.lower()
            wanted = VERSION_BLOCK_ALIASES.get(key)
            if wanted is None:
                raise ValueError(
                    "unknown version block %r; expected one of: %s" %
                    (block, ", ".join(sorted(VERSION_BLOCK_ALIASES))))
        for rec in self.version_records():
            if wanted is not None and rec["kind"] not in wanted:
                continue
            fields = dict(rec)
            if "offset" in fields:
                fields["offset"] = "0x%05X" % fields["offset"]
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
                "act": fmt_bool(rec.get("active", False)),
                "vt": "0x%04X" % rec.get("vid_type", 0),
            })
        if rec["array"] == "g1":
            fields.update({
                "subtype": "0x%04X" % rec["subtype"],
                "linked_var": "0x%04X" % rec["linked_var_id"],
                "class_tag": "0x%04X" % rec["class_tag"],
                "max_len": rec["max_length"],
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
                "raw_default": rec["default"],
                "raw_min": rec["min"],
                "raw_max": rec["max"],
                "format": "0x%04X" % rec["format"],
                "bounds_slot": "0x%02X" % rec["bounds_slot"],
                "sample_source": rec["sample_source_id"],
                "quantity_class": "0x%08X" % rec["quantity_class"],
            })
        elif rec["array"] == "g3":
            fields.update({
                "g4_list": "+0x%04X" % rec["g4_list_offset"],
                "g4_off": fmt_off(rec["g4_list_file_offset"]),
                "bits": rec["bit_count"],
                "fixed": "0x%08X" % rec["fixed_mask"],
                "editable": "0x%08X" % rec["editable_mask"],
                "set_bits": rec["mask_bits"],
                "g4_codes": ["0x%02X" % value for value in rec["g4_codes"]],
            })
        elif rec["array"] == "g5":
            fields.update({
                "g4_opts": "+0x%04X" % rec["g4_options_offset"],
                "g4_off": fmt_off(rec["g4_options_file_offset"]),
                "default_opt": rec["default_option"],
                "n_opts": rec["n_options"],
                "mask": "0x%08X" % rec["option_mask"],
                "enabled": rec["enabled_options"],
                "owner_ref": "0x%04X" % rec["owner_ref"],
                "item_class": "0x%04X" % rec["item_class"],
                "g4_codes": ["0x%02X" % value for value in rec["g4_codes"]],
            })
        elif rec["array"] == "g10":
            fields.update({
                "modes": rec["modes"],
                "mode_bytes": " ".join("%02X" % b for b in rec["mode_bytes"]),
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
                modes = ",".join(g10["modes"])
                print(f"  g10[{i:3d}]:  modes={modes}")
                print(f"             bytes={' '.join(f'{b:02X}' for b in g10['mode_bytes'][:11])}")
                break
        else:
            print("  g10:       (not registered)")

    def cmd_mode(self, mode_idx):
        if mode_idx < 0 or mode_idx >= len(MODE_NAMES):
            raise ValueError("mode index must be 0..%d" % (len(MODE_NAMES) - 1))

        mode_name = MODE_NAMES[mode_idx]
        prefix = MODE_PREFIXES.get(mode_idx)
        vids = {}
        for i in range(self.g10_count):
            g10 = self.read_descriptor("g10", i)
            if mode_name in g10["modes"]:
                vids[g10["var_id"]] = "g10"
        if prefix:
            for vid, name in self.long_names.items():
                if (self.name_namespace_matches_descriptor(vid)
                        and name.startswith(prefix) and vid not in vids):
                    vids[vid] = "name"

        for vid in sorted(vids):
            status, _ = self.descriptor_status(vid)
            emit_line(
                mode=mode_idx,
                mode_name=mode_name,
                var="0x%04X" % vid,
                short=fmt_text(self.var_short_name(vid)),
                long=fmt_text(self.var_long_name(vid)),
                source=vids[vid],
                status=status,
            )

    def cmd_var_options(self, ident, verbose=False):
        """Print enum option slots for a var_id, long name, or 3-char tag."""
        vid = self._resolve_var_ident(ident)
        if vid is None:
            raise ValueError(
                "could not resolve %r to a var_id; use a numeric id, long name, "
                "3-char tag, or underscored short name" % ident)
        self.cmd_var_options_by_id(vid, verbose)

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
                    enabled=1 if ((rec["option_mask"] >> opt) & 1) else 0,
                    default=1 if opt == rec["default_option"] else 0,
                    g4_code=(
                        "0x%02X" % rec["g4_codes"][opt]
                        if opt < len(rec["g4_codes"]) else "n/a"
                    ),
                    symbol=fmt_text(symbols[opt] if opt < len(symbols) else None),
                )
            return

        print("  var_id:   0x%04X  tag=%s  name=%s" %
              (vid, fmt_text(tag), fmt_text(name)))
        print(
            "  dispatch: g[5][%d]   n_opts=%d   default=%d   mask=0x%08X"
            % (idx, rec["n_options"], rec["default_option"],
               rec["option_mask"])
        )
        print(
            "  g4:       +0x%04X file=%s codes=%s"
            % (
                rec["g4_options_offset"],
                fmt_off(rec["g4_options_file_offset"]),
                ",".join("0x%02X" % value for value in rec["g4_codes"]) or "n/a",
            )
        )
        print("  options:")
        for opt in range(rec["n_options"]):
            flags = []
            if (rec["option_mask"] >> opt) & 1:
                flags.append("enabled")
            if opt == rec["default_option"]:
                flags.append("default")
            suffix = " [%s]" % ",".join(flags) if flags else ""
            g4_code = (
                "0x%02X" % rec["g4_codes"][opt]
                if opt < len(rec["g4_codes"]) else "n/a"
            )
            symbol = symbols[opt] if opt < len(symbols) else "n/a"
            print(f"    {opt:3d}: g4={g4_code} symbol={symbol!r}{suffix}")

    def cmd_text(self, text_id, lang=0):
        if not self._ensure_gui_text_decoder():
            raise ValueError("GUI text decoder is not available for this image")
        text = self.decode_gui_text(text_id, lang)
        shown = text.replace("\r", "\\r").replace("\n", "\\n")
        if not shown:
            shown = "(empty)"
        lang_name = LANGUAGE_NAMES[lang] if 0 <= lang < len(LANGUAGE_NAMES) else "n/a"
        print(f"  0x{text_id:03X} lang={lang} ({lang_name}): {shown}")

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
        if not found:
            print(f'  No GUI text matching "{query}"')
            return
        print(f"  {'text_id':>7}  text")
        print(f"  {'-' * 7}  {'-' * 60}")
        for text_id, text in found:
            shown = text.replace("\r", "\\r").replace("\n", "\\n")
            print(f"  0x{text_id:03X}  {shown}")

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
            out = [row for row in out if row.get("active") is True]
        if inactive:
            out = [row for row in out if row.get("active") is False]
        if name:
            rx = re.compile(name, re.IGNORECASE)
            out = [row for row in out if rx.search(descriptor_filter_text(row))]
        return out

    def cmd_globals(self):
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
                end=fmt_off(sec.get("end")),
                size=(
                    "0x%X" % sec["size"]
                    if sec.get("size") is not None else "n/a"
                ),
            )

    def cmd_conf_layout(self):
        for sec in sorted(self.conf_layout(),
                          key=lambda row: row["offset"] or 0xFFFFFFFF):
            if sec["offset"] is None or sec["end"] is None:
                continue
            emit_line(
                global_index=sec["index"],
                off=fmt_off(sec["offset"]),
                end=fmt_off(sec["end"]),
                addr=fmt_addr(self.off_to_addr(sec["offset"])),
                size="0x%X" % sec["size"],
            )

    def cmd_vars(self, arr_name, active=False, inactive=False, name=None,
                 verbose=False):
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
            rows = self.filter_rows(rows, active=active, inactive=inactive, name=name)
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
                "act": fmt_bool(row["active"]),
                "field": row["field_id"],
                "kind": row["kind"],
                "record_class": row["record_class"],
                "selected_var": "0x%04X" % row["selected_var"],
                "short": fmt_text(row["short_name"]),
                "long": fmt_text(row["long_name"]),
                "hydrated": int(row["hydrated"]),
                "edf_label": fmt_text(row["edf_label"]),
                "edf_unit": fmt_text(row["edf_unit"]),
                "scale": fmt_number(row["scale"]),
                "edf_scale": fmt_number(row["edf_output_scale"]),
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
                print("  samples_per_60s: %d" % item["samples_per_60s"])
                print("  signal_count: %d" % item["signal_count"])
            for sig in item["signals"]:
                emit_line(
                    stream=item["tag"],
                    stream_idx=item["index"],
                    signal_idx=sig["index"],
                    off=fmt_off(sig["offset"]),
                    id="0x%04X" % sig["id"],
                    name=fmt_text(sig["name"]),
                    unit=fmt_text(sig["unit"]),
                    scale=fmt_number(sig["scale"]),
                    period_ms=item["period_ms"],
                    samples_per_60s=item["samples_per_60s"],
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
                "event_class": row["event_class"],
                "record_kind": row["record_kind"],
                "flags": "0x%08X" % row["flags_a"],
                "buffer_or_mask": "0x%08X" % row["buffer_or_mask"],
            }
            if verbose:
                print("[event %d]" % row["index"])
                for key, value in fields.items():
                    print("  %s: %s" % (key, line_value(value)))
                print("  period_or_limit: %s" % row["period_or_limit"])
                print("  retention_or_batch: %s" % row["retention_or_batch"])
                print("  packed_ref: 0x%08X" % row["packed_ref"])
            else:
                emit_line(**fields)

    def cmd_event_routes(self, filters=None):
        wanted = [f.lower() for f in (filters or [])]
        for row in self.event_routes():
            if wanted:
                haystack = "%s %s" % (
                    fmt_text(row["event_code"]), fmt_text(row["event_name"]))
                if not any(f in haystack.lower() for f in wanted):
                    continue
            emit_line(
                idx=row["index"],
                off=fmt_off(row["offset"]),
                event_idx=row["event_index"],
                subindex=row["subindex"],
                route=row["route"],
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
                    backdate_onset=table["backdate_onset"],
                    flags="0x%08X" % table["flags"],
                )

    def cmd_collections(self, names=None, verbose=False):
        wanted = {name.upper().lstrip("&") for name in (names or [])}
        for row in self.periodic_collections():
            if wanted and row["tag"].upper().lstrip("&") not in wanted:
                continue
            if verbose:
                emit_line(
                    collection=row["tag"],
                    idx=row["index"],
                    off=fmt_off(row["offset"]),
                    period_ms=row["period_ms"],
                    window=row["window_or_period"],
                    buffer=row["buffer_size"],
                    record_size=row["record_size"],
                    active_bit=row["active_bit"],
                    flags="0x%08X" % row["flags"],
                    signals=row["signal_count"],
                )
            for sig in row["signals"]:
                meta = sig.get("metadata") or {}
                emit_line(
                    collection=row["tag"],
                    collection_idx=row["index"],
                    signal_idx=sig["index"],
                    var="0x%04X" % sig["var_id"],
                    short=fmt_text(sig["short_name"]),
                    long=fmt_text(sig["long_name"]),
                    min=fmt_number(meta.get("min", 0)) if meta else "n/a",
                    max=fmt_number(meta.get("max", 0)) if meta else "n/a",
                    scale=fmt_number(meta.get("scale", 0)) if meta else "n/a",
                    metadata_off=fmt_off(sig["metadata_offset"]),
                )

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
                    set_id="0x%04X" % row["set_id"],
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
                    set_id="0x%04X" % row["set_id"],
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


def _parse_edit_bool(value, what):
    text = value.strip().lower()
    if text in ("1", "true", "yes", "on", "act", "active"):
        return True
    if text in ("0", "false", "no", "off", "inact", "inactive"):
        return False
    raise ValueError("%s must be on/off, true/false, yes/no, or 1/0" % what)


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


def _parse_mode_list(value):
    text = value.strip()
    if text.lower() in ("none", "off", ""):
        return bytearray(G10_STRIDE - 2)
    if text.lower() == "all":
        return bytearray([1] * (G10_STRIDE - 2))

    out = bytearray(G10_STRIDE - 2)
    parts = [part.strip() for part in re.split(r"[,|+]", text)]
    if not parts or any(not part for part in parts):
        raise ValueError("modes requires mode names/indices, none, or all")
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


def _format_modes(mode_bytes):
    names = [
        MODE_NAMES[idx] if idx < len(MODE_NAMES) else str(idx)
        for idx, enabled in enumerate(mode_bytes)
        if enabled
    ]
    return ",".join(names) if names else "none"


def _encode_scaled_edit(value, scale, field):
    display = _parse_edit_decimal(value, field.name)
    raw = display * scale if scale else display
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
    if field.kind == "active":
        current = state[field.attr]
        if _parse_edit_bool(value, field.name):
            return current | 1
        return current & ~1
    if field.kind == "modes":
        return _parse_mode_list(value)
    if field.kind == "scaled" and not edit["raw"]:
        return _encode_scaled_edit(value, state["scale"], field)
    return field.normalize_int(_parse_edit_int(value, field.name))


def _g4_pool_limit(fw):
    base = fw.g.get(4)
    end = fw.section_end(4)
    if not isinstance(base, int) or not isinstance(end, int) or end < base:
        return None
    return end - base


def _validate_edit_state(fw, target, state, touched):
    warnings = []
    arr = target["array"]
    name = target["name"]
    if arr == "g2" and touched & {"default", "min", "max", "scale"}:
        if state["min"] > state["max"]:
            raise ValueError("%s has min greater than max" % name)
        if not state["min"] <= state["default"] <= state["max"]:
            raise ValueError("%s default is outside min..max" % name)

    if arr == "g3":
        if state["bit_count"] > 32:
            raise ValueError("%s bit_count exceeds 32" % name)
        outside = (state["fixed_mask"] | state["editable_mask"]) & ~(
            (1 << state["bit_count"]) - 1 if state["bit_count"] else 0
        )
        if outside:
            warnings.append(
                "%s fixed/editable masks contain bits outside bit_count: "
                "0x%08X" % (name, outside)
            )
        limit = _g4_pool_limit(fw)
        if limit is not None:
            end = state["g4_list_offset"] + state["bit_count"]
            if end > limit:
                raise ValueError(
                    "%s g4 list ends at +0x%X beyond globals[4] size 0x%X" %
                    (name, end, limit)
                )

    if arr == "g5":
        if state["n_options"] > 32:
            raise ValueError("%s n_opts exceeds 32" % name)
        if state["n_options"] and state["default_option"] >= state["n_options"]:
            raise ValueError("%s default_opt is outside n_opts" % name)
        if state["n_options"] == 0 and state["default_option"] != 0:
            raise ValueError("%s has nonzero default_opt with no options" % name)
        outside = (state["option_mask"] & ~((1 << state["n_options"]) - 1)
                   if state["n_options"] else state["option_mask"])
        if outside:
            warnings.append(
                "%s option mask contains bits outside n_opts: 0x%08X" %
                (name, outside)
            )
        limit = _g4_pool_limit(fw)
        if limit is not None:
            end = state["g4_options_offset"] + state["n_options"]
            if end > limit:
                raise ValueError(
                    "%s g4 options end at +0x%X beyond globals[4] size 0x%X" %
                    (name, end, limit)
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
    if field.kind == "active":
        return ("on" if value & 1 else "off") + " (vt=0x%04X)" % value
    if field.kind == "modes":
        return _format_modes(value)
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
        if edit["field"].kind == "modes":
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
    try:
        mode = parse_numeric_arg(value, "mode")
    except argparse.ArgumentTypeError as exc:
        raise argparse.ArgumentTypeError(
            "invalid mode %r; use decimal 0..%d or explicit hex like 0x6" %
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


def fmt_bool(value):
    return "ACT" if value else "off"


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
    subparsers.add_parser("info", help="show firmware summary and array sizes")
    p = subparsers.add_parser("versions", help="extract firmware version identifiers")
    p.add_argument(
        "block",
        nargs="?",
        help="optional block filter, e.g. fgbl, bootloader, fgcb, conf, appx",
    )

    p = subparsers.add_parser(
        "var",
        help="show one variable descriptor by id, long name, or short tag",
    )
    p.add_argument("ident", help="var_id, long name, tag, or _TAG")
    p.add_argument("--verbose", action="store_true", help="show multi-line details")

    p = subparsers.add_parser("mode", help="show settings associated with a therapy mode")
    p.add_argument("mode", type=parse_mode_arg,
                   help="mode index 0..10, decimal or explicit hex")

    p = subparsers.add_parser("globals", help="list globals[] values")

    subparsers.add_parser("conf-layout", help="list CONF layout inferred from globals[]")

    p = subparsers.add_parser("vars", help="list variables")
    p.add_argument(
        "--array",
        choices=("all", "g1", "g2", "g3", "g5", "g10"),
        default="all",
        help="descriptor array to list; default scans g1/g2/g3/g5",
    )
    p.add_argument("--active", action="store_true", help="only active records")
    p.add_argument("--inactive", action="store_true", help="only inactive records")
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

    p = subparsers.add_parser("events", help="list globals[12] event definitions")
    p.add_argument("filter", nargs="*", help="optional code/name substring filter")
    p.add_argument("--verbose", action="store_true", help="show multi-line details")

    p = subparsers.add_parser("event-routes", help="list globals[13] event route triples")
    p.add_argument("filter", nargs="*", help="optional code/name substring filter")

    p = subparsers.add_parser("event-labels", help="list globals[17] event label tables")
    p.add_argument("table", nargs="*", help="optional table tag filter, e.g. EVE CSL")

    p = subparsers.add_parser("collections", help="list globals[14] collection tables")
    p.add_argument("collection", nargs="*", help="optional collection tag filter, e.g. NRF APD")
    p.add_argument("--verbose", action="store_true", help="include collection rows")

    p = subparsers.add_parser("storage-sets", help="list globals[6] persisted setting sets")
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
    elif command == "versions":
        fw.cmd_versions(args.block)
    elif command == "var":
        fw.cmd_var(resolve_var_arg(fw, args.ident), args.verbose)
    elif command == "globals":
        fw.cmd_globals()
    elif command == "conf-layout":
        fw.cmd_conf_layout()
    elif command == "vars":
        if args.active and args.inactive:
            raise ValueError("--active and --inactive are mutually exclusive")
        fw.cmd_vars(args.array, args.active, args.inactive, args.name,
                    args.verbose)
    elif command == "mode":
        fw.cmd_mode(args.mode)
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
    elif command == "event-routes":
        fw.cmd_event_routes(args.filter)
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

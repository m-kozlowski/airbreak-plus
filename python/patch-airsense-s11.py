#!/usr/bin/env python3

# This work was not produced in affiliation with any of the device manufactures and is,
# and is intended to be, an independent, third-party research project.
#
# This work is presented for research and educational purposes only. Any use or reproduction
# of this work is at your sole risk. The work is provided "as is" and "as available", and without
# warranties of any kind, whether express or implied, including, but not limited to, implied
# warranties of merchantability, non-infringement of third party rights, or fitness for a
# particular purpose.
#
# See LICENSE in main repository for distribution license and additional restrictions.

import argparse
import fnmatch
import hashlib
import os.path
import re
import struct
import sys

try:
    import crcmod.predefined
except ImportError:
    crcmod = None


def crc16_ccitt_false(data, crc=0xFFFF):
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            if crc & 0x8000:
                crc = ((crc << 1) ^ 0x1021) & 0xFFFF
            else:
                crc = (crc << 1) & 0xFFFF
    return crc


def str2bool(value):
    if isinstance(value, bool):
        return value
    if value.lower() in ("yes", "true", "t", "y", "1"):
        return True
    if value.lower() in ("no", "false", "f", "n", "0"):
        return False
    raise argparse.ArgumentTypeError("Boolean value expected.")


def parse_int(value):
    return int(value, 0)


def clean_ascii(data):
    return data.decode("ascii", errors="replace").split("\x00")[0]


def compiled_payload_path(filename):
    script_dir = os.path.dirname(os.path.abspath(__file__))
    repo_dir = os.path.dirname(script_dir)
    return os.path.join(repo_dir, "build", filename)



# Mode bit, APPL setting prefix, RPC profile node, supported-by-patcher flag.
THERAPY_MODES = (
    (0, "Cpap", "CpapProfile", True),
    (1, "AutoSet", "AutoSetProfile", True),
    (2, "HerAuto", "AutoSetForHerProfile", True),
    (3, "Spont", "SpontProfile", True),
    (4, "ST", "STProfile", True),
    (5, "Timed", "TimedProfile", True),
    (6, "VAuto", "VAutoProfile", True),
    (7, "ASV", "ASVProfile", True),
    (8, "ASVAuto", "ASVAutoProfile", True),
    (9, "iVAPS", "iVAPSProfile", False),
    (10, "PAC", "PACProfile", False),
)

# Override built-in defaults for selected settings.
DEFAULT_SETTINGS = (
    # Entries may use long names, short names, or numeric var IDs. The
    # default writer handles g1 scalar, g2 numeric, and g5 enum records.
    ("RampEnablePatientAccess", 1),
    ("EprEnablePatientAccess", 1),
    ("Language", 0),
    ("TemperatureUnit", 0),
    ("MaskType", 0),
    ("TubeType", 0),
    ("PatientView", 1),
    ("ClinicalConfirmation", 0),
    ("EprType", 1),
)

# BLE command IDs enabled by default when patch-ble-permissions runs.
DEFAULT_BLE_UNLOCK_CMDS = (
    5,   # SetDateTime
    18,  # ApplyUpgrade
    # 25,   # GetLedStatus
    # 31,   # SetNextPowerUpDateTime
    # 63,   # ResetDevice
    # 64,   # StoreSecurityData
    # 70,   # VerifySecurityData
    # 86,   # ClearAutoConnectList
)

# GUI/config descriptors that must stay hidden even when activating tables.
BLACKLISTED_SETTING_PATTERNS = (
    "HeightDisplayUnit",
    "LearnTargets*",
    "*RampDown*",
    "PHI", # iVAPS-PatientHeight, inches
    "iVAPS-*",
    "PAC-*",
    "MaxRampTime",
)

# Non-mode APPL/RPC JSON profile nodes tied to hidden experimental features.
BLACKLISTED_FEATURE_PROFILE_NODE_NAMES = (
    "HeightFeature",
    "RampDownFeature",
)

# g5 selectors whose option masks gate the available therapy modes.
MODE_SELECTOR_NAMES = (
    "MOP",
    "GOM",
    "TOM",
)

AS11_VID_SPOOF_ADDR = 0x081DA000
AS11_VID_SPOOF_BINARY = "as11_vid_spoof.bin"
AS11_VID_SPOOF_MAGIC = 0x56313141

# Byte signatures from DataItem writeback routines:
# g5 enum stores obj+0x16 to backing[index * 4 + 2]
# g2 numeric stores obj+0x18 to backing[index * 8 + 4]
# Literal loads in these routines expose the runtime SRAM backing-table bases.
AS11_G5_ENUM_WRITEBACK_PATTERN = (
    0xDF, 0xF8, None, None, 0xB0, 0xF9, 0x14, 0x20,
    0x01, 0xEB, 0x82, 0x01, 0x80, 0x7D, 0x88, 0x70, 0x70, 0x47,
)
AS11_G2_NUMERIC_WRITEBACK_PATTERN = (
    0xDF, 0xF8, None, None, 0xB0, 0xF9, 0x14, 0x20,
    0x01, 0xEB, 0xC2, 0x01, 0x80, 0x69, 0x48, 0x60, 0x70, 0x47,
)


class S11Firmware(object):

    FLASH_BASE = 0x08000000

    FGBL_OFF = 0x00000
    FGBL_SIZE = 0x20000
    CONF_OFF = 0x20000
    CONF_SIZE = 0x20000
    APPL_OFF = 0x40000
    APPL_SIZE = 0x1C0000

    GLOBALS_REL = 0x104
    GLOBAL_COUNT = 20
    BID_OFFSET = FGBL_OFF + 0x4000

    G1_STRIDE = 10
    G2_STRIDE = 32
    G3_STRIDE = 20
    G5_STRIDE = 16

    GLOBAL_NAMES = {
        0: "conf_header",
        1: "scalar_descriptors",
        2: "numeric_descriptors",
        3: "bitfield_descriptors",
        4: "shared_backing_store",
        5: "enum_descriptors",
        6: "var_list_headers",
        7: "pdl_settings_unit_list",
        8: "short_name_buckets",
        9: "short_name_linear_pool",
        10: "mode_var_registration",
        11: "mode_var_registration_count",
        12: "event_definitions",
        13: "event_routes_ddo_storage",
        14: "collection_definitions",
        15: "str_summary_schema",
        16: "edf_stream_schemas",
        17: "event_label_tables",
        18: "rpc_json_permission_table",
        19: "reporting_ddo_pool",
    }

    def __init__(self, fileobj):
        self.fw = bytearray(fileobj.read())
        self.crcfunc = self.make_crcfunc()
        self._globals_cache = {}
        self.hash = hashlib.sha256(bytes(self.fw)).hexdigest()

        self.validate()
        self.setup_arrays()
        self.name_buckets = self.build_name_buckets()
        self.appl_nodes = self.build_appl_nodes()

    def validate(self):
        if len(self.fw) < self.APPL_OFF + self.APPL_SIZE:
            raise IOError("Input is too small for an S11 full firmware image")

        self.bid = self.read_str(self.BID_OFFSET, 16)
        self.platform = self.read_str(self.CONF_OFF + 0x18, 16)
        self.model = self.read_str(self.CONF_OFF + 0x28, 16)
        self.codename = self.read_str(self.CONF_OFF + 0x38, 16)
        self.appl_ver = self.find_app_version() or "unknown"

        if self.platform != "SIMPLICITY":
            raise IOError("Not an AS11 firmware (platform='%s')" % self.platform)

        print("Firmware Info:")
        print("  Bootloader       " + self.bid)
        print("  Application      " + self.appl_ver)
        print("  Platform         %s / %s / %s" % (self.platform, self.model, self.codename))

        for name, off, size in self.blocks():
            crc = self.crcfunc(bytes(self.fw[off:off + size]))
            if crc != 0:
                print("  WARN: %s CRC currently 0x%04X (will be refreshed on PATCH)" % (name, crc))

    def blocks(self):
        return (
            ("FGBL", self.FGBL_OFF, self.FGBL_SIZE),
            ("CONF", self.CONF_OFF, self.CONF_SIZE),
            ("APPL", self.APPL_OFF, self.APPL_SIZE),
        )

    def make_crcfunc(self):
        if crcmod is not None:
            return crcmod.predefined.mkCrcFun("crc-ccitt-false")
        return crc16_ccitt_false

    def find_app_version(self):
        last = None
        appl = bytes(self.fw[self.APPL_OFF:self.APPL_OFF + self.APPL_SIZE])
        for match in re.finditer(rb"(\d+\.\d+\.\d+\.[0-9a-f]{7,40})", appl):
            last = match.group(1).decode("ascii", errors="replace")
        if last:
            return last

        text = appl.decode("latin1", errors="ignore")
        last = None
        for match in re.finditer(r"SW\d+\.(\d+\.\d+\.\d+\.\d+(?:\.[0-9a-f]{7,40})?)", text):
            last = match.group(1)
        if last:
            return last
        for match in re.finditer(r"(?<!\d)(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})(?!\d)", text):
            last = match.group(1)
        return last

    def read_str(self, off, length):
        return clean_ascii(bytes(self.fw[off:off + length]))

    def u8(self, off):
        return self.fw[off]

    def u16(self, off):
        return struct.unpack_from("<H", self.fw, off)[0]

    def u32(self, off):
        return struct.unpack_from("<I", self.fw, off)[0]

    def write_u8(self, off, value):
        self.fw[off] = value & 0xFF

    def write_u16(self, off, value):
        struct.pack_into("<H", self.fw, off, value & 0xFFFF)

    def write_u32(self, off, value):
        struct.pack_into("<I", self.fw, off, value & 0xFFFFFFFF)

    def ptr_to_off(self, ptr):
        off = ptr - self.FLASH_BASE
        if 0 <= off < len(self.fw):
            return off
        return None

    def off_to_addr(self, off):
        return self.FLASH_BASE + off

    def string_at_ptr(self, ptr, max_len=120, allow_empty=False):
        off = self.ptr_to_off(ptr)
        if off is None:
            return None
        end_limit = min(len(self.fw), off + max_len + 1)
        end = self.fw.find(b"\x00", off, end_limit)
        if end < 0:
            return None
        if end == off and not allow_empty:
            return None
        raw = bytes(self.fw[off:end])
        if any(byte < 0x20 or byte > 0x7E for byte in raw):
            return None
        return raw.decode("ascii")

    def find_bytes(self, dataseq, start=0, unique=True):
        if isinstance(dataseq, str):
            dataseq = bytes.fromhex(dataseq)
        needle = tuple(dataseq)

        def find_from(pos):
            end = len(self.fw) - len(needle) + 1
            for off in range(pos, end):
                for idx, byte in enumerate(needle):
                    if byte is not None and self.fw[off + idx] != byte:
                        break
                else:
                    return off
            return -1

        i1 = find_from(start)
        if i1 < 0:
            raise ValueError("Passed sequence not found")
        if not unique:
            return i1
        i2 = find_from(i1 + 1)
        if i2 >= 0:
            raise ValueError("Passed sequence is not unique! Found at 0x%x and 0x%x" % (i1, i2))
        return i1

    def find_u32_offsets(self, value, skip_range=None):
        needle = struct.pack("<I", value)
        out = []
        start = 0
        while True:
            off = bytes(self.fw).find(needle, start)
            if off < 0:
                break
            if skip_range is None or not (skip_range[0] <= off < skip_range[1]):
                out.append(off)
            start = off + 1
        return out

    def read_thumb2_ldr_w_pc_literal_u32(self, off):
        # Decode the literal value loaded by "ldr.w Rt, [pc, #imm12]".
        addr = self.off_to_addr(off)
        imm = self.u16(off + 2) & 0x0FFF
        literal_addr = ((addr + 4) & ~3) + imm
        literal_off = self.ptr_to_off(literal_addr)
        if literal_off is None:
            raise ValueError("literal 0x%08X is outside image" % literal_addr)
        return self.u32(literal_off)

    def patch(self, patchdata, addr=None, dataseq=None, verbose=True):
        patchdata = bytes(patchdata)
        if addr is None:
            if dataseq is None:
                raise ValueError("Need addr or dataseq")
            addr = self.find_bytes(dataseq)
        if verbose:
            print("Patching %d bytes at 0x%x" % (len(patchdata), addr))
        self.fw[addr:addr + len(patchdata)] = patchdata

    def globals_addr(self):
        # Master table: trampoline at CONF+0x100, pointer at CONF+0x104.
        ptr = self.u32(self.CONF_OFF + self.GLOBALS_REL)
        off = self.ptr_to_off(ptr)
        if off is None:
            raise ValueError("globals pointer 0x%08X is outside image" % ptr)
        return off

    def read_globals(self):
        out = []
        base = self.globals_addr()
        for idx in range(self.GLOBAL_COUNT):
            value = self.u32(base + idx * 4)
            off = self.ptr_to_off(value)
            out.append({
                "index": idx,
                "name": self.GLOBAL_NAMES.get(idx, "g%d" % idx),
                "value": value,
                "offset": off,
            })
        pointer_offsets = sorted(
            row["offset"] for row in out
            if row["offset"] is not None and self.CONF_OFF <= row["offset"] < self.CONF_OFF + self.CONF_SIZE
        )
        for row in out:
            off = row["offset"]
            row["size"] = None
            if off is None or not (self.CONF_OFF <= off < self.CONF_OFF + self.CONF_SIZE):
                continue
            end = self.CONF_OFF + self.CONF_SIZE
            for candidate in pointer_offsets:
                if candidate > off:
                    end = candidate
                    break
            row["size"] = end - off
        return out

    def globals_offset(self, idx):
        if idx not in self._globals_cache:
            if not hasattr(self, "globals"):
                self.globals = self.read_globals()
            off = self.globals[idx]["offset"]
            if off is None:
                value = self.globals[idx]["value"]
                raise ValueError("globals[%d] value 0x%08X is not a flash pointer" % (idx, value))
            self._globals_cache[idx] = off
        return self._globals_cache[idx]

    def count_records(self, base, stride):
        count = 0
        while base + count * stride + stride <= len(self.fw):
            vt = self.u16(base + count * stride)
            if vt < 0x0200 or vt > 0x0FFF:
                break
            count += 1
        return count

    def setup_arrays(self):
        self.globals = self.read_globals()
        for row in self.globals:
            if row["offset"] is not None:
                setattr(self, "g%d_base" % row["index"], row["offset"])
                setattr(self, "g%d_size" % row["index"], row["size"])
            else:
                setattr(self, "g%d_value" % row["index"], row["value"])

        self.g1_base = self.globals_offset(1)
        self.g2_base = self.globals_offset(2)
        self.g3_base = self.globals_offset(3)
        self.g5_base = self.globals_offset(5)
        self.g8_base = self.globals_offset(8)
        self.perm_table = self.globals_offset(18)

        self.g1_count = self.count_records(self.g1_base, self.G1_STRIDE)
        self.g2_count = self.count_records(self.g2_base, self.G2_STRIDE)
        self.g3_count = self.count_records(self.g3_base, self.G3_STRIDE)
        self.g5_count = self.count_records(self.g5_base, self.G5_STRIDE)

        # Descriptor var IDs are table-order based
        self.g1_id_base = 0
        self.g2_id_base = self.g1_count
        self.g3_id_base = self.g2_id_base + self.g2_count
        self.g5_id_base = self.g3_id_base + self.g3_count

        self.arrays = {
            "g1": dict(base=self.g1_base, stride=self.G1_STRIDE, count=self.g1_count, id_base=self.g1_id_base),
            "g2": dict(base=self.g2_base, stride=self.G2_STRIDE, count=self.g2_count, id_base=self.g2_id_base),
            "g3": dict(base=self.g3_base, stride=self.G3_STRIDE, count=self.g3_count, id_base=self.g3_id_base),
            "g5": dict(base=self.g5_base, stride=self.G5_STRIDE, count=self.g5_count, id_base=self.g5_id_base),
        }

        print("Arrays:    g1=%d g2=%d g3=%d g5=%d" % (
            self.g1_count, self.g2_count, self.g3_count, self.g5_count
        ))
        print("Globals:   %d known entries, g11=%d" % (len(self.globals), self.g11_value))

    def build_name_buckets(self):
        # globals[8] is an A-Z bucket table mapping short 3-byte setting tags
        # such as MOP or TLF back to var IDs.
        out = {}
        for bucket in range(26):
            off = self.g8_base + bucket * 8
            ptr = self.u32(off)
            count = self.u32(off + 4)
            table_off = self.ptr_to_off(ptr)
            if table_off is None or count > 300:
                continue
            prefix = chr(ord("A") + bucket)
            for idx in range(count):
                eoff = table_off + idx * 4
                if eoff + 4 > len(self.fw):
                    break
                c1 = self.u8(eoff)
                c2 = self.u8(eoff + 1)
                vid = self.u16(eoff + 2)
                if 0x20 < c1 < 0x7F and 0x20 < c2 < 0x7F and vid < 0x1000:
                    out[vid] = prefix + chr(c1) + chr(c2)
        return out

    def valid_appl_name_entry(self, off):
        if off + 8 > len(self.fw):
            return False
        ptr = self.u32(off)
        vid = self.u16(off + 4)
        pad = self.u16(off + 6)
        if pad != 0 or not (vid < 0x1000 or vid == 0x7FFF):
            return False
        return self.string_at_ptr(ptr, allow_empty=True) is not None

    def build_appl_nodes(self):
        # APPL has a large [name pointer, var_id] metadata table. This gives
        # long setting names such as ActiveTherapyProfile and TherapyLEDAlwaysOn.
        appl_end = self.APPL_OFF + self.APPL_SIZE
        best_named = 0
        best_count = 0
        best_start = None
        for start in range(self.APPL_OFF, appl_end - 8, 4):
            if not self.valid_appl_name_entry(start):
                continue
            if start > self.APPL_OFF and self.valid_appl_name_entry(start - 8):
                continue
            count = 0
            named = 0
            off = start
            while off + 8 <= appl_end and self.valid_appl_name_entry(off):
                name = self.string_at_ptr(self.u32(off), allow_empty=True)
                if name:
                    named += 1
                count += 1
                off += 8
            if count >= 100 and named >= 50 and (named, count) > (best_named, best_count):
                best_named = named
                best_count = count
                best_start = start
        if best_start is None:
            return {}

        out = {}
        for idx in range(best_count):
            off = best_start + idx * 8
            vid = self.u16(off + 4)
            if vid >= 0x1000:
                continue
            name = self.string_at_ptr(self.u32(off), allow_empty=True)
            if name:
                out[vid] = name
        return out

    def var_short_name(self, vid):
        return self.name_buckets.get(vid, "")

    def var_long_name(self, vid):
        return self.appl_nodes.get(vid, "")

    def var_name(self, vid):
        return self.var_long_name(vid) or self.var_short_name(vid)

    def descriptor(self, array, idx):
        spec = self.arrays[array]
        if idx < 0 or idx >= spec["count"]:
            raise IndexError("%s[%d] outside table" % (array, idx))
        off = spec["base"] + idx * spec["stride"]
        vid = spec["id_base"] + idx
        row = {
            "array": array,
            "index": idx,
            "offset": off,
            "address": self.off_to_addr(off),
            "var_id": vid,
            "short_name": self.var_short_name(vid),
            "long_name": self.var_long_name(vid),
            "name": self.var_name(vid),
            "vid_type": self.u16(off),
            "active": bool(self.u16(off) & 1),
        }
        if array == "g5":
            row.update({
                "sub": self.u8(off + 8),
                "n_options": self.u8(off + 9),
                "option_mask": self.u32(off + 12),
            })
        elif array == "g3":
            row.update({
                "fixed_mask": self.u32(off + 8),
                "editable_mask": self.u32(off + 12),
                "bit_count": self.u8(off + 16),
                "g4_list_offset": self.u16(off + 18),
            })
        return row

    def iter_descriptors(self, array):
        for idx in range(self.arrays[array]["count"]):
            yield self.descriptor(array, idx)

    def normalize_short_name(self, name):
        return name.upper().lstrip("_")

    def descriptor_matches_name(self, row, name):
        wanted_short = self.normalize_short_name(name)
        if row["short_name"] and self.normalize_short_name(row["short_name"]) == wanted_short:
            return True
        return bool(row["long_name"] and row["long_name"] == name)

    def find_descriptors_by_name(self, name, arrays=("g1", "g2", "g3", "g5")):
        rows = []
        for array in arrays:
            for row in self.iter_descriptors(array):
                if self.descriptor_matches_name(row, name):
                    rows.append(row)
        return rows

    def find_rpc_nodes(self, names):
        names = set(names)
        found = {}
        for off in range(0, len(self.fw) - 12, 4):
            name = self.string_at_ptr(self.u32(off))
            if name not in names:
                continue
            node = self.string_at_ptr(self.u32(off + 4))
            if not node:
                continue
            match = re.match(r"^!(\d+)$", node)
            if not match:
                continue
            if self.u32(off + 8) != 0x00007FFF:
                continue
            found[name] = int(match.group(1))
        return found

    def find_rpc_feature_nodes(self):
        found = {}
        for off in range(0, len(self.fw) - 12, 4):
            name = self.string_at_ptr(self.u32(off))
            if not name or not name.endswith("Feature"):
                continue
            node = self.string_at_ptr(self.u32(off + 4))
            if not node:
                continue
            match = re.match(r"^!(\d+)$", node)
            if not match:
                continue
            if self.u32(off + 8) != 0x00007FFF:
                continue
            found[name] = int(match.group(1))
        return found

    def rpc_json_row(self, off):
        if off < 0 or off + 12 > len(self.fw):
            return None
        name = self.string_at_ptr(self.u32(off))
        value = self.string_at_ptr(self.u32(off + 4))
        if not name or not value or self.u32(off + 8) != 0x00007FFF:
            return None
        return (name, value)

    def find_rpc_feature_setting_names(self):
        feature_offsets = []
        for off in range(0, len(self.fw) - 12, 4):
            row = self.rpc_json_row(off)
            if row is None:
                continue
            name, value = row
            if name.endswith("Feature") and re.match(r"^!\d+$", value):
                feature_offsets.append(off)
        if not feature_offsets:
            return []

        # In the APPL JSON model, feature profile nodes are followed by their
        # backing settings. The next therapy profile node ends the feature area.
        names = []
        seen = set()
        off = max(feature_offsets) + 12
        while True:
            row = self.rpc_json_row(off)
            if row is None:
                break
            name, value = row
            if re.match(r"^!\d+$", value):
                if name.endswith("Profile"):
                    break
            elif value not in seen:
                seen.add(value)
                names.append(value)
            off += 12
        return names

    def fix_crcs(self):
        print("Updating checksums")
        for name, off, size in self.blocks():
            crc_off = off + size - 2
            new_crc = self.crcfunc(bytes(self.fw[off:crc_off]))
            self.fw[crc_off] = (new_crc >> 8) & 0xFF
            self.fw[crc_off + 1] = new_crc & 0xFF
            print("  block @0x%05X (%d bytes) -> CRC %04X" % (off, size, new_crc))

    def write_output(self, filename, overwrite=False):
        if os.path.exists(filename) and not overwrite:
            raise IOError("File " + filename + " exists already.")
        with open(filename, "wb") as f:
            f.write(bytes(self.fw))


class S11FirmwarePatches(object):
    """Patch methods for S11 firmware."""

    def __init__(self, asf, ble_unlock_cmds=None):
        self.asf = asf
        self.ble_unlock_cmds = list(ble_unlock_cmds or DEFAULT_BLE_UNLOCK_CMDS)

    def is_blacklisted_setting(self, row):
        long_name = row["long_name"] or ""
        short_name = row["short_name"] or ""
        for pattern in BLACKLISTED_SETTING_PATTERNS:
            if fnmatch.fnmatchcase(long_name, pattern) or fnmatch.fnmatchcase(short_name, pattern):
                return True
        return False

    def hide_blacklisted_settings(self):
        n_act = 0
        n_masks = 0
        for array in ("g1", "g2", "g3", "g5"):
            for row in self.asf.iter_descriptors(array):
                if not self.is_blacklisted_setting(row):
                    continue
                off = row["offset"]
                if self.asf.u16(off) & 1:
                    self.asf.write_u8(off, self.asf.u8(off) & ~1)
                    n_act += 1
                if array == "g5" and self.asf.u32(off + 12):
                    self.asf.write_u32(off + 12, 0)
                    n_masks += 1
        return (n_act, n_masks)

    def activate_table(self, array):
        n = 0
        for row in self.asf.iter_descriptors(array):
            if self.is_blacklisted_setting(row):
                continue
            off = row["offset"]
            vt = row["vid_type"]
            if vt >= 0x0200 and not (vt & 1):
                self.asf.write_u8(off, self.asf.u8(off) | 1)
                n += 1
        return n

    def named_g5_rows(self, names):
        seen = set()
        out = []
        for name in names:
            for row in self.asf.find_descriptors_by_name(name, ("g5",)):
                if row["offset"] in seen:
                    continue
                seen.add(row["offset"])
                out.append(row)
        return out

    def is_editable_g5_target(self, row, feature_setting_offsets):
        if self.is_blacklisted_setting(row):
            return None
        long_name = row["long_name"]
        if row["offset"] in feature_setting_offsets:
            return "feature"
        for _bit, prefix, _profile, supported in THERAPY_MODES:
            if supported and long_name.startswith(prefix + "-"):
                return "therapy"
        return None

    def default_target_label(self, target):
        if isinstance(target, int):
            return "0x%04X" % target
        return str(target)

    def find_default_rows(self, target):
        if isinstance(target, int):
            rows = []
            for array in ("g1", "g2", "g5"):
                spec = self.asf.arrays[array]
                idx = target - spec["id_base"]
                if 0 <= idx < spec["count"]:
                    rows.append(self.asf.descriptor(array, idx))
            return rows
        return self.asf.find_descriptors_by_name(target, ("g1", "g2", "g5"))

    def write_default_value(self, row, value):
        off = row["offset"]
        array = row["array"]
        if array == "g1":
            if not 0 <= value <= 0xFFFF:
                raise ValueError("g1 default outside u16 range")
            old = self.asf.u16(off + 8)
            if old != value:
                self.asf.write_u16(off + 8, value)
                return True
            return False
        if array == "g2":
            old = self.asf.u32(off + 8)
            value &= 0xFFFFFFFF
            if old != value:
                self.asf.write_u32(off + 8, value)
                return True
            return False
        if array == "g5":
            n_options = self.asf.u8(off + 9)
            if not 0 <= value < n_options:
                raise ValueError("g5 default outside option range 0..%d" % (n_options - 1))
            old = self.asf.u8(off + 8)
            if old != value:
                self.asf.write_u8(off + 8, value)
                return True
            return False
        raise ValueError("unsupported default array %s" % array)

    def patch_defaults(self):
        """Patch descriptor defaults for firmware, clinical, or patient settings."""
        n_changed = 0
        n_unchanged = 0
        n_missing = 0
        n_invalid = 0
        for target, desired in DEFAULT_SETTINGS:
            rows = self.find_default_rows(target)
            label = self.default_target_label(target)
            if not rows:
                print("  default %s not found" % label)
                n_missing += 1
                continue
            for row in rows:
                try:
                    changed = self.write_default_value(row, desired)
                except ValueError as exc:
                    print("  default %s skipped: %s" % (label, exc))
                    n_invalid += 1
                    continue
                if changed:
                    n_changed += 1
                else:
                    n_unchanged += 1

        n_skipped = n_missing + n_invalid
        print("Patching firmware defaults... %d changed, %d already set, %d skipped" % (
            n_changed, n_unchanged, n_skipped
        ))
        if n_skipped:
            print("  skipped detail: %d not found, %d invalid" % (n_missing, n_invalid))
        return n_changed

    def unlock_languages(self):
        """Unlock language availability and prevent persisted narrowing."""
        n_changed = 0
        n_unchanged = 0
        n_missing = 0
        default_mask = 0x07FFFFFF
        # editable_mask=0 forces all configured language bits on at boot
        # but prevents overriding mask with as11_config set LanguageConfiguration
        # editable_mask=0x07FFFFFF allows changing LanguageConfiguration but also
        # requires manually changgin LanguageConfiguration for the new languages to appear
        editable_mask = 0x00000000
        lnc_rows = self.asf.find_descriptors_by_name("LanguageConfiguration", ("g3",))
        if not lnc_rows:
            print("  language LanguageConfiguration not found")
            n_missing += 1
        for row in lnc_rows:
            off = row["offset"]
            if (self.asf.u32(off + 8) != default_mask
                    or self.asf.u32(off + 12) != editable_mask):
                self.asf.write_u32(off + 8, default_mask)
                self.asf.write_u32(off + 12, editable_mask)
                n_changed += 1
            else:
                n_unchanged += 1

        print("Patching language configuration... %d changed, %d already set, %d missing" % (
            n_changed, n_unchanged, n_missing
        ))
        return n_changed

    def unlock_features(self):
        """Unlock therapy modes and related GUI settings at descriptor level."""
        feature_setting_offsets = set()
        for name in self.asf.find_rpc_feature_setting_names():
            for row in self.asf.find_descriptors_by_name(name, ("g5",)):
                if not self.is_blacklisted_setting(row):
                    feature_setting_offsets.add(row["offset"])

        editable_rows = []
        for row in self.asf.iter_descriptors("g5"):
            kind = self.is_editable_g5_target(row, feature_setting_offsets)
            if kind:
                row = dict(row)
                row["edit_kind"] = kind
                editable_rows.append(row)

        # ACT flags are the basic "can this menu/data item appear?" gate.
        n_hidden_act, n_hidden_masks = self.hide_blacklisted_settings()
        n_g1 = self.activate_table("g1")
        n_g2 = self.activate_table("g2")
        n_g3 = self.activate_table("g3")
        n_g5 = self.activate_table("g5")

        # globals[5] also holds therapy mode selectors and enum option masks.
        # Patch only selectors resolved by name, because var IDs shift between
        # builds and n_options alone is not identity.
        n_modes = 0
        supported_mask = sum(1 << bit for bit, _prefix, _profile, supported in THERAPY_MODES if supported)
        for row in self.named_g5_rows(MODE_SELECTOR_NAMES):
            n_options = row["n_options"]
            mask = self.asf.u32(row["offset"] + 12)
            if n_options != 11:
                print("  mode selector %s skipped: n_options=%d" % (row["short_name"] or row["long_name"], n_options))
                continue
            if mask == 0 or mask == supported_mask:
                continue
            if mask & ~0x07FF:
                print("  mode selector %s skipped: unusual mask 0x%08X" % (row["short_name"] or row["long_name"], mask))
                continue
            self.asf.write_u32(row["offset"] + 12, supported_mask)
            n_modes += 1

        n_editable = 0
        n_already = 0
        n_skipped = 0
        for row in editable_rows:
            # Named feature/therapy enum settings need non-zero option masks
            # before the GUI can edit them. Existing non-zero masks are
            # preserved because variant firmwares may already narrow them.
            n_options = row["n_options"]
            mask = self.asf.u32(row["offset"] + 12)
            if n_options == 0 or n_options > 31:
                n_skipped += 1
                continue
            if mask != 0:
                n_already += 1
                continue
            self.asf.write_u32(row["offset"] + 12, (1 << n_options) - 1)
            n_editable += 1

        print("Patching GUI ACT flags... g1=%d g2=%d g3=%d g5=%d" % (n_g1, n_g2, n_g3, n_g5))
        if n_hidden_act or n_hidden_masks:
            print("Hiding blacklisted iVAPS/PAC/RampDown settings... %d ACT flags, %d masks" % (
                n_hidden_act, n_hidden_masks
            ))
        print("Patching GUI mode gates... %d selectors" % n_modes)
        print("Patching GUI enum editability... %d/%d masks enabled (%d already enabled, %d skipped)" % (
            n_editable, len(editable_rows), n_already, n_skipped
        ))

    def rpc_json_profile_visibility(self):
        # globals[18] contains u16 permissions for APPL/RPC JSON tree nodes.
        # These gates expose profile nodes in Get responses; backing setting
        # descriptors still need their own ACT bits and option masks.
        mode_profile_nodes = tuple(
            profile for _bit, _prefix, profile, supported in THERAPY_MODES if supported
        )
        feature_nodes = self.asf.find_rpc_feature_nodes()
        blacklisted_nodes = tuple(
            profile for _bit, _prefix, profile, supported in THERAPY_MODES if not supported
        ) + BLACKLISTED_FEATURE_PROFILE_NODE_NAMES
        blacklisted_nodes = set(blacklisted_nodes)

        nodes = self.asf.find_rpc_nodes(mode_profile_nodes)
        for name, node_id in feature_nodes.items():
            if name not in blacklisted_nodes:
                nodes[name] = node_id
        if not nodes:
            raise ValueError("metadata: no RPC JSON profile nodes resolved")

        n = 0
        for name, node_id in sorted(nodes.items(), key=lambda item: (item[1], item[0])):
            off = self.asf.perm_table + node_id * 2
            if self.asf.u16(off) == 0:
                self.asf.write_u16(off, 1)
                n += 1

        n_hidden = 0
        hidden_nodes = self.asf.find_rpc_nodes(blacklisted_nodes)
        for name, node_id in sorted(hidden_nodes.items(), key=lambda item: (item[1], item[0])):
            off = self.asf.perm_table + node_id * 2
            if self.asf.u16(off) != 0:
                self.asf.write_u16(off, 0)
                n_hidden += 1

        print("Patching RPC JSON profile visibility... %d/%d nodes enabled" % (n, len(nodes)))
        if n_hidden:
            print("Hiding blacklisted RPC JSON profile nodes... %d nodes disabled" % n_hidden)

    def motor_nagscreen(self):
        try:
            offset = self.asf.find_bytes(bytes.fromhex("C000B304"))
            print("Patching \"Motor life exceeded\" threshold...")
            self.asf.patch(b"\xFF\xFF\xFF\x7F", addr=offset, verbose=False)
            print("ok")
        except ValueError:
            print("motor_nagscreen: threshold not found!")

    def ble_record_flags_are_bits(self, off):
        if off + 9 > len(self.asf.fw):
            return False
        for idx in range(1, 9):
            flag = self.asf.u8(off + idx)
            if flag not in (0, 1):
                return False
        return True

    def ble_permissions(self):
        if not self.ble_unlock_cmds:
            return

        # Level 3 command permission table: 9-byte entries
        # [cmd_id] [flag0..flag7], flag index 1 = BLE encrypted.
        #
        # BLE RPC command IDs are distinct from APPL/RPC JSON node IDs. The
        # unlock list contains command IDs, not permission-table entry indices.
        #
        # Anchor: cmd_id 4 (GetDateTime) with all 8 flags = 1, APPL region only.
        # Walk the table bounds because command 3 is absent and table length
        # shifts between firmware builds.
        anchor_off = self.asf.find_bytes(bytes.fromhex("040101010101010101"), self.asf.APPL_OFF)
        base = anchor_off
        cmd = self.asf.u8(base)
        while base - 9 >= self.asf.APPL_OFF:
            prev_off = base - 9
            if not self.ble_record_flags_are_bits(prev_off):
                break
            prev_cmd = self.asf.u8(prev_off)
            if prev_cmd >= cmd:
                break
            base = prev_off
            cmd = prev_cmd

        unlock = set(self.ble_unlock_cmds)
        prev_cmd = -1
        off = base
        n = 0
        scanned = 0
        while self.ble_record_flags_are_bits(off):
            cmd = self.asf.u8(off)
            if cmd <= prev_cmd:
                break
            if cmd in unlock and self.asf.u8(off + 2) == 0:
                self.asf.write_u8(off + 2, 1)
                n += 1
            prev_cmd = cmd
            off += 9
            scanned += 1
        print("Patching BLE permissions... %d commands unlocked (%d entries scanned)" % (n, scanned))

    def vid_spoof(self):
        """Install the runtime MOP-to-VID hook."""
        path = compiled_payload_path(AS11_VID_SPOOF_BINARY)
        if not os.path.exists(path):
            print("Patching runtime VID spoof... skipped (%s not found; run 'make as11-vid-spoof')" % path)
            return

        vid_rows = self.asf.find_descriptors_by_name("VariantIdentifier", ("g2",))
        mop_rows = self.asf.find_descriptors_by_name("ActiveTherapyProfile", ("g5",))
        if len(vid_rows) != 1:
            raise ValueError("vid_spoof: expected one VariantIdentifier descriptor, found %d" % len(vid_rows))
        if len(mop_rows) != 1:
            raise ValueError("vid_spoof: expected one ActiveTherapyProfile descriptor, found %d" % len(mop_rows))
        vid_row = vid_rows[0]
        mop_row = mop_rows[0]

        # Resolve the commit path and runtime SRAM slots from the firmware
        # g5 gives the MOP trigger, g2 gives the VID target.
        code_off = self.asf.ptr_to_off(AS11_VID_SPOOF_ADDR)
        if code_off is None:
            raise ValueError("vid_spoof: code cave address outside firmware image")

        try:
            enum_off = self.asf.find_bytes(AS11_G5_ENUM_WRITEBACK_PATTERN, self.asf.APPL_OFF)
        except ValueError as exc:
            raise ValueError("vid_spoof: g5 enum writeback pattern not unique: %s" % exc)
        enum_base = self.asf.read_thumb2_ldr_w_pc_literal_u32(enum_off)
        orig = self.asf.off_to_addr(enum_off) | 1

        numeric = []
        start = self.asf.APPL_OFF
        while True:
            try:
                off = self.asf.find_bytes(AS11_G2_NUMERIC_WRITEBACK_PATTERN, start, unique=False)
            except ValueError as exc:
                if "not found" not in str(exc):
                    raise ValueError("vid_spoof: numeric writeback pattern scan failed from 0x%X: %s" % (start, exc))
                break
            base = self.asf.read_thumb2_ldr_w_pc_literal_u32(off)
            if base < enum_base:
                numeric.append((off, base))
            start = off + 1
        if len(numeric) != 1:
            raise ValueError("vid_spoof: expected one g2 numeric writeback before g5 storage, found %d" % len(numeric))
        _numeric_off, numeric_base = numeric[0]

        skip = (code_off, code_off + 0x400)
        hook_ptr = AS11_VID_SPOOF_ADDR | 1
        refs = self.asf.find_u32_offsets(orig, skip)
        if len(refs) == 1:
            vtable_entry = self.asf.off_to_addr(refs[0])
        else:
            hook_refs = self.asf.find_u32_offsets(hook_ptr, skip)
            if len(hook_refs) != 1:
                raise ValueError(
                    "vid_spoof: expected one vtable reference to 0x%08X or hook, found %d/%d" %
                    (orig, len(refs), len(hook_refs))
                )
            vtable_entry = self.asf.off_to_addr(hook_refs[0])

        with open(path, "rb") as f:
            blob = f.read()
        if not blob:
            raise ValueError("vid_spoof: %s is empty" % path)

        # The compiled hook has a tiny placeholder parameter block.
        # Fill it with resolved values
        magic = struct.pack("<I", AS11_VID_SPOOF_MAGIC)
        param_off = blob.find(magic)
        if param_off < 0 or blob.find(magic, param_off + 1) >= 0:
            raise ValueError("vid_spoof: parameter block magic not unique")
        if param_off + 20 > len(blob):
            raise ValueError("vid_spoof: parameter block is truncated")
        blob = bytearray(blob)
        struct.pack_into(
            "<IIIII",
            blob,
            param_off,
            AS11_VID_SPOOF_MAGIC,
            orig,
            numeric_base + vid_row["index"] * 8 + 4,
            enum_base + mop_row["index"] * 4 + 2,
            mop_row["index"],
        )
        blob = bytes(blob)

        vt_off = self.asf.ptr_to_off(vtable_entry)
        if vt_off is None:
            raise ValueError("vid_spoof: patch address outside firmware image")
        if code_off + len(blob) > self.asf.APPL_OFF + self.asf.APPL_SIZE:
            raise ValueError("vid_spoof: hook binary does not fit APPL block")

        current_ptr = self.asf.u32(vt_off)
        if current_ptr not in (orig, hook_ptr):
            raise ValueError(
                "vid_spoof: vtable entry 0x%08X is 0x%08X, expected 0x%08X" %
                (vtable_entry, current_ptr, orig)
            )

        existing = bytes(self.asf.fw[code_off:code_off + len(blob)])
        if existing != blob and current_ptr != hook_ptr and any(byte != 0xFF for byte in existing):
            raise ValueError("vid_spoof: code cave at 0x%08X is not empty" % AS11_VID_SPOOF_ADDR)

        changed = 0
        if existing != blob:
            self.asf.patch(blob, addr=code_off, verbose=False)
            changed += 1
        if current_ptr != hook_ptr:
            self.asf.write_u32(vt_off, hook_ptr)
            changed += 1

        print("Patching runtime VID spoof... %s, %d bytes, %s" % (
            self.asf.appl_ver, len(blob), "changed" if changed else "already installed"
        ))

    def patch_edf_superset(self):
        """Expose the official S11 EDF schema superset."""
        try:
            from as11_edf_superset import patch_edf_superset
        except ImportError:
            script_dir = os.path.dirname(os.path.abspath(__file__))
            sys.path.insert(0, script_dir)
            from as11_edf_superset import patch_edf_superset

        patch_edf_superset(self.asf)


PATCH_LIST = [
    {
        "arg": "patch-unlock-features",
        "desc": "Unlock supported therapy modes, related settings, and GUI editability.",
        "default": True,
        "function": "unlock_features",
    },
    {
        "arg": "patch-unlock-languages",
        "desc": "Unlock all configured language choices.",
        "default": True,
        "function": "unlock_languages",
    },
    {
        "arg": "patch-defaults",
        "desc": "Patch firmware defaults for selected settings.",
        "default": True,
        "function": "patch_defaults",
    },
    {
        "arg": "patch-rpc-json-profile-visibility",
        "desc": "Expose supported therapy/feature profile nodes in RPC JSON.",
        "default": True,
        "function": "rpc_json_profile_visibility",
    },
    {
        "arg": "patch-edf-superset",
        "desc": "Expose the official S11 EDF PLD and STR superset.",
        "default": True,
        "function": "patch_edf_superset",
    },
    {
        "arg": "patch-motor-nagscreen",
        "desc": "Remove \"Motor life exceeded\" nag screen.",
        "default": True,
        "function": "motor_nagscreen",
    },
    {
        "arg": "patch-ble-permissions",
        "desc": "Enable selected BLE Level 3 RPC commands on encrypted VCID.",
        "default": True,
        "function": "ble_permissions",
    },
    {
        "arg": "patch-vid-spoof",
        "desc": "Install runtime MOP-based VariantIdentifier spoofing.",
        "default": True,
        "function": "vid_spoof",
    },
]


def add_patch_switch(parser, patch):
    parser.add_argument(
        "--" + patch["arg"],
        metavar="Y/n",
        default=None,
        type=str2bool,
        help=patch["desc"],
    )


def build_arg_parser():
    parser = argparse.ArgumentParser(description="Patch AirSense/AirCurve 11 firmware.")
    parser.add_argument("INFILE", help="Input original binary file")
    parser.add_argument("OUTFILE", help="Output patched file")
    parser.add_argument("OPERATION", choices=["INFO", "PATCH"], help="Operation to perform")

    for patch in PATCH_LIST:
        add_patch_switch(parser, patch)

    parser.add_argument(
        "--all-patches",
        metavar="Y/n",
        default=None,
        type=str2bool,
        help="Default state for patch switches not explicitly set. Default: built-in patch defaults.",
    )
    parser.add_argument("--overwrite", action="store_true", help="Overwrite output file if it exists already.")
    parser.add_argument(
        "--ble-unlock-cmd",
        action="append",
        type=parse_int,
        default=None,
        help="BLE command id to unlock; repeatable. Default: 5, 18.",
    )
    return parser


def main(argv=None):
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    with open(args.INFILE, "rb") as f:
        asf = S11Firmware(f)

    if args.OPERATION == "INFO":
        return 0

    patches = S11FirmwarePatches(
        asf,
        ble_unlock_cmds=args.ble_unlock_cmd,
    )

    for patch in PATCH_LIST:
        enabled = getattr(args, patch["arg"].replace("-", "_"))
        if enabled is None:
            if args.all_patches is None:
                enabled = patch["default"]
            else:
                enabled = args.all_patches
        if enabled:
            print("PATCH: " + patch["desc"])
            getattr(patches, patch["function"])()

    asf.fix_crcs()
    asf.write_output(args.OUTFILE, args.overwrite)
    print(hashlib.sha256(bytes(asf.fw)).hexdigest() + "  " + args.OUTFILE)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except BrokenPipeError:
        raise SystemExit(1)
    except Exception as exc:
        print("error: %s" % exc, file=sys.stderr)
        raise SystemExit(2)

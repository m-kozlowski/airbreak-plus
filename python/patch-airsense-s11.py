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
import io
import os.path
import re
import struct
import sys
from contextlib import redirect_stdout
from dataclasses import dataclass

from lib.as11_conf_discovery import (
    discover_conf_global_count,
    discover_dataitem_layout,
    discover_rpc_json_permission_count,
)
from lib.as11_patch_versions import AS11_FGBL_PATCH_VERSIONS, AS11_PATCH_VERSIONS
from lib.compiled_payload import CompiledPayloadMixin

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


def parse_u16(value):
    try:
        out = int(value, 0)
    except ValueError:
        raise argparse.ArgumentTypeError("expected integer or hex value") from None
    if out < 0 or out > 0xFFFF:
        raise argparse.ArgumentTypeError("expected 16-bit value")
    return out


def parse_rpc_permission(value):
    parts = [part.strip() for part in value.split(":")]
    if len(parts) != 3 or not parts[0]:
        raise argparse.ArgumentTypeError("expected METHOD:VCID:BOOL")
    method, vcid_text, enabled_text = parts
    try:
        vcid = parse_u16(vcid_text)
        enabled = str2bool(enabled_text)
    except argparse.ArgumentTypeError as exc:
        raise argparse.ArgumentTypeError(
            "invalid RPC permission %r: %s" % (value, exc)
        ) from None
    return method, vcid, enabled


def clean_ascii(data):
    return data.decode("ascii", errors="replace").split("\x00")[0]


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
    # iVAPS requires HeightDisplayUnit, PHI, HeightFeature and PHT descriptor fix
    (9, "iVAPS", "iVAPSProfile", True),
    (10, "PAC", "PACProfile", True),
)

# Override built-in defaults for selected settings.
DEFAULT_SETTINGS = (
    # Entries may use long names, short names, or numeric var IDs. The
    # default writer handles g2 numeric and g5 enum records.
    ("RampEnablePatientAccess", 1),
    ("EprEnablePatientAccess", 1),
    ("Language", 0),
    ("TemperatureUnit", 0),
    ("MaskType", 0),
    ("TubeType", 0),
    ("PatientView", 1),
    ("ClinicalConfirmation", 0),
    ("EprType", 1),
    ("TSS", 0),  # Treatment screen style: Dots, PressureBar, FlowBar
)

# Standalone enum masks that are useful but not tied to therapy profiles.
UNLOCKED_ENUM_SETTING_NAMES = (
    "TSS",  # Treatment screen style: Dots, PressureBar, FlowWave
    "HeightDisplayUnit",
)

# RPC permissions set by patch-rpc-permissions. The outer key is the method,
# and each nested map assigns the permission state for one or more VCIDs.
DEFAULT_RPC_PERMISSIONS = {
    "SetDateTime": {
        0x0396: True,
    },
    "ApplyUpgrade": {
        0x0396: True,
        # 0x0780: False,
        # 0x0788: False,
    },
    # "GetLedStatus": {0x0396: True},
    # "SetNextPowerUpDateTime": {0x0396: True},
    # "ResetDevice": {0x0396: True},
    # "StoreSecurityData": {0x0396: True},
    # "VerifySecurityData": {0x0396: True},
    # "ClearAutoConnectList": {0x0396: True},
    # Cellular upgrade blocking is opt-in.
    # "InitiateUpgrade": {0x0780: False, 0x0788: False},
    # "UpgradeDataBlock": {0x0780: False, 0x0788: False},
    # "CheckUpgradeFile": {0x0780: False, 0x0788: False},
    # "ApplyAuthenticatedUpgrade": {0x0780: False, 0x0788: False},
}

# Known RPC permission selector values
KNOWN_RPC_PERMISSION_VCIDS = (
    0x0380,  # CAN small JSON-RPC lane, 600-byte buffer; paired with host 0x0381
    0x0382,  # CAN large/service JSON-RPC lane, 7650-byte buffer; paired with host 0x0383
    0x0390,  # BLE plaintext small session lane, 600-byte buffer; paired with host 0x0391
    0x0392,  # BLE plaintext large session lane, 7650-byte buffer; paired with host 0x0393
    0x0394,  # BLE encrypted small RPC lane, 632-byte buffer; paired with host 0x0395
    0x0396,  # BLE encrypted large RPC lane, 7682-byte buffer; paired with host 0x0397
    0x0398,  # no endpoint-catalog transport row found
    0x0780,  # Internal/cloud small RPC lane, 1024-byte buffer; paired with 0x0781
    0x0788,  # Internal/cloud large RPC lane, 7650-byte buffer; paired with 0x0789
)

# RPC method names known from AS11 firmware dispatch tables. Used only to
# locate the moving method->command-id table; patch defaults live in DEFAULT_RPC_PERMISSIONS
KNOWN_RPC_METHODS = (
    "GetVersion",
    "EnterTherapy",
    "EnterStandby",
    "SubscribeEvent",
    "GetDateTime",
    "SetDateTime",
    "EnterMaskFit",
    "Get",
    "Set",
    "GetRtcAndSystemClocks",
    "StartKeyExchange",
    "ConfirmKeyExchange",
    "RequestSession",
    "CheckSessionIntegrity",
    "GenerateAuthCode",
    "ClearAutoConnectList",
    "StartStream",
    "DiscardPairKey",
    "StartSpool",
    "PullSpoolFragments",
    "CheckLcdText",
    "CheckLcdBitmap",
    "CheckLcdWindow",
    "CheckLcdRectFilled",
    "CheckLcdLine",
    "ShowAllMenuListItems",
    "GetBitmapInfo",
    "InsertSdCard",
    "RemoveSdCard",
    "InitiateUpgrade",
    "UpgradeDataBlock",
    "CheckUpgradeFile",
    "ApplyUpgrade",
    "ApplyAuthenticatedUpgrade",
    "EnterTest",
    "EnterTestDrive",
    "EraseData",
    "ResetDevice",
    "StoreSecurityData",
    "VerifySecurityData",
    "GetLedStatus",
    "SetNextPowerUpDateTime",
    "InjectLoggedEvent",
    "EnableSecurity",
)

# GUI/config descriptors that must stay hidden even when activating tables.
BLACKLISTED_SETTING_PATTERNS = (
    # "HeightDisplayUnit",
    # "LearnTargets*",
    "*RampDown*",
    # "PHI",  # iVAPS-PatientHeight, inches
    # "iVAPS-*",
    # "PAC-*",
    "MaxRampTime",
)

# Non-mode APPL/RPC JSON profile nodes tied to hidden experimental features.
BLACKLISTED_FEATURE_PROFILE_NODE_NAMES = (
    # "HeightFeature",
    "RampDownFeature",
)

# g5 selectors whose option masks gate the available therapy modes.
MODE_SELECTOR_NAMES = (
    "MOP",
    "GOM",
    "TOM",
)

AS11_VID_SPOOF_PAYLOAD = "as11_vid_spoof"

AS11_MOP_CALLBACK_DISPATCHER_PAYLOAD = "as11_mop_callback_dispatcher"

AS11_ASV_BACKUP_RATE_PAYLOAD = "as11_asv_backup_rate"

AS11_CUSTOM_SETTINGS_PAYLOAD = "as11_custom_settings"


class S11Firmware(object):

    FLASH_BASE = 0x08000000

    FGBL_OFF = 0x00000
    FGBL_SIZE = 0x20000
    CONF_OFF = 0x20000
    CONF_SIZE = 0x20000
    APPL_OFF = 0x40000
    APPL_SIZE = 0x1C0000

    GLOBALS_REL = 0x104
    BID_OFFSET = FGBL_OFF + 0x4000

    G1_STRIDE = 10
    G2_STRIDE = 32
    G3_STRIDE = 20
    G5_STRIDE = 16
    G10_STRIDE = 14

    DESCRIPTOR_FIELDS = {
        "g1": {
            "flags": (0x00, 2),
            "data_rule_id": (0x02, 1),
            "linked_counter_index": (0x04, 2),
            "change_event_queue_index": (0x06, 1),
            "buffer_capacity": (0x08, 2),
        },
        "g2": {
            "flags": (0x00, 2),
            "data_rule_id": (0x02, 1),
            "linked_counter_index": (0x04, 2),
            "change_event_queue_index": (0x06, 1),
            "default": (0x08, 4),
            "max": (0x0C, 4),
            "min": (0x10, 4),
            "decimal_places": (0x14, 1),
            "scale": (0x16, 2),
            "step": (0x18, 2),
            "bounds_slot": (0x1A, 1),
            "sample_block_signal_id": (0x1B, 1),
            "quantity_class": (0x1C, 1),
        },
        "g3": {
            "flags": (0x00, 2),
            "data_rule_id": (0x02, 1),
            "linked_counter_index": (0x04, 2),
            "change_event_queue_index": (0x06, 1),
            "default_mask": (0x08, 4),
            "editable_mask": (0x0C, 4),
            "bit_count": (0x10, 1),
            "selection_order_offset": (0x12, 2),
        },
        "g5": {
            "flags": (0x00, 2),
            "data_rule_id": (0x02, 1),
            "linked_counter_index": (0x04, 2),
            "change_event_queue_index": (0x06, 1),
            "default_option": (0x08, 1),
            "n_options": (0x09, 1),
            "reserved": (0x0A, 2),
            "option_mask": (0x0C, 4),
        },
    }

    def __init__(self, fileobj):
        self.fw = bytearray(fileobj.read())
        self.crcfunc = self.make_crcfunc()
        self._rpc_json_index = None

        self.validate()
        self.setup_arrays()
        self.short_names = self.build_short_names()
        self.appl_nodes = self.build_appl_nodes()

    def validate(self):
        if len(self.fw) < self.APPL_OFF + self.APPL_SIZE:
            raise IOError("Input is too small for an S11 full firmware image")

        self.data_version = self.u32(self.CONF_OFF)
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

    def appx_version_key(self):
        match = re.match(r"^(\d+)\.(\d+)\.(\d+)(?:\.|$)", self.appl_ver)
        if match is None:
            raise ValueError("cannot derive APPX payload version from %r" % self.appl_ver)
        return "_".join(match.groups())

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

    def read_thumb2_bl_target(self, off):
        # Decode the target of a Thumb-2 immediate BL instruction.
        first = self.u16(off)
        second = self.u16(off + 2)
        if (first & 0xF800) != 0xF000 or (second & 0xD000) != 0xD000:
            raise ValueError("instruction at 0x%08X is not Thumb-2 BL" % self.off_to_addr(off))

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
        return self.off_to_addr(off) + 4 + immediate

    def write_thumb2_bl_target(self, off, target):
        """Replace a Thumb-2 BL target while preserving the call site."""
        source = self.off_to_addr(off)
        immediate = (target & ~1) - (source + 4)
        if immediate & 1 or not -(1 << 24) <= immediate < (1 << 24):
            raise ValueError(
                "Thumb-2 BL from 0x%08X cannot reach 0x%08X" %
                (source, target)
            )

        encoded = immediate & ((1 << 25) - 1)
        sign = (encoded >> 24) & 1
        i1 = (encoded >> 23) & 1
        i2 = (encoded >> 22) & 1
        j1 = ((~i1) & 1) ^ sign
        j2 = ((~i2) & 1) ^ sign
        first = 0xF000 | (sign << 10) | ((encoded >> 12) & 0x03FF)
        second = (
            0xD000 | (j1 << 13) | (j2 << 11) |
            ((encoded >> 1) & 0x07FF)
        )
        self.write_u16(off, first)
        self.write_u16(off + 2, second)

    def patch(self, patchdata, addr=None, dataseq=None, verbose=True, checkempty=False):
        patchdata = bytes(patchdata)
        if addr is None:
            if dataseq is None:
                raise ValueError("Need addr or dataseq")
            addr = self.find_bytes(dataseq)
        if verbose:
            print("Patching %d bytes at 0x%x" % (len(patchdata), addr))
        if checkempty and bytes(self.fw[addr:addr + len(patchdata)]) != b"\xFF" * len(patchdata):
            raise ValueError("Appears data in section you want me to patch! Bailing out...")
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
        count = discover_conf_global_count(self.fw, base)
        for idx in range(count):
            value = self.u32(base + idx * 4)
            off = self.ptr_to_off(value)
            out.append({
                "index": idx,
                "value": value,
                "offset": off,
            })
        return out

    def globals_offset(self, idx):
        row = self.globals[idx]
        if row["offset"] is None:
            raise ValueError(
                "globals[%d] value 0x%08X is not a flash pointer" %
                (idx, row["value"])
            )
        return row["offset"]

    def setup_arrays(self):
        self.globals = self.read_globals()
        self.perm_table = self.globals_offset(18)

        item_layout = discover_dataitem_layout(self.fw, self.APPL_OFF)
        self.arrays = {
            "g1": dict(base=self.globals_offset(1), stride=self.G1_STRIDE,
                       count=item_layout.g1_count, id_base=item_layout.g1_base),
            "g2": dict(base=self.globals_offset(2), stride=self.G2_STRIDE,
                       count=item_layout.g2_count, id_base=item_layout.g2_base),
            "g3": dict(base=self.globals_offset(3), stride=self.G3_STRIDE,
                       count=item_layout.g3_count, id_base=item_layout.g3_base),
            "g5": dict(base=self.globals_offset(5), stride=self.G5_STRIDE,
                       count=item_layout.g5_count, id_base=item_layout.g5_base),
        }

        print("Arrays:    g1=%d g2=%d g3=%d g5=%d" % (
            item_layout.g1_count, item_layout.g2_count,
            item_layout.g3_count, item_layout.g5_count,
        ))
        print("Globals:   %d known entries, g11=%d" % (
            len(self.globals), self.globals[11]["value"]
        ))

    def build_short_names(self):
        base = self.globals_offset(9)
        g5 = self.arrays["g5"]
        count = g5["id_base"] + g5["count"]
        return {
            vid: bytes(self.fw[base + vid * 3:base + vid * 3 + 3]).decode("ascii")
            for vid in range(count)
        }

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
        return self.short_names.get(vid, "")

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
            "flags": self.u16(off),
            "active": bool(self.u16(off) & 1),
        }
        if array == "g5":
            row.update({
                "default_option": self.u8(off + 8),
                "n_options": self.u8(off + 9),
                "reserved": self.u16(off + 10),
                "option_mask": self.u32(off + 12),
            })
        elif array == "g3":
            row.update({
                "default_mask": self.u32(off + 8),
                "editable_mask": self.u32(off + 12),
                "bit_count": self.u8(off + 16),
                "selection_order_offset": self.u16(off + 18),
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

    def write_descriptor_fields(self, row, fields):
        """Update named fields in an existing DataItem descriptor."""
        layout = self.DESCRIPTOR_FIELDS[row["array"]]
        unknown = set(fields) - set(layout)
        if unknown:
            raise ValueError(
                "unknown %s descriptor field(s): %s" %
                (row["array"], ", ".join(sorted(unknown)))
            )
        writers = {
            1: self.write_u8,
            2: self.write_u16,
            4: self.write_u32,
        }
        for field, value in fields.items():
            field_off, width = layout[field]
            writers[width](row["offset"] + field_off, value)

    def rpc_json_index(self):
        if self._rpc_json_index is None:
            rows = {}
            nodes = {}
            for off in range(self.APPL_OFF, len(self.fw) - 12, 4):
                if self.u32(off + 8) != 0x00007FFF:
                    continue
                name = self.string_at_ptr(self.u32(off))
                value = self.string_at_ptr(self.u32(off + 4))
                if not name or not value:
                    continue
                rows[off] = (name, value)
                if value.startswith("!") and value[1:].isdigit():
                    nodes[name] = int(value[1:])
            self._rpc_json_index = rows, nodes
        return self._rpc_json_index

    def find_rpc_nodes(self, names):
        wanted = set(names)
        nodes = self.rpc_json_index()[1]
        return {
            name: node_id for name, node_id in nodes.items()
            if name in wanted
        }

    def find_rpc_feature_nodes(self):
        return {
            name: node_id
            for name, node_id in self.rpc_json_index()[1].items()
            if name.endswith("Feature")
        }

    def find_rpc_feature_setting_names(self):
        rows, _ = self.rpc_json_index()
        feature_offsets = [
            off for off, (name, value) in rows.items()
            if (name.endswith("Feature") and
                value.startswith("!") and value[1:].isdigit())
        ]
        if not feature_offsets:
            return []

        # In the APPL JSON model, feature profile nodes are followed by their
        # backing settings. The next therapy profile node ends the feature area.
        names = []
        seen = set()
        off = max(feature_offsets) + 12
        while True:
            row = rows.get(off)
            if row is None:
                break
            name, value = row
            if value.startswith("!") and value[1:].isdigit():
                if name.endswith("Profile"):
                    break
            elif value not in seen:
                seen.add(value)
                names.append(value)
            off += 12
        return names

    def fix_crcs(self):
        print("Updating checksums")
        for _, off, size in self.blocks():
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


class S11FirmwarePatches(CompiledPayloadMixin):
    """Patch methods for S11 firmware."""

    PAYLOAD_LAYOUT_TEMPLATE = "as11_payload_layout_%s.tsv"
    FGBL_PAYLOAD_LAYOUT_TEMPLATE = "as11_fgbl_payload_layout_%s.tsv"
    PAYLOAD_BUILD_COMMAND = "make as11-binaries"
    CUSTOM_MENU_SECTIONS = {
        "therapy": 0,
        "comfort": 1,
        "accessories": 2,
        "options": 3,
        "configuration": 4,
    }
    CUSTOM_SETTING_RECLAIM_POOLS = {
        "reminders": {
            "resources": (
                "RIF", "RIM", "RIT", "RIC",
                "RDF", "RDM", "RDT", "RDH",
                "RTF", "RTM", "RTT", "RTH",
            ),
            "handler": "_custom_settings_reclaim_reminders",
        },
    }
    CUSTOM_MENU_FACTORY_SYMBOLS = {
        "text_value": "custom_menu_text_value_factory",
    }

    def __init__(self, asf, rpc_permissions=None):
        self.asf = asf
        self._init_compiled_payloads()
        self.mop_callback_handlers = []
        self.mop_callback_handler_seen = set()
        self.custom_settings_enabled = False
        self.custom_setting_claims = {}
        self.custom_menu_entries = []
        self.custom_setting_bindings = []
        if rpc_permissions is None:
            rpc_permissions = DEFAULT_RPC_PERMISSIONS
        self.rpc_permission_rules = {
            method: dict(vcid_permissions)
            for method, vcid_permissions in rpc_permissions.items()
        }

    def _payload_version_key(self, region=None):
        region = "APPL" if region is None else region
        if region == "APPL":
            return self.asf.appx_version_key()
        if region == "FGBL":
            match = re.match(r"^(\d+)\.(\d+)\.(\d+)(?:\.|$)", self.asf.bid)
            if match is not None:
                return "_".join(match.groups())
        raise ValueError("cannot derive %s payload version" % region)

    def _payload_layout_template(self, region=None):
        region = "APPL" if region is None else region
        if region == "APPL":
            return self.PAYLOAD_LAYOUT_TEMPLATE
        if region == "FGBL":
            return self.FGBL_PAYLOAD_LAYOUT_TEMPLATE
        raise ValueError("cannot select %s payload layout" % region)

    def _payload_flash_range(self, region=None):
        region = "APPL" if region is None else region
        if region == "APPL":
            start = self.asf.FLASH_BASE + self.asf.APPL_OFF
            return start, start + self.asf.APPL_SIZE
        if region == "FGBL":
            start = self.asf.FLASH_BASE + self.asf.FGBL_OFF
            return start, start + self.asf.FGBL_SIZE
        raise ValueError("cannot select %s payload range" % region)

    def patch_fgbl_service(self):
        """Add bootloader support for firmware dump and restore over CAN."""
        version = self._payload_version_key("FGBL")
        version_data = AS11_FGBL_PATCH_VERSIONS.get(version)
        if version_data is None:
            raise ValueError("FGBL service: unsupported bootloader BID %r" % self.asf.bid)
        storage = {}
        for role in ("gate", "extension"):
            name = "as11_fgbl_service_" + role
            data, _ = self._load_versioned_bin(name, required=True, region="FGBL")
            storage[role], _ = self._inject_payload(name, data, region="FGBL")
        for hook, role in (("selector_hook", "gate"),
                           ("dispatch_hook_storage", "extension")):
            self.asf.write_thumb2_bl_target(
                self.asf.ptr_to_off(version_data[hook]), storage[role]
            )

    def mop_callback_register_handler(self, handler, name):
        """Register one feature handler to run after a MOP writeback."""
        handler = int(handler) | 1
        if handler in self.mop_callback_handler_seen:
            return
        self.mop_callback_handler_seen.add(handler)
        self.mop_callback_handlers.append(handler)
        print("  MOP callback handler: %s at 0x%08X" % (name, handler))

    def patch_mop_callback_dispatcher(self):
        """Install the shared EnumDataItem writeback dispatcher."""
        writeback_pattern = (
            0xDF, 0xF8, None, None, 0xB0, 0xF9, 0x14, 0x20,
            0x01, 0xEB, 0x82, 0x01, 0x80, 0x7D, 0x88, 0x70, 0x70, 0x47,
        )

        if not self.mop_callback_handlers:
            return PatchOutcome.skip("no callback handlers registered")
        if len(self.mop_callback_handlers) > 4:
            raise ValueError(
                "mop_callback_dispatcher: too many handlers (%d)" %
                len(self.mop_callback_handlers)
            )

        data, ver = self._load_versioned_bin(
            AS11_MOP_CALLBACK_DISPATCHER_PAYLOAD, required=True
        )
        elf_path = self._versioned_artifact_path(
            AS11_MOP_CALLBACK_DISPATCHER_PAYLOAD, "elf", ver
        )
        start = self._elf_symbol_addr(elf_path, "start")
        handler_table = self._elf_symbol_addr(
            elf_path, "mop_callback_handler_table"
        )

        version = AS11_PATCH_VERSIONS.get(ver, {})
        anchors = version.get("mop_callback_dispatcher")
        if anchors is None:
            raise ValueError(
                "mop_callback_dispatcher: no anchors for APPX %s" % ver
            )
        writeback = anchors["writeback"]
        writeback_off = self.asf.ptr_to_off(writeback)
        slot = self.asf.ptr_to_off(anchors["vtable_slot"])
        if (writeback_off is None or
                writeback_off + len(writeback_pattern) > len(self.asf.fw)):
            raise ValueError(
                "mop_callback_dispatcher: %s writeback anchor is outside firmware" % ver
            )
        for index, expected in enumerate(writeback_pattern):
            if expected is not None and self.asf.u8(writeback_off + index) != expected:
                raise ValueError(
                    "mop_callback_dispatcher: %s writeback anchor does not match" % ver
                )
        if slot is None:
            raise ValueError(
                "mop_callback_dispatcher: %s vtable slot is outside firmware" % ver
            )

        writeback = self.asf.off_to_addr(writeback_off)
        original = writeback | 1
        if self.asf.u32(slot) != original:
            raise ValueError(
                "mop_callback_dispatcher: vtable slot 0x%08X contains "
                "0x%08X, expected 0x%08X" %
                (self.asf.off_to_addr(slot), self.asf.u32(slot), original)
            )

        flash, _off = self._inject_payload(
            AS11_MOP_CALLBACK_DISPATCHER_PAYLOAD, data
        )
        table_off = handler_table - self.asf.FLASH_BASE
        self.asf.write_u32(table_off, original)
        for index, handler in enumerate(self.mop_callback_handlers):
            self.asf.write_u32(table_off + (index + 1) * 4, handler)
        self.asf.write_u32(
            table_off + (len(self.mop_callback_handlers) + 1) * 4, 0xFFFFFFFF
        )
        self.asf.write_u32(slot, start | 1)

        print(
            "  MOP callback dispatcher: build/%s_%s.bin (%dB) at 0x%08X" %
            (AS11_MOP_CALLBACK_DISPATCHER_PAYLOAD, ver, len(data), flash)
        )
        print(
            "  EnumDataItem writeback: 0x%08X -> 0x%08X" %
            (original, start | 1)
        )

    def enable_custom_settings(self):
        """Enable custom settings requested by payload patches."""
        self.custom_settings_enabled = True

    def therapy_mode_mask(self, *names):
        """Build the MOP bitset used to gate a custom menu row."""
        wanted = set(names)
        mask = 0
        for bit, prefix, _profile, _supported in THERAPY_MODES:
            if prefix in wanted:
                mask |= 1 << bit
                wanted.remove(prefix)
        if wanted:
            raise ValueError(
                "unknown therapy mode(s): %s" % ", ".join(sorted(wanted))
            )
        return mask

    @staticmethod
    def _custom_setting_key(name):
        short = name.lstrip("_")
        return short.upper() if len(short) == 3 else name

    def _custom_setting_reclaim_pool(self, setting):
        for pool, definition in self.CUSTOM_SETTING_RECLAIM_POOLS.items():
            if setting in definition["resources"]:
                return pool
        return None

    def custom_setting_claim(self, name, owner):
        """Reserve one reclaimed DataItem for a feature patch."""
        name = self._custom_setting_key(name)
        pool = self._custom_setting_reclaim_pool(name)
        if pool is None:
            raise ValueError(
                "custom settings: %s is not a reclaimed resource" % name
            )
        if name in self.custom_setting_claims:
            raise ValueError(
                "custom settings: %s already claimed by %s" %
                (name, self.custom_setting_claims[name]["owner"])
            )
        self.custom_setting_claims[name] = {
            "owner": owner,
            "pool": pool,
            "definition": None,
        }
        return name

    def custom_setting_define(self, setting, **fields):
        """Define descriptor fields for a claimed DataItem."""
        setting = self._custom_setting_key(setting)
        if setting not in self.custom_setting_claims:
            raise ValueError("custom settings: unclaimed setting %s" % setting)
        claim = self.custom_setting_claims[setting]
        if claim["definition"] is not None:
            raise ValueError("custom settings: %s defined twice" % setting)
        claim["definition"] = dict(fields)

    def custom_menu_add(
            self, section, setting, label_id, mode_mask,
            factory):
        """Append a DataItem to one clinical-menu section."""
        section = section.lower()
        if section not in self.CUSTOM_MENU_SECTIONS:
            raise ValueError("custom settings: unknown section %s" % section)
        setting = self._custom_setting_key(setting)
        if not 0 <= label_id <= 0xFFFF:
            raise ValueError(
                "custom settings: invalid GUI text id 0x%X" % label_id
            )
        if not 0 <= mode_mask <= 0xFFFF:
            raise ValueError(
                "custom settings: invalid mode mask 0x%X" % mode_mask
            )
        self.custom_menu_entries.append({
            "section": section,
            "setting": setting,
            "label_id": label_id,
            "mode_mask": mode_mask,
            "factory": factory,
        })

    def custom_setting_bind(self, setting, abi_slot):
        """Write a DataItem's var_id into a payload ABI slot."""
        setting = self._custom_setting_key(setting)
        self.custom_setting_bindings.append((setting, abi_slot))

    def custom_settings_layout(self, ver):
        """Return stock clinical-menu anchors for one APPX version."""
        layout = AS11_PATCH_VERSIONS.get(ver, {}).get("custom_settings")
        if layout is None:
            raise ValueError(
                "custom settings: no UI layout for APPX %s" % ver
            )
        return layout

    def _custom_settings_expect_bytes(self, address, expected_hex, label):
        off = self.asf.ptr_to_off(address)
        expected = bytes.fromhex(expected_hex)
        if off is None:
            raise ValueError("custom settings: invalid %s site" % label)
        actual = bytes(self.asf.fw[off:off + len(expected)])
        if actual != expected:
            raise ValueError(
                "custom settings: %s at 0x%08X contains %s, expected %s" %
                (label, address, actual.hex(), expected.hex())
            )
        return off

    def _custom_settings_reclaim_reminders(self, layout):
        """Detach the stock Reminders consumers from its persistent fields."""
        label_addr, label_hex = layout["row_label"]
        self._custom_settings_expect_bytes(
            label_addr, label_hex, "Reminders row label"
        )
        store_addr, store_hex = layout["row_store"]
        self._custom_settings_expect_bytes(
            store_addr, store_hex, "Reminders row slot"
        )

        row_call, row_ctor = layout["row_call"]
        row_call_off = self.asf.ptr_to_off(row_call)
        if (row_call_off is None or
                self.asf.read_thumb2_bl_target(row_call_off) != row_ctor):
            raise ValueError("custom settings: Reminders row does not match")

        scheduler_call, scheduler_target = layout["scheduler_call"]
        scheduler_off = self.asf.ptr_to_off(scheduler_call)
        if (scheduler_off is None or
                self.asf.read_thumb2_bl_target(scheduler_off) !=
                scheduler_target):
            raise ValueError(
                "custom settings: reminder scheduler call does not match"
            )

        return {
            "removed_rows": (layout["row_index"],),
            "patches": ((scheduler_off, b"\x00\xBF\x00\xBF"),),
        }

    def finalize_custom_settings(self):
        """Resolve queued feature requests and install their shared support."""
        if not self.custom_settings_enabled:
            return
        if not (self.custom_setting_claims or self.custom_menu_entries or
                self.custom_setting_bindings):
            print("  custom settings: skipped (no active features)")
            return

        ver = self._payload_version_key()

        # Resolve each requested DataItem once after all feature patches have
        # declared their storage, menu, and ABI requirements.
        setting_names = set(self.custom_setting_claims)
        setting_names.update(
            request["setting"] for request in self.custom_menu_entries
        )
        setting_names.update(
            setting for setting, _abi_slot in self.custom_setting_bindings
        )
        setting_rows = {}
        for setting in setting_names:
            rows = self.asf.find_descriptors_by_name(setting)
            if not rows:
                raise ValueError(
                    "custom settings: descriptor %s not found" % setting
                )
            setting_rows[setting] = rows[0]

        # A reclaim provider detaches the stock consumers for its entire pool.
        # Build each provider's patch plan once, regardless of how many of its
        # DataItems were claimed.
        removed_rows = []
        stock_patches = []
        pools = sorted({
            claim["pool"] for claim in self.custom_setting_claims.values()
        })
        layout = (
            self.custom_settings_layout(ver)
            if pools or self.custom_menu_entries else None
        )
        for pool in pools:
            handler_name = self.CUSTOM_SETTING_RECLAIM_POOLS[pool]["handler"]
            handler = getattr(self, handler_name)
            plan = handler(layout["reclaim"][pool])
            removed_rows.extend(plan.get("removed_rows", ()))
            stock_patches.extend(plan.get("patches", ()))

        menu_entries = []
        menu_factories = []
        menu_factory_indexes = {}
        menu_payload = None
        menu_symbols = None
        if self.custom_menu_entries or removed_rows:
            # Menu rows and reclaimed stock rows share one bridge payload.
            data, _payload_ver = self._load_versioned_bin(
                AS11_CUSTOM_SETTINGS_PAYLOAD
            )
            if data is None:
                return

            elf_path = self._versioned_artifact_path(
                AS11_CUSTOM_SETTINGS_PAYLOAD, "elf", ver
            )
            factory_symbols = {
                name: self._elf_symbol_addr(elf_path, symbol)
                for name, symbol in self.CUSTOM_MENU_FACTORY_SYMBOLS.items()
            }

            # Menu records store one-byte indexes into a deduplicated factory
            # table instead of repeating Thumb function pointers.
            for request in self.custom_menu_entries:
                factory = request["factory"]
                if isinstance(factory, str):
                    if factory not in factory_symbols:
                        raise ValueError(
                            "custom settings: unknown menu factory %s" %
                            factory
                        )
                    factory = factory_symbols[factory]
                factory = int(factory) | 1
                factory_index = menu_factory_indexes.get(factory)
                if factory_index is None:
                    factory_index = len(menu_factories)
                    if factory_index > 0xFF:
                        raise ValueError(
                            "custom settings: too many menu factories"
                        )
                    menu_factory_indexes[factory] = factory_index
                    menu_factories.append(factory)
                row = setting_rows[request["setting"]]
                menu_entries.append((
                    row["var_id"],
                    request["label_id"],
                    request["mode_mask"],
                    self.CUSTOM_MENU_SECTIONS[request["section"]],
                    factory_index,
                ))

            # These final-link symbols locate the registries to populate after
            # the bridge is copied into its allocated code cave.
            menu_symbols = {
                "start": self._elf_symbol_addr(elf_path, "start"),
                "wrapper": self._elf_symbol_addr(
                    elf_path, "custom_settings_clinical_scroller_ctor"
                ),
                "entries": self._elf_symbol_addr(
                    elf_path, "custom_menu_entries"
                ),
                "entries_size": self._elf_symbol_size(
                    elf_path, "custom_menu_entries"
                ),
                "factories": self._elf_symbol_addr(
                    elf_path, "custom_menu_factories"
                ),
                "factories_size": self._elf_symbol_size(
                    elf_path, "custom_menu_factories"
                ),
                "removed_rows": self._elf_symbol_addr(
                    elf_path, "custom_menu_removed_rows"
                ),
                "removed_rows_size": self._elf_symbol_size(
                    elf_path, "custom_menu_removed_rows"
                ),
            }

            # Registry capacities and the stock scroller call must match before
            # the bridge payload or any CONF descriptors are changed.
            entry_size = struct.calcsize("<HHHBB")
            if len(menu_entries) * entry_size > menu_symbols["entries_size"]:
                raise ValueError("custom settings: menu registry is too small")
            if len(menu_factories) * 4 > menu_symbols["factories_size"]:
                raise ValueError("custom settings: factory registry is too small")
            if len(removed_rows) * 2 > menu_symbols["removed_rows_size"]:
                raise ValueError("custom settings: removal registry is too small")

            call_off = self.asf.ptr_to_off(layout["menu"]["scroller_call"])
            scroller_ctor = self._elf_symbol_addr(
                elf_path, "GuiScroller_ctor"
            )
            if (call_off is None or
                    self.asf.read_thumb2_bl_target(call_off) != scroller_ctor):
                raise ValueError(
                    "custom settings: clinical settings scroller does not match"
                )
            menu_symbols["call_off"] = call_off
            menu_payload = data

        # Apply the prepared payload, descriptor, ABI, and reclaim changes.
        menu_flash = None
        if menu_payload is not None:
            menu_flash, _off = self._inject_payload(
                AS11_CUSTOM_SETTINGS_PAYLOAD, menu_payload
            )

        # Recast claimed persistent DataItems for their new feature roles.
        for setting, claim in self.custom_setting_claims.items():
            if claim["definition"] is not None:
                self.asf.write_descriptor_fields(
                    setting_rows[setting], claim["definition"]
                )

        # Compiled feature payloads receive resolved var_ids through explicit
        # 16-bit ABI slots, keeping descriptor indexes out of their code.
        for setting, abi_slot in self.custom_setting_bindings:
            abi_off = self.asf.ptr_to_off(abi_slot)
            if (abi_off is None or abi_off + 2 > len(self.asf.fw) or
                    self.asf.u16(abi_off) != 0xFFFF):
                raise ValueError(
                    "custom settings: ABI slot at 0x%08X is not empty" %
                    abi_slot
                )
            self.asf.write_u16(abi_off, setting_rows[setting]["var_id"])

        # Remove the original consumers only after their replacement resources
        # and payload bindings have been installed.
        for off, patch_data in stock_patches:
            self.asf.patch(patch_data, addr=off, verbose=False)

        if menu_symbols is not None:
            # Populate payload-owned registries, then redirect the stock
            # clinical scroller construction through the bridge.
            if menu_entries:
                menu_data = b"".join(
                    struct.pack("<HHHBB", *entry)
                    for entry in menu_entries
                )
                self.asf.patch(
                    menu_data,
                    addr=menu_symbols["entries"] - self.asf.FLASH_BASE,
                    verbose=False,
                )
                self.asf.patch(
                    struct.pack("<%dI" % len(menu_factories),
                                *menu_factories),
                    addr=(
                        menu_symbols["factories"] - self.asf.FLASH_BASE
                    ),
                    verbose=False,
                )
            if removed_rows:
                self.asf.patch(
                    struct.pack("<%dH" % len(removed_rows), *removed_rows),
                    addr=(
                        menu_symbols["removed_rows"] - self.asf.FLASH_BASE
                    ),
                    verbose=False,
                )
            self.asf.write_thumb2_bl_target(
                menu_symbols["call_off"], menu_symbols["wrapper"]
            )
            if menu_entries:
                # Refresh custom row visibility whenever MOP is committed.
                self.mop_callback_register_handler(
                    menu_symbols["start"], "custom_settings"
                )

        for request in self.custom_menu_entries:
            row = setting_rows[request["setting"]]
            print(
                "  custom setting %s/%s: label=0x%04X var_id=0x%04X" %
                (request["section"], row["short_name"] or row["long_name"],
                 request["label_id"], row["var_id"])
            )
        if menu_payload is not None:
            print(
                "  custom settings: build/%s_%s.bin (%dB) at 0x%08X" %
                (AS11_CUSTOM_SETTINGS_PAYLOAD, ver,
                 len(menu_payload), menu_flash)
            )

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
            flags = row["flags"]
            if flags >= 0x0200 and not (flags & 1):
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
            for array in ("g2", "g5"):
                spec = self.asf.arrays[array]
                idx = target - spec["id_base"]
                if 0 <= idx < spec["count"]:
                    rows.append(self.asf.descriptor(array, idx))
            return rows
        return self.asf.find_descriptors_by_name(target, ("g2", "g5"))

    def write_default_value(self, row, value):
        off = row["offset"]
        array = row["array"]
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
            return PatchOutcome.warn("%d defaults skipped" % n_skipped)
        return PatchOutcome.ok()

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
        if n_missing:
            return PatchOutcome.warn("language configuration not found")
        return PatchOutcome.ok()

    def therapy_screen(self):
        """Show respiratory statistics hidden from compatible therapy modes."""
        visibility_plan = {
            "ZLF": (0, 1, 2),  # Leak: CPAP, AutoSet, HerAuto
            "MV5": (0, 1, 2),  # Minute ventilation
            "RRR": (0, 1, 2),  # Respiratory rate
            "ZTD": (0, 1, 2),  # Tidal volume
            "IER": (0, 1, 2),  # I:E ratio
            "IN5": (7, 8),     # Ti: ASV, ASVAuto
        }
        # SPONT CYC (RCR) and SPONT TRIG (RTR) are gated outside g[10].
        g10_base = self.asf.globals_offset(10)
        g10_count = self.asf.globals[11]["value"]
        rows_by_var = {
            self.asf.u16(g10_base + index * self.asf.G10_STRIDE):
                g10_base + index * self.asf.G10_STRIDE
            for index in range(g10_count)
        }

        changed = 0
        already_visible = 0
        for tag, mode_indexes in visibility_plan.items():
            descriptors = self.asf.find_descriptors_by_name(tag, ("g2",))
            if not descriptors:
                raise ValueError("therapy screen: %s descriptor not found" % tag)
            row_off = rows_by_var.get(descriptors[0]["var_id"])
            if row_off is None:
                raise ValueError("therapy screen: %s has no mode visibility row" % tag)
            for mode_index in mode_indexes:
                visibility_off = row_off + 2 + mode_index
                if self.asf.u8(visibility_off):
                    already_visible += 1
                else:
                    self.asf.write_u8(visibility_off, 1)
                    changed += 1

        print(
            "Patching therapy screen... %d visibility flags enabled, "
            "%d already enabled" % (changed, already_visible)
        )

    def fix_ivaps_patient_height_range(self):
        """Replace the stripped metric-height descriptor with usable bounds."""
        pht_rows = self.asf.find_descriptors_by_name("PHT", ("g2",))
        phi_rows = self.asf.find_descriptors_by_name("PHI", ("g2",))
        if not pht_rows or not phi_rows:
            raise ValueError("iVAPS height descriptors are missing")

        pht = pht_rows[0]
        phi = phi_rows[0]
        if self.asf.u16(pht["offset"] + 0x16) != 1 or self.asf.u16(phi["offset"] + 0x16) != 1:
            raise ValueError("iVAPS height descriptor scale does not match")

        # Firmware synchronizes the centimeter and inch DataItems with an
        # exact 2.5 conversion. PHI retains its complete range in stripped
        # CONF images, while PHT carries unusable integer-sentinel bounds.
        def inches_to_cm_raw(value):
            scaled = value * 5
            if scaled & 1:
                raise ValueError("iVAPS inch height does not convert to an integer centimeter value")
            return scaled // 2

        phi_off = phi["offset"]
        expected = (
            inches_to_cm_raw(self.asf.u32(phi_off + 0x08)),
            inches_to_cm_raw(self.asf.u32(phi_off + 0x0C)),
            inches_to_cm_raw(self.asf.u32(phi_off + 0x10)),
            inches_to_cm_raw(self.asf.u16(phi_off + 0x18)),
        )
        pht_off = pht["offset"]
        current = (
            self.asf.u32(pht_off + 0x08),
            self.asf.u32(pht_off + 0x0C),
            self.asf.u32(pht_off + 0x10),
            self.asf.u16(pht_off + 0x18),
        )
        placeholder = (0, 0x7FFFFFFF, 0x80000001, expected[3])
        if current == expected:
            print("Patching iVAPS patient height... already hydrated")
            return 0
        if current != placeholder:
            raise ValueError("iVAPS metric-height descriptor has unexpected bounds")

        self.asf.write_u32(pht_off + 0x08, expected[0])
        self.asf.write_u32(pht_off + 0x0C, expected[1])
        self.asf.write_u32(pht_off + 0x10, expected[2])
        print(
            "Patching iVAPS patient height... default=%d range=%d..%d step=%d" %
            (expected[0], expected[2], expected[1], expected[3])
        )
        return 1

    def unlock_features(self):
        """Unlock therapy modes and related GUI settings at descriptor level."""
        if any(prefix == "iVAPS" and supported
               for _bit, prefix, _profile, supported in THERAPY_MODES):
            self.fix_ivaps_patient_height_range()

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

        n_enum_options = 0
        n_enum_already = 0
        n_enum_missing = 0
        n_enum_skipped = 0
        for name in UNLOCKED_ENUM_SETTING_NAMES:
            rows = self.asf.find_descriptors_by_name(name, ("g5",))
            if not rows:
                print("  enum option mask %s not found" % name)
                n_enum_missing += 1
                continue
            for row in rows:
                n_options = row["n_options"]
                if n_options == 0:
                    n_enum_skipped += 1
                    continue
                desired_mask = (1 << min(n_options, 32)) - 1
                off = row["offset"]
                if self.asf.u32(off + 12) == desired_mask:
                    n_enum_already += 1
                    continue
                self.asf.write_u32(off + 12, desired_mask)
                n_enum_options += 1

        n_editable = 0
        n_already = 0
        n_skipped = 0
        for row in editable_rows:
            # Named feature/therapy enum settings need non-zero option masks
            # before the GUI can edit them. Existing non-zero masks are
            # preserved because variant firmwares may already narrow them.
            n_options = row["n_options"]
            mask = self.asf.u32(row["offset"] + 12)
            if n_options == 0:
                n_skipped += 1
                continue
            if mask != 0:
                n_already += 1
                continue
            self.asf.write_u32(
                row["offset"] + 12,
                (1 << min(n_options, 32)) - 1,
            )
            n_editable += 1

        print("Patching GUI ACT flags... g1=%d g2=%d g3=%d g5=%d" % (n_g1, n_g2, n_g3, n_g5))
        if n_hidden_act or n_hidden_masks:
            print("Hiding blacklisted settings... %d ACT flags, %d masks" % (
                n_hidden_act, n_hidden_masks
            ))
        print("Patching GUI mode gates... %d selectors" % n_modes)
        print("Patching standalone enum options... %d enabled, %d already enabled, %d missing, %d skipped" % (
            n_enum_options, n_enum_already, n_enum_missing, n_enum_skipped
        ))
        print("Patching GUI enum editability... %d/%d masks enabled (%d already enabled, %d skipped)" % (
            n_editable, len(editable_rows), n_already, n_skipped
        ))

    def rpc_json_profile_visibility(self):
        # Each globals[18] record contains independent read-enabled and
        # write-blocked bytes. Profile visibility changes only the former;
        # backing setting descriptors still need their own flags and masks.
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

        hidden_nodes = self.asf.find_rpc_nodes(blacklisted_nodes)
        permission_count = discover_rpc_json_permission_count(
            self.asf.fw, self.asf.APPL_OFF
        )
        for name, node_id in {**nodes, **hidden_nodes}.items():
            if not 0 <= node_id < permission_count:
                raise ValueError(
                    "metadata: RPC node %s id %d exceeds permission count %d" %
                    (name, node_id, permission_count)
                )

        n = 0
        for name, node_id in sorted(nodes.items(), key=lambda item: (item[1], item[0])):
            off = self.asf.perm_table + node_id * 2
            if self.asf.u8(off) == 0:
                self.asf.write_u8(off, 1)
                n += 1

        n_hidden = 0
        for name, node_id in sorted(hidden_nodes.items(), key=lambda item: (item[1], item[0])):
            off = self.asf.perm_table + node_id * 2
            if self.asf.u8(off) != 0:
                self.asf.write_u8(off, 0)
                n_hidden += 1

        print("Patching RPC JSON profile visibility... %d/%d nodes enabled" % (n, len(nodes)))
        if n_hidden:
            print("Hiding blacklisted RPC JSON profile nodes... %d nodes disabled" % n_hidden)

    def asv_pressure_support_range(self):
        """Remove the ASV/ASVAuto 5 cmH2O MinPS/MaxPS separation."""
        pairs = (
            ("ASV-MaxPressureSupport", "ASV-MinPressureSupport"),
            ("ASVAuto-MaxPressureSupport", "ASVAuto-MinPressureSupport"),
        )
        max_rows = []
        rows = []
        n_static_bounds = 0
        n_max_floor = 0
        static_bounds_slot = (
            0x3D if self.asf.data_version >= 16 else 0x3E
        )

        for max_name, min_name in pairs:
            found = self.asf.find_descriptors_by_name(max_name, ("g2",))
            if len(found) != 1:
                raise ValueError("asv_pressure_support_range: expected one %s descriptor, found %d" %
                                 (max_name, len(found)))
            max_row = found[0]
            found = self.asf.find_descriptors_by_name(min_name, ("g2",))
            if len(found) != 1:
                raise ValueError("asv_pressure_support_range: expected one %s descriptor, found %d" %
                                 (min_name, len(found)))
            min_row = found[0]
            max_rows.append(max_row)
            rows.extend((max_row, min_row))

            # MaxPS has a static 5 cmH2O floor. Match it to MinPS, then force
            # both descriptors off the runtime dynamic-bounds slots that also
            # encode the stock 5 cmH2O separation during setting application.
            max_min_off = max_row["offset"] + 0x10
            min_min = self.asf.u32(min_row["offset"] + 0x10)
            if self.asf.u32(max_min_off) != min_min:
                self.asf.write_u32(max_min_off, min_min)
                n_max_floor += 1

        for row in rows:
            bounds_off = row["offset"] + 0x1A
            if self.asf.u8(bounds_off) != static_bounds_slot:
                self.asf.write_u8(bounds_off, static_bounds_slot)
                n_static_bounds += 1

        # PairedNumericRangeSelector PS helper takes ASV-MaxPressureSupport and
        # ASVAuto-MaxPressureSupport, multiplies raw scale by 5 and adds MinPS.
        # Descriptor indexes drift between releases, so include resolved indexes
        # in the signature and patch only the nearby "movs r0, #5".
        pattern = (
            0x32, 0xB5, 0x98, 0xB0, 0x04, 0x00, 0x20, 0x00,
            0x00, 0xB2, max_rows[0]["index"], 0x28, 0x03, 0xD0,
            0x20, 0x00, 0x00, 0xB2, max_rows[1]["index"], 0x28, 0x23, 0xD1,
        )
        helper_off = self.asf.find_bytes(bytes(pattern), self.asf.APPL_OFF)
        mul_off = None
        for off in range(helper_off, min(helper_off + 0x60, len(self.asf.fw) - 4)):
            if bytes(self.asf.fw[off + 1:off + 4]) == bytes.fromhex("204543"):
                if self.asf.u8(off) in (0, 5):
                    mul_off = off
                    break
        if mul_off is None:
            raise ValueError("asv_pressure_support_range: multiplier not found near helper")

        n_code = 0
        if self.asf.u8(mul_off) == 5:
            self.asf.write_u8(mul_off, 0)
            n_code = 1

        print("Patching ASV pressure support range... %d max floors, %d static bounds, %d code constants" %
              (n_max_floor, n_static_bounds, n_code))

    def asv_backup_rate(self):
        """Install an ASV/ASVAuto update wrapper that inhibits backup breaths."""
        data, ver = self._load_versioned_bin(AS11_ASV_BACKUP_RATE_PAYLOAD)
        if data is None:
            return PatchOutcome.skip("compiled payload unavailable")

        elf_path = self._versioned_artifact_path(
            AS11_ASV_BACKUP_RATE_PAYLOAD, "elf", ver
        )
        start = self._elf_symbol_addr(elf_path, "start")
        backup_rate_var_slot = self._elf_symbol_addr(
            elf_path, "as11_asv_backup_rate_var_id"
        )
        original_update = self._elf_symbol_addr(elf_path, "AsvFeature_update")
        original_ptr = original_update | 1
        version = AS11_PATCH_VERSIONS.get(ver, {}).get("asv_backup_rate")
        if version is None:
            raise ValueError(
                "asv_backup_rate: no version data for APPX %s" % ver
            )
        vtable_update_off = self.asf.ptr_to_off(version["vtable_slot"])
        if (vtable_update_off is None or
                self.asf.u32(vtable_update_off) != original_ptr):
            raise ValueError(
                "asv_backup_rate: ASV update vtable slot does not match"
            )

        flash, _off = self._inject_payload(AS11_ASV_BACKUP_RATE_PAYLOAD, data)
        if not flash <= backup_rate_var_slot <= flash + len(data) - 2:
            raise ValueError("asv_backup_rate: variable-ID slot lies outside payload")
        # Replace the ASV update vtable entry; the payload calls the original
        # implementation through its versioned stub after applying the gate.
        self.asf.write_u32(vtable_update_off, start | 1)
        # Without custom-settings finalization, the untouched 0xFFFF slot keeps
        # backup-rate suppression active unconditionally.
        backup_rate_setting = self.custom_setting_claim(
            "RIF", "asv_backup_rate"
        )
        self.custom_setting_define(
            backup_rate_setting,
            default_option=1,
        )
        self.custom_menu_add(
            section="therapy",
            setting=backup_rate_setting,
            label_id=version["label_id"],
            mode_mask=self.therapy_mode_mask("ASV", "ASVAuto"),
            factory="text_value",
        )
        self.custom_setting_bind(backup_rate_setting, backup_rate_var_slot)

        print(
            "Patching ASV backup rate... build/%s_%s.bin (%dB) at 0x%08X" %
            (AS11_ASV_BACKUP_RATE_PAYLOAD, ver, len(data), flash)
        )

    def motor_nagscreen(self):
        try:
            offset = self.asf.find_bytes(bytes.fromhex("C000B304"))
            print("Patching \"Motor life exceeded\" threshold...")
            self.asf.patch(b"\xFF\xFF\xFF\x7F", addr=offset, verbose=False)
            print("ok")
            return PatchOutcome.ok()
        except ValueError:
            print("motor_nagscreen: threshold not found!")
            return PatchOutcome.warn("threshold not found")

    def rpc_permission_record_flags_are_bits(self, off, stride):
        if off + stride > len(self.asf.fw) or stride < 2:
            return False
        for idx in range(1, stride):
            flag = self.asf.u8(off + idx)
            if flag not in (0, 1):
                return False
        return True

    def find_rpc_permission_table(self):
        # Level 3 command permission table:
        # 8.3/8.4: [cmd_id] [flag0..flag7]
        # 8.5:     [cmd_id] [flag0..flag8]
        #
        # Anchor: cmd_id 4 (GetDateTime) with all flags = 1, APPL region only.
        # Walk the table bounds because command 3 is absent and table length
        # shifts between firmware builds.
        for stride in (10, 9):
            anchor = bytes([4] + [1] * (stride - 1))
            try:
                anchor_off = self.asf.find_bytes(anchor, self.asf.APPL_OFF)
                break
            except ValueError:
                continue
        else:
            raise ValueError("RPC permission table anchor not found")
        base = anchor_off
        cmd = self.asf.u8(base)
        while base - stride >= self.asf.APPL_OFF:
            prev_off = base - stride
            if not self.rpc_permission_record_flags_are_bits(prev_off, stride):
                break
            prev_cmd = self.asf.u8(prev_off)
            if prev_cmd >= cmd:
                break
            base = prev_off
            cmd = prev_cmd
        return base, stride

    def find_rpc_permission_vcid_table(self, flag_count):
        # The permission flag columns are named by a nearby u16 VCID table.
        # Its order is firmware-specific, so resolve the VCID before patching.
        known = set(KNOWN_RPC_PERMISSION_VCIDS)
        appl_end = self.asf.APPL_OFF + self.asf.APPL_SIZE
        candidates = []
        for off in range(self.asf.APPL_OFF, appl_end - flag_count * 2, 2):
            vcids = tuple(self.asf.u16(off + idx * 2) for idx in range(flag_count))
            if len(set(vcids)) != flag_count:
                continue
            if any(vcid not in known for vcid in vcids):
                continue
            after = bytes(self.asf.fw[off + flag_count * 2:off + flag_count * 2 + 64])
            score = 0
            for marker in (b"UnsupportedCommand", b"StorageFailure", b"InvalidObject"):
                if marker in after:
                    score += 1
            candidates.append((score, off, vcids))
        if not candidates:
            raise ValueError("RPC permission VCID table not found")
        candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
        best_score, best_off, best_vcids = candidates[0]
        if len(candidates) > 1 and candidates[1][0] == best_score:
            raise ValueError("RPC permission VCID table is ambiguous")
        return best_off, best_vcids

    def rpc_permission_rows(self, base, stride):
        rows = {}
        prev_cmd = -1
        off = base
        scanned = 0
        while self.rpc_permission_record_flags_are_bits(off, stride):
            cmd = self.asf.u8(off)
            if cmd <= prev_cmd:
                break
            rows[cmd] = off
            prev_cmd = cmd
            off += stride
            scanned += 1
        return rows, scanned

    def find_rpc_dispatch_table(self):
        # APPL method table: [char *method_name, u32 command_id] records.
        # The table moves between versions, so score candidates by known RPC
        # method names instead of relying on absolute addresses.
        known = set(KNOWN_RPC_METHODS)
        appl_end = self.asf.APPL_OFF + self.asf.APPL_SIZE
        best = None
        for start in range(self.asf.APPL_OFF, appl_end - 8, 4):
            seq = []
            off = start
            while off + 8 <= appl_end:
                name = self.asf.string_at_ptr(self.asf.u32(off))
                cmd = self.asf.u32(off + 4)
                if not name or cmd > 0x200:
                    break
                seq.append((name, cmd, off))
                off += 8
            if len(seq) < 10:
                continue
            score = sum(1 for name, _cmd, _off in seq if name in known)
            if score >= 8 and (best is None or (score, len(seq)) > (best[0], len(best[2]))):
                best = (score, start, seq)
        if best is None:
            raise ValueError("RPC dispatch table not found")
        return best[1], best[2]

    def rpc_method_cmds(self):
        _base, seq = self.find_rpc_dispatch_table()
        out = {}
        for name, cmd, _off in seq:
            out[name] = cmd
        return out

    def rpc_permissions(self):
        if not self.rpc_permission_rules:
            return PatchOutcome.skip("no permission rules configured")

        method_cmds = self.rpc_method_cmds()
        base, stride = self.find_rpc_permission_table()
        rows, scanned = self.rpc_permission_rows(base, stride)
        vcid_table_off, vcids = self.find_rpc_permission_vcid_table(stride - 1)
        vcid_columns = {vcid: idx + 1 for idx, vcid in enumerate(vcids)}

        for method, vcid_permissions in self.rpc_permission_rules.items():
            if method not in method_cmds:
                raise ValueError("rpc_permissions: RPC method %r not found" % method)
            for vcid, allowed in vcid_permissions.items():
                if vcid not in vcid_columns:
                    raise ValueError("rpc_permissions: VCID 0x%04X not present in permission table" % vcid)
                if not isinstance(allowed, bool):
                    raise ValueError(
                        "rpc_permissions: %s VCID 0x%04X permission must be bool" %
                        (method, vcid)
                    )

        enabled = 0
        blocked = 0
        missing = 0
        already = 0
        print("Patching RPC permissions... table 0x%05X, VCIDs %s" % (
            vcid_table_off,
            ", ".join("0x%04X" % vcid for vcid in vcids),
        ))
        for label, vcid_permissions in self.rpc_permission_rules.items():
            cmd = method_cmds[label]
            off = rows.get(cmd)
            if off is None:
                print("  %s -> id %d: permission row missing" % (label, cmd))
                missing += 1
                continue
            for vcid, allowed in vcid_permissions.items():
                value = int(allowed)
                action = "enabled" if allowed else "blocked"
                flag_off = off + vcid_columns[vcid]
                if self.asf.u8(flag_off) != value:
                    self.asf.write_u8(flag_off, value)
                    print("  %s -> id %d VCID 0x%04X: %s" %
                          (label, cmd, vcid, action))
                    if allowed:
                        enabled += 1
                    else:
                        blocked += 1
                else:
                    print("  %s -> id %d VCID 0x%04X: already %s" %
                          (label, cmd, vcid, action))
                    already += 1
        print("Patching RPC permissions... %d enabled, %d blocked, %d already set, %d missing "
              "(%d entries scanned)" %
              (enabled, blocked, already, missing, scanned))
        if missing:
            return PatchOutcome.warn("%d permission rows missing" % missing)
        return PatchOutcome.ok()

    def vid_spoof(self):
        """Set VID from MOP after the stock writeback completes."""
        data, ver = self._load_versioned_bin(AS11_VID_SPOOF_PAYLOAD)
        if data is None:
            return PatchOutcome.skip("compiled payload unavailable")
        flash, _off = self._inject_payload(AS11_VID_SPOOF_PAYLOAD, data)
        elf_path = self._versioned_artifact_path(AS11_VID_SPOOF_PAYLOAD, "elf", ver)
        handler = self._elf_symbol_addr(elf_path, "start")
        print(
            "Patching runtime VID spoof... build/%s_%s.bin (%dB) at 0x%08X" %
            (AS11_VID_SPOOF_PAYLOAD, ver, len(data), flash)
        )
        self.mop_callback_register_handler(handler, "vid_spoof")

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
        "arg": "patch-fgbl-service",
        "desc": "Add bootloader support for firmware dump and restore over CAN.",
        "default": True,
        "function": "patch_fgbl_service",
    },
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
        "desc": "Expose the official S11 EDF schema superset.",
        "default": True,
        "function": "patch_edf_superset",
    },
    {
        "arg": "patch-asv-ps-range",
        "desc": "Unlock ASV/ASVAuto pressure support range.",
        "default": True,
        "function": "asv_pressure_support_range",
    },
    {
        "arg": "patch-therapy-screen",
        "desc": "Show additional respiratory statistics in compatible therapy modes.",
        "default": True,
        "function": "therapy_screen",
    },
    {
        "arg": "patch-asv-backup-rate",
        "desc": "Add ASV/ASVAuto backup-rate suppression and control.",
        "default": True,
        "function": "asv_backup_rate",
    },
    {
        "arg": "patch-custom-settings",
        "desc": "Expose settings requested by active compiled payloads.",
        "default": True,
        "function": "enable_custom_settings",
    },
    {
        "arg": "patch-motor-nagscreen",
        "desc": "Remove \"Motor life exceeded\" nag screen.",
        "default": True,
        "function": "motor_nagscreen",
    },
    {
        "arg": "patch-rpc-permissions",
        "desc": "Enable or block selected RPC commands on configured VCID permissions.",
        "default": True,
        "function": "rpc_permissions",
    },
    {
        "arg": "patch-vid-spoof",
        "desc": "Install runtime MOP-based VariantIdentifier spoofing.",
        "default": True,
        "function": "vid_spoof",
    },
]


@dataclass(frozen=True)
class PatchOutcome:
    status: str = "OK"
    summary: str = None

    @classmethod
    def ok(cls, summary=None):
        return cls("OK", summary)

    @classmethod
    def warn(cls, summary):
        return cls("WARN", summary)

    @classmethod
    def skip(cls, summary):
        return cls("SKIP", summary)


class TeeStream:
    def __init__(self, *streams):
        self.streams = streams

    def write(self, data):
        for stream in self.streams:
            stream.write(data)
        return len(data)

    def flush(self):
        for stream in self.streams:
            stream.flush()


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
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="Show detailed patch output.")
    parser.add_argument("--log-file",
                        help="Append a verbose patching transcript to this file.")
    parser.add_argument(
        "--rpc-permission",
        action="append",
        type=parse_rpc_permission,
        metavar="METHOD:VCID:BOOL",
        default=None,
        help="Set METHOD permission on VCID; repeatable. Overrides the built-in rule for the same pair.",
    )
    return parser


def print_patch_output(text, stream=None):
    for line in text.rstrip("\n").splitlines():
        if line.startswith("  "):
            line = line[2:]
        print(("  " + line) if line else "", file=stream)


def apply_reported_patch(option, method, args, detail_log=None):
    output = io.StringIO()
    try:
        with redirect_stdout(output):
            outcome = method()
        if not isinstance(outcome, PatchOutcome):
            outcome = PatchOutcome.ok()
    except Exception as exc:
        print("PATCH: %s [ERROR]" % option)
        stream = None if args.verbose or detail_log is None else detail_log
        print_patch_output(output.getvalue(), stream)
        print("  " + str(exc))
        raise

    print("PATCH: %s [%s]" % (option, outcome.status))
    if args.verbose:
        print_patch_output(output.getvalue())
    elif detail_log is not None:
        print_patch_output(output.getvalue(), detail_log)
    if outcome.status in ("WARN", "SKIP") and outcome.summary:
        print("  " + outcome.summary)


def run_patcher(args, detail_log=None):

    with open(args.INFILE, "rb") as f:
        asf = S11Firmware(f)

    if args.OPERATION == "INFO":
        return 0

    rpc_permissions = {
        method: dict(vcid_permissions)
        for method, vcid_permissions in DEFAULT_RPC_PERMISSIONS.items()
    }
    for method, vcid, allowed in args.rpc_permission or ():
        rpc_permissions.setdefault(method, {})[vcid] = allowed

    patches = S11FirmwarePatches(asf, rpc_permissions=rpc_permissions)

    print("\n=== Patches")
    for patch in PATCH_LIST:
        enabled = getattr(args, patch["arg"].replace("-", "_"))
        if enabled is None:
            if args.all_patches is None:
                enabled = patch["default"]
            else:
                enabled = args.all_patches
        if enabled:
            apply_reported_patch(
                patch["arg"], getattr(patches, patch["function"]),
                args, detail_log,
            )

    # Feature patches queue controls; resolve them before building the shared
    # mode-change dispatcher that refreshes their visibility.
    def finalize_payloads():
        patches.finalize_custom_settings()
        return patches.patch_mop_callback_dispatcher()

    print("\n=== Finalization")
    apply_reported_patch(
        "patch-mop-callback-dispatcher", finalize_payloads,
        args, detail_log,
    )

    output = io.StringIO()
    try:
        with redirect_stdout(output):
            asf.fix_crcs()
            asf.write_output(args.OUTFILE, args.overwrite)
    except Exception:
        stream = None if args.verbose or detail_log is None else detail_log
        print(output.getvalue(), end="", file=stream)
        raise

    if args.verbose:
        print(output.getvalue(), end="")
    elif detail_log is not None:
        print(output.getvalue(), end="", file=detail_log)
    return 0


def main(argv=None):
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    if args.log_file is None:
        return run_patcher(args)

    with open(args.log_file, "a", encoding="utf-8") as detail_log:
        with redirect_stdout(TeeStream(sys.stdout, detail_log)):
            return run_patcher(args, detail_log)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except BrokenPipeError:
        raise SystemExit(1)
    except Exception as exc:
        print("error: %s" % exc, file=sys.stderr)
        raise SystemExit(2)

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
import binascii
import datetime
import fnmatch
import io
import json
import os
import re
import struct
import subprocess
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


class PatchVersionUnavailable(ValueError):
    def __init__(self, status, summary):
        super().__init__(summary)
        self.status = status


def crc16_ccitt_false(data, crc=0xFFFF):
    return binascii.crc_hqx(data, crc)


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
        raise argparse.ArgumentTypeError(
            "expected METHOD:VCID:BOOL or DATAITEM:FLAG:BOOL"
        )
    target, selector, enabled_text = parts
    try:
        enabled = str2bool(enabled_text)
    except argparse.ArgumentTypeError as exc:
        raise argparse.ArgumentTypeError(
            "invalid RPC permission %r: %s" % (value, exc)
        ) from None

    flag = selector.upper()
    if flag in RPC_DATAITEM_PERMISSION_FLAGS:
        if re.fullmatch(r"(?:0[xX][0-9a-fA-F]+|[0-9]+)", target):
            target = parse_u16(target)
        return "dataitem", target, flag, enabled

    try:
        vcid = parse_u16(selector)
    except argparse.ArgumentTypeError:
        raise argparse.ArgumentTypeError(
            "invalid RPC permission %r: selector must be a VCID, RPC, or RPW" %
            value
        ) from None
    return "method", target, vcid, enabled


def airbreak_version():
    """Return the release label embedded in AirbreakInfo."""
    override = os.environ.get("AIRBREAK_VERSION")
    if override:
        return override

    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    try:
        return subprocess.check_output(["git", "-C", repo, "describe", "--tags", "--always", "--dirty"], stderr=subprocess.DEVNULL, universal_newlines=True).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def airbreak_build_timestamp():
    """Return the UTC time embedded in the patched image manifest."""
    epoch = os.environ.get("SOURCE_DATE_EPOCH")
    if epoch is None:
        stamp = datetime.datetime.now(datetime.timezone.utc)
    else:
        stamp = datetime.datetime.fromtimestamp(
            int(epoch), datetime.timezone.utc
        )
    return stamp.isoformat(timespec="seconds").replace("+00:00", "Z")


def airbreak_patch_name(name):
    """Return a patch name without the CLI switch prefix."""
    return name[6:] if name.startswith("patch-") else name


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

# Method permissions set by patch-rpc-permissions. The outer key is the method,
# and each nested map assigns the permission state for one or more VCIDs.
DEFAULT_RPC_METHOD_PERMISSIONS = {
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

# DataItem permissions set by patch-rpc-permissions. Targets may be long names,
# short tags, or numeric var IDs. Unspecified descriptor flags are preserved.
DEFAULT_RPC_DATAITEM_PERMISSIONS = {
    "WUP": {
        "RPC": True,
        "RPW": True,
    },
}

DATAITEM_FLAG_MASKS = {
    "ACT": 0x0001,
    "VIS": 0x0002,
    "MOD": 0x0004,
    "SGN": 0x0008,
    "INH": 0x0010,
    "VAL": 0x0020,
    "ULK": 0x0040,
    "RAW": 0x0080,
    "MON": 0x0100,
    "RPC": 0x0200,
    "RPW": 0x0400,
    "PST": 0x0800,
}
RPC_DATAITEM_PERMISSION_FLAGS = frozenset(("RPC", "RPW"))

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
# locate the moving method->command-id table; patch defaults live above
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
    "LearnMode",
    "LearnTargets*",
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

AS11_RPC_DISPATCHER_PAYLOAD = "as11_rpc_dispatcher"

AS11_ASV_BACKUP_RATE_PAYLOAD = "as11_asv_backup_rate"

AS11_CUSTOM_SETTINGS_PAYLOAD = "as11_custom_settings"

AS11_HEADER_CLOCK_PAYLOAD = "as11_header_clock"

AS11_AIRBREAK_INFO_PAYLOAD = "as11_airbreak_info"


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
        self.crcfunc = crc16_ccitt_false
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

        bad_crcs = []
        for name, off, size in self.blocks():
            crc_off = off + size - 2
            stored = (self.fw[crc_off] << 8) | self.fw[crc_off + 1]
            computed = self.crcfunc(bytes(self.fw[off:crc_off]))
            if stored != computed:
                bad_crcs.append("%s stored=0x%04X computed=0x%04X" %
                                (name, stored, computed))
        if bad_crcs:
            raise ValueError("invalid input firmware CRC: %s" %
                             ", ".join(bad_crcs))

    def blocks(self):
        return (
            ("FGBL", self.FGBL_OFF, self.FGBL_SIZE),
            ("CONF", self.CONF_OFF, self.CONF_SIZE),
            ("APPL", self.APPL_OFF, self.APPL_SIZE),
        )

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
        return bytes(self.fw[off:off + length]).decode("ascii", errors="replace").split("\x00")[0]

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

    def patch_exact(self, address, before, after):
        """Replace one fixed-size site when its current bytes are known."""
        before = bytes.fromhex(before) if isinstance(before, str) else bytes(before)
        after = bytes.fromhex(after) if isinstance(after, str) else bytes(after)
        off = address - self.FLASH_BASE
        current = bytes(self.fw[off:off + len(before)])
        if current not in (before, after):
            raise ValueError(
                "patch site 0x%08X contains %s, expected %s" %
                (address, current.hex(), before.hex())
            )
        if current == before:
            self.fw[off:off + len(after)] = after
            return True
        return False

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

    def var_name(self, vid):
        return self.appl_nodes.get(vid, "") or self.short_names.get(vid, "")

    def descriptor(self, array, idx):
        spec = self.arrays[array]
        if idx < 0 or idx >= spec["count"]:
            raise IndexError("%s[%d] outside table" % (array, idx))
        off = spec["base"] + idx * spec["stride"]
        vid = spec["id_base"] + idx
        short_name = self.short_names.get(vid, "")
        long_name = self.appl_nodes.get(vid, "")
        row = {
            "array": array,
            "index": idx,
            "offset": off,
            "address": self.off_to_addr(off),
            "var_id": vid,
            "short_name": short_name,
            "long_name": long_name,
            "name": long_name or short_name,
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

    def find_descriptors(self, identifier, arrays=("g1", "g2", "g3", "g5")):
        rows = []
        if isinstance(identifier, int):
            for array in arrays:
                spec = self.arrays[array]
                idx = identifier - spec["id_base"]
                if 0 <= idx < spec["count"]:
                    rows.append(self.descriptor(array, idx))
        else:
            wanted_short = identifier.upper().lstrip("_")
            for array in arrays:
                for row in self.iter_descriptors(array):
                    short_name = row["short_name"]
                    if ((short_name and short_name.upper().lstrip("_") == wanted_short) or
                            row["long_name"] == identifier):
                        rows.append(row)
        return rows

    def update_descriptor_flags(self, row, values):
        """Set selected DataItem flags while preserving all other bits."""
        flags = self.u16(row["offset"])
        updated = flags
        for name, enabled in values.items():
            flag = name.upper()
            if flag not in DATAITEM_FLAG_MASKS:
                raise ValueError("unknown DataItem flag %s" % name)
            mask = DATAITEM_FLAG_MASKS[flag]
            updated = updated | mask if enabled else updated & ~mask
        if updated != flags:
            self.write_u16(row["offset"], updated)
        return flags, updated

    def _descriptor_field_layout(self, row, fields):
        layout = self.DESCRIPTOR_FIELDS[row["array"]]
        unknown = set(fields) - set(layout)
        if unknown:
            raise ValueError(
                "unknown %s descriptor field(s): %s" %
                (row["array"], ", ".join(sorted(unknown)))
            )
        return [(field,) + layout[field] for field in fields]

    def write_descriptor_fields(self, row, fields):
        """Update named fields in an existing DataItem descriptor."""
        writers = {
            1: self.write_u8,
            2: self.write_u16,
            4: self.write_u32,
        }
        for field, field_off, width in self._descriptor_field_layout(row, fields):
            writers[width](row["offset"] + field_off, fields[field])

    def read_descriptor_fields(self, row, fields):
        """Read named fields from an existing DataItem descriptor."""
        readers = {
            1: self.u8,
            2: self.u16,
            4: self.u32,
        }
        return {
            field: readers[width](row["offset"] + field_off)
            for field, field_off, width in self._descriptor_field_layout(row, fields)
        }

    def enum_rpc_values(self, row, table):
        """Return enabled RPC symbols from a final g[5] descriptor."""
        if row["array"] != "g5":
            raise ValueError("enum RPC values require a g5 descriptor")

        table_off = self.ptr_to_off(table["rpc_enum_symbols"])
        symbols = {}
        for index in range(table["rpc_enum_symbol_count"]):
            off = table_off + index * 12
            enum_index = self.u32(off)
            raw_value = self.u32(off + 4)
            if enum_index == row["index"]:
                symbol = self.string_at_ptr(self.u32(off + 8))
                if symbol is not None:
                    symbols[raw_value] = symbol

        enabled = [
            option for option in range(row["n_options"])
            if option >= 32 or row["option_mask"] & (1 << option)
        ]
        missing = [option for option in enabled if option not in symbols]
        if missing:
            raise ValueError(
                "missing RPC enum symbols for %s option(s) %s" %
                (row["short_name"], ", ".join(map(str, missing)))
            )
        return [symbols[option] for option in enabled]

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
            "stock_feature": "Reminders",
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

    def __init__(self, asf, rpc_method_permissions=None, rpc_dataitem_permissions=None):
        self.asf = asf
        self._init_compiled_payloads()
        self.mop_callback_handlers = []
        self.mop_callback_handler_seen = set()
        self.mop_callback_dispatcher_context = None
        self.mop_callback_dispatcher_outcome = None
        self.rpc_objects = []
        self.rpc_object_seen = set()
        self.rpc_dispatcher_context = None
        self.rpc_dispatcher_outcome = None
        self.custom_settings_enabled = False
        self.custom_setting_claims = {}
        self.custom_menu_entries = []
        self.custom_setting_bindings = []
        self.airbreak_info_enabled = False
        self.patch_outcomes = {}
        self.claimed_dataitems = {}
        self.disabled_stock_features = set()
        self.rpc_method_permission_rules = DEFAULT_RPC_METHOD_PERMISSIONS if rpc_method_permissions is None else rpc_method_permissions
        self.rpc_dataitem_permission_rules = DEFAULT_RPC_DATAITEM_PERMISSIONS if rpc_dataitem_permissions is None else rpc_dataitem_permissions

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

    def _patch_version_data(self, feature, ver=None):
        """Return version data or report why this patch cannot run."""
        ver = self._payload_version_key() if ver is None else ver
        version = AS11_PATCH_VERSIONS.get(ver)
        if version is None or feature not in version:
            raise PatchVersionUnavailable(
                "WARN", "%s is not ported to APPX %s" % (feature, ver)
            )
        data = version[feature]
        if data is None:
            raise PatchVersionUnavailable(
                "SKIP", "%s does not apply to APPX %s" % (feature, ver)
            )
        return data

    def record_patch_outcome(self, name, outcome):
        """Record the current status of one enabled patch."""
        self.patch_outcomes[name] = outcome.status

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
        outcome = self._prepare_mop_callback_dispatcher()
        if outcome.status != "OK":
            summary = "MOP callback dispatcher unavailable"
            if outcome.summary:
                summary += ": " + outcome.summary
            return PatchOutcome.skip(summary)

        handler = int(handler) | 1
        if handler in self.mop_callback_handler_seen:
            return PatchOutcome.ok()
        self.mop_callback_handler_seen.add(handler)
        self.mop_callback_handlers.append(handler)
        print("  MOP callback handler: %s at 0x%08X" % (name, handler))
        return PatchOutcome.ok()

    def patch_mop_callback_dispatcher(self):
        """Install the shared EnumDataItem writeback dispatcher."""
        if (self.mop_callback_dispatcher_outcome is not None and
                self.mop_callback_dispatcher_outcome.status != "OK"):
            return self.mop_callback_dispatcher_outcome
        if not self.mop_callback_handlers:
            return PatchOutcome.skip("no callback handlers registered")

        outcome = self._prepare_mop_callback_dispatcher()
        if outcome.status != "OK":
            return outcome

        context = self.mop_callback_dispatcher_context
        if len(self.mop_callback_handlers) > context["handler_capacity"]:
            raise ValueError(
                "mop_callback_dispatcher: too many handlers (%d; capacity %d)" %
                (len(self.mop_callback_handlers), context["handler_capacity"])
            )

        data = context["data"]
        handler_table = context["handler_table"]
        original = context["original"]
        start = context["start"]
        ver = context["version"]

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
        self.asf.patch_exact(
            context["vtable_slot"], struct.pack("<I", original),
            struct.pack("<I", start | 1),
        )

        print(
            "  MOP callback dispatcher: build/%s_%s.bin (%dB) at 0x%08X" %
            (AS11_MOP_CALLBACK_DISPATCHER_PAYLOAD, ver, len(data), flash)
        )
        print(
            "  EnumDataItem writeback: 0x%08X -> 0x%08X" %
            (original, start | 1)
        )
        return PatchOutcome.ok()

    def _prepare_mop_callback_dispatcher(self):
        """Resolve and validate the dispatcher without modifying the image."""
        if self.mop_callback_dispatcher_outcome is not None:
            return self.mop_callback_dispatcher_outcome

        ver = self._payload_version_key()
        try:
            anchors = self._patch_version_data(
                "mop_callback_dispatcher", ver
            )
        except PatchVersionUnavailable as exc:
            self.mop_callback_dispatcher_outcome = PatchOutcome(
                exc.status, str(exc)
            )
            return self.mop_callback_dispatcher_outcome

        data, _ = self._load_versioned_bin(
            AS11_MOP_CALLBACK_DISPATCHER_PAYLOAD, required=True
        )
        elf_path = self._versioned_artifact_path(
            AS11_MOP_CALLBACK_DISPATCHER_PAYLOAD, "elf", ver
        )
        start = self._elf_symbol_addr(elf_path, "start")
        handler_table = self._elf_symbol_addr(
            elf_path, "mop_callback_handler_table"
        )
        handler_table_size = self._elf_symbol_size(
            elf_path, "mop_callback_handler_table"
        )
        if handler_table_size < 8 or handler_table_size % 4:
            raise ValueError(
                "mop_callback_dispatcher: invalid handler table size %d" %
                handler_table_size
            )

        original = anchors["writeback"] | 1
        vtable_slot = anchors["vtable_slot"]
        vtable_off = self.asf.ptr_to_off(vtable_slot)
        current = self.asf.u32(vtable_off)
        if current not in (original, start | 1):
            raise ValueError(
                "mop_callback_dispatcher: vtable slot contains 0x%08X, "
                "expected 0x%08X" % (current, original)
            )

        self.mop_callback_dispatcher_context = {
            "data": data,
            "handler_capacity": handler_table_size // 4 - 2,
            "handler_table": handler_table,
            "original": original,
            "start": start,
            "version": ver,
            "vtable_slot": vtable_slot,
        }
        self.mop_callback_dispatcher_outcome = PatchOutcome.ok()
        return self.mop_callback_dispatcher_outcome

    def rpc_object_register(self, rpc_object, name):
        """Register one rpc_object_t with the shared named-object dispatcher."""
        outcome = self._prepare_rpc_dispatcher()
        if outcome.status != "OK":
            summary = "RPC dispatcher unavailable"
            if outcome.summary:
                summary += ": " + outcome.summary
            return PatchOutcome.skip(summary)

        rpc_object = int(rpc_object)
        if rpc_object in self.rpc_object_seen:
            return PatchOutcome.ok()
        self.rpc_object_seen.add(rpc_object)
        self.rpc_objects.append(rpc_object)
        print("  RPC object: %s at 0x%08X" % (name, rpc_object))
        return PatchOutcome.ok()

    @staticmethod
    def _rel32_target(address, value):
        displacement = value
        if displacement & 0x80000000:
            displacement -= 0x100000000
        return (address + displacement) & 0xFFFFFFFF

    def patch_rpc_dispatcher(self):
        """Install the shared JSON RPC named-object dispatcher."""
        if self.rpc_dispatcher_outcome is not None and self.rpc_dispatcher_outcome.status != "OK":
            return self.rpc_dispatcher_outcome
        if not self.rpc_objects:
            return PatchOutcome.skip("no RPC objects registered")

        outcome = self._prepare_rpc_dispatcher()
        if outcome.status != "OK":
            return outcome

        context = self.rpc_dispatcher_context
        data = context["data"]
        object_table = context["object_table"]
        object_capacity = context["object_capacity"]
        init_entry = context["init_entry"]
        original_entry = context["original_entry"]
        start = context["start"]
        ver = context["version"]
        if len(self.rpc_objects) > object_capacity:
            raise ValueError(
                "rpc_dispatcher: too many objects (%d; capacity %d)" %
                (len(self.rpc_objects), object_capacity)
            )

        flash, _off = self._inject_payload(AS11_RPC_DISPATCHER_PAYLOAD, data)
        table_off = object_table - self.asf.FLASH_BASE
        for index, rpc_object in enumerate(self.rpc_objects):
            self.asf.write_u32(table_off + index * 4, rpc_object)
        self.asf.write_u32(table_off + len(self.rpc_objects) * 4, 0xFFFFFFFF)

        replacement_entry = ((start | 1) - init_entry) & 0xFFFFFFFF
        self.asf.patch_exact(init_entry, struct.pack("<I", original_entry), struct.pack("<I", replacement_entry))
        print("  RPC dispatcher: build/%s_%s.bin (%dB) at 0x%08X" % (AS11_RPC_DISPATCHER_PAYLOAD, ver, len(data), flash))
        return PatchOutcome.ok()

    def _prepare_rpc_dispatcher(self):
        """Resolve and validate the dispatcher without modifying the image."""
        if self.rpc_dispatcher_outcome is not None:
            return self.rpc_dispatcher_outcome

        ver = self._payload_version_key()
        try:
            anchors = self._patch_version_data("rpc_dispatcher", ver)
        except PatchVersionUnavailable as exc:
            self.rpc_dispatcher_outcome = PatchOutcome(exc.status, str(exc))
            return self.rpc_dispatcher_outcome

        data, _ = self._load_versioned_bin(AS11_RPC_DISPATCHER_PAYLOAD, required=True)
        elf_path = self._versioned_artifact_path(AS11_RPC_DISPATCHER_PAYLOAD, "elf", ver)
        start = self._elf_symbol_addr(elf_path, "start")
        registry_ctor = self._elf_symbol_addr(elf_path, "rpc_profile_json_formatter_registry_ctor")
        object_table = self._elf_symbol_addr(elf_path, "rpc_object_table")
        object_table_size = self._elf_symbol_size(elf_path, "rpc_object_table")
        init_entry = anchors["init_entry"]
        init_off = self.asf.ptr_to_off(init_entry)
        original_entry = self.asf.u32(init_off)
        original_target = self._rel32_target(init_entry, original_entry)
        if original_target != (registry_ctor | 1):
            raise ValueError(
                "RPC object initializer names 0x%08X, expected 0x%08X" %
                (original_target, registry_ctor | 1)
            )

        self.rpc_dispatcher_context = {
            "data": data,
            "init_entry": init_entry,
            "object_capacity": object_table_size // 4 - 1,
            "object_table": object_table,
            "original_entry": original_entry,
            "start": start,
            "version": ver,
        }
        self.rpc_dispatcher_outcome = PatchOutcome.ok()
        return self.rpc_dispatcher_outcome

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

    def custom_setting_claim(self, name, owner, custom_name=None):
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
            "custom_name": custom_name,
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

    def _custom_settings_reclaim_reminders(self, layout):
        """Detach the stock Reminders consumers from its persistent fields."""
        scheduler_call, scheduler_target = layout["scheduler_call"]
        scheduler_off = self.asf.ptr_to_off(scheduler_call)
        if self.asf.read_thumb2_bl_target(scheduler_off) != scheduler_target:
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
            return PatchOutcome.skip("custom settings disabled")
        if not (self.custom_setting_claims or self.custom_menu_entries or
                self.custom_setting_bindings):
            return PatchOutcome.skip("no active features")

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
            rows = self.asf.find_descriptors(setting)
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
            self._patch_version_data("custom_settings", ver)
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
                return PatchOutcome.skip("compiled payload unavailable")

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
            if self.asf.read_thumb2_bl_target(call_off) != scroller_ctor:
                raise ValueError(
                    "custom settings: clinical settings scroller does not match"
                )
            menu_symbols["call_off"] = call_off
            menu_payload = data

            if any(
                    request["mode_mask"] != 0xFFFF
                    for request in self.custom_menu_entries):
                outcome = self.mop_callback_register_handler(
                    menu_symbols["start"], "custom_settings"
                )
                if outcome.status != "OK":
                    return outcome

        # Apply the prepared payload, descriptor, ABI, and reclaim changes.
        menu_flash = None
        if menu_payload is not None:
            menu_flash, _off = self._inject_payload(
                AS11_CUSTOM_SETTINGS_PAYLOAD, menu_payload
            )

        # Recast claimed persistent DataItems for their new feature roles.
        menu_metadata = {
            request["setting"]: {
                "section": request["section"],
                "mode_mask": request["mode_mask"],
            }
            for request in self.custom_menu_entries
        }
        for setting, claim in self.custom_setting_claims.items():
            if claim["definition"] is not None:
                self.asf.write_descriptor_fields(
                    setting_rows[setting], claim["definition"]
                )

            stock_row = setting_rows[setting]
            row = self.asf.descriptor(stock_row["array"], stock_row["index"])
            custom_name = claim["custom_name"]
            if custom_name:
                metadata = {
                    "name": custom_name,
                    "owner": airbreak_patch_name(claim["owner"]),
                }
                if stock_row["long_name"]:
                    metadata["stock"] = stock_row["long_name"]
                menu = menu_metadata.get(setting)
                if menu is not None:
                    metadata["menu"] = {
                        "section": menu["section"],
                        "modes": [
                            profile
                            for bit, _prefix, profile, _supported
                            in THERAPY_MODES
                            if menu["mode_mask"] & (1 << bit)
                        ],
                    }
                if row["array"] == "g5":
                    metadata["enum"] = self.asf.enum_rpc_values(row, layout)
                self.claimed_dataitems["_" + row["short_name"]] = metadata

        for pool in pools:
            stock_feature = self.CUSTOM_SETTING_RECLAIM_POOLS[pool].get("stock_feature")
            if stock_feature:
                self.disabled_stock_features.add(stock_feature)

        # Compiled feature payloads receive resolved var_ids through explicit
        # 16-bit ABI slots, keeping descriptor indexes out of their code.
        for setting, abi_slot in self.custom_setting_bindings:
            self.asf.patch_exact(
                abi_slot, b"\xFF\xFF",
                struct.pack("<H", setting_rows[setting]["var_id"]),
            )

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
            rows = self.asf.find_descriptors(target, ("g2", "g5"))
            label = "0x%04X" % target if isinstance(target, int) else str(target)
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
        lnc_rows = self.asf.find_descriptors("LanguageConfiguration", ("g3",))
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
            descriptors = self.asf.find_descriptors(tag, ("g2",))
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
        pht_rows = self.asf.find_descriptors("PHT", ("g2",))
        phi_rows = self.asf.find_descriptors("PHI", ("g2",))
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

    def fix_st_respiratory_rate_range(self):
        """Hydrate the stripped ST backup-rate default and lower bound."""
        rows = self.asf.find_descriptors("ST-SetRespiratoryRate", ("g2",))
        row = rows[0]
        current = self.asf.read_descriptor_fields(row, ("default", "min"))
        desired = {"default": 50, "min": 25}
        if current == desired:
            print("Patching ST respiratory-rate range... already hydrated")
            return 0

        # Official S/ST firmware stores 5..50 bpm with a 10 bpm default.
        self.asf.write_descriptor_fields(row, desired)
        print("Patching ST respiratory-rate range... default=10 range=5..50 step=1")
        return 1

    def unlock_features(self):
        """Unlock therapy modes and related GUI settings at descriptor level."""
        if any(prefix == "ST" and supported
               for _bit, prefix, _profile, supported in THERAPY_MODES):
            self.fix_st_respiratory_rate_range()
        if any(prefix == "iVAPS" and supported
               for _bit, prefix, _profile, supported in THERAPY_MODES):
            self.fix_ivaps_patient_height_range()

        feature_setting_offsets = set()
        for name in self.asf.find_rpc_feature_setting_names():
            for row in self.asf.find_descriptors(name, ("g5",)):
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
        mode_rows = [
            row
            for name in MODE_SELECTOR_NAMES
            for row in self.asf.find_descriptors(name, ("g5",))
        ]
        for row in mode_rows:
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
            rows = self.asf.find_descriptors(name, ("g5",))
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
        blacklisted_nodes = tuple(
            profile for _bit, _prefix, profile, supported in THERAPY_MODES if not supported
        ) + BLACKLISTED_FEATURE_PROFILE_NODE_NAMES
        blacklisted_nodes = set(blacklisted_nodes)

        rpc_nodes = self.asf.rpc_json_index()[1]
        nodes = {
            name: node_id for name, node_id in rpc_nodes.items()
            if (name in mode_profile_nodes or
                (name.endswith("Feature") and name not in blacklisted_nodes))
        }
        if not nodes:
            raise ValueError("metadata: no RPC JSON profile nodes resolved")

        hidden_nodes = {
            name: node_id for name, node_id in rpc_nodes.items()
            if name in blacklisted_nodes
        }
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
            found = self.asf.find_descriptors(max_name, ("g2",))
            if len(found) != 1:
                raise ValueError("asv_pressure_support_range: expected one %s descriptor, found %d" %
                                 (max_name, len(found)))
            max_row = found[0]
            found = self.asf.find_descriptors(min_name, ("g2",))
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
        ver = self._payload_version_key()
        version = self._patch_version_data("asv_backup_rate", ver)
        data, _ = self._load_versioned_bin(AS11_ASV_BACKUP_RATE_PAYLOAD)
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
        vtable_update_off = self.asf.ptr_to_off(version["vtable_slot"])
        if self.asf.u32(vtable_update_off) != original_ptr:
            raise ValueError(
                "asv_backup_rate: ASV update vtable slot does not match"
            )

        flash, _off = self._inject_payload(AS11_ASV_BACKUP_RATE_PAYLOAD, data)
        # Replace the ASV update vtable entry; the payload calls the original
        # implementation through its versioned stub after applying the gate.
        self.asf.write_u32(vtable_update_off, start | 1)
        # Without custom-settings finalization, the untouched 0xFFFF slot keeps
        # backup-rate suppression active unconditionally.
        backup_rate_setting = self.custom_setting_claim("RIF", "patch-asv-backup-rate", custom_name="ASVBackupRateEnable")
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

    def timezone_write(self):
        """Keep time-zone writes available after summary history exists."""
        version = self._patch_version_data("timezone_write")

        # r4 >> 31 is the firmware's (FTS == 0) boolean. At metadata_gate:
        #   e10f       lsrs  r1, r4, #31  ->  0121      movs r1, #1
        # At data_rule_gate, r6/r7 holds TZG. Replace:
        #   17ead47f   tst.w r7, r4, lsr #31  ->  002f00bf  cmp r7, #0; nop
        #   16ead47f   tst.w r6, r4, lsr #31  ->  002e00bf  cmp r6, #0; nop
        # This preserves the TZG test while removing only the FTS == 0 term.
        # menu_warning_action replaces its version-specific BL with two NOPs.
        changed = []
        for name in ("metadata_gate", "data_rule_gate", "menu_warning_action"):
            site = version[name]
            if self.asf.patch_exact(
                    site["address"], site["before"], site["after"]):
                changed.append(name)

        if changed:
            return PatchOutcome.ok("enabled: %s" % ", ".join(changed))
        return PatchOutcome.ok("already enabled")

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
        image = bytes(self.asf.fw)

        # Every valid table starts with a known VCID. Let bytes.find() locate
        # those sparse candidates before decoding the complete table row.
        candidate_offsets = set()
        for vcid in known:
            needle = struct.pack("<H", vcid)
            off = image.find(needle, self.asf.APPL_OFF, appl_end)
            while off >= 0:
                if off % 2 == 0:
                    candidate_offsets.add(off)
                off = image.find(needle, off + 1, appl_end)

        candidates = []
        row_format = "<%dH" % flag_count
        for off in sorted(candidate_offsets):
            if off + flag_count * 2 > appl_end:
                continue
            vcids = struct.unpack_from(row_format, image, off)
            if len(set(vcids)) != flag_count:
                continue
            if any(vcid not in known for vcid in vcids):
                continue
            after = image[off + flag_count * 2:off + flag_count * 2 + 64]
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

    def rpc_permissions(self):
        if (not self.rpc_method_permission_rules and
                not self.rpc_dataitem_permission_rules):
            return PatchOutcome.skip("no permission rules configured")

        # Resolve both permission layers before modifying the image.
        method_plan = []
        method_rows_missing = []
        scanned = 0
        vcids = ()
        vcid_table_off = None
        if self.rpc_method_permission_rules:
            dispatch_rows = self.find_rpc_dispatch_table()[1]
            method_cmds = {name: cmd for name, cmd, _off in dispatch_rows}
            base, stride = self.find_rpc_permission_table()
            rows, scanned = self.rpc_permission_rows(base, stride)
            vcid_table_off, vcids = self.find_rpc_permission_vcid_table(stride - 1)
            vcid_columns = {vcid: idx + 1 for idx, vcid in enumerate(vcids)}

            for method, vcid_permissions in self.rpc_method_permission_rules.items():
                if method not in method_cmds:
                    raise ValueError("rpc_permissions: RPC method %r not found" % method)
                cmd = method_cmds[method]
                off = rows.get(cmd)
                if off is None:
                    method_rows_missing.append((method, cmd))
                    continue
                for vcid, allowed in vcid_permissions.items():
                    if vcid not in vcid_columns:
                        raise ValueError("rpc_permissions: VCID 0x%04X not present in permission table" % vcid)
                    method_plan.append((method, cmd, vcid, off + vcid_columns[vcid], allowed))

        dataitem_plan = []
        for target, flag_permissions in self.rpc_dataitem_permission_rules.items():
            rows = self.asf.find_descriptors(target)
            if not rows:
                raise ValueError("rpc_permissions: DataItem %r not found" % target)
            row = rows[0]
            for flag, allowed in flag_permissions.items():
                if flag.upper() not in RPC_DATAITEM_PERMISSION_FLAGS:
                    raise ValueError("rpc_permissions: DataItem permission must be RPC or RPW")
            dataitem_plan.append((target, row, flag_permissions))

        enabled = 0
        blocked = 0
        already = 0
        if self.rpc_method_permission_rules:
            print("Patching RPC method permissions... table 0x%05X, VCIDs %s" % (
                vcid_table_off,
                ", ".join("0x%04X" % vcid for vcid in vcids),
            ))
            for method, cmd in method_rows_missing:
                print("  %s -> id %d: permission row missing" % (method, cmd))
            for method, cmd, vcid, flag_off, allowed in method_plan:
                value = int(allowed)
                action = "enabled" if allowed else "blocked"
                if self.asf.u8(flag_off) != value:
                    self.asf.write_u8(flag_off, value)
                    print("  %s -> id %d VCID 0x%04X: %s" %
                          (method, cmd, vcid, action))
                    if allowed:
                        enabled += 1
                    else:
                        blocked += 1
                else:
                    print("  %s -> id %d VCID 0x%04X: already %s" %
                          (method, cmd, vcid, action))
                    already += 1
            print("Patching RPC method permissions... %d enabled, %d blocked, "
                  "%d already set, %d missing (%d entries scanned)" %
                  (enabled, blocked, already, len(method_rows_missing), scanned))

        dataitems_changed = 0
        dataitems_already = 0
        if dataitem_plan:
            print("Patching RPC DataItem permissions...")
            for target, row, flag_permissions in dataitem_plan:
                old_flags, new_flags = self.asf.update_descriptor_flags(row, flag_permissions)
                values = ", ".join(
                    "%s=%d" % (flag.upper(), allowed)
                    for flag, allowed in flag_permissions.items()
                )
                print("  %s -> %s var 0x%04X: %s, flags 0x%04X -> 0x%04X" % (
                    target, row["array"], row["var_id"], values,
                    old_flags, new_flags,
                ))
                if old_flags == new_flags:
                    dataitems_already += 1
                else:
                    dataitems_changed += 1
            print("Patching RPC DataItem permissions... %d changed, %d already set" %
                  (dataitems_changed, dataitems_already))

        if method_rows_missing:
            return PatchOutcome.warn("%d permission rows missing" % len(method_rows_missing))
        return PatchOutcome.ok()

    def header_clock(self):
        """Show local time in the dashboard and therapy-screen title bar."""
        ver = self._payload_version_key()
        anchors = self._patch_version_data("header_clock", ver)
        data, _ = self._load_versioned_bin(AS11_HEADER_CLOCK_PAYLOAD)
        if data is None:
            return PatchOutcome.skip("compiled payload unavailable")

        elf_path = self._versioned_artifact_path(
            AS11_HEADER_CLOCK_PAYLOAD, "elf", ver
        )
        draw_wrapper = self._elf_symbol_addr(elf_path, "start")
        menu_draw_wrapper = self._elf_symbol_addr(elf_path, "header_clock_menu_label_draw")
        ctor_wrapper = self._elf_symbol_addr(
            elf_path, "header_clock_root_widget_ctor"
        )
        timer_callback = self._elf_symbol_addr(
            elf_path, "header_clock_timer_callback"
        )
        text_ids = self._elf_symbol_addr(
            elf_path, "header_clock_text_ids"
        )
        setting_slot = self._elf_symbol_addr(elf_path, "header_clock_var_id")
        stock_draw = self._elf_symbol_addr(
            elf_path, "GuiPaint_DrawLocalizedTextById"
        )
        stock_ctor = self._elf_symbol_addr(
            elf_path, "user_interface_root_widget_ctor"
        )
        stock_timer_callback = self._elf_symbol_addr(
            elf_path,
            "user_interface_root_widget_status_blink_timer_callback_adjustor",
        )

        draw_call = self.asf.ptr_to_off(anchors["draw_call"])
        menu_draw_call = (
            self.asf.ptr_to_off(anchors["menu_draw_call"])
            if "menu_draw_call" in anchors else None
        )
        ctor_call = self.asf.ptr_to_off(anchors["root_ctor_call"])
        timer_slot = self.asf.ptr_to_off(anchors["timer_callback_slot"])
        if self.asf.read_thumb2_bl_target(draw_call) != stock_draw:
            raise ValueError("header_clock: title-bar draw call does not match")
        if (menu_draw_call is not None and
                self.asf.read_thumb2_bl_target(menu_draw_call) != stock_draw):
            raise ValueError("header_clock: menu-label draw call does not match")
        if self.asf.read_thumb2_bl_target(ctor_call) != stock_ctor:
            raise ValueError("header_clock: root-widget constructor call does not match")
        if self.asf.u32(timer_slot) != (stock_timer_callback | 1):
            raise ValueError("header_clock: root-widget timer callback does not match")

        flash, _off = self._inject_payload(AS11_HEADER_CLOCK_PAYLOAD, data)
        text_ids_off = text_ids - self.asf.FLASH_BASE
        self.asf.write_u16(text_ids_off, anchors["home_text_id"])
        self.asf.write_u16(text_ids_off + 2, anchors["empty_text_id"])
        if menu_draw_call is not None:
            self.asf.write_u16(text_ids_off + 4, anchors["menu_text_id"])
        self.asf.write_thumb2_bl_target(draw_call, draw_wrapper)
        if menu_draw_call is not None:
            self.asf.write_thumb2_bl_target(menu_draw_call, menu_draw_wrapper)
        self.asf.write_thumb2_bl_target(ctor_call, ctor_wrapper)
        self.asf.write_u32(timer_slot, timer_callback | 1)

        if menu_draw_call is not None:
            setting = self.custom_setting_claim("RIM", "patch-header-clock", custom_name="HeaderClockEnable")
            self.custom_setting_define(setting, default_option=0)
            # TODO: Replace this label shim with framework-managed GUI string
            # redefinition once custom settings can reclaim localized text IDs.
            self.custom_menu_add("configuration", setting, anchors["menu_text_id"], 0xFFFF, "text_value")
            self.custom_setting_bind(setting, setting_slot)

        print(
            "Patching header clock... build/%s_%s.bin (%dB) at 0x%08X" %
            (AS11_HEADER_CLOCK_PAYLOAD, ver, len(data), flash)
        )
        return PatchOutcome.ok()

    def vid_spoof(self):
        """Set VID from MOP after the stock writeback completes."""
        data, ver = self._load_versioned_bin(AS11_VID_SPOOF_PAYLOAD)
        if data is None:
            return PatchOutcome.skip("compiled payload unavailable")
        elf_path = self._versioned_artifact_path(AS11_VID_SPOOF_PAYLOAD, "elf", ver)
        handler = self._elf_symbol_addr(elf_path, "start")
        outcome = self.mop_callback_register_handler(handler, "vid_spoof")
        if outcome.status != "OK":
            return outcome

        flash, _off = self._inject_payload(AS11_VID_SPOOF_PAYLOAD, data)
        print(
            "Patching runtime VID spoof... build/%s_%s.bin (%dB) at 0x%08X" %
            (AS11_VID_SPOOF_PAYLOAD, ver, len(data), flash)
        )
        return PatchOutcome.ok()

    def patch_edf_superset(self):
        """Expose the official S11 EDF schema superset."""
        try:
            from as11_edf_superset import patch_edf_superset
        except ImportError:
            script_dir = os.path.dirname(os.path.abspath(__file__))
            sys.path.insert(0, script_dir)
            from as11_edf_superset import patch_edf_superset

        patch_edf_superset(self.asf)

    def enable_airbreak_info(self):
        """Request the runtime AirbreakInfo RPC object."""
        self.airbreak_info_enabled = True

    def _airbreak_info_manifest(self):
        patch_statuses = {}
        for status in ("OK", "WARN", "SKIP"):
            names = sorted(
                airbreak_patch_name(name)
                for name, outcome in self.patch_outcomes.items()
                if outcome == status
            )
            if names:
                patch_statuses[status.lower()] = names

        return {
            "schema": 4,
            "version": airbreak_version(),
            "builtAt": airbreak_build_timestamp(),
            "patches": patch_statuses,
            "disabledFeatures": sorted(self.disabled_stock_features),
            "dataItems": dict(sorted(self.claimed_dataitems.items())),
        }

    def finalize_airbreak_info(self):
        """Install the AirbreakInfo RPC object with the completed manifest."""
        if not self.airbreak_info_enabled:
            return PatchOutcome.skip("AirbreakInfo disabled")

        ver = self._payload_version_key()
        data, _payload_ver = self._load_versioned_bin(AS11_AIRBREAK_INFO_PAYLOAD)
        if data is None:
            return PatchOutcome.skip("compiled payload unavailable")
        elf_path = self._versioned_artifact_path(AS11_AIRBREAK_INFO_PAYLOAD, "elf", ver)
        rpc_object = self._elf_symbol_addr(elf_path, "airbreak_info_rpc_object")
        manifest_addr = self._elf_symbol_addr(elf_path, "airbreak_info_json")
        manifest_capacity = self._elf_symbol_size(elf_path, "airbreak_info_json")
        manifest_length_addr = self._elf_symbol_addr(elf_path, "airbreak_info_json_length")

        manifest = json.dumps(
            self._airbreak_info_manifest(),
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("ascii")
        if len(manifest) > manifest_capacity:
            raise ValueError(
                "AirbreakInfo manifest is %d bytes; payload capacity is %d" %
                (len(manifest), manifest_capacity)
            )

        outcome = self.rpc_object_register(rpc_object, "AirbreakInfo")
        if outcome.status != "OK":
            return outcome

        flash, _off = self._inject_payload(AS11_AIRBREAK_INFO_PAYLOAD, data)
        self.asf.patch(manifest, addr=manifest_addr - self.asf.FLASH_BASE, verbose=False)
        self.asf.write_u32(manifest_length_addr - self.asf.FLASH_BASE, len(manifest))

        print("  AirbreakInfo: build/%s_%s.bin (%dB) at 0x%08X; manifest %dB" % (AS11_AIRBREAK_INFO_PAYLOAD, ver, len(data), flash, len(manifest)))
        return PatchOutcome.ok("Get AirbreakInfo")


PATCH_LIST = [
    {
        "arg": "patch-airbreak-info",
        "desc": "Expose Airbreak version and applied patch metadata through RPC Get.",
        "default": True,
        "function": "enable_airbreak_info",
    },
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
        "arg": "patch-header-clock",
        "desc": "Show local time in the dashboard and therapy-screen headers.",
        "default": True,
        "function": "header_clock",
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
        "desc": "Apply configured RPC method and DataItem permissions.",
        "default": True,
        "function": "rpc_permissions",
    },
    {
        "arg": "patch-timezone-write",
        "desc": "Allow time-zone changes after summary history exists.",
        "default": True,
        "function": "timezone_write",
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
        metavar="TARGET:VCID|FLAG:BOOL",
        default=None,
        help=("Set METHOD:VCID or DATAITEM:RPC|RPW permission; repeatable. "
              "Overrides the built-in rule for the same pair."),
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
    except PatchVersionUnavailable as exc:
        outcome = PatchOutcome(exc.status, str(exc))
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
    return outcome


def run_patcher(args, detail_log=None):

    with open(args.INFILE, "rb") as f:
        asf = S11Firmware(f)

    if args.OPERATION == "INFO":
        return 0

    rpc_method_permissions = {
        method: dict(vcid_permissions)
        for method, vcid_permissions in DEFAULT_RPC_METHOD_PERMISSIONS.items()
    }
    rpc_dataitem_permissions = {
        target: dict(flag_permissions)
        for target, flag_permissions in DEFAULT_RPC_DATAITEM_PERMISSIONS.items()
    }
    for kind, target, selector, allowed in args.rpc_permission or ():
        if kind == "method":
            rpc_method_permissions.setdefault(target, {})[selector] = allowed
        else:
            rpc_dataitem_permissions.setdefault(target, {})[selector] = allowed

    patches = S11FirmwarePatches(
        asf,
        rpc_method_permissions=rpc_method_permissions,
        rpc_dataitem_permissions=rpc_dataitem_permissions,
    )

    print("\n=== Patches")
    for patch in PATCH_LIST:
        enabled = getattr(args, patch["arg"].replace("-", "_"))
        if enabled is None:
            if args.all_patches is None:
                enabled = patch["default"]
            else:
                enabled = args.all_patches
        if enabled:
            outcome = apply_reported_patch(patch["arg"], getattr(patches, patch["function"]), args, detail_log)
            patches.record_patch_outcome(patch["arg"], outcome)


    print("\n=== Finalization")
    custom_settings_outcome = apply_reported_patch("finalize-custom-settings", patches.finalize_custom_settings, args, detail_log)
    if "patch-custom-settings" in patches.patch_outcomes:
        patches.record_patch_outcome("patch-custom-settings", custom_settings_outcome)

    mop_dispatcher_outcome = apply_reported_patch(
        "patch-mop-callback-dispatcher",
        patches.patch_mop_callback_dispatcher,
        args,
        detail_log,
    )
    if (patches.mop_callback_dispatcher_outcome is not None or
            patches.mop_callback_handlers):
        patches.record_patch_outcome(
            "patch-mop-callback-dispatcher", mop_dispatcher_outcome
        )

    if patches.airbreak_info_enabled:
        airbreak_info_outcome = apply_reported_patch("finalize-airbreak-info", patches.finalize_airbreak_info, args, detail_log)
        patches.record_patch_outcome("patch-airbreak-info", airbreak_info_outcome)

    apply_reported_patch("patch-rpc-dispatcher", patches.patch_rpc_dispatcher, args, detail_log)

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

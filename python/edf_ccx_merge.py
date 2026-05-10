#!/usr/bin/env python3
"""
Takes a firmware image (dumped from any SX567 variant - AutoSet, VAuto, CS PaceWave)
and patches the CCX region so all EDF file types contain the full universal signal set.

Supported input formats:
  - CCX-only (240KB / 0x3C000 bytes)
  - CMX (CCX+CDX combined, 0xFC000 bytes)
  - Full 1MB flash dump (BLX+CCX+CDX)
  - Any raw dump containing CCX at a detectable offset

"""

import struct
import sys
import hashlib
from pathlib import Path


ADDR_BASE = 0x08000000
CCX_OFFSET = 0x4000
CCX_SIZE = 0x3C000
CCX_BASE = ADDR_BASE + CCX_OFFSET
CCX_CRC_OFFSET = 0x3C000 - 2


# Free space is discovered dynamically, but must be before 0x10500 (locale tables)
FREE_SPACE_LIMIT = 0x10500


FULL_FLASH_SIZE = 0x100000  # 1MB
ERASED = 0xFF


# BRP.edf signals: [name, var_id, samples_per_60s_record]
BRP_SIGNALS = [
    ("Flow.40ms",       0x006B, 1500),  # 25 Hz
    ("Press.40ms",      0x0038, 1500),
    ("TrigCycEvt.40ms", 0x0244, 1500),
    ("Crc16",           0x0023, 1),
]

# PLD.edf signals
PLD_SIGNALS = [
    ("MaskPress.2s", 0x0037, 30),   # 0.5 Hz
    ("Press.2s",     0x0043, 30),
    ("EprPress.2s",  0x0042, 30),
    ("Leak.2s",      0x008D, 30),
    ("RespRate.2s",  0x00A0, 30),
    ("TidVol.2s",    0x00A3, 30),
    ("MinVent.2s",   0x0093, 30),
    ("TgtVent.2s",   0x002A, 30),
    ("IERatio.2s",   0x0082, 30),
    ("Snore.2s",     0x00A1, 30),
    ("FlowLim.2s",   0x0071, 30),
    ("B5ITime.2s",   0x0084, 30),
    ("B5ETime.2s",   0x0085, 30),
    ("Ti.2s",        0x0086, 30),
    ("Crc16",        0x0023, 1),
]

# SAD.edf signals (same across all variants)
SAD_SIGNALS = [
    ("Pulse.1s", 0x0074, 60),  # 1 Hz
    ("SpO2.1s",  0x0077, 60),
    ("Crc16",    0x0023, 1),
]

# STR.edf signal names - must be in EXACT field record order.
# strtab[i] labels field_record[i].
STR_SIGNAL_NAMES = [
    # [0] Date
    "Date",
    # [1-3] CSL_EMPTY - always at these positions in all 4 variants
    "MaskOn", "MaskOff", "MaskEvents",
    # [4-11] Shared base - identical across all 4 variants
    "Duration", "OnDuration", "PatientHours", "Mode",
    "S.RampEnable", "S.RampTime", "S.C.StartPress", "S.C.Press",
    # [12-15] VA/CP/AS shared (not in AV)
    "S.EPR.ClinEnable", "S.EPR.EPREnable", "S.EPR.Level", "S.EPR.EPRType",
    # [16-29] VA-only (14 entries)
    "S.BL.StartPress", "S.BL.IPAP", "S.BL.EPAP", "S.EasyBreathe",
    "S.VA.StartPress", "S.VA.MaxIPAP", "S.VA.MinEPAP", "S.VA.PS",
    "S.RiseEnable", "S.RiseTime", "S.Cycle", "S.Trigger",
    "S.TiMax", "S.TiMin",
    # [30-33] AS-only (4 entries)
    "S.AS.Comfort", "S.AS.StartPress", "S.AS.MaxPress", "S.AS.MinPress",
    # [34-42] AV-only (9 entries)
    "S.AV.StartPress", "S.AV.EPAP", "S.AV.MaxPS", "S.AV.MinPS",
    "S.AA.StartPress", "S.AA.MaxEPAP", "S.AA.MinEPAP", "S.AA.MaxPS", "S.AA.MinPS",
    # [43-56] Union shared tail (14 entries)
    "S.SmartStart", "S.PtAccess", "S.ABFilter", "S.LeakAlert",
    "S.Mask", "S.Tube", "S.ClimateControl", "S.HumEnable",
    "S.HumLevel", "S.TempEnable", "S.Temp", "S.ExternalHum",
    "HeatedTube", "Humidifier",
    # [57-69] EVE block 1 - identical across all 4 variants (13 entries)
    "BlowPress.95", "BlowPress.5", "Flow.95", "Flow.5",
    "BlowFlow.50", "AmbHumidity.50", "HumTemp.50", "HTubeTemp.50",
    "HTubePow.50", "HumPow.50", "SpO2.50", "SpO2.95", "SpO2.Max",
    # [70] CSL_B
    "SpO2Thresh",
    # [71] CSL_C (AS-only)
    "CSR",
    # [72] EXT (VA/CP only)
    "SpontCyc%",
    # [73-103] EVE block 2 - union (31 entries: base 22 + VA 6 + AV 3)
    "MaskPress.50", "MaskPress.95", "MaskPress.Max",
    "TgtIPAP.50", "TgtIPAP.95", "TgtIPAP.Max",
    "TgtEPAP.50", "TgtEPAP.95", "TgtEPAP.Max",
    "Leak.50", "Leak.95", "Leak.70", "Leak.Max",
    "MinVent.50", "MinVent.95", "MinVent.Max",
    "RespRate.50", "RespRate.95", "RespRate.Max",
    "TidVol.50", "TidVol.95", "TidVol.Max",
    "IERatio.50", "IERatio.95", "IERatio.Max",
    "Ti.50", "Ti.95", "Ti.Max",
    "TgtVent.50", "TgtVent.95", "TgtVent.Max",
    # [104-109] AEV (6 entries - superset, AV has 3-subset)
    "AHI", "HI", "AI", "OAI", "CAI", "UAI",
    # [110] AEV (AS-only, 81-field AutoSet variants)
    "RIN",
    # [111-115] CSL tail - identical across all 4 variants
    "Fault.Device", "Fault.Alarm", "Fault.Humidifier", "Fault.HeatedTube", "Crc16",
]

assert len(STR_SIGNAL_NAMES) == 116

# g[12] field records - interleaved superset
#
# Pattern observed across all 4 variants:
#   CSL_A block -> EVE1(13) -> CSL_B -> [CSL_C] -> [EXT] -> EVE2 -> AEV -> CSL_tail

# Record templates
_CSL_A = bytes([0x0D, 0x00, 0xFF, 0x7F, 0xFF, 0x7F, 0x00, 0x00, 0x00, 0x00])
_CSL_B = bytes([0x0D, 0x00, 0xFF, 0x7F, 0xFF, 0x7F, 0x00, 0x02, 0x01, 0x00])
_CSL_C = bytes([0x0D, 0x00, 0xFF, 0x7F, 0xFF, 0x7F, 0x00, 0x00, 0x01, 0x00])
_EMPTY = bytes([0x00, 0x00, 0xFF, 0x7F, 0xFF, 0x7F, 0x00, 0x00, 0x00, 0x00])

def _eve(vid, filt):
    return bytes([0x0D, 0x02]) + struct.pack('<HHHH', vid, 0x7FFF, filt, 0x0001)

def _aev(vid):
    return bytes([0x0D, 0x01]) + struct.pack('<HHHH', vid, 0x7FFF, 0x0000, 0x0002)

_EXT_REC = bytes([0x0D, 0x03]) + struct.pack('<HHHH', 0x012F, 0x0130, 0x0200, 0x0001)

# Complete interleaved field record sequence (116 records)
SUPERSET_RECORDS = [
    # [0] Date
    _CSL_A,
    # [1-3] EMPTY (MaskOn, MaskOff, MaskEvents)
    _EMPTY, _EMPTY, _EMPTY,
    # [4-56] CSL_A settings (53 entries)
    _CSL_A, _CSL_A, _CSL_A, _CSL_A, _CSL_A, _CSL_A, _CSL_A, _CSL_A,   # [4-11] shared base
    _CSL_A, _CSL_A, _CSL_A, _CSL_A,                                   # [12-15] VA/CP/AS
    _CSL_A, _CSL_A, _CSL_A, _CSL_A, _CSL_A, _CSL_A, _CSL_A, _CSL_A,   # [16-29] VA-only
    _CSL_A, _CSL_A, _CSL_A, _CSL_A, _CSL_A, _CSL_A,
    _CSL_A, _CSL_A, _CSL_A, _CSL_A,                                   # [30-33] AS-only
    _CSL_A, _CSL_A, _CSL_A, _CSL_A, _CSL_A, _CSL_A, _CSL_A, _CSL_A,   # [34-42] AV-only
    _CSL_A,
    _CSL_A, _CSL_A, _CSL_A, _CSL_A, _CSL_A, _CSL_A, _CSL_A, _CSL_A,   # [43-56] union tail
    _CSL_A, _CSL_A, _CSL_A, _CSL_A, _CSL_A, _CSL_A,
    # [57-69] EVE block 1 (13 entries)
    _eve(0x0120, 0x015F), _eve(0x0120, 0x0105),
    _eve(0x0111, 0x015F), _eve(0x0111, 0x0105),
    _eve(0x005C, 0x0132), _eve(0x005E, 0x0132),
    _eve(0x0064, 0x0132), _eve(0x0066, 0x0132),
    _eve(0x0061, 0x0132), _eve(0x0060, 0x0132),
    _eve(0x007E, 0x0232), _eve(0x007E, 0x025F), _eve(0x007E, 0x0264),
    # [70] CSL_B (SpO2Thresh)
    _CSL_B,
    # [71] CSL_C (CSR - AS-only)
    _CSL_C,
    # [72] EXT (SpontCyc%)
    _EXT_REC,
    # [73-103] EVE block 2 (31 entries - base 22 + VA 6 + AV 3)
    _eve(0x0036, 0x0132), _eve(0x0036, 0x015F), _eve(0x0036, 0x0164),
    _eve(0x0045, 0x0232), _eve(0x0045, 0x025F), _eve(0x0045, 0x0264),
    _eve(0x0044, 0x0232), _eve(0x0044, 0x025F), _eve(0x0044, 0x0264),
    _eve(0x008F, 0x0232), _eve(0x008F, 0x025F), _eve(0x008F, 0x0246), _eve(0x008F, 0x0264),
    _eve(0x0094, 0x0232), _eve(0x0094, 0x025F), _eve(0x0094, 0x0264),
    _eve(0x009C, 0x0232), _eve(0x009C, 0x025F), _eve(0x009C, 0x0264),
    _eve(0x00A2, 0x0232), _eve(0x00A2, 0x025F), _eve(0x00A2, 0x0264),
    # IERatio (0x0083), Ti (0x008B)
    _eve(0x0083, 0x0232), _eve(0x0083, 0x025F), _eve(0x0083, 0x0264),
    _eve(0x008B, 0x0232), _eve(0x008B, 0x025F), _eve(0x008B, 0x0264),
    # TgtVent (0x0029)
    _eve(0x0029, 0x0232), _eve(0x0029, 0x025F), _eve(0x0029, 0x0264),
    # [104-109] AEV (6 entries)
    _aev(0x0114), _aev(0x0117), _aev(0x0115),
    _aev(0x0121), _aev(0x0122), _aev(0x0118),
    # [110] AEV (RIN - AS-only)
    _aev(0x0152),
    # [111-115] CSL tail (Fault.*, Crc16)
    _CSL_A, _CSL_A, _CSL_A, _CSL_A, _CSL_A,
]

SUPERSET_FIELD_COUNT = len(SUPERSET_RECORDS)
assert SUPERSET_FIELD_COUNT == 116

# g[13]+0x10 -> col1 start, g[13]+0x14 -> col2 start.
# col1 = EDF signal column ID for this record
# col2 = sample count (1 for normal, 10 for MaskOn/MaskOff)
SUPERSET_COL1 = [
    # [0] Date
    0x00BA,
    # [1-3] EMPTY (MaskOn, MaskOff, MaskEvents)
    0x00B8, 0x00B5, 0x00B4,
    # [4-11] Shared base
    0x00B6, 0x00B7, 0x00BD, 0x020D, 0x0240, 0x01EF, 0x01D2, 0x0024,
    # [12-15] VA/CP/AS shared (not in AV)
    0x0232, 0x0233, 0x0070, 0x0234,
    # [16-29] VA-only (14 entries)
    0x01DA, 0x0026, 0x01D9, 0x0217, 0x01D8, 0x01D6, 0x01D5, 0x01D7,
    0x0218, 0x01DB, 0x0245, 0x0246, 0x01DD, 0x01DC,
    # [30-33] AS-only (4 entries)
    0x0221, 0x01D4, 0x0025, 0x01D3,
    # [34-42] AV-only (9 entries)
    0x01E3, 0x01E0, 0x01E2, 0x01E1, 0x01E8, 0x01E4, 0x01E5, 0x01E7, 0x01E6,
    # [43-56] Union shared tail (14 entries)
    0x0243, 0x0216, 0x021C, 0x0222, 0x0213, 0x0214, 0x0223, 0x0224,
    0x0059, 0x0226, 0x005A, 0x022B, 0x0225, 0x0227,
    # [57-69] EVE block 1 (13)
    0x003F, 0x0040, 0x006E, 0x006F, 0x005D, 0x005F, 0x0065, 0x0067,
    0x0063, 0x0069, 0x0078, 0x0079, 0x007A,
    # [70] CSL_B, [71] CSL_C
    0x007D, 0x00AA,
    # [72] EXT
    0x00A8,
    # [73-103] EVE block 2 (31)
    0x0039, 0x003A, 0x003B, 0x0048, 0x0046, 0x0047, 0x004B, 0x0049, 0x004A,
    0x008E, 0x008C, 0x0092, 0x0090, 0x0097, 0x0095, 0x0096,
    0x009F, 0x009D, 0x009E, 0x00A7, 0x00A5, 0x00A6,
    0x0081, 0x007F, 0x0080, 0x0088, 0x0089, 0x008A,
    0x002D, 0x002B, 0x002C,
    # [104-109] AEV (6)
    0x004C, 0x004F, 0x004D, 0x0056, 0x0057, 0x0058,
    # [110] AEV (RIN)
    0x0050,
    # [111-115] CSL tail (5)
    0x0201, 0x0202, 0x01FF, 0x0200, 0x0023,
]
SUPERSET_COL2 = [
    # [0] Date
    0x0001,
    # [1-3] EMPTY (MaskOn=10, MaskOff=10, MaskEvents=1)
    0x000A, 0x000A, 0x0001,
    # [4-56] CSL_A settings: all 1
    0x0001, 0x0001, 0x0001, 0x0001, 0x0001, 0x0001, 0x0001, 0x0001,
    0x0001, 0x0001, 0x0001, 0x0001,
    0x0001, 0x0001, 0x0001, 0x0001, 0x0001, 0x0001, 0x0001, 0x0001,
    0x0001, 0x0001, 0x0001, 0x0001, 0x0001, 0x0001,
    0x0001, 0x0001, 0x0001, 0x0001,
    0x0001, 0x0001, 0x0001, 0x0001, 0x0001, 0x0001, 0x0001, 0x0001, 0x0001,
    0x0001, 0x0001, 0x0001, 0x0001, 0x0001, 0x0001, 0x0001, 0x0001,
    0x0001, 0x0001, 0x0001, 0x0001, 0x0001, 0x0001,
    # [57-69] EVE1: all 1
    0x0001, 0x0001, 0x0001, 0x0001, 0x0001, 0x0001, 0x0001, 0x0001,
    0x0001, 0x0001, 0x0001, 0x0001, 0x0001,
    # [70] CSL_B, [71] CSL_C, [72] EXT
    0x0001, 0x0001, 0x0001,
    # [73-103] EVE2: all 1
    0x0001, 0x0001, 0x0001, 0x0001, 0x0001, 0x0001, 0x0001, 0x0001, 0x0001,
    0x0001, 0x0001, 0x0001, 0x0001, 0x0001, 0x0001, 0x0001,
    0x0001, 0x0001, 0x0001, 0x0001, 0x0001, 0x0001,
    0x0001, 0x0001, 0x0001, 0x0001, 0x0001, 0x0001,
    0x0001, 0x0001, 0x0001,
    # [104-109] AEV: all 1
    0x0001, 0x0001, 0x0001, 0x0001, 0x0001, 0x0001,
    # [110] AEV (RIN)
    0x0001,
    # [111-115] CSL tail: all 1
    0x0001, 0x0001, 0x0001, 0x0001, 0x0001,
]
assert len(SUPERSET_COL1) == SUPERSET_FIELD_COUNT
assert len(SUPERSET_COL2) == SUPERSET_FIELD_COUNT

G12_HEADER_SIZE = 72  # 3 x 24B headers (CSL, AEV, EVE)

# g[12] header gap arrays - var_id arrays pointed to by CSL/AEV/EVE headers at +0x10.
# These sit between g[11]+96 and g[12] in native firmware, contiguous: CSL[n] + AEV[m] + EVE[k].
# The count field at header +0x08 specifies how many u16 entries per type.
G12_GAP_CSL = [0x00B3, 0x00AB, 0x0247, 0x0023]  # superset (4)
G12_GAP_AEV = [0x00B3, 0x0023]                  # all variants (2)
G12_GAP_EVE = [0x00B3, 0x004E, 0x0220, 0x0023]  # all variants (4)

# g[13] var_id slots that are masked to 0x0000 in some variants.
# The NPD array at g[13]+0x24 lists var_ids, count at g[13]+0x44.
# AS/AV have count=7, VA/CP have count=8 ; slot [7] is 0x0083 (IERatio).
PSTR_VARID_MASKS = {
    0x32: 0x0083,  # NPD[7]: IERatio - AS/AV=0x0000, VA/CP=0x0083
}
PSTR_NPD_COUNT_OFF = 0x44
PSTR_NPD_SUPERSET_COUNT = 8

# g[20] PDL stat computation records (16 bytes each) 
# Controls which EVE stats CDX computes.
# AS=13, VA/CP=20, AV=17 records. Superset=21
G20_SUPERSET_RECORDS = [
    (0x00E8, 0x00B6, 0x0000, 0x0000, 0xFFFF, 0xFFFF, 0xFFFF, 0xFFFF),
    (0x00EB, 0x0046, 0x0000, 0x0000, 0xFFFF, 0xFFFF, 0xFFFF, 0xFFFF),
    (0x00EC, 0x0049, 0x0000, 0x0000, 0xFFFF, 0xFFFF, 0xFFFF, 0xFFFF),
    (0x00ED, 0x008C, 0x0000, 0x0000, 0xFFFF, 0xFFFF, 0xFFFF, 0xFFFF),
    (0x00EE, 0x00A7, 0x0000, 0x0000, 0xFFFF, 0xFFFF, 0xFFFF, 0xFFFF),
    (0x00F1, 0x009F, 0x0000, 0x0000, 0xFFFF, 0xFFFF, 0xFFFF, 0xFFFF),
    (0x00F0, 0x0097, 0x0000, 0x0000, 0xFFFF, 0xFFFF, 0xFFFF, 0xFFFF),
    (0x00F2, 0x0088, 0x0000, 0x0000, 0xFFFF, 0xFFFF, 0xFFFF, 0xFFFF),
    (0x00EF, 0x0081, 0x0000, 0x0000, 0xFFFF, 0xFFFF, 0xFFFF, 0xFFFF),
    (0x00F3, 0x002D, 0x0000, 0x0000, 0xFFFF, 0xFFFF, 0xFFFF, 0xFFFF),
    (0x00F5, 0x00A8, 0x0000, 0x0000, 0xFFFF, 0xFFFF, 0xFFFF, 0xFFFF),
    (0x00F8, 0x004C, 0x0000, 0x0000, 0xFFFF, 0xFFFF, 0xFFFF, 0xFFFF),
    (0x00F9, 0x004D, 0x0000, 0x0000, 0xFFFF, 0xFFFF, 0xFFFF, 0xFFFF),
    (0x00FA, 0x0057, 0x0000, 0x0000, 0xFFFF, 0xFFFF, 0xFFFF, 0xFFFF),
    (0x00E7, 0x00B6, 0x0100, 0x0000, 0xFFFF, 0xFFFF, 0x00F0, 0x0000),
    (0x00EA, 0x00B6, 0x0100, 0x0000, 0xFFFF, 0xFFFF, 0xFFFF, 0xFFFF),
    (0x00E9, 0x00B6, 0x0200, 0x0000, 0xFFFF, 0xFFFF, 0xFFFF, 0xFFFF),
    (0x00F7, 0x004C, 0x0300, 0x0000, 0xFFFF, 0xFFFF, 0xFFFF, 0xFFFF),
    (0x0257, 0x0092, 0x0300, 0x0000, 0xFFFF, 0xFFFF, 0xFFFF, 0xFFFF),
    (0x00E5, 0x00B6, 0x0300, 0x0000, 0xFFFF, 0xFFFF, 0xFFFF, 0xFFFF),
    (0x0258, 0x01FF, 0x0300, 0x0000, 0xFFFF, 0xFFFF, 0xFFFF, 0xFFFF),
]
G20_SUPERSET_COUNT = len(G20_SUPERSET_RECORDS)
G20_HEADER_SIZE = 12  # "PDL\0" + ptr(4) + 0x0022 + 0x0000

# g[26] tail superset, var_id pool referenced by g[27] APN/CSN/BRH records
# g[26] = 8 records x 20B at 0x080093F4, followed by a packed var_id pool.
# g[27] APN/CSN/BRH records point INTO this pool with overlapping windows.
#
# APN: [0x0220, 0x004E]                 same all variants, cnt=2
# CSN: [0x00AC, 0x0247]                 AS has both (cnt=2), VA/AV only 0x0247 (cnt=1)
# BRH: [0x00A4, 0x0041, 0x0086, 0x0087] VA has 4 (cnt=4), AS/AV only first 2 (cnt=2)
G26_TAIL_APN = [0x0220, 0x004E]
G26_TAIL_CSN = [0x00AC, 0x0247]
G26_TAIL_BRH = [0x00A4, 0x0041, 0x0086, 0x0087]

# g[26] record data array superset.
#
# Each g[26] record (20B) has ptr1 -> var_id array, ptr2 -> rate array.
# These arrays sit in a packed region BEFORE the g[26] records and are NOT
# part of the g[26] 160B copy. Bumping a record's count without relocating
# its ptr1/ptr2 arrays causes the firmware to read into adjacent array data.
#
# Fix: for every record whose count changes, write the full superset array
# into the merge block and redirect ptr1/ptr2.
#
# TCE (record[0]): AS/ASV=3, VA=4. VA prepends TrigCycEvt (0x0244).
# PBT (record[1]): AS/VA=5, ASV=6. ASV inserts TgtVent (0x002A) at [1].
# Records 2-7 (PMD/FTX/RAW/DRT/CPU/SSK): identical across all variants.
G26_DATA_PATCHES = {
    # record_index: (superset_varids, superset_rates)
    0: ([0x0244, 0x0038, 0x006B, 0x0091],            # TCE: VA order
        [0x0001, 0x0001, 0x0001, 0x0001]),
    1: ([0x0093, 0x002A, 0x00A0, 0x008D, 0x003E, 0x003D],  # PBT: ASV order
        [0x0001, 0x0001, 0x0001, 0x0001, 0x0001, 0x0001]),
}

# g[27] record count superset
# Record layout: 3 x 16B records (APN, CSN, BRH) + 24B shared tail (OXH var_ids+rates)
# Counts:        APN: max(2,2,2)=2   CSN: max(2,1,1)=2   BRH: max(2,4,2)=4
G27_APN_SUPERSET_COUNT = 2
G27_CSN_SUPERSET_COUNT = 2  # AS=2, VA/AV=1
G27_BRH_SUPERSET_COUNT = 4  # VA=4, AS/AV=2

# g[14] NPD count, byte at g[14]+16 inside the NPD sub-record header.
# AS/AV=7, VA=8. Parallels g[13]+0x44 NPD count (already patched).
G14_NPD_SUPERSET_COUNT = 8


# g[4] variable descriptor activation flags.
G4_ACT_PATCHES = [
      7,   8,  11,  12,  13,  14,  15,  50,  56,  57,
     58,  82,  97,  98,  99, 100, 101, 102, 103, 104,
    105, 106, 107, 108, 109, 138, 140, 141, 142, 206,
    208, 209, 210, 211, 212, 213, 215, 220, 228, 229,
    230, 231, 232, 244, 254, 259, 260, 269, 272, 273,
    274, 275, 276, 277, 286, 295, 308, 309, 310, 312,
    437, 438, 439, 440, 441, 442, 443, 444, 445, 446,
    447, 450, 451, 452, 453, 454, 455, 456, 457, 458,
]

# g[8] variable descriptor activation flags.
# Records where at least one variant has ACT=1 but not all do.
G8_ACT_PATCHES = [
    10, 11, 20, 21, 30, 37, 38, 39, 55, 56, 57, 58, 99, 100, 160,
]



class CCXMergeError(Exception):
    pass


def read_u16(data, off):
    return struct.unpack_from('<H', data, off)[0]


def read_u32(data, off):
    return struct.unpack_from('<I', data, off)[0]


def write_u8(data, off, val):
    data[off] = val & 0xFF


def write_u16(data, off, val):
    struct.pack_into('<H', data, off, val)


def write_u32(data, off, val):
    struct.pack_into('<I', data, off, val)


def crc16_ccitt(data, init=0xFFFF):
    crc = init
    for b in data:
        crc ^= b << 8
        for _ in range(8):
            if crc & 0x8000:
                crc = (crc << 1) ^ 0x1021
            else:
                crc = crc << 1
            crc &= 0xFFFF
    return crc


def update_ccx_crc(data):
    body = data[:CCX_CRC_OFFSET]
    crc = crc16_ccitt(body)
    struct.pack_into('>H', data, CCX_CRC_OFFSET, crc)
    return crc


def ccx_off(addr):
    """Convert absolute flash address to CCX file offset."""
    if not (CCX_BASE <= addr < CCX_BASE + CCX_SIZE):
        raise CCXMergeError(f"Address 0x{addr:08X} outside CCX range")
    return addr - CCX_BASE


def ccx_addr(off):
    return CCX_BASE + off


def find_globals(data):
    # globals[0] should point to 0x08004000 (config_variables).
    # globals[] is at CCX+0x108
    g0 = read_u32(data, 0x108)
    if g0 != CCX_BASE:
        raise CCXMergeError(
            f"globals[0] = 0x{g0:08X}, expected 0x{CCX_BASE:08X}. "
            "Not a valid SX567 CCX image?"
        )
    return 0x108


def read_globals(data, globals_off, count=29):
    return [read_u32(data, globals_off + i * 4) for i in range(count)]


def find_free_space(data, g=None):
    """Find the start of free (0xFF) space after all used data.
    
    Scans backward from FREE_SPACE_LIMIT to find where erased flash begins.
    Then returns the start of the free region.
    
    IMPORTANT: The STR strtab is terminated by 0xFFFFFFFF, which looks like
    erased flash but is actually the strtab fence post. Free space starts
    AFTER the terminator (terminator_offset + 4).
    """
    # If we know the strtab location, skip past its terminator
    strtab_end = None
    if g is not None:
        g13_off = ccx_off(g[13])
        strtab_ptr = read_u32(data, g13_off + 0x1C)
        if CCX_BASE <= strtab_ptr < CCX_BASE + CCX_SIZE:
            strtab_off = ccx_off(strtab_ptr)
            n = 0
            while n < 300:
                v = read_u32(data, strtab_off + n * 4)
                if not (CCX_BASE <= v < CCX_BASE + CCX_SIZE):
                    break
                n += 1
            # strtab_off + n*4 is the terminator (0xFFFFFFFF)
            strtab_end = strtab_off + n * 4 + 4  # skip past terminator
    
    # Scan forward from the globals area to find where 0xFF starts
    # The free gap is between the string tables and locale data (0x10500)
    off = strtab_end if strtab_end else 0x6000
    while off < FREE_SPACE_LIMIT:
        if data[off] == ERASED:
            # Found start of free region - verify it's actually free
            end = off
            while end < FREE_SPACE_LIMIT and data[end] == ERASED:
                end += 1
            if end >= FREE_SPACE_LIMIT:
                return off  # Good - continuous free space to limit
            # Small gap, keep scanning
            off = end
        else:
            off += 1
    
    raise CCXMergeError("Cannot find free space in CCX image")


def validate_g11_header(data, off, expected_tag):
    """Validate a BRP/PLD/SAD 32-byte header at given offset."""
    tag = data[off + 9:off + 12].decode('ascii', errors='replace')
    if tag != expected_tag:
        raise CCXMergeError(
            f"Expected '{expected_tag}' tag at CCX+0x{off:05X}, got '{tag}'"
        )
    return True


def detect_variant(data, g):
    g13_off = ccx_off(g[13])
    strtab_ptr = read_u32(data, g13_off + 28)
    strtab_off = ccx_off(strtab_ptr)
    
    # Count STR signal entries
    n = 0
    while True:
        ptr = read_u32(data, strtab_off + n * 4)
        if CCX_BASE <= ptr < CCX_BASE + CCX_SIZE:
            n += 1
        else:
            break
    
    names = []
    for i in range(min(n, 25)):
        ptr = read_u32(data, strtab_off + i * 4)
        off = ccx_off(ptr)
        s = data[off:off + 30].split(b'\x00')[0].decode('ascii', errors='replace')
        names.append(s)
    
    if n in (80, 81) and "S.AS.MaxPress" in names:
        return "AutoSet", n
    elif n == 97 and "S.VA.StartPress" in names:
        return "VAuto", n
    elif n == 82 and "S.AV.StartPress" in names:
        return "CS_PaceWave", n
    elif n == 76 and "S.C.Press" in names and "S.AS.MaxPress" not in names:
        return "Elite", n
    else:
        return f"Unknown({n}sig)", n


def parse_g12_block(data, g):
    """Parse the g[12] CSL/AEV/EVE block and extract headers.
    
    Returns:
        headers: 72-byte header block (CSL/AEV/EVE file type headers)
        field_count: number of field records in original block
        old_range: (start_off, end_off) CCX offsets of old g[12] block
    """
    g12_off = ccx_off(g[12])
    g13_off = ccx_off(g[13])
    
    headers = bytes(data[g12_off:g12_off + G12_HEADER_SIZE])
    
    fr_start = g12_off + G12_HEADER_SIZE
    field_count = 0
    for i in range(200):
        off = fr_start + i * 10
        typ = data[off]
        fid = data[off + 1]
        vid = read_u16(data, off + 2)
        if typ == 0x0D and fid in (0, 1, 2, 3):
            field_count += 1
        elif typ == 0x00 and fid in (0, 1, 2, 3) and vid == 0x7FFF:
            field_count += 1
        else:
            break
    
    return headers, field_count, (g12_off, g13_off)


def build_g12_block(headers):
    """Build the complete relocated g[12] block.
    
    Layout:
        +0x000: 3x24B headers (from source, unchanged)
        +0x048: 116 superset field records x 10B (interleaved CSL/EVE/AEV/EXT)
        +0x4D0: 116 x 2B col1 array (chain_start)
        +0x5B8: 116 x 2B col2 array (chain_mid)
        +0x6A0: end
    
    Returns the block bytes.
    """
    buf = bytearray()
    
    buf.extend(headers)
    
    # Interleaved field records, order preserves native firmware layout
    for rec in SUPERSET_RECORDS:
        buf.extend(rec)
    
    for c1 in SUPERSET_COL1:
        buf.extend(struct.pack('<H', c1))
    
    for c2 in SUPERSET_COL2:
        buf.extend(struct.pack('<H', c2))
    
    return bytes(buf)


def build_merge_block(free_start, g12_block=None, source_data=None, g=None):
    """Build the complete merge data block to write into free space.
    
    Returns (block_bytes, layout) where layout contains all the
    absolute addresses needed for pointer patching.
    
    Args:
        free_start: CCX offset where free space begins
        g12_block: optional bytes for relocated g[12] block
        source_data: CCX image bytes (needed for g[28]+g[11] template extraction)
        g: globals[] array (needed for g[28]+g[11] relocation)
    """
    buf = bytearray()
    base_addr = ccx_addr(free_start)
    
    layout = {}
    
    def cur_addr():
        return base_addr + len(buf)
    
    def align4():
        while len(buf) % 4 != 0:
            buf.append(0x00)
    
    # Collect all unique strings, write once, map name -> address
    all_strings = set()
    for name, _, _ in BRP_SIGNALS:
        all_strings.add(name)
    for name, _, _ in PLD_SIGNALS:
        all_strings.add(name)
    for name, _, _ in SAD_SIGNALS:
        all_strings.add(name)
    for name in STR_SIGNAL_NAMES:
        all_strings.add(name)
    
    str_addrs = {}
    layout['strings_start'] = cur_addr()
    for name in sorted(all_strings):
        str_addrs[name] = cur_addr()
        buf.extend(name.encode('ascii'))
        buf.append(0x00)
    align4()
    layout['strings_end'] = cur_addr()
    
    # BRP var_ids array
    layout['brp_var_ids'] = cur_addr()
    for _, var_id, _ in BRP_SIGNALS:
        buf.extend(struct.pack('<H', var_id))
    align4()
    
    # BRP samples array
    layout['brp_samples'] = cur_addr()
    for _, _, samples in BRP_SIGNALS:
        buf.extend(struct.pack('<H', samples))
    align4()
    
    # PLD var_ids array
    layout['pld_var_ids'] = cur_addr()
    for _, var_id, _ in PLD_SIGNALS:
        buf.extend(struct.pack('<H', var_id))
    align4()
    
    # PLD samples array
    layout['pld_samples'] = cur_addr()
    for _, _, samples in PLD_SIGNALS:
        buf.extend(struct.pack('<H', samples))
    align4()
    
    # BRP string pointer table
    layout['brp_str_ptrs'] = cur_addr()
    for name, _, _ in BRP_SIGNALS:
        buf.extend(struct.pack('<I', str_addrs[name]))
    
    # PLD string pointer table
    layout['pld_str_ptrs'] = cur_addr()
    for name, _, _ in PLD_SIGNALS:
        buf.extend(struct.pack('<I', str_addrs[name]))
    
    # SAD string pointer table
    layout['sad_str_ptrs'] = cur_addr()
    for name, _, _ in SAD_SIGNALS:
        buf.extend(struct.pack('<I', str_addrs[name]))
    
    # STR string pointer table
    layout['str_ptrs'] = cur_addr()
    for name in STR_SIGNAL_NAMES:
        buf.extend(struct.pack('<I', str_addrs[name]))
    # Terminator
    buf.extend(struct.pack('<I', 0xFFFFFFFF))
    layout['str_ptrs_end'] = cur_addr()
    
    # g[12] CSL/AEV/EVE relocated block
    if g12_block is not None:
        align4()
        layout['g12_block'] = cur_addr()
        buf.extend(g12_block)
        layout['g12_block_end'] = cur_addr()
        layout['g12_block_size'] = len(g12_block)
    
    # g[12] header gap arrays 
    # Contiguous: CSL[4] + AEV[2] + EVE[4] = 10 u16 entries = 20 bytes.
    align4()
    layout['gap_csl'] = cur_addr()
    for v in G12_GAP_CSL:
        buf.extend(struct.pack('<H', v))
    layout['gap_aev'] = cur_addr()
    for v in G12_GAP_AEV:
        buf.extend(struct.pack('<H', v))
    layout['gap_eve'] = cur_addr()
    for v in G12_GAP_EVE:
        buf.extend(struct.pack('<H', v))
    
    # g[28] + g[11] combined block (OXH header + inline arrays + signal headers)
    # g[11] headers sit at the tail of the g[28] block.
    #
    # Layout:
    #   OXH header (20B) - copied from source, +8/+12 ptrs fixed to inline arrays
    #   OXH var_ids [6] (12B) - relocated from before g[28] (in erase range)
    #   OXH rates [6]   (12B) - relocated from before g[28] (in erase range)
    #   BRP var_ids [4]  (8B)
    #   BRP samples [4]  (8B)
    #   PLD var_ids [14] (28B)
    #   PLD samples [14] (28B)
    #   SAD var_ids [3+pad] (8B)
    #   SAD samples [3+pad] (8B)
    #   g[11] BRP header (32B) - ptr1/ptr2 -> inline above, ptr3 -> merge block str ptrs
    #   g[11] PLD header (32B)
    #   g[11] SAD header (32B)
    #
    if source_data is not None and g is not None:
        OXH_HDR_SIZE = 20
        G11_HDR_SIZE = 32
        
        g28_off = ccx_off(g[28])
        g11_off = ccx_off(g[11])
        
        align4()
        layout['g28_block'] = cur_addr()
        g28_buf_start = len(buf)
        
        # Copy OXH header (20 bytes) from source
        buf.extend(source_data[g28_off:g28_off + OXH_HDR_SIZE])
        
        # Relocate OXH var_id and rate arrays.
        # These sit BEFORE g[28] in the original layout (in the erase range).
        # The header at +8/+12 still points to the old addresses after copy.
        oxh_count = source_data[g28_off]
        oxh_p1 = ccx_off(read_u32(source_data, g28_off + 8))
        oxh_p2 = ccx_off(read_u32(source_data, g28_off + 12))

        layout['g28_oxh_var_ids'] = cur_addr()
        buf.extend(source_data[oxh_p1:oxh_p1 + oxh_count * 2])
        layout['g28_oxh_rates'] = cur_addr()
        buf.extend(source_data[oxh_p2:oxh_p2 + oxh_count * 2])

        # Fix OXH header +8/+12 to point to relocated arrays
        struct.pack_into('<I', buf, g28_buf_start + 8, layout['g28_oxh_var_ids'])
        struct.pack_into('<I', buf, g28_buf_start + 12, layout['g28_oxh_rates'])

        # Inline BRP var_ids + samples
        layout['g28_brp_var_ids'] = cur_addr()
        for _, var_id, _ in BRP_SIGNALS:
            buf.extend(struct.pack('<H', var_id))
        layout['g28_brp_samples'] = cur_addr()
        for _, _, samples in BRP_SIGNALS:
            buf.extend(struct.pack('<H', samples))
        
        # Inline PLD var_ids + samples
        layout['g28_pld_var_ids'] = cur_addr()
        for _, var_id, _ in PLD_SIGNALS:
            buf.extend(struct.pack('<H', var_id))
        layout['g28_pld_samples'] = cur_addr()
        for _, _, samples in PLD_SIGNALS:
            buf.extend(struct.pack('<H', samples))
        
        # Inline SAD var_ids + samples
        layout['g28_sad_var_ids'] = cur_addr()
        for _, var_id, _ in SAD_SIGNALS:
            buf.extend(struct.pack('<H', var_id))
        buf.extend(struct.pack('<H', 0x0000))
        layout['g28_sad_samples'] = cur_addr()
        for _, _, samples in SAD_SIGNALS:
            buf.extend(struct.pack('<H', samples))
        buf.extend(struct.pack('<H', 0x0000))
        
        # g[11] headers - copy templates from source, then fix pointers in-place
        layout['g11_block'] = cur_addr()
        
        for h, (tag, vid_key, samp_key, str_key, signals) in enumerate([
            ('BRP', 'g28_brp_var_ids', 'g28_brp_samples', 'brp_str_ptrs', BRP_SIGNALS),
            ('PLD', 'g28_pld_var_ids', 'g28_pld_samples', 'pld_str_ptrs', PLD_SIGNALS),
            ('SAD', 'g28_sad_var_ids', 'g28_sad_samples', 'sad_str_ptrs', SAD_SIGNALS),
        ]):
            hdr_src = g11_off + h * G11_HDR_SIZE
            hdr_start = len(buf)
            buf.extend(source_data[hdr_src:hdr_src + G11_HDR_SIZE])
            
            # Fix count
            buf[hdr_start + 8] = len(signals)
            # Fix ptr1 -> inline var_ids
            struct.pack_into('<I', buf, hdr_start + 16, layout[vid_key])
            # Fix ptr2 -> inline samples
            struct.pack_into('<I', buf, hdr_start + 20, layout[samp_key])
            # Fix ptr3 -> merge block string ptrs
            struct.pack_into('<I', buf, hdr_start + 28, layout[str_key])
        
        layout['g28_block_end'] = cur_addr()
    
    # g[21] computation enable table
    # AS=13, VA/CP=20, AV=17 records. Superset=21
    align4()
    layout['g21_records'] = cur_addr()
    for rec_tuple in G20_SUPERSET_RECORDS:
        for v in rec_tuple:
            buf.extend(struct.pack('<H', v))
    layout['g21_records_end'] = cur_addr()
    
    # g[13]+g[14] consolidated block (84B) 
    # g[13] (PSTR, 52B) and g[14] (NPD, 32B) are contiguous in all variants.
    if source_data is not None and g is not None:
        align4()
        g13_src = ccx_off(g[13])
        layout['g13_block'] = cur_addr()
        g13_start = len(buf)
        buf.extend(source_data[g13_src:g13_src + 84])
        
        # g[13]+0x08: field record count
        buf[g13_start + 0x08] = SUPERSET_FIELD_COUNT
        # g[13]+0x10: chain_start ptr -> col1 in relocated g[12]
        if 'g12_block' in layout:
            chain_start = layout['g12_block'] + G12_HEADER_SIZE + SUPERSET_FIELD_COUNT * 10
            chain_mid = chain_start + SUPERSET_FIELD_COUNT * 2
            field_recs = layout['g12_block'] + G12_HEADER_SIZE
            struct.pack_into('<I', buf, g13_start + 0x10, chain_start)
            struct.pack_into('<I', buf, g13_start + 0x14, chain_mid)
            struct.pack_into('<I', buf, g13_start + 0x20, field_recs)
        # g[13]+0x1C: strtab ptr -> STR signal name pointer table
        struct.pack_into('<I', buf, g13_start + 0x1C, layout['str_ptrs'])
        # g[13]+0x32: var_id unmask
        for off, expected in PSTR_VARID_MASKS.items():
            if expected != 0x0000:
                struct.pack_into('<H', buf, g13_start + off, expected)
        # g[13]+0x44 = g[14]+0x10: NPD count
        buf[g13_start + 0x44] = PSTR_NPD_SUPERSET_COUNT
        # g[14]+0x18: back-pointer to g[13]+0x24
        struct.pack_into('<I', buf, g13_start + 0x34 + 0x18, layout['g13_block'] + 0x24)
        
        layout['g14_block'] = layout['g13_block'] + 52  # g[14] immediately follows
        layout['g13g14_end'] = cur_addr()
    
    # g[21] header (8B)
    # {count(u16), pad(u16), ptr(u32)}
    if source_data is not None and g is not None:
        align4()
        layout['g21_block'] = cur_addr()
        buf.extend(struct.pack('<HHI', G20_SUPERSET_COUNT, 0, layout['g21_records']))
        layout['g21_block_end'] = cur_addr()
    
    # g[26]+g[27] consolidated block
    # g[26]: 8 records x 20B = 160B (internal ptrs to 0x080092xx data arrays, shared)
    #        + superset tail: APN(4B) + CSN(4B) + BRH(8B) = 16B
    # g[27]: 3 records x 16B = 48B (APN/CSN/BRH with counts+ptrs into g[26] tail)
    #        + 24B shared tail (OXH var_ids + rates, identical all variants)
    if source_data is not None and g is not None:
        align4()
        g26_src = ccx_off(g[26])
        layout['g26_block'] = cur_addr()
        g26_start = len(buf)
        
        # Copy 160B of g[26] records, then patch counts and relocate data arrays
        buf.extend(source_data[g26_src:g26_src + 160])
        
        for rec_idx, (sup_varids, sup_rates) in G26_DATA_PATCHES.items():
            rec_buf_off = g26_start + rec_idx * 20
            new_count = len(sup_varids)
            buf[rec_buf_off] = new_count
            
            # Write superset arrays into merge block
            layout[f'g26_r{rec_idx}_varids'] = cur_addr()
            for v in sup_varids:
                buf.extend(struct.pack('<H', v))
            layout[f'g26_r{rec_idx}_rates'] = cur_addr()
            for v in sup_rates:
                buf.extend(struct.pack('<H', v))
            
            # Redirect record ptr1/ptr2 to new arrays
            struct.pack_into('<I', buf, rec_buf_off + 8, layout[f'g26_r{rec_idx}_varids'])
            struct.pack_into('<I', buf, rec_buf_off + 12, layout[f'g26_r{rec_idx}_rates'])
        
        tail_start = len(buf)
        layout['g26_tail_apn'] = cur_addr()
        for v in G26_TAIL_APN:
            buf.extend(struct.pack('<H', v))
        layout['g26_tail_csn'] = cur_addr()
        for v in G26_TAIL_CSN:
            buf.extend(struct.pack('<H', v))
        layout['g26_tail_brh'] = cur_addr()
        for v in G26_TAIL_BRH:
            buf.extend(struct.pack('<H', v))
        
        layout['g27_block'] = cur_addr()
        g27_src = ccx_off(g[27])
        g27_start = len(buf)
        buf.extend(source_data[g27_src:g27_src + 48])
        
        # Fix counts and pointers in g[27] records
        for r, (superset_cnt, tail_key) in enumerate([
            (G27_APN_SUPERSET_COUNT, 'g26_tail_apn'),
            (G27_CSN_SUPERSET_COUNT, 'g26_tail_csn'),
            (G27_BRH_SUPERSET_COUNT, 'g26_tail_brh'),
        ]):
            rec_off = g27_start + r * 16
            buf[rec_off] = superset_cnt
            struct.pack_into('<I', buf, rec_off + 8, layout[tail_key])
        
        # Append 24B shared tail (OXH var_ids + rates, same in all variants)
        buf.extend(source_data[g27_src + 48:g27_src + 72])
        
        layout['g26_tail_end'] = cur_addr()
        layout['g26g27_end'] = cur_addr()
    
    # g[15]..g[24] opaque block (variable descriptors + config tables)
    # These 10 globals form a self-contained block with internal cross-references
    # No external code/data refs INTO the block (only globals[] entries).
    # One outgoing ref: g[15]+0x10 -> g[14]+0x1C (fixed separately in apply_patches).
    # Relocate as opaque bytes + pointer sweep
    if source_data is not None and g is not None:
        align4()
        
        old_block_start = g[15]
        old_block_end_off = len(source_data)  # fallback
        g24_off = ccx_off(g[24])
        for probe in range(g24_off + 512, len(source_data) - 32):
            if source_data[probe:probe + 32] == b'\xFF' * 32:
                old_block_end_off = probe
                break
        old_block_end = ccx_addr(old_block_end_off)
        old_block_size = old_block_end - old_block_start
        
        layout['g15_block'] = cur_addr()
        delta = layout['g15_block'] - old_block_start
        
        g15_buf_start = len(buf)
        src_off = ccx_off(old_block_start)
        buf.extend(source_data[src_off:src_off + old_block_size])
        
        # Pointer sweep: fixup all aligned u32 in old block range
        ptr_fixups = 0
        for j in range(0, old_block_size - 3, 4):
            val = struct.unpack_from('<I', buf, g15_buf_start + j)[0]
            if old_block_start <= val < old_block_end:
                struct.pack_into('<I', buf, g15_buf_start + j, val + delta)
                ptr_fixups += 1
        
        for i in range(15, 25):
            if i == 21:
                continue  # g[21] has its own dedicated merge block section
            gi_addr = g[i]
            if old_block_start <= gi_addr < old_block_end:
                layout[f'g{i}_block'] = gi_addr + delta
        
        layout['g15_24_ptr_fixups'] = ptr_fixups
        layout['g15_24_delta'] = delta
        layout['g15_24_old_start'] = old_block_start
        layout['g15_24_old_end'] = old_block_end
        layout['g15_24_end'] = cur_addr()
    
    layout['total_size'] = len(buf)
    return bytes(buf), layout

def apply_patches(data, g, layout):
    """Patch the CCX image to use the new merge block.
    
    Most structs are now pre-built in the merge block - we just redirect
    globals[] pointers.  Only g[4] ACT flags and g[12] header fixups
    remain as in-place patches.
    """
    patches = []
    globals_off = 0x108
    
    # Redirect globals[28] -> new g[28] block
    # Redirect globals[11] -> new g[11] headers (inside g[28] block)
    if 'g28_block' in layout:
        old_g28 = read_u32(data, globals_off + 28 * 4)
        patches.append(f"globals[28]: 0x{old_g28:08X} -> 0x{layout['g28_block']:08X}")
        write_u32(data, globals_off + 28 * 4, layout['g28_block'])
        
        old_g11 = read_u32(data, globals_off + 11 * 4)
        patches.append(f"globals[11]: 0x{old_g11:08X} -> 0x{layout['g11_block']:08X}")
        write_u32(data, globals_off + 11 * 4, layout['g11_block'])
        
        patches.append(f"BRP sig_count -> {len(BRP_SIGNALS)} (in new g[11])")
        patches.append(f"PLD sig_count -> {len(PLD_SIGNALS)} (in new g[11])")
    
    # Redirect globals[12] -> new g[12] block
    if 'g12_block' in layout:
        old_g12 = read_u32(data, globals_off + 12 * 4)
        patches.append(f"globals[12]: 0x{old_g12:08X} -> 0x{layout['g12_block']:08X}")
        write_u32(data, globals_off + 12 * 4, layout['g12_block'])
    
    # Patch g[12] header gap arrays (in relocated g[12])
    if 'gap_csl' in layout:
        new_g12_off = ccx_off(layout['g12_block'])
        
        # CSL header +4: AS=0x01, VA/ASV=0x00
        #old_val = data[new_g12_off + 4]
        #if old_val != 0x00:
        #    patches.append(f"g12 CSL hdr+4: 0x{old_val:02X} -> 0x00")
        #    write_u8(data, new_g12_off + 4, 0x00)
        
        for h, (tag, gap_key, gap_arr) in enumerate([
            ('CSL', 'gap_csl', G12_GAP_CSL),
            ('AEV', 'gap_aev', G12_GAP_AEV),
            ('EVE', 'gap_eve', G12_GAP_EVE),
        ]):
            hdr_off = new_g12_off + h * 24
            old_count = data[hdr_off + 8]
            new_count = len(gap_arr)
            old_ptr = read_u32(data, hdr_off + 16)
            new_ptr = layout[gap_key]
            
            if old_count != new_count:
                patches.append(f"g12 {tag} gap count: {old_count} -> {new_count}")
                write_u8(data, hdr_off + 8, new_count)
            if old_ptr != new_ptr:
                patches.append(f"g12 {tag} gap ptr: 0x{old_ptr:08X} -> 0x{new_ptr:08X}")
                write_u32(data, hdr_off + 16, new_ptr)
    
    # Redirect globals[13] + globals[14] -> consolidated block
    # All PSTR patches (strtab, field_rec_count, chain ptrs, var_id unmask,
    # NPD count, g[14] back-pointer) are pre-applied in the merge block copy.
    if 'g13_block' in layout:
        old_g13 = read_u32(data, globals_off + 13 * 4)
        patches.append(f"globals[13]: 0x{old_g13:08X} -> 0x{layout['g13_block']:08X}")
        write_u32(data, globals_off + 13 * 4, layout['g13_block'])
        
        old_g14 = read_u32(data, globals_off + 14 * 4)
        patches.append(f"globals[14]: 0x{old_g14:08X} -> 0x{layout['g14_block']:08X}")
        write_u32(data, globals_off + 14 * 4, layout['g14_block'])
    
    # Redirect globals[15..20, 22..24] -> opaque relocated block
    # Internal pointers already delta-adjusted by build_merge_block sweep.
    # g[21] is handled separately (dedicated merge block section).
    # g[25] is a literal value (0x31), not a pointer - left untouched.
    if 'g15_block' in layout:
        for i in range(15, 25):
            if i == 21:
                continue  # handled separately
            key = f'g{i}_block'
            if key in layout:
                old_gi = read_u32(data, globals_off + i * 4)
                patches.append(f"globals[{i}]: 0x{old_gi:08X} -> 0x{layout[key]:08X}")
                write_u32(data, globals_off + i * 4, layout[key])
        
        # Fix g[15]+0x10 cross-reference: points to g[14]+0x1C (outside the block).
        new_g15_off = ccx_off(layout['g15_block'])
        old_xref = read_u32(data, new_g15_off + 0x10)
        new_xref = layout['g14_block'] + 0x1C
        if old_xref != new_xref:
            patches.append(f"g[15]+0x10 xref: 0x{old_xref:08X} -> 0x{new_xref:08X} (-> g[14]+0x1C)")
            write_u32(data, new_g15_off + 0x10, new_xref)
        
        fixups = layout.get('g15_24_ptr_fixups', 0)
        delta = layout.get('g15_24_delta', 0)
        patches.append(f"g[15..24] opaque block: {fixups} internal ptrs delta-adjusted by +0x{delta:X}")
    
    # Redirect globals[21] -> pre-built header
    if 'g21_block' in layout:
        old_g21 = read_u32(data, globals_off + 21 * 4)
        patches.append(f"globals[21]: 0x{old_g21:08X} -> 0x{layout['g21_block']:08X}")
        write_u32(data, globals_off + 21 * 4, layout['g21_block'])
    
    # Redirect globals[26] + globals[27] -> consolidated block
    # TCE/PBT counts, g[27] APN/CSN/BRH counts+ptrs all pre-applied.
    if 'g26_block' in layout:
        old_g26 = read_u32(data, globals_off + 26 * 4)
        patches.append(f"globals[26]: 0x{old_g26:08X} -> 0x{layout['g26_block']:08X}")
        write_u32(data, globals_off + 26 * 4, layout['g26_block'])
        
        old_g27 = read_u32(data, globals_off + 27 * 4)
        patches.append(f"globals[27]: 0x{old_g27:08X} -> 0x{layout['g27_block']:08X}")
        write_u32(data, globals_off + 27 * 4, layout['g27_block'])
    
    # Patch g[4] ACT flags
    g4_off = ccx_off(g[4])
    act_count = 0
    for rec_idx in G4_ACT_PATCHES:
        rec_off = g4_off + rec_idx * 28
        old_flags = read_u16(data, rec_off)
        if not (old_flags & 0x0001):
            write_u16(data, rec_off, old_flags | 0x0001)
            act_count += 1
    if act_count:
        patches.append(f"g[4] ACT bit0: {act_count}/{len(G4_ACT_PATCHES)} records activated")
    
    # Patch g[8] ACT flags
    g8_off = ccx_off(g[8])
    g8_act_count = 0
    for rec_idx in G8_ACT_PATCHES:
        rec_off = g8_off + rec_idx * 20
        old_flags = read_u16(data, rec_off)
        if not (old_flags & 0x0001):
            write_u16(data, rec_off, old_flags | 0x0001)
            g8_act_count += 1
    if g8_act_count:
        patches.append(f"g[8] ACT bit0: {g8_act_count}/{len(G8_ACT_PATCHES)} records activated")

    return patches


def validate_result(data, g, layout):
    """Post-patch validation.
    
    After apply_patches, globals[] pointers have been redirected to the merge block.
    Read current pointers from data, not from the pre-patch `g` dict.
    """
    errors = []
    globals_off = 0x108
    
    # Read current globals[] (post-patch)
    cur_g = {}
    for i in range(29):
        cur_g[i] = read_u32(data, globals_off + i * 4)
    
    # g[11] / g[28]: BRP/PLD signal counts
    g11_off = ccx_off(cur_g[11])
    if data[g11_off + 8] != len(BRP_SIGNALS):
        errors.append(f"BRP sig_count = {data[g11_off+8]}, expected {len(BRP_SIGNALS)}")
    if data[g11_off + 32 + 8] != len(PLD_SIGNALS):
        errors.append(f"PLD sig_count = {data[g11_off+32+8]}, expected {len(PLD_SIGNALS)}")
    
    # g[13]: PSTR record
    g13_off = ccx_off(cur_g[13])
    
    # STR signal name table pointer
    strtab_ptr = read_u32(data, g13_off + 28)
    if strtab_ptr != layout['str_ptrs']:
        errors.append(f"PSTR strtab pointer mismatch: 0x{strtab_ptr:08X} vs 0x{layout['str_ptrs']:08X}")
    else:
        first_str_ptr = read_u32(data, ccx_off(strtab_ptr))
        first_str_off = ccx_off(first_str_ptr)
        s = data[first_str_off:first_str_off + 10].split(b'\x00')[0].decode('ascii', errors='replace')
        if s != STR_SIGNAL_NAMES[0]:
            errors.append(f"First STR signal = '{s}', expected '{STR_SIGNAL_NAMES[0]}'")
    
    # Field record count
    actual_str_count = data[g13_off + 0x08]
    if actual_str_count != SUPERSET_FIELD_COUNT:
        errors.append(f"PSTR field_rec_count = {actual_str_count}, expected {SUPERSET_FIELD_COUNT}")
    
    # STR table terminator
    term_off = ccx_off(layout['str_ptrs']) + len(STR_SIGNAL_NAMES) * 4
    term = read_u32(data, term_off)
    if term != 0xFFFFFFFF:
        errors.append(f"STR table terminator = 0x{term:08X}, expected 0xFFFFFFFF")
    
    # g[13] -> g[12] internal pointers
    if 'g12_block' in layout:
        new_g12 = layout['g12_block']
        expected_fr = new_g12 + G12_HEADER_SIZE
        expected_chain = new_g12 + G12_HEADER_SIZE + SUPERSET_FIELD_COUNT * 10
        expected_mid = expected_chain + SUPERSET_FIELD_COUNT * 2
        
        actual_fr = read_u32(data, g13_off + 0x20)
        if actual_fr != expected_fr:
            errors.append(f"PSTR field_recs ptr = 0x{actual_fr:08X}, expected 0x{expected_fr:08X}")
        actual_chain = read_u32(data, g13_off + 0x10)
        if actual_chain != expected_chain:
            errors.append(f"PSTR chain_start ptr = 0x{actual_chain:08X}, expected 0x{expected_chain:08X}")
        actual_mid = read_u32(data, g13_off + 0x14)
        if actual_mid != expected_mid:
            errors.append(f"PSTR chain_mid ptr = 0x{actual_mid:08X}, expected 0x{expected_mid:08X}")
    
    # PSTR var_id unmask
    for off, expected in PSTR_VARID_MASKS.items():
        actual = read_u16(data, g13_off + off)
        if expected != 0x0000 and actual != expected:
            errors.append(f"PSTR +0x{off:02X} var_id = 0x{actual:04X}, expected 0x{expected:04X}")
    
    # NPD count in g[13] (at +0x44 = g[14]+0x10 offset from g[13] start)
    npd_count = data[g13_off + PSTR_NPD_COUNT_OFF]
    if npd_count < PSTR_NPD_SUPERSET_COUNT:
        errors.append(f"PSTR NPD count = {npd_count}, expected >= {PSTR_NPD_SUPERSET_COUNT}")
    
    # g[14]: NPD count + back-pointer
    g14_off = ccx_off(cur_g[14])
    npd14 = data[g14_off + 16]
    if npd14 < G14_NPD_SUPERSET_COUNT:
        errors.append(f"g[14] NPD count = {npd14}, expected >= {G14_NPD_SUPERSET_COUNT}")
    
    # g[14]+0x18 back-pointer should reference g[13]+0x24
    backptr = read_u32(data, g14_off + 0x18)
    expected_backptr = cur_g[13] + 0x24
    if backptr != expected_backptr:
        errors.append(f"g[14] back-pointer = 0x{backptr:08X}, expected 0x{expected_backptr:08X}")
    
    # g[15]+0x10 cross-reference should point to g[14]+0x1C
    g15_off = ccx_off(cur_g[15])
    g15_xref = read_u32(data, g15_off + 0x10)
    expected_xref = cur_g[14] + 0x1C
    if g15_xref != expected_xref:
        errors.append(f"g[15]+0x10 xref = 0x{g15_xref:08X}, expected 0x{expected_xref:08X} (g[14]+0x1C)")
    
    # g[12]: relocated block
    if 'g12_block' in layout:
        actual_g12 = cur_g[12]
        if actual_g12 != layout['g12_block']:
            errors.append(f"globals[12] = 0x{actual_g12:08X}, expected 0x{layout['g12_block']:08X}")
        
        new_g12_off = ccx_off(layout['g12_block'])
        tag_csl = data[new_g12_off + 9:new_g12_off + 12].decode('ascii', errors='replace')
        tag_aev = data[new_g12_off + 24 + 9:new_g12_off + 24 + 12].decode('ascii', errors='replace')
        tag_eve = data[new_g12_off + 48 + 9:new_g12_off + 48 + 12].decode('ascii', errors='replace')
        if tag_csl != "CSL":
            errors.append(f"New g[12] CSL tag = '{tag_csl}', expected 'CSL'")
        if tag_aev != "AEV":
            errors.append(f"New g[12] AEV tag = '{tag_aev}', expected 'AEV'")
        if tag_eve != "EVE":
            errors.append(f"New g[12] EVE tag = '{tag_eve}', expected 'EVE'")
        
        # Count field records
        fr_start = new_g12_off + G12_HEADER_SIZE
        field_count = 0
        for i in range(200):
            off = fr_start + i * 10
            if off + 10 > len(data):
                break
            typ = data[off]
            fid = data[off + 1]
            vid = read_u16(data, off + 2)
            if typ == 0x0D and fid in (0, 1, 2, 3):
                field_count += 1
            elif typ == 0x00 and fid in (0, 1, 2, 3) and vid == 0x7FFF:
                field_count += 1
            else:
                break
        if field_count != SUPERSET_FIELD_COUNT:
            errors.append(f"New g[12] has {field_count} field records, expected {SUPERSET_FIELD_COUNT}")
    
    # Check BRP ptr chain
    brp_ptr3 = read_u32(data, g11_off + 28)
    first_brp_str_ptr = read_u32(data, ccx_off(brp_ptr3))
    first_brp_str = data[ccx_off(first_brp_str_ptr):ccx_off(first_brp_str_ptr)+20].split(b'\x00')[0]
    if first_brp_str.decode('ascii', errors='replace') != BRP_SIGNALS[0][0]:
        errors.append(f"First BRP string = '{first_brp_str}', expected '{BRP_SIGNALS[0][0]}'")
    
    # g[21]: computation table
    g21_off = ccx_off(cur_g[21])
    g21_count = read_u16(data, g21_off)
    g21_ptr = read_u32(data, g21_off + 4)
    if g21_count != G20_SUPERSET_COUNT:
        errors.append(f"g[21] comp count = {g21_count}, expected {G20_SUPERSET_COUNT}")
    if g21_ptr != layout['g21_records']:
        errors.append(f"g[21] comp ptr = 0x{g21_ptr:08X}, expected 0x{layout['g21_records']:08X}")
    
    # g[26]: record counts and data array pointers
    g26_off = ccx_off(cur_g[26])
    for rec_idx, (sup_varids, sup_rates) in G26_DATA_PATCHES.items():
        expected_count = len(sup_varids)
        rec_off = g26_off + rec_idx * 20
        actual_count = data[rec_off]
        tag = data[rec_off + 1:rec_off + 4].decode('ascii', errors='replace')
        if actual_count != expected_count:
            errors.append(f"g[26] {tag} count = {actual_count}, expected {expected_count}")
        # Verify ptr1/ptr2 point into merge block (relocated arrays)
        ptr_key = f'g26_r{rec_idx}_varids'
        if ptr_key in layout:
            actual_ptr1 = read_u32(data, rec_off + 8)
            if actual_ptr1 != layout[ptr_key]:
                errors.append(f"g[26] {tag} ptr1 = 0x{actual_ptr1:08X}, expected 0x{layout[ptr_key]:08X}")
            rate_key = f'g26_r{rec_idx}_rates'
            actual_ptr2 = read_u32(data, rec_off + 12)
            if actual_ptr2 != layout[rate_key]:
                errors.append(f"g[26] {tag} ptr2 = 0x{actual_ptr2:08X}, expected 0x{layout[rate_key]:08X}")
    
    # g[27]: record counts and pointers
    g27_off = ccx_off(cur_g[27])
    for r, (tag, expected_cnt, tail_key) in enumerate([
        ('APN', G27_APN_SUPERSET_COUNT, 'g26_tail_apn'),
        ('CSN', G27_CSN_SUPERSET_COUNT, 'g26_tail_csn'),
        ('BRH', G27_BRH_SUPERSET_COUNT, 'g26_tail_brh'),
    ]):
        rec_off = g27_off + r * 16
        actual_cnt = data[rec_off]
        if actual_cnt != expected_cnt:
            errors.append(f"g[27] {tag} count = {actual_cnt}, expected {expected_cnt}")
        if tail_key in layout:
            actual_ptr = read_u32(data, rec_off + 8)
            if actual_ptr != layout[tail_key]:
                errors.append(f"g[27] {tag} ptr = 0x{actual_ptr:08X}, expected 0x{layout[tail_key]:08X}")
    
    # Merge block bounds
    merge_end = 0
    for key in ('str_ptrs_end', 'g12_block_end', 'g28_block_end', 
                'g21_block_end', 'g13g14_end', 'g26g27_end', 'g15_24_end'):
        if key in layout:
            merge_end = max(merge_end, ccx_off(layout[key]))
    if merge_end >= FREE_SPACE_LIMIT:
        errors.append(f"Merge block extends to CCX+0x{merge_end:05X}, past limit 0x{FREE_SPACE_LIMIT:05X}")
    
    # globals[] pointer consistency
    check_globals = [
        (11, 'g11_block'), (12, 'g12_block'), (28, 'g28_block'),
        (13, 'g13_block'), (14, 'g14_block'),
        (26, 'g26_block'), (27, 'g27_block'),
        (21, 'g21_block'),
    ]
    # Add g[15]..g[24] (except g[21] already listed)
    for i in range(15, 25):
        if i == 21:
            continue
        check_globals.append((i, f'g{i}_block'))
    
    for idx, key in check_globals:
        if key in layout:
            actual = cur_g[idx]
            if actual != layout[key]:
                errors.append(f"globals[{idx}] = 0x{actual:08X}, expected 0x{layout[key]:08X}")
    
    # g[15]+0x10 xref -> g[14]+0x1C
    if 'g15_block' in layout and 'g14_block' in layout:
        g15_off = ccx_off(cur_g[15])
        g15_xref = read_u32(data, g15_off + 0x10)
        expected_xref = cur_g[14] + 0x1C
        if g15_xref != expected_xref:
            errors.append(f"g[15]+0x10 xref = 0x{g15_xref:08X}, expected 0x{expected_xref:08X} (g[14]+0x1C)")
    
    # g[15]..g[24] internal pointer integrity
    # Verify all intra-block pointers were correctly delta-adjusted.
    # When merge block is near original location, old and new ranges overlap
    # a correctly adjusted pointer may still fall in the old range.
    # Only flag pointers in old range that are NOT also in new range.
    if 'g15_24_old_start' in layout:
        old_start = layout['g15_24_old_start']
        old_end = layout['g15_24_old_end']
        new_start = layout['g15_block']
        new_end = layout['g15_24_end']
        new_off = ccx_off(new_start)
        block_size = old_end - old_start
        stale_ptrs = 0
        # g[15]+0x10 is a known cross-reference to g[14]+0x1C - handled separately
        g15_xref_offset = 0x10  # offset within g[15], which is at block+0x0000
        for j in range(0, block_size - 3, 4):
            val = read_u32(data, new_off + j)
            # Stale = in old range but NOT in new range (would need adjustment)
            if old_start <= val < old_end and not (new_start <= val < new_end):
                if j == g15_xref_offset:
                    continue  # validated separately as g[15]+0x10 xref
                stale_ptrs += 1
        if stale_ptrs:
            errors.append(f"g[15..24] block has {stale_ptrs} un-adjusted pointers still in old range")
    
    # g[4] ACT flags
    g4_off = ccx_off(g[4])
    act_mismatches = 0
    for rec_idx in G4_ACT_PATCHES:
        rec_off = g4_off + rec_idx * 28
        actual = read_u16(data, rec_off)
        if not (actual & 0x0001):
            act_mismatches += 1
    if act_mismatches:
        errors.append(f"g[4] ACT bit0: {act_mismatches} records missing ACT")
    
    # g[8] ACT flags
    g8_off = ccx_off(g[8])
    g8_mismatches = 0
    for rec_idx in G8_ACT_PATCHES:
        rec_off = g8_off + rec_idx * 20
        actual = read_u16(data, rec_off)
        if not (actual & 0x0001):
            g8_mismatches += 1
    if g8_mismatches:
        errors.append(f"g[8] ACT bit0: {g8_mismatches} records missing ACT")

    return errors


def detect_image_type(data):
    """Detect whether input is a CCX-only image or a full flash dump.
    
    Returns ('ccx', ccx_offset, ccx_size) or ('full', ccx_offset, ccx_size).
    """
    size = len(data)
    
    if size == CCX_SIZE:
        # Verify globals[0] points to CCX_BASE
        g0 = read_u32(data, 0x108)
        if g0 == CCX_BASE:
            return ('ccx', 0, CCX_SIZE)
        raise CCXMergeError(
            f"File is {CCX_SIZE} bytes but globals[0] = 0x{g0:08X}, "
            f"expected 0x{CCX_BASE:08X}"
        )
    
    if size == FULL_FLASH_SIZE:
        g0 = read_u32(data, CCX_OFFSET + 0x108)
        if g0 == CCX_BASE:
            return ('full', CCX_OFFSET, CCX_SIZE)
        raise CCXMergeError(
            f"File is 1MB but globals[0] at offset 0x{CCX_OFFSET + 0x108:X} "
            f"= 0x{g0:08X}, expected 0x{CCX_BASE:08X}"
        )
    
    cmx_size = CCX_SIZE + 0xC0000  # 240KB + 768KB = 0xFC000
    if size == cmx_size:
        g0 = read_u32(data, 0x108)
        if g0 == CCX_BASE:
            return ('cmx', 0, CCX_SIZE)
        raise CCXMergeError(
            f"File is CMX-sized ({cmx_size} bytes) but globals[0] = 0x{g0:08X}"
        )
    
    # Try to find CCX by scanning for globals[0] signature
    for candidate_off in range(0, min(size, FULL_FLASH_SIZE), 0x1000):
        if candidate_off + CCX_SIZE > size:
            break
        try:
            g0 = read_u32(data, candidate_off + 0x108)
            if g0 == CCX_BASE:
                return ('raw', candidate_off, CCX_SIZE)
        except:
            continue
    
    raise CCXMergeError(
        f"Cannot identify image type (size={size} bytes). "
        f"Expected {CCX_SIZE} (CCX), {cmx_size} (CMX), or {FULL_FLASH_SIZE} (full flash)."
    )


def merge_ccx_image(data, force=False, verbose=False):
    """Merge universal EDF signals into a firmware image in-place.

    Args:
        data: bytearray (modified in-place)
        force: proceed even if variant is unknown
        verbose: print progress to stdout

    Returns:
        list of patch description strings

    Raises:
        CCXMergeError on failure
    """
    def log(msg):
        if verbose:
            print(msg)

    img_type, ccx_start, ccx_size = detect_image_type(data)
    ccx = bytearray(data[ccx_start:ccx_start + ccx_size])
    if len(ccx) != CCX_SIZE:
        raise CCXMergeError("CCX region is %d bytes, expected %d" % (len(ccx), CCX_SIZE))

    globals_off = find_globals(ccx)
    g = read_globals(ccx, globals_off)

    variant, sig_count = detect_variant(ccx, g)
    log("EDF merge: %s (%d STR signals)" % (variant, sig_count))

    if variant.startswith("Unknown") and not force:
        raise CCXMergeError("Unknown variant '%s'. Use force=True to proceed." % variant)

    # Capture old signal counts before patching
    g11_off = ccx_off(g[11])
    old_brp = ccx[g11_off + 8]
    old_pld = ccx[g11_off + 32 + 8]
    old_sad = ccx[g11_off + 64 + 8]
    old_g21 = read_u16(ccx, ccx_off(g[21]))

    g12_headers, old_g12_field_count, old_g12_range = parse_g12_block(ccx, g)
    g12_block = build_g12_block(g12_headers)
    log("  g[12]: %d -> %d field records (%dB)" % (old_g12_field_count, SUPERSET_FIELD_COUNT, len(g12_block)))

    free_start = find_free_space(ccx, g)
    free_end = FREE_SPACE_LIMIT

    relocated_indices = [11, 12, 13, 14] + list(range(15, 25)) + [26, 27, 28]
    merge_start = min(ccx_off(g[i]) for i in relocated_indices
                      if g[i] >= CCX_BASE and g[i] < CCX_BASE + CCX_SIZE)

    reclaimed_set = set(relocated_indices)
    for i in range(29):
        if i in reclaimed_set:
            continue
        gval = g[i]
        if gval == 0xFFFFFFFF or gval < CCX_BASE:
            continue
        goff = ccx_off(gval)
        if merge_start <= goff < free_start:
            raise CCXMergeError("Non-relocated g[%d] at CCX+0x%05X conflicts with merge target" % (i, goff))

    avail_size = free_end - merge_start
    merge_block, layout = build_merge_block(merge_start, g12_block, source_data=ccx, g=g)
    log("  merge block: %d bytes at CCX+0x%05X (%dB free)" % (layout['total_size'], merge_start, avail_size - layout['total_size']))

    if layout['total_size'] > avail_size:
        raise CCXMergeError("Merge block (%dB) exceeds available space (%dB)" % (layout['total_size'], avail_size))

    # erase relocated data, write merge block, apply patches
    for i in range(merge_start, free_start):
        if ccx[i] != ERASED:
            ccx[i] = ERASED

    ccx[merge_start:merge_start + len(merge_block)] = merge_block
    patches = apply_patches(ccx, g, layout)

    errors = validate_result(ccx, g, layout)
    if errors:
        raise CCXMergeError("Validation failed:\n  " + "\n  ".join(errors))

    update_ccx_crc(ccx)

    data[ccx_start:ccx_start + ccx_size] = ccx

    print("EDF merge: STR %d->%d, BRP %d->%d, PLD %d->%d, g12 %d->%d, g21 %d->%d"
          % (sig_count, len(STR_SIGNAL_NAMES), old_brp, len(BRP_SIGNALS),
             old_pld, len(PLD_SIGNALS), old_g12_field_count, SUPERSET_FIELD_COUNT,
             old_g21, G20_SUPERSET_COUNT))
    return patches


def main():
    import argparse
    parser = argparse.ArgumentParser(
        description="Merge universal EDF signals into SX567 CCX image"
    )
    parser.add_argument("input", help="Input binary: CCX, CMX, or full 1MB flash dump")
    parser.add_argument("-o", "--output", help="Output file (default: <input>.merged.bin)")
    parser.add_argument("-v", "--verbose", action="store_true", help="Show detailed patch list")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be done without writing")
    parser.add_argument("--force", action="store_true", help="Skip variant detection warnings")
    args = parser.parse_args()

    input_path = Path(args.input)
    full_data = bytearray(input_path.read_bytes())

    if args.dry_run:
        print("DRY RUN (no output written)")
        return

    patches = merge_ccx_image(full_data, force=args.force, verbose=args.verbose)

    if args.verbose:
        print("\nPatches (%d):" % len(patches))
        for p in patches:
            print("  %s" % p)

    out_path = Path(args.output) if args.output else input_path.with_suffix('.merged.bin')
    out_path.write_bytes(full_data)


if __name__ == '__main__':
    main()

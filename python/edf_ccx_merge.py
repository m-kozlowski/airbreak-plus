#!/usr/bin/env python3
"""
Extends SX567 and SX584 EDF layouts with a shared signal catalogue, omitting
fields whose variables or calculation sources are absent from the firmware.

This helper uses the shared ASFirmware framework from lib/as10_firmware.py for
firmware layout, globals[], UART name resolution, and CRC finalization.
"""

import struct
from pathlib import Path
from typing import NamedTuple, Optional

from lib.as10_firmware import ASFirmware


PERIODIC_HEADER_SIZE = 32
STR_HEADER_SIZE = 36
LIVE_HEADER_SIZE = 20
CHANGE_HEADER_SIZE = 16
NPD_HEADER_SIZE = 28
STR_CALCULATION = struct.Struct('<BBHHBBH')
DERIVED_VARIABLE_RULE = struct.Struct('<HHIII')


# g[13] calculation fields; source names are resolved when serializing.
class STRCalculation(NamedTuple):
    kind: int = 0
    source_a: Optional[str] = None
    source_b: Optional[str] = None
    percentile: int = 0
    gate: int = 0
    reset: int = 0
    param_00: int = 0x0D


_DIRECT = STRCalculation()
_DIRECT_RESET = STRCalculation(reset=1)
_DIRECT_RESET_GATE2 = STRCalculation(gate=2, reset=1)
_MASK_EVENTS = STRCalculation(param_00=0)

def _percentile(var_name, percentile, gate):
    # Record bytes +6/+7 are a percentile and sampling gate (1=ZTE, 2=ZLE).
    return STRCalculation(kind=2, source_a=var_name, percentile=percentile,
                          gate=gate, reset=1)

def _event_rate(var_name, duration=None):
    return STRCalculation(kind=1, source_a=var_name, source_b=duration, reset=2)

def _percentage(var_a, var_b):
    return STRCalculation(kind=3, source_a=var_a, source_b=var_b, gate=2, reset=1)


BRP_SIGNALS = [
    ("Flow.40ms",       "RFL", 1500),  # 25 Hz
    ("Press.40ms",      "MKP", 1500),
    ("TrigCycEvt.40ms", "TCV", 1500),
    ("Crc16",           "DCR", 1),
]

PLD_SIGNALS = [
    ("MaskPress.2s", "MKF", 30),   # 0.5 Hz
    ("Press.2s",     "MKI", 30),
    ("EprPress.2s",  "MKE", 30),
    ("Leak.2s",      "LKF", 30),
    ("RespRate.2s",  "RRR", 30),
    ("TidVol.2s",    "TDD", 30),
    ("MinVent.2s",   "MV5", 30),
    ("TgtVent.2s",   "TGT", 30),
    ("IERatio.2s",   "IER", 30),
    ("Snore.2s",     "SNI", 30),
    ("FlowLim.2s",   "FFL", 30),
    ("B5ITime.2s",   "IN5", 30),
    ("B5ETime.2s",   "EX5", 30),
    ("Ti.2s",        "INT", 30),
    ("AlvMinVent.2s", "AAV", 30),
    ("CLRatio.2s",   "RCR", 30),
    ("TRRatio.2s",   "RTR", 30),
    ("Crc16",        "DCR", 1),
]

SAD_SIGNALS = [
    ("Pulse.1s", "HRT", 60),  # 1 Hz
    ("SpO2.1s",  "SAO", 60),
    ("Crc16",    "DCR", 1),
]

CSL_SIGNALS = ["ETI", "CSZ", "CSR", "DCR"]

# STR.edf fields: (EDF label, UART name, samples per record, calculation).
STR_SIGNALS = [
    ("Date",                 "LSD",  1, _DIRECT),
    ("MaskOn",               "ONT", 10, _MASK_EVENTS),
    ("MaskOff",              "OFT", 10, _MASK_EVENTS),
    ("MaskEvents",           "MSE",  1, _MASK_EVENTS),
    ("Duration",             "OND",  1, _DIRECT),
    ("OnDuration",           "THD",  1, _DIRECT),
    ("PatientHours",         "PHM",  1, _DIRECT),
    ("Mode",                 "MOP",  1, _DIRECT),
    ("S.RampEnable",         "RMA",  1, _DIRECT),
    ("S.RampTime",           "RMT",  1, _DIRECT),
    ("S.C.StartPress",       "STP",  1, _DIRECT),
    ("S.C.Press",            "IPC",  1, _DIRECT),
    ("S.EPR.ClinEnable",     "EPA",  1, _DIRECT),
    ("S.EPR.EPREnable",      "EPX",  1, _DIRECT),
    ("S.EPR.Level",          "EPR",  1, _DIRECT),
    ("S.EPR.EPRType",        "EPT",  1, _DIRECT),
    ("S.BL.StartPress",      "EPS",  1, _DIRECT),
    ("S.BL.IPAP",            "IPP",  1, _DIRECT),
    ("S.BL.EPAP",            "EPP",  1, _DIRECT),
    ("S.EasyBreathe",        "EBE",  1, _DIRECT),
    ("S.VA.StartPress",      "STV",  1, _DIRECT),
    ("S.VA.MaxIPAP",         "MXI",  1, _DIRECT),
    ("S.VA.MinEPAP",         "MNE",  1, _DIRECT),
    ("S.VA.PS",              "SPT",  1, _DIRECT),
    ("S.RiseEnable",         "RSC",  1, _DIRECT),
    ("S.RiseTime",           "RST",  1, _DIRECT),
    ("S.Cycle",              "VCS",  1, _DIRECT),
    ("S.Trigger",            "VTS",  1, _DIRECT),
    ("S.TiMax",              "ITX",  1, _DIRECT),
    ("S.TiMin",              "ITN",  1, _DIRECT),
    ("S.AS.Comfort",         "AFC",  1, _DIRECT),
    ("S.AS.StartPress",      "STU",  1, _DIRECT),
    ("S.AS.MaxPress",        "MPA",  1, _DIRECT),
    ("S.AS.MinPress",        "MPI",  1, _DIRECT),
    ("S.AV.StartPress",      "STE",  1, _DIRECT),
    ("S.AV.EPAP",            "EEP",  1, _DIRECT),
    ("S.AV.MaxPS",           "MXS",  1, _DIRECT),
    ("S.AV.MinPS",           "MNS",  1, _DIRECT),
    ("S.AA.StartPress",      "EAS",  1, _DIRECT),
    ("S.AA.MaxEPAP",         "EAX",  1, _DIRECT),
    ("S.AA.MinEPAP",         "EAI",  1, _DIRECT),
    ("S.AA.MaxPS",           "AXS",  1, _DIRECT),
    ("S.AA.MinPS",           "ANS",  1, _DIRECT),
    ("S.SmartStart",         "SST",  1, _DIRECT),
    ("S.PtAccess",           "ACC",  1, _DIRECT),
    ("S.ABFilter",           "ABF",  1, _DIRECT),
    ("S.LeakAlert",          "ALR",  1, _DIRECT),
    ("S.Mask",               "MSK",  1, _DIRECT),
    ("S.Tube",               "TBT",  1, _DIRECT),
    ("S.ClimateControl",     "CCO",  1, _DIRECT),
    ("S.HumEnable",          "HMX",  1, _DIRECT),
    ("S.HumLevel",           "HMS",  1, _DIRECT),
    ("S.TempEnable",         "HTX",  1, _DIRECT),
    ("S.Temp",               "HTS",  1, _DIRECT),
    ("S.ExternalHum",        "HME",  1, _DIRECT),
    ("HeatedTube",           "HTB",  1, _DIRECT),
    ("Humidifier",           "HUM",  1, _DIRECT),
    ("BlowPress.95",         "BP9",  1, _percentile("BPA", 95, 1)),
    ("BlowPress.5",          "BP5",  1, _percentile("BPA", 5, 1)),
    ("Flow.95",              "RF9",  1, _percentile("RFA", 95, 1)),
    ("Flow.5",               "RF5",  1, _percentile("RFA", 5, 1)),
    ("BlowFlow.50",          "BFM",  1, _percentile("AFL", 50, 1)),
    ("AmbHumidity.50",       "ABM",  1, _percentile("ABH", 50, 1)),
    ("HumTemp.50",           "HHM",  1, _percentile("HPT", 50, 1)),
    ("HTubeTemp.50",         "HTM",  1, _percentile("HTT", 50, 1)),
    ("HTubePow.50",          "TPM",  1, _percentile("TPA", 50, 1)),
    ("HumPow.50",            "HPM",  1, _percentile("PPA", 50, 1)),
    ("SpO2.50",              "SOM",  1, _percentile("SAV", 50, 2)),
    ("SpO2.95",              "SO9",  1, _percentile("SAV", 95, 2)),
    ("SpO2.Max",             "SOX",  1, _percentile("SAV", 100, 2)),
    ("SpO2Thresh",           "SAU",  1, _DIRECT_RESET_GATE2),
    ("CSR",                  "CSD",  1, _DIRECT_RESET),
    ("SpontCyc%",            "VCR",  1, _percentage("TBB", "TBC")),
    ("MaskPress.50",         "MSP",  1, _percentile("MAP", 50, 1)),
    ("MaskPress.95",         "PM9",  1, _percentile("MAP", 95, 1)),
    ("MaskPress.Max",        "PMA",  1, _percentile("MAP", 100, 1)),
    ("TgtIPAP.50",           "PIM",  1, _percentile("AIP", 50, 2)),
    ("TgtIPAP.95",           "PI9",  1, _percentile("AIP", 95, 2)),
    ("TgtIPAP.Max",          "PIA",  1, _percentile("AIP", 100, 2)),
    ("TgtEPAP.50",           "PEM",  1, _percentile("AEP", 50, 2)),
    ("TgtEPAP.95",           "PE9",  1, _percentile("AEP", 95, 2)),
    ("TgtEPAP.Max",          "PEA",  1, _percentile("AEP", 100, 2)),
    ("Leak.50",              "LKM",  1, _percentile("LKP", 50, 2)),
    ("Leak.95",              "LK9",  1, _percentile("LKP", 95, 2)),
    ("Leak.70",              "LK7",  1, _percentile("LKP", 70, 2)),
    ("Leak.Max",             "LMX",  1, _percentile("LKP", 100, 2)),
    ("MinVent.50",           "VTM",  1, _percentile("MVT", 50, 2)),
    ("MinVent.95",           "VT9",  1, _percentile("MVT", 95, 2)),
    ("MinVent.Max",          "VTA",  1, _percentile("MVT", 100, 2)),
    ("RespRate.50",          "RRM",  1, _percentile("RR1", 50, 2)),
    ("RespRate.95",          "RR9",  1, _percentile("RR1", 95, 2)),
    ("RespRate.Max",         "RRA",  1, _percentile("RR1", 100, 2)),
    ("TidVol.50",            "TVM",  1, _percentile("ATI", 50, 2)),
    ("TidVol.95",            "TV9",  1, _percentile("ATI", 95, 2)),
    ("TidVol.Max",           "TVA",  1, _percentile("ATI", 100, 2)),
    ("IERatio.50",           "IEM",  1, _percentile("AIE", 50, 2)),
    ("IERatio.95",           "IE9",  1, _percentile("AIE", 95, 2)),
    ("IERatio.Max",          "IEA",  1, _percentile("AIE", 100, 2)),
    ("Ti.50",                "ISM",  1, _percentile("MIS", 50, 2)),
    ("Ti.95",                "IS9",  1, _percentile("MIS", 95, 2)),
    ("Ti.Max",               "ISA",  1, _percentile("MIS", 100, 2)),
    ("TgtVent.50",           "VAM",  1, _percentile("MTT", 50, 2)),
    ("TgtVent.95",           "VA9",  1, _percentile("MTT", 95, 2)),
    ("TgtVent.Max",          "VAA",  1, _percentile("MTT", 100, 2)),
    ("AHI",                  "AHI",  1, _event_rate("AHC")),
    ("HI",                   "HIS",  1, _event_rate("HYC")),
    ("AI",                   "AIS",  1, _event_rate("AIC")),
    ("OAI",                  "CLI",  1, _event_rate("CAC")),
    ("CAI",                  "OPI",  1, _event_rate("OAC")),
    ("UAI",                  "UAI",  1, _event_rate("UAC")),
    ("RIN",                  "RIN",  1, _event_rate("RDC")),
    ("Fault.Device",         "SYS",  1, _DIRECT),
    ("Fault.Alarm",          "SYT",  1, _DIRECT),
    ("Fault.Humidifier",     "SYC",  1, _DIRECT),
    ("Fault.HeatedTube",     "SYH",  1, _DIRECT),
    ("S.BL.BackupRate",      "BRR",  1, _DIRECT),
    ("S.BL.RespRate",        "RRT",  1, _DIRECT),
    ("S.Ti",                 "ITT",  1, _DIRECT),
    ("SpontTrig%",           "VSR",  1, _percentage("SBC", "SBD")),
    ("Crc16",                "DCR",  1, _DIRECT),
]

# Additional SX584 fields
LUMIS_STR_SIGNALS = [
    ("S.RampDownEnable",     "RDA",  1, _DIRECT),
    ("S.BL.IBR",             "VBE",  1, _DIRECT),
    ("S.BL.TgtRR",           "TBR",  1, _DIRECT),
    ("S.i.StartPress",       "IVS",  1, _DIRECT),
    ("S.i.EPAP",             "EPI",  1, _DIRECT),
    ("S.i.EPAPAuto",         "IEU",  1, _DIRECT),
    ("S.i.MaxPS",            "WPA",  1, _DIRECT),
    ("S.i.MinPS",            "WPM",  1, _DIRECT),
    ("S.i.MinEPAP",          "IMN",  1, _DIRECT),
    ("S.i.MaxEPAP",          "IMX",  1, _DIRECT),
    ("S.i.Height",           "PHT",  1, _DIRECT),
    ("S.i.AlvMinVent",       "WMV",  1, _DIRECT),
    ("S.i.RespRate",         "IBR",  1, _DIRECT),
    ("ODIThreshold",         "ODT",  1, _DIRECT),
    ("NVMask.Alm.En",        "NMF",  1, _DIRECT),
    ("HiLeak.Alm.En",        "HLE",  1, _DIRECT),
    ("LowMV.Alm.Thres",      "LMA",  1, _DIRECT),
    ("LowMV.Alm.En",         "LMO",  1, _DIRECT),
    ("Apnea.Alm.Thres",      "APX",  1, _DIRECT),
    ("Apnea.Alm.En",         "APO",  1, _DIRECT),
    ("Alm.Vol",              "ALV",  1, _DIRECT),
    ("Spo2.Alm.Thres",       "SPX",  1, _DIRECT),
    ("Spo2.Alm.En",          "SPO",  1, _DIRECT),
    ("HeartRate.50",         "HR5",  1, _percentile("HAV", 50, 2)),
    ("HeartRate.Max",        "HRX",  1, _percentile("HAV", 100, 2)),
    ("HeartRate.95",         "HRM",  1, _percentile("HAV", 95, 2)),
    ("SpO2.Min",             "SOZ",  1, _percentile("SAV", 0, 2)),
    ("AlvMinVent.50",        "AVM",  1, _percentile("MAV", 50, 2)),
    ("AlvMinVent.95",        "AV9",  1, _percentile("MAV", 95, 2)),
    ("AlvMinVent.Max",       "AVA",  1, _percentile("MAV", 100, 2)),
    ("ODI",                  "ODI",  1, _event_rate("ODC", "OVD")),
    ("Oxy.Dur",              "ODD",  1, _DIRECT_RESET),
]

NPD_SIGNALS = ['LRP', 'LRE', 'LKP', 'MVT', 'ATI', 'RR1', 'SAV', 'AIE',
               'RCR', 'RTR', 'HAV', 'HMI', 'HMA', 'SMO']

# These channels use the same field encoding on both families. Other event
# and live channels retain their native composition, including Lumis AEV/MSD.
LIVE_SIGNALS = {
    'TCE': ['TCV', 'MKP', 'RFL', 'LYK'],
    'PBT': ['MV5', 'TGT', 'RRR', 'LKF', 'TIP', 'TEP', 'AAV'],
    'APN': ['AET', 'DUR'],
    'CSN': ['CET', 'CSR'],
    'BRH': ['TID', 'ATP', 'INT', 'EXT'],
}

# g[21] rules for calculating summary variables from EEPROM SESSION/STR history.
# Entries: (destination name, source name, operation, upper bound, lower bound).
DERIVED_VARIABLE_RULES = [
    ("WRD", "OND", 0x00000000, 0xFFFFFFFF, 0xFFFFFFFF),
    ("ZAI", "PI9", 0x00000000, 0xFFFFFFFF, 0xFFFFFFFF),
    ("ZAE", "PE9", 0x00000000, 0xFFFFFFFF, 0xFFFFFFFF),
    ("LRS", "LK9", 0x00000000, 0xFFFFFFFF, 0xFFFFFFFF),
    ("ZAT", "TVM", 0x00000000, 0xFFFFFFFF, 0xFFFFFFFF),
    ("ZAR", "RRM", 0x00000000, 0xFFFFFFFF, 0xFFFFFFFF),
    ("ZAM", "VTM", 0x00000000, 0xFFFFFFFF, 0xFFFFFFFF),
    ("ZAZ", "ISM", 0x00000000, 0xFFFFFFFF, 0xFFFFFFFF),
    ("ZA1", "IEM", 0x00000000, 0xFFFFFFFF, 0xFFFFFFFF),
    ("ZA2", "VAM", 0x00000000, 0xFFFFFFFF, 0xFFFFFFFF),
    ("ZAY", "VCR", 0x00000000, 0xFFFFFFFF, 0xFFFFFFFF),
    ("ZAS", "VSR", 0x00000000, 0xFFFFFFFF, 0xFFFFFFFF),
    ("ARD", "AHI", 0x00000000, 0xFFFFFFFF, 0xFFFFFFFF),
    ("TRD", "AIS", 0x00000000, 0xFFFFFFFF, 0xFFFFFFFF),
    ("CRD", "OPI", 0x00000000, 0xFFFFFFFF, 0xFFFFFFFF),
    ("VRD", "OND", 0x00000100, 0xFFFFFFFF, 0x000000F0),
    ("DRD", "OND", 0x00000100, 0xFFFFFFFF, 0xFFFFFFFF),
    ("XRD", "OND", 0x00000200, 0xFFFFFFFF, 0xFFFFFFFF),
    ("AQD", "AHI", 0x00000300, 0xFFFFFFFF, 0xFFFFFFFF),
    ("MQD", "LK7", 0x00000300, 0xFFFFFFFF, 0xFFFFFFFF),
    ("UQD", "OND", 0x00000300, 0xFFFFFFFF, 0xFFFFFFFF),
    ("ZRH", "SYC", 0x00000300, 0xFFFFFFFF, 0xFFFFFFFF),
]


# Explicit activations in addition to those collected from STR calculations,
# NPD fields and derived-variable rules. Descriptor types are resolved by name.
REPORTING_ACTIVATION = [
    # Therapy settings captured by the reporting channels.
    "MPA", "IPP", "EPR", "PSP", "MPI", "STU", "MNE", "MXI", "SPT", "STV",
    "EPP", "EPS", "RST", "ITN", "ITX", "EEP", "MNS", "MXS", "STE", "EAX",
    "EAI", "ANS", "AXS", "EAS", "EBE", "RSC", "AFC", "ALR", "HME", "EPA",
    "EPX", "EPT", "VCS", "VTS",
    # Pressure, ventilation and breath-timing signals and statistics.
    "MTT", "TGT", "ATP", "VA9", "VAA", "VAM", "IE9", "IEA", "IEM", "IER",
    "AIE", "IN5", "EX5", "INT", "EXT", "ISM", "IS9", "ISA", "MIS", "AAV", "MAV",
    # Snore and flow limitation.
    "SNI", "FFL",
    # Respiratory event counters and indexes.
    "RIN", "CLI", "OPI", "UAI", "CAC", "OAC", "RDC",
    # Trigger/cycle events, counters and ratios.
    "TCV", "CYI", "TRI", "TCT", "SBD", "TBB", "TBC", "VCR", "RCR", "RTR",
    # CSR events, timestamps and accumulated durations.
    "CSR", "CSD", "CSZ", "CET", "CSG", "CSC", "CSE", "CST", "CSS",
    # History summary outputs.
    "ZAI", "ZAE", "ZAT", "ZA1", "ZAM", "ZAR", "ZAZ", "ZA2", "ZAY", "CRD", "ZAV",
    # Settings-group change trackers.
    "AGT", "DGT", "IGT", "EGT", "QXI", "VGT", "XGT",
    # Blocked-tube event reporting.
    "ZLM",
]


class CCXMergeError(Exception):
    pass


class CCXImage(bytearray):
    def __init__(self, asf):
        super().__init__(asf.read_bytes(asf.ccx_off, asf.ccx_size))
        self.base = asf.FLASH_BASE + asf.ccx_off

    def u16(self, off):
        return struct.unpack_from('<H', self, off)[0]

    def u32(self, off):
        return struct.unpack_from('<I', self, off)[0]

    def offset(self, addr):
        """Convert an absolute flash address to an offset in this CCX buffer."""
        if not self.base <= addr < self.base + len(self):
            raise CCXMergeError(f"Address 0x{addr:08X} outside CCX range")
        return addr - self.base

    def address(self, off):
        return self.base + off


def build_field_record(rec, var_id):
    source_a = var_id(rec.source_a) if rec.source_a is not None else 0x7FFF
    source_b = var_id(rec.source_b) if rec.source_b is not None else 0x7FFF
    return STR_CALCULATION.pack(rec.param_00, rec.kind, source_a, source_b,
                                rec.percentile, rec.gate, rec.reset)


def record_sources(rec):
    """Return variable names referenced by a STR calculation, excluding parameters."""
    return tuple(name for name in (rec.source_a, rec.source_b) if name is not None)


def channel_headers(data, addr, count, stride, tag_offset):
    """Index a known channel-header array by its three-letter tags."""
    result = {}
    for i in range(count):
        off = data.offset(addr) + i * stride
        tag = bytes(data[off + tag_offset:off + tag_offset + 3])
        if len(tag) != 3 or not all(65 <= c <= 90 for c in tag):
            raise CCXMergeError(f"Invalid channel tag at CCX+0x{off:05X}")
        tag = tag.decode('ascii')
        if tag in result:
            raise CCXMergeError(f"Duplicate channel tag {tag}")
        result[tag] = off
    return result


def firmware_layout(asf, data, g):
    """Select the CDX channel-header ABI and verify its CCX tags."""
    if asf.cdx_ver.startswith('SX567-') and asf.ccx_size == 0x3C000:
        event_stride, live_count = 24, 8
    elif asf.cdx_ver.startswith('SX584-') and asf.ccx_size == 0x1C000:
        event_stride, live_count = 28, 9
    else:
        raise CCXMergeError(f"Unsupported EDF layout: {asf.cdx_ver}")
    # globals index -> (header count, header size).
    tables = {
        11: (3, PERIODIC_HEADER_SIZE),
        12: (3, event_stride),
        13: (1, STR_HEADER_SIZE),
        26: (live_count, LIVE_HEADER_SIZE),
        27: (3, CHANGE_HEADER_SIZE),
        28: (1, LIVE_HEADER_SIZE),
    }
    periodic = channel_headers(data, g[11], *tables[11], 9)
    events = channel_headers(data, g[12], *tables[12], 9)
    live = channel_headers(data, g[26], *tables[26], 1)
    changes = channel_headers(data, g[27], *tables[27], 1)
    if set(periodic) != {'BRP', 'PLD', 'SAD'} or set(events) != {'CSL', 'AEV', 'EVE'}:
        raise CCXMergeError("Unexpected periodic/event channel layout")
    if not {'TCE', 'PBT', 'SSK'} <= live.keys() or set(changes) != {'APN', 'CSN', 'BRH'}:
        raise CCXMergeError("Unexpected live channel layout")
    return dict(tables=tables,
                periodic=periodic, events=events, live=live, changes=changes)


def stream_objects(data, g, abi):
    """Return exact owned ranges, including shared arrays but excluding padding."""
    spans = set()
    limit = len(data) - 2

    def add(addr, size):
        off = data.offset(addr)
        if size < 0 or off + size > limit:
            raise CCXMergeError(f"Stream object at 0x{addr:08X} exceeds CCX data")
        if size:
            spans.add((off, off + size))
        return off

    def array(slot, count, stride):
        return add(data.u32(slot), count * stride) if count else None

    for idx, (records, stride) in abi['tables'].items():
        base = add(g[idx], records * stride)
        for i in range(records):
            off = base + i * stride
            count = data[off + 8] if idx in (11, 12, 13) else data[off]
            array(off + (16 if idx in (11, 12, 13) else 8), count, 2)
            if idx in (26, 28):
                array(off + 12, count, 2)
            if idx in (11, 13):
                array(off + 20, count, 2)
                labels = array(off + 28, count, 4)
                for j in range(count):
                    addr = data.u32(labels + j * 4)
                    start = data.offset(addr)
                    end = data.find(b'\x00', start, limit)
                    if end < 0:
                        raise CCXMergeError(f"Unterminated EDF label at 0x{addr:08X}")
                    add(addr, end - start + 1)
                if idx == 13:
                    array(off + 32, count, STR_CALCULATION.size)
                    if data.u32(labels + count * 4) == 0xFFFFFFFF:
                        add(data.address(labels + count * 4), 4)

    off = add(g[14], NPD_HEADER_SIZE)
    array(off + 24, data[off + 16], 2)
    off = add(g[21], 8)
    array(off + 4, data.u32(off), DERIVED_VARIABLE_RULE.size)
    return spans


def mask_ranges(mask, value):
    """Yield contiguous ranges marked with the requested byte value."""
    start = 0
    while start < len(mask):
        start = mask.find(bytes([value]), start)
        if start < 0:
            break
        end = start + 1
        while end < len(mask) and mask[end] == value:
            end += 1
        yield start, end
        start = end


def reclaim_stream_objects(data, old_objects, live_objects, external_refs=()):
    """Erase replaced objects, retaining shared arrays and externally referenced data."""
    retired = bytearray(len(data))
    for start, end in old_objects:
        retired[start:end] = b'\x01' * (end - start)
    owned = bytes(retired)
    for start, end in live_objects:
        retired[start:end] = b'\x00' * (end - start)

    # A previous patch may have added another reference to an old object.
    # Retaining its whole target also makes its outgoing references live.
    # This scan only prevents erasure; it never interprets or rewrites words.
    refs = [(off, data.u32(off) - data.base)
            for off in range(0, len(data) - 3, 2)
            if data.base <= data.u32(off) < data.base + len(data) - 2]
    refs.extend((None, target) for target in external_refs if 0 <= target < len(data))
    changed = True
    while changed:
        changed = False
        for slot, target in refs:
            if owned[target] and (slot is None or not any(retired[slot:slot + 4])):
                for start, end in old_objects:
                    if start <= target < end and any(retired[start:end]):
                        retired[start:end] = b'\x00' * (end - start)
                        changed = True

    for start, end in mask_ranges(retired, 1):
        data[start:end] = b'\xFF' * (end - start)
    return retired


def build_merge_block(asf, data, g, abi, start):
    """Build arrays and explicit header writes without relocating header tables."""
    available = asf.var_ids_by_name()
    by_id = {vid: name for name, vid in available.items()}
    block = bytearray()
    writes = {}
    omitted = []
    counts = {}
    strings = {}
    activated = set()
    layout = dict(writes=writes, omitted=omitted, counts=counts, start=start)

    def append(raw):
        block.extend(b'\x00' * (-len(block) % 4))
        addr = data.address(start + len(block))
        block.extend(raw)
        return addr

    def append_u16_array(values):
        values = list(values)
        return append(struct.pack('<' + 'H' * len(values), *values))

    def selected(label, names):
        missing = sorted(set(names) - available.keys())
        if missing:
            omitted.append((label, missing))
            return False
        return True

    def read_u16_array(off, ptr_field, count):
        pos = data.offset(data.u32(off + ptr_field))
        return [data.u16(pos + i * 2) for i in range(count)]

    def native_names(off, ptr_field, count):
        return [by_id[vid] for vid in read_u16_array(off, ptr_field, count)]

    def require_native(native, supported, tag, excluded=()):
        extra = set(native) - set(supported) - set(excluded)
        if extra:
            raise CCXMergeError(f"{tag}: catalogue would remove native fields: {sorted(extra)}")

    def labels(off, count):
        ptr = data.offset(data.u32(off + 28))
        result = []
        for i in range(count):
            text = data.offset(data.u32(ptr + i * 4))
            result.append(bytes(data[text:data.index(0, text)]).decode('ascii'))
        return result

    def write_edf(tag, off, size, rows, calculations=None, excluded=()):
        old_count = data[off + 8]
        require_native(labels(off, old_count), [r[0] for r in rows], tag, excluded)
        if not rows or rows[-1][1] != 'DCR' or len(rows) > 255:
            raise CCXMergeError(f"{tag}: invalid field count or final CRC field")
        hdr = bytearray(data[off:off + size])
        hdr[8] = len(rows)
        struct.pack_into('<I', hdr, 16, append_u16_array(available[name] for _, name, _ in rows))
        struct.pack_into('<I', hdr, 20, append_u16_array(samples for _, _, samples in rows))
        pointers = []
        for label, _, _ in rows:
            if label not in strings:
                strings[label] = append(label.encode('ascii') + b'\x00')
            pointers.append(strings[label])
        if tag == 'STR':
            pointers.append(0xFFFFFFFF)
        struct.pack_into('<I', hdr, 28, append(struct.pack('<' + 'I' * len(pointers), *pointers)))
        if calculations is not None:
            struct.pack_into('<I', hdr, 32, append(b''.join(calculations)))
        writes[off] = bytes(hdr)
        counts[tag] = (old_count, len(rows))

    for tag, specs in (('BRP', BRP_SIGNALS), ('PLD', PLD_SIGNALS), ('SAD', SAD_SIGNALS)):
        rows = [row for row in specs if selected(tag + '/' + row[0], [row[1]])]
        write_edf(tag, abi['periodic'][tag], PERIODIC_HEADER_SIZE, rows)

    # SX584 includes additional STR settings and statistics.
    str_signals = list(STR_SIGNALS)
    excluded_str = []
    if asf.cdx_ver.startswith('SX584-'):
        str_signals[-1:-1] = LUMIS_STR_SIGNALS
    else:
        excluded_str = [label for label, _, _, _ in LUMIS_STR_SIGNALS]

    str_rows, calculations = [], []
    for label, name, samples, rec in str_signals:
        sources = record_sources(rec)
        if not selected('STR/' + label, (name,) + sources):
            continue
        str_rows.append((label, name, samples))
        calculations.append(build_field_record(rec, available.__getitem__))
        if sources:
            activated.update((name,) + sources)
    write_edf('STR', data.offset(g[13]), STR_HEADER_SIZE, str_rows, calculations, excluded_str)

    # Preserve the family-specific event schemas. Only CSL has a shared
    # extension: AEV remains two fields on SX567 and four on SX584.
    off = abi['events']['CSL']
    csl = [n for n in CSL_SIGNALS if selected('CSL/' + n, [n])]
    require_native(native_names(off, 16, data[off + 8]), csl, 'CSL')
    hdr = bytearray(data[off:off + abi['tables'][12][1]])
    hdr[8] = len(csl)
    struct.pack_into('<I', hdr, 16, append_u16_array(available[n] for n in csl))
    writes[off] = bytes(hdr)

    off = data.offset(g[14])
    npd = [n for n in NPD_SIGNALS if selected('NPD/' + n, [n])]
    require_native(native_names(off, 24, data[off + 16]), npd, 'NPD')
    hdr = bytearray(data[off:off + NPD_HEADER_SIZE])
    hdr[16] = len(npd)
    struct.pack_into('<I', hdr, 24, append_u16_array(available[n] for n in npd))
    writes[off] = bytes(hdr)
    counts['NPD'] = (data[off + 16], len(npd))
    activated.update(npd)

    off = data.offset(g[21])
    rules = []
    str_names = {name for _, name, _ in str_rows}
    for destination, source, operation, upper_bound, lower_bound in DERIVED_VARIABLE_RULES:
        if selected('g21/' + destination, [destination, source]):
            if source not in str_names:
                omitted.append(('g21/' + destination, ['STR/' + source]))
                continue
            rules.append(DERIVED_VARIABLE_RULE.pack(
                available[destination], available[source], operation, upper_bound, lower_bound))
            activated.add(destination)
    old_rules = data.offset(data.u32(off + 4))
    # Keep native metadata for every rule already present in the catalogue.
    # Only rules sourcing deliberately excluded STR fields may be discarded.
    excluded_sources = {available[name] for label, name, _, _ in LUMIS_STR_SIGNALS
                        if label in excluded_str and name in available}
    new_pairs = {r[:4] for r in rules}
    for i in range(data.u32(off)):
        record_off = old_rules + i * DERIVED_VARIABLE_RULE.size
        rec = bytes(data[record_off:record_off + DERIVED_VARIABLE_RULE.size])
        if rec[:4] not in new_pairs:
            if struct.unpack_from('<H', rec, 2)[0] in excluded_sources:
                continue
            raise CCXMergeError("g21: catalogue would remove a native history rule")
        rules = [rec if r[:4] == rec[:4] else r for r in rules]
    rules_addr = append(b''.join(rules))
    writes[off] = struct.pack('<II', len(rules), rules_addr)
    counts['g21'] = (data.u32(off), len(rules))

    for tag, names in LIVE_SIGNALS.items():
        names = [n for n in names if selected(tag + '/' + n, [n])]
        periodic = tag in abi['live']
        off = (abi['live'] if periodic else abi['changes'])[tag]
        native = native_names(off, 8, data[off])
        require_native(native, names, tag)
        hdr = bytearray(data[off:off + (LIVE_HEADER_SIZE if periodic else CHANGE_HEADER_SIZE)])
        hdr[0] = len(names)
        struct.pack_into('<I', hdr, 8, append_u16_array(available[n] for n in names))
        if periodic:
            rates = dict(zip(native, read_u16_array(off, 12, data[off])))
            struct.pack_into('<I', hdr, 12, append_u16_array(rates.get(n, 1) for n in names))
        writes[off] = bytes(hdr)
        counts[tag] = (data[off], len(names))

    # Activate reporting variables, preserving every other descriptor bit.
    # Directly captured settings retain their native activation unless listed
    # explicitly in REPORTING_ACTIVATION.
    activated.update(REPORTING_ACTIVATION)
    for name in sorted(activated & available.keys()):
        table = asf.find_var_table_number(name)
        if table not in (4, 8):
            continue
        off = asf.find_var_name(name) - asf.ccx_off
        writes[off] = struct.pack('<H', data.u16(off) | 1)

    layout['total_size'] = len(block)
    layout['expected_block'] = bytes(block)
    return bytes(block), layout


def validate_merge_writes(data, layout):
    """Check all planned bytes and every untouched CCX range before committing."""
    errors = []
    start = layout['start']
    if start % 4 or start < 0 or start + layout['total_size'] > len(data) - 2:
        errors.append("Invalid merge block bounds")
    if bytes(data[start:start + layout['total_size']]) != layout['expected_block']:
        errors.append("Merge block differs from the planned arrays or labels")
    for off, expected in layout['writes'].items():
        if bytes(data[off:off + len(expected)]) != expected:
            errors.append(f"Descriptor write at CCX+0x{off:05X} differs from the plan")
    for off, expected in layout['preserved_ranges']:
        if bytes(data[off:off + len(expected)]) != expected:
            errors.append(f"Unchanged CCX range at +0x{off:05X} was modified")
    return errors


def patch_edf_merge(asf, verbose=False):
    """Apply the name-resolved SX567/SX584 superset as one validated CCX update."""
    g = [asf.FLASH_BASE + asf.globals_offset(i) for i in range(29)]
    data = CCXImage(asf)
    if g[0] != data.base:
        raise CCXMergeError(f"Unexpected CCX base: 0x{g[0]:08X}")
    original = bytes(data)
    abi = firmware_layout(asf, data, g)
    old_objects = stream_objects(data, g, abi)
    block, _ = build_merge_block(asf, data, g, abi, 0)
    start = asf.find_ccx_ff_range_backwards(len(block), alignment=4) - asf.ccx_off
    block, layout = build_merge_block(asf, data, g, abi, start)
    if data[start:start + len(block)] != b'\xFF' * len(block):
        raise CCXMergeError("Merge allocation is not erased")
    data[start:start + len(block)] = block
    for off, raw in layout['writes'].items():
        data[off:off + len(raw)] = raw

    external_refs = (asf.read_u32(off) - data.base
                     for begin, end in ((0, asf.ccx_off),
                                        (asf.ccx_off + asf.ccx_size, len(asf.fw)))
                     for off in range(begin, end - 3, 2))
    live_objects = stream_objects(data, g, abi)
    changed = reclaim_stream_objects(data, old_objects, live_objects, external_refs)
    reclaimed = sum(changed)
    changed[start:start + len(block)] = b'\x01' * len(block)
    for off, raw in layout['writes'].items():
        changed[off:off + len(raw)] = b'\x01' * len(raw)
    layout['preserved_ranges'] = [(a, original[a:b]) for a, b in mask_ranges(changed, 0)]
    errors = validate_merge_writes(data, layout)
    if errors:
        raise CCXMergeError("Validation failed:\n  " + "\n  ".join(errors))
    asf.patch(data, addr=asf.ccx_off, clobber=True)

    summary = ', '.join('%s %d->%d' % (tag, *layout['counts'][tag])
                        for tag in ('STR', 'BRP', 'PLD', 'NPD', 'g21'))
    retention = data.u16(data.offset(g[14]))
    print("EDF merge: " + summary +
          f", NPD retention={retention} ({retention + 1} slots)")
    details = [f"arrays: {len(block)} bytes at 0x{data.address(start):08X}",
               f"reclaimed {reclaimed} bytes of replaced objects"]
    details.extend(f"omit {label}: missing {', '.join(missing)}"
                   for label, missing in layout['omitted'])
    if verbose:
        for detail in details:
            print("  " + detail)
    return details


def main():
    import argparse
    parser = argparse.ArgumentParser(
        description="Merge universal EDF signals into SX567/SX584 CCX image"
    )
    parser.add_argument("input", help="Input full AS10 firmware image")
    parser.add_argument("-o", "--output", help="Output file (default: <input>.merged.bin)")
    parser.add_argument("-v", "--verbose", action="store_true", help="Show detailed patch list")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be done without writing")
    parser.add_argument(
        "--ignore-input-crc", action="store_true",
        help="Allow input whose firmware region CRCs are already dirty"
    )
    parser.add_argument(
        "--defer-crc", action="store_true",
        help="Leave firmware region CRCs dirty for the calling patcher to finalize"
    )
    args = parser.parse_args()

    input_path = Path(args.input)
    with input_path.open("rb") as f:
        asf = ASFirmware(f, validate_crc=not args.ignore_input_crc)

    patch_edf_merge(asf, verbose=args.verbose)

    if args.dry_run:
        print("DRY RUN (no output written)")
        return

    if not args.defer_crc:
        asf.fix_crcs()
    out_path = Path(args.output) if args.output else input_path.with_suffix('.merged.bin')
    out_path.write_bytes(bytes(asf.fw))


if __name__ == '__main__':
    main()

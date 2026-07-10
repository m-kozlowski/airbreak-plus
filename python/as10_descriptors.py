#!/usr/bin/env python3

import struct
import sys
import os
import argparse
import contextlib
import io
import shlex
try:
    import readline  # arrow-key history
except ImportError:
    pass
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

FLASH_BASE   = 0x08000000
RAM_BASE     = 0x20000000

LANG_MASTER = {
    0:  ("EN",  "English"),
    1:  ("FR",  "French"),
    2:  ("DE",  "German"),
    3:  ("IT",  "Italian"),
    4:  ("ES",  "Spanish"),
    5:  ("ES*", "Spanish (regional)"),
    6:  ("PT",  "Portuguese"),
    7:  ("PT*", "Portuguese (regional)"),
    8:  ("NL",  "Dutch"),
    9:  ("SV",  "Swedish"),
    10: ("DA",  "Danish"),
    11: ("NO",  "Norwegian"),
    12: ("FI",  "Finnish"),
    13: ("JA",  "Japanese (Katakana)"),
    14: ("RU",  "Russian"),
    15: ("TR",  "Turkish"),
    16: ("ZH",  "Chinese (Traditional)"),
    17: ("ZS",  "Chinese (Simplified)"),
    18: ("PL",  "Polish"),
    19: ("JK",  "Japanese (Kanji)"),
}

def detect_languages(flash, ta, lan_idx=5):
    """Detect language list from the LAN enum descriptor.

    The perm_mask has one bit per LAN value. Set bits indicate available
    languages. Locale slot = popcount of lower bits.
    Returns (count, labels_list, lan_ids_list).
    """
    g8 = ta.get('table8')
    if not g8:
        raise ValueError("globals[8] not loaded; cannot detect language list")
    lan_addr = g8 + lan_idx * TABLES[8]['stride']
    lan_options = flash.u8(lan_addr + 0x09) or 0
    perm = flash.u32(lan_addr + 0x0C)
    if perm is None or perm == 0:
        raise ValueError("LAN descriptor has no language permission mask")
    ids = []
    labels = []
    for bit in range(max(perm.bit_length(), lan_options)):
        if perm & (1 << bit):
            ids.append(bit)
            lbl = LANG_MASTER.get(bit, (f"L{bit}", f"Language {bit}"))[0]
            labels.append(lbl)
    if not ids:
        raise ValueError("LAN descriptor language mask is empty")
    return len(ids), labels, ids


def infer_language_count_from_g2(flash, g2_addr):
    ptrs = []
    for i in range(128):
        ptr = flash.u32(g2_addr + i * 8 + 4)
        if not ptr or not flash.is_flash_ptr(ptr):
            break
        ptrs.append(ptr)
    if len(ptrs) < 2:
        raise ValueError("globals[2] has too few locale arrays")

    deltas = [b - a for a, b in zip(ptrs, ptrs[1:])
              if b > a and (b - a) % 2 == 0 and (b - a) <= 128]
    if not deltas:
        raise ValueError("cannot infer language slot count from globals[2]")
    stride = max(set(deltas), key=deltas.count)
    slots = stride // 2

    # Locale arrays are u16 slots aligned to 4 bytes; odd language counts leave
    # a trailing zero pad word before the next array.
    sample = ptrs[:min(len(ptrs), 128)]
    while slots > 1:
        col = [flash.u16(ptr + (slots - 1) * 2) for ptr in sample]
        col = [value for value in col if value is not None]
        if col and all(value == 0 for value in col):
            slots -= 1
        else:
            break
    return slots

TABLES = {
    3:  dict(stride=10),
    4:  dict(stride=0x1C),
    6:  dict(stride=0x18),
    8:  dict(stride=0x14),
    9:  dict(stride=0x18),
    10: dict(stride=0x24),
}

GLOBAL_LABELS = {
    0: "device identity/config header",
    1: "scheduler/logical-period profiles",
    2: "string descriptor table",
    3: "string variable descriptors",
    4: "numeric/settings descriptors",
    5: "alternate labels for specialized g[4] descriptors",
    6: "config/status descriptors",
    7: "g[6] byte-slice pool",
    8: "enum/menu descriptors",
    9: "ANV apnea-event record descriptor",
    10: "PCC/HPI/HUI hardware-interface vector descriptors",
    11: "BRP/PLD/SAD channels",
    12: "CSL/AEV/EVE channels",
    13: "STR channel descriptor",
    14: "NPD NIGHT_PROFILE_PERIODIC signal group",
    15: "NPA/ALA aperiodic signal groups",
    16: "EEPROM-backed variable groups",
    17: "DAC date descriptor",
    18: "TIC time descriptor",
    19: "stream table",
    20: "PDL persistent-state list",
    21: "derived-variable rules",
    22: "identity TGT export list",
    23: "UART name index",
    24: "mode membership table",
    25: "mode count",
    26: "TCE/PBT/PMD/FTX/RAW/DRT/CPU/SSK channels",
    27: "APN/CSN/BRH channels",
    28: "OXH channel",
    29: "sentinel/end marker",
}

FLAG_DEFS = {
    0: ("ACT", "Active -- master enable"),
    1: ("VIS", "Visible in menu"),
    2: ("EDT", "Editable by user"),
    3: ("SGN", "Signed numeric representation"),
    4: ("LOCK", "Read-only lock"),
    5: ("RDY", "Runtime initialized/ready"),
    6: ("EXT", "Harness/periodic external override"),
    7: ("B7",  "Table-specific"),
}


class Flash:
    def __init__(self, path, base=FLASH_BASE):
        with open(path, "rb") as f:
            self.data = f.read()
        self.base = base
        self.end  = base + len(self.data)

    def _o(self, addr):
        o = addr - self.base
        return o if 0 <= o < len(self.data) else None

    def u8(self, a):
        o = self._o(a)
        return self.data[o] if o is not None else None

    def u16(self, a):
        o = self._o(a)
        return struct.unpack_from("<H", self.data, o)[0] if o is not None and o+2 <= len(self.data) else None

    def s16(self, a):
        o = self._o(a)
        return struct.unpack_from("<h", self.data, o)[0] if o is not None and o+2 <= len(self.data) else None

    def u32(self, a):
        o = self._o(a)
        return struct.unpack_from("<I", self.data, o)[0] if o is not None and o+4 <= len(self.data) else None

    def s32(self, a):
        o = self._o(a)
        return struct.unpack_from("<i", self.data, o)[0] if o is not None and o+4 <= len(self.data) else None

    def blob(self, a, n):
        o = self._o(a)
        return self.data[o:o+n] if o is not None and o+n <= len(self.data) else None

    def cstr(self, a, mx=256):
        o = self._o(a)
        if o is None: return None
        e = self.data.find(b'\x00', o, min(o+mx, len(self.data)))
        if e < 0: e = min(o+mx, len(self.data))
        return self.data[o:e]

    def is_flash_ptr(self, v):
        return v is not None and self.base <= v < self.end

    def is_ram_ptr(self, v):
        return v is not None and RAM_BASE <= v < RAM_BASE + 0x20000



def find_globals_array(flash):
    """Find the globals[] ABI vector by scanning for its pointer-heavy prefix.

    Most entries are ascending CCX pointers, but g[25] is a record count and
    g[29] is the end marker.
    """
    scan_start = flash.base + 0x4000   # CCX starts after BLX
    scan_end = flash.base + 0x8000     # globals is early in CCX
    best_score, best_addr = 0, None

    for probe in range(scan_start, scan_end, 4):
        score = 0
        prev = 0
        for i in range(20):
            ptr = flash.u32(probe + i * 4)
            if ptr is None:
                break
            if flash.is_flash_ptr(ptr):
                score += 1
                if ptr > prev:
                    score += 1  # bonus for ascending order
                prev = ptr
            elif ptr == 0 or ptr == 0xFFFFFFFF:
                pass  # sentinel, don't penalize
            else:
                if i < 10:
                    break  # non-pointer too early = wrong candidate
        if score > best_score:
            best_score = score
            best_addr = probe

    return best_addr, best_score


def find_tables_direct(flash):
    """Find descriptor tables by locating the globals[] ABI vector.

    Scans CCX for the pointer-heavy vector, then reads object roots directly
    from it.
    """
    results = {}

    print("[*] Scanning for globals[] pointer array...")
    g_addr, g_score = find_globals_array(flash)

    if not g_addr or g_score < 20:
        print(f"[-] globals[] not found (best score={g_score})")
        return results

    print(f"[+] globals[] at 0x{g_addr:08X} (score={g_score})")
    results['_globals_addr'] = g_addr

    # Read all table pointers
    ptrs = {i: flash.u32(g_addr + i * 4) for i in range(30)}
    results['_globals_values'] = ptrs

    for t in (3, 4, 6, 8, 9, 10):
        if ptrs.get(t) and flash.is_flash_ptr(ptrs[t]):
            results[f"table{t}"] = ptrs[t]
            print(f"    globals[{t:2d}] = 0x{ptrs[t]:08X}")

    if ptrs.get(1) and flash.is_flash_ptr(ptrs[1]):
        results['timers'] = ptrs[1]

    if ptrs.get(5) and flash.is_flash_ptr(ptrs[5]):
        results['globals5'] = ptrs[5]

    if ptrs.get(7) and flash.is_flash_ptr(ptrs[7]):
        results['globals7'] = ptrs[7]

    if ptrs.get(2) and flash.is_flash_ptr(ptrs[2]):
        results['globals2'] = ptrs[2]

    if ptrs.get(23) and flash.is_flash_ptr(ptrs[23]):
        results['names'] = ptrs[23]

    if ptrs.get(19) and flash.is_flash_ptr(ptrs[19]):
        results['streams'] = ptrs[19]

    if ptrs.get(14) and flash.is_flash_ptr(ptrs[14]):
        results['npd'] = ptrs[14]

    if ptrs.get(15) and flash.is_flash_ptr(ptrs[15]):
        results['npa'] = ptrs[15]

    if ptrs.get(22) and flash.is_flash_ptr(ptrs[22]):
        results['name_pool'] = ptrs[22]

    if ptrs.get(0) and flash.is_flash_ptr(ptrs[0]):
        results['device'] = ptrs[0]
    if ptrs.get(20) and flash.is_flash_ptr(ptrs[20]):
        results['pdl'] = ptrs[20]
    if ptrs.get(21) and flash.is_flash_ptr(ptrs[21]):
        results['pdl_rules'] = ptrs[21]
    if ptrs.get(24) and flash.is_flash_ptr(ptrs[24]):
        results['modes'] = ptrs[24]
        # globals[25] is count, not a pointer
        g25 = ptrs.get(25, 0)
        if 0 < g25 < 200:
            results['modes_count'] = g25
    if ptrs.get(16) and flash.is_flash_ptr(ptrs[16]):
        results['vargroups'] = ptrs[16]
    if ptrs.get(17) and flash.is_flash_ptr(ptrs[17]):
        results['desc17'] = ptrs[17]
    if ptrs.get(18) and flash.is_flash_ptr(ptrs[18]):
        results['desc18'] = ptrs[18]
    if ptrs.get(11) and flash.is_flash_ptr(ptrs[11]):
        results['brp'] = ptrs[11]
    if ptrs.get(12) and flash.is_flash_ptr(ptrs[12]):
        results['csl'] = ptrs[12]
    if ptrs.get(13) and flash.is_flash_ptr(ptrs[13]):
        results['str_ch'] = ptrs[13]
    if ptrs.get(26) and flash.is_flash_ptr(ptrs[26]):
        results['tce'] = ptrs[26]
    if ptrs.get(27) and flash.is_flash_ptr(ptrs[27]):
        results['apn'] = ptrs[27]
    if ptrs.get(28) and flash.is_flash_ptr(ptrs[28]):
        results['oxh'] = ptrs[28]

    return results


def decode_flags(f, table=None):
    names = []
    for bit, (name, _) in FLAG_DEFS.items():
        if not f & (1 << bit):
            continue
        names.append("RAW" if table == 4 and bit == 7 else name)
    return "|".join(names) or "-"


def fmt_flags(f, table=None):
    return f"fl=0x{f:04X} [{decode_flags(f, table):>20s}]"


def _vid_str(var_id, db=None):
    """Format var_id with optional UART name: '0x02C4:BRP' or '0x001E'."""
    if db and db.names:
        n = db.uart_name(var_id)
        if n:
            return f"0x{var_id:04X}:{n}"
    return f"0x{var_id:04X}"


def _g4_idx_ref(idx, db=None, none="none", detail=False):
    if idx == 0x7FFF:
        return none
    idx_hex = f"0x{idx & 0xFFFF:04X}"
    entry = db.g4_by_idx(idx) if db else None
    if entry:
        var = _vid_str(entry.var_id, db)
        if detail:
            return f"[4] idx {idx_hex} -> var_id {var}"
        return f"[4]{idx_hex}->{var}"
    if detail:
        return f"[4] idx {idx_hex} (not loaded)"
    return f"[4]{idx_hex}"


class Entry3:
    """globals[3] -- String variable descriptor (10 bytes).

    30 entries for string-type variables (device ID, serial, etc.).
    Each variable has a RAM shadow at 0x20000104 + idx*8: {u16 flags, u32 value}.

    ROM record layout:
      +0x00  u16  flags
      +0x02  u8   notify_handler  (callback index, 0=none)
      +0x03  u8   _pad
      +0x04  s16  dependency_head_g4_idx (0x7FFF=none)
      +0x06  s16  format_str_id   (display format string, 0x00DE=none)
      +0x08  u16  max_length      (max string length / default)
    """
    TABLE = 3
    def __init__(self, fl, addr, idx, id_base):
        self.addr, self.idx = addr, idx
        self.var_id = id_base + idx
        self.flags          = fl.u16(addr + 0x00)
        self.notify_handler = fl.u8(addr + 0x02)   # callback jump table index
        self.dependency_idx = fl.s16(addr + 0x04)
        self.format_str_id  = fl.s16(addr + 0x06)   # format string, 0xDE=none
        self.max_length     = fl.u16(addr + 0x08)    # max string length

    def oneline(self, db=None):
        off = self.addr - (db.table_bases.get(3, self.addr) if db else self.addr)
        lv = _g4_idx_ref(self.dependency_idx, db, none="")
        fs = f"0x{self.format_str_id & 0xFFFF:04X}" if self.format_str_id != 0xDE else "--"
        cb = f"cb={self.notify_handler}" if self.notify_handler else ""
        return (f"0x{self.idx:03X} var={_vid_str(self.var_id, db)} @0x{self.addr:08X} +0x{off:04X}  "
                f"{fmt_flags(self.flags, self.TABLE)}  "
                f"maxlen={self.max_length}  linked={lv}  fmt={fs}  {cb}")

    def detail(self, db=None):
        off = self.addr - (db.table_bases.get(3, self.addr) if db else self.addr)
        lv = _g4_idx_ref(self.dependency_idx, db, none="none", detail=True)
        fs = f"0x{self.format_str_id & 0xFFFF:04X}" if self.format_str_id != 0xDE else "0x00DE (none)"
        return (f"  [3] idx=0x{self.idx:03X}  var_id={_vid_str(self.var_id, db)}  "
                f"@ 0x{self.addr:08X} +0x{off:04X}\n"
                f"    flags          = 0x{self.flags:04X} ({decode_flags(self.flags, self.TABLE)})\n"
                f"    notify_handler = {self.notify_handler}\n"
                f"    dep_head       = 0x{self.dependency_idx & 0xFFFF:04X} ({lv})\n"
                f"    format_str_id  = {fs}\n"
                f"    max_length     = {self.max_length}")


class Entry4:
    TABLE = 4
    def __init__(self, fl, addr, idx, id_base):
        self.addr, self.idx = addr, idx
        self.var_id = id_base + idx
        self.flags         = fl.u16(addr + 0x00)
        self.callback_id   = fl.u8(addr + 0x02)
        self._pad_03       = fl.u8(addr + 0x03)   # alignment padding (always 0)
        self.next_var_idx  = fl.s16(addr + 0x04)
        self.name_str_id   = fl.u16(addr + 0x06)  # variable name/label string ID
        self.default_value = fl.s32(addr + 0x08)
        self.max_value     = fl.s32(addr + 0x0C)
        self.min_value     = fl.s32(addr + 0x10)
        self.decimal_places= fl.u8(addr + 0x14)
        self._pad_15       = fl.u8(addr + 0x15)   # alignment padding (always 0)
        self.scale_factor  = fl.s16(addr + 0x16)
        self.step_size     = fl.s16(addr + 0x18)
        self.units_str_id  = fl.u16(addr + 0x1A)

    def _fmt(self, v):
        s = self.scale_factor
        dp = self.decimal_places if self.decimal_places is not None and self.decimal_places < 10 else 0
        if s and s > 0:  return f"{v / s:.{dp}f}"
        if s and s < 0:  return f"{v * (-s)}"
        return str(v)

    def range_str(self):
        return (f"{self._fmt(self.min_value)} .. {self._fmt(self.max_value)} "
                f"step {self._fmt(self.step_size)}")

    def scale_str(self):
        s = self.scale_factor
        if s > 0: return f"/{s}"
        if s < 0: return f"x{-s}"
        return "raw"

    def oneline(self, db=None):
        off = self.addr - (db.table_bases.get(4, self.addr) if db else self.addr)
        name = ""
        if db and self.name_str_id and self.name_str_id not in (0xFFFF, 0xDE):
            n = db.string(self.name_str_id)
            if n: name = f' "{n}"'
        unit = ""
        if db and self.units_str_id and self.units_str_id not in (0xFFFF, 0xDE):
            u = db.string(self.units_str_id)
            if u: unit = f" [{u}]"
        chain_ref = _g4_idx_ref(self.next_var_idx, db, none="")
        chain = f"next={chain_ref}" if chain_ref else ""
        g5 = ""
        if db:
            rec = db.g5_lookup(self.idx)
            if rec is not None:
                a, b = rec
                parts_g5 = []
                if a != 0xDE:
                    sa = db.string(a) if db.strtab else None
                    parts_g5.append(f'a="{sa}"' if sa else f'a=0x{a:04X}')
                if b != 0xDE:
                    sb = db.string(b) if db.strtab else None
                    parts_g5.append(f'b="{sb}"' if sb else f'b=0x{b:04X}')
                if parts_g5:
                    g5 = f"  alt[{', '.join(parts_g5)}]"
        return (f"0x{self.idx:03X} var={_vid_str(self.var_id, db)} @0x{self.addr:08X} +0x{off:05X}  "
                f"{fmt_flags(self.flags, self.TABLE)}  "
                f"def={self._fmt(self.default_value):>8s}  "
                f"[{self.range_str()}]{unit}  "
                f"{chain}{name}{g5}")

    def detail(self, db=None):
        off = self.addr - (db.table_bases.get(4, self.addr) if db else self.addr)
        chain_str = _g4_idx_ref(self.next_var_idx, db, none="end", detail=True)
        name = ""
        if db and self.name_str_id and self.name_str_id not in (0xFFFF, 0xDE):
            n = db.string(self.name_str_id)
            if n: name = f' = "{n}"'
        unit = ""
        if db and self.units_str_id and self.units_str_id not in (0xFFFF, 0xDE):
            u = db.string(self.units_str_id)
            if u: unit = f' = "{u}"'
        sub_base = db.g4_subrange_base_idx if db else None
        sub = (f"  (sub-range 0x{sub_base:03X}+{self.idx - sub_base})"
               if sub_base is not None and self.idx >= sub_base else "")
        lines = [
            f"  [4] idx=0x{self.idx:03X}  var_id={_vid_str(self.var_id, db)}  "
            f"@ 0x{self.addr:08X} +0x{off:05X}{sub}",
            f"    flags      = 0x{self.flags:04X} ({decode_flags(self.flags, self.TABLE)})  "
            f"0b{self.flags:016b}",
            f"    callback   = {self.callback_id}",
            f"    next_chain = 0x{self.next_var_idx & 0xFFFF:04X} ({chain_str})",
            f"    name_str   = 0x{self.name_str_id:04X}{name}",
            f"    default    = {self.default_value} ({self._fmt(self.default_value)})",
            f"    max        = {self.max_value} ({self._fmt(self.max_value)})",
            f"    min        = {self.min_value} ({self._fmt(self.min_value)})",
            f"    step       = {self.step_size} ({self._fmt(self.step_size)})",
            f"    scale      = {self.scale_factor} ({self.scale_str()})  "
            f"dp={self.decimal_places}",
            f"    range      : {self.range_str()}",
            f"    units_str  = 0x{self.units_str_id:04X}{unit}",
        ]
        if db:
            rec = db.g5_lookup(self.idx)
            if rec is not None:
                a, b = rec
                sa = db.string(a) if db.strtab and a != 0xDE else None
                sb = db.string(b) if db.strtab and b != 0xDE else None
                lines.append(f"    -- globals[5] alternate labels --")
                lines.append(f"      str_a = 0x{a:04X}"
                             f'{f" ({sa!r})" if sa else " (none)" if a == 0xDE else ""}')
                lines.append(f"      str_b = 0x{b:04X}"
                             f'{f" ({sb!r})" if sb else " (none)" if b == 0xDE else ""}')
        return "\n".join(lines)


class Entry6:
    TABLE = 6
    def __init__(self, fl, addr, idx, id_base):
        self.addr, self.idx = addr, idx
        self.var_id = id_base + idx
        self.flags          = fl.u16(addr + 0x00)
        self.callback_id    = fl.u8(addr + 0x02)
        self._pad_03        = fl.u8(addr + 0x03)
        self.dependency_idx = fl.s16(addr + 0x04)
        self.name_str_id    = fl.u16(addr + 0x06)
        self.default        = fl.u32(addr + 0x08)
        self.allowed_bits   = fl.u32(addr + 0x0C)
        self.item_count     = fl.u8(addr + 0x10)
        self.display_param  = fl.u8(addr + 0x11)
        self.pool_offset    = fl.u16(addr + 0x12)
        self.base_str_id    = fl.u16(addr + 0x14)
        self._pad_16        = fl.u16(addr + 0x16)

    def pool_values(self, db):
        if not db or db.g7_addr is None:
            return []
        return [db.fl.u8(db.g7_addr + self.pool_offset + i)
                for i in range(self.item_count)]

    def oneline(self, db=None):
        off = self.addr - (db.table_bases.get(6, self.addr) if db else self.addr)
        lbl = ""
        if db and self.name_str_id and self.name_str_id not in (0xFFFF, 0xDE):
            s = db.string(self.name_str_id)
            if s: lbl = f' "{s}"'
        values = self.pool_values(db)
        pool = f"  pool={','.join(str(v) for v in values)}" if values else ""
        return (f"0x{self.idx:03X} var={_vid_str(self.var_id, db)} @0x{self.addr:08X} +0x{off:04X}  "
                f"{fmt_flags(self.flags, self.TABLE)}  "
                f"def=0x{self.default:08X}  allowed=0x{self.allowed_bits:08X}  "
                f"items={self.item_count}  pooloff=0x{self.pool_offset:04X}"
                f"{lbl}{pool}")

    def detail(self, db=None):
        off = self.addr - (db.table_bases.get(6, self.addr) if db else self.addr)
        lbl = ""
        if db and self.name_str_id and self.name_str_id not in (0xFFFF, 0xDE):
            s = db.string(self.name_str_id)
            if s: lbl = f' = "{s}"'
        base = ""
        if db and self.base_str_id not in (0xFFFF, 0xDE):
            s = db.string(self.base_str_id)
            if s: base = f' = "{s}"'
        dep = _g4_idx_ref(self.dependency_idx, db, none="none", detail=True)
        values = self.pool_values(db)
        return (
            f"  [6] idx=0x{self.idx:03X}  var_id={_vid_str(self.var_id, db)}  "
            f"@ 0x{self.addr:08X} +0x{off:04X}\n"
            f"    flags      = 0x{self.flags:04X} ({decode_flags(self.flags, self.TABLE)})\n"
            f"    callback   = {self.callback_id}\n"
            f"    dep_head   = 0x{self.dependency_idx & 0xFFFF:04X} ({dep})\n"
            f"    name_str   = 0x{self.name_str_id:04X}{lbl}\n"
            f"    default    = 0x{self.default:08X} ({self.default})\n"
            f"    allowed    = 0x{self.allowed_bits:08X}  "
            f"0b{self.allowed_bits:032b}\n"
            f"    item_count = {self.item_count}  display_param={self.display_param}\n"
            f"    pool_offset = 0x{self.pool_offset:04X}\n"
            f"    pool_values = {', '.join(str(v) for v in values) if values else 'not loaded'}\n"
            f"    base_str   = 0x{self.base_str_id:04X}{base}")


M36_XML_ENUM_LABELS = {
    ('HTB', 3): ('M36 XML metadata', ('None', '15mm', '19mm')),
    ('HUM', 3): ('M36 XML metadata', ('End Cap', 'Internal', 'External')),
}


def _metadata_enum_labels(db, entry):
    if not db:
        return None
    name = db.uart_name(entry.var_id)
    return M36_XML_ENUM_LABELS.get((name, entry.num_options))


def _is_no_string_id(db, str_id):
    if str_id in (-1, 0, 0xFFFF):
        return True
    if db:
        if str_id == getattr(db, 'no_string_id', None):
            return True
        if db.string(str_id) is None:
            return True
    return False


class Entry8:
    TABLE = 8
    def __init__(self, fl, addr, idx, id_base):
        self.addr, self.idx = addr, idx
        self.var_id = id_base + idx
        self.flags         = fl.u16(addr + 0x00)
        self.callback_id   = fl.u8(addr + 0x02)
        self._pad_03       = fl.u8(addr + 0x03)   # alignment padding (always 0)
        self.linked_var_idx= fl.s16(addr + 0x04)
        self.name_str_id   = fl.u16(addr + 0x06)
        self.default_value = fl.u8(addr + 0x08)
        self.num_options   = fl.u8(addr + 0x09)
        self.param_0a      = fl.s16(addr + 0x0A)   # s16 param slot (0 = unused)
        self.perm_mask     = fl.u32(addr + 0x0C)
        self.base_str_id   = fl.s16(addr + 0x10)
        self.param_12      = fl.s16(addr + 0x12)   # s16 param slot (0 = unused)

    def has_strings(self, db=None):
        return self.base_str_id >= 0 and not _is_no_string_id(db, self.base_str_id)

    def option_strings(self, db):
        """Return list of option name strings."""
        if not db or not self.has_strings(db):
            return []
        out = []
        for i in range(self.num_options):
            s = db.string(self.base_str_id + i)
            if s is None:
                out.append(f"?str#{self.base_str_id + i}")
            else:
                out.append(s)
        return out

    def perm_bits(self):
        """Return list of (option_idx, allowed) for each option."""
        return [(i, bool(self.perm_mask & (1 << i)))
                for i in range(self.num_options)]

    def oneline(self, db=None):
        off = self.addr - (db.table_bases.get(8, self.addr) if db else self.addr)
        name = ""
        if db and not _is_no_string_id(db, self.name_str_id):
            n = db.string(self.name_str_id)
            if n: name = f' "{n}"'
        link_ref = _g4_idx_ref(self.linked_var_idx, db, none="")
        link = f"dep={link_ref}" if link_ref else ""
        opts = ""
        labels = self.option_strings(db) if db else []
        meta = _metadata_enum_labels(db, self) if not labels else None
        if db and (labels or meta):
            labels = labels if meta is None else list(meta[1])
            parts = []
            for i, lb in enumerate(labels):
                if lb:
                    parts.append(lb)
                elif lb is not None:
                    # Empty string in ROM -- likely filled at runtime (e.g. formatted numeric)
                    parts.append(f"[str#0x{self.base_str_id + i:04X}]")
                else:
                    parts.append(f"?str#0x{self.base_str_id + i:04X}")
            opts = "  (" + ", ".join(parts) + ")"
        return (f"0x{self.idx:03X} var={_vid_str(self.var_id, db)} @0x{self.addr:08X} +0x{off:04X}  "
                f"{fmt_flags(self.flags, self.TABLE)}  "
                f"def={self.default_value}  opts={self.num_options:>2}  "
                f"perm=0x{self.perm_mask:08X}  {link}{name}{opts}")

    def detail(self, db=None):
        off = self.addr - (db.table_bases.get(8, self.addr) if db else self.addr)
        link = _g4_idx_ref(self.linked_var_idx, db, none="none", detail=True)
        name = ""
        if db and not _is_no_string_id(db, self.name_str_id):
            n = db.string(self.name_str_id)
            if n: name = f' = "{n}"'
        stxt = "none"
        if self.has_strings(db):
            stxt = f"str#{self.base_str_id}"
            if db:
                s = db.string(self.base_str_id)
                if s: stxt += f' = "{s}"'
        lines = [
            f"  [8] idx=0x{self.idx:03X}  var_id={_vid_str(self.var_id, db)}  "
            f"@ 0x{self.addr:08X} +0x{off:04X}",
            f"    flags      = 0x{self.flags:04X} ({decode_flags(self.flags, self.TABLE)})  "
            f"0b{self.flags:016b}",
            f"    callback   = {self.callback_id}",
            f"    dep_head   = 0x{self.linked_var_idx & 0xFFFF:04X} ({link})",
            f"    name_str   = 0x{self.name_str_id:04X}{name}",
            f"    default    = {self.default_value}   num_options={self.num_options}",
            f"    param_0a   = {self.param_0a}   param_12={self.param_12}",
            f"    perm_mask  = 0x{self.perm_mask:08X}  "
            f"0b{self.perm_mask:032b}",
            f"    base_str   = 0x{self.base_str_id & 0xFFFF:04X} ({stxt})",
        ]
        # Per-option breakdown
        if self.num_options > 0:
            lines.append("    -- options --")
            labels = self.option_strings(db) if db else []
            meta = _metadata_enum_labels(db, self) if not labels else None
            meta_labels = list(meta[1]) if meta else []
            for i in range(self.num_options):
                allowed = "Y" if self.perm_mask & (1 << i) else "N"
                label = ""
                if i < len(meta_labels):
                    label = f'  "{meta_labels[i]}"'
                elif db and self.has_strings(db):
                    s = db.string(self.base_str_id + i)
                    sid = self.base_str_id + i
                    if s:
                        label = f'  "{s}"'
                    elif s is not None:
                        label = f'  [empty -- runtime-filled? str#0x{sid:04X}]'
                    else:
                        label = f'  ?str#0x{sid:04X}'
                lines.append(f"      [{i:>2}] perm={allowed}{label}")
            if meta:
                lines.append(f"    NOTE: option labels from {meta[0]}")
            lan_idx = db._table_index_for_name('LAN', 8, fallback=5) if db else 5
            lnc_idx = db._table_index_for_name('LNC', 6, fallback=7) if db else 7
            htx_idx = db._table_index_for_name('HTX', 8, fallback=0x19) if db else 0x19
            cco_idx = db._table_index_for_name('CCO', 8, fallback=0x16) if db else 0x16
            hum_idx = db._table_index_for_name('HUM', 8, fallback=0x1A) if db else 0x1A
            if self.idx == lan_idx:
                lines.append(f"    NOTE: idx=0x{lan_idx:03X} has extra language-availability gate "
                             f"via LNC (globals[6] idx 0x{lnc_idx:03X}, available languages bitmask)")
            elif self.idx == htx_idx:
                lines.append(f"    NOTE: idx=0x{htx_idx:03X} has extra visibility gate "
                             f"checking CCO ([8] idx 0x{cco_idx:03X}) and HUM ([8] idx 0x{hum_idx:03X})")
        return "\n".join(lines)


ENTRY_CLS = {3: Entry3, 4: Entry4, 6: Entry6, 8: Entry8}


class Entry9:
    """globals[9] -- ANV apnea-event record descriptor (0x18 bytes).

    The runtime value is an event-time u32 followed by duration and event-type
    u16 fields. The descriptor constrains duration and event type.

    ROM record layout (0x18 = 24 bytes):
      +0x00  u16  flags
      +0x02  u16  pad
      +0x04  u16  dependency_head_g4_idx
      +0x06  u16  name_str_id    (0xDE = hidden)
      +0x08  u8   default event type
      +0x09  u8   event type count
      +0x0A  u16  pad
      +0x0C  u32  allowed event type mask
      +0x10  u16  event type base string ID
      +0x12  u16  minimum duration in deciseconds
      +0x14  u16  maximum duration in deciseconds
      +0x16  u16  duration units per second
    """
    TABLE = 9

    def __init__(self, fl, addr, idx, id_base):
        self.addr, self.idx = addr, idx
        self.var_id = id_base + idx

        self.flags        = fl.u16(addr + 0x00)
        self.pad_02       = fl.u16(addr + 0x02)
        self.dependency_idx = fl.u16(addr + 0x04)
        self.name_str_id  = fl.u16(addr + 0x06)
        self.default_byte = fl.u8(addr + 0x08)
        self.num_options  = fl.u8(addr + 0x09)
        self.pad_0a       = fl.u16(addr + 0x0A)
        self.perm_bitmask = fl.u32(addr + 0x0C)
        self.base_str_id  = fl.u16(addr + 0x10)
        self.min_value    = fl.u16(addr + 0x12)
        self.max_value    = fl.u16(addr + 0x14)
        self.step_size    = fl.u16(addr + 0x16)

    def oneline(self, db=None):
        off = self.addr - (db.table_bases.get(9, self.addr) if db else self.addr)
        name = ""
        if db and self.name_str_id and self.name_str_id not in (0xFFFF, 0xDE):
            s = db.string(self.name_str_id)
            if s: name = f'  "{s}"'
        return (f"0x{self.idx:03X} var={_vid_str(self.var_id, db)} @0x{self.addr:08X} +0x{off:04X}  "
                f"{fmt_flags(self.flags, self.TABLE)}  "
                f"type={self.default_byte}  types={self.num_options}  "
                f"duration={self.min_value}..{self.max_value} ds  "
                f"units/s={self.step_size}  "
                f"allowed=0x{self.perm_bitmask:08X}{name}")

    def detail(self, db=None):
        off = self.addr - (db.table_bases.get(9, self.addr) if db else self.addr)
        name = ""
        if db and self.name_str_id and self.name_str_id not in (0xFFFF, 0xDE):
            s = db.string(self.name_str_id)
            if s: name = f' = "{s}"'
        base_str = ""
        if db and self.base_str_id and self.base_str_id not in (0xFFFF, 0xDE):
            s = db.string(self.base_str_id)
            if s: base_str = f' = "{s}"'
        link = _g4_idx_ref(self.dependency_idx, db, none="none", detail=True)
        return (
            f"  [9] idx=0x{self.idx:03X}  var_id={_vid_str(self.var_id, db)}  "
            f"@ 0x{self.addr:08X} +0x{off:04X}\n"
            f"    flags      = 0x{self.flags:04X} ({decode_flags(self.flags, self.TABLE)})  "
            f"0b{self.flags:016b}\n"
            f"    dep_head   = 0x{self.dependency_idx:04X} ({link})\n"
            f"    name_str   = 0x{self.name_str_id:04X}{name}\n"
            f"    default_type = {self.default_byte}\n"
            f"    event_types  = {self.num_options}\n"
            f"    allowed_types = 0x{self.perm_bitmask:08X}  "
            f"0b{self.perm_bitmask:032b}\n"
            f"    type_base_str = 0x{self.base_str_id:04X}{base_str}\n"
            f"    duration     = {self.min_value}..{self.max_value} deciseconds\n"
            f"    units_per_s  = {self.step_size}")


ENTRY_CLS[9] = Entry9


class Entry10:
    """globals[10] -- Hardware-interface vector descriptor (0x24 bytes).

    Three named vectors bridge accessory-controller reports into the variable
    system through a separate indexed-element handler.

    ROM record layout (0x24 = 36 bytes):
      +0x00  u16  flags
      +0x02  u8   callback_id
      +0x03  u8   _pad (alignment)
      +0x04  s16  next_var_idx   (always 0x7FFF = none)
      +0x06  u16  name_str_id
      +0x08  s32  default_value  (copied to secondary RAM on init)
      +0x0C  s32  max_value      (upper clamp)
      +0x10  s32  min_value      (lower clamp)
      +0x14  u8   decimal_places
      +0x15  u8   _pad (alignment)
      +0x16  s16  scale_factor
      +0x18  s16  step_size
      +0x1A  u16  units_str_id
      +0x1C  s32  ram_base_index (index into secondary RAM array)
      +0x20  u8   ram_entry_count
      +0x21  3B   _pad (tail alignment)
    """
    TABLE = 10

    def __init__(self, fl, addr, idx, id_base):
        self.addr, self.idx = addr, idx
        self.var_id = id_base + idx

        self.flags          = fl.u16(addr + 0x00)
        self.callback_id    = fl.u8(addr + 0x02)
        self._pad_03        = fl.u8(addr + 0x03)   # alignment padding (always 0)
        self.next_var_idx   = fl.s16(addr + 0x04)   # linked var (always 0x7FFF = none)
        self.name_str_id    = fl.u16(addr + 0x06)
        self.default_value  = fl.s32(addr + 0x08)
        self.max_value      = fl.s32(addr + 0x0C)
        self.min_value      = fl.s32(addr + 0x10)
        self.decimal_places = fl.u8(addr + 0x14)
        self._pad_15        = fl.u8(addr + 0x15)   # alignment padding (always 0)
        self.scale_factor   = fl.s16(addr + 0x16)
        self.step_size      = fl.s16(addr + 0x18)
        self.units_str_id   = fl.u16(addr + 0x1A)
        self.ram_base_index = fl.s32(addr + 0x1C)
        self.ram_count      = fl.u8(addr + 0x20)

    def _fmt(self, v):
        s = self.scale_factor
        dp = self.decimal_places if self.decimal_places is not None and self.decimal_places < 10 else 0
        if s and s > 0:  return f"{v / s:.{dp}f}"
        if s and s < 0:  return f"{v * (-s)}"
        return str(v)

    def range_str(self):
        return (f"{self._fmt(self.min_value)} .. {self._fmt(self.max_value)} "
                f"step {self._fmt(self.step_size)}")

    def scale_str(self):
        s = self.scale_factor
        if s > 0: return f"/{s}"
        if s < 0: return f"x{-s}"
        return "raw"

    def role(self, db=None):
        name = db.uart_name(self.var_id) if db else None
        return {
            "PCC": "humidifier-interface parameter vector; climate logic uses elements 0,1,3,4",
            "HPI": "binary vector received through the heated-tube interface path",
            "HUI": "binary vector received through the humidifier interface path and used by climate logic",
        }.get(name, "hardware-interface runtime vector")

    def oneline(self, db=None):
        off = self.addr - (db.table_bases.get(10, self.addr) if db else self.addr)
        name = ""
        if db and self.name_str_id and self.name_str_id not in (0xFFFF, 0xDE, 0):
            n = db.string(self.name_str_id)
            if n: name = f' "{n}"'
        unit = ""
        if db and self.units_str_id and self.units_str_id not in (0xFFFF, 0xDE, 0):
            u = db.string(self.units_str_id)
            if u: unit = f" [{u}]"
        return (f"0x{self.idx:03X} var={_vid_str(self.var_id, db)} "
                f"@0x{self.addr:08X} +0x{off:04X}  "
                f"{fmt_flags(self.flags, self.TABLE)}  "
                f"def={self._fmt(self.default_value):>8s}  "
                f"[{self.range_str()}]{unit}  "
                f"ram[{self.ram_base_index}..+{self.ram_count}]{name}  "
                f"[{self.role(db)}]")

    def detail(self, db=None):
        off = self.addr - (db.table_bases.get(10, self.addr) if db else self.addr)
        name = ""
        if db and self.name_str_id and self.name_str_id not in (0xFFFF, 0xDE, 0):
            n = db.string(self.name_str_id)
            if n: name = f' = "{n}"'
        unit = ""
        if db and self.units_str_id and self.units_str_id not in (0xFFFF, 0xDE, 0):
            u = db.string(self.units_str_id)
            if u: unit = f' = "{u}"'
        return (
            f"  [10] idx=0x{self.idx:03X}  var_id={_vid_str(self.var_id, db)}  "
            f"@ 0x{self.addr:08X} +0x{off:04X}\n"
            f"    flags      = 0x{self.flags:04X} ({decode_flags(self.flags, self.TABLE)})  "
            f"0b{self.flags:016b}\n"
            f"    callback   = {self.callback_id}\n"
            f"    name_str   = 0x{self.name_str_id:04X}{name}\n"
            f"    default    = {self.default_value} ({self._fmt(self.default_value)})\n"
            f"    max        = {self.max_value} ({self._fmt(self.max_value)})\n"
            f"    min        = {self.min_value} ({self._fmt(self.min_value)})\n"
            f"    step       = {self.step_size} ({self._fmt(self.step_size)})\n"
            f"    scale      = {self.scale_factor} ({self.scale_str()})  "
            f"dp={self.decimal_places}\n"
            f"    range      : {self.range_str()}\n"
            f"    units_str  = 0x{self.units_str_id:04X}{unit}\n"
            f"    ram_base   = {self.ram_base_index}  ram_count={self.ram_count}\n"
            f"    purpose    = {self.role(db)}")


ENTRY_CLS[10] = Entry10


class StringTable:
    """
    globals[2] is a table of 8-byte records:
      +0x00: u16 max_strlen (max char count across all locale translations)
      +0x02: u16 _pad (alignment, always 0)
      +0x04: u32 pointer to locale index array

    locale_index_array: array of globals[2]-inferred language slots
    string_raw_table[index] -> pointer to C string

    string_lookup(str_id, locale):
      locale_arr = u32(globals[2] + str_id*8 + 4)
      raw_index  = u16(locale_arr + locale*2)
      str_ptr    = u32(raw_table + raw_index*4)
      return cstr(str_ptr)
    """
    def __init__(self, flash, g2_addr, num_langs, raw_addr=None):
        self.fl, self.g2, self.num_langs = flash, g2_addr, num_langs
        # Derive raw_table_ptr from g2[0].locale_arr - 8 if not provided.
        # Layout: [raw_table_ptr u32][0xFFFFFFFF][locale_arr[0]...]
        # raw_table_ptr is an indirect pointer: *(raw_table_ptr) -> string pointer array base
        if raw_addr is None:
            la0 = flash.u32(g2_addr + 4)  # g2[0].locale_arr
            if la0 and flash.is_flash_ptr(la0):
                raw_addr = la0 - 8
            else:
                raise ValueError("cannot derive string raw table from globals[2]")
        raw_ptr = flash.u32(raw_addr)
        if raw_ptr and flash.is_flash_ptr(raw_ptr):
            self.raw = raw_ptr
            print(f"    string_raw_table: 0x{raw_addr:08X} -> 0x{raw_ptr:08X}")
        else:
            raise ValueError(
                f"string raw table dereference failed at 0x{raw_addr:08X}")
        self.count = 0
        for i in range(2000):
            ptr = flash.u32(self.g2 + i * 8 + 4)
            if ptr is None or (ptr != 0 and not flash.is_flash_ptr(ptr)):
                break
            self.count = i + 1

    def get(self, str_id, lang=0):
        if str_id < 0 or str_id >= self.count:
            return None
        la = self.fl.u32(self.g2 + str_id * 8 + 4)
        if not la or not self.fl.is_flash_ptr(la):
            return None
        ri = self.fl.u16(la + lang * 2)
        if ri is None:
            return None
        sp = self.fl.u32(self.raw + ri * 4)
        if not sp or not self.fl.is_flash_ptr(sp):
            return None
        bs = self.fl.cstr(sp)
        if bs is None:
            return None
        try:
            return bs.decode('utf-8', errors='replace')
        except:
            return bs.hex()

    def get_all(self, str_id):
        return [self.get(str_id, l) for l in range(self.num_langs)]


class NameLookup:
    """globals[23]: 26-bucket lookup table mapping 3-letter UART names to var_ids.

    Structure: 26 entries x 8 bytes = {u32 subtable_ptr, u32 count}, one per letter A-Z.
    Each subtable entry: {u8 char2, u8 char3, u16 var_id}.
    """
    def __init__(self, flash, g23_addr):
        self.by_name = {}   # "ABC" -> var_id
        self.by_varid = {}  # var_id -> "ABC"
        total = 0
        for letter_idx in range(26):
            off = g23_addr + letter_idx * 8
            sub_ptr = flash.u32(off)
            count = flash.u32(off + 4)
            if not sub_ptr or not flash.is_flash_ptr(sub_ptr) or count is None or count > 200:
                continue
            for j in range(count):
                c2 = flash.u8(sub_ptr + j * 4)
                c3 = flash.u8(sub_ptr + j * 4 + 1)
                vid = flash.u16(sub_ptr + j * 4 + 2)
                if c2 is None or c3 is None or vid is None:
                    continue
                name = chr(letter_idx + ord('A')) + chr(c2) + chr(c3)
                self.by_name[name] = vid
                self.by_varid[vid] = name
                total += 1
        print(f"[+] globals[23]: UART name lookup, {total} variables")

    def name(self, var_id):
        return self.by_varid.get(var_id)

    def var_id(self, name):
        return self.by_name.get(name.upper())


class DeviceIdentity:
    """globals[0]: Device identity and config header.

    +0x00: u32[7]  CID components (reordered: CX g[1]-g[0]-g[3]-g[2]-g[5]-g[4]-g[6])
    +0x1C: u32     front-panel profile
    +0x20: char[]  product code (e.g. '37101')
    +0x30: char[]  product name (e.g. 'AirSense 10 AutoSet')
    """
    def __init__(self, flash, addr):
        self.addr = addr
        self.cid_vals = [flash.u32(addr + i * 4) or 0 for i in range(7)]
        self.front_panel_profile = flash.u32(addr + 0x1C)
        raw_product_code = flash.cstr(addr + 0x20)
        self.product_code = (raw_product_code.decode('ascii', errors='replace')
                             if raw_product_code else "")
        raw_prod = flash.cstr(addr + 0x30)
        self.product = raw_prod.decode('ascii', errors='replace') if raw_prod else ""
        v = self.cid_vals
        self.cid = "CX%03d-%03d-%03d-%03d-%03d-%03d-%03d" % (
            v[1], v[0], v[3], v[2], v[5], v[4], v[6])
        if self.product_code or self.product:
            print(f"[+] globals[0]: {self.product_code} / {self.product} ({self.cid})")

    def dump(self):
        profile = {
            0: "3 buttons, rotary encoder, default logo",
            1: "5 buttons, no rotary encoder, wave logo",
        }.get(self.front_panel_profile, "invalid")
        return (f"  Product code:  {self.product_code}\n"
                f"  Product name:  {self.product}\n"
                f"  CID:           {self.cid}\n"
                f"  Front-panel profile: {self.front_panel_profile} ({profile})")


class VariableGroups:
    """globals[16]: EEPROM-backed .set variable groups.

    Each entry: 16 bytes:
      +0x00: char[4]  group name (3-char + null)
      +0x04: u16      g4 group-tracker index
      +0x06: u16      param
      +0x08: u32      member_var_id_array_ptr
      +0x0C: u32      member_count
    """
    STRIDE = 16

    def __init__(self, flash, addr, end_addr=None, names=None):
        self.groups = []
        limit = (end_addr - addr) // self.STRIDE if end_addr and end_addr > addr else 16
        for i in range(limit):
            base = addr + i * self.STRIDE
            raw_name = flash.blob(base, 4)
            if not raw_name or not all(0x41 <= b <= 0x5A for b in raw_name[:3]):
                break
            name = raw_name[:3].decode('ascii')
            tracker_idx = flash.u16(base + 4)
            param = flash.u16(base + 6)
            arr_ptr = flash.u32(base + 8)
            count = flash.u32(base + 12)
            members = []
            if arr_ptr and flash.is_flash_ptr(arr_ptr) and count and count < 100:
                for j in range(count):
                    vid = flash.u16(arr_ptr + j * 2)
                    if vid is not None:
                        uart = names.name(vid) if names else None
                        members.append((vid, uart))
            self.groups.append({
                'name': name, 'tracker_idx': tracker_idx,
                'param': param, 'members': members,
            })
        print(f"[+] globals[16]: {len(self.groups)} EEPROM-backed variable groups")

    def dump(self, group_name=None):
        lines = []
        for g in self.groups:
            if group_name and g['name'] != group_name.upper():
                continue
            members = ', '.join(
                f"{u}" if u else f"0x{v:04X}" for v, u in g['members'])
            tracker = _g4_idx_ref(g['tracker_idx'], None, none="none")
            lines.append(f"  {g['name']} ({len(g['members'])} vars, "
                         f"tracker={tracker}): {members}")
        return "\n".join(lines) if lines else f"  group '{group_name}' not found"


class DescriptorTable:
    """globals[17]/[18]: one 8-byte date/time descriptor per root.

    The object var_id is implicit in the global object sequence. The final u16
    in the record is a string ID, not a var_id. Arrays placed after g[18]
    belong to g[19].
    """
    STRIDE = 8

    def __init__(self, flash, gidx, addr, object_var_id, names=None):
        self.gidx = gidx
        self.object_var_id = object_var_id
        self.object_name = names.name(object_var_id) if names else None
        self.entries = []
        self.flags = flash.u16(addr)
        self.callback = flash.u8(addr + 2)
        self.dependency_idx = flash.u16(addr + 4)
        self.string_id = flash.u16(addr + 6)
        print(f"[+] globals[{gidx}]: {_vid_str(object_var_id, None)} descriptor")

    def dump(self):
        name = f":{self.object_name}" if self.object_name else ""
        dep = "none" if self.dependency_idx == 0x7FFF else f"[4]0x{self.dependency_idx:04X}"
        return (f"  0x{self.object_var_id:04X}{name}  flags=0x{self.flags:04X}  "
                f"callback={self.callback}  dep={dep}  string_id=0x{self.string_id:04X}")


class StreamTable:
    """globals[19]: stored record-stream definitions.

    Each entry: 28 bytes.
      +0x00: char[4]  name (3-char + null)
      +0x04: u32      field_var_id_array_ptr
      +0x08: u8       field_count
      +0x09: u8       reserved
      +0x0A: u16      capacity
      +0x0C: u16      trigger_var_id
      +0x0E: u8       globals[1] timer index
      +0x0F: u8       flags
      +0x10: u16      secondary trigger var_id
      +0x12: u16      secondary parameter
      +0x14: u32      trigger idle value
      +0x18: u16      globals[4] state/cursor index
      +0x1A: u16      pad
    """
    STRIDE = 28
    METADATA_NAMES = {
        'ABR': 'ABORT_ERR',
        'TXC': 'CLIMATE_CONTROL_ERR_LOG',
        'TXH': 'HEATED_TUBE_ERROR_LOG',
        'TXE': 'TRANSDR_ERR',
        'TXW': 'TRANSDR_ERR_TWO',
        'TRR': 'TRANSIENT_ERR_LOG',
    }
    PURPOSES = {
        'ABR': 'abort error',
        'TXC': 'climate-control errors',
        'TXH': 'heated-tube errors',
        'TXE': 'transducer errors',
        'TXW': 'transducer errors 2',
        'TRR': 'transient errors',
        'DLL': 'DLA records',
        'ERR': 'application-error origins',
        'ELI': 'ELV records',
        'ZRL': 'saved system errors',
    }

    def __init__(self, flash, g19_addr, end_addr=None, names=None, g4_id_base=None):
        self.entries = []
        scan_end = end_addr if end_addr and end_addr > g19_addr else g19_addr + 0x400
        i = 0
        while g19_addr + (i + 1) * self.STRIDE <= scan_end:
            base = g19_addr + i * self.STRIDE
            raw_name = flash.blob(base, 4)
            if raw_name is None:
                break
            name = raw_name.split(b'\x00')[0].decode('ascii', errors='replace')
            if not name or not name[0].isalpha():
                break
            field_ptr = flash.u32(base + 4)
            field_count = flash.u8(base + 8)
            reserved_09 = flash.u8(base + 9)
            fields = []
            if field_ptr and flash.is_flash_ptr(field_ptr):
                for j in range(field_count):
                    field_vid = flash.u16(field_ptr + j * 2)
                    field_name = names.name(field_vid) if names and field_vid is not None else None
                    fields.append((field_vid, field_name))
            capacity = flash.u16(base + 0xA)
            trigger_vid = flash.u16(base + 0xC)
            timer_index = flash.u8(base + 0xE)
            flags = flash.u8(base + 0xF)
            secondary_vid = flash.u16(base + 0x10)
            secondary_param = flash.u16(base + 0x12)
            idle_value = flash.u32(base + 0x14)
            tracker_idx = flash.u16(base + 0x18)
            trigger_name = names.name(trigger_vid) if names and trigger_vid else None
            secondary_name = names.name(secondary_vid) if names and secondary_vid else None
            tracker_vid = g4_id_base + tracker_idx if g4_id_base is not None else None
            tracker_name = names.name(tracker_vid) if names and tracker_vid is not None else None
            self.entries.append({
                'name': name, 'field_ptr': field_ptr, 'field_count': field_count,
                'reserved_09': reserved_09, 'fields': fields,
                'capacity': capacity, 'trigger_vid': trigger_vid,
                'trigger_name': trigger_name, 'timer_index': timer_index,
                'flags': flags, 'secondary_vid': secondary_vid,
                'secondary_name': secondary_name, 'secondary_param': secondary_param,
                'idle_value': idle_value, 'tracker_idx': tracker_idx,
                'tracker_vid': tracker_vid, 'tracker_name': tracker_name,
            })
            i += 1
        print(f"[+] globals[19]: stream table, {len(self.entries)} streams")

    def dump(self):
        lines = ["  Stream  Capacity  Timer  Trigger  State g[4]  Fields             Purpose"]
        for e in self.entries:
            trigger = e['trigger_name'] or f"0x{e['trigger_vid']:04X}"
            tracker = e['tracker_name'] or f"idx 0x{e['tracker_idx']:03X}"
            fields = ','.join(
                name or (f"0x{vid:04X}" if vid is not None else "?")
                for vid, name in e['fields'])
            lines.append(f"  {e['name']:>5}  {e['capacity']:>8}  g1[{e['timer_index']}]  "
                         f"{trigger:>7}  {tracker:>9}  {fields:<18} "
                         f"{self.PURPOSES.get(e['name'], '')}")
        return "\n".join(lines)


class NameMetadataPool:
    """Parse the g[22] identity list and adjacent g[23] name-record pool.

    The g[22] root contains 16 identity var_ids. The following records are
    pointer-owned by the g[23] bucket index.
    """
    HEADER_COUNT = 16

    def __init__(self, flash, g22_addr, g22_end, names=None):
        self.header_vids = []
        self.entries = []       # (label, var_id, uart_name)
        self.by_label = {}      # label -> var_id
        self.by_varid = {}      # var_id -> label
        self.header_count = self.HEADER_COUNT

        for i in range(self.header_count):
            vid = flash.u16(g22_addr + i * 2)
            if vid is not None:
                self.header_vids.append(vid)

        off = g22_addr + self.header_count * 2
        while off < g22_end:
            c0 = flash.u8(off)
            c1 = flash.u8(off + 1)
            vid = flash.u16(off + 2)
            if c0 is None or c1 is None or vid is None:
                break
            if c0 == 0 and c1 == 0 and vid == 0:
                break
            label = chr(c0) + chr(c1) if 0x20 <= c0 < 0x7F and 0x20 <= c1 < 0x7F else "??"
            uart = names.name(vid) if names else None
            self.entries.append((label, vid, uart))
            self.by_label[label] = vid
            self.by_varid[vid] = label
            off += 4

        print(f"[+] globals[22]: {len(self.header_vids)} identity export IDs; "
              f"adjacent g[23] pool has {len(self.entries)} records")

    def dump(self, names=None):
        lines = [f"  {len(self.entries)} shared UART name-pool records:"]
        lines.append(f"  {'Suffix':>6}  {'VarID':>10}  {'UART':>5}")
        for label, vid, uart in self.entries:
            u = uart or ""
            lines.append(f"  {label:>5}  0x{vid:04X}      {u:>5}")
        return "\n".join(lines)

    def dump_header(self, names=None):
        lines = ["  Identity TGT export var_ids:"]
        for vid in self.header_vids:
            n = names.name(vid) if names else None
            ns = f":{n}" if n else ""
            lines.append(f"    0x{vid:04X}{ns}")
        return "\n".join(lines)

    def lookup(self, query):
        """Lookup by UART name, 2-char suffix, or var_id."""
        if isinstance(query, int):
            return [(l, v, u) for l, v, u in self.entries if v == query]
        else:
            q = query.upper()
            return [(l, v, u) for l, v, u in self.entries if l == q or u == q]


def _signal_value_info(db, var_id):
    if not db:
        return ""
    entry = db.get(var_id)
    if isinstance(entry, Entry8):
        labels = entry.option_strings(db)
        source = None
        meta = _metadata_enum_labels(db, entry) if not labels else None
        if meta:
            source, labels = meta[0], list(meta[1])
        if labels:
            text = "  [enum: " + ", ".join(f"{i}={label}" for i, label in enumerate(labels))
            if source:
                text += f"; source={source}"
            return text + "]"
        if entry.num_options:
            return "  [enum: " + ", ".join(str(i) for i in range(entry.num_options)) + "]"
        return ""
    if not isinstance(entry, Entry4):
        return ""
    unit = ""
    if entry.units_str_id and entry.units_str_id not in (0xFFFF, 0xDE):
        text = db.string(entry.units_str_id)
        if text:
            unit = f" {text}"
    return (f"  [phys={entry._fmt(entry.min_value)}..{entry._fmt(entry.max_value)}{unit}; "
            f"raw={entry.min_value}..{entry.max_value}; "
            f"scale={entry.scale_str()}]")


class SignalChannel:
    """Signal channel descriptor. Used for BRP, CSL, STR, OXH, etc.

    Two formats depending on where count/name appear:

    BRP/CSL/STR format (globals[11]/[12]/[13]):
      +0x00: u32 config_a
      +0x04: u32 config_b
      +0x08: u8  field_count, char[3] name
      +0x0C: u32 reserved
      +0x10: u32 var_id_array_ptr
      +0x14: u32 config_array_ptr
      +0x18: u32 param (sample count?)
      +0x1C: u32 name_string_ptr

    OXH format (globals[28]):
      +0x00: u8  field_count, char[3] name
      +0x04: u32 reserved
      +0x08: u32 var_id_array_ptr
      +0x0C: u32 output_array_ptr
    """
    def __init__(self, flash, gidx, addr, names=None, forced_header_size=None):
        self.gidx = gidx
        self.addr = addr
        self.name = "?"
        self.count = 0
        self.var_ids = []       # [(vid, uart_name)]
        self.field_names = []   # per-field signal names (e.g. "Flow.40ms")
        self.samples_per_rec = []  # per-field samples per EDF data record
        self.param = None
        self.format = None      # 'extended', 'compact', or 'oxh'

        # Try OXH format: count+name at +0x00, array ptr at +0x08
        name_00 = flash.blob(addr + 1, 3)
        count_00 = flash.u8(addr)

        # Try BRP format: count+name at +0x08, array ptr at +0x10
        name_08 = flash.blob(addr + 0x09, 3)
        count_08 = flash.u8(addr + 0x08)

        self.header_size = 0

        if name_08 and all(0x41 <= b <= 0x5A for b in name_08) and count_08 and 0 < count_08 < 200:
            self.name = name_08.decode('ascii')
            self.count = count_08
            arr_ptr = flash.u32(addr + 0x10)
            if gidx == 12:
                self.format = 'event'
                self.header_size = forced_header_size or 0x18
            else:
                # Samples-per-record array at +0x14
                spr_ptr = flash.u32(addr + 0x14)
                if spr_ptr and flash.is_flash_ptr(spr_ptr):
                    for i in range(self.count):
                        v = flash.u16(spr_ptr + i * 2)
                        self.samples_per_rec.append(v if v is not None else 0)
                names_ptr = flash.u32(addr + 0x1C)
                if names_ptr and flash.is_flash_ptr(names_ptr):
                    self.format = 'extended'
                    self.header_size = forced_header_size or 0x20
                    self.param = flash.u32(addr + 0x18)
                    for i in range(self.count):
                        sp = flash.u32(names_ptr + i * 4)
                        if sp and flash.is_flash_ptr(sp):
                            s = flash.cstr(sp)
                            self.field_names.append(s.decode('ascii', errors='replace') if s else None)
                        else:
                            self.field_names.append(None)
                else:
                    self.format = 'compact'
                    self.header_size = forced_header_size or 0x18
        elif name_00 and all(0x41 <= b <= 0x5A for b in name_00) and count_00 and 0 < count_00 < 200:
            self.name = name_00.decode('ascii')
            self.count = count_00
            arr_ptr = flash.u32(addr + 0x08)
            # Check for second pointer at +0x0C — if valid flash ptr, stride is 0x14
            ptr2 = flash.u32(addr + 0x0C)
            if ptr2 and flash.is_flash_ptr(ptr2):
                self.format = 'oxh_ext'
                self.header_size = forced_header_size or 0x14
            else:
                self.format = 'oxh'
                self.header_size = forced_header_size or 0x10
        else:
            return

        if arr_ptr and flash.is_flash_ptr(arr_ptr):
            for i in range(self.count):
                vid = flash.u16(arr_ptr + i * 2)
                if vid is not None:
                    self.var_ids.append((vid, names.name(vid) if names else None))

        print(f"[+] globals[{gidx}]: {self.name} ({self.count} fields)")

    def dump(self, db=None):
        lines = [f"  {self.name} ({self.count} fields) @ 0x{self.addr:08X}:"]
        for i, (vid, uart) in enumerate(self.var_ids):
            u = f":{uart}" if uart else ""
            fn = f"  \"{self.field_names[i]}\"" if i < len(self.field_names) and self.field_names[i] else ""
            spr = ""
            if i < len(self.samples_per_rec):
                n = self.samples_per_rec[i]
                # Assume 60s record duration for rate calculation
                rate = n / 60.0 if n > 1 else 0
                spr = f"  [{n} samp" + (f", {rate:.1f} Hz" if rate > 0 else "") + "]"
            lines.append(f"    0x{vid:04X}{u}{fn}{spr}{_signal_value_info(db, vid)}")
        return "\n".join(lines)


class SignalGroup:
    """Parse NPD, NPA, or ALA signal groups from globals[14] or globals[15].

    NPD (globals[14], 28 bytes):
      +0x00: u16 flags, u16 id
      +0x04: u32 param
      +0x08: u32 threshold
      +0x0C: u32 session_config
      +0x10: u8  signal_count, char[3] group_name
      +0x14: u32 reserved
      +0x18: u32 var_id_array_ptr

    NPA/ALA (globals[15], 24 bytes):
      +0x00: u16 flags, u16 id
      +0x04: u16 sample_rate?, u16 param
      +0x08: u8  signal_count, char[3] group_name
      +0x0C: u32 reserved
      +0x10: u32 var_id_array_ptr
      +0x14: u16 linked_var_id
    """
    PURPOSES = {
        'NPD': 'NIGHT_PROFILE_PERIODIC',
        'NPA': 'NIGHT_PROFILE_APNEA',
        'ALA': 'ALARM_LOG_APERIODIC',
    }

    def __init__(self, flash, addr, names=None):
        self.addr = addr
        self.signals = []
        self.name = "?"
        self.linked_vid = None
        self.linked_uart = None

        # Try NPD format first (name at +0x10)
        count_10 = flash.u8(addr + 0x10)
        name_10 = flash.blob(addr + 0x11, 3)

        # Try NPA format (name at +0x08)
        count_08 = flash.u8(addr + 0x08)
        name_08 = flash.blob(addr + 0x09, 3)

        if name_10 and all(0x41 <= b <= 0x5A for b in name_10):
            # NPD format
            self.name = name_10.decode('ascii')
            count = count_10
            arr_ptr = flash.u32(addr + 0x18)
        elif name_08 and all(0x41 <= b <= 0x5A for b in name_08):
            # NPA format
            self.name = name_08.decode('ascii')
            count = count_08
            arr_ptr = flash.u32(addr + 0x10)
            self.linked_vid = flash.u16(addr + 0x14)
            if self.linked_vid is not None and names:
                self.linked_uart = names.name(self.linked_vid)
        else:
            return

        if arr_ptr and flash.is_flash_ptr(arr_ptr):
            for i in range(count):
                vid = flash.u16(arr_ptr + i * 2)
                if vid is not None:
                    uart = names.name(vid) if names else None
                    self.signals.append((vid, uart))

    def dump(self):
        linked_name = f":{self.linked_uart}" if self.linked_uart else ""
        linked = (f", linked=0x{self.linked_vid:04X}{linked_name}"
                  if self.linked_vid is not None else "")
        purpose = self.PURPOSES.get(self.name)
        label = f"{self.name} {purpose}" if purpose else self.name
        lines = [f"  {label} ({len(self.signals)} signals{linked}):"]
        for vid, uart in self.signals:
            n = f":{uart}" if uart else ""
            lines.append(f"    0x{vid:04X}{n}")
        return "\n".join(lines)


class SignalGroupTable:
    """Sequence of 24-byte g[15] signal-group records."""
    STRIDE = 0x18

    def __init__(self, flash, addr, end_addr, names=None):
        self.groups = []
        count = max(0, (end_addr - addr) // self.STRIDE)
        for i in range(count):
            group = SignalGroup(flash, addr + i * self.STRIDE, names)
            if not group.signals:
                break
            self.groups.append(group)

    def dump(self):
        return "\n".join(group.dump() for group in self.groups)


class TimerScaleTable:
    """Parse globals[1] -- Scheduler and logical-period profiles.

    14 entries of 16 bytes each:
      +0x00: u8   scheduler level
      +0x01: u8   pad
      +0x02: u16  base cadence in 10 ms ticks
      +0x04: u32  cadence variant multiplier
      +0x08: f64  logical period in seconds
    """
    STRIDE = 16

    def __init__(self, flash, addr, end_addr):
        self.addr = addr
        self.entries = []
        count = (end_addr - addr) // self.STRIDE
        for i in range(count):
            ea = addr + i * self.STRIDE
            level = flash.u8(ea)
            ticks = flash.u16(ea + 2)
            mult = flash.u32(ea + 4)
            o = flash._o(ea + 8)
            period = struct.unpack_from('<d', flash.data, o)[0] if o is not None else 0.0
            self.entries.append(dict(idx=i, level=level, ticks=ticks,
                                     multiplier=mult, period=period))

    def dump(self):
        lines = [f"  {len(self.entries)} entries (stride {self.STRIDE}):"]
        lines.append(f"  {'idx':>4s}  {'queue':>5s}  {'base':>5s}  {'mult':>4s}  {'period':>12s}")
        for e in self.entries:
            p = e['period']
            if p >= 3600:
                ps = f"{p:.0f}s ({p/3600:.1f}h)"
            elif p >= 60:
                ps = f"{p:.0f}s ({p/60:.0f}m)"
            elif p >= 1:
                ps = f"{p:.0f}s"
            else:
                ps = f"{p*1000:.0f}ms"
            lines.append(f"  [{e['idx']:2d}]  {e['level']:5d}  {e['ticks']:5d}  {e['multiplier']:4d}  {ps:>12s}")
        return "\n".join(lines)


class ModeTable:
    """Parse globals[24] -- Setting-to-mode membership table.

    globals[24] = pointer to table data
    globals[25] = entry count (49 on AirSense, not a flash pointer)

    Each entry:
      +0x00: u16      var_id (setting variable)
      +0x02: u8[]     mode_flags (0x00 or 0x01, one per MOP option)
    """
    FALLBACK_NUM_FLAGS = 12

    def __init__(self, flash, addr, count, names=None, num_flags=None):
        self.addr = addr
        self.count = count
        self.num_flags = num_flags or self.FALLBACK_NUM_FLAGS
        self.stride = 2 + self.num_flags
        self.entries = []

        for i in range(count):
            ea = addr + i * self.stride
            vid = flash.u16(ea)
            if vid is None:
                break
            flags = []
            for f in range(self.num_flags):
                b = flash.u8(ea + 2 + f)
                flags.append(b if b is not None else 0)
            uart = names.name(vid) if names else None
            self.entries.append(dict(idx=i, var_id=vid, uart=uart, flags=flags))

    def dump(self):
        hdr = "     var_id     " + " ".join(f"{i:>2d}" for i in range(self.num_flags))
        lines = [f"  {len(self.entries)} entries (stride {self.stride}):", f"  {hdr}"]
        for e in self.entries:
            n = f":{e['uart']}" if e['uart'] else ""
            fstr = "  ".join(str(f) for f in e['flags'])
            lines.append(f"  [{e['idx']:2d}] 0x{e['var_id']:04X}{n:>4s}   {fstr}")
        return "\n".join(lines)


class PDLTable:
    """Parse the globals[20] PDL variable list and globals[21] rules.

    Structure at globals[20]:
      +0x00: char[4]  name ("PDL\\0")
      +0x04: u32      var_id_array_ptr (-> array of u16 var_ids)
      +0x08: u32      var_id_count
      +0x0C: rule entries (also referenced by g[21])

    Each rule entry (16 bytes):
      +0x00: u16      var_id_a
      +0x02: u16      var_id_b
      +0x04: u32      flags (0x00000000..0x00030000)
      +0x08: u32      param_a (0xFFFFFFFF = unused)
      +0x0C: u32      param_b (0xFFFFFFFF = unused)

    globals[21] is a {u32 count, u32 ptr} that points into g[20]+0x0C,
    providing a separate access path to the same rule entries.
    """
    def __init__(self, flash, addr, rules_ref=None, names=None):
        self.addr = addr
        self.var_ids = []      # list of (var_id, uart_name)
        self.rules = []        # list of dicts
        self.name = "?"

        # Header
        raw_name = flash.blob(addr, 4)
        if raw_name:
            self.name = raw_name.rstrip(b'\x00').decode('ascii', errors='replace')
        arr_ptr = flash.u32(addr + 0x04)
        count = flash.u32(addr + 0x08)

        # Var_id array
        if arr_ptr and flash.is_flash_ptr(arr_ptr) and count and count < 200:
            for i in range(count):
                vid = flash.u16(arr_ptr + i * 2)
                if vid is not None:
                    uart = names.name(vid) if names else None
                    self.var_ids.append((vid, uart))

        rule_base = addr + 0x0C
        rule_count = None
        if rules_ref and flash.is_flash_ptr(rules_ref):
            count_from_g21 = flash.u32(rules_ref)
            ptr_from_g21 = flash.u32(rules_ref + 4)
            if count_from_g21 is not None and count_from_g21 < 200:
                rule_count = count_from_g21
            if ptr_from_g21 and flash.is_flash_ptr(ptr_from_g21):
                rule_base = ptr_from_g21
        if rule_count is None:
            rule_count = 0
            while rule_count < 64:
                ea = rule_base + rule_count * 16
                if flash.u16(ea) is None:
                    break
                rule_count += 1

        for i in range(rule_count):
            ea = rule_base + i * 16
            vid_a = flash.u16(ea + 0x00)
            vid_b = flash.u16(ea + 0x02)
            flags = flash.u32(ea + 0x04)
            param_a = flash.u32(ea + 0x08)
            param_b = flash.u32(ea + 0x0C)
            if vid_a is None:
                break
            ua = names.name(vid_a) if names else None
            ub = names.name(vid_b) if names else None
            self.rules.append(dict(
                idx=i, vid_a=vid_a, vid_b=vid_b, name_a=ua, name_b=ub,
                flags=flags, param_a=param_a, param_b=param_b))

    def dump(self):
        lines = [f"  {self.name} ({len(self.var_ids)} vars, {len(self.rules)} rules)"]
        lines.append(f"  Var_ids:")
        for i, (vid, uart) in enumerate(self.var_ids):
            n = f":{uart}" if uart else ""
            lines.append(f"    [{i:2d}] 0x{vid:04X}{n}")
        lines.append(f"  Rules:")
        for r in self.rules:
            na = f":{r['name_a']}" if r['name_a'] else ""
            nb = f":{r['name_b']}" if r['name_b'] else ""
            fg = (r['flags'] >> 8) & 0xFF
            pa = f"0x{r['param_a']:08X}" if r['param_a'] != 0xFFFFFFFF else "--"
            pb = f"0x{r['param_b']:08X}" if r['param_b'] != 0xFFFFFFFF else "--"
            lines.append(f"    [{r['idx']:2d}] a=0x{r['vid_a']:04X}{na}  b=0x{r['vid_b']:04X}{nb}  "
                         f"type={fg}  param_a={pa}  param_b={pb}")
        return "\n".join(lines)

    def dump_rules(self):
        """Dump only the rule entries (for g21 command)."""
        lines = [f"  {len(self.rules)} rule entries (stride 16, from {self.name}+0x0C):"]
        for r in self.rules:
            na = f":{r['name_a']}" if r['name_a'] else ""
            nb = f":{r['name_b']}" if r['name_b'] else ""
            fg = (r['flags'] >> 8) & 0xFF
            pa = f"0x{r['param_a']:08X}" if r['param_a'] != 0xFFFFFFFF else "--"
            pb = f"0x{r['param_b']:08X}" if r['param_b'] != 0xFFFFFFFF else "--"
            lines.append(f"    [{r['idx']:2d}] a=0x{r['vid_a']:04X}{na}  b=0x{r['vid_b']:04X}{nb}  "
                         f"type={fg}  param_a={pa}  param_b={pb}")
        return "\n".join(lines)


class DB:
    def __init__(self, flash, ta, g2=None, raw=None,
                 globals_addr=None, globals_values=None):
        self.fl = flash
        self.g2_addr = g2
        self.raw_strings = raw
        self.globals_addr = globals_addr
        if globals_values is None:
            raise ValueError("globals[] array not found")
        self.globals_values = {
            idx: value for idx, value in globals_values.items()
            if value is not None
        }
        self.tables = {}
        self.by_varid = {}
        self.strtab = None
        self.names = None      # NameLookup (globals[23])
        self.streams = None    # StreamTable (globals[19])
        self.npd = None        # SignalGroup (globals[14])
        self.npa = None        # First SignalGroup from globals[15]
        self.g15_groups = None # SignalGroupTable (globals[15])
        self.device = None     # DeviceIdentity (globals[0])
        self.vargroups = None  # VariableGroups (globals[16])
        self.desc17 = None     # DescriptorTable (globals[17])
        self.desc18 = None     # DescriptorTable (globals[18])
        self.nametab = None    # g[22] identity list and adjacent g[23] record pool
        self.pdl = None        # PDLTable (globals[20] list and globals[21] rules)
        self.modes = None      # ModeTable (globals[24], setting-to-mode flags)
        self.timers = None     # TimerScaleTable (globals[1])
        self.channels = {}     # gidx -> SignalChannel (globals[11,12,13,28])
        self.table_bases = {}  # table_num -> base address
        self.id_bases = {}     # table_num -> first var_id, derived from globals[23]
        self.g5_ptr = None
        self.g5_count = 0
        self.g5_base_idx = None
        self.g5_end_idx = None
        self.g5_alias_count = 0
        self.g7_addr = ta.get('globals7')
        self.g7_size = 0
        self.g7_alloc_size = 0
        self.g4_subrange_base_idx = None
        self.no_string_id = None

        g23 = ta.get('names')
        if g23:
            self.names = NameLookup(flash, g23)
        self._load_var_tables(flash, ta)
        if self.g7_addr and 6 in self.tables:
            self.g7_size = max(
                (e.pool_offset + e.item_count for e in self.tables[6]),
                default=0)
            g8_addr = ta.get('table8')
            if g8_addr and g8_addr > self.g7_addr:
                self.g7_alloc_size = g8_addr - self.g7_addr

        # G2 gives string slot count; LAN gives the labels/order for those slots.
        n = infer_language_count_from_g2(flash, g2) if g2 else None
        lan_n, labels, ids = detect_languages(
            flash, ta, self._table_index_for_name('LAN', 8, fallback=5))
        if n is not None and n != lan_n:
            raise ValueError(
                f"language count mismatch: globals[2] has {n} slots, "
                f"LAN mask has {lan_n} ({', '.join(labels)})")
        self.num_languages = n if n is not None else lan_n
        self.lang_labels = labels
        self.lang_ids = ids
        print(f"[+] Languages: {self.num_languages} locales [{', '.join(labels)}]")

        if g2:
            self.strtab = StringTable(flash, g2, self.num_languages, raw)
            raw_s = f"0x{raw:08X}" if raw else "auto"
            print(f"[+] Strings: globals[2]=0x{g2:08X}, "
                  f"raw={raw_s}, count={self.strtab.count}")
            self.no_string_id = self._infer_no_string_id()

        # Load timer scale table (globals[1], bounded by globals[2])
        g1 = ta.get('timers')
        if g1 and g2:
            self.timers = TimerScaleTable(flash, g1, g2)
            if self.timers.entries:
                print(f"[+] globals[1]: timer scale table ({len(self.timers.entries)} entries)")

        # Load device identity (globals[0])
        g0 = ta.get('device')
        if g0:
            self.device = DeviceIdentity(flash, g0)

        # Load variable groups (globals[16])
        g16 = ta.get('vargroups')
        g17 = ta.get('desc17')
        if g16:
            self.vargroups = VariableGroups(flash, g16, g17, self.names)

        # Load descriptor tables (globals[17], [18])
        g18 = ta.get('desc18')
        g19 = ta.get('streams')
        object_id = self.id_bases.get(10, 0) + len(self.tables.get(10, []))
        if g17:
            self.desc17 = DescriptorTable(flash, 17, g17, object_id, self.names)
        if g18:
            self.desc18 = DescriptorTable(flash, 18, g18, object_id + 1, self.names)

        # The g[23] record pool is packed directly after the g[22] identity list.
        g22 = ta.get('name_pool')
        g22_end = ta.get('names')  # g[23] is the end boundary
        if g22 and g22_end:
            self.nametab = NameMetadataPool(flash, g22, g22_end, self.names)

        # Load stream table (globals[19])
        g19 = ta.get('streams')
        g20 = ta.get('pdl')
        if g19:
            self.streams = StreamTable(
                flash, g19, g20, self.names, self.id_bases.get(4))

        # Load signal groups (globals[14]/[15])
        g14 = ta.get('npd')
        if g14:
            self.npd = SignalGroup(flash, g14, self.names)
            if self.npd.signals:
                print(f"[+] globals[14]: {self.npd.name} ({len(self.npd.signals)} signals)")
        g15 = ta.get('npa')
        g16 = ta.get('vargroups')
        if g15 and g16:
            self.g15_groups = SignalGroupTable(flash, g15, g16, self.names)
            if self.g15_groups.groups:
                self.npa = self.g15_groups.groups[0]
                summary = ", ".join(
                    f"{g.name} ({len(g.signals)})" for g in self.g15_groups.groups)
                print(f"[+] globals[15]: {summary}")

        # Load PDL (globals[20], also covers g[21] rules)
        if g20:
            self.pdl = PDLTable(flash, g20, ta.get('pdl_rules'), self.names)
            if self.pdl.var_ids:
                print(f"[+] globals[20]: {self.pdl.name} ({len(self.pdl.var_ids)} vars, {len(self.pdl.rules)} rules)")

        # Load mode table (globals[24], count from globals[25])
        g24 = ta.get('modes')
        g25 = ta.get('modes_count')
        if g24 and g25:
            self.modes = ModeTable(flash, g24, g25, self.names, self._mode_count())
            if self.modes.entries:
                print(f"[+] globals[24]: mode table ({len(self.modes.entries)} settings x {self.modes.num_flags} modes)")

        # Header roots and referenced payload arrays are separate objects. Use
        # each consumer's record shape instead of the next globals[] root as a
        # generic table boundary.
        self._load_channel_records(flash, ta.get('brp'), 11, 3, 0x20)
        g12_stride = self._detect_g12_stride(flash, ta.get('csl'))
        self._load_channel_records(flash, ta.get('csl'), 12, 3, g12_stride)
        self._load_channel_records(flash, ta.get('str_ch'), 13, 1, 0x24)
        self._load_channel_window(flash, ta.get('tce'), ta.get('apn'), 26, 0x14)
        self._load_channel_records(flash, ta.get('apn'), 27, 3, 0x10)
        self._load_channel_records(flash, ta.get('oxh'), 28, 1, 0x14)

        g5 = ta.get('globals5')
        if g5:
            self._load_g5(g5)

        print(f"[+] Total: {len(self.by_varid)} variables")

    def _load_channel_records(self, flash, addr, gidx, count, stride):
        if not addr or not stride:
            return
        for i in range(count):
            ch = SignalChannel(
                flash, gidx, addr + i * stride, self.names,
                forced_header_size=stride)
            if not ch.var_ids:
                break
            self.channels[ch.name] = ch

    def _load_channel_window(self, flash, addr, end_addr, gidx, stride):
        if not addr or not end_addr:
            return
        count = max(0, (end_addr - addr) // stride)
        self._load_channel_records(flash, addr, gidx, count, stride)

    @staticmethod
    def _detect_g12_stride(flash, addr):
        if not addr:
            return None
        for stride in (0x18, 0x1C):
            valid = True
            for i in range(3):
                name = flash.blob(addr + i * stride + 0x09, 3)
                if not name or not all(0x41 <= b <= 0x5A for b in name):
                    valid = False
                    break
            if valid:
                return stride
        return None

    def _load_var_tables(self, flash, ta):
        next_id_base = None
        for tnum in (3, 4, 6, 8, 9, 10):
            base = ta.get(f"table{tnum}")
            if not base:
                continue
            self.table_bases[tnum] = base
            info = TABLES[tnum]
            cls = ENTRY_CLS[tnum]
            count = self._table_count(tnum, base, info['stride'])
            id_base = self._infer_id_base(tnum, count, next_id_base)
            self.id_bases[tnum] = id_base
            next_id_base = id_base + count
            entries = []
            for i in range(count):
                addr = base + i * info['stride']
                entries.append(cls(flash, addr, i, id_base))
            self.tables[tnum] = entries
            for e in entries:
                self.by_varid[e.var_id] = e
            print(f"[+] globals[{tnum}]: {len(entries)} entries @ 0x{base:08X}")

        if 4 in self.tables:
            self.g4_subrange_base_idx = self._infer_g4_subrange_base()

    def _infer_g4_subrange_base(self):
        prev_had_b7 = False
        for entry in self.tables[4]:
            has_b7 = bool(entry.flags & 0x0080)
            if prev_had_b7 and not has_b7:
                return entry.idx
            prev_had_b7 = has_b7
        return None

    def _infer_no_string_id(self):
        # Firmware enum-string code compares base_str_id against a per-build
        # sentinel. ROP is a stable no-label enum and carries that sentinel.
        rop = self._entry_for_name('ROP')
        if not isinstance(rop, Entry8):
            return None
        for sid in (rop.base_str_id, rop.name_str_id):
            if sid in (-1, 0, 0xFFFF) or sid < 0:
                continue
            vals = self.strings_all(sid)
            if vals and all(v == "" for v in vals):
                return sid
        return None

    def _table_index_for_name(self, name, table_num, fallback=None):
        if self.names:
            vid = self.names.var_id(name)
            base = self.id_bases.get(table_num)
            entries = self.tables.get(table_num)
            if vid is not None and base is not None and entries:
                idx = vid - base
                if 0 <= idx < len(entries):
                    return idx
        return fallback

    def _entry_for_name(self, name):
        if not self.names:
            return None
        vid = self.names.var_id(name)
        return self.get(vid) if vid is not None else None

    def _mode_count(self):
        mop = self._entry_for_name('MOP')
        if isinstance(mop, Entry8) and mop.num_options:
            return mop.num_options
        return ModeTable.FALLBACK_NUM_FLAGS

    def _next_global_ptr_after(self, base):
        candidates = [
            value for value in self.globals_values.values()
            if self.fl.is_flash_ptr(value) and value > base
        ]
        return min(candidates) if candidates else None

    def _table_count(self, tnum, base, stride):
        if tnum == 10:
            return self._table10_count(base, stride)
        end = self._next_global_ptr_after(base)
        if end is None:
            raise ValueError(f"cannot infer globals[{tnum}] count")
        size = end - base
        if size <= 0:
            raise ValueError(f"globals[{tnum}] size 0x{size:X} is invalid")
        rem = size % stride
        if rem:
            count = size // stride
            pad = self.fl.blob(base + count * stride, rem)
            # Older SX584 aligns the following table after g[3], leaving a
            # short zero pad that is not part of the descriptor array.
            if tnum == 3 and 0 < rem < 4 and count > 0 and pad and all(b == 0x00 for b in pad):
                return count
            raise ValueError(
                f"globals[{tnum}] size 0x{size:X} is not aligned to stride 0x{stride:X}")
        return size // stride

    def _table10_count(self, base, stride):
        count = 0
        for i in range(64):
            addr = base + i * stride
            if not self._valid_table10_entry(addr):
                break
            count += 1
        if count == 0:
            raise ValueError("cannot infer globals[10] count")
        return count

    def _valid_table10_entry(self, addr):
        flags = self.fl.u16(addr)
        callback = self.fl.u8(addr + 0x02)
        default = self.fl.s32(addr + 0x08)
        max_value = self.fl.s32(addr + 0x0C)
        min_value = self.fl.s32(addr + 0x10)
        decimal_places = self.fl.u8(addr + 0x14)
        scale = self.fl.s16(addr + 0x16)
        step = self.fl.s16(addr + 0x18)
        if None in (flags, callback, default, max_value, min_value,
                    decimal_places, scale, step):
            return False
        if flags & ~0x00FF:
            return False
        if callback > 64:
            return False
        if max_value < min_value:
            return False
        if decimal_places > 6:
            return False
        if scale == 0 or abs(scale) > 10000:
            return False
        if step <= 0 or abs(step) > 10000:
            return False
        return True

    def _load_g5(self, addr):
        end = self._next_global_ptr_after(addr)
        if end is None:
            raise ValueError("cannot infer globals[5] size")
        size = end - addr
        if size <= 0 or size % 4:
            raise ValueError(f"globals[5] size 0x{size:X} is not aligned")
        if 4 not in self.tables:
            raise ValueError("globals[4] not loaded; cannot map globals[5]")

        # The final B8-tagged g[4] records are a shared handler tail; they reuse
        # the first g[5] records rather than extending the physical g[5] window.
        alias_count = 0
        for entry in reversed(self.tables[4]):
            if entry.flags & 0x0100:
                alias_count += 1
            else:
                break

        count = size // 4
        base_idx = len(self.tables[4]) - count - alias_count
        if base_idx < 0:
            raise ValueError("globals[5] is larger than the globals[4] tail window")

        self.g5_ptr = addr
        self.g5_count = count
        self.g5_base_idx = base_idx
        self.g5_end_idx = base_idx + count
        self.g5_alias_count = alias_count
        print(f"[+] globals[5]: alternate-label table @ 0x{addr:08X} "
              f"({count} entries, idx 0x{base_idx:03X}..0x{self.g5_end_idx-1:03X})")

    def _infer_id_base(self, tnum, count, expected_base):
        if not self.names:
            raise ValueError(f"globals[23] not loaded; cannot infer globals[{tnum}] var_id base")
        ids = set(self.names.by_varid)
        if expected_base is not None:
            if self._has_id_range(ids, expected_base, count):
                return expected_base
            raise ValueError(
                f"globals[{tnum}] var_id range 0x{expected_base:04X}"
                f"..0x{expected_base + count - 1:04X} missing from globals[23]")

        for candidate in sorted(ids):
            if candidate - 1 in ids:
                continue
            if self._has_id_range(ids, candidate, count):
                return candidate
        raise ValueError(f"cannot infer globals[{tnum}] var_id base from globals[23]")

    @staticmethod
    def _has_id_range(ids, start, count):
        return all(start + i in ids for i in range(count))

    def uart_name(self, var_id):
        """Return 3-letter UART name for var_id, or None."""
        return self.names.name(var_id) if self.names else None

    def get(self, vid):
        return self.by_varid.get(vid)

    def g4_by_idx(self, idx):
        entries = self.tables.get(4)
        if entries and 0 <= idx < len(entries):
            entry = entries[idx]
            if isinstance(entry, Entry4):
                return entry
        return None

    def string(self, sid, lang=0):
        return self.strtab.get(sid, lang) if self.strtab else None

    def strings_all(self, sid):
        return self.strtab.get_all(sid) if self.strtab else [None] * self.num_languages

    def g5_lookup(self, t4_idx):
        """Look up globals[5] alternate-label record for a [4] table index.
        Returns (str_id_a, str_id_b) or None if not in range or g5 not loaded."""
        if self.g5_ptr is None or self.g5_base_idx is None:
            return None
        if not (self.g5_base_idx <= t4_idx < self.g5_end_idx):
            return None
        offset = t4_idx - self.g5_base_idx
        addr = self.g5_ptr + offset * 4
        a = self.fl.u16(addr)
        b = self.fl.u16(addr + 2)
        return (a, b)

    def chain(self, entry):
        result = [entry]
        if isinstance(entry, Entry3):
            nxt = entry.dependency_idx
        elif isinstance(entry, Entry4):
            nxt = entry.next_var_idx
        elif isinstance(entry, Entry6):
            nxt = entry.dependency_idx
        elif isinstance(entry, Entry8):
            nxt = entry.linked_var_idx
        elif isinstance(entry, Entry9):
            nxt = entry.dependency_idx
        else:
            return result
        seen = set()
        while nxt != 0x7FFF and nxt >= 0 and nxt not in seen and len(result) < 10:
            seen.add(nxt)
            e = self.g4_by_idx(nxt)
            if not e or not isinstance(e, Entry4):
                result.append(f"[4] idx=0x{nxt:04X} (not loaded)")
                break
            result.append(e)
            nxt = e.next_var_idx
        return result



def parse_numeric_arg(value, what="number"):
    try:
        return int(value, 0)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"{what} must be decimal or explicit hex") from exc


def resolve_var_arg(db, ident):
    try:
        return int(ident, 0)
    except ValueError:
        pass
    if db.names:
        vid = db.names.var_id(ident)
        if vid is not None:
            return vid
    raise ValueError(f"could not resolve {ident!r} to a var_id")


def _print_var_detail(db, ident, verbose=False):
    vid = resolve_var_arg(db, ident)
    e = db.get(vid)
    if not e:
        print(f"  var 0x{vid:04X} not found")
        return
    print(e.detail(db) if verbose else f"  {e.oneline(db)}")


def _print_table(db, tnum, idx=None, to=None):
    if tnum not in db.tables:
        print(f"  globals[{tnum}] not loaded")
        return
    n = len(db.tables[tnum])
    if idx is None:
        for i in range(n):
            print(f"  {db.tables[tnum][i].oneline(db)}")
        return

    idx = parse_numeric_arg(idx, "index")
    to = parse_numeric_arg(to, "end index") if to is not None else None
    if to is not None:
        for i in range(idx, min(to, n)):
            print(f"  {db.tables[tnum][i].oneline(db)}")
    elif 0 <= idx < n:
        print(db.tables[tnum][idx].detail(db))
    else:
        e = db.get(idx)
        if e and e.TABLE == tnum:
            print(e.detail(db))
            return
        id_hint = ""
        id_base = db.id_bases.get(tnum)
        if id_base is not None:
            id_hint = f"  var_ids: 0x{id_base:04X}..0x{id_base+n-1:04X}"
        print(f"  idx 0x{idx:X} out of range (0..0x{n-1:X}){id_hint}")


def _print_g2_info(db):
    if not db.strtab:
        print("  globals[2] not loaded")
        return
    st = db.strtab
    print("  String descriptor table:")
    print(f"    globals[2]  = 0x{st.g2:08X}")
    print(f"    raw base    = 0x{st.raw:08X}")
    print(f"    count       = {st.count}")
    print(f"    languages   = {db.num_languages} ({', '.join(db.lang_labels)})")
    print("  Use 'strid <id> [lang]' to look up strings.")


def _print_g5(db):
    if db.g5_ptr is None:
        print("  globals[5] not loaded")
        return
    print("  globals[5] alternate-label table:")
    print(f"  addr=0x{db.g5_ptr:08X}  entries={db.g5_count} "
          f"(idx 0x{db.g5_base_idx:03X}..0x{db.g5_end_idx-1:03X})")
    for idx in range(db.g5_base_idx, db.g5_end_idx):
        rec = db.g5_lookup(idx)
        if rec is None:
            continue
        a, b = rec
        vid = idx + db.id_bases[4]
        sa = db.string(a) if db.strtab and a != 0xDE else None
        sb = db.string(b) if db.strtab and b != 0xDE else None
        la = f'"{sa}"' if sa else ("--" if a == 0xDE else f"0x{a:04X}")
        lb = f'"{sb}"' if sb else ("--" if b == 0xDE else f"0x{b:04X}")
        off = idx - db.g5_base_idx
        shared = ""
        alt_idx = db.g5_end_idx + off
        if off < db.g5_alias_count:
            shared = f"  (shared w/ idx 0x{alt_idx:03X})"
        print(f"  [4] idx=0x{idx:03X} var=0x{vid:04X}  off={off:+3d}  "
              f"a={la:>24s}  b={lb:>24s}{shared}")


def _print_g7(db):
    if db.g7_addr is None or 6 not in db.tables:
        print("  globals[7] not loaded")
        return
    size = f"{db.g7_size} referenced"
    if db.g7_alloc_size:
        size += f", {db.g7_alloc_size} allocated"
    print(f"  globals[7] byte-slice pool @ 0x{db.g7_addr:08X} ({size} bytes):")
    for entry in db.tables[6]:
        values = entry.pool_values(db)
        pool = ", ".join(str(v) for v in values)
        print(f"    {_vid_str(entry.var_id, db):>10}  +0x{entry.pool_offset:04X} "
              f"[{entry.item_count:2d}]  {pool}")


def _print_strinfo(db, sid):
    if not db.strtab:
        print("  string table not loaded")
        return
    st = db.strtab
    print(f"  globals[2] base  = 0x{st.g2:08X}")
    print(f"  raw string base  = 0x{st.raw:08X}")
    print(f"  max string ID    = {st.count - 1}")
    rec_addr = st.g2 + sid * 8
    field0 = db.fl.u32(rec_addr)
    la = db.fl.u32(rec_addr + 4)
    print(f"  record[{sid}] @ 0x{rec_addr:08X}:")
    print(f"    field0 = 0x{field0:08X} ({field0})")
    print(f"    locale_arr_ptr = 0x{la:08X}")
    if la and db.fl.is_flash_ptr(la):
        for l in range(db.num_languages):
            ri = db.fl.u16(la + l * 2)
            sp = db.fl.u32(st.raw + ri * 4) if ri is not None else None
            if sp and db.fl.is_flash_ptr(sp):
                s = db.fl.cstr(sp).decode('utf-8', errors='replace')
                print(f"    [{db.lang_labels[l]}] raw_idx={ri} "
                      f"str_ptr=0x{sp:08X} -> \"{s}\"")
            else:
                print(f"    [{db.lang_labels[l]}] raw_idx={ri} -> ?")


def _search_strings(db, query):
    needle = query.lower()
    hits = []
    if 8 in db.tables:
        for e in db.tables[8]:
            if e.name_str_id and e.name_str_id not in (0xFFFF, 0xDE):
                s = db.string(e.name_str_id)
                if s and needle in s.lower():
                    hits.append((e, s))
                    continue
            if e.has_strings():
                for i in range(max(1, e.num_options)):
                    s = db.string(e.base_str_id + i)
                    if s and needle in s.lower():
                        hits.append((e, s))
                        break
    for tnum in (4, 9, 10):
        if tnum not in db.tables:
            continue
        for e in db.tables[tnum]:
            bad_ids = (0xFFFF, 0xDE, 0) if tnum == 10 else (0xFFFF, 0xDE)
            if getattr(e, "name_str_id", 0) not in bad_ids:
                s = db.string(e.name_str_id)
                if s and needle in s.lower():
                    hits.append((e, s))
                    continue
            if isinstance(e, (Entry4, Entry10)) and getattr(e, "units_str_id", 0) not in bad_ids:
                s = db.string(e.units_str_id)
                if s and needle in s.lower():
                    hits.append((e, s))
    for entry, s in hits:
        print(f"  [{entry.TABLE}] var=0x{entry.var_id:04X} "
              f'idx=0x{entry.idx:03X}: "{s}"')
    if not hits:
        print(f'  no matches for "{query}"')


def _print_chain(db, ident):
    vid = resolve_var_arg(db, ident)
    e = db.get(vid)
    if not e or not isinstance(e, Entry8):
        print("  not a [8] entry")
        return
    ch = db.chain(e)
    print(f"  Chain from 0x{vid:04X} ({len(ch)} nodes):")
    for i, ce in enumerate(ch):
        pipe = "+--" if i == len(ch) - 1 else "|--"
        if isinstance(ce, Entry8):
            st = ""
            if ce.has_strings():
                s = db.string(ce.base_str_id)
                if s:
                    st = f'  "{s}"'
            print(f"  {pipe} [8] 0x{ce.var_id:04X} "
                  f"dep={_g4_idx_ref(ce.linked_var_idx, db, none='none')}{st}")
        elif isinstance(ce, Entry4):
            u = ""
            if ce.units_str_id and ce.units_str_id != 0xFFFF:
                s = db.string(ce.units_str_id)
                if s:
                    u = f" [{s}]"
            print(f"  {pipe} [4] 0x{ce.var_id:04X} "
                  f"next={_g4_idx_ref(ce.next_var_idx, db, none='end')} "
                  f"{ce.range_str()}{u}")
        else:
            print(f"  {pipe} {ce}")


def _print_info(db):
    print("  Air10 CCX block navigator")
    print(f"  image       {len(db.fl.data)} bytes  "
          f"0x{db.fl.base:08X}..0x{db.fl.end:08X}")
    print(f"  languages   {db.num_languages} ({', '.join(db.lang_labels)})")
    if db.strtab:
        print(f"  strings     g2=0x{db.strtab.g2:08X} raw=0x{db.strtab.raw:08X}")
    for tnum in sorted(db.tables):
        base = db.table_bases.get(tnum)
        print(f"  globals[{tnum:<2}] {len(db.tables[tnum]):>4} entries @ 0x{base:08X}")
    extras = []
    for name, value in (
        ("g0 device", db.device),
        ("g1 timers", db.timers),
        ("g14 NPD", db.npd),
        ("g15 signal groups", db.g15_groups),
        ("g16 groups", db.vargroups),
        ("g19 streams", db.streams),
        ("g20 PDL", db.pdl),
        ("g22 metadata/name pool", db.nametab),
        ("g23 UART names", db.names),
        ("g24 modes", db.modes),
    ):
        if value:
            extras.append(name)
    if db.channels:
        extras.append(f"{len(db.channels)} signal channels")
    if extras:
        print("  loaded      " + ", ".join(extras))
    print(f"  variables   {len(db.by_varid)}")


def _print_globals(db):
    if db.globals_addr:
        print(f"  globals[] @ 0x{db.globals_addr:08X}")
    else:
        print("  globals[] values inferred from loaded globals entries")
    print("  idx  value       kind   description")
    for idx in sorted(db.globals_values):
        value = db.globals_values[idx]
        if value == 0:
            continue
        label = GLOBAL_LABELS.get(idx, "")
        if value == 0xFFFFFFFF:
            kind = "sentinel"
            shown = f"0x{value:08X}"
        elif idx == 25:
            kind = "count"
            shown = f"0x{value:08X} ({value})"
        elif db.fl.is_flash_ptr(value):
            kind = "ptr"
            shown = f"0x{value:08X}"
        else:
            kind = "value"
            shown = f"0x{value:08X} ({value})"
        print(f"  [{idx:2d}] {shown:<15} {kind:<5} {label}")
    if db.raw_strings:
        print(f"       raw strings 0x{db.raw_strings:08X}")


def add_command_parsers(subparsers):
    subparsers.add_parser("info", help="show firmware summary and loaded tables")
    p = subparsers.add_parser("globals", help="show globals[] map or decoded entries")
    p.add_argument("items", nargs="*", help="globals[] indices")

    p = subparsers.add_parser("var", help="show one variable descriptor")
    p.add_argument("ident", help="var_id or UART tag")

    p = subparsers.add_parser("channels", help="show signal channels")
    p.add_argument("name", nargs="?")

    p = subparsers.add_parser("mode", help="list vars mapped to one therapy mode")
    p.add_argument("mode", nargs="*", help="mode index or name")

    p = subparsers.add_parser("strid", help="lookup raw string id")
    p.add_argument("id")
    p.add_argument("lang", nargs="?")

    p = subparsers.add_parser("strinfo", help="show string table record internals")
    p.add_argument("id", nargs="?", default="0")

    p = subparsers.add_parser("search", help="search descriptor strings")
    p.add_argument("query", nargs="+")

    p = subparsers.add_parser("chain", help="walk a descriptor's g[4] dependency chain")
    p.add_argument("ident")

    p = subparsers.add_parser("dump-tsv", help="dump descriptor tables as TSV")
    p.add_argument("outfile", help="output path, or - for stdout")
    p.add_argument("--tables", default="3,4,6,8,9,10",
                   help="tables to dump (default: 3,4,6,8,9,10)")


def build_command_parser(prog="as10"):
    parser = argparse.ArgumentParser(prog=prog)
    subparsers = parser.add_subparsers(dest="command")
    add_command_parsers(subparsers)
    return parser


def build_main_parser():
    parser = argparse.ArgumentParser(
        description="ResMed Air10 - Descriptor Navigator")
    parser.add_argument("firmware", help="raw flash binary")
    parser.add_argument("-i", "--interactive", action="store_true",
                        help="start interactive descriptor shell")
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="show multiline variable details")
    parser.add_argument("--globals", type=lambda x: int(x, 0), default=None,
                        help="globals[] pointer array address in flash")
    subparsers = parser.add_subparsers(dest="command")
    add_command_parsers(subparsers)
    return parser


def _run_global(db, item):
    parts = item.split(":", 1)
    gidx = parse_numeric_arg(parts[0], "globals index")
    extra = parts[1].split(",") if len(parts) > 1 and parts[1] else []
    if gidx in (3, 4, 6, 8, 9, 10):
        if len(extra) > 2:
            raise ValueError(f"globals {gidx} takes at most: :idx[,to]")
        idx = extra[0] if extra else None
        to = extra[1] if len(extra) > 1 else None
        _print_table(db, gidx, idx, to)
    elif gidx == 0:
        print(db.device.dump() if db.device else "  globals[0] not loaded")
    elif gidx == 1:
        print(db.timers.dump() if db.timers else "  globals[1] not loaded")
    elif gidx == 2:
        _print_g2_info(db)
    elif gidx == 5:
        _print_g5(db)
    elif gidx == 7:
        _print_g7(db)
    elif gidx == 14:
        print(db.npd.dump() if db.npd else "  globals[14] not loaded")
    elif gidx == 15:
        print(db.g15_groups.dump() if db.g15_groups else "  globals[15] not loaded")
    elif gidx == 16:
        if len(extra) > 1:
            raise ValueError("globals 16 takes at most: :group")
        name = extra[0] if extra else None
        print(db.vargroups.dump(name) if db.vargroups else "  globals[16] not loaded")
    elif gidx == 17:
        print(db.desc17.dump() if db.desc17 else "  globals[17] not loaded")
    elif gidx == 18:
        print(db.desc18.dump() if db.desc18 else "  globals[18] not loaded")
    elif gidx == 19:
        print(db.streams.dump() if db.streams else "  globals[19] not loaded")
    elif gidx == 20:
        print(db.pdl.dump() if db.pdl else "  globals[20] not loaded")
    elif gidx == 21:
        print(db.pdl.dump_rules() if db.pdl else "  globals[21] not loaded (shares data with g[20])")
    elif gidx == 22:
        if len(extra) > 1:
            raise ValueError("globals 22 takes at most: :query")
        _run_g22(db, extra[0] if extra else None)
    elif gidx == 23:
        if len(extra) > 1:
            raise ValueError("globals 23 takes at most: :query")
        _run_g23(db, extra[0] if extra else None)
    elif gidx == 24:
        print(db.modes.dump() if db.modes else "  globals[24] not loaded")
    elif gidx in (11, 12, 13, 26, 27, 28):
        if extra:
            raise ValueError(f"globals {gidx} takes no extra args")
        _run_channels(db, gidx, None)
    else:
        raise ValueError(f"globals[{gidx}] is not decoded")


def run_command(db, args):
    command = args.command or "info"
    if command == "info":
        _print_info(db)
    elif command == "globals":
        if args.items:
            for i, item in enumerate(args.items):
                if i:
                    print()
                _run_global(db, item)
        else:
            _print_globals(db)
    elif command == "var":
        verbose = getattr(args, "verbose", getattr(db, "verbose", False))
        _print_var_detail(db, args.ident, verbose)
    elif command == "channels":
        _run_channels(db, None, args.name)
    elif command == "mode":
        _run_mode(db, " ".join(args.mode) if args.mode else None)
    elif command == "strid":
        sid = parse_numeric_arg(args.id, "string id")
        lang = parse_numeric_arg(args.lang, "language") if args.lang is not None else None
        if not db.strtab:
            print("  string table not loaded")
        elif lang is not None:
            print(f"  {db.string(sid, lang)}")
        else:
            for lb, s in zip(db.lang_labels, db.strings_all(sid)):
                print(f"  {lb}: {s}")
    elif command == "strinfo":
        _print_strinfo(db, parse_numeric_arg(args.id, "string id"))
    elif command == "search":
        _search_strings(db, " ".join(args.query))
    elif command == "chain":
        _print_chain(db, args.ident)
    elif command == "dump-tsv":
        tables = [int(t.strip()) for t in args.tables.split(",")]
        outfile = None if args.outfile == "-" else args.outfile
        dump_tsv(db, tables, outfile)
    else:
        raise ValueError(f"unknown command: {command}")


def _run_g22(db, query):
    if not db.nametab:
        print("  globals[22] not loaded")
        return
    if query is None:
        print(db.nametab.dump_header(db.names))
    elif query.lower() == 'header':
        print(db.nametab.dump_header(db.names))
    else:
        try:
            results = db.nametab.lookup(int(query, 0))
        except ValueError:
            results = db.nametab.lookup(query)
        if results:
            for label, vid, uart in results:
                u = f":{uart}" if uart else ""
                print(f"  '{label}' -> 0x{vid:04X}{u}")
        else:
            print(f"  '{query}' not found")


def _run_g23(db, query):
    if not db.names:
        print("  globals[23] not loaded")
        return
    if query is None:
        print(f"  {len(db.names.by_name)} UART names loaded")
        print("  usage: g23 <var_id> or g23 <ABC>")
        return
    try:
        vid = int(query, 0)
        name = db.uart_name(vid)
        print(f"  0x{vid:04X} = {name}" if name else f"  0x{vid:04X}: no UART name")
    except ValueError:
        vid = db.names.var_id(query)
        print(f"  {query.upper()} = 0x{vid:04X}" if vid is not None else f"  {query.upper()}: not found")


def _mode_labels(db):
    count = db.modes.num_flags if db.modes else ModeTable.FALLBACK_NUM_FLAGS
    labels = [str(i) for i in range(count)]
    mop_vid = db.names.var_id("MOP") if db.names else None
    mop = db.get(mop_vid) if mop_vid is not None else None
    if isinstance(mop, Entry8):
        for i, label in enumerate(mop.option_strings(db)[:count]):
            if label:
                labels[i] = label
    return labels


def _mode_key(value):
    return "".join(c.lower() for c in value if c.isalnum())


def _resolve_mode_index(db, mode):
    labels = _mode_labels(db)
    try:
        idx = int(mode, 0)
        if 0 <= idx < len(labels):
            return idx, labels
    except ValueError:
        pass

    wanted = _mode_key(mode)
    for i, label in enumerate(labels):
        if wanted == _mode_key(label):
            return i, labels
    raise ValueError(f"unknown mode {mode!r}; use 'mode' to list known modes")


def _run_mode(db, mode):
    if not db.modes:
        print("  globals[24] not loaded")
        return
    labels = _mode_labels(db)
    if not mode:
        for i, label in enumerate(labels):
            count = sum(1 for e in db.modes.entries if e['flags'][i])
            print(f"  {i:2d}  {label}  ({count} vars)")
        return

    idx, labels = _resolve_mode_index(db, mode)
    hits = [e for e in db.modes.entries if e['flags'][idx]]
    print(f"  {idx} {labels[idx]} ({len(hits)} vars):")
    for item in hits:
        entry = db.get(item['var_id'])
        if entry:
            print(f"  {entry.oneline(db)}")
        else:
            name = f":{item['uart']}" if item['uart'] else ""
            print(f"  0x{item['var_id']:04X}{name}")


def _run_channels(db, gidx, name):
    def dump_for(ch):
        return ch.dump(db if ch.gidx in (11, 13) else None)

    if not db.channels:
        print("  no signal channels loaded")
        return
    if gidx is not None:
        hits = [ch for ch in db.channels.values() if ch.gidx == gidx]
        if hits:
            for ch in hits:
                print(dump_for(ch))
        else:
            print(f"  no channels from globals[{gidx}]")
    elif name:
        ch = db.channels.get(name.upper())
        if ch:
            print(dump_for(ch))
        else:
            print(f"  channel '{name}' not found")
            print(f"  available: {', '.join(sorted(db.channels.keys()))}")
    else:
        for ch_name in sorted(db.channels):
            print(dump_for(db.channels[ch_name]))


def run_repl(db):
    parser = build_command_parser()
    print()
    print("  AS10 Descriptor Navigator")
    print("  " + "-" * 40)
    _print_info(db)
    print()
    print('  Type "help" for commands, "quit" to exit.')
    print()

    while True:
        try:
            line = input("as10> ").strip()
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
            args = parser.parse_args(shlex.split(line))
            run_command(db, args)
        except SystemExit:
            pass
        except Exception as exc:
            print(f"  Error: {exc}")
        print()


def dump_tsv(db, tables_to_dump, outfile=None):
    """Dump all entries as TSV for import into spreadsheets."""
    import io
    out = open(outfile, 'w', encoding='utf-8') if outfile else sys.stdout

    def s(str_id):
        """Resolve string or return empty."""
        if not db.strtab or not str_id or str_id in (0xFFFF, 0xDE):
            return ""
        r = db.string(str_id)
        return r if r else ""

    def g4_target_fields(idx):
        entry = db.g4_by_idx(idx)
        if not entry:
            return "", ""
        return f"0x{entry.var_id:04X}", db.uart_name(entry.var_id) or ""

    for tnum in tables_to_dump:
        if tnum not in db.tables:
            continue
        base = db.table_bases.get(tnum, 0)

        if tnum == 4:
            out.write(f"# globals[4] -- base=0x{base:08X}  stride=0x1C  count={len(db.tables[4])}\n")
            out.write("idx\tvar_id\taddr\toffset\tflags\tflags_str\t"
                      "callback\tnext_dependent_g4_idx\tnext_dependent_var_id\tnext_dependent_name\t"
                      "name_str_id\tname\t"
                      "default\tmax\tmin\tstep\tscale\tdp\t"
                      "default_fmt\tmax_fmt\tmin_fmt\tstep_fmt\trange\t"
                      "units_str_id\tunits\t"
                      "g5_str_a\tg5_name_a\tg5_str_b\tg5_name_b\n")
            for e in db.tables[4]:
                off = e.addr - base
                g5a = g5b = g5na = g5nb = ""
                rec = db.g5_lookup(e.idx)
                if rec is not None:
                    a, b = rec
                    g5a = f"0x{a:04X}"
                    g5b = f"0x{b:04X}"
                    if a != 0xDE: g5na = s(a)
                    if b != 0xDE: g5nb = s(b)
                next_vid, next_name = g4_target_fields(e.next_var_idx)
                out.write(f"0x{e.idx:03X}\t0x{e.var_id:04X}\t0x{e.addr:08X}\t0x{off:05X}\t"
                          f"0x{e.flags:04X}\t{decode_flags(e.flags, tnum)}\t"
                          f"{e.callback_id}\t0x{e.next_var_idx & 0xFFFF:04X}\t"
                          f"{next_vid}\t{next_name}\t"
                          f"0x{e.name_str_id:04X}\t{s(e.name_str_id)}\t"
                          f"{e.default_value}\t{e.max_value}\t{e.min_value}\t"
                          f"{e.step_size}\t{e.scale_factor}\t{e.decimal_places}\t"
                          f"{e._fmt(e.default_value)}\t{e._fmt(e.max_value)}\t"
                          f"{e._fmt(e.min_value)}\t{e._fmt(e.step_size)}\t"
                          f"{e.range_str()}\t"
                          f"0x{e.units_str_id:04X}\t{s(e.units_str_id)}\t"
                          f"{g5a}\t{g5na}\t{g5b}\t{g5nb}\n")

        elif tnum == 8:
            out.write(f"# globals[8] -- base=0x{base:08X}  stride=0x14  count={len(db.tables[8])}\n")
            out.write("idx\tvar_id\taddr\toffset\tflags\tflags_str\t"
                      "callback\tdependency_head_g4_idx\tdependency_head_var_id\tdependency_head_name\t"
                      "name_str_id\tname\t"
                      "default\tnum_options\t"
                      "perm_mask\tbase_str_id\toption_names\t"
                      "param_0a\tparam_12\n")
            for e in db.tables[8]:
                off = e.addr - base
                nstr = s(e.name_str_id) if e.name_str_id not in (0xFFFF, 0xDE) else ""
                opts_str = ""
                if e.has_strings():
                    labels = e.option_strings(db)
                    # mark permitted with Y, denied with N
                    parts_o = []
                    for i, lbl in enumerate(labels):
                        mark = "Y" if e.perm_mask & (1 << i) else "N"
                        parts_o.append(f"{mark}{lbl}")
                    opts_str = " | ".join(parts_o)
                linked_vid, linked_name = g4_target_fields(e.linked_var_idx)
                out.write(f"0x{e.idx:03X}\t0x{e.var_id:04X}\t0x{e.addr:08X}\t0x{off:04X}\t"
                          f"0x{e.flags:04X}\t{decode_flags(e.flags, tnum)}\t"
                          f"{e.callback_id}\t0x{e.linked_var_idx & 0xFFFF:04X}\t"
                          f"{linked_vid}\t{linked_name}\t"
                          f"0x{e.name_str_id:04X}\t{nstr}\t"
                          f"{e.default_value}\t{e.num_options}\t"
                          f"0x{e.perm_mask:08X}\t"
                          f"0x{e.base_str_id & 0xFFFF:04X}\t{opts_str}\t"
                          f"{e.param_0a}\t{e.param_12}\n")

        elif tnum == 6:
            out.write(f"# globals[6] -- base=0x{base:08X}  stride=0x18  count={len(db.tables[6])}\n")
            out.write("idx\tvar_id\taddr\toffset\tflags\tflags_str\t"
                      "callback\tdependency_g4_idx\tname_str_id\t"
                      "default\tallowed_bits\titem_count\tdisplay_param\t"
                      "pool_offset\tbase_str_id\tpool_values\n")
            for e in db.tables[6]:
                off = e.addr - base
                pool = ",".join(str(v) for v in e.pool_values(db))
                out.write(f"0x{e.idx:03X}\t0x{e.var_id:04X}\t0x{e.addr:08X}\t0x{off:04X}\t"
                          f"0x{e.flags:04X}\t{decode_flags(e.flags, tnum)}\t"
                          f"{e.callback_id}\t0x{e.dependency_idx & 0xFFFF:04X}\t"
                          f"0x{e.name_str_id:04X}\t0x{e.default:08X}\t"
                          f"0x{e.allowed_bits:08X}\t{e.item_count}\t{e.display_param}\t"
                          f"0x{e.pool_offset:04X}\t0x{e.base_str_id:04X}\t{pool}\n")

        elif tnum == 3:
            out.write(f"# globals[3] -- base=0x{base:08X}  stride=10  count={len(db.tables[3])}\n")
            out.write("idx\tvar_id\taddr\toffset\tflags\tflags_str\t"
                      "notify_handler\tdependency_g4_idx\tformat_str_id\tmax_length\n")
            for e in db.tables[3]:
                off = e.addr - base
                out.write(f"0x{e.idx:03X}\t0x{e.var_id:04X}\t0x{e.addr:08X}\t0x{off:04X}\t"
                          f"0x{e.flags:04X}\t{decode_flags(e.flags, tnum)}\t"
                          f"{e.notify_handler}\t0x{e.dependency_idx & 0xFFFF:04X}\t"
                          f"0x{e.format_str_id & 0xFFFF:04X}\t{e.max_length}\n")

        elif tnum == 9:
            out.write(f"# globals[9] -- base=0x{base:08X}  stride=0x18  count={len(db.tables[9])}\n")
            out.write("idx\tvar_id\taddr\toffset\tflags\tflags_str\t"
                      "dependency_g4_idx\tname_str_id\tname\t"
                      "default_event_type\tevent_type_count\tevent_type_mask\t"
                      "event_type_base_str_id\tduration_min_ds\tduration_max_ds\t"
                      "duration_units_per_second\n")
            for e in db.tables[9]:
                off = e.addr - base
                nstr = s(e.name_str_id) if e.name_str_id not in (0xFFFF, 0xDE) else ""
                out.write(f"0x{e.idx:03X}\t0x{e.var_id:04X}\t0x{e.addr:08X}\t0x{off:04X}\t"
                          f"0x{e.flags:04X}\t{decode_flags(e.flags, tnum)}\t"
                          f"0x{e.dependency_idx:04X}\t"
                          f"0x{e.name_str_id:04X}\t{nstr}\t"
                          f"{e.default_byte}\t{e.num_options}\t"
                          f"0x{e.perm_bitmask:08X}\t"
                          f"0x{e.base_str_id:04X}\t"
                          f"{e.min_value}\t{e.max_value}\t{e.step_size}\n")

        elif tnum == 10:
            out.write(f"# globals[10] -- base=0x{base:08X}  stride=0x24  count={len(db.tables[10])}\n")
            out.write("idx\tvar_id\taddr\toffset\tflags\tflags_str\t"
                      "callback\tname_str_id\tname\t"
                      "default\tmax\tmin\tstep\tscale\tdp\t"
                      "default_fmt\tmax_fmt\tmin_fmt\tstep_fmt\trange\t"
                      "units_str_id\tunits\t"
                      "ram_base\tram_count\tpurpose\n")
            for e in db.tables[10]:
                off = e.addr - base
                out.write(f"0x{e.idx:03X}\t0x{e.var_id:04X}\t0x{e.addr:08X}\t0x{off:04X}\t"
                          f"0x{e.flags:04X}\t{decode_flags(e.flags, tnum)}\t"
                          f"{e.callback_id}\t"
                          f"0x{e.name_str_id:04X}\t{s(e.name_str_id)}\t"
                          f"{e.default_value}\t{e.max_value}\t{e.min_value}\t"
                          f"{e.step_size}\t{e.scale_factor}\t{e.decimal_places}\t"
                          f"{e._fmt(e.default_value)}\t{e._fmt(e.max_value)}\t"
                          f"{e._fmt(e.min_value)}\t{e._fmt(e.step_size)}\t"
                          f"{e.range_str()}\t"
                          f"0x{e.units_str_id:04X}\t{s(e.units_str_id)}\t"
                          f"{e.ram_base_index}\t{e.ram_count}\t{e.role(db)}\n")

        out.write("\n")

    # New tables (not keyed by tnum)
    if db.streams:
        out.write("# globals[19] -- stream table\n")
        out.write("name\tcapacity\ttimer_index\ttrigger_var_id\ttrigger_name\t"
                  "idle_value\tstate_g4_idx\tstate_var_id\tstate_name\t"
                  "field_var_ids\tfield_names\tflags\tsecondary_var_id\t"
                  "secondary_name\tsecondary_param\tmetadata_name\tpurpose\n")
        for e in db.streams.entries:
            field_ids = ",".join(f"0x{vid:04X}" for vid, _ in e['fields'])
            field_names = ",".join(name or "" for _, name in e['fields'])
            state_vid = f"0x{e['tracker_vid']:04X}" if e['tracker_vid'] is not None else ""
            out.write(f"{e['name']}\t{e['capacity']}\t{e['timer_index']}\t"
                      f"0x{e['trigger_vid']:04X}\t{e['trigger_name'] or ''}\t"
                      f"0x{e['idle_value']:08X}\t0x{e['tracker_idx']:04X}\t"
                      f"{state_vid}\t{e['tracker_name'] or ''}\t{field_ids}\t"
                      f"{field_names}\t0x{e['flags']:02X}\t"
                      f"0x{e['secondary_vid']:04X}\t{e['secondary_name'] or ''}\t"
                      f"0x{e['secondary_param']:04X}\t"
                      f"{StreamTable.METADATA_NAMES.get(e['name'], '')}\t"
                      f"{StreamTable.PURPOSES.get(e['name'], '')}\n")
        out.write("\n")

    if db.timers and db.timers.entries:
        out.write(f"# globals[1] -- timer scale table ({len(db.timers.entries)} entries)\n")
        out.write("idx\tscheduler_level\tbase_ticks_10ms\tnominal_multiplier\tperiod_s\n")
        for e in db.timers.entries:
            out.write(f"{e['idx']}\t{e['level']}\t{e['ticks']}\t{e['multiplier']}\t{e['period']}\n")
        out.write("\n")

    if db.pdl and db.pdl.var_ids:
        out.write(f"# globals[20] -- {db.pdl.name} ({len(db.pdl.var_ids)} vars)\n")
        out.write("idx\tvar_id\tuart_name\n")
        for i, (vid, uart) in enumerate(db.pdl.var_ids):
            out.write(f"{i}\t0x{vid:04X}\t{uart or ''}\n")
        out.write("\n")

        out.write(f"# globals[20/21] -- {db.pdl.name} rules ({len(db.pdl.rules)} entries)\n")
        out.write("idx\tvar_id_a\tname_a\tvar_id_b\tname_b\ttype\tparam_a\tparam_b\n")
        for r in db.pdl.rules:
            pa = f"0x{r['param_a']:08X}" if r['param_a'] != 0xFFFFFFFF else ""
            pb = f"0x{r['param_b']:08X}" if r['param_b'] != 0xFFFFFFFF else ""
            out.write(f"{r['idx']}\t0x{r['vid_a']:04X}\t{r['name_a'] or ''}\t"
                      f"0x{r['vid_b']:04X}\t{r['name_b'] or ''}\t"
                      f"{(r['flags'] >> 16) & 0xFF}\t{pa}\t{pb}\n")
        out.write("\n")

    if db.modes and db.modes.entries:
        out.write(f"# globals[24] -- mode table ({len(db.modes.entries)} settings)\n")
        hdr = "idx\tvar_id\tuart_name\t" + "\t".join(str(i) for i in range(db.modes.num_flags))
        out.write(hdr + "\n")
        for e in db.modes.entries:
            fstr = "\t".join(str(f) for f in e['flags'])
            out.write(f"{e['idx']}\t0x{e['var_id']:04X}\t{e['uart'] or ''}\t{fstr}\n")
        out.write("\n")

    if db.names:
        out.write(f"# globals[23] -- UART name lookup ({len(db.names.by_name)} entries)\n")
        out.write("name\tvar_id\n")
        for name in sorted(db.names.by_name):
            out.write(f"{name}\t0x{db.names.by_name[name]:04X}\n")
        out.write("\n")

    if db.npd and db.npd.signals:
        out.write(f"# globals[14] -- NPD signal group ({len(db.npd.signals)} signals)\n")
        out.write("var_id\tuart_name\n")
        for vid, uart in db.npd.signals:
            out.write(f"0x{vid:04X}\t{uart or ''}\n")
        out.write("\n")

    if db.g15_groups and db.g15_groups.groups:
        for group in db.g15_groups.groups:
            out.write(f"# globals[15] -- {group.name} signal group "
                      f"({len(group.signals)} signals)\n")
            out.write("var_id\tuart_name\n")
            for vid, uart in group.signals:
                out.write(f"0x{vid:04X}\t{uart or ''}\n")
            out.write("\n")

    if db.channels:
        out.write(f"# Signal channels ({len(db.channels)} channels)\n")
        out.write("channel\tfield_idx\tvar_id\tuart_name\tfield_name\tsamples_per_rec\n")
        for ch_name in sorted(db.channels):
            ch = db.channels[ch_name]
            for i, (vid, uart) in enumerate(ch.var_ids):
                fn = ch.field_names[i] if i < len(ch.field_names) and ch.field_names[i] else ''
                spr = ch.samples_per_rec[i] if i < len(ch.samples_per_rec) else ''
                out.write(f"{ch_name}\t{i}\t0x{vid:04X}\t{uart or ''}\t{fn}\t{spr}\n")
        out.write("\n")

    if outfile:
        out.close()
        print(f"[+] Wrote {outfile}")


def load_db(args):
    fl = Flash(args.firmware)
    print(f"[+] {len(fl.data)} bytes  0x{fl.base:08X}..0x{fl.end:08X}")

    ta = {}
    g2 = None
    globals_addr = None
    globals_values = None

    if args.globals:
        # User provided a flash address containing the pointer array
        ptrs = {i: fl.u32(args.globals + i * 4) for i in range(30)}
        globals_addr = args.globals
        globals_values = ptrs
        print(f"[+] globals[] @ 0x{args.globals:08X}:")
        for i in range(30):
            tag = f"  <- [{i}]" if i in (2,3,4,5,6,8,9,10) else ""
            if ptrs[i] and fl.is_flash_ptr(ptrs[i]):
                print(f"    [{i:2d}] 0x{ptrs[i]:08X}{tag}")
        for t in (3,4,6,8,9,10):
            if fl.is_flash_ptr(ptrs.get(t,0)): ta[f"table{t}"] = ptrs[t]
        if fl.is_flash_ptr(ptrs.get(1,0)): ta['timers'] = ptrs[1]
        if fl.is_flash_ptr(ptrs.get(5,0)): ta['globals5'] = ptrs[5]
        if fl.is_flash_ptr(ptrs.get(7,0)): ta['globals7'] = ptrs[7]
        if fl.is_flash_ptr(ptrs.get(2,0)): g2 = ptrs[2]
        if fl.is_flash_ptr(ptrs.get(0,0)):  ta['device'] = ptrs[0]
        if fl.is_flash_ptr(ptrs.get(23,0)): ta['names'] = ptrs[23]
        if fl.is_flash_ptr(ptrs.get(16,0)): ta['vargroups'] = ptrs[16]
        if fl.is_flash_ptr(ptrs.get(20,0)): ta['pdl'] = ptrs[20]
        if fl.is_flash_ptr(ptrs.get(21,0)): ta['pdl_rules'] = ptrs[21]
        if fl.is_flash_ptr(ptrs.get(24,0)):
            ta['modes'] = ptrs[24]
            g25 = ptrs.get(25, 0)
            if 0 < g25 < 200:
                ta['modes_count'] = g25
        if fl.is_flash_ptr(ptrs.get(17,0)): ta['desc17'] = ptrs[17]
        if fl.is_flash_ptr(ptrs.get(18,0)): ta['desc18'] = ptrs[18]
        if fl.is_flash_ptr(ptrs.get(19,0)): ta['streams'] = ptrs[19]
        if fl.is_flash_ptr(ptrs.get(14,0)): ta['npd'] = ptrs[14]
        if fl.is_flash_ptr(ptrs.get(15,0)): ta['npa'] = ptrs[15]
        if fl.is_flash_ptr(ptrs.get(22,0)): ta['name_pool'] = ptrs[22]
        if fl.is_flash_ptr(ptrs.get(11,0)): ta['brp'] = ptrs[11]
        if fl.is_flash_ptr(ptrs.get(12,0)): ta['csl'] = ptrs[12]
        if fl.is_flash_ptr(ptrs.get(13,0)): ta['str_ch'] = ptrs[13]
        if fl.is_flash_ptr(ptrs.get(26,0)): ta['tce'] = ptrs[26]
        if fl.is_flash_ptr(ptrs.get(27,0)): ta['apn'] = ptrs[27]
        if fl.is_flash_ptr(ptrs.get(28,0)): ta['oxh'] = ptrs[28]
    else:
        # Auto-detect all tables by content signatures
        found = find_tables_direct(fl)
        globals_addr = found.pop('_globals_addr', None)
        globals_values = found.pop('_globals_values', None)
        for k, v in found.items():
            if k == 'globals2':
                if not g2: g2 = v
            else:
                ta[k] = v

    # globals[2] now found via globals[] array in auto-detect

    if not ta:
        raise ValueError("no descriptor tables found; use --globals 0xADDR if needed")

    return DB(fl, ta, g2, None, globals_addr, globals_values)


def _main():
    ap = build_main_parser()
    args = ap.parse_args()

    if args.interactive and args.command is not None:
        raise ValueError("--interactive cannot be combined with a command")

    if not os.path.isfile(args.firmware):
        raise FileNotFoundError(args.firmware)

    with contextlib.redirect_stdout(io.StringIO()):
        db = load_db(args)
    db.verbose = args.verbose

    if args.interactive:
        run_repl(db)
    else:
        run_command(db, args)
    return 0


def main():
    try:
        return _main()
    except BrokenPipeError:
        return 0
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

"""Shared Air10 firmware regions, descriptors, strings and patching primitives."""

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

import binascii
import hashlib
import os
import re
import struct


class ASFirmware(object):
    """Patch firmware from device with various changes"""

    reserve_marker = 0xBA
    FLASH_BASE = 0x08000000
    BID_OFFSET = 0x3F80
    GLOBALS_REL = 0x108  # relative to CCX start

    PLATFORMS = {
        'SX577-0200': {
            'blx_off': 0x00000, 'blx_size': 0x04000,
            'ccx_off': 0x04000, 'ccx_size': 0x3C000,
            'cdx_off': 0x40000, 'cdx_size': 0xC0000,
        },
        'SX585-0200': {
            'blx_off': 0x00000, 'blx_size': 0x04000,
            'ccx_off': 0x04000, 'ccx_size': 0x1C000,
            'cdx_off': 0x20000, 'cdx_size': 0xE0000,
        },
    }

    # Descriptor tables in var_id order.
    TABLES = {
        3:  dict(stride=10),
        4:  dict(stride=0x1C),
        6:  dict(stride=0x18),
        8:  dict(stride=0x14),
        9:  dict(stride=0x18),
        10: dict(stride=0x24),
        17: dict(stride=8, count=1),
        18: dict(stride=8, count=1),
    }

    # Descriptor field offsets. Keep these in one place so patch code does not
    # grow parallel local definitions for the same firmware structures.
    G4_FLAGS = 0x00
    G4_CALLBACK = 0x02
    G4_NEXT_DEP = 0x04
    G4_NAME_STR = 0x06
    G4_DEFAULT = 0x08
    G4_MAX = 0x0C
    G4_MIN = 0x10
    G4_DECIMALS = 0x14
    G4_SCALE = 0x16
    G4_STEP = 0x18
    G4_UNITS_STR = 0x1A

    G6_FLAGS = 0x00
    G6_CONFIG_GROUP = 0x02
    G6_LINKED_VAR = 0x04
    G6_PARENT_VAR = 0x06
    G6_DEFAULT = 0x08
    G6_PERM_MASK = 0x0C
    G6_ITEM_COUNT = 0x10
    G6_STEP_DIV = 0x11
    G6_CHILD_INDEX = 0x12
    G6_LABEL_STR = 0x14
    G6_PAD_16 = 0x16

    G8_FLAGS = 0x00
    G8_CALLBACK = 0x02
    G8_DEP_HEAD = 0x04
    G8_NAME_STR = 0x06
    G8_DEFAULT = 0x08
    G8_NUM_OPTIONS = 0x09
    G8_PARAM_0A = 0x0A
    G8_BITMASK = 0x0C
    G8_BASE_STR = 0x10
    G8_PARAM_12 = 0x12

    G9_EVENT_TYPES = 0x09
    G9_ALLOWED_TYPES = 0x0C

    def __init__(self, file, validate_crc=True):
        self.fw = file.read()
        self.fw = list(self.fw)
        self.crcfunc = lambda data: binascii.crc_hqx(data, 0xFFFF)
        self.var_by_name = None
        self.var_tables = None
        self.fw_lang_count = None
        self.fw_lang_ids = None
        self.str_id_empty = None
        self.str_id_off_on_base = None
        # Queued g[2] changes; finalize_fw_strings() writes them.
        self._fw_string_edits = {}
        self._fw_string_base = None
        self._fw_string_added = 0

        self.validate(validate_crc=validate_crc)

    def read_u8(self, off):
        return self.fw[off]

    def read_u16(self, off):
        return struct.unpack_from('<H', bytes(self.fw[off:off+2]))[0]

    def read_u32(self, off):
        return struct.unpack_from('<I', bytes(self.fw[off:off+4]))[0]

    def read_bytes(self, off, size):
        return bytes(self.fw[off:off+size])

    def write_u8(self, off, val):
        self.fw[off] = val & 0xFF

    def write_u16(self, off, val):
        self.fw[off:off+2] = list(struct.pack('<H', val))

    def write_u32(self, off, val):
        self.fw[off:off+4] = list(struct.pack('<I', val))

    def fill_range(self, off, size, byte):
        self.fw[off:off+size] = [byte & 0xFF] * size

    def c_string_len(self, off):
        if off < 0 or off >= len(self.fw):
            return None
        try:
            end = self.fw.index(0, off)
        except ValueError:
            return None
        return end - off + 1

    def find_ccx_ff_range_backwards(self, size, alignment=1):
        """Find an erased CCX range, excluding the region CRC."""
        if size <= 0 or alignment <= 0:
            raise ValueError("CCX allocation size and alignment must be positive")
        limit = self.ccx_off + self.ccx_size - 2
        data = bytes(self.fw)
        erased = b'\xFF' * size
        while limit >= self.ccx_off + size:
            start = data.rfind(erased, self.ccx_off, limit)
            if start < 0:
                break
            if start % alignment == 0:
                return start
            limit = start - start % alignment + size
        raise ValueError("no CCX space for %d bytes (alignment %d)" % (size, alignment))

    def globals_offset(self, idx):
        """Return file offset for data that globals[idx] points to"""
        off = self.globals_addr + idx * 4
        ptr = self.read_u32(off)
        return ptr - self.FLASH_BASE

    def find_var_group(self, name):
        """Return globals[16] variable-group record offset, or None."""
        name = name.upper()
        if not re.match(r'^[A-Z0-9]{3}$', name):
            raise ValueError("find_var_group: invalid group name '%s'" % name)

        base = self.globals_offset(16)
        end = self._next_global_offset_after(base)
        if end is None:
            raise ValueError("cannot infer globals[16] end")

        target = name.encode('ascii') + b'\x00'
        for off in range(base, end - 0x0f, 0x10):
            raw_name = self.read_bytes(off, 4)
            if not re.match(br'^[A-Z0-9]{3}\x00$', raw_name):
                break
            if raw_name == target:
                return off
        return None

    def find_var_id(self, var_id):
        """Return descriptor file offset for numeric var_id."""
        _, tbl = self._var_table_for_id(var_id)
        return tbl['base'] + (var_id - tbl['id_base']) * tbl['stride']

    def _var_table_for_id(self, var_id):
        """Return the globals[] table number and metadata containing var_id."""
        self._load_var_tables()
        for table_num, tbl in self.var_tables.items():
            if tbl['id_base'] <= var_id < tbl['id_base'] + tbl['count']:
                return table_num, tbl
        raise ValueError("var_id 0x%04X not in derived descriptor tables" % var_id)

    def _flash_ptr_offset(self, ptr):
        off = ptr - self.FLASH_BASE
        if off < 0 or off >= len(self.fw):
            return None
        return off

    def _next_global_offset_after(self, base):
        """Return the next higher globals[] target used as a table boundary."""
        candidates = []
        for idx in range(30):
            ptr = self.read_u32(self.globals_addr + idx * 4)
            off = self._flash_ptr_offset(ptr)
            if off is not None and off > base:
                candidates.append(off)
        return min(candidates) if candidates else None

    def _table_count(self, table_num, base, stride):
        """Return descriptor count from the table layout or globals[] boundary."""
        # Signal arrays follow g[10] before the next globals[] target. Its ID
        # range starts at PCC and ends immediately before the DAC descriptor.
        if table_num == 10:
            return self.find_var_id_by_name('DAC') - self.find_var_id_by_name('PCC')
        # Date/time roots each contain one descriptor; following arrays belong
        # to other structures, not to additional date/time variables.
        if 'count' in self.TABLES[table_num]:
            return self.TABLES[table_num]['count']
        end = self._next_global_offset_after(base)
        if end is None:
            raise ValueError("cannot infer globals[%d] count" % table_num)
        size = end - base
        if size <= 0:
            raise ValueError("globals[%d] size 0x%X is invalid" % (table_num, size))
        rem = size % stride
        if rem:
            count = size // stride
            pad = self.fw[base + count * stride:base + count * stride + rem]
            # Older SX584 aligns the following table after g[3] with a short zero pad.
            if table_num == 3 and 0 < rem < 4 and count > 0 and all(b == 0 for b in pad):
                return count
            raise ValueError(
                "globals[%d] size 0x%X is not aligned to stride 0x%X" %
                (table_num, size, stride))
        return size // stride

    @staticmethod
    def _has_id_range(ids, start, count):
        return all(start + i in ids for i in range(count))

    def _infer_id_base(self, table_num, count, expected_base):
        """Match one descriptor table to its var_id range in globals[23]."""
        ids = set(self.var_ids_by_name().values())
        if expected_base is not None:
            if self._has_id_range(ids, expected_base, count):
                return expected_base
            raise ValueError(
                "globals[%d] var_id range 0x%04X..0x%04X missing from globals[23]" %
                (table_num, expected_base, expected_base + count - 1))

        for candidate in sorted(ids):
            if candidate - 1 in ids:
                continue
            if self._has_id_range(ids, candidate, count):
                return candidate
        raise ValueError("cannot infer globals[%d] var_id base from globals[23]" % table_num)

    def _load_var_tables(self):
        """Load descriptor addresses, counts, strides, and derived var_id bases."""
        if self.var_tables is not None:
            return

        self.var_tables = {}
        expected_base = None
        for table_num in self.TABLES:
            ptr = self.read_u32(self.globals_addr + table_num * 4)
            base = self._flash_ptr_offset(ptr)
            if base is None:
                continue

            stride = self.TABLES[table_num]['stride']
            count = self._table_count(table_num, base, stride)
            id_base = self._infer_id_base(table_num, count, expected_base)
            self.var_tables[table_num] = {
                'base': base,
                'count': count,
                'stride': stride,
                'id_base': id_base,
            }
            expected_base = id_base + count

    def _load_uart_names(self):
        """Build the UART name to var_id map from globals[23]."""
        if self.var_by_name is not None:
            return

        fw = bytes(self.fw)
        self.var_by_name = {}
        g23 = self.globals_offset(23)

        # globals[23] is a 26-bucket UART-name lookup table:
        # each bucket points to {char2, char3, var_id} entries for one first letter.
        for letter_idx in range(26):
            off = g23 + letter_idx * 8
            if off < 0 or off + 8 > len(fw):
                continue
            sub_ptr, count = self.read_u32(off), self.read_u32(off + 4)
            sub_off = self._flash_ptr_offset(sub_ptr)
            if sub_off is None or count > 200 or sub_off + count * 4 > len(fw):
                continue
            for j in range(count):
                rec_off = sub_off + j * 4
                c2 = self.read_u8(rec_off)
                c3 = self.read_u8(rec_off + 1)
                var_id = self.read_u16(rec_off + 2)
                name = chr(ord('A') + letter_idx) + chr(c2) + chr(c3)
                self.var_by_name[name] = var_id

    def find_var_id_by_name(self, name):
        """Return numeric var_id for a UART variable name."""
        var_id = self.var_ids_by_name().get(name.upper())
        if var_id is None:
            raise ValueError("unknown UART variable name: %s" % name)
        return var_id

    def resolve_var_id(self, var):
        """Return numeric var_id from a UART name or numeric id."""
        if isinstance(var, str):
            var = var.strip()
            lower = var.lower()
            if lower.startswith('0x'):
                return int(var, 16)
            if var.isdigit():
                return int(var, 10)
            return self.find_var_id_by_name(var)
        return int(var)

    def var_ids_by_name(self):
        """Return UART variable name -> numeric var_id mapping."""
        self._load_uart_names()
        return self.var_by_name

    def find_var_name(self, name):
        """Return file offset of descriptor record for a UART variable name."""
        return self.find_var_id(self.find_var_id_by_name(name))

    def find_var(self, var):
        """Return descriptor file offset for a UART name or numeric id."""
        return self.find_var_id(self.resolve_var_id(var))

    def find_var_table_index(self, table_num, var):
        """Return descriptor index for var within one globals[] table."""
        vid = self.resolve_var_id(var)
        actual_table, tbl = self._var_table_for_id(vid)
        if actual_table != table_num:
            raise ValueError("%s is not in globals[%d]" % (var, table_num))
        return vid - tbl['id_base']

    def find_var_table_number(self, var):
        """Return globals[] descriptor table number for a UART name or var_id."""
        vid = self.resolve_var_id(var)
        table_num, _ = self._var_table_for_id(vid)
        return table_num

    def infer_g2_language_count(self):
        """Return the number of locale slots compiled into globals[2]."""
        g2 = self.globals_offset(2)
        ptrs = []
        for i in range(128):
            ptr = self.read_u32(g2 + i * 8 + 4)
            if not ptr or self._flash_ptr_offset(ptr) is None:
                break
            ptrs.append(ptr)
        if len(ptrs) < 2:
            raise ValueError("globals[2] has too few locale arrays")

        deltas = {}
        for i in range(len(ptrs) - 1):
            delta = ptrs[i + 1] - ptrs[i]
            if delta > 0 and delta % 2 == 0 and delta <= 128:
                deltas[delta] = deltas.get(delta, 0) + 1
        if not deltas:
            raise ValueError("cannot infer language slot count from globals[2]")

        stride = max(deltas, key=deltas.get)
        slots = stride // 2
        sample = ptrs[:128]
        while slots > 1:
            all_zero = True
            for ptr in sample:
                off = ptr - self.FLASH_BASE + (slots - 1) * 2
                if self.read_u16(off) != 0:
                    all_zero = False
                    break
            if not all_zero:
                break
            slots -= 1
        return slots

    def load_firmware_string_metadata(self):
        """Cache string metadata before custom settings mutate descriptors."""
        if self.str_id_empty is not None:
            return

        rop = self.find_var('ROP')
        rpo = self.find_var('RPO')
        lan = self.find_var('LAN')

        self.str_id_empty = self.read_u16(rop + self.G8_NAME_STR)
        self.str_id_off_on_base = self.read_u16(rpo + self.G8_BASE_STR)
        self.fw_lang_count = self.infer_g2_language_count()

        perm = self.read_u32(lan + self.G8_BITMASK)
        self.fw_lang_ids = [bit for bit in range(32) if perm & (1 << bit)]
        if len(self.fw_lang_ids) != self.fw_lang_count:
            raise ValueError(
                "LAN language mask count %d != globals[2] slots %d" %
                (len(self.fw_lang_ids), self.fw_lang_count))

    def _raw_string_table_offset(self):
        g2 = self.globals_offset(2)
        locale0 = self.read_u32(g2 + 4)
        raw_indirect = locale0 - self.FLASH_BASE - 8
        if raw_indirect < 0 or raw_indirect + 4 > len(self.fw):
            raise ValueError("invalid raw string table pointer")

        raw = self.read_u32(raw_indirect) - self.FLASH_BASE
        if raw < 0 or raw >= len(self.fw):
            raise ValueError("invalid raw string table")
        return raw

    def firmware_string(self, str_id, lang_slot=0):
        """Return one localized globals[2] string, including queued changes."""
        edit = self._fw_string_edits.get(str_id)
        if edit is not None:
            self.load_firmware_string_metadata()
            return edit[self.fw_lang_ids[lang_slot]].decode('utf-8', errors='replace')
        g2 = self.globals_offset(2)
        locale_ptr = self.read_u32(g2 + str_id * 8 + 4)
        locale_arr = self._flash_ptr_offset(locale_ptr)
        if locale_arr is None:
            raise ValueError("invalid locale array for str_id 0x%04X" % str_id)

        raw = self._raw_string_table_offset()
        raw_idx = self.read_u16(locale_arr + lang_slot * 2)
        string_ptr = self.read_u32(raw + raw_idx * 4)
        string_off = self._flash_ptr_offset(string_ptr)
        if string_off is None:
            raise ValueError("invalid raw string pointer for str_id 0x%04X" % str_id)

        length = self.c_string_len(string_off)
        if length is None:
            raise ValueError("unterminated firmware string for str_id 0x%04X" % str_id)
        return self.read_bytes(string_off, length - 1).decode('utf-8', errors='replace')

    def _string_tables(self):
        """Read the current g[2] tables with the language-arena reader."""
        from .as10_languages import AS10LanguageFirmware
        return AS10LanguageFirmware('<patched image>', bytes(self.fw))

    def fw_string_count(self):
        """Return the number of g[2] text IDs, including queued additions."""
        if self._fw_string_base is None:
            self._fw_string_base = self._string_tables().text_count
        return self._fw_string_base + self._fw_string_added

    def add_fw_strings(self, count=1):
        """Reserve count consecutive new g[2] text IDs and return the first.

        Each reserved ID must be defined with redefine_fw_string() before
        finalize_fw_strings() writes the tables.
        """
        from .as10_languages import MAX_TEXT_IDS
        if count <= 0:
            raise ValueError("add_fw_strings: count must be positive")
        first = self.fw_string_count()
        if first + count > MAX_TEXT_IDS:
            raise ValueError("add_fw_strings: text ID 0x%04X exceeds the firmware ID range"
                             % (first + count - 1))
        self._fw_string_added += count
        return first

    def redefine_fw_string(self, str_id, strings):
        """Queue text for one g[2] string in every locale compiled into the image.

        strings maps ResMed language IDs to text and must contain English (0).
        Compiled languages without an entry use the English text; entries for
        other languages are ignored. The text is stored when
        finalize_fw_strings() rebuilds the tables, so this does not depend on
        how the current image shares raw entries or locale rows.
        """
        self.load_firmware_string_metadata()
        if 0 not in strings:
            raise ValueError("redefine_fw_string: missing English string at language id 0")
        if not 0 <= str_id < self.fw_string_count():
            raise ValueError("redefine_fw_string: str_id 0x%04X is not allocated" % str_id)

        from .as10_languages import text_length
        texts = {}
        for lang_id in self.fw_lang_ids:
            text = strings.get(lang_id, strings[0])
            texts[lang_id] = text.encode('utf-8') if isinstance(text, str) else bytes(text)
            if b'\0' in texts[lang_id]:
                raise ValueError("redefine_fw_string: text for str_id 0x%04X contains NUL" % str_id)
        text_length(texts, str_id)
        self._fw_string_edits[str_id] = texts

    def finalize_fw_strings(self, share=False):
        """Rebuild the g[2] tables with queued strings; return the layout or None.

        Unchanged strings keep their text and length field. Data owned by other
        patches inside the language arena is preserved; emit_string_tables()
        verifies the result.
        """
        if not self._fw_string_edits and not self._fw_string_added:
            return None
        from .as10_languages import emit_string_tables, text_length

        # Read the image now, after other patches have used CCX space.
        tables = self._string_tables()
        count = self.fw_string_count()
        undefined = [tid for tid in range(tables.text_count, count)
                     if tid not in self._fw_string_edits]
        if undefined:
            raise ValueError("finalize_fw_strings: new str_id 0x%04X has no text" % undefined[0])

        languages = tables.languages
        texts, lengths = [], []
        for tid in range(count):
            edit = self._fw_string_edits.get(tid)
            if edit is None:
                texts.append({lang: tables.texts[tid, lang] for lang in languages})
                lengths.append(tables.lengths[tid])
            else:
                texts.append(edit)
                lengths.append(text_length(edit, tid))
        data, layout = emit_string_tables(tables, languages, texts, lengths, share=share)

        self.fw[:] = data
        layout.update(texts=count, added=count - tables.text_count,
                      edited=len(self._fw_string_edits))
        self._fw_string_edits = {}
        self._fw_string_base = None
        self._fw_string_added = 0
        return layout

    def validate(self, validate_crc=True):
        """Validate the input file looks OK and populate information"""
        
        self.hash = hashlib.sha256(bytes(self.fw)).hexdigest()

        # Detect platform from bootloader ID string
        self.bid = self.read_bytes(self.BID_OFFSET, 16).split(b'\x00')[0].decode()
        platform_key = None
        for key in self.PLATFORMS:
            if self.bid.startswith(key):
                platform_key = key
                break
        if not platform_key:
            raise IOError("Unknown bootloader ID: '%s'" % self.bid)
        self.platform = self.PLATFORMS[platform_key]

        self.blx_off  = self.platform['blx_off']
        self.blx_size = self.platform['blx_size']
        self.ccx_off  = self.platform['ccx_off']
        self.ccx_size = self.platform['ccx_size']
        self.cdx_off  = self.platform['cdx_off']
        self.cdx_size = self.platform['cdx_size']
        self.globals_addr = self.ccx_off + self.GLOBALS_REL

        if validate_crc:
            for name, off, size in self.firmware_blocks():
                crc = self.crcfunc(self.read_bytes(off, size))
                if crc != 0:
                    print("%s CRC: 0x%04x (expected 0)" % (name, crc))
                    raise IOError("CRC mismatch in %s block" % name)

        # Read version strings
        self.pcd = self.read_bytes(self.ccx_off + 0x20, 7).split(b'\x00', 1)[0].decode()
        self.pna = self.read_bytes(self.ccx_off + 0x30, 0x1f).split(b'\x00', 1)[0].decode()
        cid_values = [self.read_u32(self.globals_offset(0) + i * 4) for i in range(7)]
        # Match the runtime CID formatter: MID-VID-RID-PVD-VIR-RIR-PVR.
        self.cid = "CX%03d-%03d-%03d-%03d-%03d-%03d-%03d" % (
            cid_values[1], cid_values[2], cid_values[3], cid_values[0],
            cid_values[5], cid_values[6], cid_values[4])
        self.cdx_sid = self.read_bytes(self.cdx_off, 0x20).split(b'\x00', 1)[0].decode()
        self.cdx_ver = self.cdx_sid[:10]
        if not re.match(r'^SX[0-9]{3}-[0-9]{4}$', self.cdx_ver):
            raise IOError("Unknown CDX software ID: '%s'" % self.cdx_sid)
        
        print("Firmware Info:")
        print("  BID  " + self.bid)
        print("  SID  " + self.cdx_sid)
        print("  PCD  " + self.pcd)
        print("  PNA  " + self.pna)

    def firmware_blocks(self):
        """Return the named firmware regions covered by block CRCs."""
        return (
            ('BLX', self.blx_off, self.blx_size),
            ('CCX', self.ccx_off, self.ccx_size),
            ('CDX', self.cdx_off, self.cdx_size),
        )

    def patch_firmware_sid(self, build):
        """Append the build identity to the stock CDX software ID."""
        if self.cdx_sid != self.cdx_ver and not re.match(
                r'^%s(?:[+!~][0-9A-Za-z]{3,4}|[0-9A-Za-z]{5})$' %
                re.escape(self.cdx_ver), self.cdx_sid):
            raise ValueError("firmware SID: unexpected input value '%s'" % self.cdx_sid)
        sid = self.cdx_ver + build['code']
        if len(sid) not in (14, 15):
            raise ValueError("firmware SID: '%s' does not fit the 15-character limit" % sid)
        sid_bytes = sid.encode('ascii')
        self.fw[self.cdx_off:self.cdx_off + 16] = list(sid_bytes + b'\x00' * (16 - len(sid_bytes)))
        self.cdx_sid = sid
        source = build['state']
        if build['commit']:
            source = "%s, %s" % (build['commit'][:12], source)
        print("Firmware SID:   %s (%s)" % (sid, source))
        
    def fix_crcs(self):
        """Update CRCs in the file"""
        for _, off, size in self.firmware_blocks():
            crc_off = off + size - 2
            new_crc = self.crcfunc(self.read_bytes(off, crc_off - off))
            self.write_u8(crc_off, new_crc >> 8)
            self.write_u8(crc_off + 1, new_crc)
        
    def find_bytes(self, dataseq):
        """Find location of byte sequence in FW"""
        fw = bytes(self.fw)
        dataseq = bytes(dataseq)
        i1 = fw.find(dataseq)
        i2 = fw.rfind(dataseq)
        
        if i1 != i2:
            raise ValueError("Passed sequence is not unique! Found at 0x%x and 0x%x"%(i1, i2))

        if i1 == -1:
            raise ValueError("Passed sequence not found")

        return i1

    def patch(self, patchdata, addr=None, dataseq=None, verbose=None,
              checkreserved=True, checkempty=False, clobber=False):
        """Updates firmware data with patchdata, based on address, sequence, or hash of sequence"""

        #I love Python3(TM)
        patchdata = list(bytes(patchdata))

        patchlen = len(patchdata)

        #Use simple method - fixed address patch
        if addr is not None:
            pass

        elif dataseq is not None:
            addr = self.find_bytes(dataseq)

        else:
            raise ValueError("Need to specify one of the patch methods")

        if verbose:
            data_hex = ' '.join('%02X' % byte for byte in patchdata)
            print("Patching %d bytes at 0x%08X: %s" %
                  (patchlen, self.FLASH_BASE + addr, data_hex))

        #Reservered uses self.reserve_marker to indicate our usage (more obvious when inspecting...)
        if checkempty:
            checkreserved = False
        
        if clobber:
            checkreserved = False
            checkempty = False
        
        if checkreserved:
            if self.read_bytes(addr, patchlen) != bytes([self.reserve_marker]) * patchlen:
                raise ValueError("Appears data in section you want me to patch! Bailing out...")

        if checkempty:
            if self.read_bytes(addr, patchlen) != b'\xFF' * patchlen:
                #print(self.fw[addr:(addr+patchlen)])
                raise ValueError("Appears data in section you want me to patch! Bailing out...")

        self.fw[addr:(addr+patchlen)] = patchdata

    def find_flash_room(self, length_needed, start=0x4000, start_mod=0x100, reserve=True):
        """Find at least length_needed bytes of 0xFF in flash we can hopefully re-use."""
        
        address = -1
        
        start_padding = 32
        end_padding = 256
        
        trying = True
        
        while trying:
            candidate = bytes(self.fw[start:]).find(bytes([0xff] * (length_needed + start_padding + end_padding)))
            if candidate < 0:
                raise ValueError("No more room :(")
            candidate += start
            candidate += start_padding
            
            #Round up to requested start position, check it will still work
            while candidate % start_mod != 0:
                candidate += 1
            
            if self.fw[candidate:(candidate+length_needed)] != [0xFF]*length_needed:
                start = candidate
            else:
                address = candidate
                trying = False
        
        if address < 0:
           raise ValueError("Failed to find space?")
        
        if reserve:
            self.fw[candidate:(candidate+length_needed)] = [self.reserve_marker] * length_needed
        
        return address
        
    def write_output(self, filename, overwrite=False):
        if self._fw_string_edits or self._fw_string_added:
            raise ValueError("queued firmware strings were not written; call finalize_fw_strings() first")
        if os.path.exists(filename) and not overwrite:
            raise IOError("File %s exists already." % filename)
    
        with open(filename, "wb") as f:
            f.write(bytes(self.fw))

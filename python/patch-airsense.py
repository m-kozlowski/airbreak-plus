#!/usr/bin/env python3

# This work was not produced in affiliation with any of the device manufactures and is,
# and is intended to be, an independent, third-party research project.
#
# This work is presented for research and educational purposes only. Any use or reproduction
# of this work is at your sole risk. The work is provided “as is” and “as available”, and without
# warranties of any kind, whether express or implied, including, but not limited to, implied
# warranties of merchantability, non-infringement of third party rights, or fitness for a
# particular purpose.
#
# See LICENSE in main repository for distribution license and additional restrictions.

import argparse
import hashlib
import io
import crcmod
import crcmod.predefined
import os
import subprocess
import struct
import re
import sys

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

    TABLES = {
        3:  dict(stride=10),
        4:  dict(stride=0x1C),
        6:  dict(stride=0x18),
        8:  dict(stride=0x14),
        9:  dict(stride=0x18),
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

    def __init__(self, file, validate_crc=True):
        self.fw = file.read()
        self.fw = list(self.fw)
        self.crcfunc = crc_func = crcmod.predefined.mkCrcFun('crc-ccitt-false')
        self.var_by_name = None
        self.var_tables = None
        self.fw_lang_count = None
        self.fw_lang_ids = None
        self.str_id_empty = None
        self.str_id_off_on_base = None
        
        self.validate(validate_crc=validate_crc)

    def read_u8(self, off):
        return self.fw[off]

    def read_u16(self, off):
        return struct.unpack_from('<H', bytes(self.fw[off:off+2]))[0]

    def read_u32(self, off):
        return struct.unpack_from('<I', bytes(self.fw[off:off+4]))[0]

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

    def find_ccx_ff_range_backwards(self, size):
        limit = self.ccx_off + self.ccx_size - 2
        for end in range(limit, self.ccx_off + size - 1, -1):
            start = end - size
            if self.fw[start:end] == [0xFF] * size:
                return start
        raise ValueError("no CCX string space for %d bytes" % size)

    def globals_offset(self, idx):
        """Return file offset for data that globals[idx] points to"""
        off = self.globals_addr + idx * 4
        ptr = self.read_u32(off)
        return ptr - self.FLASH_BASE

    def find_var_id(self, var_id):
        """Return descriptor file offset for numeric var_id."""
        self._load_var_tables()
        for tbl in self.var_tables.values():
            id_base = tbl['id_base']
            count = tbl['count']
            if id_base <= var_id < id_base + count:
                return tbl['base'] + (var_id - id_base) * tbl['stride']
        raise ValueError("find_var_id: var_id 0x%04X not in derived descriptor tables" % var_id)

    def _flash_ptr_offset(self, ptr):
        off = ptr - self.FLASH_BASE
        if off < 0 or off >= len(self.fw):
            return None
        return off

    def _next_global_offset_after(self, base):
        candidates = []
        for idx in range(30):
            ptr = self.read_u32(self.globals_addr + idx * 4)
            off = self._flash_ptr_offset(ptr)
            if off is not None and off > base:
                candidates.append(off)
        return min(candidates) if candidates else None

    def _table_count(self, table_num, base, stride):
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
        if self.var_tables is not None:
            return

        self.var_tables = {}
        expected_base = None
        for table_num in (3, 4, 6, 8, 9):
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
        self._load_var_tables()
        tbl = self.var_tables.get(table_num)
        if tbl is None:
            raise ValueError("globals[%d] descriptor table not found" % table_num)

        rec = self.find_var(var)
        rel = rec - tbl['base']
        if rel < 0 or rel % tbl['stride']:
            raise ValueError("%s is not in globals[%d]" % (var, table_num))

        idx = rel // tbl['stride']
        if idx >= tbl['count']:
            raise ValueError("%s is not in globals[%d]" % (var, table_num))
        return idx

    def find_var_table_number(self, var):
        """Return globals[] descriptor table number for a UART name or var_id."""
        vid = self.resolve_var_id(var)
        self._load_var_tables()
        for table_num, tbl in self.var_tables.items():
            id_base = tbl['id_base']
            count = tbl['count']
            if id_base <= vid < id_base + count:
                return table_num
        raise ValueError("find_var_table_number: var_id 0x%04X not in derived descriptor tables" % vid)

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

    def redefine_fw_string(self, str_id, strings):
        """Rewrite one firmware string for all locales compiled into the image."""
        self.load_firmware_string_metadata()
        if 0 not in strings:
            raise ValueError("redefine_fw_string: missing English string at language id 0")

        raw = self._raw_string_table_offset()
        g2 = self.globals_offset(2)
        rec = g2 + str_id * 8
        locale_arr = self.read_u32(rec + 4) - self.FLASH_BASE
        if locale_arr < 0 or locale_arr >= len(self.fw):
            raise ValueError("invalid locale array for str_id 0x%04X" % str_id)

        english_ptr = None
        max_len = 0
        for slot, lang_id in enumerate(self.fw_lang_ids):
            text = strings.get(lang_id)
            if text is None and english_ptr is not None:
                raw_idx = self.read_u16(locale_arr + slot * 2)
                raw_ptr_off = raw + raw_idx * 4
                if raw_ptr_off < 0 or raw_ptr_off + 4 > len(self.fw):
                    raise ValueError("raw string entry out of range")
                self.write_u32(raw_ptr_off, english_ptr)
                continue

            if text is None:
                text = strings[0]
            data = text.encode('ascii') + b'\x00'
            max_len = max(max_len, len(data) - 1)

            raw_idx = self.read_u16(locale_arr + slot * 2)
            raw_ptr_off = raw + raw_idx * 4
            if raw_ptr_off < 0 or raw_ptr_off + 4 > len(self.fw):
                raise ValueError("raw string entry out of range")

            old = self.read_u32(raw_ptr_off) - self.FLASH_BASE
            old_cap = self.c_string_len(old)
            if old_cap is not None and len(data) <= old_cap:
                self.fw[old:old+old_cap] = list(data + b'\x00' * (old_cap - len(data)))
                new_off = old
            else:
                new_off = self.find_ccx_ff_range_backwards(len(data))
                self.fw[new_off:new_off+len(data)] = list(data)

            ptr = self.FLASH_BASE + new_off
            self.write_u32(raw_ptr_off, ptr)
            if lang_id == 0:
                english_ptr = ptr

        self.write_u16(rec, max_len)
        
    def validate(self, validate_crc=True):
        """Validate the input file looks OK and populate information"""
        
        self.hash = hashlib.sha256(bytes(self.fw)).hexdigest()

        # Detect platform from bootloader ID string
        self.bid = bytes(self.fw[self.BID_OFFSET:self.BID_OFFSET + 16]).split(b'\x00')[0].decode()
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
            blocks = [
                ('BLX', self.blx_off, self.blx_size),
                ('CCX', self.ccx_off, self.ccx_size),
                ('CDX', self.cdx_off, self.cdx_size),
            ]
            for name, off, size in blocks:
                crc = self.crcfunc(bytes(self.fw[off:off + size]))
                if crc != 0:
                    print("%s CRC: 0x%04x (expected 0)" % (name, crc))
                    raise IOError("CRC mismatch in %s block" % name)

        # Read version strings
        self.str_model_number = bytes(self.fw[self.ccx_off + 0x20:self.ccx_off + 0x27]).decode()
        self.str_model_name = bytes(self.fw[self.ccx_off + 0x30:self.ccx_off + 0x4F]).decode()
        self.cdx_ver = bytes(self.fw[self.cdx_off:self.cdx_off + 0x0B]).split(b'\x00')[0].decode()
        
        print("Firmware Info: ")
        print("  Loader Version   " + self.bid)
        print("  Catalog No.      " + self.str_model_number)
        print("  Model Name       " + self.str_model_name)
        print("  Main SW Version  " + self.cdx_ver)
        
    def fix_crcs(self):
        """Update CRCs in the file"""
        blocks = [
            (self.blx_off, self.blx_size),
            (self.ccx_off, self.ccx_size),
            (self.cdx_off, self.cdx_size),
        ]
        for off, size in blocks:
            crc_off = off + size - 2
            new_crc = self.crcfunc(bytes(self.fw[off:crc_off]))
            self.write_u8(crc_off, new_crc >> 8)
            self.write_u8(crc_off + 1, new_crc)
        
    def find_bytes(self, dataseq):
        """Find location of byte sequence in FW"""
        
        i1 = bytes(self.fw).find(bytes(dataseq))
        i2 = bytes(self.fw).rfind(bytes(dataseq))
        
        if i1 != i2:
            raise ValueError("Passed sequence is not unique! Found at 0x%x and 0x%x"%(i1, i2))

        if i1 == -1:
            raise ValueError("Passed sequence not found")

        return i1

    def patch(self, patchdata, addr=None, dataseq=None, hash=None, verbose=None, checkreserved=True, checkempty=False, clobber=False):
        """Updates firmware data with patchdata, based on address, sequence, or hash of sequence"""

        #I love Python3(TM)
        patchdata = list(bytes(patchdata))

        patchlen = len(patchdata)

        #Use simple method - fixed address patch
        if addr:
            pass

        elif dataseq:
            addr = self.find_bytes(dataseq)

        elif hash:
            raise NotImplementedError("Not yet done")

        else:
            raise ValueError("Need to specify one of the patch methods")

        if verbose or (verbose is None and getattr(self, 'verbose', False)):
            print("Patching %d bytes at 0x%x"%(patchlen, addr))

        #Reservered uses self.reserve_marker to indicate our usage (more obvious when inspecting...)
        if checkempty:
            checkreserved = False
        
        if clobber:
            checkreserved = False
            checkempty = False
        
        if checkreserved:
            if self.fw[addr:(addr+patchlen)] != self.reserve_marker*len(patchdata):
                raise ValueError("Appears data in section you want me to patch! Bailing out...")

        if checkempty:
            if self.fw[addr:(addr+patchlen)] != [0xFF]*len(patchdata):
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
                print("Oops... try again")
                start = candidate
            else:
                address = candidate
                trying = False
        
        if address < 0:
           raise ValueError("Failed to find space?")
        
        print("Found space at " + str(hex(address)))
        
        if reserve:
            print("Reserving %d bytes"%length_needed)
            self.fw[candidate:(candidate+length_needed)] = [self.reserve_marker] * length_needed
        
        return address
        
    def patch_image(self, structaddr, palletaddr, pixeladdr, image):
        #X size
        self.fw[(structaddr + 0):(structaddr + 2)] = list(struct.pack('H', image.meta_xsize))

        #Y size
        self.fw[(structaddr + 2):(structaddr + 4)] = list(struct.pack('H', image.meta_ysize))

        #'BytesPerLine' size
        self.fw[(structaddr + 4):(structaddr + 6)] = list(struct.pack('H', image.meta_bytesper))

        
        # We leave bitsperpixel alone - should be '0'
        #self.fw[structaddr + 6]
        #self.fw[structaddr + 7]
        
        #Pointer to pixels
        self.fw[(structaddr + 8):(structaddr + 12)] = list(struct.pack('I', pixeladdr + 0x08000000))
        
        #Pointer to pallete
        self.fw[(structaddr + 12):(structaddr + 16)] = list(struct.pack('I', palletaddr + 0x08000000))
        
        #Pointer to function for drawing/decoding (not changed)
        #self.fw[(structaddr + 16):(structaddr + 24)]
        
        #Copy pixel data over as well
        self.patch(image.pixels, pixeladdr)
        
        #Pallete needs a little support struct to feel better
        self.fw[(palletaddr + 0):(palletaddr + 4)] = list(struct.pack('I', image.pallete_numberentries))
        self.fw[(palletaddr + 4):(palletaddr + 8)] = list(struct.pack('I', image.pallete_numbertransp))
        self.fw[(palletaddr + 8):(palletaddr + 12)] = list(struct.pack('I', palletaddr + 16 + 0x08000000))

        #Copy pallete over where we expect it
        for i in range(0, len(image.pallete)):
            self.fw[(palletaddr + 16 + (i*4)):(palletaddr + 16 + (i*4 + 4))] = list(struct.pack('I', image.pallete[i]))

    def write_output(self, filename, overwrite=False):
        if os.path.exists(filename) and (overwrite == False):
            raise IOError("File " + filename + "exists already.")
    
        f = open(filename, "wb")
        f.write(bytes(self.fw))
        f.close()
        
    def prepare_bin(self, filename):
        """Uses .lst file to find symbols - could use ELF too put requires additional dependancy"""
        
        f = open(filename + ".lst", "rb")
        lst = f.read()
        f.close()
        
        f = open(filename + ".bin", "rb")
        bin = f.read()
        f.close()
        
        #Find 'start' symbol we assume each file uses
        addr_offset = re.search(rb'\.text:[0-F]{8} start', lst, re.IGNORECASE).group(0)
        
        #addr should look like this now - .text:00000000 start        
        addr_offset = addr_offset.split(b':')[1].split(b' ')[0]
        addr_offset = int(addr_offset, 16)
        
        return addr_offset, bin

class ASFirmwarePatches(object):
    """This class contains the actual patching scripts for specific items"""

    CUSTOM_MENU_HOOKS_OFF = 0xFFC00
    CUSTOM_MENU_HOOKS_BUDGET = 0x3FE
    MOP_CALLBACK_DISPATCHER_OFF = 0xFCF98
    MOP_CALLBACK_DISPATCHER_BUDGET = 0x2C
    VID_SPOOF_OFF = 0xFCFC4
    VID_SPOOF_BUDGET = 0x3C
    MOP_CALLBACK_TABLES = {
        'SX567-0302': 0x757e0,
        'SX567-0305': 0x75f4c,
        'SX567-0306': 0x75f48,
        'SX567-0401': 0x75f48,
        'SX567-0402': 0x75f48,
    }
    CUSTOM_MENU_FLAG_G4_NUMERIC = 1
    CUSTOM_MENU_SECTIONS = {
        'therapy': 0,
        'comfort': 1,
        'accessories': 2,
        'options': 3,
        'configuration': 4,
    }
    MOP_INDEX = {
        'CPAP': 0,
        'AUTOSET': 1,
        'APAP': 2,
        'S': 3,
        'ST': 4,
        'T': 5,
        'VAUTO': 6,
        'ASV': 7,
        'ASVAUTO': 8,
        'IVAPS': 9,
        'PAC': 10,
        'AFH': 11,
    }
        
    def __init__(self, asf):
        self.asf = asf
        self.squarewave_applied = False
        self.wrapper_limit_max_pdiff_applied = False
        self.mop_callback_handlers = []
        self.mop_callback_handler_seen = set()
        self.custom_patch_settings_init()

    def custom_patch_settings_init(self):
        """Reset generated custom-settings state."""
        self.custom_g8_pool = []
        self.custom_g4_pool = []
        self.custom_g8_reclaimed = {}
        self.custom_g4_reclaimed = {}
        self.custom_g8_claims = {}
        self.custom_g4_claims = {}
        self.custom_string_pool = []
        self.custom_reclaimed_string_candidates = []
        self.custom_reclaimed_string_seen = set()
        self.custom_menu_entries = []
        self.custom_menu_registered = set()
        self.custom_settings_registry_addr = None
        self.custom_settings_registry_size = None

    def _custom_note_reclaimed_string_id(self, str_id):
        self.asf.load_firmware_string_metadata()
        if str_id == self.asf.str_id_empty:
            return
        if str_id not in self.custom_reclaimed_string_seen:
            self.custom_reclaimed_string_seen.add(str_id)
            self.custom_reclaimed_string_candidates.append(str_id)

    def _referenced_reclaimed_string_ids(self):
        candidates = set(self.custom_reclaimed_string_candidates)
        referenced = set()

        def mark(str_id):
            if str_id in candidates:
                referenced.add(str_id)

        self.asf._load_var_tables()
        for table_num, tbl in self.asf.var_tables.items():
            if table_num == 3:
                offsets = (0x06,)
            elif table_num == 4:
                offsets = (self.asf.G4_NAME_STR, self.asf.G4_UNITS_STR)
            elif table_num == 6:
                offsets = (self.asf.G6_LABEL_STR,)
            elif table_num in (8, 9):
                offsets = (self.asf.G8_NAME_STR, self.asf.G8_BASE_STR)
            else:
                continue

            for idx in range(tbl['count']):
                rec = tbl['base'] + idx * tbl['stride']
                for off in offsets:
                    mark(self.asf.read_u16(rec + off))

        g5 = self.asf.globals_offset(5)
        g5_end = self.asf._next_global_offset_after(g5)
        if g5 >= 0 and g5_end is not None and g5_end > g5:
            for off in range(g5, g5_end - 1, 2):
                mark(self.asf.read_u16(off))

        return referenced

    def custom_build_string_pool(self):
        """Build reusable string pool from reclaimed, now-unreferenced strings."""
        if not self.custom_reclaimed_string_candidates:
            raise ValueError("custom_patch_settings: no reclaimed string IDs available")

        referenced = self._referenced_reclaimed_string_ids()
        self.custom_string_pool = [
            str_id for str_id in self.custom_reclaimed_string_candidates
            if str_id not in referenced
        ]
        if not self.custom_string_pool:
            raise ValueError("custom_patch_settings: no reclaimed string IDs available")

    def custom_alloc_string(self, owner):
        """Allocate one reclaimed string ID to a feature."""
        if not self.custom_string_pool:
            raise ValueError("custom_alloc_string: pool exhausted for %s" % owner)
        return self.custom_string_pool.pop(0)

    def redefine_fw_string(self, str_id, strings, owner='string'):
        """Rewrite a firmware string, allocating from the reclaimed pool for -1."""
        if str_id == -1:
            str_id = self.custom_alloc_string(owner)
        self.asf.redefine_fw_string(str_id, strings)
        return str_id

    def custom_reclaim_g8_var(self, name):
        """Scrub a g[8] enum descriptor and add it to the reclaimed pool."""
        vid = self.asf.resolve_var_id(name)
        if vid in self.custom_g8_reclaimed:
            raise ValueError("custom_reclaim_g8_var: duplicate reclaim of %s (var_id 0x%04X)" % (name, vid))

        self.asf.load_firmware_string_metadata()
        rec = self.asf.find_var(vid)
        name_str = self.asf.read_u16(rec + self.asf.G8_NAME_STR)
        base_str = self.asf.read_u16(rec + self.asf.G8_BASE_STR)
        self.asf.write_u16(rec + self.asf.G8_NAME_STR, self.asf.str_id_empty)
        self.asf.write_u16(rec + self.asf.G8_BASE_STR, self.asf.str_id_empty)
        self._custom_note_reclaimed_string_id(name_str)
        self._custom_note_reclaimed_string_id(base_str)

        claim_name = name.upper() if isinstance(name, str) and not name.lower().startswith('0x') else "0x%04X" % vid
        self.custom_g8_reclaimed[vid] = claim_name
        self.custom_g8_pool.append(claim_name)

    def custom_reclaim_g4_var(self, name):
        """Scrub a g[4] numeric descriptor and add it to the reclaimed pool."""
        vid = self.asf.resolve_var_id(name)
        if vid in self.custom_g4_reclaimed:
            raise ValueError("custom_reclaim_g4_var: duplicate reclaim of %s (var_id 0x%04X)" % (name, vid))

        self.asf.load_firmware_string_metadata()
        rec = self.asf.find_var(vid)
        name_str = self.asf.read_u16(rec + self.asf.G4_NAME_STR)
        units_str = self.asf.read_u16(rec + self.asf.G4_UNITS_STR)
        self.asf.write_u16(rec + self.asf.G4_NAME_STR, self.asf.str_id_empty)
        self.asf.write_u16(rec + self.asf.G4_UNITS_STR, self.asf.str_id_empty)
        self._custom_note_reclaimed_string_id(name_str)
        self._custom_note_reclaimed_string_id(units_str)

        claim_name = name.upper() if isinstance(name, str) and not name.lower().startswith('0x') else "0x%04X" % vid
        self.custom_g4_reclaimed[vid] = claim_name
        self.custom_g4_pool.append(claim_name)

    def custom_claim_g8_var(self, request, owner=None):
        """Claim one exact reclaimed g[8] variable and return its UART name."""
        vid = self.asf.resolve_var_id(request)
        owner = owner or request
        if vid not in self.custom_g8_reclaimed:
            raise ValueError("custom_claim_g8_var: %s (var_id 0x%04X) is not reclaimed" % (request, vid))
        if vid in self.custom_g8_claims:
            raise ValueError(
                "custom_claim_g8_var: %s (var_id 0x%04X) already claimed by %s" %
                (request, vid, self.custom_g8_claims[vid]))
        self.custom_g8_claims[vid] = owner
        return self.custom_g8_reclaimed[vid]

    def custom_claim_g4_var(self, request, owner=None):
        """Claim one exact reclaimed g[4] variable and return its UART name."""
        vid = self.asf.resolve_var_id(request)
        owner = owner or request
        if vid not in self.custom_g4_reclaimed:
            raise ValueError("custom_claim_g4_var: %s (var_id 0x%04X) is not reclaimed" % (request, vid))
        if vid in self.custom_g4_claims:
            raise ValueError(
                "custom_claim_g4_var: %s (var_id 0x%04X) already claimed by %s" %
                (request, vid, self.custom_g4_claims[vid]))
        self.custom_g4_claims[vid] = owner
        return self.custom_g4_reclaimed[vid]

    def redefine_g8_var(self, var, flags, callback, dep_head, name_str, default,
                        num_options, param_0a, perm_mask, base_str, param_12):
        """Rewrite a g[8] descriptor with caller-provided raw fields."""
        rec = self.asf.find_var(var)
        self.asf.write_u16(rec + self.asf.G8_FLAGS, flags)
        self.asf.write_u8(rec + self.asf.G8_CALLBACK, callback)
        self.asf.write_u16(rec + self.asf.G8_DEP_HEAD, dep_head)
        self.asf.write_u16(rec + self.asf.G8_NAME_STR, name_str)
        self.asf.write_u8(rec + self.asf.G8_DEFAULT, default)
        self.asf.write_u8(rec + self.asf.G8_NUM_OPTIONS, num_options)
        self.asf.write_u16(rec + self.asf.G8_PARAM_0A, param_0a)
        self.asf.write_u32(rec + self.asf.G8_BITMASK, perm_mask)
        self.asf.write_u16(rec + self.asf.G8_BASE_STR, base_str)
        self.asf.write_u16(rec + self.asf.G8_PARAM_12, param_12)

    def redefine_g4_var(self, var, flags, callback, next_chain, name_str, default,
                        max_value, min_value, decimals, scale, step, units_str):
        """Rewrite a g[4] numeric descriptor with caller-provided raw fields."""
        rec = self.asf.find_var(var)
        self.asf.write_u16(rec + self.asf.G4_FLAGS, flags)
        self.asf.write_u8(rec + self.asf.G4_CALLBACK, callback)
        self.asf.write_u16(rec + self.asf.G4_NEXT_DEP, next_chain)
        self.asf.write_u16(rec + self.asf.G4_NAME_STR, name_str)
        self.asf.write_u32(rec + self.asf.G4_DEFAULT, default)
        self.asf.write_u32(rec + self.asf.G4_MAX, max_value)
        self.asf.write_u32(rec + self.asf.G4_MIN, min_value)
        self.asf.write_u8(rec + self.asf.G4_DECIMALS, decimals)
        self.asf.write_u16(rec + self.asf.G4_SCALE, scale)
        self.asf.write_u16(rec + self.asf.G4_STEP, step)
        self.asf.write_u16(rec + self.asf.G4_UNITS_STR, units_str)

    def custom_menu_add(self, section_name, var, mode_mask=0xffffffff):
        """Register one variable to be appended to a clinical menu section."""
        section = self.CUSTOM_MENU_SECTIONS.get(section_name.lower())
        if section is None:
            raise ValueError("custom_menu_add: unknown section %s" % section_name)

        vid = self.asf.resolve_var_id(var)
        table_num = self.asf.find_var_table_number(var)
        if table_num == 4:
            flags = self.CUSTOM_MENU_FLAG_G4_NUMERIC
        elif table_num == 8:
            flags = 0
        else:
            raise ValueError(
                "custom_menu_add: %s is globals[%d], only g[4]/g[8] menu settings are supported" %
                (var, table_num))
        if vid in self.custom_menu_registered:
            raise ValueError("custom_menu_add: duplicate variable %s (var_id 0x%04X)" % (var, vid))
        self.custom_menu_registered.add(vid)
        self.custom_menu_entries.append((section, flags, vid, int(mode_mask)))

    def mop_bitmask(self, *modes):
        """Build a g[24]/MOP visibility mask from MOP names or numeric indexes."""
        mask = 0
        for mode in modes:
            if isinstance(mode, str):
                key = mode.upper()
                if key in self.MOP_INDEX:
                    idx = self.MOP_INDEX[key]
                else:
                    idx = int(mode, 0)
            else:
                idx = int(mode)
            mask |= 1 << idx
        return mask

    def custom_emit_registry(self):
        """Serialize the generated registry into the reclaimed Reminders page space."""
        need = (len(self.custom_menu_entries) + 1) * 8
        if need > self.custom_settings_registry_size:
            raise ValueError(
                "custom_patch_settings: registry %dB exceeds reclaimed %dB" %
                (need, self.custom_settings_registry_size))

        off = self.custom_settings_registry_addr
        for section, flags, vid, mode_mask in self.custom_menu_entries:
            self.asf.write_u8(off, section)
            self.asf.write_u8(off + 1, flags)
            self.asf.write_u16(off + 2, vid)
            self.asf.write_u32(off + 4, mode_mask)
            off += 8
        self.asf.fill_range(off, 8, 0xff)

    def mop_callback_register_handler(self, handler, name):
        """Register one feature handler to run after the stock MOP callback."""
        handler = int(handler) | 1
        if handler in self.mop_callback_handler_seen:
            return
        self.mop_callback_handler_seen.add(handler)
        self.mop_callback_handlers.append(handler)
        print("  MOP callback handler: %s at 0x%08X" % (name, handler))

    def patch_mop_callback_dispatcher(self):
        """Install callback_table[MOP.callback_id] dispatcher if handlers exist."""
        if not self.mop_callback_handlers:
            return
        if len(self.mop_callback_handlers) > 4:
            raise ValueError("mop_callback_dispatcher: too many handlers (%d)" %
                             len(self.mop_callback_handlers))

        ver = self.asf.cdx_ver.replace('SX567-', '')
        bin_path = self._versioned_artifact_path('mop_callback_dispatcher', 'bin', ver)
        elf_path = self._versioned_artifact_path('mop_callback_dispatcher', 'elf', ver)
        if not os.path.exists(bin_path):
            raise ValueError("mop_callback_dispatcher: build/mop_callback_dispatcher_%s.bin not found (run make)" % ver)
        if not os.path.exists(elf_path):
            raise ValueError("mop_callback_dispatcher: build/mop_callback_dispatcher_%s.elf not found" % ver)

        with open(bin_path, 'rb') as f:
            data = f.read()
        if len(data) > self.MOP_CALLBACK_DISPATCHER_BUDGET:
            raise ValueError(
                "mop_callback_dispatcher: %s is %dB, exceeds %dB budget" %
                (bin_path, len(data), self.MOP_CALLBACK_DISPATCHER_BUDGET))

        off = self.MOP_CALLBACK_DISPATCHER_OFF
        budget = self.asf.fw[off:off + self.MOP_CALLBACK_DISPATCHER_BUDGET]
        if budget != [0xff] * self.MOP_CALLBACK_DISPATCHER_BUDGET:
            raise ValueError("mop_callback_dispatcher: payload area 0x%X is not empty" % off)

        start = self._elf_symbol_addr(elf_path, 'start')
        handler_table = self._elf_symbol_addr(elf_path, 'mop_callback_handler_table')
        callback_table = self.MOP_CALLBACK_TABLES.get(self.asf.cdx_ver)
        if callback_table is None:
            raise ValueError("mop_callback_dispatcher: unsupported CDX version %s" % self.asf.cdx_ver)

        mop_rec = self.asf.find_var('MOP')
        callback_id = self.asf.read_u8(mop_rec + self.asf.G8_CALLBACK)
        slot = callback_table + callback_id * 4
        original = self.asf.read_u32(slot)

        self.asf.patch(data, off, checkempty=True)
        table_off = handler_table - self.asf.FLASH_BASE
        self.asf.write_u32(table_off, original)
        for i, handler in enumerate(self.mop_callback_handlers):
            self.asf.write_u32(table_off + (i + 1) * 4, handler)
        self.asf.write_u32(table_off + (len(self.mop_callback_handlers) + 1) * 4, 0xffffffff)
        self.asf.write_u32(slot, start | 1)

        print("  MOP callback dispatcher: build/mop_callback_dispatcher_%s.bin (%dB) at 0x%08X" %
              (ver, len(data), self.asf.FLASH_BASE + off))
        print("  MOP callback[%d]: 0x%08X -> 0x%08X" %
              (callback_id, original, start | 1))

    def _versioned_artifact_path(self, name, ext, ver):
        return os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            '..', 'build', '%s_%s.%s' % (name, ver, ext))

    def _patch_menu_hook_site(self, site, expected, target, name):
        """Replace one stock section-tail append call with a hook call."""
        if bytes(self.asf.fw[site:site+len(expected)]) != expected:
            raise ValueError("custom_patch_settings: unexpected %s hook bytes at 0x%X" % (name, site))
        self.asf.patch(self._encode_thumb_bl(site, target), site, clobber=True)

    def _patch_clinical_menu_capacity(self, imm_off, stock_capacity):
        """Grow the clinical settings scrollbar capacity for generated entries."""
        custom_count = len(self.custom_menu_entries)
        new_capacity = stock_capacity + custom_count
        if (self.asf.read_u8(imm_off) != stock_capacity or
                self.asf.read_u8(imm_off + 1) != 0x22):
            raise ValueError("custom_patch_settings: unexpected clinical menu capacity bytes at 0x%X" % imm_off)
        if new_capacity > 0xff:
            raise ValueError("custom_patch_settings: clinical menu capacity exceeds Thumb imm8")
        self.asf.write_u8(imm_off, new_capacity)
        print("  clinical menu capacity: %d -> %d" % (stock_capacity, new_capacity))

    def custom_patch_menu_hooks(self):
        """Inject the generic clinical-menu hook payload and patch its ABI slots."""
        sites_by_version = {
            'SX567-0401': {
                'therapy': 0x62414,
                'comfort': 0x62672,
                'accessories': 0x626fe,
                'options': 0x62750,
                'configuration': 0x628d2,
                'clinical_capacity_site': 0x61fba,
                'clinical_capacity': 70,
            },
            'SX567-0402': {
                'therapy': 0x62414,
                'comfort': 0x62672,
                'accessories': 0x626fe,
                'options': 0x62750,
                'configuration': 0x628d2,
                'clinical_capacity_site': 0x61fba,
                'clinical_capacity': 70,
            },
        }
        sites = sites_by_version.get(self.asf.cdx_ver)
        if sites is None:
            print("  custom_patch_menu_hooks: skipped (unsupported CDX version %s)" % self.asf.cdx_ver)
            return

        ver = self.asf.cdx_ver.replace('SX567-', '')
        bin_path = self._versioned_artifact_path('custom_menu_hooks', 'bin', ver)
        elf_path = self._versioned_artifact_path('custom_menu_hooks', 'elf', ver)
        if not os.path.exists(bin_path):
            raise ValueError("custom_patch_settings: build/custom_menu_hooks_%s.bin not found (run make)" % ver)
        if not os.path.exists(elf_path):
            raise ValueError("custom_patch_settings: build/custom_menu_hooks_%s.elf not found" % ver)

        with open(bin_path, 'rb') as f:
            data = f.read()
        if len(data) > self.CUSTOM_MENU_HOOKS_BUDGET:
            raise ValueError(
                "custom_patch_settings: %s is %dB, exceeds %dB budget" %
                (bin_path, len(data), self.CUSTOM_MENU_HOOKS_BUDGET))

        budget = self.asf.fw[
            self.CUSTOM_MENU_HOOKS_OFF:self.CUSTOM_MENU_HOOKS_OFF + self.CUSTOM_MENU_HOOKS_BUDGET]
        if budget != [0xff] * self.CUSTOM_MENU_HOOKS_BUDGET:
            raise ValueError("custom_patch_settings: payload area 0x%X is not empty" %
                             self.CUSTOM_MENU_HOOKS_OFF)

        self.asf.patch(data, self.CUSTOM_MENU_HOOKS_OFF, checkempty=True)
        registry_flash = self.asf.FLASH_BASE + self.custom_settings_registry_addr

        hook_therapy = self._elf_symbol_addr(elf_path, 'custom_menu_hook_therapy')
        hook_comfort = self._elf_symbol_addr(elf_path, 'custom_menu_hook_comfort')
        hook_accessories = self._elf_symbol_addr(elf_path, 'custom_menu_hook_accessories')
        hook_options = self._elf_symbol_addr(elf_path, 'custom_menu_hook_options')
        hook_configuration = self._elf_symbol_addr(elf_path, 'custom_menu_hook_configuration')
        registry_addr = self._elf_symbol_addr(elf_path, 'custom_menu_registry_addr')
        visibility_handler = self._elf_symbol_addr(elf_path, 'custom_menu_apply_mode_visibility')

        self.asf.write_u32(registry_addr - self.asf.FLASH_BASE, registry_flash)

        self._patch_clinical_menu_capacity(sites['clinical_capacity_site'], sites['clinical_capacity'])
        self._patch_menu_hook_site(sites['therapy'], b'\x02\xf0\x3a\xfd', hook_therapy, 'therapy')
        self._patch_menu_hook_site(sites['comfort'], b'\x02\xf0\x0b\xfc', hook_comfort, 'comfort')
        self._patch_menu_hook_site(sites['accessories'], b'\x02\xf0\xc5\xfb', hook_accessories, 'accessories')
        self._patch_menu_hook_site(sites['options'], b'\x02\xf0\x9c\xfb', hook_options, 'options')
        self._patch_menu_hook_site(
            sites['configuration'], b'\x02\xf0\xdb\xfa', hook_configuration, 'configuration')
        self.mop_callback_register_handler(visibility_handler, 'custom_menu_visibility')

        print("  custom menu hooks: build/custom_menu_hooks_%s.bin (%dB) at 0x%08X" %
              (ver, len(data), self.asf.FLASH_BASE + self.CUSTOM_MENU_HOOKS_OFF))

    def custom_patch_settings_myasv(self):
        """Expose reclaimed my_asv settings and pass their var_ids to the wrapper."""
        myasv_var = self.custom_claim_g8_var('RPO', 'my_asv_enable')
        tc_var = self.custom_claim_g8_var('RPH', 'my_asv_triggercycle')
        max_var = self.custom_claim_g4_var('RCM', 'my_asv_max')
        sens_var = self.custom_claim_g8_var('RXM', 'my_asv_sens')
        myasv_label = self.redefine_fw_string(-1, {0: 'Custom ASV'}, 'my_asv_label')
        tc_label = self.redefine_fw_string(-1, {0: 'Custom T/C'}, 'my_asv_triggercycle_label')
        max_label = self.redefine_fw_string(-1, {0: 'ASV Max'}, 'my_asv_max_label')
        sens_label = self.redefine_fw_string(-1, {0: 'ASV Sens'}, 'my_asv_sens_label')
        myasv_dep = self.asf.find_var_table_index(4, 'RGT')
        cmh2o_units = self.asf.read_u16(self.asf.find_var('IPC') + self.asf.G4_UNITS_STR)
        sens_base = self.asf.read_u16(self.asf.find_var('VCS') + self.asf.G8_BASE_STR)

        self.redefine_g8_var(myasv_var, 0x0007, 0, myasv_dep, myasv_label, 0,
                             2, 0, 0x00000003, self.asf.str_id_off_on_base, 0)
        self.redefine_g8_var(tc_var, 0x0007, 0, myasv_dep, tc_label, 0,
                             2, 0, 0x00000003, self.asf.str_id_off_on_base, 0)
        self.redefine_g8_var(sens_var, 0x0007, 0, myasv_dep, sens_label, 2,
                             5, 0, 0x0000001F, sens_base, 0)
        self.redefine_g4_var(max_var, 0x0007, 0, myasv_dep, max_label, 150,
                             500, 0, 1, 50, 10, cmh2o_units)
        myasv_vid = self.asf.resolve_var_id(myasv_var)
        tc_vid = self.asf.resolve_var_id(tc_var)
        max_vid = self.asf.resolve_var_id(max_var)
        sens_vid = self.asf.resolve_var_id(sens_var)
        self.custom_menu_add('therapy', myasv_var, self.mop_bitmask('VAuto'))
        self.custom_menu_add('therapy', max_var, self.mop_bitmask('VAuto'))
        self.custom_menu_add('therapy', sens_var, self.mop_bitmask('VAuto'))
        self.custom_menu_add('therapy', tc_var, self.mop_bitmask('S', 'ST', 'T', 'VAuto', 'PAC'))

        ver = self.asf.cdx_ver.replace('SX567-', '')
        elf_path = self._versioned_artifact_path('wrapper_limit_max_pdiff', 'elf', ver)
        if not os.path.exists(elf_path):
            raise ValueError("custom_patch_settings_myasv: build/wrapper_limit_max_pdiff_%s.elf not found" % ver)
        addr = self._elf_symbol_addr(elf_path, 'wrapper_limit_max_pdiff_toggle_var_id')
        self.asf.write_u16(addr - self.asf.FLASH_BASE, myasv_vid)
        tc_addr = self._elf_symbol_addr(elf_path, 'wrapper_limit_max_pdiff_triggercycle_var_id')
        self.asf.write_u16(tc_addr - self.asf.FLASH_BASE, tc_vid)
        max_addr = self._elf_symbol_addr(elf_path, 'wrapper_limit_max_pdiff_asv_max_var_id')
        self.asf.write_u16(max_addr - self.asf.FLASH_BASE, max_vid)
        sens_addr = self._elf_symbol_addr(elf_path, 'wrapper_limit_max_pdiff_asv_sens_var_id')
        self.asf.write_u16(sens_addr - self.asf.FLASH_BASE, sens_vid)

        print("  my_asv enable: %s var_id=0x%04X label_str=0x%04X" %
              (myasv_var, myasv_vid, myasv_label))
        print("  my_asv max: %s var_id=0x%04X label_str=0x%04X" %
              (max_var, max_vid, max_label))
        print("  my_asv sens: %s var_id=0x%04X label_str=0x%04X" %
              (sens_var, sens_vid, sens_label))
        print("  my_asv trigger/cycle: %s var_id=0x%04X label_str=0x%04X" %
              (tc_var, tc_vid, tc_label))
        print("  VAuto wrapper toggle var_id=0x%04X at 0x%08X" % (myasv_vid, addr))
        print("  ASV Max var_id=0x%04X at 0x%08X" % (max_vid, max_addr))
        print("  ASV Sens var_id=0x%04X at 0x%08X" % (sens_vid, sens_addr))
        print("  trigger/cycle toggle var_id=0x%04X at 0x%08X" % (tc_vid, tc_addr))

    def custom_patch_settings_squarewave(self):
        """Expose the squarewave runtime switch and pass its var_id to the payload."""
        square_var = self.custom_claim_g8_var('RPF', 'squarewave_enable')
        square_label = self.redefine_fw_string(-1, {0: 'Square Wave'}, 'squarewave_label')
        square_dep = self.asf.find_var_table_index(4, 'RGT')

        self.redefine_g8_var(square_var, 0x0007, 0, square_dep, square_label, 1,
                             2, 0, 0x00000003, self.asf.str_id_off_on_base, 0)

        square_vid = self.asf.resolve_var_id(square_var)
        self.custom_menu_add('therapy', square_var, self.mop_bitmask('S', 'ST', 'T', 'PAC'))

        ver = self.asf.cdx_ver.replace('SX567-', '')
        elf_path = self._versioned_artifact_path('squarewave', 'elf', ver)
        if not os.path.exists(elf_path):
            raise ValueError("custom_patch_settings_squarewave: build/squarewave_%s.elf not found" % ver)
        enable_addr = self._elf_symbol_addr(elf_path, 'squarewave_enable_var_id')
        self.asf.write_u16(enable_addr - self.asf.FLASH_BASE, square_vid)

        print("  squarewave enable: %s var_id=0x%04X label_str=0x%04X" %
              (square_var, square_vid, square_label))
        print("  squarewave toggle var_id=0x%04X at 0x%08X" %
              (square_vid, enable_addr))

    def custom_patch_settings_collect_features(self):
        """Return active custom-settings feature functions."""
        features = []
        if self.wrapper_limit_max_pdiff_applied:
            features.append(self.custom_patch_settings_myasv)
        if self.squarewave_applied:
            features.append(self.custom_patch_settings_squarewave)
        return features

    def custom_patch_settings(self):
        """Orchestrate reclaim, feature registration, registry emit, and hook injection."""
        features = self.custom_patch_settings_collect_features()
        if not features:
            print("  custom_patch_settings: skipped (no active features)")
            return

        print("  Preparing custom patch settings")
        self.custom_patch_settings_init()
        if not self.custom_patch_settings_reclaim_reminders():
            return
        self.custom_build_string_pool()

        for feature in features:
            feature()

        self.custom_emit_registry()
        self.custom_patch_menu_hooks()

    @staticmethod
    def _print_resource_summary_line(label, items):
        text = "  %s: %d" % (label, len(items))
        if items:
            text += " (" + ", ".join(items) + ")"
        print(text)

    def print_custom_resource_summary(self):
        """Print reclaimed-resource state after all patch passes had a chance to consume it."""
        touched = (
            len(self.custom_g8_reclaimed) +
            len(self.custom_g4_reclaimed) +
            len(self.custom_reclaimed_string_candidates)
        )
        if not touched:
            return

        unused_g8 = []
        for name in self.custom_g8_pool:
            vid = self.asf.resolve_var_id(name)
            if vid not in self.custom_g8_claims:
                unused_g8.append(name)

        unused_g4 = []
        for name in self.custom_g4_pool:
            vid = self.asf.resolve_var_id(name)
            if vid not in self.custom_g4_claims:
                unused_g4.append(name)

        free_str_ids = ["0x%04X" % str_id for str_id in self.custom_string_pool]

        print("Custom resource summary:")
        self._print_resource_summary_line("unused reclaimed g[8] vars", unused_g8)
        self._print_resource_summary_line("unused reclaimed g[4] vars", unused_g4)
        self._print_resource_summary_line("free reclaimed str_id", free_str_ids)

    def _patch_or_verify(self, addr, expected, replacement, label):
        current_expected = bytes(self.asf.fw[addr:addr + len(expected)])
        if current_expected == expected:
            self.asf.patch(replacement, addr, clobber=True)
            return True

        current_replacement = bytes(self.asf.fw[addr:addr + len(replacement)])
        if current_replacement == replacement:
            return False

        raise ValueError("custom_patch_settings: unexpected %s bytes at 0x%X" % (label, addr))

    def custom_patch_settings_reclaim_reminders(self):
        """Disable stock Reminders behavior and reclaim its storage-backed vars."""
        sites_by_version = {
            'SX567-0401': {
                'reminders_tick': 0xec446,
                'reminder_menu_item': 0x62754,
                'reminder_menu_item_end': 0x62790,
                'reminder_menu': 0x63778,
                'reminder_menu_end': 0x639d4,
                'reclaimed_string_ids': (0x0048, 0x00B7, 0x00B8, 0x00B9, 0x00BA), # Reminders + four reminder message bodies
            },
            'SX567-0402': {
                'reminders_tick': 0xec6be,
                'reminder_menu_item': 0x62754,
                'reminder_menu_item_end': 0x62790,
                'reminder_menu': 0x63778,
                'reminder_menu_end': 0x639d4,
                'reclaimed_string_ids': (0x0048, 0x00B7, 0x00B8, 0x00B9, 0x00BA), # Reminders + four reminder message bodies
            },
        }
        sites = sites_by_version.get(self.asf.cdx_ver)
        if sites is None:
            print("  custom_patch_settings: skipped (unsupported CDX version %s)" % self.asf.cdx_ver)
            return False

        reminders_tick = sites['reminders_tick']
        reminder_menu_item = sites['reminder_menu_item']
        reminder_menu_item_end = sites['reminder_menu_item_end']
        reminder_menu = sites['reminder_menu']
        reminder_menu_end = sites['reminder_menu_end']

        self._patch_or_verify(reminders_tick, b'\x38\xb5\x04\x46', b'\x70\x47', 'reminder tick')

        item_reclaim = reminder_menu_item + 2
        item_reclaim_size = reminder_menu_item_end - item_reclaim
        if self._patch_or_verify(reminder_menu_item, b'\x08\x20\x01\xf0', b'\x1c\xe0', 'reminder menu item'):
            self.asf.fill_range(item_reclaim, item_reclaim_size, 0xff)
        for str_id in sites['reclaimed_string_ids']:
            self._custom_note_reclaimed_string_id(str_id)

        reclaim = reminder_menu + 6
        reclaim_size = reminder_menu_end - reclaim
        if self._patch_or_verify(reminder_menu, b'\x2c\x20\x00\xf0', b'\x00\x24\x6c\x67\x2a\xe1', 'reminder menu'):
            self.asf.fill_range(reclaim, reclaim_size, 0xff)

        self.custom_settings_registry_addr = reclaim
        self.custom_settings_registry_size = reclaim_size

        for var in ('RPO', 'RPH', 'RPF', 'RPW', 'RXM', 'RXH', 'RXF', 'RXW'):
            self.custom_reclaim_g8_var(var)
        for var in ('RDF', 'RDM', 'RDH', 'RDW', 'RCF', 'RCM', 'RCH', 'RCW'):
            self.custom_reclaim_g4_var(var)

        print("  disabled stock Reminders menu item at 0x%08X" %
              (self.asf.FLASH_BASE + reminder_menu_item))
        print("  reclaimed 0x%08X..0x%08X (%d bytes) padded with FF" %
              (self.asf.FLASH_BASE + item_reclaim,
               self.asf.FLASH_BASE + reminder_menu_item_end - 1,
               item_reclaim_size))
        print("  disabled stock Reminders page slot at 0x%08X" %
              (self.asf.FLASH_BASE + reminder_menu))
        print("  reclaimed 0x%08X..0x%08X (%d bytes) padded with FF" %
              (self.asf.FLASH_BASE + reclaim,
               self.asf.FLASH_BASE + reminder_menu_end - 1,
               reclaim_size))
        return True

    def bypass_startcheck(self):
        #Start-up check for CRC etc, bypass it to avoid (might not be needed)
        bid = self.asf.bid

        if bid.startswith('SX577-0200'):
            # AirSense / AirCurve variant
            self.asf.patch(b'\x01\x20\xc0\x46', 0x310e, clobber=True) # BLX
            self.asf.patch(b'\x00\x20\xc0\x46', 0x313e, clobber=True) # CCX
            self.asf.patch(b'\x00\x20\xc0\x46', 0x3130, clobber=True) # CDX
        elif bid.startswith('SX585-0200'):
            # Lumis
            self.asf.patch(b'\x01\x20\xc0\x46', 0x316e, clobber=True) # BLX
            self.asf.patch(b'\x00\x20\xc0\x46', 0x319e, clobber=True) # CCX
            self.asf.patch(b'\x00\x20\xc0\x46', 0x3190, clobber=True) # CDX
        else:
            raise IOError("Unknown bootloader version: '%s'" % bid)
        print("  BLX/CCX/CDX integrity checks bypassed")

    def bypass_psucheck(self):
        # power supply ID (adc_and_object_2826_stuff)
        if self.asf.bid.startswith('SX577-0200'):
            self.asf.patch(b'\x00\x20\x70\x47', 0x2882, clobber=True)
        else:
            print("  bypass_psucheck: skipped (unsupported bootloader version %s)" % self.asf.bid)
            
    def unlock_ui_limits(self):
        # patch min/max pressure limits to allow full range
        # Entry4 record layout: +0x0C = max (u32), +0x10 = min (u32)

        vars = [
            'IPC', # Set Pressure (CPAP)
            'MPA', # Max Pressure (AutoSet, APAP, AfH)
            'IPP', # IPAP (S, ST, T, PAC)
            'STP', # Start Pressure (CPAP)
            'MPI', # Min Pressure (AutoSet, APAP, AfH)
            'STU', # Start Pressure (AutoSet, APAP, AfH)
            'MNE', # Min EPAP (VAuto)
            'MXI', # Max IPAP (VAuto)
            'STV', # Start EPAP (VAuto)
            'EPP', # EPAP (S, ST)
            'EPS', # Start EPAP (S, ST, PAC)
            'EEP', # EPAP (ASV)
            'STE', # Start EPAP (ASV)
            'EAX', # Max EPAP (ASVAuto)
            'EAI', # Min EPAP (ASVAuto)
            'EAS', # Start EPAP (ASVAuto)
            'EPI', # EPAP (iVAPS)
            'IVS', # Start EPAP (iVAPS)
        ]

        for var in vars:
            addr = self.asf.find_var(var) + self.asf.G4_MAX
            # max=0x000005DC (1500) min=0x00000032 (50) scale=1/50
            self.asf.patch(b'\xdc\x05\x00\x00\x32\x00\x00\x00', addr, clobber=True)
        print("  %d pressure variables set to 1.0-30.0 cmH2O" % len(vars))

    def unlock_languages(self):
        """
            it would be best to read 7th pointer from globals table (global_var_0x6) and go to 7th var descriptor, like
            var_bitmask_addr = ((void **)0x08004108)[6] + 6*0x1c
            var_value_addr = $var_bitmask_addr + 8
            but hardcoded offset works for almost all firmwares...
        """
        addr = self.asf.find_var('LNC')
        # make variable read only to prevent overwriting with eeprom data
        self.asf.patch(b'\x06', addr, clobber=True)
        # 0x007fffff, except font-reserved bits jp (13,19) and cn (16,17).
        self.asf.patch(b'\xff\xdf\x74\x00', addr + 0x08, clobber=True)

    def extra_debug(self):
        # set config variable 0xc value to 4 == enable more debugging data on display
        # if you set it to \x0f it will enable four separate display pages of info in sleep report mode
        self.asf.patch(b'\x0e', self.asf.find_var('TSS') + self.asf.G6_DEFAULT, clobber=True)

    def extra_modes(self):
        # add more mode entries, set config 0x0 mask to all bits high
        # default is 0x3, which only enables mode 1 (CPAP) and 2 (AutoSet)
        # ---> This is the real magic <---
        self.asf.patch(b'\xff\xff', self.asf.find_var('MOP') + self.asf.G8_BITMASK, clobber=True)

    def unlock_option_masks(self):
        masks = {
            'TBT': 0x00000007,  # Tube: SlimLine, Standard, 3m
            'RMA': 0x00000007,  # Ramp: Off, On, Auto
        }
        for name, mask in masks.items():
            self.asf.patch(struct.pack('<I', mask),
                           self.asf.find_var(name) + self.asf.G8_BITMASK,
                           clobber=True)

    def asv_unlock_ps_range(self):
        # Disable the ASV and ASVAuto PS range check to allow Max PS < (Min PS + 5)
        # and remove the fixed ASV EPAP ceiling of MCP - 6.0 cmH2O.
        #
        # CDX code patches: zero the 0xfa (5.0 cmH2O) immediate in add.w/sub.w
        cdx_patches = {
            'SX567-0402': [
                (0x76bd6, b'\xa0\xf1\x00\x01'), # EEP max: MCP - 6.0 -> MCP             ; sub.w r1, r0, #0x12c -> #0x00
                (0x76c08, b'\x00'),             # MXS min: MNS + 5.0 -> MNS             ; add.w r1, r0, #0xfa -> #0x00
                (0x76c34, b'\x00'),             # MNS max: MCP - EEP - 5.0 -> MCP - EEP ; sub.w r1, r0, #0xfa -> #0x00
                (0x76cca, b'\x00'),             # AXS min: ANS + 5.0 -> ANS             ; add.w r1, r0, #0xfa -> #0x00
            ],
            'SX567-0401': [
                (0x76bd6, b'\xa0\xf1\x00\x01'),
                (0x76c08, b'\x00'),
                (0x76c34, b'\x00'),
                (0x76cca, b'\x00'),
            ],
            'SX567-0306': [
                (0x76bd6, b'\xa0\xf1\x00\x01'),
                (0x76c08, b'\x00'),
                (0x76c34, b'\x00'),
                (0x76cca, b'\x00'),
            ],
            'SX567-0305': [
                (0x76bda, b'\xa0\xf1\x00\x01'),
                (0x76c0c, b'\x00'),
                (0x76c38, b'\x00'),
                (0x76cce, b'\x00'),
            ],
            'SX567-0302': [
                (0x76462, b'\xa0\xf1\x00\x01'),
                (0x76494, b'\x00'),
                (0x764c0, b'\x00'),
                (0x76556, b'\x00'),
            ],
        }
        patches = cdx_patches.get(self.asf.cdx_ver)
        if patches:
            for addr, data in patches:
                self.asf.patch(data, addr, clobber=True)
        else:
            print("  asv_unlock_ps_range: CDX code patches skipped (unknown CDX version %s)" % self.asf.cdx_ver)

        # Pressure support vars use scale=1/50: 1250 = 25.0 cmH2O.
        for var in ('MNS', 'MXS', 'ANS', 'AXS'):
            self.asf.patch(b'\x00\x00\x00\x00', self.asf.find_var(var) + self.asf.G4_MIN, clobber=True)
            self.asf.patch(b'\xe2\x04\x00\x00', self.asf.find_var(var) + self.asf.G4_MAX, clobber=True)

    def gui_config (self):
        # enable editable options in clinical settings menu
        # by setting bit 0 (ACT) of the flags field at record +0x00

        vars = [
            # gui_create_menus->menu_floatvar_create
            'IPC', 'MPA', 'IPP', 'PHT',
            'EPR', 'STP', 'MPI', 'STU', 'MNE', 'MXI', 'SPT', 'STV', 'EPP', 'EPS', 'ITN', 'ITX', 'RRT', 'ITT',
            'EEP', 'MNS', 'MXS', 'STE', 'EAX', 'EAI', 'ANS', 'AXS', 'EAS', 'EPI', 'WPM', 'WPA', 'IBR', 'WMV', 'IVS',

            # gui_create_menus->menu_create_text_or_float
            'EBE', 'BRE', 'AFC', 'ALR', 'HME', 'EPA', 'EPX', 'EPT', 'VCS', 'VTS',
            'RSC', 'RST', 'CSR', 'CYI', 'TRI',

            # gui_create_menus->menu_create_item_type_0x29_maybe
            'MTT', 'ZAE', 'ZAM', 'ZAR', 'ZAZ', 'ZA1', 'ZA2', 'ZA3', 'ZAY', 'ZAS', 'CRD', 'ZAV', 'RCR',

            # gui_create_menus->gui_infobox_create
            'TGT', 'AAV', 'IER', 'IN5', 'ZMA', 'ITN', 'ITX',
        ]

        count = 0
        for var in vars:
            addr = self.asf.find_var(var)
            flags = self.asf.read_u8(addr)
            if not (flags & 1):
                self.asf.write_u8(addr, flags | 1)
                count += 1
        print("  %d/%d menu ACT flags set" % (count, len(vars)))

    def patch_defaults(self):
        # language (eng)
        self.asf.patch(b'\x00', self.asf.find_var('LAN') + self.asf.G8_DEFAULT, clobber=True)
        # press. units: 0=cmH2O 1=hPa
        self.asf.patch(b'\x00', self.asf.find_var('PRD') + self.asf.G8_DEFAULT, clobber=True)
        # mask: 0=Pillows 1=Full 2=Nasal 3=Pediatric
        self.asf.patch(b'\x00', self.asf.find_var('MSK') + self.asf.G8_DEFAULT, clobber=True)
        # tube: SlimLine, Standard, 3m
        self.asf.patch(b'\x00', self.asf.find_var('TBT') + self.asf.G8_DEFAULT, clobber=True)
        # Essentials: Plus, On
        self.asf.patch(b'\x00', self.asf.find_var('ACC') + self.asf.G8_DEFAULT, clobber=True)

    def patch_logos(self):

        #Change these to adjust logos, rest should work automatically.
        #NB - be sure of settings when saving file:
        #     'text' was exported with `Compressed, RLE4`
        #     'logo' was exported with `Compressed, RLE8`
        import image_conversion_example.example1_umbrella_logo_c as logo
        import image_conversion_example.example1_umbrella_text_c as text
        
        # Find somewhere to stash our stuff in the flash memory
        # NOTE: Pallet is in 32-bit, and need room for struct stuff around pallete
        pallete_addr = self.asf.find_flash_room(len(logo.pallete*4)+32, reserve=True) 
        pixels_addr = self.asf.find_flash_room(len(logo.pixels), reserve=True)
        
        # Find the location of the original wave
        setting_loc = self.asf.find_bytes([0xb8, 0x00, 0x54, 0x00, 0xb8, 0x00, 0x00, 0x00])
        
        asf.patch_image(setting_loc, pallete_addr, pixels_addr, logo)    
        
        # Find somewhere to stash our stuff in the flash memory
        # NOTE: Pallet is in 32-bit, and need room for struct stuff around pallete
        pallete_addr = self.asf.find_flash_room(len(text.pallete*4)+32, reserve=True) 
        pixels_addr = self.asf.find_flash_room(len(text.pixels), reserve=True)
        
        # Find the location of the original text
        setting_loc = self.asf.find_bytes([0xB8, 0x00, 0x32, 0x00, 0x5c, 0x00, 0x00])
        
        self.asf.patch_image(setting_loc, pallete_addr, pixels_addr, text)

    def patch_uart3_monitor(self):

        irq_offset, irq_bin = self.asf.prepare_bin("../serial_monitor/monitor_irq")
        
        # Need to rebuild if location changes - for now just fix it, check we've got room
        # before doing it.
        #
        # If following fails, these two lines will figure out where there is room again
        # irq_location = asf.find_flash_room(len(data)*2)
        # print("Suggest to place at %x"%irq_location)
        irq_location = 0xC600
        asf.patch(irq_bin, irq_location, checkempty=True)
        
        init_offset, init_bin = self.asf.prepare_bin("../serial_monitor/monitor_init")
        if init_offset != 0:
            raise ValueError("Nonsense - no other function!?")
        
        #Init location
        init_location = self.asf.find_bytes([0x70, 0xb5, 0x84, 0xb0, 0x04, 0x46, 00, 0xf0])
        if (init_location != 0xC339A):
            raise ValueError("oops.... init function location is fixed in FW build")
        self.asf.patch(init_bin, init_location, clobber=True)
        
        #Entry is not at start of file sometimes in this file?
        print("IRQ has offset of 0x%x (dealt with)"%irq_offset)
        irq_location += irq_offset
        
        # IRQ vector - at fixed location 0x080402DC so don't need to worry about
        # this moving. Address needs to be +1 for normal code jump location.
        irq_location_packed = struct.pack("<I", 0x08000000 + irq_location + 1)
        self.asf.patch(irq_location_packed, 0x402dc, clobber=True)
        
    def _load_versioned_bin(self, name):
        """Load a per-version binary from build/. Returns (data, ver) or (None, ver)."""
        ver = self.asf.cdx_ver.replace('SX567-', '')
        bin_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                '..', 'build', '%s_%s.bin' % (name, ver))
        if not os.path.exists(bin_path):
            print("  %s: build/%s_%s.bin not found (run make)" % (name, name, ver))
            return None, ver
        with open(bin_path, 'rb') as f:
            return f.read(), ver

    def _elf_symbol_addr(self, elf_path, symbol):
        """Return linked flash address of symbol from an ELF file."""
        try:
            out = subprocess.check_output(
                ['arm-none-eabi-nm', elf_path],
                stderr=subprocess.DEVNULL,
                universal_newlines=True)
        except (OSError, subprocess.CalledProcessError) as exc:
            raise ValueError("failed to read symbols from %s: %s" % (elf_path, exc))

        for line in out.splitlines():
            fields = line.split()
            if len(fields) >= 3 and fields[2] == symbol:
                return int(fields[0], 16)
        raise ValueError("symbol %s not found in %s" % (symbol, elf_path))

    def _patch_pointer(self, data, offset, fptr_offset, flash_base=0x08000000):
        """Inject binary at offset and write Thumb pointer to fptr_offset."""
        self.asf.patch(data, offset, checkempty=True)
        thumb_ptr = struct.pack('<I', flash_base + offset + 1)
        self.asf.patch(thumb_ptr, fptr_offset, clobber=True)

    def patch_common_code(self):
        """Inject common_code shared library (required by graph, squarewave, etc.)"""
        data, ver = self._load_versioned_bin('common_code')
        if data is None:
            return
        self.asf.patch(data, 0xfd800, checkempty=True)
        print("  common_code: %dB at 0xFD800" % len(data))

    def patch_graph(self):
        """Add special graph module"""
        data, ver = self._load_versioned_bin('graph')
        if data is None:
            return
        FPTR = {'0401': 0xf9c88, '0402': 0xf9f00}
        fptr = FPTR.get(ver)
        if fptr is None:
            print("  patch_graph: skipped (unsupported CDX version %s)" % self.asf.cdx_ver)
            return
        self._patch_pointer(data, 0xfd000, fptr)
        print("  graph: %dB at 0xFD000" % len(data))

    def patch_squarewave(self):
        """Add squarewave pressure mode"""
        code_off = 0xfd400
        data, ver = self._load_versioned_bin('squarewave')
        if data is None:
            return
        FPTR = {'0401': 0xf9778, '0402': 0xf99f0}
        fptr = FPTR.get(ver)
        if fptr is None:
            print("  patch_squarewave: skipped (unsupported CDX version %s)" % self.asf.cdx_ver)
            return
        elf_path = self._versioned_artifact_path('squarewave', 'elf', ver)
        if not os.path.exists(elf_path):
            raise ValueError("patch_squarewave: build/squarewave_%s.elf not found" % ver)
        original_slot = self._elf_symbol_addr(elf_path, 'squarewave_original_handler')
        payload_thumb = self.asf.FLASH_BASE + code_off + 1
        original = self.asf.read_u32(fptr)
        if original == payload_thumb:
            original = self.asf.read_u32(original_slot - self.asf.FLASH_BASE)
        self._patch_pointer(data, code_off, fptr)
        self.asf.write_u32(original_slot - self.asf.FLASH_BASE, original)
        self.squarewave_applied = True
        print("  squarewave: %dB at 0x%05X" % (len(data), code_off))
        print("  original handler: 0x%08X -> ABI 0x%08X" % (original, original_slot))

    def patch_asv_task_wrapper(self):
        """Suppress ASV backup breathing rate"""
        data, ver = self._load_versioned_bin('asv_task_wrapper')
        if data is None:
            return
        FPTR = {'0401': 0xf44e0, '0306': 0xf44e0, '0402': 0xf4758}
        fptr = FPTR.get(ver)
        if fptr is None:
            print("  patch_asv_task_wrapper: skipped (unsupported CDX version %s)" % self.asf.cdx_ver)
            return
        self._patch_pointer(data, 0xfd700, fptr)
        print("  asv_task_wrapper: %dB at 0xFD700" % len(data))

    def patch_wrapper_limit_max_pdiff(self):
        """Add VAuto/ASV pressure shaping wrapper"""
        data, ver = self._load_versioned_bin('wrapper_limit_max_pdiff')
        if data is None:
            return
        FPTR = {'0401': 0xf93d0, '0402': 0xf9648}
        fptr = FPTR.get(ver)
        if fptr is None:
            print("  patch_wrapper_limit_max_pdiff: skipped (unsupported CDX version %s)" % self.asf.cdx_ver)
            return
        self._patch_pointer(data, 0xff000, fptr)
        self.wrapper_limit_max_pdiff_applied = True
        print("  limit_max_pdiff: %dB at 0xFF000" % len(data))

    def patch_lcd_ili9325(self):
        """Universal ILI9325/ILI9328 + ILI9341 LCD driver"""
        ver = self.asf.cdx_ver.replace('SX567-', '')
        BL_OFF_MAP = {'0401': 0x7C030, '0402': 0x7C030}
        bl_off = BL_OFF_MAP.get(ver)
        if bl_off is None:
            print("  patch_lcd_ili9325: skipped (unsupported CDX version %s)" % self.asf.cdx_ver)
            return
        expected_bl = b'\xFF\xF7\x7A\xFE'
        if bytes(self.asf.fw[bl_off:bl_off+4]) != expected_bl:
            print("  patch_lcd_ili9325: unexpected bytes at BL 0x%X" % bl_off)
            return
        data, ver = self._load_versioned_bin('s10_lcd_ili9325')
        if data is None:
            return
        lcd_offset = 0xFF800
        self.asf.patch(data, lcd_offset, checkempty=True)
        print("  lcd_ili9325: %dB at 0x%X" % (len(data), lcd_offset))
        bl_bytes = self._encode_thumb_bl(bl_off, 0x08000000 + lcd_offset + 1)
        self.asf.patch(bl_bytes, bl_off, clobber=True)

    def _encode_thumb_bl(self, src_off, dst_addr):
        """Encode a Thumb BL instruction from file offset to absolute address."""
        src = src_off + 0x08000004
        offset = dst_addr - src
        S = 1 if offset < 0 else 0
        if offset < 0:
            offset += (1 << 25)
        I1 = (offset >> 23) & 1
        I2 = (offset >> 22) & 1
        imm10 = (offset >> 12) & 0x3FF
        imm11 = (offset >> 1) & 0x7FF
        J1 = (~(I1 ^ S)) & 1
        J2 = (~(I2 ^ S)) & 1
        hw1 = 0xF000 | (S << 10) | imm10
        hw2 = 0xD000 | (J1 << 13) | (J2 << 11) | imm11
        return struct.pack('<HH', hw1, hw2)

    def patch_backlight_adapt(self):
        """improved backlight response to ambient light"""
        BACKLIGHT_OFFSET = 0xFEC00
        data, ver = self._load_versioned_bin('backlight_adapt')
        if data is None:
            return

        if ver not in ('0401', '0402'):
            print("  skipped (unsupported version %s)" % ver)
            return

        # signature: bl A1D0; mov r0,r4; bl A2A4; movs r5,#0
        try:
            sig_off = self.asf.find_bytes(bytes.fromhex('00F0D5F8204600F03CF90025'))
        except ValueError:
            print("  tick signature not found")
            return

        hook_off = sig_off + 6
        expected_bl = b'\x00\xF0\x3C\xF9'
        if bytes(self.asf.fw[hook_off:hook_off+4]) != expected_bl:
            print("  unexpected bytes at hook site 0x%X, already patched?" % hook_off)
            return

        self.asf.patch(data, BACKLIGHT_OFFSET, checkempty=True)

        # NOP the beq that skips ASR->ASF averaging
        gate_off = sig_off + 0x1C8
        if bytes(self.asf.fw[gate_off:gate_off+2]) == b'\x4F\xD0':
            self.asf.patch(b'\x00\xBF', gate_off, clobber=True)

        # redirect bl backlight_state_machine to our payload
        cave_addr = BACKLIGHT_OFFSET + 0x08000000
        bl_bytes = self._encode_thumb_bl(hook_off, cave_addr)
        self.asf.patch(bl_bytes, hook_off, clobber=True)

        # tune defaults
        self.asf.patch(b'\x20', self.asf.find_var('LBL') + self.asf.G4_DEFAULT, clobber=True)  # LBL = 32
        self.asf.patch(b'\x50', self.asf.find_var('LBH') + self.asf.G4_DEFAULT, clobber=True)  # LBH = 80
        self.asf.patch(struct.pack('<I', 590), self.asf.find_var('ATH') + self.asf.G4_DEFAULT, clobber=True)  # ATH = 590

        print("  backlight_adapt: %dB at 0x%X" % (len(data), BACKLIGHT_OFFSET))

    def patch_breath(self):
        """Add breath routine to allow full control"""
        f = open("../breath.bin", "rb")
        fw = f.read()
        f.close()
        
        self.asf.patch(fw, 0xBB734, clobber=True)


    def patch_vid_spoof(self):
        """Register MOP callback handler to dynamically set VID per therapy mode."""
        ver = self.asf.cdx_ver.replace('SX567-', '')
        bin_path = self._versioned_artifact_path('vid_spoof', 'bin', ver)
        elf_path = self._versioned_artifact_path('vid_spoof', 'elf', ver)
        if not os.path.exists(bin_path):
            print("  patch_vid_spoof: build/vid_spoof_%s.bin not found (run make)" % ver)
            return
        if not os.path.exists(elf_path):
            raise ValueError("patch_vid_spoof: build/vid_spoof_%s.elf not found" % ver)
        with open(bin_path, 'rb') as f:
            data = f.read()
        if len(data) > self.VID_SPOOF_BUDGET:
            raise ValueError(
                "patch_vid_spoof: %s is %dB, exceeds %dB budget" %
                (bin_path, len(data), self.VID_SPOOF_BUDGET))
        budget = self.asf.fw[self.VID_SPOOF_OFF:self.VID_SPOOF_OFF + self.VID_SPOOF_BUDGET]
        if budget != [0xff] * self.VID_SPOOF_BUDGET:
            raise ValueError("patch_vid_spoof: payload area 0x%X is not empty" % self.VID_SPOOF_OFF)

        self.asf.patch(data, self.VID_SPOOF_OFF, checkempty=True)
        print("  vid_spoof: build/vid_spoof_%s.bin (%dB) at 0x%08X" %
              (ver, len(data), self.asf.FLASH_BASE + self.VID_SPOOF_OFF))
        handler = self._elf_symbol_addr(elf_path, 'vid_spoof_apply_current_mop')
        self.mop_callback_register_handler(handler, 'vid_spoof')

    def custom_palette(self):
        """Patch custom color palette."""
        try:
            base = self.asf.find_bytes(bytes.fromhex('286031BD61020000FFFFFF0096969600'))
        except ValueError:
            print("  custom_palette: palette signature not found")
            return
        base += 8

        self.asf.patch(b'\xCC\x33\x00\x00', base + 0x24, clobber=True)

        for off in (0x00, 0x1C, 0x28, 0x40, 0x44, 0x48, 0x54, 0x70, 0x7C, 0x94, 0x98, 0x9C):
            self.asf.patch(b'\xFF\xBB\x44\x00', base + off, clobber=True)

        for off in (0x04, 0x0C, 0x58, 0x60, 0x74):
            self.asf.patch(b'\x96\x48\x48\x00', base + off, clobber=True)

        for off in (0x08, 0x5C):
            self.asf.patch(b'\x64\x32\x32\x00', base + off, clobber=True)

        for off in (0x10, 0x14, 0x30, 0x4C, 0x64, 0x68, 0x84, 0xA0):
            self.asf.patch(b'\x40\x20\x20\x00', base + off, clobber=True)

        for off in (0x18, 0x34, 0x50, 0x6C, 0x88, 0xA4):
            self.asf.patch(b'\x08\x00\x08\x00', base + off, clobber=True)

        print("  custom_palette: palette at 0x%X" % base)


    def patch_past_date(self):
        """Allow setting past date in menu and UART"""
        # date direction check: cmp r0,r5 -> cmp r0,r0
        off = self.asf.find_bytes(bytes.fromhex('0098a8428041c043c00f05b030bd'))
        self.asf.patch(b'\x80', addr=off + 2, clobber=True)

    def motor_nagscreen(self):
        """Remove "Motor life exceeded" nag screen"""
        try:
            self.asf.patch([0x0e, 0x49, 0x88, 0x42, 0x05, 0xe0, 0x03, 0x21, 0x0f, 0x20], dataseq=[0x0e, 0x49, 0x88, 0x42, 0x05, 0xdb, 0x03, 0x21, 0x0f, 0x20], clobber=True)
            print("  BLT bypass patched")
        except ValueError:
            # fallback: find and patch runtime threshold
            try:
                self.asf.patch(b'\xFF\xFF\xFF\x7F', dataseq=[0xC0, 0x00, 0xB3, 0x04], clobber=True)
                print("  threshold set to max")
            except ValueError:
                print("  WARN: neither patch location found!")

    def patch_edf_merge(self):
        """Merge universal EDF signal superset into CCX"""
        try:
            from edf_ccx_merge import patch_edf_merge
        except ImportError:
            script_dir = os.path.dirname(os.path.abspath(__file__))
            sys.path.insert(0, script_dir)
            from edf_ccx_merge import patch_edf_merge

        buf = io.StringIO()
        old_stdout = sys.stdout
        sys.stdout = buf
        try:
            patches = patch_edf_merge(self.asf, force=True)
        finally:
            sys.stdout = old_stdout
        summary = buf.getvalue().strip()
        if summary:
            print("  %s" % summary)

            
def str2bool(v):
    if isinstance(v, bool):
       return v
    if v.lower() in ('yes', 'true', 't', 'y', '1'):
        return True
    elif v.lower() in ('no', 'false', 'f', 'n', '0'):
        return False
    else:
        raise argparse.ArgumentTypeError('Boolean value expected.')

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Patch Airsense Firmware with various updates.')
    parser.add_argument('INFILE', help="Input original binary file")
    parser.add_argument('OUTFILE', help="Output patched file")
    
    parser.add_argument('OPERATION', help="Operation to perform", choices=['INFO', 'PATCH'])
    
    patch_list_yn = [
        {'arg':"patch-bypass-start",    'desc':"Bypass checks that block start-up.",                    'default':True,  'function':'bypass_startcheck'},
        {'arg':"patch-bypass-psuid",    'desc':"Bypass Power Supply check at start-up.",                'default':True,  'function':'bypass_psucheck'},
        {'arg':"patch-unlock-uilimits", 'desc':"Unlock higher UI limits.",                              'default':True,  'function':'unlock_ui_limits'},
        {'arg':"patch-unlock-languages",'desc':"Unlock all built-in languages",                         'default':True,  'function':'unlock_languages'},
        {'arg':"patch-extra-debug",     'desc':"Add extra debug to display.",                           'default':True,  'function':'extra_debug'},
        {'arg':"patch-extra-modes",     'desc':"Add all modes.",                                        'default':True,  'function':'extra_modes'},
        {'arg':"patch-unlock-options",  'desc':"Unlock additional enum option masks.",                  'default':True,  'function':'unlock_option_masks'},
        {'arg':"patch-gui-config",      'desc':"Enable all of the editable options in the settings menu.",
                                                                                                        'default':True,  'function':'gui_config'},
        {'arg':"patch-asv-ps-range",    'desc':"Unlock ASV/ASVAuto pressure constraints.",              'default':True,  'function':'asv_unlock_ps_range'},
        {'arg':"patch-defaults",        'desc':"Change firmware defaults.",                             'default':True,  'function':'patch_defaults'},
        {'arg':"patch-logos",           'desc':"Change start-up logos.",                                'default':False, 'function':'patch_logos'},
        {'arg':"patch-fw-serialmonitor",'desc':"Add monitor binary running on USART3 accessory port.",  'default':False, 'function':'patch_uart3_monitor'},
        {'arg':"patch-fw-breath",       'desc':"Add breath binary to allow direct pressure control.",   'default':False, 'function':'patch_breath'},
        {'arg':"patch-fw-common-code",  'desc':"Inject shared code library (required by graph, squarewave, etc.).", 'default':False, 'function':'patch_common_code'},
        {'arg':"patch-fw-graph",        'desc':"Add graph binary to allow graphing of pressures.",      'default':False, 'function':'patch_graph'},
        {'arg':"patch-fw-squarewave",   'desc':"Add squarewave pressure mode.",                         'default':False, 'function':'patch_squarewave'},
        {'arg':"patch-fw-asv-wrapper",  'desc':"Suppress ASV backup breathing rate.",                   'default':False, 'function':'patch_asv_task_wrapper'},
        {'arg':"patch-fw-vauto-wrapper",'desc':"Add VAuto/ASV pressure shaping wrapper.",               'default':False, 'function':'patch_wrapper_limit_max_pdiff'},
        {'arg':"patch-custom-settings", 'desc':"Expose settings for injected custom patch features.",
                                                                                                        'default':True,  'function':'custom_patch_settings'},
        {'arg':"patch-fw-vidspoof",     'desc':"Register MOP callback handler to dynamically set VID per therapy mode.", 'default':True, 'function':'patch_vid_spoof'},
        {'arg':"patch-custom-palette",  'desc':"Patch custom color palette.",
                                                                                                        'default':True,  'function':'custom_palette'},
        {'arg':"patch-fw-lcd",          'desc':"Universal ILI9325/ILI9328 LCD driver.",                 'default':False, 'function':'patch_lcd_ili9325'},
        {'arg':"patch-fw-backlight",    'desc':"Improved backlight adaptation to ambient light.",       'default':True,  'function':'patch_backlight_adapt'},
        {'arg':"patch-past-date",       'desc':"Allow setting past date in menu and UART.",             'default':True,  'function':'patch_past_date'},
        {'arg':"patch-motor-nagscreen", 'desc':"Remove \"Motor life exceeded\" nag screen",             'default':True,  'function':'motor_nagscreen'},
        {'arg':"patch-edf-merge",       'desc':"Merge universal EDF signal superset into CCX.",         'default':True,  'function':'patch_edf_merge'},
    ]
    
    for arg in patch_list_yn:
        if arg['default'] == True:
            choices = ['Y', 'n']
        else:
            choices = ['y', 'N']
        parser.add_argument("--"+arg['arg'], help=arg['desc'], default=arg['default'], choices=choices)
    
    parser.add_argument("--overwrite", action="store_true", help="Overwrite output file if it exists already.")
    parser.add_argument("--force-deprecated", action="store_true", help="Apply deprecated patches (you know what you're doing).")
    parser.add_argument("-v", "--verbose", action="store_true", help="Show per-patch byte-level details.")
    
    args = parser.parse_args()

    #Open existing file
    b = open(args.INFILE, "rb")
    asf = ASFirmware(b)
    b.close()
    asf.verbose = args.verbose

    if args.OPERATION == "PATCH":

        patches = ASFirmwarePatches(asf)
        
        for patch in patch_list_yn:
            if str2bool(getattr(args, patch['arg'].replace("-","_"))):
                if patch.get('deprecated'):
                    if not args.force_deprecated:
                        print("SKIP: %s -- %s" % (patch['desc'], patch['deprecated']))
                        continue
                    print("WARN: applying deprecated patch: " + patch['desc'])
                print("PATCH: " + patch['desc'])
                getattr(patches, patch['function'])()

        patches.patch_mop_callback_dispatcher()
        asf.fix_crcs()
        asf.write_output(args.OUTFILE, args.overwrite)
        patches.print_custom_resource_summary()

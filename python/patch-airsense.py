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

    def __init__(self, file, validate_crc=True):
        self.fw = file.read()
        self.fw = list(self.fw)
        self.crcfunc = crc_func = crcmod.predefined.mkCrcFun('crc-ccitt-false')
        self.var_by_name = None
        self.var_tables = None
        
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
        
    def __init__(self, asf):
        self.asf = asf

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
        G4_MAX = 0x0C

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
            addr = self.asf.find_var(var) + G4_MAX
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
        G6_DEFAULT = 0x08
        self.asf.patch(b'\x04', self.asf.find_var('TSS') + G6_DEFAULT, clobber=True)

    def extra_modes(self):
        # add more mode entries, set config 0x0 mask to all bits high
        # default is 0x3, which only enables mode 1 (CPAP) and 2 (AutoSet)
        # ---> This is the real magic <---
        G8_BITMASK = 0x0C
        self.asf.patch(b'\xff\xff', self.asf.find_var('MOP') + G8_BITMASK, clobber=True)

    def unlock_option_masks(self):
        G8_BITMASK = 0x0C
        masks = {
            'TBT': 0x00000007,  # Tube: SlimLine, Standard, 3m
            'RMA': 0x00000007,  # Ramp: Off, On, Auto
        }
        for name, mask in masks.items():
            self.asf.patch(struct.pack('<I', mask),
                           self.asf.find_var(name) + G8_BITMASK,
                           clobber=True)

    def extra_menu(self):
        #try enabling extra menu items
        cdx_patches = {
            'SX567-0402': [(0x66470, b'\x01\x20')],
            'SX567-0401': [(0x66470, b'\x01\x20')],
            'SX567-0306': [(0x66470, b'\x01\x20')],
            'SX567-0305': [(0x66470, b'\x01\x20')],
        }
        patches = cdx_patches.get(self.asf.cdx_ver)
        if patches:
            for addr, data in patches:
                self.asf.patch(data, addr, clobber=True)
        else:
            print("  extra_menu: skipped (unknown CDX version %s)" % self.asf.cdx_ver)

    
    def all_menu(self):
        # If you want all menu items to always be visible, let this section run
        cdx_patches = {
            'SX567-0402': [
                (0x6e502, b'\x01\x20'),  # force status bit 5 always on - always editable
                (0x6e4c4, b'\x01\x20'),  # force status bit 4 always on - visible regardless of mode
            ],
            'SX567-0401': [
                (0x6e502, b'\x01\x20'),
                (0x6e4c4, b'\x01\x20'),
            ],
            'SX567-0306': [
                (0x6e502, b'\x01\x20'),
                (0x6e4c4, b'\x01\x20'),
            ],
            'SX567-0305': [
                (0x6e502, b'\x01\x20'),
                (0x6e4c4, b'\x01\x20'),
            ],
        }
        patches = cdx_patches.get(self.asf.cdx_ver)
        if patches:
            for addr, data in patches:
                self.asf.patch(data, addr, clobber=True)
        else:
            print("  all_menu: skipped (unknown CDX version %s)" % self.asf.cdx_ver)

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
        G4_MAX = 0x0C
        G4_MIN = 0x10
        for var in ('MNS', 'MXS', 'ANS', 'AXS'):
            self.asf.patch(b'\x00\x00\x00\x00', self.asf.find_var(var) + G4_MIN, clobber=True)
            self.asf.patch(b'\xe2\x04\x00\x00', self.asf.find_var(var) + G4_MAX, clobber=True)

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
        self.asf.patch(b'\x00', self.asf.find_var('LAN') + 0x08, clobber=True)
        # press. units: 0=cmH2O 1=hPa
        self.asf.patch(b'\x00', self.asf.find_var('PRD') + 0x08, clobber=True)
        # mask: 0=Pillows 1=Full 2=Nasal 3=Pediatric
        self.asf.patch(b'\x00', self.asf.find_var('MSK') + 0x08, clobber=True)
        # tube: SlimLine, Standard, 3m
        self.asf.patch(b'\x00', self.asf.find_var('TBT') + 0x08, clobber=True)
        # Essentials: Plus, On
        self.asf.patch(b'\x00', self.asf.find_var('ACC') + 0x08, clobber=True)

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
        data, ver = self._load_versioned_bin('squarewave')
        if data is None:
            return
        FPTR = {'0401': 0xf9778, '0402': 0xf99f0}
        fptr = FPTR.get(ver)
        if fptr is None:
            print("  patch_squarewave: skipped (unsupported CDX version %s)" % self.asf.cdx_ver)
            return
        self._patch_pointer(data, 0xfd400, fptr)
        print("  squarewave: %dB at 0xFD400" % len(data))

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
        G4_DEFAULT = 0x08
        self.asf.patch(b'\x20', self.asf.find_var('LBL') + G4_DEFAULT, clobber=True)  # LBL = 32
        self.asf.patch(b'\x50', self.asf.find_var('LBH') + G4_DEFAULT, clobber=True)  # LBH = 80
        self.asf.patch(struct.pack('<I', 590), self.asf.find_var('ATH') + G4_DEFAULT, clobber=True)  # ATH = 590

        print("  backlight_adapt: %dB at 0x%X" % (len(data), BACKLIGHT_OFFSET))

    def patch_breath(self):
        """Add breath routine to allow full control"""
        f = open("../breath.bin", "rb")
        fw = f.read()
        f.close()
        
        self.asf.patch(fw, 0xBB734, clobber=True)


    def patch_vid_spoof(self):
        """Hook MOP writeback to dynamically set VID per therapy mode"""
        VID_SPOOF_OFFSET = 0xFCFA0
        VTABLE_ENTRIES = {
            '0402': (0xF1744, b'\x1d\xa5\x06\x08'),
            '0401': (0xF14CC, b'\x1d\xa5\x06\x08'),
            '0306': (0xF126C, b'\x1d\xa5\x06\x08'),
            '0305': (0xF1350, b'\x19\xa5\x06\x08'),
            '0302': (0xF0B54, b'\xf5\x9d\x06\x08'),
        }
        data, ver = self._load_versioned_bin('vid_spoof')
        if data is None:
            return
        info = VTABLE_ENTRIES.get(ver)
        if info is None:
            print("  patch_vid_spoof: skipped (unsupported CDX version %s)" % self.asf.cdx_ver)
            return
        vtable_entry, expected_vt = info
        if bytes(self.asf.fw[vtable_entry:vtable_entry+4]) != expected_vt:
            print("  patch_vid_spoof: unexpected bytes at vtable entry, already patched?")
            return
        self._patch_pointer(data, VID_SPOOF_OFFSET, vtable_entry)
        print("  %dB payload at 0x%X, vtable 0x%X" % (len(data), VID_SPOOF_OFFSET, vtable_entry))


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
        {'arg':"patch-extra-menu",      'desc':"Try enabling extra menu items.",                        'default':False,  'function':'extra_menu',
                                        'deprecated': "gui_config now sets ACT flags on all menu variables. "
                                                      "If you believe some items are still missing, please file a bug report. "
                                                      "Use --force-deprecated to apply anyway."},
        {'arg':"patch-all-menu",        'desc':"All menu items will always be visible.",                'default':False, 'function':'all_menu',
                                        'deprecated': "gui_config now sets ACT flags on all menu variables. "
                                                      "If you believe some items are still missing, please file a bug report. "
                                                      "Use --force-deprecated to apply anyway."},
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
        {'arg':"patch-fw-vidspoof",     'desc':"Hook MOP write to dynamically set VID per therapy mode.", 'default':True, 'function':'patch_vid_spoof'},
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

        asf.fix_crcs()
        asf.write_output(args.OUTFILE, args.overwrite)

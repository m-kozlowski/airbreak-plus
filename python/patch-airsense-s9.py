#!/usr/bin/env python3
"""Patch S9 firmware using the same CLI/config conventions as Air10/Air11."""
from __future__ import annotations
import argparse
import binascii
from contextlib import redirect_stdout, redirect_stderr
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import struct
import sys

from lib.s9_firmware import S9Firmware, write_output
from lib.patch_config import parse_patch_args
from lib import patch_options
from lib.compiled_payload import elf_symbol_address, elf_text_address, elf_binary_data

REPO = Path(__file__).resolve().parents[1]

PRESSURES = 'IPC IPP EPP EEP EPS MPA MPI MNE MXI STP STE STU STV EAX EAI EAS EPI IVS'.split()

PS = 'MNS MXS ANS AXS SPT'.split()

CLINICAL = set(PRESSURES + PS + '''PHT PHI EPR EBE BRE AFC ALR LLA ABF INH HME EPA EPX EPT VCS VTS
RSC RST CSR ITN ITX RRT ITT WPM WPA IBR WMV
ZAE ZAI ZAM ZAR ZAS ZAT ZAV ZAY ZAZ ZA1 ZA2 ZA3 ZMA'''.split())
STATS = '''AHC HYC AIC CAC OAC UAC AHI HIS AIS CLI OPI UAI FFL FLP
LK9 LKM LMX MSP PE9 PEA PEM PM9 PMA PT9 PTA PTM'''.split()

REPORT_SETTINGS = 'AQD ARD CRD LRD LRS SRD TRD'.split()

DEFAULTS = (
    ('MOP', 1),  # Therapy mode: AutoSet
    ('PRD', 0),  # Pressure units: cmH2O
    ('MSK', 0),  # Mask type: Pillows
    ('TBT', 0),  # Tube type: SlimLine
    ('MTP', 1),  # Menu access: Full
    ('CCA', 2),  # Climate control: Patient
    ('EPA', 4),  # EPR level: Patient
    ('LLA', 2),  # Leak alert: Patient
    ('SSA', 2),  # SmartStart: Patient
)

MOTOR = {'SX474-0907': 0x45A14, 'SX474-0912': 0x46580, 'SX474-1201': 0x470A0,
         'SX474-1203': 0x47168, 'SX474-1301': 0x4CC88}

LCD = {'SX474-1201': (0x80ADC, 0x44670, 0x4464A),
       'SX474-1203': (0x80EC8, 0x45290, 0x4526A),
       'SX474-1301': (0x9A010, 0x52A18, 0x529F2)}

# Dynamic setting-bound helpers. These sites remove the stock 5 cmH2O
# MinPS/MaxPS separation and the fixed EPAP ceiling of MCP - 6 cmH2O.
# The total-pressure relationship MaxPS <= MCP - EPAP remains in place.
PS_CONSTRAINTS = {
    'SX474-0907': (0x8C0C4, 0x8C10A, 0x8C12C),
    'SX474-0912': (0x8DA3C, 0x8DA82, 0x8DAA4),
    'SX474-1201': (0x8E638, 0x8E67E, 0x8E6A0),
    'SX474-1203': (0x8EA24, 0x8EA6A, 0x8EA8C),
    'SX474-1301': (0x64028, 0x64064, 0x64092),
}


@dataclass(frozen=True)
class PatchOutcome:
    status: str = 'OK'
    summary: str = ''

    @classmethod
    def ok(cls, summary=''):
        return cls('OK', summary)

    @classmethod
    def skip(cls, summary):
        return cls('SKIP', summary)


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


PATCH_OPTIONS = patch_options.load('s9')


class S9Patcher:
    def __init__(self, firmware):
        self.fw = firmware
        self.data = bytearray(firmware.fl.data)
        self.details = []

    def checked(self, offset, original, replacement):
        current = bytes(self.data[offset:offset + len(original)])
        if len(original) != len(replacement) or current not in (original, replacement):
            raise ValueError(f'unexpected bytes at 0x{offset:05X}: {current.hex()}')
        self.write(offset, replacement)

    def write(self, offset, value):
        if offset < 0 or offset + len(value) > len(self.data):
            raise ValueError('patch exceeds image bounds')
        if self.data[offset:offset + len(value)] != value:
            self.details.append(f'0x{offset:05X}: {self.data[offset:offset+len(value)].hex()} -> {value.hex()}')
            self.data[offset:offset + len(value)] = value

    def descriptor(self, name, kind):
        rec = self.fw.resolve(name)
        if rec.kind != kind:
            raise ValueError(f'{name}: expected {kind}, found {rec.kind}')
        if kind == 'setting' and self.fw.records[rec.idx].class_byte & 31 not in (1, 2, 4, 8, 16):
            raise ValueError(f'{name}: unsupported setting class')
        return rec

    def tamper(self):
        sites = ((0x49A, '00f07dfe'), (0x4AA, '00f075fe'), (0x1030, '00f0b2f8'))
        if self.fw.bid == 'SX525-0400':
            sites = ((0x49E, '00f081fe'), (0x4AE, '00f079fe'), (0x103C, '00f0b2f8'))
        for off, expected in sites:
            self.checked(off, bytes.fromhex(expected), bytes.fromhex('00200020'))
        return PatchOutcome.ok('Integrity sites verified (original or already patched).')

    def extra_modes(self):
        rec = self.descriptor('MOP', 'setting')
        count = rec.option_count
        expected = 11 if self.fw.cdx_version == 'SX474-1301' else 8
        if count != expected or not 0 <= rec.default < count:
            raise ValueError('MOP: invalid declared option count')
        self.write(rec.off + 24, struct.pack('<I', (1 << count) - 1))
        return PatchOutcome.ok(f'{count} declared mode options enabled.')

    def respiratory_events(self):
        event_record = self.fw.respiratory_record_offset()
        cen = self.descriptor('CEN', 'enum')
        if cen.option_count != 2 or cen.default not in (0, 1) or cen.mask != 3:
            raise ValueError('unexpected CEN descriptor')
        self.unlock_options('AET', 'enum')
        self.write(cen.off, b'\x01')
        for name in STATS:
            rec = self.descriptor(name, 'numeric')
            self.write(rec.flags_offset, bytes([rec.flags | 1]))
        for name in REPORT_SETTINGS:
            rec = self.descriptor(name, 'setting')
            self.write(rec.flags_offset, bytes([rec.flags | 1]))
        self.write(event_record + 4, b'\x01')
        return PatchOutcome.ok('CEN, respiratory statistics, EVE recording and all declared AET options enabled.')

    def unlock_options(self, name, kind):
        rec = self.descriptor(name, kind)
        count = rec.option_count
        if count is None or not 1 <= count <= 32 or not 0 <= rec.default < count:
            raise ValueError(f'{name}: invalid declared option count or default')
        self.write(rec.off + (4 if kind == 'enum' else 24), struct.pack('<I', (1 << count) - 1))

    def gui_config(self):
        self.unlock_options('SQA', 'setting')
        names = sorted(CLINICAL.intersection(self.fw.name_lookup.by_name))
        for name in names:
            rec = self.descriptor(name, 'setting')
            self.write(rec.flags_offset, bytes([rec.flags | 1]))
        return PatchOutcome.ok(f'{len(names)} named clinical settings active.')

    def patch_defaults(self):
        targets = []
        for name, value in DEFAULTS:
            rec = self.descriptor(name, 'setting')
            if rec.option_count is None or not 0 <= value < rec.option_count:
                raise ValueError(f'{name}: default outside declared options')
            targets.append((rec.off, value))
        for offset, value in targets:
            self.write(offset, struct.pack('<I', value))
        return PatchOutcome.ok(f'Updated defaults for {len(targets)} vars.')

    def ranges(self, names, minimum, maximum):
        present = [name for name in names if self.fw.name_entry(name)]
        for name in present:
            rec = self.descriptor(name, 'setting')
            if self.fw.records[rec.idx].class_byte & 31 != 4:
                raise ValueError(f'{name}: not a numeric setting')
            scale_offset = 20 if self.fw.cdx_version == 'SX474-1301' else 18
            if self.fw.fl.u16(rec.off + scale_offset) != 50:
                raise ValueError(f'{name}: unexpected numeric scale (expected 50)')
            if not minimum <= rec.default <= maximum:
                raise ValueError(f'{name}: default outside requested range')
            self.write(rec.off + 4, struct.pack('<ii', maximum, minimum))
        return present

    def ui_limits(self):
        names = self.ranges(PRESSURES, 50, 1500)
        self.ranges(('ITN', 'ITX'), 5, 200)
        return PatchOutcome.ok(f'{len(names)} pressure UI ranges: 1..30 cmH2O; Ti Min/Max: 0.1..4 s; '
                               'native dependencies, controller limits and MCP retained.')

    def ps_ranges(self):
        names = self.ranges(PS, 0, 1250)
        sub_gap, epap_ceiling, add_gap = PS_CONSTRAINTS[self.fw.cdx_version]
        self.checked(sub_gap, bytes.fromhex('a0f1fa04'), bytes.fromhex('a0f10004'))
        self.checked(epap_ceiling, bytes.fromhex('a0f59670'), bytes.fromhex('a0f10000'))
        self.checked(add_gap, bytes.fromhex('fa307047'), bytes.fromhex('00307047'))
        return PatchOutcome.ok(f'{len(names)} PS ranges: 0..25 cmH2O; 5 cmH2O MinPS/MaxPS '
                               'separation and MCP-6 EPAP ceiling removed; MCP-EPAP total-pressure limit retained.')

    def motor(self):
        self.checked(MOTOR[self.fw.cdx_version], bytes.fromhex('c000b304'), bytes.fromhex('ffffff7f'))
        return PatchOutcome.ok('Motor life warning threshold extended.')

    def no_alarm_board(self):
        if self.fw.name_entry('AOA') is None:
            return PatchOutcome.skip('Not applicable: firmware has no AOA setting.')
        rec = self.descriptor('AOA', 'setting')
        if rec.option_count != 2 or rec.mask != 3 or rec.default not in (0, 1):
            raise ValueError('unexpected AOA descriptor')
        self.checked(rec.off, struct.pack('<I', 1), struct.pack('<I', 0))
        if self.fw.name_entry('HLE') is not None:
            hle = self.descriptor('HLE', 'setting')
            # With AOA=0 the leak detector uses ALR, controlled by LLA.
            self.write(hle.flags_offset, bytes([self.data[hle.flags_offset] & ~2]))
            return PatchOutcome.ok('AOA.default=0; HLE hidden, leak control remains with LLA/ALR.')
        return PatchOutcome.ok('AOA.default=0; configuration without an alarm board.')

    def lcd(self):
        if self.fw.cdx_version not in LCD:
            raise ValueError(f'LCD adapter unsupported for {self.fw.cdx_version}')
        version = self.fw.cdx_version.removeprefix('SX474-')
        elf = str(REPO / 'build' / f's9_lcd_{version}.elf')
        binary = REPO / 'build' / f's9_lcd_{version}.bin'
        payload = binary.read_bytes()
        if elf_text_address(elf) != 0x080D8000 or payload != elf_binary_data(elf):
            raise ValueError('LCD ELF/binary mismatch or wrong link address; run make s9_lcd_driver')
        base = 0xD8000
        if not payload or base + len(payload) > 0xFFFFE:
            raise ValueError('LCD payload exceeds available flash')
        old = self.data[base:base + len(payload)]
        if old != payload and old != b'\xff' * len(payload):
            raise ValueError('LCD injection area is occupied')
        # Init displaces a complete six-byte PUSH/BL sequence. The other hooks
        # displace four bytes of position-independent PUSH/MOVS instructions.
        init_prefix = {'1201': '80b517f003fe', '1203': '80b517f013fe',
                       '1301': '80b51bf039fd'}[version]
        originals = (init_prefix, 'f8b50700', '38b50500')
        symbols = ('s9_lcd_init', 's9_lcd_set_window', 's9_lcd_set_cursor')
        init, window, cursor = LCD[self.fw.cdx_version]
        native_symbols = {'stock_lcd_init_resume': 0x08000000 + init + 7,
                          'stock_lcd_window_resume': 0x08000000 + window + 5,
                          'stock_lcd_cursor_resume': 0x08000000 + cursor + 5}
        # Cache pointers come from the native window function's literal pool.
        for name, relative in (('x0', 0), ('y0', 8), ('x1', 4), ('y1', 12)):
            native_symbols['lcd_window_' + name] = self.fw.fl.u32(window + 0x5fc + relative)
        for symbol, address in native_symbols.items():
            if elf_symbol_address(elf, symbol) != address:
                raise ValueError(f'LCD native symbol mismatch: {symbol}')
        for off, expected, symbol in zip(LCD[self.fw.cdx_version], originals, symbols):
            target = elf_symbol_address(elf, symbol) & ~1
            if not 0x080D8000 <= target < 0x080D8000 + len(payload):
                raise ValueError(f'LCD symbol outside payload: {symbol}')
            replacement = encode_bw(0x08000000 + off, target)
            if len(bytes.fromhex(expected)) == 6:
                replacement += bytes.fromhex('00bf')
            self.checked(off, bytes.fromhex(expected), replacement)
        self.write(base, payload)
        return PatchOutcome.ok('Automatic LCD selection installed (0x9225/0x0164 or native); native entry points and window cache verified.')

    def checksums(self):
        for name, start, end in self.fw.regions:
            crc = binascii.crc_hqx(self.data[start:end - 2], 0xFFFF)
            self.write(end - 2, struct.pack('>H', crc))
            if binascii.crc_hqx(self.data[start:end], 0xFFFF):
                raise ValueError(f'{name} output checksum verification failed')


def encode_bw(source, target):
    delta = target - (source + 4)
    if delta % 2 or not -(1 << 24) <= delta < (1 << 24):
        raise ValueError('invalid Thumb branch target')
    value = delta & 0x1FFFFFF
    s, i1, i2 = (value >> 24) & 1, (value >> 23) & 1, (value >> 22) & 1
    return struct.pack('<HH', 0xF000 | s << 10 | (value >> 12) & 0x3FF,
                       0x9000 | ((~(i1 ^ s)) & 1) << 13 | ((~(i2 ^ s)) & 1) << 11 | (value >> 1) & 0x7FF)


def build_argument_parser():
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument('INFILE', help='Input original binary file')
    parser.add_argument('OUTFILE', help='Output patched file (unused for INFO)')
    parser.add_argument('OPERATION', choices=['INFO', 'PATCH'], help='Operation to perform')
    PATCH_OPTIONS.add_arguments(parser)
    parser.add_argument('--overwrite', action='store_true', help='Overwrite an existing output file.')
    parser.add_argument('--allow-invalid-input-crc', action='store_true',
                        help='Explicitly allow a research input with invalid region CRCs.')
    parser.add_argument('-v', '--verbose', action='store_true', help='Show per-patch details and byte changes.')
    parser.add_argument('--log-file', help='Append a verbose patching transcript to this file.')
    return parser


def print_patch_details(lines, args, detail_log):
    stream = None if args.verbose else detail_log
    if args.verbose or detail_log is not None:
        for line in lines:
            print('  ' + line, file=stream)


def apply_reported_patch(spec, patcher, args, detail_log=None):
    start = len(patcher.details)
    try:
        outcome = getattr(patcher, spec.method)()
        if not isinstance(outcome, PatchOutcome):
            raise TypeError(f'{spec.option} did not return PatchOutcome')
    except Exception:
        print(f'PATCH: {spec.option} [ERROR]')
        print_patch_details(patcher.details[start:], args, detail_log)
        raise
    print(f'PATCH: {spec.option} [{outcome.status}]')
    if outcome.status == 'SKIP':
        print('  ' + outcome.summary)
    else:
        lines = [outcome.summary, *patcher.details[start:]]
        if len(patcher.details) == start:
            lines.append('Already matches the requested patch; no bytes changed.')
        print_patch_details(lines, args, detail_log)
    return outcome


def run_patcher(args, detail_log=None):
    source, target = Path(args.INFILE), Path(args.OUTFILE)
    firmware = S9Firmware(source)
    print('Firmware Info:')
    print('  BID  ' + firmware.bid)
    print('  SID  ' + firmware.cdx_version)
    invalid = firmware.invalid_crcs()
    if args.OPERATION == 'INFO':
        print('Input CRCs: ' + (', '.join(invalid) + ' invalid' if invalid else 'OK'))
        for spec in PATCH_OPTIONS.patches():
            print(f'{spec.option}: {PATCH_OPTIONS.selected(args, spec)}')
        return 0
    if invalid:
        if not args.allow_invalid_input_crc:
            raise ValueError('invalid input CRC: ' + ', '.join(invalid) +
                             '; inspect the input or explicitly use --allow-invalid-input-crc')
        print('WARNING: explicitly accepting invalid input CRC: ' + ', '.join(invalid))
    if paths_alias(source, target):
        raise ValueError('input and output must be different files')
    if target.exists() and not args.overwrite:
        raise ValueError('output exists; use --overwrite')
    if firmware.cdx_version == 'SX474-1301' and firmware.fl.bytes(0x61DC8, 4) == bytes.fromhex('704700bf'):
        raise ValueError('input contains the old shared-fault bypass; use the original ST-A image')
    patcher = S9Patcher(firmware)
    for phase in PATCH_OPTIONS.phases:
        selected = [spec for spec in phase.patches if PATCH_OPTIONS.selected(args, spec)]
        if not selected:
            continue
        print('\n=== ' + phase.name)
        for spec in selected:
            apply_reported_patch(spec, patcher, args, detail_log)
    print('\n=== Finalization')
    start = len(patcher.details)
    patcher.checksums()
    print_patch_details(['BLX, CCX and CDX CRCs verified.', *patcher.details[start:]], args, detail_log)
    write_output(target, patcher.data, args.overwrite)
    print(hashlib.sha256(patcher.data).hexdigest(), target)
    return 0


def paths_alias(left, right):
    left, right = Path(left), Path(right)
    return left.resolve() == right.resolve() or (left.exists() and right.exists() and os.path.samefile(left, right))


def run_handled(args, detail_log=None):
    try:
        return run_patcher(args, detail_log)
    except (OSError, ValueError, struct.error) as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        return 1


def main(argv=None):
    parser = build_argument_parser()
    args = parse_patch_args(parser, argv, PATCH_OPTIONS)
    if args.OPERATION == 'PATCH':
        errors = PATCH_OPTIONS.dependency_errors(args)
        if errors:
            parser.error('; '.join(errors))
    if args.log_file is None:
        return run_handled(args)
    try:
        if any(paths_alias(args.log_file, image) for image in (args.INFILE, args.OUTFILE)):
            raise ValueError('log file must differ from input and output images')
        with open(args.log_file, 'a', encoding='utf-8') as detail_log:
            with redirect_stdout(TeeStream(sys.stdout, detail_log)), redirect_stderr(TeeStream(sys.stderr, detail_log)):
                return run_handled(args, detail_log)
    except OSError as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        return 1
    except ValueError as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    try:
        sys.exit(main())
    except BrokenPipeError:
        sys.exit(1)

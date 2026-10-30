"""Air 10 SD error logs: fixed-width records in bounded circular files."""

import binascii
import struct
from datetime import date, timedelta
from pathlib import Path


# g[19] stream layouts: trigger variable, serialized value bytes, ring capacity.
# Every record starts with three little-endian u16 fields: UDT, UTT, NOC.
LOG_LAYOUTS = {
    'ABR': ('FAT', 1, 50),
    'TXC': ('SYC', 1, 50),
    'TXH': ('SYH', 1, 50),
    'TXE': ('SYS', 2, 50),
    'TXW': ('SYT', 2, 50),
    'TRR': ('TYS', 2, 100),
    'DLL': ('DLA', 2, 400),
    'ERR': ('AER', 2, 100),
    'ELI': ('ELV', 4, 50),
    'ZRL': ('ZSE', 4, 50),
}

# Only identified conditions are named. Keep unknown bits in the decoded output.
ERROR_BITS = {
    # 080710FA maps SYS bits to Error 001..016, SYT bits to Error 017 onward.
    # These name set conditions; the LCD displays only the first active one.
    'SYS': {1 << bit: f'System error {bit + 1:03}' for bit in range(16)},
    'SYT': {1 << bit: f'System error {bit + 17:03}' for bit in range(10)},
    'SYC': {
        0x01: 'Heater temperature limit exceeded',
        0x02: 'Heater electrical self-test failed',
        0x04: 'Heater feedback detected with PWM disabled',
        0x08: 'Low heater feedback while heating',
        0x10: 'Ambient temperature/humidity sensor communication failed',
    },
    'TYS': {
        0x01: 'High leak',
        0x02: 'Non-vented mask',
        0x04: 'Low minute ventilation',
        0x08: 'Apnea',
        0x10: 'Low SpO2',
        0x20: 'Oximeter disconnected',
        0x40: 'Invalid oximeter data',
        # UART command result 4 = timeout after retry, 5 = invalid response.
        # SX567-0402: 080D295C/080D2892 -> 080D1F62/080DF41E.
        0x80: 'Humidifier timeout',
        0x100: 'Invalid humidifier response',
        0x200: 'Tube timeout',
        0x400: 'Invalid tube response',
    },
}


# AER identifies firmware checks, not the system-error number shown on screen.
# Call sites verified in SX567-0402. Describe the failed check, not a presumed
# hardware cause: e.g. an SD CRC error does not establish that the card is bad.
ERROR_CODES = {
    # 0806A364 -> BKP13R -> 0808C1BA -> FAT.
    'FAT': {
        0x26: 'Menu item capacity exceeded',  # 08064E8C
        0x27: 'GUI window creation failed',  # 0806D2F8
    },
    'AER': {
        0x27FC: 'Numeric variable read before ready',  # 0806B348, vtable +84
        # 080D2892: UART1 receive result other than success or pending.
        # 0808686C includes inactive receiver and receive-budget exhaustion.
        0x281E: 'Peripheral UART receive failed',
        0x2825: 'Log copy to SD incomplete',  # 080C7B20 -> 080C7436
        0x2835: 'Timed-task/IRQ CPU load limit reached',  # 0808B45E
        0x283C: 'EDF file operation failed',  # 080D126C, file state 2
        0x284C: 'Startup: unrecognized saved restart state',  # 0808C7D8
        0x284E: 'Startup: backup register 9 not clear',  # 0808C876
        0x284F: 'Non-numeric time string',  # 08070E84
        0x2855: 'Low-pressure/disconnected-tube alarm',  # 080E5A90
        0x28A7: 'Peripheral response opcode mismatch',  # 080D2892
        0x28CB: 'EDF write smaller than one record',  # 080CC520
        0x28D1: 'EEPROM session file validation failed; recreating storage',  # 0809C150
        0x28D2: 'EEPROM session file read failed during validation',
        # Session EDF exporter: 080CBBE8, 080CBDCE, 080CBF44.
        0x28DF: 'Session export: reversed source range',
        0x28E0: 'Session export: incomplete source records',
        0x28E1: 'Session export: empty source batch',
        0x28E2: 'Session export: source batch exceeds range',
        0x28E3: 'Session export: target extends past current day',
        0x28F2: 'SD command did not become idle',  # 0808E4A4
        0x28F3: 'SD data CRC error during read',  # 0808E5EC, SDIO STA DCRCFAIL
        0x28F4: 'SD command-response CRC error',  # SDIO_ReadResponse, CCRCFAIL
        0x28F5: 'SD command response wait: unexpected data-end flag',
        0x28F6: 'SD command-response wait timed out',
        0x28F7: 'SD DMA read completion wait timed out',
        0x28F8: 'SD receive FIFO overrun',
        0x28F9: 'SD read ended without block-completion flag',
        0x28FB: 'SD data timeout during read',
        0x2902: 'SD block read failed after retries',  # 0808DD5E
        0x2905: 'SD card selection failed before read',  # 0808DD32
        0x2928: 'SD identification file not ready for truncation',  # 080F6AE8
        0x2929: 'SD identification file truncation: unexpected writer state',
        # 08094E4E selects by path and operation; the table at 20000000 is
        # decompressed during startup. These entries agree in 0302..0402.
        0x2952: 'SD DATALOG file open failed',
        0x2969: 'SD SETTINGS log write failed',
        0x29AE: 'SD backup completion timed out (30 s)',  # 080C8558
        0x29B0: 'SD data CRC error during write',  # 0808E6CC
        # 0808C7D8 translates saved BKP10R states, not new faults at log time.
        0x29B6: 'Startup: saved fatal-error state',
        0x29B7: 'Startup: saved restart state 8',
        0x29BA: 'Startup: saved HardFault',
        0x29BB: 'Startup: saved MemManage fault',
        0x29BC: 'Startup: saved BusFault',
        0x29BD: 'Startup: saved UsageFault',
        0x29BE: 'Startup: previous initialization incomplete',
        0x29C3: 'Chinese and Japanese font groups enabled together',  # 0806B158
    },
    'DLA': {
        # 0807A804: BPF raw thresholds with hysteresis, not an on/off command.
        0x01: 'Blower pressure crossed upper activity threshold',
        0x02: 'Blower pressure crossed lower activity threshold',
        0x03: 'SmartStop requested therapy stop',
        0x04: 'SmartStart requested therapy start',
        # 0807A864 maps run states to DLA; constructors 080C8CB4..080C8DF8
        # register the state numbers. These are not MOP therapy mode indexes.
        0x05: 'Reset',
        0x06: 'Standby',
        0x07: 'Power recovery',
        0x08: 'Compliance reset',
        0x09: 'Therapy',
        0x0A: 'Mask fit',
        0x0B: 'Calibration',
        0x0C: 'System error state',
        0x0D: 'Power save',
        0x0E: 'Learn targets',
        0x0F: 'Firmware upgrade',
        0x10: 'Firmware upgrade preparation',
        0x11: 'Application startup marker 1',  # 0808C876
        0x12: 'Application startup marker 2',
        0x13: 'Mask on',  # 080D5E20, 080D5EE8
        0x14: 'Mask off',  # 080D5EBC
        0x15: 'SD card detected',  # 0808EBF8
        0x16: 'SD card removed',
        # 0807A79C and 080EAC3A: key events versus signed encoder movement.
        0x17: 'Front-panel key event 1',
        0x18: 'Front-panel key event 3',
        0x19: 'Front-panel key event 8',
        0x1A: 'Front-panel key event 9',
        0x1B: 'Front-panel key event 4',
        0x1C: 'Dial movement (positive)',
        0x1D: 'Dial movement (negative)',
        # 0807A7D0 groups several GUI pages under a single event code.
        0x1E: 'GUI page group changed (page 0)',
        0x1F: 'GUI page group changed (page 5)',
        0x20: 'GUI message activated',  # 080802B0
        0x21: 'GUI page group changed (pages 3/4/7)',
        0x22: 'GUI page group changed (pages 1/2/6)',
        # 0807A830/080D2E7C/080DAC80: HUS state events.
        0x23: 'Humidifier off',
        0x24: 'Humidifier standby',
        0x25: 'Humidifier warming',
        0x26: 'Humidifier cooling',
        0x27: 'Humidifier ready',
        0x28: 'Humidifier therapy state, heating enabled',
        0x29: 'Humidifier therapy state, heating disabled',
        0x2A: 'Humidifier fault state',
        # 080D1CDE mirrors response bit 7 into HUC, including the first report.
        0x2B: 'Humidifier status reported HUC=0',
        0x2C: 'Humidifier status reported HUC=1',
        0x2D: 'Blocked-tube condition activated',  # 080E5884
        0x2E: 'Low-pressure alarm',  # 080E5A90
        0x2F: 'Blocked-tube alarm',  # 080E5884
        0x30: 'Disconnected-tube alarm',  # 080E5A90
        0x33: 'Humidifier or heated-tube communication failed',
    },
}


def describe_error(source, value):
    """Decode bitmasks and scalar event codes without conflating the two."""
    if source == 'ELV':
        # 0808C7D8 copies BKP11R to ELV for saved exception states 10..14.
        return 'No saved exception PC' if value == 0x7FFFFFFF else 'Saved exception PC'
    codes = ERROR_CODES.get(source)
    if codes is not None:
        return codes.get(value, 'Undecoded value')
    bits = ERROR_BITS.get(source)
    if bits is None:
        return 'Undecoded value'
    if value == 0:
        return 'No flags set'

    descriptions = []
    remaining = value
    for mask, description in bits.items():
        if value & mask:
            descriptions.append(description)
            remaining &= ~mask
    if remaining:
        descriptions.append(f'Unknown bits 0x{remaining:X}')
    return '; '.join(descriptions)


def find_error_logs(path):
    """Accept a card root, a log directory, or one named TAG.log file."""
    path = Path(path)
    if path.is_file():
        if path.suffix.lower() != '.log' or path.stem.upper() not in LOG_LAYOUTS:
            raise ValueError(f'{path}: expected a known Air 10 TAG.log file')
        return [path]
    if not path.is_dir():
        raise ValueError(f'{path}: file or directory not found')

    settings = [p for p in path.iterdir() if p.is_dir() and p.name.upper() == 'SETTINGS']
    if len(settings) > 1:
        raise ValueError(f'{path}: multiple SETTINGS directories')
    if settings:
        path = settings[0]

    files = sorted(p for p in path.iterdir()
                   if p.is_file() and p.suffix.lower() == '.log' and p.stem.upper() in LOG_LAYOUTS)
    if not files:
        raise ValueError(f'{path}: no Air 10 error logs found')
    return files


def read_error_log(path):
    """Validate a .log file and return records in circular-buffer write order."""
    path = Path(path)
    tag = path.stem.upper()
    if tag not in LOG_LAYOUTS:
        raise ValueError(f'{path}: unknown error-log tag')
    source, value_bytes, capacity = LOG_LAYOUTS[tag]
    data = path.read_bytes()
    if len(data) < 12:
        raise ValueError(f'{path}: truncated 12-byte header')

    header_day, header_seconds, last_slot, stored_crc = struct.unpack_from('<IIHH', data)
    actual_crc = binascii.crc_hqx(data[:10], 0xFFFF)
    if actual_crc != stored_crc:
        raise ValueError(f'{path}: header CRC mismatch (stored {stored_crc:04X}, calculated {actual_crc:04X})')
    if header_seconds >= 86400:
        raise ValueError(f'{path}: invalid header time {header_seconds}')

    record_size = 6 + value_bytes
    count, remainder = divmod(len(data) - 12, record_size)
    if remainder:
        raise ValueError(f'{path}: truncated {record_size}-byte record ({remainder} trailing bytes)')
    if count > capacity:
        raise ValueError(f'{path}: {count} records exceed capacity {capacity}')
    if last_slot >= max(count, 1):
        raise ValueError(f'{path}: last slot {last_slot} outside {count} records')

    # The persisted index is the last written slot, not the next slot or count.
    # A partially filled ring has not wrapped; full rings start after that slot.
    if count < capacity and count and last_slot != count - 1:
        raise ValueError(f'{path}: last slot {last_slot} inconsistent with {count} records')
    slots = list(range(count))
    if count == capacity:
        slots = slots[last_slot + 1:] + slots[:last_slot + 1]

    records = []
    for slot in slots:
        offset = 12 + slot * record_size
        day, minute, noc = struct.unpack_from('<HHH', data, offset)
        if minute >= 1440:
            raise ValueError(f'{path}: slot {slot} has invalid minute-of-day {minute}')
        value = int.from_bytes(data[offset + 6:offset + record_size], 'little')
        record_date = date(1970, 1, 1) + timedelta(days=day)
        records.append({
            'tag': tag,
            'source': source,
            'slot': slot,
            'day': day,
            'minute': minute,
            'timestamp': f'{record_date.isoformat()} {minute // 60:02d}:{minute % 60:02d}',
            'noc': noc,
            'value': value,
            'raw': f'0x{value:0{value_bytes * 2}X}',
            'description': describe_error(source, value),
        })

    backwards = sum(a['timestamp'] > b['timestamp'] for a, b in zip(records, records[1:]))
    warnings = []
    if backwards:
        warnings.append(f'{path}: timestamps move backwards at {backwards} record transitions; '
                        'use --order record to retain write order')

    return {
        'path': str(path),
        'tag': tag,
        'source': source,
        'capacity': capacity,
        'header': {
            'day': header_day,
            'seconds': header_seconds,
            'last_slot': last_slot,
            'crc': stored_crc,
        },
        'records': records,
        'warnings': warnings,
    }


def summarize_error_logs(logs):
    """Count stored records per code, keeping NOC separate from record counts."""
    groups = {}
    for log in logs:
        for record in log['records']:
            key = (record['tag'], record['value'])
            if key not in groups:
                groups[key] = {name: record[name] for name in ('tag', 'source', 'value', 'raw', 'description')}
                groups[key].update(records=0, first=record['timestamp'], last=record['timestamp'])
            group = groups[key]
            group['records'] += 1
            group['first'] = min(group['first'], record['timestamp'])
            group['last'] = max(group['last'], record['timestamp'])
    return [groups[key] for key in sorted(groups)]

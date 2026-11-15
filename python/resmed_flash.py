#!/usr/bin/env python3
"""
ResMed AirSense UART Flash Tool

Transfers firmware through the ResMed AirSense UART bootloader protocol.
Supports block flashing, firmware dumps, and verified EEPROM transfers.

S10 flash memory map (SX577/SX585):
  0x08000000  BLX  16KB   Bootloader
  0x08004000  CCX  240KB  Configuration
  0x08040000  CDX  768KB  Firmware
              CMX  1008KB CCX+CDX combined

S9 flash memory map (SX525):
  0x08000000  BLX  12KB   Bootloader
  0x08003000  CCX  118KB  Configuration
  0x08020800  CDX  894KB  Firmware

"""

import serial
import argparse
import os
import time
import sys
import struct
import re
import math
from pathlib import Path
from tcp_serial import open_tcp


class FlashUnconfirmed(RuntimeError):
    """Transmission started, but the device's final result is not known."""


# Platform profiles, keyed by bootloader BID prefix.
PLATFORMS = {
    'SX577': {'baud_method': 'bdd', 'default_baud': 57600,
              'baud_rates': {57600: '0000', 115200: '0001', 460800: '0002'},
              'enter_cmd': 'P S #BLL 0001', 'reset_cmd': 'P S #RES 0001',
              'flash_status': 'BLE', 'rop_settings': True},
    'SX585': {'baud_method': 'bdd', 'default_baud': 57600,
              'baud_rates': {57600: '0000', 115200: '0001', 460800: '0002'},
              'enter_cmd': 'P S #BLL 0001', 'reset_cmd': 'P S #RES 0001',
              'flash_status': 'BLE'},
    'SX525': {'baud_method': 'fixed', 'default_baud': 57600,
              'baud_rates': {57600: 'E100'},
              'enter_cmd': 'P S #RES 0001', 'reset_cmd': None,
              'flash_status': 'PST', 'end_record': 7,
              'bls_errors': {0x6004: 1, 0x600E: 0}},
}

BLOCK_MAPS = {
    'SX577-0200': {
        'BLX': {'flash_start': 0x08000000, 'file_offset': 0x00000, 'size': 0x04000,
                'name': 'Bootloader', 'erase_cmd': 'P F *BLX 0000'},
        'CCX': {'flash_start': 0x08004000, 'file_offset': 0x04000, 'size': 0x3C000,
                'name': 'Config',     'erase_cmd': 'P F *CCX 0000'},
        'CDX': {'flash_start': 0x08040000, 'file_offset': 0x40000, 'size': 0xC0000,
                'name': 'Firmware',   'erase_cmd': 'P F *CDX 0000'},
        'CMX': {'flash_start': 0x08004000, 'file_offset': 0x04000, 'size': 0xFC000,
                'name': 'Config+FW',  'erase_cmd': 'P F *CMX 0000'},
    },
    'SX585-0200': {
        'BLX': {'flash_start': 0x08000000, 'file_offset': 0x00000, 'size': 0x04000,
                'name': 'Bootloader', 'erase_cmd': 'P F *BLX 0000'},
        'CCX': {'flash_start': 0x08004000, 'file_offset': 0x04000, 'size': 0x1C000,
                'name': 'Config',     'erase_cmd': 'P F *CCX 0000'},
        'CDX': {'flash_start': 0x08020000, 'file_offset': 0x20000, 'size': 0xE0000,
                'name': 'Firmware',   'erase_cmd': 'P F *CDX 0000'},
        'CMX': {'flash_start': 0x08004000, 'file_offset': 0x04000, 'size': 0xFC000,
                'name': 'Config+FW',  'erase_cmd': 'P F *CMX 0000'},
    },
    'SX525-0300': {
        'BLX': {'flash_start': 0x08000000, 'file_offset': 0x00000, 'size': 0x03000,
                'name': 'Bootloader', 'erase_cmd': 'P F *BLX 1C200'},
        'CCX': {'flash_start': 0x08003000, 'file_offset': 0x03000, 'size': 0x1D800,
                'name': 'Config',     'erase_cmd': 'P F *CCX 1C200'},
        'CDX': {'flash_start': 0x08020800, 'file_offset': 0x20800, 'size': 0xDF800,
                'name': 'Firmware',   'erase_cmd': 'P F *CDX 1C200'},
    },
    'SX525-0400': {
        'BLX': {'flash_start': 0x08000000, 'file_offset': 0x00000, 'size': 0x03000,
                'name': 'Bootloader', 'erase_cmd': 'P F *BLX 1C200'},
        'CCX': {'flash_start': 0x08003000, 'file_offset': 0x03000, 'size': 0x1D800,
                'name': 'Config',     'erase_cmd': 'P F *CCX 1C200'},
        'CDX': {'flash_start': 0x08020800, 'file_offset': 0x20800, 'size': 0xDF800,
                'name': 'Firmware',   'erase_cmd': 'P F *CDX 1C200'},
    },
}

DUMP_SUPPORTED_BIDS = {'SX577-0200', 'SX585-0200'}
SUPPORTED_BIDS = DUMP_SUPPORTED_BIDS | {'SX525-0300', 'SX525-0400'}

FULL_IMAGE_SIZE = 0x100000
DUMP_CHUNK_SIZE = 240
DUMP_FRAME_TYPE = 'O'
EEPROM_SIZE = 0x40000
EEPROM_PAGE_SIZE = 256
EEPROM_MODULE_LIMIT = 0x8000
EEPROM_WRITE_BUFFER = 0x8000
EEPROM_INFO = b'AEEP' + struct.pack('<BIHI', 4, EEPROM_SIZE, EEPROM_PAGE_SIZE, EEPROM_WRITE_BUFFER)
EEPROM_ERRORS = {
    1: 'invalid transfer request, range or sequence',
    2: 'SPI transfer timeout',
    3: 'EEPROM busy timeout (check the EEPROM connection)',
    4: 'EEPROM block protection is enabled',
    5: 'EEPROM did not enable writes',
    6: 'EEPROM readback differs from written data',
    7: 'bootloader is not idle',
    8: 'SPI1 is already in use',
    9: 'EEPROM write stream timed out',
}

BLOCK_ALIASES = {
    'bootloader': 'BLX', 'boot': 'BLX', 'blx': 'BLX',
    'config': 'CCX', 'conf': 'CCX', 'ccx': 'CCX',
    'firmware': 'CDX', 'fw': 'CDX', 'cdx': 'CDX',
    'cmx': 'CMX',
}


BDD_RATES = {57600: '0000', 115200: '0001', 460800: '0002'}
BDD_RATES_ORDERED = [460800, 115200, 57600]
PROBE_RATES = [57600, 115200, 460800]


def _platform(bid):
    if bid and len(bid) >= 5:
        return PLATFORMS.get(bid[:5])
    return None


def crc16_ccitt(data: bytes) -> int:
    crc = 0xFFFF
    for b in data:
        crc ^= b << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021 if crc & 0x8000 else crc << 1) & 0xFFFF
    return crc

def escape_payload(data: bytes) -> bytes:
    return data.replace(b'U', b'UU')

def build_frame(frame_type: str, payload: bytes) -> bytes:
    escaped = escape_payload(payload)
    frame_len = 1 + 1 + 3 + len(escaped) + 4
    pre_crc = b'U' + frame_type.encode() + f'{frame_len:03X}'.encode() + escaped
    crc = crc16_ccitt(pre_crc)
    return pre_crc + f'{crc:04X}'.encode()

def build_q_frame(cmd: str) -> bytes:
    return build_frame('Q', cmd.encode())

def build_f_frame(block_name: bytes, seq: int, records: bytes) -> bytes:
    return build_frame('f', block_name + b'\x00' + bytes([seq]) + records)

def build_completion_frame(block_name: bytes, seq: int) -> bytes:
    return build_frame('f', block_name + b'F' + bytes([seq]))

def build_record_03(address: int, data: bytes) -> bytes:
    length = 4 + len(data) + 1
    return bytes([0x03, length]) + struct.pack('>I', address) + data + bytes([0])

def reset_input_buffer(ser):
    """Discard both transport input and any partially assembled protocol frame."""
    ser.reset_input_buffer()
    ser._resmed_rx = bytearray()

def read_responses(ser, timeout=1.0):
    responses = []
    raw = bytearray()
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        frame = read_frame(ser, timeout=deadline - time.monotonic())
        if frame is None:
            break
        raw.extend(frame['raw'])
        # S9 can send its first erase-progress P frame with a damaged CRC.
        # It is informational only; terminal R/E responses must pass CRC.
        if frame['crc_ok'] or frame['type'] == 'P':
            responses.append(frame)
            deadline = min(deadline, time.monotonic() + 0.02)
    return bytes(raw), responses


def read_frame(ser, timeout=1.0):
    """Read one frame, retaining fragments and coalesced replies for later reads."""
    old_timeout = ser.timeout
    ser.timeout = 0.02
    if not hasattr(ser, '_resmed_rx'):
        ser._resmed_rx = bytearray()
    data = ser._resmed_rx
    deadline = None if timeout is None else time.monotonic() + timeout
    try:
        while True:
            needed = 5
            while True:
                try:
                    start = data.index(ord('U'))
                except ValueError:
                    data.clear()
                    break
                if start:
                    del data[:start]
                if len(data) < 5:
                    needed = 5 - len(data)
                    break
                if data[1] == ord('U'):
                    del data[0]
                    continue
                try:
                    length = int(bytes(data[2:5]), 16)
                except ValueError:
                    del data[0]
                    continue
                if length < 9 or length > 0x1ff:
                    del data[0]
                    continue
                if len(data) < length:
                    needed = length - len(data)
                    break

                raw = bytes(data[:length])
                try:
                    stored_crc = int(raw[-4:], 16)
                except ValueError:
                    del data[0]
                    continue
                del data[:length]
                return {
                    'type': chr(raw[1]),
                    'payload': raw[5:-4].replace(b'UU', b'U'),
                    'crc_ok': stored_crc == crc16_ccitt(raw[:-4]),
                    'raw': raw,
                }
            remaining = None if deadline is None else deadline - time.monotonic()
            if remaining is not None and remaining <= 0:
                return None
            ser.timeout = 0.02 if remaining is None else min(0.02, remaining)
            # Serial.read waits for the requested byte count or its timeout.
            # Read only the header/remainder, so a complete short frame returns
            # immediately on serial ports as well as TCP sockets.
            data.extend(ser.read(needed))
    finally:
        ser.timeout = old_timeout


def read_blx_reply(ser, timeout=1.0, strict=False):
    """Read a complete O reply with a valid CRC and declared payload length."""
    deadline = None if timeout is None else time.monotonic() + timeout
    while deadline is None or time.monotonic() < deadline:
        frame = read_frame(ser, timeout=None if deadline is None else deadline - time.monotonic())
        if frame is None:
            return None
        payload = frame['payload']
        if not frame['crc_ok'] or frame['type'] != DUMP_FRAME_TYPE or len(payload) < 7:
            if strict:
                raise RuntimeError('invalid BLX stream frame or CRC')
            continue
        offset, n = struct.unpack_from('<IH', payload, 1)
        if len(payload) == 7 + n:
            return payload[:1], offset, payload[7:]
        if strict:
            raise RuntimeError('invalid BLX stream frame length')
    return None


def check_blx_error(command, op, offset, data):
    if op == b'E' and not data:
        if command == b'D':
            raise RuntimeError('bootloader rejected dump range at 0x%05X' % offset)
        raise RuntimeError('BLX rejected the RAM module or upload range; use the '
                           'module from the same build as --patch-blx-dump')
    if op == b'e' and len(data) == 1:
        raise RuntimeError('%s at 0x%05X: %s' % (
            'BLX' if command == b'D' else 'EEPROM', offset,
            EEPROM_ERRORS.get(data[0], 'unknown error %d' % data[0])))


def send_blx_request(ser, request):
    wire = build_frame(DUMP_FRAME_TYPE, request)
    if len(wire) > 0x1ff:
        raise ValueError('request exceeds the bootloader frame size')
    reset_input_buffer(ser)
    if ser.write(wire) != len(wire):
        raise OSError('short write of BLX transfer request')
    ser.flush()


def request_blx_chunk(ser, command, offset, length, data=b'', retries=3):
    """Exchange a loader flash/upload chunk or a module information request."""
    if command in (b'D', b'U'):
        request = command + struct.pack('<IH', offset, length) + data
    elif command == b'I':
        request = b'X' + struct.pack('<IH', offset, length) + command + data
    else:
        raise ValueError('unknown BLX transfer command: %r' % command)
    response_length = len(EEPROM_INFO) if command == b'I' else length
    for _ in range(retries):
        send_blx_request(ser, request)
        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline:
            reply = read_blx_reply(ser, deadline - time.monotonic())
            if reply is None:
                break
            op, reply_offset, actual = reply
            if reply_offset != offset:
                continue
            check_blx_error(command, op, offset, actual)
            if op != command.lower() or len(actual) != response_length:
                continue
            if command == b'U' and actual != data:
                raise RuntimeError('RAM module readback mismatch at 0x%05X' % offset)
            return actual
    raise RuntimeError('BLX transfer failed at 0x%05X: no valid response' % offset)


def load_eeprom_module(bid, path=None):
    if bid not in DUMP_SUPPORTED_BIDS:
        raise RuntimeError('EEPROM service does not support BID ' + str(bid))
    binary = (Path(path) if path else Path(__file__).resolve().parent.parent /
              'build' / ('blx_eeprom_%s.bin' % bid))
    try:
        data = binary.read_bytes()
    except OSError as exc:
        raise RuntimeError('cannot load EEPROM module from %s '
                           '(run make binaries): %s' % (binary, exc)) from exc
    if not 0 < len(data) <= EEPROM_MODULE_LIMIT:
        raise RuntimeError('invalid EEPROM module size: %s' % binary)
    return data


def upload_eeprom_module(ser, module):
    print('[*] Uploading and verifying transfer RAM module (%d bytes)...' % len(module))
    for offset, length in transfer_ranges(len(module)):
        chunk = module[offset:offset + length]
        request_blx_chunk(ser, b'U', offset, length, chunk)
    info = request_blx_chunk(ser, b'I', 0, 0)
    if info != EEPROM_INFO:
        raise RuntimeError('unexpected EEPROM module protocol or geometry')
    print('[+] RAM readback and BLX module CRC verified')


def transfer_ranges(size):
    offset = 0
    while offset < size:
        length = min(DUMP_CHUNK_SIZE, size - offset)
        yield offset, length
        offset += length


def read_memory(ser, command, size):
    yield from read_memory_range(ser, command, 0, size)


def read_memory_range(ser, command, start, end):
    """Acknowledge consumed data within a bounded sliding window of frames."""
    limits = {b'D': FULL_IMAGE_SIZE, b'R': EEPROM_SIZE}
    if command not in limits or not 0 <= start < end <= limits[command]:
        raise ValueError('invalid memory read command or range')
    # Budget wire bytes, including worst-case escaping, not just payload bytes.
    # Direct serial uses a conservative 4 KiB receive buffer. TCP advertises its
    # actual queue; a legacy/raw bridge permits only one outstanding frame.
    window = min(128, getattr(ser, 'reply_buffer', 4096) // 511)
    if window < 1:
        raise RuntimeError('receive buffer cannot hold one BLX frame')
    acknowledge_every = max(1, window // 2) * DUMP_CHUNK_SIZE
    offset = acknowledged = start
    complete = False
    send_blx_request(ser, b'X' + struct.pack('<IH', start, window) + command + struct.pack('<I', end))
    try:
        while True:
            reply = read_blx_reply(ser, timeout=None, strict=True)
            if reply is None:
                raise RuntimeError('memory stream timed out at 0x%05X' % offset)
            op, reply_offset, data = reply
            if reply_offset < start:
                continue
            check_blx_error(command, op, reply_offset, data)
            if op != command.lower() or reply_offset != offset:
                raise RuntimeError('unexpected memory stream reply at 0x%05X (expected 0x%05X)' %
                                   (reply_offset, offset))
            if offset == end and not data:
                complete = True
                return
            if not data or len(data) != min(DUMP_CHUNK_SIZE, end - offset):
                raise RuntimeError('incomplete memory stream at 0x%05X' % offset)
            yield offset, data
            offset += len(data)
            # Yield first: a slow file writer or comparison must also stop BLX.
            if offset == end or offset - acknowledged >= acknowledge_every:
                frame = build_frame(DUMP_FRAME_TYPE, b'A' + struct.pack('<IH', offset, 0))
                write_transfer_frame(ser, frame, 'memory read acknowledgement')
                ser.flush()
                acknowledged = offset
    finally:
        if not complete:
            # An invalid ACK cancels the module's wait and restores borrowed SPI.
            # Do not mask the original failure if the transport has gone away.
            try:
                ser.write(build_frame(DUMP_FRAME_TYPE, b'A' + struct.pack('<IH', offset, 1)))
                ser.flush()
            except OSError:
                pass


def write_eeprom_range(ser, data):
    """Stream frames into the device's staging buffer; await verified credits."""
    end = len(data)
    if not 0 < end <= EEPROM_SIZE:
        raise ValueError('invalid EEPROM write range')
    send_blx_request(ser, b'X' + struct.pack('<IH', 0, 0) + b'W' + struct.pack('<I', end))
    offset = 0
    while True:
        # A full buffer needs at most 128 page writes. The device bounds each
        # busy wait to 100 ms, so allow completion even at that error boundary.
        reply = read_blx_reply(ser, timeout=15.0)
        if reply is None:
            raise RuntimeError('no verified EEPROM write completion at 0x%05X' % offset)
        op, at, content = reply
        check_blx_error(b'W', op, at, content)
        if op != b'w' or at != offset or content:
            raise RuntimeError('unexpected EEPROM write completion at 0x%05X' % offset)
        if offset == end:
            return
        stop = min(offset + EEPROM_WRITE_BUFFER, end)
        while offset < stop:
            chunk = data[offset:min(offset + DUMP_CHUNK_SIZE, stop)]
            frame = build_frame(DUMP_FRAME_TYPE, b'W' + struct.pack('<IH', offset, len(chunk)) + chunk)
            write_transfer_frame(ser, frame, 'EEPROM data at 0x%05X' % offset)
            offset += len(chunk)
        ser.flush()


def restore_eeprom_data(ser, data):
    if len(data) != EEPROM_SIZE:
        raise ValueError('EEPROM restore requires exactly 262144 bytes')
    print('[*] Streaming EEPROM data with write verification...')
    started = time.monotonic()
    write_eeprom_range(ser, data)
    print('[+] EEPROM write verified in %.1fs' % (time.monotonic() - started))
    print('[*] Reading back all 262,144 bytes for final comparison...')
    verified = time.monotonic()
    for offset, actual in read_memory(ser, b'R', EEPROM_SIZE):
        if actual != data[offset:offset + len(actual)]:
            raise RuntimeError('final EEPROM verification failed at 0x%05X' % offset)
    finished = time.monotonic()
    print('[+] Entire EEPROM matches the restore file (comparison %.1fs, restore total %.1fs)' %
          (finished - verified, finished - started))

def send_cmd(ser, cmd_str, timeout=2.0, quiet=False):
    reset_input_buffer(ser)
    frame = build_q_frame(cmd_str)
    if ser.write(frame) != len(frame):
        raise OSError('short write of command: ' + cmd_str)
    ser.flush()
    raw, responses = read_responses(ser, timeout=timeout)
    if not quiet:
        for r in responses:
            print(f"  [{r['type']}] {r['payload'].decode('ascii', errors='replace')}")
    return raw, responses

def _extract_bid(responses):
    for r in responses:
        if b'BID' in r['payload']:
            text = r['payload'].decode('ascii', errors='replace')
            if '= ' in text:
                return text.split('= ', 1)[1].strip().rstrip('\x00')
            parts = text.split('BID ', 1)
            if len(parts) > 1:
                return parts[1].strip().rstrip('\x00')
    return None

def query_bid(ser):
    _, resp = send_cmd(ser, "G S #BID", timeout=0.5, quiet=True)
    return _extract_bid(resp)

def _extract_hex_var(responses, name, frame_type='R'):
    pattern = rb'G S #' + re.escape(name.encode()) + rb'\s*=\s*([0-9A-Fa-f]+)\x00*'
    for r in responses:
        if r['type'] == frame_type:
            match = re.fullmatch(pattern, r['payload'].strip())
            if match:
                return int(match[1], 16)
    return None

def query_boot_var(ser, name, timeout=0.3, wait_final=False, discard_input=True):
    """Send one query and await its reply without polling or losing fragments."""
    if discard_input:
        reset_input_buffer(ser)
    frame = build_q_frame(f"G S #{name}")
    if ser.write(frame) != len(frame):
        raise OSError('short write of status query')
    ser.flush()
    # S9 answers PST with P while checking flash, then R with the result.
    deadline = time.monotonic() + (max(timeout, 15.0) if wait_final else timeout)
    while time.monotonic() < deadline:
        response = read_frame(ser, timeout=deadline - time.monotonic())
        if response is None:
            break
        if not response['crc_ok']:
            continue
        value = _extract_hex_var([response], name)
        if value is not None:
            return value
        if response['type'] == 'E':
            print("[!] Device error while awaiting %s: %s" %
                  (name, response['payload'].decode('ascii', errors='replace')))
            return None
    return None


def query_bls(ser, timeout=0.3, platform=None):
    """Return 0=application, 1=bootloader, 2=invalid firmware, None=no state."""
    _, resp = send_cmd(ser, "G S #BLS", timeout=timeout, quiet=True)
    value = _extract_hex_var(resp, 'BLS')
    if value is None and platform:
        # S9 has no BLS value: BLX replies E 6004, running CDX replies E 600E.
        error = _extract_hex_var(resp, 'BLS', frame_type='E')
        return platform.get('bls_errors', {}).get(error)
    return value

def wait_for_application(ser, status_var, timeout=15.0,
                         clean_status_grace=5.0, quiet_time=3.0):
    deadline = time.time() + timeout
    last_bls = None
    last_status = None
    extended = False

    # Successful bootloader commands restart its UART activity timeout. Leave
    # the line idle long enough for the normal application boot path to run.
    time.sleep(quiet_time)
    while time.time() < deadline:
        bls = query_bls(ser, timeout=0.3)
        if bls == 0:
            return True, bls, None
        if bls is not None:
            last_bls = bls
            last_status = query_boot_var(ser, status_var, timeout=0.5)
            if last_status not in (None, 0) or bls >= 2:
                return False, last_bls, last_status
            if last_status == 0 and not extended:
                deadline += clean_status_grace
                extended = True
                print(f"[*] Bootloader reports {status_var}=0000; "
                      f"allowing {clean_status_grace:.0f}s more for startup...")
            time.sleep(quiet_time)
            continue
        time.sleep(0.2)
    if last_status is None:
        last_status = query_boot_var(ser, status_var, timeout=0.5)
    return False, last_bls, last_status

def bid_from_image(image_data):
    """Extract BID from BLX region of a full image (version string near end of BLX)."""
    blx_sizes = sorted(set(b['BLX']['size'] for b in BLOCK_MAPS.values()), reverse=True)
    for blx_size in blx_sizes:
        if len(image_data) < blx_size:
            continue
        blx = image_data[:blx_size]
        for off in range(blx_size - 16, blx_size // 2, -1):
            chunk = blx[off:off+10]
            if (chunk[:2] == b'SX' and chunk[5:6] == b'-'
                    and all(0x30 <= b <= 0x39 for b in chunk[2:5])
                    and all(0x30 <= b <= 0x39 for b in chunk[6:10])):
                return chunk.decode('ascii')
    return None

def get_blocks(bid):
    return BLOCK_MAPS.get(bid)


def probe_baud(ser):
    for rate in PROBE_RATES:
        ser.baudrate = rate
        reset_input_buffer(ser)
        time.sleep(0.05)
        _, resp = send_cmd(ser, "G S #BID", timeout=0.3, quiet=True)
        bid = _extract_bid(resp)
        if bid:
            return rate, bid
    return None, None

def wait_for_device(ser, timeout=None):
    t0 = time.time()
    attempt = 0
    while True:
        baud, bid = probe_baud(ser)
        if baud:
            return baud, bid
        attempt += 1
        if attempt == 1:
            sys.stdout.write("[*] Waiting for device...")
            sys.stdout.flush()
        elif attempt % 5 == 0:
            sys.stdout.write(".")
            sys.stdout.flush()
        if timeout and time.time() - t0 > timeout:
            print()
            return None, None
        time.sleep(0.5)

def switch_baud(ser, target, quiet=False):
    if target not in BDD_RATES or ser.baudrate == target:
        return ser.baudrate == target
    old = ser.baudrate
    if not quiet:
        print(f"[*] Switching baud: {old} -> {target} (BDD {BDD_RATES[target]})...")
    reset_input_buffer(ser)
    ser.write(build_q_frame(f"P S #BDD {BDD_RATES[target]}"))
    ser.flush()
    time.sleep(0.3)
    read_responses(ser, timeout=0.5)  # consume ACK at old baud
    ser.baudrate = target
    time.sleep(0.05)
    _, resp = send_cmd(ser, "G S #BID", timeout=0.5, quiet=True)
    if any(b'BID' in r['payload'] for r in resp):
        if not quiet:
            print(f"[+] Running at {target} baud")
        return True
    if not quiet:
        print(f"[!] No response at {target}, reverting")
    ser.baudrate = old
    time.sleep(0.05)
    return False

def negotiate_best_baud(ser):
    for rate in BDD_RATES_ORDERED:
        if rate == ser.baudrate:
            return rate
        if switch_baud(ser, rate):
            return rate
    return ser.baudrate


def connect_device(ser, baud_arg, wait=True):
    if baud_arg == 'auto':
        print("\n[*] Probing device...")
        if wait:
            baud, bid = wait_for_device(ser)
            if baud:
                print()
        else:
            baud, bid = probe_baud(ser)
        if not baud:
            print("[!] Device not responding at any known baud rate")
            return None
        ser.baudrate = baud
    else:
        baud = int(baud_arg)
        ser.baudrate = baud
        print("\n[*] Connecting at %d baud..." % baud)
        if wait:
            while True:
                bid = query_bid(ser)
                if bid:
                    break
                time.sleep(0.5)
        else:
            bid = query_bid(ser)
        if not bid:
            print("[!] No response at %d baud" % baud)
            return None
    print("[+] Device responding at %d baud (BID: %s)" % (ser.baudrate, bid))
    return bid


def enter_bootloader(ser, max_retries=3, enter_cmd='P S #BLL 0001', platform=None,
                     preserve_settings=False):
    """Enter bootloader mode. Returns bootloader BID on success, None on failure."""
    for retry in range(max_retries):
        if retry > 0:
            print(f"[*] Retry {retry}/{max_retries-1}...")
            time.sleep(0.3)

        # Quick probe: BLS tells us where we are
        reset_input_buffer(ser)
        print("[*] Checking device...")
        bls = query_bls(ser, timeout=0.3, platform=platform)

        if bls is not None and bls >= 1:
            # Already in bootloader, just grab BID and go
            print(f"[+] Already in bootloader (BLS={bls})")
            bid = query_bid(ser)
            if bid:
                return bid

        if bls is None:
            # No response device may be mid-reset or off
            # Try one more BLS with slightly longer timeout
            bls = query_bls(ser, timeout=0.3, platform=platform)
            if bls is not None and bls >= 1:
                print(f"[+] Already in bootloader (BLS={bls})")
                bid = query_bid(ser)
                if bid:
                    return bid
            if bls is None:
                continue

        # BLS=0 (CDX running)
        if preserve_settings and bls == 0:
            # Calibration only exits through Standby; it rejects ROP=5.
            if query_boot_var(ser, 'ZRM') == 6:
                send_cmd(ser, 'P S #ROP 0000', quiet=True)
                continue
            print("[*] Preserving settings (ROP=5)...")
            send_cmd(ser, 'P S #ROP 0005', quiet=True)
            if query_boot_var(ser, 'ROP') != 5:
                raise RuntimeError('Cannot set ROP=5 to preserve settings')

        print("[*] Triggering reboot...")
        reset_input_buffer(ser)
        ser.write(build_q_frame(enter_cmd))
        ser.flush()
        time.sleep(0.05)
        reset_input_buffer(ser)

        # Poll with spacing after reboot.
        print("[*] Waiting for bootloader...")
        t0 = time.time()
        time.sleep(0.2)
        for _ in range(60):
            bls = query_bls(ser, timeout=0.3, platform=platform)
            if bls is not None and bls >= 1:
                print(f"[+] Bootloader caught at t+{time.time()-t0:.2f}s (BLS={bls})")
                time.sleep(0.2)
                reset_input_buffer(ser)
                bid = query_bid(ser)
                if bid:
                    return bid
                break
            elif bls == 0:
                # BLL is rejected during UpgradePrep; retry until Upgrade is ready.
                ser.write(build_q_frame(enter_cmd))
                ser.flush()
                time.sleep(0.3)

        print("[!] Failed to catch bootloader")
    return None

def _finish_erase(ser, initial_responses, timeout=30.0):
    """Collect P-ACKs until R-frame. Returns baud from R-frame or None on failure."""
    # S9's first P echo has a damaged CRC (overlapping RX/TX buffer copy).
    # Keep the existing burst reader here; P only indicates progress.
    t0 = time.time()
    p_count = 0
    for r in initial_responses:
        p = r['payload'].decode('ascii', errors='replace')
        if r['type'] == 'E':
            raise RuntimeError(f"erase rejected: {p}")
        if r['type'] == 'P':
            p_count += 1
        elif r['type'] == 'R':
            print(f"    Erase done: {p} ({p_count} ACKs)")
            if '= ' in p:
                try:
                    return int(p.split('= ', 1)[1].strip(), 16)
                except (ValueError, IndexError):
                    pass
            return 0
    while time.time() - t0 < timeout:
        _, responses = read_responses(ser, timeout=0.5)
        for r in responses:
            p = r['payload'].decode('ascii', errors='replace')
            if r['type'] == 'E':
                raise RuntimeError(f"erase rejected: {p}")
            if r['type'] == 'P':
                p_count += 1
                sys.stdout.write(f"\r    Erase progress: {p_count} ACKs...")
                sys.stdout.flush()
            elif r['type'] == 'R':
                print(f"\r    Erase done: {p} ({p_count} ACKs)          ")
                if '= ' in p:
                    try:
                        return int(p.split('= ', 1)[1].strip(), 16)
                    except (ValueError, IndexError):
                        pass
                return 0
            else:
                print(f"\n    [{r['type']}] {p}")
    print(f"\n[!] Erase timeout ({p_count} ACKs)")
    return None


def wait_for_erase(ser, block_id, timeout=30.0):
    print("[*] Waiting for erase completion...")
    return _finish_erase(ser, [], timeout=timeout)

def check_block_crc(data: bytes, block_id: str) -> tuple:
    stored = (data[-2] << 8) | data[-1]
    computed = crc16_ccitt(data[:-2])
    return stored, computed, stored == computed

def fix_block_crc(data: bytearray, block_id: str) -> int:
    crc = crc16_ccitt(data[:-2])
    data[-2] = (crc >> 8) & 0xFF
    data[-1] = crc & 0xFF
    return crc



def detect_input(file_data: bytes, block_args: list, include_bootloader: bool, blocks: dict,
                 raw: bool = False):
    """
    Determine what to flash based on file size and --block argument(s).
    Returns list of (block_id, data_bytes, flash_start_addr) tuples.
    """
    fsize = len(file_data)
    is_full_image = (fsize == FULL_IMAGE_SIZE)
    has_cmx = 'CMX' in blocks

    if block_args:
        requested = []
        for arg in block_args:
            key = arg.lower()
            if key == 'all':
                if has_cmx:
                    requested.extend(['BLX', 'CMX'])
                else:
                    requested.extend(['BLX', 'CCX', 'CDX'])
            else:
                block_id = BLOCK_ALIASES.get(key)
                if not block_id:
                    print(f"[!] Unknown block '{arg}'. Use: config, firmware, all, bootloader"
                          + (", cmx" if has_cmx else ""))
                    return None
                if block_id == 'CMX' and not has_cmx:
                    print(f"[!] CMX not supported on this platform. Use --block config --block firmware")
                    return None
                requested.append(block_id)
    else:
        if has_cmx:
            requested = ['BLX', 'CMX']
        else:
            requested = ['BLX', 'CCX', 'CDX']

    # Deduplicate preserving order
    seen = set()
    unique = []
    for bid in requested:
        if bid not in seen:
            seen.add(bid)
            unique.append(bid)

    jobs = []
    for block_id in unique:
        if block_id == 'BLX' and not include_bootloader:
            print(f"[*] Skipping {block_id} (use --include-bootloader to include)")
            continue

        blk = blocks[block_id]
        if is_full_image:
            data = file_data[blk['file_offset']:blk['file_offset'] + blk['size']]
        elif len(unique) == 1 and fsize == blk['size']:
            data = file_data
        elif raw and len(unique) == 1 and fsize <= blk['size']:
            data = file_data
        else:
            print(f"[!] Need full image ({FULL_IMAGE_SIZE} bytes) for this operation")
            return None

        jobs.append((block_id, bytearray(data), blk['flash_start']))

    if not jobs:
        print("[!] No blocks to flash")
        return None

    # Sort by flash address (BLX before CMX/CCX/CDX)
    jobs.sort(key=lambda j: j[2])
    return jobs


def connect_dump_bootloader(ser, args):
    device_bid = connect_device(ser, args.baud, wait=not args.no_wait)
    if not device_bid:
        raise RuntimeError("device connection failed")
    if device_bid not in DUMP_SUPPORTED_BIDS:
        raise RuntimeError("dump/EEPROM service requires %s, got %s" %
                           (' or '.join(sorted(DUMP_SUPPORTED_BIDS)), device_bid))
    platform = _platform(device_bid)
    default_baud = platform['default_baud']
    if not args.no_enter:
        if ser.baudrate != default_baud:
            switch_baud(ser, default_baud)
        boot_bid = enter_bootloader(ser, enter_cmd=platform['enter_cmd'], platform=platform)
        if boot_bid != device_bid:
            raise RuntimeError("unexpected bootloader BID: %s" % boot_bid)
    elif (query_bls(ser, timeout=0.5) or 0) < 1:
        raise RuntimeError("--no-enter requires the device to be in bootloader mode")

    if args.baud == 'auto':
        print("\n[*] Negotiating baud rate...")
        negotiate_best_baud(ser)
    else:
        target = int(args.baud)
        if target != ser.baudrate and not switch_baud(ser, target):
            raise RuntimeError("failed to switch to %d baud" % target)
    return device_bid, platform


def transfer_eeprom(ser, args, restore_data=None):
    bid, platform = connect_dump_bootloader(ser, args)
    module = load_eeprom_module(bid, args.eeprom_module)
    try:
        upload_eeprom_module(ser, module)
        if restore_data is not None:
            restore_eeprom_data(ser, restore_data)
        else:
            print('[*] Dumping 262,144 EEPROM bytes...')
            dump_memory(ser, args.dump_eeprom, EEPROM_SIZE, b'R')
            print('[+] EEPROM saved: %s' % args.dump_eeprom)
    except (OSError, RuntimeError, KeyboardInterrupt):
        print('[!] EEPROM operation incomplete; no reset sent. '
              'Keep the device in BLX and retry the operation.')
        raise
    reset_device(ser, platform, reset=not args.no_reset)
    return 0


def dump_memory(ser, output_path, size, command, validate=None):
    """Write chunks to .part; publish the dump only after transfer and validation."""
    part_path = output_path + '.part'
    started = time.monotonic()
    tty_progress = sys.stdout.isatty()
    next_percent = 5
    with open(part_path, 'wb') as output:
        for offset, chunk in read_memory(ser, command, size):
            output.write(chunk)
            done = offset + len(chunk)
            progress = ("    %s/%s (%3d%%)" %
                        (f"{done:,}", f"{size:,}", done * 100 // size))
            if tty_progress:
                sys.stdout.write("\r" + progress)
                sys.stdout.flush()
            elif done == size or done * 100 // size >= next_percent:
                print(progress)
                next_percent += 5
        output.flush()
        os.fsync(output.fileno())
    elapsed = time.monotonic() - started
    if tty_progress:
        print(" in %.1fs" % elapsed)
    else:
        print("[*] Dump completed in %.1fs" % elapsed)

    if validate is not None:
        with open(part_path, 'rb') as dumped:
            validate(dumped.read())
    os.replace(part_path, output_path)


def validate_firmware_dump(image, device_bid):
    blocks = get_blocks(device_bid)
    print("[*] CRC validation:")
    crc_ok = True
    for block_id in ('BLX', 'CCX', 'CDX'):
        block = blocks[block_id]
        data = image[block['file_offset']:block['file_offset'] + block['size']]
        stored, computed, match = check_block_crc(data, block_id)
        print("    [%s] %s: stored=0x%04X computed=0x%04X %s" %
              ('+' if match else '!', block_id, stored, computed,
               'OK' if match else 'MISMATCH'))
        crc_ok = crc_ok and match
    if not crc_ok:
        raise RuntimeError('dumped image failed block CRC validation; partial file kept as .part')


def reset_device(ser, platform, reset=True):
    default_baud = platform.get('default_baud', 57600)
    if platform.get('baud_method', 'bdd') == 'bdd' and ser.baudrate != default_baud:
        if not switch_baud(ser, default_baud):
            raise RuntimeError('transfer completed, but baud reset failed; no reset sent')
    if reset:
        print('[*] Resetting device...')
        send_cmd(ser, platform.get('reset_cmd', 'P S #RES 0001'), timeout=2.0)


def dump_firmware(ser, output_path, args):
    device_bid, platform = connect_dump_bootloader(ser, args)
    upload_eeprom_module(ser, load_eeprom_module(device_bid, args.eeprom_module))
    print("\n[*] Dumping 1,048,576 bytes @ %d baud..." % ser.baudrate)
    dump_memory(ser, output_path, FULL_IMAGE_SIZE, b'D',
                validate=lambda image: validate_firmware_dump(image, device_bid))
    print("[+] Firmware saved: %s" % output_path)
    reset_device(ser, platform, reset=not args.no_reset)
    return 0


CHUNK_SIZE = 250
FLASH_COMPLETE_OK = 0x0000
FLASH_IN_PROGRESS = 0x700D


def check_flash_status(ser, status_var, expected, context, wait_final=False,
                       timeout=1.0, confirmation=False):
    """Return the status verdict; missing post-transfer evidence is not failure."""
    try:
        status = query_boot_var(ser, status_var, timeout=timeout, wait_final=wait_final,
                                discard_input=not confirmation)
    except OSError as exc:
        if confirmation:
            raise FlashUnconfirmed(f"Cannot read {status_var} {context}: {exc}") from exc
        raise
    if status is None:
        if confirmation:
            raise FlashUnconfirmed(f"No valid {status_var} response {context}")
        print(f"\n[!] No {status_var} response {context}")
        return False
    if status != expected:
        print(f"\n[!] Unexpected {status_var} {context}: {status:04X}, expected {expected:04X}")
        return False
    return True


def write_transfer_frame(ser, frame, context):
    """Send once; a short or failed write does not establish the device result."""
    try:
        written = ser.write(frame)
    except OSError as exc:
        raise FlashUnconfirmed(f"Transport error sending {context}: {exc}") from exc
    if written != len(frame):
        raise FlashUnconfirmed(f"Short write of {context}: {written}/{len(frame)} bytes")


def flash_block(ser, block_id, data, flash_start, blocks, dry_run=False,
                skip_completion=False, status_var=None, timing=False,
                end_record=None, default_baud=57600, completion_timeout=3.0):
    """Erase and flash a block; raise FlashUnconfirmed if its result is unknown.
    skip_completion (Air10 only): don't send completion frame. Bootloader stays in state 1
    (FLASH_ACTIVE) until mode 5 timeout fires (~2s after last F-frame), then
    does a plain reset. Next boot: BKP7R=0x7003 (non-zero), no SF magic ->
    bootloader enters mode 1 (infinite timeout), waiting for commands.
    Used when flashing BLX followed by more blocks to avoid the fast_boot_reset
    path that completion triggers (state=2 + BKP7R=0 -> BKP6R gate -> skip BL).
    """
    blk = blocks[block_id]
    block_name = block_id.encode()

    # Trim trailing 0xFF
    data_end = len(data)
    while data_end > 0 and data[data_end-1] == 0xFF:
        data_end -= 1
    if data_end == 0:
        print(f"[!] {block_id} data is all 0xFF, nothing to write")
        return True
    data_end = (data_end + 3) & ~3

    print(f"\n{'='*60}")
    print(f"  Block: {block_id} ({blk['name']})")
    print(f"  Flash: 0x{flash_start:08X} - 0x{flash_start + len(data):08X}")
    print(f"  Data:  {data_end:,} bytes (trimmed from {len(data):,})")
    print(f"{'='*60}")

    if dry_run:
        print("  [DRY RUN] Would erase and flash this block")
        return True

    # ERASE
    attempts = 1 if end_record is not None else 3
    for attempt in range(attempts):
        print(f"\n[*] Erasing {block_id} (attempt {attempt+1})...")
        reset_input_buffer(ser)
        ser.write(build_q_frame(blk['erase_cmd']))
        ser.flush()
        erase_baud = _finish_erase(ser, [], timeout=30.0)

        if erase_baud is not None:
            break
        elif attempt + 1 < attempts:
            print("[!] Erase stalled, retrying...")
            time.sleep(1.0)
        else:
            print("[!] Erase failed")
            return False

    # S9 Bootloader may switch baud after erase (reported in R-frame as hex value).
    # E100 = 57600, 1C200 = 115200
    KNOWN_BAUDS = {9600, 19200, 38400, 57600, 115200, 230400, 460800, 921600}
    if erase_baud and erase_baud in KNOWN_BAUDS and erase_baud != ser.baudrate:
        print(f"[*] Bootloader switched to {erase_baud} baud, following...")
        ser.baudrate = erase_baud

    # After the R-frame, the s9 bootloader reconfigures USART
    # Any bytes we send during this window get discarded.
    time.sleep(0.3)

    # WRITE
    seq = 0
    offset = 0
    frame_count = 0
    t0 = time.monotonic()
    previous_write_end = None
    max_write = (0.0, 0)
    max_flush = (0.0, 0)
    max_gap = (0.0, 0)

    print(f"\n[*] Writing {data_end:,} bytes @ {ser.baudrate} baud...")

    while offset < data_end:
        chunk = data[offset:offset + CHUNK_SIZE]
        if not chunk:
            break
        address = flash_start + offset
        f_frame = build_f_frame(block_name, seq, build_record_03(address, bytes(chunk)))
        frame_index = frame_count + 1
        write_start = time.monotonic()
        if previous_write_end is not None:
            gap = write_start - previous_write_end
            if gap > max_gap[0]:
                max_gap = (gap, frame_index)
        write_transfer_frame(ser, f_frame, f'data frame {frame_index}')
        write_end = time.monotonic()
        write_time = write_end - write_start
        if write_time > max_write[0]:
            max_write = (write_time, frame_index)
        previous_write_end = write_end
        frame_count += 1
        offset += len(chunk)
        seq = (seq + 1) & 0xFF

        if frame_count % 20 == 0:
            flush_start = time.monotonic()
            ser.flush()
            flush_time = time.monotonic() - flush_start
            if flush_time > max_flush[0]:
                max_flush = (flush_time, frame_count)
            elapsed = time.monotonic() - t0
            pct = offset / data_end * 100
            rate = offset / elapsed if elapsed > 0 else 0
            eta = (data_end - offset) / rate if rate > 0 else 0
            sys.stdout.write(
                f"\r    {offset:,}/{data_end:,} ({pct:.0f}%) "
                f"[{rate/1024:.1f} KB/s] ETA {eta:.0f}s"
            )
            sys.stdout.flush()

    flush_start = time.monotonic()
    ser.flush()
    flush_time = time.monotonic() - flush_start
    if flush_time > max_flush[0]:
        max_flush = (flush_time, frame_count)
    elapsed = time.monotonic() - t0
    print(f"\r    {offset:,}/{data_end:,} (100%) sent by host in {elapsed:.1f}s, {frame_count} frames          ")
    if timing:
        print(f"    Timing: max write {max_write[0]:.3f}s at frame {max_write[1]}, "
              f"max flush {max_flush[0]:.3f}s after frame {max_flush[1]}, "
              f"max host gap {max_gap[0]:.3f}s before frame {max_gap[1]}")

    # S9 requires a type-7 end record before the ASCII F completion.
    if end_record is not None:
        record = bytes([end_record, 5]) + struct.pack('>I', flash_start) + b'\0'
        frame = build_f_frame(block_name, seq, record)
        write_transfer_frame(ser, frame, 'transfer end record')
        seq = (seq + 1) & 0xff

    # Completion frame
    if skip_completion and end_record is None:
        print("[*] Skipping completion frame (non-final block)")
        # This query follows every data frame through the bridge. A matching
        # reply establishes that bootloader processing has reached the tail;
        # host flush or TCP acknowledgements cannot establish that themselves.
        if not status_var:
            raise FlashUnconfirmed('No status variable available after transfer')
        print("[*] Waiting for device transfer status...")
        if not check_flash_status(ser, status_var, FLASH_IN_PROGRESS, "after data transfer",
                                  timeout=completion_timeout, confirmation=True):
            return False
        # AirBridge follows BDD, but cannot observe the timeout-driven reset.
        # Restore both UART ends before BLX restarts at its default baud.
        if ser.baudrate != default_baud and not switch_baud(ser, default_baud):
            raise FlashUnconfirmed('Cannot restore default baud before bootloader restart')
        print(f"[*] Waiting for mode 5 timeout (~2s)...")
        time.sleep(2.5)
        reset_input_buffer(ser)
    else:
        print("[*] Sending completion frame...")
        frame = build_completion_frame(block_name, seq)
        write_transfer_frame(ser, frame, 'transfer completion')
        ser.flush()
        if end_record is not None:
            # S9 returns to 57600 before verifying flash and answering PST.
            ser.baudrate = default_baud
        if status_var:
            print("[*] Waiting for device confirmation...")
            if not check_flash_status(ser, status_var, FLASH_COMPLETE_OK,
                                      "after completion", wait_final=end_record is not None,
                                      timeout=completion_timeout, confirmation=True):
                return False
            print(f"[+] Device completion status: {status_var}=0000")
        else:
            raise FlashUnconfirmed('No status variable available after completion')

    return True


def cmd_info(ser, wait=False):
    print("\n[*] Probing device...")
    if wait:
        baud, bid = wait_for_device(ser)
        if baud:
            print()
    else:
        baud, bid = probe_baud(ser)
    if not baud:
        print("[!] Device not responding")
        return 1
    ser.baudrate = baud
    print(f"[+] Device responding at {baud} baud")
    print("\n[*] Device info:")
    for cmd in ["G S #BID", "G S #SID", "G S #CID", "G S #PCB",
                "G S #SRN", "G S #PCD", "G S #PNA", "G S #PST"]:
        send_cmd(ser, cmd, timeout=0.5)
    return 0


def main():
    parser = argparse.ArgumentParser(
        description='ResMed AirSense UART Flash Tool',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Blocks:
  all               BLX + CMX (S10) or BLX + CCX + CDX (S9)
  config (CCX)      Configuration data
  firmware (CDX)    Application firmware
  cmx (CMX)         Config + Firmware combined (S10 only)
  bootloader (BLX)  Bootloader (requires --include-bootloader)

Examples:
  %(prog)s -p /dev/ttyACM0 -f dump.bin                        Flash CMX/CCX+CDX (skip BLX)
  %(prog)s -p /dev/ttyACM0 -f dump.bin --include-bootloader   Flash everything
  %(prog)s -p /dev/ttyACM0 -f dump.bin --block config         Flash config only
  %(prog)s -p /dev/ttyACM0 -f dump.bin --fix-crc              Fix CRC before flash
  %(prog)s -p /dev/ttyACM0 -f dump.bin --dry-run              Validate without flashing
  %(prog)s -p /dev/ttyACM0 -f dump.bin --no-wait              Fail if device not found
  %(prog)s -p /dev/ttyACM0 --info                             Show device info
  %(prog)s -p /dev/ttyACM0 --dump firmware.bin                Dump firmware with a patched BLX
  %(prog)s -p /dev/ttyACM0 --dump-eeprom eeprom.bin            Dump 256 KiB EEPROM
  %(prog)s -p /dev/ttyACM0 --restore-eeprom eeprom.bin --yes   Restore and verify EEPROM
""")
    parser.add_argument('-p', '--port', required=True, help='Serial port or tcp:host[:port]')
    parser.add_argument('--tcp-mode', choices=['raw', 'transparent'], default='transparent',
                        help='TCP mode: transparent (AirBridge, default), raw (dumb proxy)')
    operation = parser.add_mutually_exclusive_group(required=True)
    operation.add_argument('-f', '--file', help='Firmware file to flash')
    operation.add_argument('--dump', metavar='FILE', help='Dump the full firmware image (patched SX577/SX585 BLX required)')
    operation.add_argument('--dump-eeprom', metavar='FILE', help='Dump 256 KiB EEPROM (EEPROM-capable patched SX577/SX585 BLX required)')
    operation.add_argument('--restore-eeprom', metavar='FILE', help='Restore and verify a full 256 KiB EEPROM image')
    operation.add_argument('--info', action='store_true', help='Show device info and exit')
    parser.add_argument('--eeprom-module', metavar='FILE', help='RAM module .bin from the matching BLX build (default: build/blx_eeprom_BID.bin)')
    parser.add_argument('--yes', action='store_true', help='Confirm overwriting EEPROM with --restore-eeprom')
    parser.add_argument('--block', action='append', help='Target block (repeatable): config, firmware, all, bootloader')
    parser.add_argument('--baud', default='auto', help='Transfer baud: auto, 57600, 115200, 460800')
    parser.add_argument('--completion-timeout', type=float, default=3.0, metavar='SECONDS',
                        help='Final status wait (default: 3s; S9 verification allows at least 15s)')
    parser.add_argument('--fix-crc', action='store_true', help='Recalculate and patch CRC')
    parser.add_argument('--force', action='store_true', help='Flash even with bad CRC')
    parser.add_argument('--include-bootloader', action='store_true', help='Allow bootloader writes')
    parser.add_argument('--dry-run', action='store_true', help='Validate only, do not flash')
    parser.add_argument('--no-reset', action='store_true', help='Do not reset device after transfer')
    parser.add_argument('--no-enter', action='store_true', help='Skip bootloader entry')
    parser.add_argument('--factory-reset', action='store_true',
                        help='Reset AirSense/AirCurve 10 settings to firmware defaults (default: preserve)')
    parser.add_argument('--raw', action='store_true', help='Flash raw image smaller than block size')
    parser.add_argument('--no-wait', action='store_true', help='Fail immediately if device not found')
    parser.add_argument('--timing', action='store_true',
                        help='Report serial write, flush, and inter-frame timing')
    parser.add_argument('--yolo', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()

    if not math.isfinite(args.completion_timeout) or args.completion_timeout <= 0:
        parser.error('--completion-timeout must be a positive finite number')
    eeprom = bool(args.dump_eeprom or args.restore_eeprom)
    if eeprom and (args.block or args.raw or args.force or args.fix_crc or
                   args.include_bootloader or args.factory_reset or args.yolo):
        parser.error('firmware flashing options cannot be used for EEPROM transfers')
    if args.eeprom_module and not (eeprom or args.dump):
        parser.error('--eeprom-module requires --dump or an EEPROM operation')
    if args.yes and not args.restore_eeprom:
        parser.error('--yes requires --restore-eeprom')
    if args.dump_eeprom and args.dry_run:
        parser.error('--dry-run does not apply to EEPROM dump')
    if args.restore_eeprom and not (args.yes or args.dry_run):
        parser.error('--restore-eeprom requires --yes to overwrite all EEPROM contents')
    restore_data = None
    if args.restore_eeprom:
        try:
            restore_data = Path(args.restore_eeprom).read_bytes()
        except OSError as exc:
            parser.error(str(exc))
        if len(restore_data) != EEPROM_SIZE:
            parser.error('EEPROM restore requires exactly 262144 bytes')
        print('[*] Restore file: %s' % args.restore_eeprom)
        if args.dry_run:
            print('[DRY RUN] EEPROM image size checked. No device connection or writes.')
            return 0

    if args.port.startswith('tcp:'):
        ser = open_tcp(args.port, args.tcp_mode, timeout=1.0, hold=bool(eeprom or args.dump))
    else:
        ser = serial.Serial(args.port, 57600, timeout=1.0)

    try:
        if args.info:
            return cmd_info(ser, wait=not args.no_wait)

        if args.dump:
            return dump_firmware(ser, args.dump, args)

        if eeprom:
            return transfer_eeprom(ser, args, restore_data)

        with open(args.file, 'rb') as f:
            file_data = f.read()
        print(f"[*] Loaded: {args.file} ({len(file_data):,} bytes)")

        is_full_image = (len(file_data) == FULL_IMAGE_SIZE)
        flashing_blx = args.include_bootloader

        if args.raw:
            if not args.block or len(args.block) != 1:
                parser.error("--raw requires exactly one --block")
            if args.block[0].lower() == 'all':
                parser.error("--raw cannot be used with --block all")

        image_bid = None
        if is_full_image:
            image_bid = bid_from_image(file_data)
            if image_bid:
                print(f"[*] Image bootloader: {image_bid}")

        blx_only = (args.block is not None and all(
            BLOCK_ALIASES.get(a.lower(), a.upper()) == 'BLX' for a in args.block))

        # offline validation (no device contact)
        # for full images we can resolve layout from image BID alone.
        # device BID is only needed later for cross-flash checks.

        if is_full_image and image_bid:
            active_bid = image_bid
        else:
            # standalone block file need device BID to pick layout.
            active_bid = None

        if active_bid:
            blocks = get_blocks(active_bid)
            if not blocks:
                if not args.yolo:
                    print(f"[!] Unknown block layout for BID: {active_bid}")
                    return 1
                print(f"[!] --yolo: unknown BID {active_bid}, no block map available")
                return 1

            if active_bid not in SUPPORTED_BIDS:
                if not args.yolo:
                    print(f"[!] BID {active_bid} is not supported")
                    return 1
                print(f"[!] --yolo: proceeding with non-whitelisted BID {active_bid}")

            # verify CDX header at expected offset
            if is_full_image and flashing_blx and not blx_only:
                cdx = blocks['CDX']
                cdx_hdr = file_data[cdx['file_offset']:cdx['file_offset'] + 10]
                if not (len(cdx_hdr) == 10 and cdx_hdr[:2] == b'SX'
                        and cdx_hdr[5:6] == b'-'
                        and all(0x30 <= b <= 0x39 for b in cdx_hdr[2:5])
                        and all(0x30 <= b <= 0x39 for b in cdx_hdr[6:10])):
                    print(f"[!] No valid CDX header at image offset 0x{cdx['file_offset']:X}")
                    print(f"[!] Expected SXnnn-nnnn, got: {cdx_hdr}")
                    print(f"[!] Image layout does not match {active_bid}")
                    if not args.yolo:
                        return 1

            jobs = detect_input(file_data, args.block, args.include_bootloader, blocks,
                               raw=args.raw)
            if not jobs:
                return 1

            print(f"\n[*] Flash plan ({active_bid} layout):")
            for block_id, data, flash_start in jobs:
                blk = blocks[block_id]
                print(f"    {block_id} ({blk['name']}): {len(data):,} bytes @ 0x{flash_start:08X}")

            if args.raw:
                print(f"\n[*] CRC validation: skipped (raw mode)")
            else:
                print(f"\n[*] CRC validation:")
                crc_ok = True
                for block_id, data, _ in jobs:
                    if block_id == 'CMX':
                        ccx_size = blocks['CCX']['size']
                        cdx_offset = blocks['CDX']['file_offset'] - blocks['CMX']['file_offset']
                        sub_blocks = [
                            ('CCX', 0, ccx_size),
                            ('CDX', cdx_offset, len(data)),
                        ]
                    else:
                        sub_blocks = [(block_id, 0, len(data))]

                    for sub_id, start, end in sub_blocks:
                        sub_data = data[start:end]
                        stored, computed, match = check_block_crc(sub_data, sub_id)
                        status = "OK" if match else "MISMATCH"
                        icon = "+" if match else "!"
                        print(f"    [{icon}] {sub_id}: stored=0x{stored:04X} computed=0x{computed:04X} {status}")

                        if not match:
                            if args.fix_crc:
                                crc = crc16_ccitt(data[start:end-2])
                                data[end-2] = (crc >> 8) & 0xFF
                                data[end-1] = crc & 0xFF
                                print(f"        Fixed CRC -> 0x{crc:04X}")
                            elif not args.force:
                                crc_ok = False

                if not crc_ok:
                    print("\n[!] CRC mismatch. Use --fix-crc to repair or --force to ignore.")
                    return 1

            if args.dry_run:
                print("\n[DRY RUN] Validation complete. No changes made.")
                for block_id, data, flash_start in jobs:
                    flash_block(ser, block_id, data, flash_start, blocks, dry_run=True)
                return 0

        # online phase (device contact required)

        device_bid = connect_device(ser, args.baud, wait=not args.no_wait)
        if not device_bid:
            return 1

        # if we couldn't resolve layout offline (standalone block file),
        # use device BID now
        if active_bid is None:
            active_bid = device_bid
            blocks = get_blocks(active_bid)
            if not blocks:
                if not args.yolo:
                    print(f"[!] Unknown block layout for BID: {active_bid}")
                    return 1
                print(f"[!] --yolo: unknown BID {active_bid}")
                return 1

            if active_bid not in SUPPORTED_BIDS:
                if not args.yolo:
                    print(f"[!] BID {active_bid} is not supported")
                    return 1
                print(f"[!] --yolo: proceeding with non-whitelisted BID {active_bid}")

            jobs = detect_input(file_data, args.block, args.include_bootloader, blocks,
                               raw=args.raw)
            if not jobs:
                return 1

            print(f"\n[*] Flash plan ({active_bid} layout):")
            for block_id, data, flash_start in jobs:
                blk = blocks[block_id]
                print(f"    {block_id} ({blk['name']}): {len(data):,} bytes @ 0x{flash_start:08X}")

            if args.raw:
                print(f"\n[*] CRC validation: skipped (raw mode)")
            else:
                print(f"\n[*] CRC validation:")
                crc_ok = True
                for block_id, data, _ in jobs:
                    sub_blocks = [(block_id, 0, len(data))]
                    for sub_id, start, end in sub_blocks:
                        sub_data = data[start:end]
                        stored, computed, match = check_block_crc(sub_data, sub_id)
                        status = "OK" if match else "MISMATCH"
                        icon = "+" if match else "!"
                        print(f"    [{icon}] {sub_id}: stored=0x{stored:04X} computed=0x{computed:04X} {status}")
                        if not match:
                            if args.fix_crc:
                                crc = crc16_ccitt(data[start:end-2])
                                data[end-2] = (crc >> 8) & 0xFF
                                data[end-1] = crc & 0xFF
                                print(f"        Fixed CRC -> 0x{crc:04X}")
                            elif not args.force:
                                crc_ok = False

                if not crc_ok:
                    print("\n[!] CRC mismatch. Use --fix-crc to repair or --force to ignore.")
                    return 1

            if args.dry_run:
                print("\n[DRY RUN] Validation complete. No changes made.")
                for block_id, data, flash_start in jobs:
                    flash_block(ser, block_id, data, flash_start, blocks, dry_run=True)
                return 0

        # cross-flash check (needs both image and device BID)
        if is_full_image and image_bid and image_bid != device_bid:
            if not args.yolo:
                print(f"[!] Cross-flash: image BID={image_bid}, device BID={device_bid}")
                return 1
            print(f"[!] --yolo: cross-flashing {image_bid} image onto {device_bid} device")
            if not flashing_blx:
                print(f"[!] WARNING: not replacing bootloader -- layout mismatch likely")

        # resolve platform from whatever BID we have
        plat = _platform(active_bid) or _platform(device_bid) or {}
        enter_cmd = plat.get('enter_cmd', 'P S #BLL 0001')
        reset_cmd = plat.get('reset_cmd', 'P S #RES 0001')
        default_baud = plat.get('default_baud', 57600)
        can_bdd = plat.get('baud_method', 'bdd') == 'bdd'
        flash_status = plat.get('flash_status')

        preserve_settings = (not args.factory_reset and not args.no_enter
                             and (_platform(device_bid) or {}).get('rop_settings', False)
                             and any(block_id != 'BLX' for block_id, _, _ in jobs))

        if not args.no_enter:
            if ser.baudrate != default_baud:
                if can_bdd:
                    switch_baud(ser, default_baud)
                else:
                    ser.baudrate = default_baud

            bl_bid = enter_bootloader(ser, enter_cmd=enter_cmd, platform=plat,
                                      preserve_settings=preserve_settings)
            if not bl_bid:
                return 1

            # active_bid may have come from image file; re-resolve if device BID differs
            if bl_bid != active_bid:
                bl_blocks = get_blocks(bl_bid)
                if bl_blocks:
                    active_bid = bl_bid
                    blocks = bl_blocks
                    plat = _platform(bl_bid) or plat
                    can_bdd = plat.get('baud_method', 'bdd') == 'bdd'
                    flash_status = plat.get('flash_status')
                    reset_cmd = plat.get('reset_cmd')
                    jobs = detect_input(file_data, args.block, args.include_bootloader,
                                        blocks, raw=args.raw)
                    if not jobs:
                        return 1

        if can_bdd:
            if args.baud == 'auto':
                print("\n[*] Negotiating baud rate...")
                negotiate_best_baud(ser)
            else:
                target = int(args.baud)
                if target != ser.baudrate:
                    switch_baud(ser, target)

        for i, (block_id, data, flash_start) in enumerate(jobs):
            is_last = (i == len(jobs) - 1)
            if i > 0:
                if reset_cmd:
                    # Re-enter bootloader for next block.
                    # Previous block either sent completion (fast_boot_reset ->
                    # CDX -> need BLL + catch) or skipped it (mode 5 timeout ->
                    # plain reset -> BL with infinite timeout, just probe BLS).
                    print("\n[*] Re-entering bootloader for next block...")
                    time.sleep(0.5)
                    if ser.baudrate != default_baud:
                        ser.baudrate = default_baud
                    if not enter_bootloader(ser, 30, enter_cmd=enter_cmd, platform=plat,
                                            preserve_settings=preserve_settings):
                        return 1
                    if can_bdd:
                        if args.baud == 'auto':
                            negotiate_best_baud(ser)
                        else:
                            target = int(args.baud)
                            if target != ser.baudrate:
                                switch_baud(ser, target)
                else:
                    # Wait for the device to return after transfer completion.
                    ser.baudrate = default_baud
                    print(f"\n[*] Waiting for device to continue with {block_id}...")
                    if not args.no_wait:
                        while _extract_bid(send_cmd(ser, "G S #BID", timeout=0.3, quiet=True)[1]):
                            time.sleep(0.3)
                        baud, bid = wait_for_device(ser)
                        if not baud:
                            return 1
                        print()
                        ser.baudrate = baud
                    else:
                        baud, bid = probe_baud(ser)
                        if not baud:
                            print("[!] Device not responding")
                            return 1
                        ser.baudrate = baud
                    print("[*] Entering bootloader...")
                    bl_bid = enter_bootloader(ser, enter_cmd=enter_cmd, platform=plat)
                    if not bl_bid:
                        return 1

            if plat.get('end_record') is not None:
                if not check_flash_status(ser, flash_status, FLASH_COMPLETE_OK,
                                          "before erasing"):
                    return 1

            # Air10: skip completion on BLX when more blocks follow.
            # Avoids fast_boot_reset (completion -> state=2 + BKP7R=0 -> BKP6R
            # gate -> boots CDX, no BL window). Without completion: mode 5
            # timeout (~2s) -> plain reset -> BL with infinite timeout.
            skip = (plat.get('end_record') is None and block_id == 'BLX' and not is_last)
            if not flash_block(ser, block_id, data, flash_start, blocks,
                               skip_completion=skip, status_var=flash_status,
                               timing=args.timing, end_record=plat.get('end_record'),
                               default_baud=default_baud, completion_timeout=args.completion_timeout):
                print(f"\n[!] Failed to flash {block_id}")
                return 1

        if not args.no_reset:
            if reset_cmd:
                reset_device(ser, plat)
                if flash_status:
                    print("[*] Waiting for application...")
                    ok, bls, ble = wait_for_application(ser, flash_status)
                    if not ok:
                        state = "no BLS response" if bls is None else f"BLS={bls:04X}"
                        error = "" if ble is None else f", BLE={ble:04X}"
                        print(f"[!] Application startup not confirmed ({state}{error})")
                        return 3 if bls in (None, 1) and ble in (None, 0) else 1
                    print("[+] Application responding (BLS=0000)")

        print("\n[+] Flash complete!")
        return 0

    except FlashUnconfirmed as exc:
        print(f"\n[!] {exc}")
        print("[!] Write result is unconfirmed; no automatic retry was attempted.")
        return 3
    except (OSError, RuntimeError) as exc:
        print(f"[!] {exc}")
        return 1
    finally:
        ser.close()
if __name__ == "__main__":
    sys.exit(main())

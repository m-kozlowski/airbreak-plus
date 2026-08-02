#!/usr/bin/env python3
"""
ResMed AirSense UART Flash Tool

Transfers firmware through the ResMed AirSense UART bootloader protocol.
Supports block flashing and full-image dumps with CRC validation.

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


# Platform profiles, keyed by bootloader BID prefix.
PLATFORMS = {
    'SX577': {'baud_method': 'bdd', 'default_baud': 57600,
              'baud_rates': {57600: '0000', 115200: '0001', 460800: '0002'},
              'enter_cmd': 'P S #BLL 0001', 'reset_cmd': 'P S #RES 0001',
              'flash_status': 'BLE'},
    'SX585': {'baud_method': 'bdd', 'default_baud': 57600,
              'baud_rates': {57600: '0000', 115200: '0001', 460800: '0002'},
              'enter_cmd': 'P S #BLL 0001', 'reset_cmd': 'P S #RES 0001',
              'flash_status': 'BLE'},
    'SX525': {'baud_method': 'fixed', 'default_baud': 57600,
              'baud_rates': {57600: 'E100'},
              'enter_cmd': 'P S #RES 0001', 'reset_cmd': None},
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

SUPPORTED_BIDS = {'SX577-0200', 'SX525-0300', 'SX525-0400'}

FULL_IMAGE_SIZE = 0x100000
DUMP_CHUNK_SIZE = 240
DUMP_FRAME_TYPE = 'O'

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

def parse_responses(data: bytes) -> list:
    responses = []
    i = 0
    while i < len(data):
        if data[i:i+1] == b'U' and i+1 < len(data) and data[i+1:i+2] != b'U':
            try:
                ft = chr(data[i+1])
                if ft in 'EFKLPQR':
                    length = int(data[i+2:i+5], 16)
                    if i + length <= len(data):
                        raw_payload = data[i+5:i+length-4]
                        payload = raw_payload.replace(b'UU', b'U')
                        responses.append({'type': ft, 'payload': payload})
                        i += length
                        continue
            except (ValueError, IndexError):
                pass
        i += 1
    return responses

def read_responses(ser, timeout=1.0):
    old_timeout = ser.timeout
    ser.timeout = 0.02
    data = b''
    deadline = time.time() + timeout
    while time.time() < deadline:
        chunk = ser.read(4096)
        if chunk:
            data += chunk
            # Got data but do one more quick read for any trailing bytes
            trail_deadline = time.time() + 0.02
            while time.time() < trail_deadline:
                chunk = ser.read(4096)
                if chunk:
                    data += chunk
                    trail_deadline = time.time() + 0.02  # extend if still coming
            break
    ser.timeout = old_timeout
    return data, parse_responses(data)


def read_frame(ser, timeout=1.0):
    """Read and CRC-check one complete ResMed frame."""
    old_timeout = ser.timeout
    ser.timeout = 0.02
    data = bytearray()
    deadline = time.time() + timeout
    try:
        while time.time() < deadline:
            chunk = ser.read(512)
            if chunk:
                data.extend(chunk)

            while True:
                try:
                    start = data.index(ord('U'))
                except ValueError:
                    data.clear()
                    break
                if start:
                    del data[:start]
                if len(data) < 5:
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
                    break

                raw = bytes(data[:length])
                try:
                    stored_crc = int(raw[-4:], 16)
                except ValueError:
                    del data[0]
                    continue
                return {
                    'type': chr(raw[1]),
                    'payload': raw[5:-4].replace(b'UU', b'U'),
                    'crc_ok': stored_crc == crc16_ccitt(raw[:-4]),
                    'raw': raw,
                }
        return None
    finally:
        ser.timeout = old_timeout


def request_dump_chunk(ser, offset, length, retries=3):
    request = b'D' + struct.pack('<IH', offset, length)
    last_error = "no response"
    for _ in range(retries):
        ser.reset_input_buffer()
        ser.write(build_frame(DUMP_FRAME_TYPE, request))
        ser.flush()
        frame = read_frame(ser, timeout=1.0)
        if frame is None:
            last_error = "no response"
            continue
        if frame['type'] != DUMP_FRAME_TYPE:
            last_error = "unexpected frame type %s" % frame['type']
            continue
        if not frame['crc_ok']:
            last_error = "CRC mismatch"
            continue
        payload = frame['payload']
        if len(payload) < 7:
            last_error = "short response"
            continue
        response_offset, response_length = struct.unpack_from('<IH', payload, 1)
        if payload[0:1] == b'E':
            raise RuntimeError("bootloader rejected dump range 0x%05X+%d" %
                               (offset, length))
        if (payload[0:1] != b'd' or response_offset != offset or
                response_length != length or len(payload) != 7 + length):
            last_error = "response range mismatch"
            continue
        return payload[7:]
    raise RuntimeError("dump failed at 0x%05X: %s" % (offset, last_error))

def send_cmd(ser, cmd_str, timeout=2.0, quiet=False):
    ser.reset_input_buffer()
    ser.write(build_q_frame(cmd_str))
    ser.flush()
    raw, responses = read_responses(ser, timeout=timeout)
    if not quiet:
        for r in responses:
            print(f"  [{r['type']}] {r['payload'].decode('ascii', errors='replace')}")
    return raw, responses

def sync_uart(ser):
    ser.reset_input_buffer()
    ser.write(b'\x55' * 128)
    ser.flush()
    time.sleep(0.05)
    ser.reset_input_buffer()


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

def _extract_hex_var(responses, name):
    marker = name.encode()
    for r in responses:
        if marker in r['payload']:
            text = r['payload'].decode('ascii', errors='replace')
            if '= ' in text:
                try:
                    return int(text.split('= ', 1)[1].strip().rstrip('\x00'), 16)
                except (ValueError, IndexError):
                    pass
    return None

def query_boot_var(ser, name, timeout=0.3):
    _, resp = send_cmd(ser, f"G S #{name}", timeout=timeout, quiet=True)
    return _extract_hex_var(resp, name)

def query_bls(ser, timeout=0.3):
    """Query bootloader status. Returns 0=CDX, 1=bootloader, 2=bootloader(invalid fw), None=no response."""
    return query_boot_var(ser, 'BLS', timeout)

def wait_for_application(ser, status_var, timeout=15.0):
    deadline = time.time() + timeout
    last_bls = None
    while time.time() < deadline:
        bls = query_bls(ser, timeout=0.3)
        if bls == 0:
            return True, bls, None
        if bls is not None:
            last_bls = bls
        time.sleep(0.2)
    return False, last_bls, query_boot_var(ser, status_var, timeout=0.5)

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
        ser.reset_input_buffer()
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
    ser.reset_input_buffer()
    ser.write(build_q_frame(f"P S #BDD {BDD_RATES[target]}"))
    ser.flush()
    time.sleep(0.3)
    read_responses(ser, timeout=0.5)  # consume ACK at old baud
    ser.baudrate = target
    sync_uart(ser)
    _, resp = send_cmd(ser, "G S #BID", timeout=0.5, quiet=True)
    if any(b'BID' in r['payload'] for r in resp):
        if not quiet:
            print(f"[+] Running at {target} baud")
        return True
    if not quiet:
        print(f"[!] No response at {target}, reverting")
    ser.baudrate = old
    sync_uart(ser)
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


def enter_bootloader(ser, max_retries=3, enter_cmd='P S #BLL 0001', flood=True):
    """Enter bootloader mode. Returns bootloader BID on success, None on failure.
    flood=True:  S10 style preamble flood to catch short bootloader window
    flood=False: S9 style send reset, wait, then poll gently
    """
    """The flood thing comes from early stage of protocol reversing. Shouldn't be needed anymore.
    Let’s disable this for now and remove it from the code later.
    """
    flood=False

    bls_frame = build_q_frame("G S #BLS")
    for retry in range(max_retries):
        if retry > 0:
            print(f"[*] Retry {retry}/{max_retries-1}...")
            time.sleep(0.3)

        # Quick probe: BLS tells us where we are
        ser.reset_input_buffer()
        print("[*] Checking device...")
        bls = query_bls(ser, timeout=0.3)

        if bls is not None and bls >= 1:
            # Already in bootloader, just grab BID and go
            print(f"[+] Already in bootloader (BLS={bls})")
            bid = query_bid(ser)
            if bid:
                return bid

        if bls is None:
            # No response device may be mid-reset or off
            # Try one more BLS with slightly longer timeout
            bls = query_bls(ser, timeout=0.3)
            if bls is not None and bls >= 1:
                print(f"[+] Already in bootloader (BLS={bls})")
                bid = query_bid(ser)
                if bid:
                    return bid
            if bls is None:
                continue

        # BLS=0 (CDX running)
        print("[*] Triggering reboot...")
        ser.reset_input_buffer()
        ser.write(build_q_frame(enter_cmd))
        ser.flush()
        time.sleep(0.05)
        ser.reset_input_buffer()

        if flood:
            # S10: bootloader window is tight, flood sync+BLS to catch it
            preamble = b'\x55' * 128
            print("[*] Flooding to catch bootloader...")
            t0 = time.time()
            cdx_seen = False
            for _ in range(300):
                ser.write(preamble + bls_frame)
                _, responses = read_responses(ser, timeout=0.05)
                bls = _extract_hex_var(responses, 'BLS')
                if bls is not None and bls >= 1:
                    print(f"[+] Bootloader caught at t+{time.time()-t0:.2f}s (BLS={bls})")
                    time.sleep(0.2)
                    ser.reset_input_buffer()
                    bid = query_bid(ser)
                    if bid:
                        return bid
                    print("[!] BLS confirmed bootloader but BID query failed")
                    break
                elif bls == 0 and not cdx_seen:
                    # Caught CDX - BLL was sent but may not have been
                    # processed yet, or device fast-booted past BL. Resend.
                    print(f"[*] CDX responded (BLS=0), re-sending {enter_cmd}...")
                    ser.reset_input_buffer()
                    ser.write(build_q_frame(enter_cmd))
                    ser.flush()
                    time.sleep(0.05)
                    ser.reset_input_buffer()
                    cdx_seen = True
        else:
            # S9: bootloader can't handle flood, poll with spacing
            print("[*] Waiting for bootloader...")
            t0 = time.time()
            time.sleep(0.2)
            for _ in range(60):
                ser.reset_input_buffer()
                ser.write(bls_frame)
                ser.flush()
                _, responses = read_responses(ser, timeout=0.3)
                bls = _extract_hex_var(responses, 'BLS')
                if bls is not None and bls >= 1:
                    print(f"[+] Bootloader caught at t+{time.time()-t0:.2f}s (BLS={bls})")
                    time.sleep(0.2)
                    ser.reset_input_buffer()
                    bid = query_bid(ser)
                    if bid:
                        return bid
                    break
                elif bls == 0:
                    ser.write(build_q_frame(enter_cmd))
                    ser.flush()
                    time.sleep(0.3)

        print("[!] Failed to catch bootloader")
    return None

def _finish_erase(ser, initial_responses, timeout=30.0):
    """Collect P-ACKs until R-frame. Returns baud from R-frame or None on failure."""
    t0 = time.time()
    p_count = 0
    for r in initial_responses:
        p = r['payload'].decode('ascii', errors='replace')
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


def dump_firmware(ser, output_path, args):
    part_path = output_path + '.part'

    device_bid = connect_device(ser, args.baud, wait=not args.no_wait)
    if not device_bid:
        raise RuntimeError("device connection failed")
    if device_bid != 'SX577-0200':
        raise RuntimeError("firmware dump requires SX577-0200, got %s" % device_bid)
    platform = _platform(device_bid)
    default_baud = platform['default_baud']
    if not args.no_enter:
        if ser.baudrate != default_baud:
            switch_baud(ser, default_baud)
        boot_bid = enter_bootloader(ser, enter_cmd=platform['enter_cmd'], flood=True)
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

    print("\n[*] Dumping 1,048,576 bytes @ %d baud..." % ser.baudrate)
    started = time.monotonic()
    tty_progress = sys.stdout.isatty()
    next_percent = 5
    with open(part_path, 'wb') as output:
        for offset in range(0, FULL_IMAGE_SIZE, DUMP_CHUNK_SIZE):
            length = min(DUMP_CHUNK_SIZE, FULL_IMAGE_SIZE - offset)
            output.write(request_dump_chunk(ser, offset, length))
            done = offset + length
            progress = ("    %s/%s (%3d%%)" %
                        (f"{done:,}", f"{FULL_IMAGE_SIZE:,}",
                         done * 100 // FULL_IMAGE_SIZE))
            if tty_progress:
                sys.stdout.write("\r" + progress)
                sys.stdout.flush()
            elif done == FULL_IMAGE_SIZE or done * 100 // FULL_IMAGE_SIZE >= next_percent:
                print(progress)
                next_percent += 5
        output.flush()
        os.fsync(output.fileno())
    elapsed = time.monotonic() - started
    if tty_progress:
        print(" in %.1fs" % elapsed)
    else:
        print("[*] Dump completed in %.1fs" % elapsed)

    with open(part_path, 'rb') as dumped:
        image = dumped.read()
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
        raise RuntimeError("dumped image failed block CRC validation; partial file kept at %s" %
                           part_path)

    os.replace(part_path, output_path)
    print("[+] Firmware saved: %s" % output_path)

    if not args.no_reset:
        if ser.baudrate != default_baud:
            switch_baud(ser, default_baud)
        print("[*] Resetting device...")
        send_cmd(ser, platform['reset_cmd'], timeout=2.0)
    return 0


CHUNK_SIZE = 250
FLASH_COMPLETE_OK = 0x0000


def check_flash_status(ser, status_var, expected, context):
    status = query_boot_var(ser, status_var, timeout=1.0)
    if status is None:
        print(f"\n[!] No {status_var} response {context}")
        return False
    if status != expected:
        print(f"\n[!] Flash failed {context}: {status_var}={status:04X}, expected {expected:04X}")
        return False
    return True

def flash_block(ser, block_id, data, flash_start, blocks, dry_run=False,
                skip_completion=False, status_var=None, timing=False):
    """Erase and flash a single block. Returns True on success.
    skip_completion: don't send completion frame. Bootloader stays in state 1
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
    for attempt in range(3):
        print(f"\n[*] Erasing {block_id} (attempt {attempt+1})...")
        ser.reset_input_buffer()
        ser.write(build_q_frame(blk['erase_cmd']))
        ser.flush()
        erase_baud = _finish_erase(ser, [], timeout=30.0)

        if erase_baud is not None:
            break
        elif attempt < 2:
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
        written = ser.write(f_frame)
        write_end = time.monotonic()
        if written != len(f_frame):
            print(f"\n[!] Short serial write at frame {frame_index}: "
                  f"{written}/{len(f_frame)} bytes")
            return False
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
    print(f"\r    {offset:,}/{data_end:,} (100%) in {elapsed:.1f}s, {frame_count} frames          ")
    if timing:
        print(f"    Timing: max write {max_write[0]:.3f}s at frame {max_write[1]}, "
              f"max flush {max_flush[0]:.3f}s after frame {max_flush[1]}, "
              f"max host gap {max_gap[0]:.3f}s before frame {max_gap[1]}")

    # Completion frame
    if skip_completion:
        print("[*] Skipping completion frame (non-final block)")
        print(f"[*] Waiting for mode 5 timeout (~2s)...")
        time.sleep(2.5)
        ser.reset_input_buffer()
    else:
        print("[*] Sending completion frame...")
        ser.write(build_completion_frame(block_name, seq))
        ser.flush()
        if status_var:
            if not check_flash_status(ser, status_var, FLASH_COMPLETE_OK,
                                      "after completion"):
                return False
            print(f"[+] Completion confirmed: {status_var}=0000")
        else:
            time.sleep(0.5)
            _, responses = read_responses(ser, timeout=1.0)
            for r in responses:
                print(f"    [{r['type']}] {r['payload'].decode('ascii', errors='replace')}")

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
""")
    parser.add_argument('-p', '--port', required=True, help='Serial port or tcp:host[:port]')
    parser.add_argument('--tcp-mode', choices=['raw', 'transparent'], default='transparent',
                        help='TCP mode: transparent (AirBridge, default), raw (dumb proxy)')
    parser.add_argument('-f', '--file', help='Firmware file to flash')
    parser.add_argument('--dump', metavar='FILE', help='Dump the full firmware image (patched SX577 BLX required)')
    parser.add_argument('--block', action='append', help='Target block (repeatable): config, firmware, all, bootloader')
    parser.add_argument('--baud', default='auto', help='Transfer baud: auto, 57600, 115200, 460800')
    parser.add_argument('--fix-crc', action='store_true', help='Recalculate and patch CRC')
    parser.add_argument('--force', action='store_true', help='Flash even with bad CRC')
    parser.add_argument('--include-bootloader', action='store_true', help='Allow bootloader writes')
    parser.add_argument('--dry-run', action='store_true', help='Validate only, do not flash')
    parser.add_argument('--no-reset', action='store_true', help='Do not reset device after flash')
    parser.add_argument('--no-enter', action='store_true', help='Skip bootloader entry')
    parser.add_argument('--info', action='store_true', help='Show device info and exit')
    parser.add_argument('--raw', action='store_true', help='Flash raw image smaller than block size')
    parser.add_argument('--no-wait', action='store_true', help='Fail immediately if device not found')
    parser.add_argument('--timing', action='store_true',
                        help='Report serial write, flush, and inter-frame timing')
    parser.add_argument('--yolo', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()

    if args.dump and args.file:
        parser.error("--dump and -f/--file are mutually exclusive")
    if not args.info and not args.dump and not args.file:
        parser.error("-f/--file is required (unless using --info or --dump)")

    if args.port.startswith('tcp:'):
        from tcp_serial import open_tcp
        ser = open_tcp(args.port, args.tcp_mode, timeout=1.0)
    else:
        ser = serial.Serial(args.port, 57600, timeout=1.0)

    try:
        if args.info:
            return cmd_info(ser, wait=not args.no_wait)

        if args.dump:
            try:
                return dump_firmware(ser, args.dump, args)
            except (OSError, RuntimeError) as exc:
                print("[!] %s" % exc)
                return 1

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

        if not args.no_enter:
            if ser.baudrate != default_baud:
                if can_bdd:
                    switch_baud(ser, default_baud)
                else:
                    ser.baudrate = default_baud

            bl_bid = enter_bootloader(ser, enter_cmd=enter_cmd, flood=can_bdd)
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
                    if not enter_bootloader(ser, 30, enter_cmd=enter_cmd, flood=can_bdd):
                        return 1
                    if can_bdd:
                        if args.baud == 'auto':
                            negotiate_best_baud(ser)
                        else:
                            target = int(args.baud)
                            if target != ser.baudrate:
                                switch_baud(ser, target)
                else:
                    # No software reset from bootloader. Need power cycle.
                    ser.baudrate = default_baud
                    if not args.no_wait:
                        print(f"\n[*] Power cycle device to continue with {block_id}...")
                        while _extract_bid(send_cmd(ser, "G S #BID", timeout=0.3, quiet=True)[1]):
                            time.sleep(0.3)
                        baud, bid = wait_for_device(ser)
                        if not baud:
                            return 1
                        print()
                        ser.baudrate = baud
                    else:
                        print(f"\n[*] Power cycle device to continue with {block_id}, then press Enter...")
                        input()
                    print("[*] Entering bootloader...")
                    bl_bid = enter_bootloader(ser, enter_cmd=enter_cmd, flood=False)
                    if not bl_bid:
                        return 1

            # Skip completion on BLX when more blocks follow.
            # Avoids fast_boot_reset (completion -> state=2 + BKP7R=0 -> BKP6R
            # gate -> boots CDX, no BL window). Without completion: mode 5
            # timeout (~2s) -> plain reset -> BL with infinite timeout.
            skip = (block_id == 'BLX' and not is_last)
            if not flash_block(ser, block_id, data, flash_start, blocks,
                               skip_completion=skip, status_var=flash_status,
                               timing=args.timing):
                print(f"\n[!] Failed to flash {block_id}")
                return 1

        if not args.no_reset:
            if reset_cmd:
                if can_bdd and ser.baudrate != default_baud:
                    switch_baud(ser, default_baud)
                print("\n[*] Resetting device...")
                send_cmd(ser, reset_cmd, timeout=2.0)
                if flash_status:
                    print("[*] Waiting for application...")
                    ok, bls, ble = wait_for_application(ser, flash_status)
                    if not ok:
                        state = "no BLS response" if bls is None else f"BLS={bls:04X}"
                        error = "" if ble is None else f", BLE={ble:04X}"
                        print(f"[!] Application did not start ({state}{error})")
                        return 1
                    print("[+] Application responding (BLS=0000)")
            else:
                print("\n[*] Power cycle device to boot new firmware")

        print("\n[+] Flash complete!")
        return 0

    finally:
        ser.close()
if __name__ == "__main__":
    sys.exit(main())

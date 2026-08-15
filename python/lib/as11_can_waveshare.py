#!/usr/bin/env python3
"""Waveshare USB-CAN-A serial CAN helper for AS11 bus bring-up.

USB-CAN-A exposes a USB serial port and speaks Waveshare's serial-to-CAN packet
protocol at 2 Mbps by default.

"""

from __future__ import annotations

import argparse
import re
import sys
import time
from collections import Counter
from dataclasses import dataclass
from typing import Iterable

from as11_can_common import (
    CanDatagramCodec,
    CanFrame,
    DEFAULT_RPC_RX_ID,
    DEFAULT_RPC_TX_ID,
    hex_bytes,
    parse_int,
)

try:
    import serial
    from serial.tools import list_ports
except Exception:  # pragma: no cover - dependency may be absent on dev hosts
    serial = None
    list_ports = None


SERIAL_BAUD_DEFAULT = 2_000_000
SERIAL_BAUD_SCAN = (2_000_000, 115_200, 1_000_000, 921_600, 460_800, 230_400, 57_600)

CAN_BITRATE_CODES = {
    1_000_000: 0x01,
    800_000: 0x02,
    500_000: 0x03,
    400_000: 0x04,
    250_000: 0x05,
    200_000: 0x06,
    125_000: 0x07,
    100_000: 0x08,
    50_000: 0x09,
    20_000: 0x0A,
    10_000: 0x0B,
    5_000: 0x0C,
}

SCAN_BITRATES = (1_000_000, 500_000, 250_000, 125_000, 100_000, 50_000, 20_000, 10_000)

MODE_CODES = {
    "normal": 0x00,
    "silent": 0x02,
}

FRAME_TYPE_CODES = {
    "std": 0x01,
    "ext": 0x02,
}

FRAME_FORMAT_CODES = {
    "data": 0x01,
    "remote": 0x02,
}


def eprint(*args: object, **kwargs: object) -> None:
    print(*args, file=sys.stderr, **kwargs)


def require_serial() -> None:
    if serial is None:
        raise SystemExit(
            "pyserial is required"
        )


def parse_bitrate(text: str) -> int:
    value = parse_int(text)
    if value not in CAN_BITRATE_CODES:
        choices = ", ".join(str(v) for v in sorted(CAN_BITRATE_CODES, reverse=True))
        raise argparse.ArgumentTypeError(f"unsupported CAN bitrate {value}; choices: {choices}")
    return value


def parse_hex_bytes(text: str) -> bytes:
    cleaned = re.sub(r"[^0-9A-Fa-f]", "", text)
    if len(cleaned) % 2:
        raise argparse.ArgumentTypeError("hex data must contain an even number of digits")
    data = bytes.fromhex(cleaned)
    if len(data) > 8:
        raise argparse.ArgumentTypeError("classic CAN data payload is limited to 8 bytes")
    return data


def id_bytes(can_id: int, extended: bool) -> bytes:
    if extended:
        if not 0 <= can_id <= 0x1FFFFFFF:
            raise ValueError("extended CAN ID must be in range 0..0x1fffffff")
        return can_id.to_bytes(4, "little")
    if not 0 <= can_id <= 0x7FF:
        raise ValueError("standard CAN ID must be in range 0..0x7ff")
    return can_id.to_bytes(2, "little")


def config_id_bytes(can_id: int) -> bytes:
    if not 0 <= can_id <= 0x1FFFFFFF:
        raise ValueError("filter/mask ID must be in range 0..0x1fffffff")
    return can_id.to_bytes(4, "big")


class UsbCanA:
    """USB-CAN-A serial driver with a background drain thread.

    A daemon thread continuously reads chunks of bytes from the serial port into
    an internal ring buffer. The frame parser (read_frame) pops bytes from that buffer
    rather than calling `ser.read()` directly. This isolates the kernel tty buffer
    from main-thread latency: even if the parser stalls (GC, scheduler, other work),
    the drain thread keeps the kernel buffer drained at line rate, preventing
    whole-frame drops under burst load.

    """

    # Chunk size for the drain thread's blocking reads. Bigger = fewer
    # syscalls. 4096 = ~20ms at 2Mbps baud, well below tty buffer size.
    _DRAIN_CHUNK = 4096

    def __init__(
        self,
        port: str,
        serial_baud: int = SERIAL_BAUD_DEFAULT,
        timeout: float = 0.05,
        open_delay: float = 0.05,
        dtr: bool | None = None,
        rts: bool | None = None,
        reset_buffers: bool = True,
    ):
        require_serial()
        self.ser = serial.Serial(
            port=port,
            baudrate=serial_baud,
            bytesize=8,
            parity="N",
            stopbits=1,
            timeout=timeout,
            write_timeout=1.0,
            xonxoff=False,
            rtscts=False,
            dsrdtr=False,
        )
        if hasattr(self.ser, "set_buffer_size"):
            try:
                self.ser.set_buffer_size(rx_size=256 * 1024,
                                         tx_size=64 * 1024)
            except Exception:
                pass  # best-effort; fall back to defaults

        if hasattr(self.ser, "set_low_latency_mode"):
            try:
                self.ser.set_low_latency_mode(True)
            except Exception:
                pass
        if dtr is not None:
            self.ser.dtr = dtr
        if rts is not None:
            self.ser.rts = rts
        self.serial_baud = serial_baud
        self.timeout = timeout
        if open_delay:
            time.sleep(open_delay)
        if reset_buffers:
            self.ser.reset_input_buffer()
            self.ser.reset_output_buffer()

        # Background drain machinery.
        import threading  # local; keeps top-level deps unchanged
        self._rx_buf = bytearray()
        self._rx_cond = threading.Condition()
        self._drain_stop = threading.Event()
        self._drain_thread = threading.Thread(
            target=self._drain_loop, name="usbcana-drain", daemon=True,
        )
        self._drain_thread.start()

    def _drain_loop(self) -> None:
        while not self._drain_stop.is_set():
            try:
                chunk = self.ser.read(self._DRAIN_CHUNK)
            except Exception:
                # Port closed or USB unplugged. Exit cleanly.
                with self._rx_cond:
                    self._rx_cond.notify_all()
                return
            if chunk:
                with self._rx_cond:
                    self._rx_buf.extend(chunk)
                    self._rx_cond.notify_all()

    def _read_bytes(self, n: int, *, timeout: float | None = None) -> bytes:
        if timeout is None:
            timeout = self.timeout
        deadline = time.monotonic() + timeout
        with self._rx_cond:
            while len(self._rx_buf) < n:
                remaining = deadline - time.monotonic()
                if remaining <= 0 or self._drain_stop.is_set():
                    break
                self._rx_cond.wait(timeout=remaining)
            take = min(n, len(self._rx_buf))
            out = bytes(self._rx_buf[:take])
            del self._rx_buf[:take]
            return out

    def reset_input_buffer(self) -> None:
        self.ser.reset_input_buffer()
        with self._rx_cond:
            self._rx_buf.clear()

    def close(self) -> None:
        self._drain_stop.set()
        try:
            self.ser.close()
        except Exception:
            pass
        with self._rx_cond:
            self._rx_cond.notify_all()
        if self._drain_thread.is_alive():
            self._drain_thread.join(timeout=1.0)

    def __enter__(self) -> "UsbCanA":
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def configure(
        self,
        can_bitrate: int,
        frame_type: str,
        mode: str,
        filter_id: int = 0,
        mask_id: int = 0,
        auto_retransmit: bool = True,
    ) -> bytes:
        frame = bytearray(20)
        frame[0] = 0xAA
        frame[1] = 0x55
        frame[2] = 0x12  # variable-length CAN packet protocol
        frame[3] = CAN_BITRATE_CODES[can_bitrate]
        frame[4] = FRAME_TYPE_CODES[frame_type]
        frame[5:9] = config_id_bytes(filter_id)
        frame[9:13] = config_id_bytes(mask_id)
        frame[13] = MODE_CODES[mode]
        frame[14] = 0x00 if auto_retransmit else 0x01
        frame[19] = sum(frame[2:19]) & 0xFF

        self.reset_input_buffer()
        self.ser.write(frame)
        self.ser.flush()
        time.sleep(0.05)
        return bytes(frame)

    def read_frame(self, deadline: float | None = None) -> CanFrame | None:
        while deadline is None or time.monotonic() < deadline:
            b = self._read_bytes(1)
            if not b:
                return None
            if b[0] != 0xAA:
                continue

            type_b = self._read_bytes(1)
            if not type_b:
                return None
            frame_type = type_b[0]

            if (frame_type & 0xC0) != 0xC0:
                continue

            dlc = frame_type & 0x0F
            if dlc > 8:
                continue
            extended = bool(frame_type & 0x20)
            remote = bool(frame_type & 0x10)
            id_len = 4 if extended else 2
            rest = self._read_bytes(id_len + dlc + 1)
            if len(rest) != id_len + dlc + 1:
                return None
            raw = bytes([0xAA, frame_type]) + rest
            if raw[-1] != 0x55:
                continue
            can_id = int.from_bytes(rest[:id_len], "little")
            if extended:
                can_id &= 0x1FFFFFFF
            else:
                can_id &= 0x7FF
            data = rest[id_len:id_len + dlc]
            return CanFrame(
                timestamp=time.time(),
                can_id=can_id,
                extended=extended,
                remote=remote,
                data=data,
                raw=raw,
            )
        return None

    def send_frame(self, can_id: int, data: bytes, extended: bool = False, remote: bool = False) -> bytes:
        frame_type = 0xC0 | len(data)
        if extended:
            frame_type |= 0x20
        if remote:
            frame_type |= 0x10
        packet = bytes([0xAA, frame_type]) + id_bytes(can_id, extended) + data + bytes([0x55])
        self.ser.write(packet)
        self.ser.flush()
        return packet

def summarize(frames: Iterable[CanFrame]) -> str:
    frames = list(frames)
    if not frames:
        return "0 frames"
    ids = Counter((f.extended, f.can_id) for f in frames)
    top = ", ".join(
        f"{'ext' if ext else 'std'}:0x{can_id:0{8 if ext else 3}X}x{count}"
        for (ext, can_id), count in ids.most_common(8)
    )
    return f"{len(frames)} frames; {top}"


def frame_key(frame: CanFrame) -> tuple[bool, int, bytes]:
    return (frame.extended, frame.can_id, frame.data)


def format_payload_ascii(data: bytes) -> str:
    text = "".join(chr(b) if 0x20 <= b < 0x7F else "." for b in data)
    return text


def cmd_ports(args: argparse.Namespace) -> int:
    require_serial()
    ports = list(list_ports.comports())
    if not ports:
        print("no serial ports found")
        return 1
    for port in ports:
        print(f"{port.device:16} {port.description}  hwid={port.hwid}")
    return 0


def cmd_config(args: argparse.Namespace) -> int:
    with UsbCanA(args.port, args.serial_baud, args.timeout, args.open_delay, args.dtr, args.rts, not args.no_reset_buffers) as dev:
        raw = dev.configure(
            args.can_bitrate,
            args.frame_type,
            args.mode,
            args.filter_id,
            args.mask_id,
            auto_retransmit=not args.disable_retransmit,
        )
    print(
        f"configured {args.port}: {args.frame_type} {args.can_bitrate} bps "
        f"{args.mode}, filter=0x{args.filter_id:X}, mask=0x{args.mask_id:X}"
    )
    if args.raw:
        print(f"serial >>> {hex_bytes(raw)}")
    return 0


def cmd_sniff(args: argparse.Namespace) -> int:
    with UsbCanA(args.port, args.serial_baud, args.timeout, args.open_delay, args.dtr, args.rts, not args.no_reset_buffers) as dev:
        raw_cfg = dev.configure(
            args.can_bitrate,
            args.frame_type,
            args.mode,
            args.filter_id,
            args.mask_id,
            auto_retransmit=not args.disable_retransmit,
        )
        eprint(
            f"sniffing {args.port}: {args.frame_type} {args.can_bitrate} bps "
            f"{args.mode} mode"
        )
        if args.raw:
            eprint(f"serial >>> {hex_bytes(raw_cfg)}")

        frames: list[CanFrame] = []
        start = time.time()
        deadline = None if args.duration is None else time.monotonic() + args.duration
        try:
            while deadline is None or time.monotonic() < deadline:
                frame = dev.read_frame(deadline=deadline)
                if frame is None:
                    continue
                frames.append(frame)
                print(frame.format(start_time=start, raw=args.raw), flush=True)
        except KeyboardInterrupt:
            pass
    eprint("summary:", summarize(frames))
    return 0 if frames else 2


def cmd_capture(args: argparse.Namespace) -> int:
    with UsbCanA(args.port, args.serial_baud, args.timeout, args.open_delay, args.dtr, args.rts, not args.no_reset_buffers) as dev:
        raw_cfg = dev.configure(
            args.can_bitrate,
            args.frame_type,
            args.mode,
            args.filter_id,
            args.mask_id,
            auto_retransmit=not args.disable_retransmit,
        )
        eprint(
            f"capturing {args.port}: {args.frame_type} {args.can_bitrate} bps "
            f"{args.mode} mode"
        )
        if args.raw:
            eprint(f"serial >>> {hex_bytes(raw_cfg)}")

        start_mono = time.monotonic()
        start_wall = time.time()
        deadline = start_mono + args.duration
        counts: Counter[tuple[bool, int, bytes]] = Counter()
        first_ts: dict[tuple[bool, int, bytes], float] = {}
        last_ts: dict[tuple[bool, int, bytes], float] = {}
        sample_printed = 0
        output = None
        try:
            if args.output:
                output = open(args.output, "w", encoding="ascii")
            while time.monotonic() < deadline:
                frame = dev.read_frame(deadline=deadline)
                if frame is None:
                    continue
                rel = frame.timestamp - start_wall
                key = frame_key(frame)
                counts[key] += 1
                first_ts.setdefault(key, rel)
                last_ts[key] = rel
                line = frame.format(start_time=start_wall, raw=args.raw)
                if output is not None:
                    output.write(line + "\n")
                if args.show_frames and sample_printed < args.max_print:
                    print(line, flush=True)
                    sample_printed += 1
        finally:
            if output is not None:
                output.close()

    total = sum(counts.values())
    print(f"captured {total} frames in {args.duration:.3f}s")
    for (extended, can_id, data), count in counts.most_common(args.top):
        width = 8 if extended else 3
        duration = max(0.0, last_ts[(extended, can_id, data)] - first_ts[(extended, can_id, data)])
        rate = count / args.duration if args.duration else 0
        print(
            f"{count:8d}  {rate:10.1f}/s  {'ext' if extended else 'std'} "
            f"0x{can_id:0{width}X}  [{len(data)}]  {hex_bytes(data):<23}  "
            f"{format_payload_ascii(data)}  span={duration:.6f}s"
        )
    return 0 if total else 2


def cmd_ascii(args: argparse.Namespace) -> int:
    with UsbCanA(args.port, args.serial_baud, args.timeout, args.open_delay, args.dtr, args.rts, not args.no_reset_buffers) as dev:
        raw_cfg = dev.configure(
            args.can_bitrate,
            args.frame_type,
            args.mode,
            args.filter_id,
            args.mask_id,
            auto_retransmit=not args.disable_retransmit,
        )
        eprint(
            f"ascii capture {args.port}: {args.frame_type} {args.can_bitrate} bps "
            f"{args.mode} mode id=0x{args.can_id:X}"
        )
        if args.raw:
            eprint(f"serial >>> {hex_bytes(raw_cfg)}")
        deadline = time.monotonic() + args.duration if args.duration is not None else None
        line = bytearray()
        total = 0
        try:
            while deadline is None or time.monotonic() < deadline:
                frame = dev.read_frame(deadline=deadline)
                if frame is None:
                    continue
                if frame.extended:
                    continue
                if frame.can_id != args.can_id:
                    continue
                total += 1
                data = frame.data
                if args.strip_prefix and data:
                    data = data[1:]
                if args.raw:
                    print(frame.format(raw=True), flush=True)
                for b in data:
                    if b == 0 and args.drop_nul:
                        continue
                    if b == 0x0D:
                        continue
                    if b == 0x0A:
                        print(line.decode("ascii", errors="replace"), flush=True)
                        line.clear()
                    else:
                        line.append(b)
                        if len(line) >= args.flush_len:
                            print(line.decode("ascii", errors="replace"), flush=True)
                            line.clear()
        except KeyboardInterrupt:
            pass
    if line:
        print(line.decode("ascii", errors="replace"), flush=True)
    eprint(f"ascii frames: {total}")
    return 0 if total else 2


def find_s70_header(buf: bytearray) -> int:
    for i in range(0, max(0, len(buf) - 4)):
        if buf[i:i + 3] != b"S70":
            continue
        if all(chr(b) in "0123456789ABCDEFabcdef" for b in buf[i + 3:i + 5]):
            return i
    return -1


def cmd_log(args: argparse.Namespace) -> int:
    with UsbCanA(args.port, args.serial_baud, args.timeout, args.open_delay, args.dtr, args.rts, not args.no_reset_buffers) as dev:
        raw_cfg = dev.configure(
            args.can_bitrate,
            args.frame_type,
            args.mode,
            args.filter_id,
            args.mask_id,
            auto_retransmit=not args.disable_retransmit,
        )
        eprint(
            f"log capture {args.port}: {args.frame_type} {args.can_bitrate} bps "
            f"{args.mode} mode id=0x{args.can_id:X}"
        )
        if args.raw:
            eprint(f"serial >>> {hex_bytes(raw_cfg)}")
        deadline = time.monotonic() + args.duration if args.duration is not None else None
        stream = bytearray()
        total = 0
        output = None
        try:
            if args.output:
                output = open(args.output, "w", encoding="utf-8")
            while deadline is None or time.monotonic() < deadline:
                frame = dev.read_frame(deadline=deadline)
                if frame is None:
                    continue
                if frame.extended or frame.can_id != args.can_id:
                    continue
                total += 1
                data = frame.data
                if args.strip_prefix and data:
                    data = data[1:]
                stream.extend(data)

                while True:
                    idx = find_s70_header(stream)
                    if idx < 0:
                        if len(stream) > 8:
                            if args.show_discard:
                                eprint(f"discard: {hex_bytes(stream[:-4])}")
                            del stream[:-4]
                        break
                    if idx:
                        if args.show_discard:
                            eprint(f"discard: {hex_bytes(stream[:idx])}")
                        del stream[:idx]
                    if len(stream) < 5:
                        break
                    rec_len = int(stream[3:5].decode("ascii"), 16)
                    need = 5 + rec_len
                    if len(stream) < need:
                        break
                    payload = bytes(stream[5:need])
                    del stream[:need]
                    text = payload.decode("utf-8", errors="replace")
                    prefix = f"S70{rec_len:02X} " if args.show_header else ""
                    ts = f"{time.time():.6f} " if args.timestamps else ""
                    line = ts + prefix + text
                    print(line, flush=True)
                    if output is not None:
                        output.write(line + "\n")
        except KeyboardInterrupt:
            pass
        finally:
            if output is not None:
                output.close()
    eprint(f"log frames: {total}, buffered bytes: {len(stream)}")
    return 0 if total else 2


def cmd_scan(args: argparse.Namespace) -> int:
    hit = False
    frame_types = args.frame_type
    with UsbCanA(args.port, args.serial_baud, args.timeout, args.open_delay, args.dtr, args.rts, not args.no_reset_buffers) as dev:
        for can_bitrate in args.can_bitrate:
            for frame_type in frame_types:
                raw_cfg = dev.configure(
                    can_bitrate,
                    frame_type,
                    args.mode,
                    args.filter_id,
                    args.mask_id,
                    auto_retransmit=not args.disable_retransmit,
                )
                if args.raw:
                    eprint(f"serial >>> {hex_bytes(raw_cfg)}")
                deadline = time.monotonic() + args.duration
                frames: list[CanFrame] = []
                while time.monotonic() < deadline:
                    frame = dev.read_frame(deadline=deadline)
                    if frame is None:
                        continue
                    frames.append(frame)
                    if args.show_frames:
                        print(frame.format(raw=args.raw), flush=True)
                status = "HIT " if frames else "miss"
                print(f"{status} {frame_type:3} {can_bitrate:7} bps {args.mode:14} {summarize(frames)}")
                hit = hit or bool(frames)
    return 0 if hit else 2


def cmd_send(args: argparse.Namespace) -> int:
    if not args.yes_transmit:
        raise SystemExit("refusing to transmit without --yes-transmit")
    extended = args.extended or args.can_id > 0x7FF
    frame_type = "ext" if extended else "std"
    with UsbCanA(args.port, args.serial_baud, args.timeout, args.open_delay, args.dtr, args.rts, not args.no_reset_buffers) as dev:
        raw_cfg = dev.configure(
            args.can_bitrate,
            frame_type,
            args.mode,
            args.filter_id,
            args.mask_id,
            auto_retransmit=not args.disable_retransmit,
        )
        if args.raw:
            eprint(f"serial >>> {hex_bytes(raw_cfg)}")
        packet = b""
        for i in range(args.count):
            packet = dev.send_frame(args.can_id, args.data, extended=extended, remote=args.remote)
            if args.raw:
                eprint(f"serial >>> {hex_bytes(packet)}")
            if i + 1 < args.count:
                time.sleep(args.interval)
    print(
        f"sent {args.count} {'extended' if extended else 'standard'} frame(s): "
        f"id=0x{args.can_id:X} data={hex_bytes(args.data)}"
    )
    return 0


def cmd_raw(args: argparse.Namespace) -> int:
    with UsbCanA(args.port, args.serial_baud, args.timeout, args.open_delay, args.dtr, args.rts, not args.no_reset_buffers) as dev:
        if args.configure:
            raw_cfg = dev.configure(
                args.can_bitrate,
                args.frame_type,
                args.mode,
                args.filter_id,
                args.mask_id,
                auto_retransmit=not args.disable_retransmit,
            )
            eprint(f"serial >>> {hex_bytes(raw_cfg)}")
        deadline = time.monotonic() + args.duration
        total = 0
        while time.monotonic() < deadline:
            chunk = dev.ser.read(args.chunk_size)
            if not chunk:
                continue
            total += len(chunk)
            print(f"{time.time():.6f}  {hex_bytes(chunk)}", flush=True)
    eprint(f"raw bytes: {total}")
    return 0 if total else 2


def add_port_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("-p", "--port", required=True, help="serial port, e.g. /dev/ttyUSB0 or COM7")
    parser.add_argument("--serial-baud", type=int, default=SERIAL_BAUD_DEFAULT, help="USB serial baud rate")
    parser.add_argument("--timeout", type=float, default=0.05, help="serial read timeout in seconds")
    parser.add_argument("--open-delay", type=float, default=0.05, help="delay after opening serial port")
    parser.add_argument("--no-reset-buffers", action="store_true", help="do not clear serial buffers after opening")


def add_can_config_args(parser: argparse.ArgumentParser, *, scan: bool = False) -> None:
    if scan:
        parser.add_argument(
            "-s",
            "--can-bitrate",
            type=parse_bitrate,
            nargs="+",
            default=list(SCAN_BITRATES),
            help="CAN bitrates to try",
        )
        parser.add_argument(
            "--frame-type",
            choices=("std", "ext"),
            nargs="+",
            default=["std", "ext"],
            help="CAN frame type(s) to try",
        )
    else:
        parser.add_argument("-s", "--can-bitrate", type=parse_bitrate, required=True, help="CAN bitrate")
        parser.add_argument("--frame-type", choices=("std", "ext"), default="std", help="CAN frame type")
    parser.add_argument("--mode", choices=tuple(MODE_CODES), default="silent", help="adapter CAN mode")
    parser.add_argument("--filter-id", type=parse_int, default=0, help="acceptance filter ID")
    parser.add_argument("--mask-id", type=parse_int, default=0, help="acceptance mask/block ID; 0 accepts all")
    parser.add_argument("--disable-retransmit", action="store_true", help="disable automatic retransmit for sent frames")
    parser.add_argument("--raw", action="store_true", help="show raw serial packets")


# JSON-RPC over Waveshare CAN.

import json as _json
import logging as _logging
from dataclasses import dataclass as _dataclass

from as11_rpc import (
    TransportError, FramingError,
    build_request,
)
DEFAULT_LOG_ID    = 0x796   # device -> host, S70-prefixed CAL log
DEFAULT_FG_POWERUP_ID = 0x2C8  # device boot notification



_log_can_rpc = _logging.getLogger("as11.can_waveshare")


@_dataclass
class _CanTransportConfig:
    port: str
    bitrate: int = 1_000_000
    mode: str = "normal"
    serial_baud: int = 2_000_000
    tx_id: int = DEFAULT_RPC_TX_ID
    rx_id: int = DEFAULT_RPC_RX_ID
    frame_interval: float = 0.002
    reset_buffers: bool = True
    dtr: bool | None = None
    rts: bool | None = None
    debug: bool = False


class CanWaveshareTransport:
    """JSON-RPC transport over Waveshare USB-CAN-A.
    Not thread-safe; one CLI, one open adapter.
    """

    DEFAULT_TIMEOUT = 5.0

    def __init__(self, port: str, *, bitrate: int = 1_000_000,
                 mode: str = "normal", serial_baud: int = 2_000_000,
                 tx_id: int = DEFAULT_RPC_TX_ID, rx_id: int = DEFAULT_RPC_RX_ID,
                 frame_interval: float = 0.002, reset_buffers: bool = True,
                 dtr: bool | None = None, rts: bool | None = None,
                 debug: bool = False) -> None:
        self._cfg = _CanTransportConfig(
            port=port, bitrate=bitrate, mode=mode, serial_baud=serial_baud,
            tx_id=tx_id, rx_id=rx_id, frame_interval=frame_interval,
            reset_buffers=reset_buffers, dtr=dtr, rts=rts, debug=debug,
        )
        self._dev: UsbCanA | None = None
        self._rx_codec = CanDatagramCodec()
        self._rpc_id = 0
        self._notification_handler = None
        self._notification_stop = False


    @classmethod
    def from_args(cls, target: str,
                  args: argparse.Namespace) -> "CanWaveshareTransport":
        """Construct from a `can:<port>` target + parsed CLI args."""
        return cls(
            port=target,
            bitrate=getattr(args, "bitrate", 1_000_000),
            mode=getattr(args, "mode", "normal"),
            serial_baud=getattr(args, "serial_baud", 2_000_000),
            tx_id=getattr(args, "tx_id", DEFAULT_RPC_TX_ID),
            rx_id=getattr(args, "rx_id", DEFAULT_RPC_RX_ID),
            frame_interval=getattr(args, "frame_interval", 0.002),
            reset_buffers=not getattr(args, "no_reset_buffers", False),
            dtr=getattr(args, "dtr", None),
            rts=getattr(args, "rts", None),
            debug=getattr(args, "debug", False),
        )


    @property
    def name(self) -> str:
        return f"can:waveshare:{self._cfg.port}"

    @property
    def supports_encrypted(self) -> bool:
        # Physical CAN has no encrypted admin VCID equivalent; the service
        # lane 0x383/0x382 is plaintext JSON-RPC.
        return False

    @property
    def dev(self) -> UsbCanA:
        if self._dev is None:
            raise TransportError("transport not connected")
        return self._dev

    def connect(self) -> None:
        if self._dev is not None:
            return
        cfg = self._cfg
        dev = UsbCanA(
            port=cfg.port,
            serial_baud=cfg.serial_baud,
            timeout=0.05,
            open_delay=0.05,
            dtr=cfg.dtr,
            rts=cfg.rts,
            reset_buffers=cfg.reset_buffers,
        )
        dev.configure(
            can_bitrate=cfg.bitrate,
            frame_type="std",
            mode=cfg.mode,
            filter_id=0,
            mask_id=0,
            auto_retransmit=True,
        )
        time.sleep(0.1)
        dev.reset_input_buffer()
        self._dev = dev
        self._rx_codec = CanDatagramCodec()

    def close(self) -> None:
        if self._dev is not None:
            try:
                self._dev.close()
            finally:
                self._dev = None

    def __enter__(self) -> "CanWaveshareTransport":
        self.connect()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()


    def _next_id(self) -> int:
        self._rpc_id += 1
        return self._rpc_id

    def send_payload(self, payload: bytes) -> None:
        """Fragment `payload` via CanDatagramCodec and TX each frame."""
        frames = CanDatagramCodec.encode(payload)
        for frame in frames:
            self.dev.send_frame(self._cfg.tx_id, frame, extended=False)
            if self._cfg.debug:
                _log_can_rpc.debug("TX 0x%03X %s", self._cfg.tx_id,
                                   frame.hex())
            if self._cfg.frame_interval > 0 and len(frames) > 1:
                time.sleep(self._cfg.frame_interval)

    def recv_payload(self, *, timeout: float) -> bytes:
        """Block until a complete datagram arrives on rx_id or raise TimeoutError."""
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(
                    f"no CAN datagram on 0x{self._cfg.rx_id:03X} "
                    f"within {timeout:.1f}s"
                )
            frame = self.dev.read_frame(deadline=deadline)
            if frame is None:
                continue
            if frame.can_id != self._cfg.rx_id or frame.extended:
                if self._cfg.debug:
                    _log_can_rpc.debug(
                        "rx skipped (id=0x%03X ext=%s): %s",
                        frame.can_id, frame.extended,
                        bytes(frame.data).hex(),
                    )
                continue
            data = bytes(frame.data)
            if self._cfg.debug:
                flag = data[0] & 0x03 if data else -1
                flag_name = {0x00: "MID", 0x01: "START", 0x02: "END",
                             0x03: "SINGLE"}.get(flag, f"?{flag}")
                _log_can_rpc.debug(
                    "rx 0x%03X dlc=%d %-6s %s",
                    frame.can_id, len(data), flag_name, data.hex(),
                )
            try:
                payload = self._rx_codec.feed(data)
            except ValueError as exc:
                _log_can_rpc.warning(
                    "codec error on 0x%03X (frame %s): %s",
                    frame.can_id, data.hex(), exc,
                )
                self._rx_codec.reset()
                raise FramingError(
                    f"CAN framing error on 0x{frame.can_id:03X}: {exc}"
                ) from exc
            if payload is not None:
                if self._cfg.debug:
                    _log_can_rpc.debug(
                        "rx reassembled %d B: %s",
                        len(payload),
                        payload[:80].decode("utf-8", errors="replace"),
                    )
                return payload


    def rpc(self, method: str, params: object | None = None,
            *, timeout: float = DEFAULT_TIMEOUT) -> dict:
        rpc_id = self._next_id()
        payload = build_request(method, params, rpc_id)
        self.send_payload(payload)
        return self._rpc_await_response(rpc_id, timeout)

    def _rpc_await_response(self, rpc_id: int, timeout: float) -> dict:
        """Consume RX datagrams until one with matching id is reassembled.

        Notifications ("method" + no "id") arriving during the wait are
        dispatched to the installed notification handler (if any). Other
        responses with non-matching ids are logged and skipped.
        """
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(
                    f"no RPC response for id={rpc_id} within {timeout:.1f}s"
                )
            raw = self.recv_payload(timeout=remaining)
            try:
                obj = _json.loads(raw.decode("utf-8", errors="replace"))
            except _json.JSONDecodeError as exc:
                _log_can_rpc.warning("bad JSON response: %s", exc)
                continue
            if isinstance(obj, dict) and "method" in obj and "id" not in obj:
                self._dispatch_notification(obj)
                continue
            if obj.get("id") == rpc_id:
                return obj
            _log_can_rpc.debug("unmatched id=%s (want %s)",
                               obj.get("id"), rpc_id)

    def _dispatch_notification(self, msg: dict) -> None:
        """Forward `msg` to the installed notification handler, if any.
        Sets `_notification_stop` if the handler returns truthy."""
        if self._notification_handler is None:
            return
        try:
            if self._notification_handler(msg):
                self._notification_stop = True
        except Exception as exc:
            _log_can_rpc.warning("notification handler raised: %s", exc)


    def set_notification_handler(self, handler) -> None:
        """Install a persistent handler that fires on every device
        notification (method + no id), including during other RPCs.
        Pass None to clear."""
        self._notification_handler = handler
        self._notification_stop = False

    def listen_for_notifications(self,
                                 *, duration: float | None = None) -> None:
        """Block, reading frames off rx_id. Notifications dispatched via
        the installed handler. Returns on duration timeout, interrupt, or
        when the handler signals stop."""
        deadline = (time.monotonic() + duration) if duration else None
        try:
            while True:
                if self._notification_stop:
                    return
                if deadline is not None and time.monotonic() >= deadline:
                    return
                try:
                    raw = self.recv_payload(
                        timeout=max(0.05,
                                    (deadline - time.monotonic())
                                    if deadline else 1.0)
                    )
                except TimeoutError:
                    continue
                except FramingError as exc:
                    _log_can_rpc.warning("notify framing error (skipped): %s",
                                         exc)
                    continue
                try:
                    msg = _json.loads(raw.decode("utf-8", errors="replace"))
                except (_json.JSONDecodeError, UnicodeDecodeError):
                    _log_can_rpc.debug("listen: non-JSON payload %r",
                                       raw[:60])
                    continue
                if isinstance(msg, dict) and "method" in msg and "id" not in msg:
                    self._dispatch_notification(msg)
                else:
                    _log_can_rpc.debug("listen: unhandled payload %r",
                                       str(msg)[:120])
        except KeyboardInterrupt:
            return

__all__ = [
    # Existing driver exports:
    "UsbCanA", "CanFrame", "hex_bytes", "parse_bitrate", "parse_hex_bytes",
    "parse_int", "MODE_CODES",
    # RPC additions:
    "CanDatagramCodec", "CanWaveshareTransport",
    "DEFAULT_RPC_TX_ID", "DEFAULT_RPC_RX_ID",
    "DEFAULT_LOG_ID", "DEFAULT_FG_POWERUP_ID",
]


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Waveshare USB-CAN-A serial helper for AS11 CAN discovery",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("ports", help="list serial ports")
    p.set_defaults(func=cmd_ports)

    p = sub.add_parser("config", help="configure adapter and exit")
    add_port_args(p)
    add_can_config_args(p)
    p.set_defaults(func=cmd_config)

    p = sub.add_parser("sniff", help="configure adapter and print decoded CAN frames")
    add_port_args(p)
    add_can_config_args(p)
    p.add_argument("-d", "--duration", type=float, help="capture duration in seconds")
    p.set_defaults(func=cmd_sniff)

    p = sub.add_parser("capture", help="capture for a fixed duration and summarize unique frames")
    add_port_args(p)
    add_can_config_args(p)
    p.add_argument("-d", "--duration", type=float, default=5.0, help="capture duration in seconds")
    p.add_argument("--show-frames", action="store_true", help="print first frames during capture")
    p.add_argument("--max-print", type=int, default=40, help="maximum frames to print with --show-frames")
    p.add_argument("--top", type=int, default=20, help="number of unique frames to summarize")
    p.add_argument("-o", "--output", help="optional text file for all decoded frames")
    p.set_defaults(func=cmd_capture)

    p = sub.add_parser("ascii", help="reassemble ASCII text carried in CAN frame payloads")
    add_port_args(p)
    p.add_argument("-s", "--can-bitrate", type=parse_bitrate, default=1_000_000, help="CAN bitrate")
    p.add_argument("--frame-type", choices=("std", "ext"), default="std", help="adapter frame type")
    p.add_argument("--mode", choices=tuple(MODE_CODES), default="normal", help="adapter CAN mode")
    p.add_argument("--filter-id", type=parse_int, default=0, help="acceptance filter ID")
    p.add_argument("--mask-id", type=parse_int, default=0, help="acceptance mask/block ID")
    p.add_argument("--disable-retransmit", action="store_true", help="disable automatic retransmit")
    p.add_argument("--raw", action="store_true", help="show raw serial packets")
    p.add_argument("--can-id", type=parse_int, default=0x796, help="standard CAN ID carrying text")
    p.add_argument("-d", "--duration", type=float, help="capture duration in seconds")
    p.add_argument("--strip-prefix", action=argparse.BooleanOptionalAction, default=True, help="drop first byte from each payload")
    p.add_argument("--drop-nul", action=argparse.BooleanOptionalAction, default=True, help="drop NUL bytes from text")
    p.add_argument("--flush-len", type=int, default=240, help="flush partial line after this many bytes")
    p.set_defaults(func=cmd_ascii)

    p = sub.add_parser("log", help="decode S70 length-prefixed log records on CAN text stream")
    add_port_args(p)
    p.add_argument("-s", "--can-bitrate", type=parse_bitrate, default=1_000_000, help="CAN bitrate")
    p.add_argument("--frame-type", choices=("std", "ext"), default="std", help="adapter frame type")
    p.add_argument("--mode", choices=tuple(MODE_CODES), default="normal", help="adapter CAN mode")
    p.add_argument("--filter-id", type=parse_int, default=0, help="acceptance filter ID")
    p.add_argument("--mask-id", type=parse_int, default=0, help="acceptance mask/block ID")
    p.add_argument("--disable-retransmit", action="store_true", help="disable automatic retransmit")
    p.add_argument("--raw", action="store_true", help="show raw serial config packet")
    p.add_argument("--can-id", type=parse_int, default=0x796, help="standard CAN ID carrying text")
    p.add_argument("-d", "--duration", type=float, help="capture duration in seconds")
    p.add_argument("--strip-prefix", action=argparse.BooleanOptionalAction, default=True, help="drop first byte from each payload")
    p.add_argument("--show-header", action="store_true", help="show S70 length header before decoded text")
    p.add_argument("--show-discard", action="store_true", help="show discarded binary bytes before records")
    p.add_argument("--timestamps", action="store_true", help="prefix decoded records with host timestamp")
    p.add_argument("-o", "--output", help="optional file for decoded log lines")
    p.set_defaults(func=cmd_log)

    p = sub.add_parser("scan", help="try bitrates/frame types and report any traffic")
    add_port_args(p)
    add_can_config_args(p, scan=True)
    p.add_argument("-d", "--duration", type=float, default=4.0, help="seconds per bitrate/frame-type attempt")
    p.add_argument("--show-frames", action="store_true", help="print frames during scan")
    p.set_defaults(func=cmd_scan)

    p = sub.add_parser("send", help="send one classic CAN frame")
    add_port_args(p)
    p.add_argument("-s", "--can-bitrate", type=parse_bitrate, required=True, help="CAN bitrate")
    p.add_argument("--mode", choices=tuple(MODE_CODES), default="normal", help="adapter CAN mode")
    p.add_argument("--filter-id", type=parse_int, default=0, help="acceptance filter ID")
    p.add_argument("--mask-id", type=parse_int, default=0, help="acceptance mask/block ID")
    p.add_argument("--disable-retransmit", action="store_true", help="disable automatic retransmit")
    p.add_argument("--raw", action="store_true", help="show raw serial packets")
    p.add_argument("--extended", action="store_true", help="force extended 29-bit frame")
    p.add_argument("--remote", action="store_true", help="send remote frame")
    p.add_argument("--count", type=int, default=1, help="number of times to send")
    p.add_argument("--interval", type=float, default=0.1, help="seconds between repeated sends")
    p.add_argument("--yes-transmit", action="store_true", help="required safety acknowledgement for transmit")
    p.add_argument("can_id", type=parse_int, help="CAN ID")
    p.add_argument("data", type=parse_hex_bytes, nargs="?", default=b"", help="payload hex bytes, max 8")
    p.set_defaults(func=cmd_send)

    p = sub.add_parser("raw", help="dump raw serial bytes, optionally after adapter configuration")
    add_port_args(p)
    p.add_argument("-d", "--duration", type=float, default=5.0, help="capture duration in seconds")
    p.add_argument("--chunk-size", type=int, default=64, help="serial read chunk size")
    p.add_argument("--configure", action="store_true", help="send adapter config before dumping bytes")
    p.add_argument("-s", "--can-bitrate", type=parse_bitrate, default=500_000, help="CAN bitrate for --configure")
    p.add_argument("--frame-type", choices=("std", "ext"), default="std", help="CAN frame type for --configure")
    p.add_argument("--mode", choices=tuple(MODE_CODES), default="silent", help="adapter CAN mode for --configure")
    p.add_argument("--filter-id", type=parse_int, default=0, help="acceptance filter ID for --configure")
    p.add_argument("--mask-id", type=parse_int, default=0, help="acceptance mask/block ID for --configure")
    p.add_argument("--disable-retransmit", action="store_true", help="disable automatic retransmit for --configure")
    p.set_defaults(func=cmd_raw)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())

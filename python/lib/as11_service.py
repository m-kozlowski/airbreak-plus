#!/usr/bin/env python3
"""Binary CAN protocol for the AS11 bootloader service."""

from __future__ import annotations

import binascii
import struct
import time
from dataclasses import dataclass

from as11_can_common import CanTxBufferFull
from as11_rpc import FramingError, TransportError


SERVICE_REQUEST_ID = 0x3C1
SERVICE_RESPONSE_ID = 0x3C0
PROTOCOL_VERSION = 2
PACKET_MAGIC = 0xA5

COMMAND_AIRCANNECT_ENTER = 0x01
COMMAND_INFO = 0x02
COMMAND_READ = 0x03
COMMAND_ERASE = 0x04
COMMAND_WRITE = 0x05
COMMAND_RESET = 0x06

STATUS_OK = 0x00
STATUS_NAMES = {
    0x00: "OK",
    0x01: "BadCommand",
    0x02: "BadLength",
    0x03: "BadCrc",
    0x04: "BadVersion",
    0x05: "BadTarget",
    0x06: "RangeError",
    0x07: "ReadFailure",
    0x08: "EraseFailure",
    0x09: "WriteFailure",
    0x0A: "VerifyFailure",
    0x0B: "EntryTimeout",
}

TARGET_FGCB = 0x01
TARGET_SPIN = 0x02

FLASH_BASE = 0x08000000
FLASH_SIZE = 0x00200000
FLASH_ERASE_SIZE = 0x00020000
FLASH_PROGRAM_SIZE = 32
NOR_SIZE = 0x01000000
NOR_ERASE_SIZE = 0x00010000

ISOTP_SINGLE_FRAME = 0x00
ISOTP_FIRST_FRAME = 0x10
ISOTP_CONSECUTIVE_FRAME = 0x20
ISOTP_FLOW_CONTROL = 0x30
ISOTP_TYPE_MASK = 0xF0
ISOTP_FLOW_STATUS_CTS = 0x00
ISOTP_FLOW_STATUS_WAIT = 0x01
ISOTP_FLOW_STATUS_OVERFLOW = 0x02
ISOTP_RX_BLOCK_SIZE = 255
ISOTP_MAX_PACKET_SIZE = 0xFFF

_HEADER = struct.Struct("<BBBBHH")
_CRC = struct.Struct("<H")
_INFO = struct.Struct("<BBB16s")
_READ = struct.Struct("<BIH")
_ERASE = struct.Struct("<BII")
_WRITE = struct.Struct("<BI")
MAX_REQUEST_PAYLOAD = ISOTP_MAX_PACKET_SIZE - _HEADER.size - _CRC.size
MAX_RESPONSE_PACKET_SIZE = ISOTP_MAX_PACKET_SIZE
MAX_RESPONSE_PAYLOAD = MAX_RESPONSE_PACKET_SIZE - _HEADER.size - _CRC.size
MAX_READ_DATA = MAX_RESPONSE_PAYLOAD
MAX_WRITE_DATA = MAX_REQUEST_PAYLOAD - _WRITE.size


class ServiceResponseError(TransportError):
    """The service decoded the request but returned an explicit error."""

    def __init__(self, command: int, status: int) -> None:
        self.command = command
        self.status = status
        name = STATUS_NAMES.get(status, f"status-{status}")
        super().__init__(f"service command 0x{command:02X} failed: {name}")


@dataclass(frozen=True)
class ServicePacket:
    command: int
    status: int
    sequence: int
    payload: bytes


@dataclass(frozen=True)
class ServiceInfo:
    service_version: tuple[int, int, int]
    fgbl_build_id: str


class _ServiceClient:
    """Common request and response handling for service transports."""

    def __init__(self) -> None:
        self._sequence = time.monotonic_ns() & 0xFFFF

    def _next_sequence(self) -> int:
        self._sequence = (self._sequence + 1) & 0xFFFF
        return self._sequence

    def _prepare_request(self, command: int,
                         payload: bytes) -> tuple[int, bytes]:
        sequence = self._next_sequence()
        packet = encode_packet(
            ServicePacket(command, STATUS_OK, sequence, payload)
        )
        return sequence, packet

    @staticmethod
    def _accept_response(response: ServicePacket, command: int,
                         sequence: int) -> bytes:
        if response.sequence != sequence:
            raise TransportError(
                f"service sequence mismatch: sent 0x{sequence:04X}, "
                f"received 0x{response.sequence:04X}"
            )
        if response.command != command:
            raise TransportError(
                f"service command mismatch: sent 0x{command:02X}, "
                f"received 0x{response.command:02X}"
            )
        if response.status != STATUS_OK:
            raise ServiceResponseError(response.command, response.status)
        return response.payload

    def info(self, *, timeout: float = 5.0) -> ServiceInfo:
        payload = self.request(COMMAND_INFO, timeout=timeout)
        return self._decode_info(payload)

    @staticmethod
    def _decode_info(payload: bytes) -> ServiceInfo:
        if len(payload) != _INFO.size:
            raise FramingError(
                f"service INFO payload has {len(payload)} bytes; expected "
                f"{_INFO.size}"
            )
        major, minor, patch, build_id_raw = _INFO.unpack(payload)
        build_id = build_id_raw.split(b"\0", 1)[0].decode(
            "ascii", errors="replace"
        )
        return ServiceInfo(
            service_version=(major, minor, patch),
            fgbl_build_id=build_id,
        )

    def read(self, target: int, offset: int, length: int, *,
             timeout: float = 5.0) -> bytes:
        payload = self.request(
            COMMAND_READ, _READ.pack(target, offset, length),
            timeout=timeout,
        )
        if len(payload) != length:
            raise FramingError(
                f"service READ length mismatch: requested {length}, "
                f"received {len(payload)}"
            )
        return payload

    def iter_read(self, target: int, offset: int, length: int, *,
                  timeout: float = 5.0):
        done = 0
        while done < length:
            chunk_length = min(MAX_READ_DATA, length - done)
            yield self.read(
                target, offset + done, chunk_length, timeout=timeout
            )
            done += chunk_length

    def erase(self, target: int, offset: int, length: int, *,
              timeout: float = 5.0) -> None:
        request = _ERASE.pack(target, offset, length)
        payload = self.request(COMMAND_ERASE, request, timeout=timeout)
        if payload:
            raise FramingError("service ERASE response must not carry a payload")

    def write(self, target: int, offset: int, data: bytes, *,
              timeout: float = 5.0) -> None:
        metadata = _WRITE.pack(target, offset)
        payload = self.request(
            COMMAND_WRITE, metadata + bytes(data), timeout=timeout
        )
        if payload:
            raise FramingError("service WRITE response must not carry a payload")

    def reset(self, *, timeout: float = 5.0) -> None:
        payload = self.request(COMMAND_RESET, timeout=timeout)
        if payload:
            raise FramingError("service RESET response must not carry a payload")


def encode_packet(packet: ServicePacket) -> bytes:
    body = _HEADER.pack(
        PACKET_MAGIC,
        PROTOCOL_VERSION,
        packet.command,
        packet.status,
        packet.sequence,
        len(packet.payload),
    ) + packet.payload
    return body + _CRC.pack(binascii.crc_hqx(body, 0xFFFF))


def decode_packet(data: bytes) -> ServicePacket:
    if len(data) < _HEADER.size + _CRC.size:
        raise ValueError(f"service packet is too short ({len(data)} bytes)")
    magic, version, command, status, sequence, payload_length = _HEADER.unpack_from(data)
    expected_length = _HEADER.size + payload_length + _CRC.size
    if len(data) != expected_length:
        raise ValueError(
            f"service packet length mismatch: header says {expected_length}, "
            f"received {len(data)}"
        )
    if magic != PACKET_MAGIC:
        raise ValueError(f"bad service packet magic 0x{magic:02X}")
    if version != PROTOCOL_VERSION:
        raise ValueError(
            f"unsupported service protocol version {version}; "
            f"expected {PROTOCOL_VERSION}"
        )
    expected_crc = _CRC.unpack_from(data, len(data) - _CRC.size)[0]
    actual_crc = binascii.crc_hqx(data[:-_CRC.size], 0xFFFF)
    if actual_crc != expected_crc:
        raise ValueError(
            f"service packet CRC mismatch: expected 0x{expected_crc:04X}, "
            f"got 0x{actual_crc:04X}"
        )
    payload = bytes(data[_HEADER.size:-_CRC.size])
    return ServicePacket(command, status, sequence, payload)


def _send_can_frame(raw_can, can_id: int, data: bytes) -> None:
    raw_can.send_frame(can_id, data, extended=False, remote=False)


def _send_can_frames(raw_can, can_id: int, frames: list[bytes]) -> None:
    send_batch = getattr(raw_can, "send_frames_batch", None)
    if send_batch is not None and len(frames) > 1:
        send_batch(can_id, frames, extended=False)
        return
    for frame in frames:
        _send_can_frame(raw_can, can_id, frame)


def _read_can_frame(raw_can, can_id: int, deadline: float):
    while time.monotonic() < deadline:
        frame = raw_can.read_frame(deadline=deadline)
        if frame is None:
            break
        if not frame.extended and not frame.remote and frame.can_id == can_id:
            return frame.data
    raise TimeoutError(f"no ISO-TP frame on 0x{can_id:03X}")


def _decode_stmin(value: int) -> float:
    if value <= 0x7F:
        return value / 1000.0
    if 0xF1 <= value <= 0xF9:
        return (value - 0xF0) / 10000.0
    raise FramingError(f"unsupported ISO-TP STmin 0x{value:02X}")


def _wait_flow_control(raw_can, can_id: int,
                       deadline: float) -> tuple[int, float]:
    while True:
        data = _read_can_frame(raw_can, can_id, deadline)
        if not data or data[0] & ISOTP_TYPE_MASK != ISOTP_FLOW_CONTROL:
            continue
        if len(data) < 3:
            raise FramingError("ISO-TP flow-control frame is too short")
        status = data[0] & 0x0F
        if status == ISOTP_FLOW_STATUS_WAIT:
            continue
        if status == ISOTP_FLOW_STATUS_OVERFLOW:
            raise FramingError("ISO-TP receiver rejected the packet")
        if status != ISOTP_FLOW_STATUS_CTS:
            raise FramingError(f"unknown ISO-TP flow status 0x{status:X}")
        return data[1], _decode_stmin(data[2])


def _send_isotp(raw_can, tx_id: int, fc_id: int, packet: bytes,
                 deadline: float) -> None:
    if len(packet) <= 7:
        _send_can_frame(raw_can, tx_id, bytes([len(packet)]) + packet)
        return

    length = len(packet)
    _send_can_frame(
        raw_can, tx_id,
        bytes([ISOTP_FIRST_FRAME | (length >> 8), length & 0xFF]) + packet[:6],
    )
    block_size, stmin = _wait_flow_control(raw_can, fc_id, deadline)
    offset = 6
    sequence = 1
    while offset < length:
        if time.monotonic() >= deadline:
            raise TimeoutError("ISO-TP send timed out")

        frames = []
        while offset < length and (block_size == 0 or len(frames) < block_size):
            chunk = packet[offset:offset + 7]
            frames.append(
                bytes([ISOTP_CONSECUTIVE_FRAME | sequence]) + chunk
            )
            offset += len(chunk)
            sequence = (sequence + 1) & 0x0F

        if stmin == 0:
            _send_can_frames(raw_can, tx_id, frames)
        else:
            for index, frame in enumerate(frames):
                _send_can_frame(raw_can, tx_id, frame)
                if index + 1 < len(frames):
                    delay = min(stmin, deadline - time.monotonic())
                    if delay <= 0:
                        raise TimeoutError("ISO-TP send timed out")
                    time.sleep(delay)

        if offset < length and block_size:
            block_size, stmin = _wait_flow_control(raw_can, fc_id, deadline)


def _receive_isotp(raw_can, rx_id: int, fc_id: int, deadline: float, *,
                   max_packet_size: int,
                   block_size: int = ISOTP_RX_BLOCK_SIZE) -> bytes:
    while True:
        data = _read_can_frame(raw_can, rx_id, deadline)
        if not data:
            raise FramingError("empty ISO-TP frame")
        frame_type = data[0] & ISOTP_TYPE_MASK
        if frame_type != ISOTP_FLOW_CONTROL:
            break
    if frame_type == ISOTP_SINGLE_FRAME:
        length = data[0] & 0x0F
        if length == 0 or length > len(data) - 1 or length > max_packet_size:
            raise FramingError("invalid ISO-TP single-frame length")
        return bytes(data[1:1 + length])
    if frame_type != ISOTP_FIRST_FRAME or len(data) < 2:
        raise FramingError("expected an ISO-TP first frame")

    length = ((data[0] & 0x0F) << 8) | data[1]
    if length <= 7 or length > max_packet_size:
        raise FramingError(f"invalid ISO-TP packet length {length}")
    result = bytearray(data[2:])
    del result[length:]
    _send_can_frame(
        raw_can, fc_id,
        bytes([ISOTP_FLOW_CONTROL | ISOTP_FLOW_STATUS_CTS,
               block_size, 0]),
    )

    sequence = 1
    block_count = 0
    while len(result) < length:
        data = _read_can_frame(raw_can, rx_id, deadline)
        if not data or data[0] & ISOTP_TYPE_MASK != ISOTP_CONSECUTIVE_FRAME:
            raise FramingError("expected an ISO-TP consecutive frame")
        if data[0] & 0x0F != sequence:
            raise FramingError(
                f"ISO-TP sequence mismatch: expected {sequence}, "
                f"received {data[0] & 0x0F}"
            )
        result.extend(data[1:])
        del result[length:]
        sequence = (sequence + 1) & 0x0F
        block_count += 1
        if len(result) < length and block_size and block_count == block_size:
            block_count = 0
            _send_can_frame(
                raw_can, fc_id,
                bytes([ISOTP_FLOW_CONTROL | ISOTP_FLOW_STATUS_CTS,
                       block_size, 0]),
            )
    return bytes(result)


class ServiceCanClient(_ServiceClient):
    """Synchronous service client over an already-open raw CAN backend."""

    def __init__(self, raw_can, *,
                 block_size: int = ISOTP_RX_BLOCK_SIZE) -> None:
        super().__init__()
        self.raw_can = raw_can
        self.block_size = block_size

    def request(self, command: int, payload: bytes = b"", *,
                timeout: float = 5.0) -> bytes:
        sequence, request = self._prepare_request(command, payload)
        deadline = time.monotonic() + timeout
        try:
            _send_isotp(
                self.raw_can, SERVICE_REQUEST_ID, SERVICE_RESPONSE_ID,
                request, deadline,
            )
            complete = _receive_isotp(
                self.raw_can, SERVICE_RESPONSE_ID, SERVICE_REQUEST_ID, deadline,
                max_packet_size=MAX_RESPONSE_PACKET_SIZE,
                block_size=self.block_size,
            )
            response = decode_packet(complete)
        except ValueError as exc:
            raise FramingError(f"service response framing failed: {exc}") from exc
        return self._accept_response(response, command, sequence)

    def info_during_activity(self, activity, *, timeout: float) -> ServiceInfo:
        read_pending = getattr(self.raw_can, "read_pending_frame", None)
        if read_pending is None:
            activity(timeout)
            return self.info(timeout=min(timeout, 5.0))

        sequence, request = self._prepare_request(COMMAND_INFO, b"")
        length = len(request)
        first_frame = bytes([
            ISOTP_FIRST_FRAME | (length >> 8), length & 0xFF,
        ]) + request[:6]
        final_frame = bytes([
            ISOTP_CONSECUTIVE_FRAME | 1,
        ]) + request[6:]
        deadline = time.monotonic() + timeout
        next_probe = 0.0

        while time.monotonic() < deadline:
            activity(0.001)
            now = time.monotonic()
            if now >= next_probe:
                try:
                    _send_can_frame(
                        self.raw_can, SERVICE_REQUEST_ID, first_frame
                    )
                except CanTxBufferFull:
                    pass
                next_probe = now + 0.1

            while True:
                frame = read_pending()
                if frame is None:
                    break
                data = frame.data
                if (frame.extended or frame.remote
                        or frame.can_id != SERVICE_RESPONSE_ID
                        or not data
                        or data[0] & ISOTP_TYPE_MASK != ISOTP_FLOW_CONTROL
                        or data[0] & 0x0F != ISOTP_FLOW_STATUS_CTS):
                    continue

                while True:
                    try:
                        _send_can_frame(
                            self.raw_can, SERVICE_REQUEST_ID, final_frame
                        )
                        break
                    except CanTxBufferFull:
                        time.sleep(0.001)

                try:
                    complete = _receive_isotp(
                        self.raw_can, SERVICE_RESPONSE_ID,
                        SERVICE_REQUEST_ID, time.monotonic() + 5.0,
                        max_packet_size=MAX_RESPONSE_PACKET_SIZE,
                        block_size=self.block_size,
                    )
                    response = decode_packet(complete)
                except ValueError as exc:
                    raise FramingError(
                        f"service response framing failed: {exc}"
                    ) from exc
                payload = self._accept_response(
                    response, COMMAND_INFO, sequence
                )
                return self._decode_info(payload)

        raise TimeoutError(
            f"service mode did not respond within {timeout:g}s"
        )


class ServicePacketClient(_ServiceClient):
    """Service client over a transport carrying complete binary packets."""

    def __init__(self, packet_transport) -> None:
        super().__init__()
        self.packet_transport = packet_transport

    def request(self, command: int, payload: bytes = b"", *,
                timeout: float = 5.0) -> bytes:
        sequence, request = self._prepare_request(command, payload)
        raw_response = self.packet_transport.exchange_service_packet(
            request, timeout=timeout
        )
        try:
            response = decode_packet(raw_response)
        except ValueError as exc:
            raise FramingError(
                f"service response framing failed: {exc}"
            ) from exc
        return self._accept_response(response, command, sequence)

    def enter(self, *, timeout: float = 35.0) -> ServiceInfo:
        payload = self.request(
            COMMAND_AIRCANNECT_ENTER, timeout=timeout
        )
        return self._decode_info(payload)

#!/usr/bin/env python3
"""Shared CAN framing helpers for AS11 transports."""

from __future__ import annotations

import binascii
import struct
from dataclasses import dataclass

from as11_rpc import TransportError


class CanTxBufferFull(TransportError):
    """The adapter cannot queue another frame yet."""


def parse_int(text: str) -> int:
    return int(text.replace("_", ""), 0)


def hex_bytes(data: bytes) -> str:
    return " ".join(f"{b:02X}" for b in data)


@dataclass
class CanFrame:
    timestamp: float
    can_id: int
    extended: bool
    remote: bool
    data: bytes
    raw: bytes

    @property
    def id_width(self) -> int:
        return 8 if self.extended else 3

    def format(self, start_time: float | None = None, raw: bool = False) -> str:
        ts = self.timestamp if start_time is None else self.timestamp - start_time
        kind = "ext" if self.extended else "std"
        rtr = " rtr" if self.remote else ""
        line = (
            f"{ts:10.6f}  {kind}{rtr}  "
            f"0x{self.can_id:0{self.id_width}X}  [{len(self.data)}]  {hex_bytes(self.data)}"
        )
        if raw:
            line += f"    raw: {hex_bytes(self.raw)}"
        return line


DEFAULT_RPC_TX_ID = 0x383
DEFAULT_RPC_RX_ID = 0x382


class CanDatagramCodec:
    """AS11 DatagramCan fragmentation over classic 8-byte CAN frames."""

    FLAG_MULTI_START = 0x01
    FLAG_MULTI_END = 0x02
    FLAG_SINGLE = 0x03
    FLAG_MASK = 0x03

    def __init__(self) -> None:
        self._parts: list[bytes] = []
        self._expected_crc: int | None = None

    def reset(self) -> None:
        self._parts.clear()
        self._expected_crc = None

    @staticmethod
    def encode(payload: bytes) -> list[bytes]:
        if len(payload) <= 7:
            return [bytes([CanDatagramCodec.FLAG_SINGLE]) + payload]
        crc = binascii.crc32(payload) & 0xFFFFFFFF
        frames = [
            bytes([CanDatagramCodec.FLAG_MULTI_START])
            + struct.pack("<I", crc)
            + payload[:3]
        ]
        offset = 3
        while offset < len(payload):
            chunk = payload[offset: offset + 7]
            offset += len(chunk)
            flag = CanDatagramCodec.FLAG_MULTI_END if offset >= len(payload) else 0x00
            frames.append(bytes([flag]) + chunk)
        return frames

    def feed(self, data: bytes) -> bytes | None:
        if not data:
            return None
        flag = data[0] & self.FLAG_MASK
        if flag == self.FLAG_SINGLE:
            self._parts.clear()
            self._expected_crc = None
            return bytes(data[1:])
        if flag == self.FLAG_MULTI_START:
            if len(data) < 5:
                raise ValueError("CAN datagram start frame too short")
            self._parts = [bytes(data[5:])]
            self._expected_crc = struct.unpack("<I", data[1:5])[0]
            return None
        if flag == 0x00:
            if not self._parts:
                # ignore orphan middle fragments and wait for the next
                # start frame instead of failing the whole transport.
                return None
            self._parts.append(bytes(data[1:]))
            return None
        if flag == self.FLAG_MULTI_END:
            if not self._parts:
                return None
            self._parts.append(bytes(data[1:]))
            payload = b"".join(self._parts)
            expected = self._expected_crc
            self._parts.clear()
            self._expected_crc = None
            actual = binascii.crc32(payload) & 0xFFFFFFFF
            if actual != expected:
                raise ValueError(
                    f"CAN datagram CRC mismatch "
                    f"(expected {expected:#010x}, got {actual:#010x}, "
                    f"len={len(payload)}, "
                    f"head={payload[:32].hex()}, tail={payload[-32:].hex()})"
                )
            return payload
        raise ValueError(f"CAN datagram unknown flag {flag:#x}")


__all__ = [
    "CanDatagramCodec",
    "CanFrame",
    "DEFAULT_RPC_RX_ID",
    "DEFAULT_RPC_TX_ID",
    "hex_bytes",
    "parse_int",
]

#!/usr/bin/env python3
"""SocketCAN transport for AS11 CAN RPC.

This backend talks to a pre-configured Linux CAN network interface such as
``can0``, ``slcan0`` or ``vcan0``. Interface bring-up, bitrate selection and
listen-only mode remain the caller's responsibility outside this tool.
"""

from __future__ import annotations

import argparse
import errno
import json as _json
import logging as _logging
import socket
import struct
import time
from dataclasses import dataclass as _dataclass

from as11_can_common import (
    CanTxBufferFull,
    CanDatagramCodec,
    CanFrame,
    DEFAULT_RPC_RX_ID,
    DEFAULT_RPC_TX_ID,
    hex_bytes,
)
from as11_rpc import FramingError, TransportError, build_request


DEFAULT_TIMEOUT = 5.0
_FRAME_STRUCT = struct.Struct("=IB3x8s")

_CAN_EFF_FLAG = getattr(socket, "CAN_EFF_FLAG", 0x80000000)
_CAN_RTR_FLAG = getattr(socket, "CAN_RTR_FLAG", 0x40000000)
_CAN_ERR_FLAG = getattr(socket, "CAN_ERR_FLAG", 0x20000000)
_CAN_SFF_MASK = getattr(socket, "CAN_SFF_MASK", 0x000007FF)
_CAN_EFF_MASK = getattr(socket, "CAN_EFF_MASK", 0x1FFFFFFF)

_log_can_rpc = _logging.getLogger("as11.can_socketcan")


def require_socketcan() -> None:
    if not hasattr(socket, "AF_CAN") or not hasattr(socket, "CAN_RAW"):
        raise SystemExit("SocketCAN requires Python socket.AF_CAN / socket.CAN_RAW support")


@_dataclass
class _SocketcanConfig:
    ifname: str
    bitrate: int = 1_000_000
    mode: str = "normal"
    tx_id: int = DEFAULT_RPC_TX_ID
    rx_id: int = DEFAULT_RPC_RX_ID
    frame_interval: float = 0.0
    debug: bool = False


class _SocketcanRaw:
    """Minimal wrapper around a Linux CAN_RAW socket."""

    def __init__(self, ifname: str, *, timeout: float = 0.05, debug: bool = False) -> None:
        require_socketcan()
        self.sock = socket.socket(socket.AF_CAN, socket.SOCK_RAW, socket.CAN_RAW)
        self.sock.settimeout(timeout)
        self.timeout = timeout
        self.debug = debug
        self.ifname = ifname
        try:
            self.sock.bind((ifname,))
        except OSError:
            self.sock.close()
            raise

    def close(self) -> None:
        try:
            self.sock.close()
        except Exception:
            pass

    def __enter__(self) -> "_SocketcanRaw":
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def _set_timeout_from_deadline(self, deadline: float | None) -> None:
        if deadline is None:
            self.sock.settimeout(self.timeout)
            return
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            self.sock.settimeout(0.0)
            return
        self.sock.settimeout(remaining)

    def read_frame(self, deadline: float | None = None) -> CanFrame | None:
        while deadline is None or time.monotonic() < deadline:
            self._set_timeout_from_deadline(deadline)
            try:
                raw = self.sock.recv(_FRAME_STRUCT.size)
            except TimeoutError:
                return None
            except OSError as exc:
                raise TransportError(f"SocketCAN read failed on {self.ifname!r}: {exc}") from exc

            if len(raw) < _FRAME_STRUCT.size:
                if self.debug:
                    _log_can_rpc.debug("short CAN frame (%d B)", len(raw))
                continue
            if self.debug:
                _log_can_rpc.debug("raw <<< %s", hex_bytes(raw))

            can_id_raw, can_dlc, data = _FRAME_STRUCT.unpack(raw[:_FRAME_STRUCT.size])
            if can_id_raw & _CAN_ERR_FLAG:
                if self.debug:
                    _log_can_rpc.debug("error frame <<< 0x%08X", can_id_raw)
                continue

            extended = bool(can_id_raw & _CAN_EFF_FLAG)
            remote = bool(can_id_raw & _CAN_RTR_FLAG)
            can_id = can_id_raw & (_CAN_EFF_MASK if extended else _CAN_SFF_MASK)
            return CanFrame(
                timestamp=time.time(),
                can_id=can_id,
                extended=extended,
                remote=remote,
                data=b"" if remote else data[:can_dlc],
                raw=raw[:_FRAME_STRUCT.size],
            )
        return None

    def send_frame(self, can_id: int, data: bytes, *, extended: bool = False,
                   remote: bool = False, timeout: float = 1.0) -> None:
        if extended:
            if not 0 <= can_id <= _CAN_EFF_MASK:
                raise ValueError("extended CAN ID must be in range 0..0x1fffffff")
            can_id_raw = can_id | _CAN_EFF_FLAG
        else:
            if not 0 <= can_id <= _CAN_SFF_MASK:
                raise ValueError("standard CAN ID must be in range 0..0x7ff")
            can_id_raw = can_id
        if remote:
            can_id_raw |= _CAN_RTR_FLAG
        if len(data) > 8:
            raise ValueError("classic CAN data payload is limited to 8 bytes")
        raw = _FRAME_STRUCT.pack(can_id_raw, len(data), data.ljust(8, b"\x00"))
        if self.debug:
            _log_can_rpc.debug("raw >>> %s", hex_bytes(raw))
        deadline = time.monotonic() + timeout
        while True:
            try:
                self.sock.send(raw)
                return
            except OSError as exc:
                if exc.errno not in (errno.ENOBUFS, errno.EAGAIN, errno.EWOULDBLOCK):
                    raise TransportError(f"SocketCAN write failed on {self.ifname!r}: {exc}") from exc
                if time.monotonic() >= deadline:
                    raise CanTxBufferFull(
                        f"SocketCAN transmit queue remained full on {self.ifname!r}"
                    ) from exc
                time.sleep(0.0005)


class CanSocketcanTransport:
    """JSON-RPC transport over a Linux SocketCAN interface."""

    DEFAULT_TIMEOUT = DEFAULT_TIMEOUT

    def __init__(self, ifname: str, *, bitrate: int = 1_000_000,
                 mode: str = "normal",
                 tx_id: int = DEFAULT_RPC_TX_ID, rx_id: int = DEFAULT_RPC_RX_ID,
                 frame_interval: float = 0.0,
                 debug: bool = False) -> None:
        self._cfg = _SocketcanConfig(
            ifname=ifname,
            bitrate=bitrate,
            mode=mode,
            tx_id=tx_id,
            rx_id=rx_id,
            frame_interval=frame_interval,
            debug=debug,
        )
        self._dev: _SocketcanRaw | None = None
        self._rx_codec = CanDatagramCodec()
        self._rpc_id = 0
        self._notification_handler = None
        self._notification_stop = False

    @classmethod
    def from_args(cls, target: str, args: argparse.Namespace) -> "CanSocketcanTransport":
        return cls(
            ifname=target,
            bitrate=getattr(args, "bitrate", 1_000_000),
            mode=getattr(args, "mode", "normal"),
            tx_id=getattr(args, "tx_id", DEFAULT_RPC_TX_ID),
            rx_id=getattr(args, "rx_id", DEFAULT_RPC_RX_ID),
            frame_interval=getattr(args, "frame_interval", 0.0),
            debug=getattr(args, "debug", False),
        )

    @property
    def name(self) -> str:
        return f"can:socketcan:{self._cfg.ifname}"

    @property
    def supports_encrypted(self) -> bool:
        return False

    @property
    def dev(self) -> _SocketcanRaw:
        if self._dev is None:
            raise TransportError("transport not connected")
        return self._dev

    def connect(self) -> None:
        if self._dev is not None:
            return
        cfg = self._cfg
        try:
            dev = _SocketcanRaw(cfg.ifname, timeout=0.05, debug=cfg.debug)
        except OSError as exc:
            raise TransportError(f"SocketCAN bind failed on {cfg.ifname!r}: {exc}") from exc
        self._dev = dev
        self._rx_codec = CanDatagramCodec()
        if cfg.debug and (cfg.bitrate != 1_000_000 or cfg.mode != "normal"):
            _log_can_rpc.debug(
                "socketcan backend does not configure interface bitrate/mode; "
                "using preconfigured %s (requested bitrate=%s mode=%s)",
                cfg.ifname,
                cfg.bitrate,
                cfg.mode,
            )

    def close(self) -> None:
        if self._dev is not None:
            try:
                self._dev.close()
            finally:
                self._dev = None

    def __enter__(self) -> "CanSocketcanTransport":
        self.connect()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def _next_id(self) -> int:
        self._rpc_id += 1
        return self._rpc_id

    def send_payload(self, payload: bytes) -> None:
        frames = CanDatagramCodec.encode(payload)
        for idx, frame in enumerate(frames):
            self.dev.send_frame(self._cfg.tx_id, frame, extended=False)
            if self._cfg.debug:
                _log_can_rpc.debug("TX 0x%03X %s", self._cfg.tx_id, hex_bytes(frame))
            if self._cfg.frame_interval > 0 and idx + 1 < len(frames):
                time.sleep(self._cfg.frame_interval)

    def recv_payload(self, *, timeout: float) -> bytes:
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(
                    f"no CAN datagram on 0x{self._cfg.rx_id:03X} within {timeout:.1f}s"
                )
            frame = self.dev.read_frame(deadline=deadline)
            if frame is None:
                continue
            if frame.extended or frame.can_id != self._cfg.rx_id:
                if self._cfg.debug:
                    _log_can_rpc.debug(
                        "rx skipped (id=0x%03X ext=%s): %s",
                        frame.can_id,
                        frame.extended,
                        hex_bytes(frame.data),
                    )
                continue
            data = bytes(frame.data)
            if self._cfg.debug:
                flag = data[0] & 0x03 if data else -1
                flag_name = {
                    0x00: "MID",
                    0x01: "START",
                    0x02: "END",
                    0x03: "SINGLE",
                }.get(flag, f"?{flag}")
                _log_can_rpc.debug(
                    "rx 0x%03X dlc=%d %-6s %s",
                    frame.can_id,
                    len(data),
                    flag_name,
                    data.hex(),
                )
            try:
                payload = self._rx_codec.feed(data)
            except ValueError as exc:
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

    def rpc(self, method: str, params: object | None = None, *,
            timeout: float = DEFAULT_TIMEOUT,
            post_send_delay: float = 0.0) -> dict:
        rpc_id = self._next_id()
        payload = build_request(method, params, rpc_id)
        self.send_payload(payload)
        if post_send_delay > 0:
            time.sleep(post_send_delay)
        return self._rpc_await_response(rpc_id, timeout)

    def _rpc_await_response(self, rpc_id: int, timeout: float) -> dict:
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(f"no RPC response for id={rpc_id} within {timeout:.1f}s")
            raw = self.recv_payload(timeout=remaining)
            try:
                obj = _json.loads(raw.decode("utf-8", errors="replace"))
            except _json.JSONDecodeError:
                continue
            if isinstance(obj, dict) and "method" in obj and "id" not in obj:
                self._dispatch_notification(obj)
                continue
            if obj.get("id") == rpc_id:
                return obj
            _log_can_rpc.debug("unmatched id=%s (want %s)", obj.get("id"), rpc_id)

    def _dispatch_notification(self, msg: dict) -> None:
        if self._notification_handler is None:
            return
        try:
            if self._notification_handler(msg):
                self._notification_stop = True
        except Exception as exc:
            _log_can_rpc.warning("notification handler raised: %s", exc)

    def set_notification_handler(self, handler) -> None:
        self._notification_handler = handler
        self._notification_stop = False

    def listen_for_notifications(self, *, duration: float | None = None) -> None:
        deadline = (time.monotonic() + duration) if duration else None
        try:
            while True:
                if self._notification_stop:
                    return
                if deadline is not None and time.monotonic() >= deadline:
                    return
                try:
                    raw = self.recv_payload(
                        timeout=max(0.05, (deadline - time.monotonic()) if deadline else 1.0)
                    )
                except TimeoutError:
                    continue
                except FramingError as exc:
                    _log_can_rpc.warning("notify framing error (skipped): %s", exc)
                    continue
                try:
                    msg = _json.loads(raw.decode("utf-8", errors="replace"))
                except (_json.JSONDecodeError, UnicodeDecodeError):
                    continue
                if isinstance(msg, dict) and "method" in msg and "id" not in msg:
                    self._dispatch_notification(msg)
        except KeyboardInterrupt:
            return


__all__ = ["CanSocketcanTransport"]

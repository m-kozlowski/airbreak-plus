#!/usr/bin/env python3
"""AS11 JSON-RPC over TCP - AirCANnect host transport

This backend bridges to an AS11 device through an AirCANnect TCP server (or
any compatible host-transport server). The wire protocol is one complete
AS11 JSON-RPC document per line, LF-delimited, in both directions.

- Plain TCP, no TLS, no HTTP, no auth, no banner, no greeting.
- Multi-client broadcast: the bridge forwards every AS11 response and
  notification to all connected TCP clients. The host must filter by
  request `id` and ignore unrelated lines.
- AirCANnect itself owns a request-id range, so host clients should pick
  large random numeric ids to avoid collisions.
- Non-JSON lines (for example `ERR: max clients`) are transport errors.
- No bridge-level ack: a failed enqueue surfaces as a timeout.

"""

from __future__ import annotations

import argparse
import json as _json
import logging as _logging
import os
import random
import socket
import time
from dataclasses import dataclass as _dataclass

from as11_rpc import FramingError, TransportError, build_request


DEFAULT_PORT = 39011
DEFAULT_TIMEOUT = 8.0
LINE_LIMIT_HOST_TO_BRIDGE = 2048
LINE_LIMIT_BRIDGE_TO_HOST = 16 * 1024  # generous; bridge does not enforce a hard cap

_log = _logging.getLogger("as11.aircannect")


@_dataclass
class _AirCannectConfig:
    host: str
    port: int = DEFAULT_PORT
    debug: bool = False


def parse_target(target: str, *, default_port: int = DEFAULT_PORT) -> tuple[str, int]:
    """Parse ``host``, ``host:port`` or ``[ipv6]:port`` into (host, port)."""
    s = target.strip()
    if not s:
        raise SystemExit("aircannect: empty target (expected host[:port])")
    if s.startswith("["):
        # bracketed IPv6 literal
        close = s.find("]")
        if close < 0:
            raise SystemExit(f"aircannect: malformed IPv6 literal in {target!r}")
        host = s[1:close]
        rest = s[close + 1:]
        if rest.startswith(":"):
            try:
                port = int(rest[1:], 0)
            except ValueError as exc:
                raise SystemExit(
                    f"aircannect: bad port in {target!r}: {exc}") from exc
        elif not rest:
            port = default_port
        else:
            raise SystemExit(
                f"aircannect: unexpected text after IPv6 bracket in {target!r}")
        return host, port
    if s.count(":") == 1 and "." not in s.split(":", 1)[1]:
        # plain host:port (rule out raw IPv6, which has multiple colons)
        host, _, port_str = s.partition(":")
        try:
            port = int(port_str, 0)
        except ValueError as exc:
            raise SystemExit(
                f"aircannect: bad port in {target!r}: {exc}") from exc
        return host, port
    if ":" not in s:
        return s, default_port
    raise SystemExit(
        f"aircannect: ambiguous target {target!r}; wrap IPv6 in [brackets]")


class AirCannectTransport:
    """JSON-RPC transport over the AirCANnect line-based TCP bridge.

    Concurrency: the underlying socket is read inline during `rpc()` and
    `listen_for_notifications()`. Notifications received while waiting for
    an RPC response are dispatched to the registered notification handler.
    """

    DEFAULT_TIMEOUT = DEFAULT_TIMEOUT

    def __init__(self, host: str, port: int = DEFAULT_PORT,
                 *, debug: bool = False) -> None:
        self._cfg = _AirCannectConfig(host=host, port=port, debug=debug)
        self._sock: socket.socket | None = None
        self._buf = bytearray()
        # Per the spec: use a large random id base and increment monotonically
        # to avoid collision with AirCANnect's own request IDs.
        self._rpc_id = random.SystemRandom().randrange(
            0x10000000, 0x7FFFFF00)
        self._notification_handler = None
        self._notification_stop = False

    @classmethod
    def from_args(cls, target: str, args: argparse.Namespace
                  ) -> "AirCannectTransport":
        host, port = parse_target(target,
                                  default_port=getattr(args, "aircannect_port",
                                                       DEFAULT_PORT))
        return cls(
            host=host,
            port=port,
            debug=getattr(args, "debug", False),
        )

    @property
    def name(self) -> str:
        return f"tcp:aircannect:{self._cfg.host}:{self._cfg.port}"

    @property
    def supports_encrypted(self) -> bool:
        # AirCANnect bridges to the device over CAN
        return False

    @property
    def sock(self) -> socket.socket:
        if self._sock is None:
            raise TransportError("transport not connected")
        return self._sock

    def connect(self) -> None:
        if self._sock is not None:
            return
        cfg = self._cfg
        try:
            s = socket.create_connection((cfg.host, cfg.port),
                                         timeout=DEFAULT_TIMEOUT)
        except OSError as exc:
            raise TransportError(
                f"aircannect connect failed: {cfg.host}:{cfg.port}: {exc}"
            ) from exc
        try:
            s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        except OSError:
            pass
        s.settimeout(None)  # we manage deadlines per-call
        self._sock = s
        self._buf.clear()
        if cfg.debug:
            _log.debug("connected to %s:%d", cfg.host, cfg.port)

    def close(self) -> None:
        if self._sock is not None:
            try:
                self._sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None
        self._buf.clear()

    def __enter__(self) -> "AirCannectTransport":
        self.connect()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def _next_id(self) -> int:
        self._rpc_id += 1
        return self._rpc_id

    def _send_line(self, payload: bytes) -> None:
        if len(payload) + 1 > LINE_LIMIT_HOST_TO_BRIDGE:
            raise TransportError(
                f"request line {len(payload) + 1} B exceeds AirCANnect "
                f"host->bridge line limit ({LINE_LIMIT_HOST_TO_BRIDGE} B)")
        try:
            self.sock.sendall(payload + b"\n")
        except OSError as exc:
            raise TransportError(f"aircannect send failed: {exc}") from exc
        if self._cfg.debug:
            _log.debug("TX %s", payload[:120].decode("utf-8", "replace"))

    def _read_line(self, *, deadline: float | None) -> bytes:
        """Read one LF-terminated line. Returns the line without LF or CR.

        Raises TimeoutError if `deadline` passes before a line completes.
        Raises TransportError on socket closure or other I/O error.
        """
        # Fast path: an entire line is already buffered.
        nl = self._buf.find(b"\n")
        while nl < 0:
            if deadline is None:
                remaining = None
            else:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("aircannect read deadline reached")
            try:
                self.sock.settimeout(remaining if remaining is not None else None)
                chunk = self.sock.recv(4096)
            except socket.timeout as exc:
                raise TimeoutError(
                    "aircannect read timed out") from exc
            except OSError as exc:
                raise TransportError(
                    f"aircannect read failed: {exc}") from exc
            if not chunk:
                raise TransportError("aircannect connection closed by peer")
            self._buf.extend(chunk)
            if self._cfg.debug:
                _log.debug("rx %d B (buf=%d)", len(chunk), len(self._buf))
            nl = self._buf.find(b"\n")
            if len(self._buf) > LINE_LIMIT_BRIDGE_TO_HOST and nl < 0:
                raise TransportError(
                    f"aircannect inbound line exceeded "
                    f"{LINE_LIMIT_BRIDGE_TO_HOST} B without LF")
        line = bytes(self._buf[:nl])
        del self._buf[:nl + 1]
        if line.endswith(b"\r"):
            line = line[:-1]
        return line

    def rpc(self, method: str, params: object | None = None, *,
            timeout: float = DEFAULT_TIMEOUT,
            post_send_delay: float = 0.0) -> dict:
        rpc_id = self._next_id()
        payload = build_request(method, params, rpc_id)
        self._send_line(payload)
        if post_send_delay > 0:
            time.sleep(post_send_delay)
        return self._await_response(rpc_id, timeout=timeout)

    def _await_response(self, rpc_id: int, *, timeout: float) -> dict:
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(
                    f"no RPC response for id={rpc_id} within {timeout:.1f}s")
            line = self._read_line(deadline=deadline)
            if not line:
                continue  # blank keepalive
            text = line.decode("utf-8", errors="replace")
            try:
                obj = _json.loads(text)
            except _json.JSONDecodeError:
                # Bridge-level error strings (e.g. "ERR: max clients") are not
                # JSON. Per the spec, treat as a transport error.
                raise TransportError(
                    f"aircannect non-JSON line: {text!r}")
            if not isinstance(obj, dict):
                if self._cfg.debug:
                    _log.debug("dropping non-object response: %r", obj)
                continue
            if "method" in obj and "id" not in obj:
                self._dispatch_notification(obj)
                continue
            if obj.get("id") == rpc_id:
                if self._cfg.debug:
                    _log.debug("RX matching id=%d", rpc_id)
                return obj
            if self._cfg.debug:
                _log.debug("dropping unrelated response id=%s (waiting for %s)",
                           obj.get("id"), rpc_id)

    def _dispatch_notification(self, msg: dict) -> None:
        if self._notification_handler is None:
            if self._cfg.debug:
                _log.debug("unhandled notification: method=%s",
                           msg.get("method"))
            return
        try:
            if self._notification_handler(msg):
                self._notification_stop = True
        except Exception as exc:
            _log.warning("notification handler raised: %s", exc)

    def set_notification_handler(self, handler) -> None:
        self._notification_handler = handler
        self._notification_stop = False

    def listen_for_notifications(self, *, duration: float | None = None) -> None:
        """Drain the socket and dispatch notifications.

        Returns when `duration` expires, the handler returns truthy, the
        connection drops, or KeyboardInterrupt is raised.
        """
        deadline = (time.monotonic() + duration) if duration is not None else None
        try:
            while True:
                if self._notification_stop:
                    return
                if deadline is not None and time.monotonic() >= deadline:
                    return
                # Cap each blocking read so KeyboardInterrupt has a chance to
                # land on the main thread. 1s slice mirrors the SocketCAN transport.
                if deadline is None:
                    slice_deadline = time.monotonic() + 1.0
                else:
                    slice_deadline = min(deadline, time.monotonic() + 1.0)
                try:
                    line = self._read_line(deadline=slice_deadline)
                except TimeoutError:
                    continue
                if not line:
                    continue
                text = line.decode("utf-8", errors="replace")
                try:
                    msg = _json.loads(text)
                except _json.JSONDecodeError:
                    _log.warning(
                        "aircannect non-JSON line dropped during listen: %r",
                        text)
                    continue
                if isinstance(msg, dict) and "method" in msg and "id" not in msg:
                    self._dispatch_notification(msg)
                # Unrelated responses (e.g. another raw TCP client's reply) are
                # ignored on the notification path.
        except KeyboardInterrupt:
            return


class AirCannectServiceTransport(AirCannectTransport):
    """Complete AS11 service packets over AirCANnect's binary TCP mode."""

    @staticmethod
    def _packet_size_from_header(header: bytes) -> int:
        from as11_service import MAX_RESPONSE_PACKET_SIZE, PACKET_MAGIC

        if len(header) != 8:
            raise FramingError(
                f"AirCANnect service header has {len(header)} bytes; expected 8"
            )
        if header[0] != PACKET_MAGIC:
            raise FramingError(
                f"AirCANnect service response has bad magic 0x{header[0]:02X}"
            )
        payload_length = int.from_bytes(header[6:8], "little")
        packet_size = 8 + payload_length + 2
        if packet_size > MAX_RESPONSE_PACKET_SIZE:
            raise FramingError(
                f"AirCANnect service response declares {packet_size} bytes; "
                f"limit is {MAX_RESPONSE_PACKET_SIZE}"
            )
        return packet_size

    def _read_exact(self, size: int, *, deadline: float) -> bytes:
        result = bytearray()
        while len(result) < size:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("AirCANnect service response timed out")
            try:
                self.sock.settimeout(remaining)
                chunk = self.sock.recv(size - len(result))
            except socket.timeout as exc:
                raise TimeoutError(
                    "AirCANnect service response timed out"
                ) from exc
            except OSError as exc:
                raise TransportError(
                    f"AirCANnect service read failed: {exc}"
                ) from exc
            if not chunk:
                raise TransportError(
                    "AirCANnect service connection closed before response completed"
                )
            result.extend(chunk)
        return bytes(result)

    def exchange_service_packet(self, packet: bytes, *, timeout: float) -> bytes:
        deadline = time.monotonic() + timeout
        try:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("AirCANnect service request timed out")
            self.sock.settimeout(remaining)
            self.sock.sendall(packet)
            header = self._read_exact(8, deadline=deadline)
            packet_size = self._packet_size_from_header(header)
            return header + self._read_exact(packet_size - 8, deadline=deadline)
        except (FramingError, TimeoutError, TransportError):
            self.close()
            raise
        except OSError as exc:
            self.close()
            raise TransportError(
                f"AirCANnect service write failed: {exc}"
            ) from exc


def add_args(p: argparse.ArgumentParser) -> None:
    suppr = argparse.SUPPRESS
    g = p.add_argument_group("AirCANnect bridge (ignored unless -d tcp:...)")
    g.add_argument("--aircannect-port", type=int, default=suppr,
                   help=f"TCP port if -d tcp:<host> omits the port "
                        f"(default {DEFAULT_PORT})")


__all__ = [
    "AirCannectServiceTransport",
    "AirCannectTransport",
    "DEFAULT_PORT",
    "add_args",
    "from_args",
    "parse_target",
    "service_from_args",
]


def from_args(target: str, args: argparse.Namespace) -> AirCannectTransport:
    return AirCannectTransport.from_args(target, args)


def service_from_args(target: str,
                      args: argparse.Namespace) -> AirCannectServiceTransport:
    return AirCannectServiceTransport.from_args(target, args)

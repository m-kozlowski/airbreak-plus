#!/usr/bin/env python3
"""CANable/CANable 2.x SLCAN transport for AS11 CAN RPC."""

from __future__ import annotations

import argparse
import json as _json
import logging as _logging
import time
from collections import deque
from dataclasses import dataclass as _dataclass

try:
    import serial
except Exception:  # pragma: no cover
    serial = None

from as11_can_common import (
    CanTxBufferFull,
    CanDatagramCodec,
    CanFrame,
    DEFAULT_RPC_RX_ID,
    DEFAULT_RPC_TX_ID,
    hex_bytes,
)
from as11_rpc import FramingError, TransportError, build_request


SERIAL_BAUD_DEFAULT = 2_000_000
SERIAL_BAUD_CANDIDATES = (
    2_000_000,
    1_000_000,
    460_800,
    115_200,
)
DEFAULT_TIMEOUT = 5.0
FRAME_BATCH_SIZE = 8
FRAME_BATCH_INTERVAL = 0.0

ELMUE_BITRATE_CODES = {
    10_000: "0",
    20_000: "1",
    50_000: "2",
    100_000: "3",
    125_000: "4",
    250_000: "5",
    500_000: "6",
    800_000: "7",
    1_000_000: "8",
}

LEGACY_BITRATE_CODES = {
    10_000: "0",
    20_000: "1",
    50_000: "2",
    100_000: "3",
    125_000: "4",
    250_000: "5",
    500_000: "6",
    750_000: "7",
    1_000_000: "8",
    83_300: "9",
}

SLCAN_FEEDBACK = {
    "": "success",
    "1": "invalid command",
    "2": "invalid parameter",
    "3": "command requires adapter to be open",
    "4": "command requires adapter to be closed",
    "5": "firmware/HAL error",
    "6": "unsupported feature or board capability",
    "7": "CAN TX buffer full",
    "8": "CAN bus off",
    "9": "cannot send in silent mode",
    ":": "baud rate not set",
    ";": "option-byte programming failed",
    "<": "USB reconnect required",
}

MODE_TO_OPEN_COMMAND = {
    "normal": "ON",
    "silent": "OS",
}

LEGACY_MODE_TO_PREOPEN_COMMAND = {
    "normal": "M0",
    "silent": "M1",
}

_log_can_rpc = _logging.getLogger("as11.can_canable")


def require_serial() -> None:
    if serial is None:
        raise SystemExit("pyserial is required")


def _deadline_after(timeout: float | None) -> float | None:
    if timeout is None:
        return None
    return time.monotonic() + timeout


def _remaining(deadline: float | None) -> float | None:
    if deadline is None:
        return None
    return deadline - time.monotonic()


def _readable_ascii(data: bytes) -> str:
    return data.decode("ascii", errors="replace")


def _format_slcan_frame(can_id: int, data: bytes, *, extended: bool, remote: bool) -> str:
    kind = (
        "R" if extended and remote else
        "T" if extended else
        "r" if remote else
        "t"
    )
    can_text = f"{can_id:08X}" if extended else f"{can_id:03X}"
    return f"{kind}{can_text}{len(data):X}{data.hex().upper()}"


def _parse_slcan_frame_prefix(text: str) -> tuple[CanFrame | None, int]:
    if not text:
        return None, 0

    channel_prefix = ""
    offset = 0
    if text[0] in "&$":
        channel_prefix = text[0]
        offset = 1
    if len(text) <= offset:
        return None, 0

    frame_type = text[offset]
    if frame_type not in "tTrRdDbB":
        return None, 0

    extended = frame_type in "TDRB"
    remote = frame_type in "Rr"
    is_fd = frame_type in "DdBb"
    if is_fd:
        # AS11 uses classic CAN with 8-byte payloads; the backend does not
        # need CAN FD support right now.
        return None, 0

    id_len = 8 if extended else 3
    header_end = offset + 1 + id_len + 1
    if len(text) < header_end:
        return None, 0

    try:
        can_id = int(text[offset + 1:offset + 1 + id_len], 16)
        dlc = int(text[offset + 1 + id_len], 16)
    except ValueError:
        return None, 0
    if dlc > 8:
        return None, 0

    data_start = header_end
    data_end = data_start + (0 if remote else dlc * 2)
    if len(text) < data_end:
        return None, 0

    data_hex = text[data_start:data_end]
    try:
        data = b"" if remote else bytes.fromhex(data_hex)
    except ValueError:
        return None, 0

    raw_text = text[:data_end]
    raw = raw_text.encode("ascii", errors="replace") + b"\r"
    return CanFrame(
        timestamp=time.time(),
        can_id=can_id,
        extended=extended,
        remote=remote,
        data=data,
        raw=raw,
    ), data_end


def _parse_slcan_frame(line: str) -> CanFrame | None:
    frame, consumed = _parse_slcan_frame_prefix(line)
    if frame is None or consumed != len(line):
        return None
    return frame


def _parse_slcan_frames(line: str) -> list[CanFrame]:
    """Parse a line as either one exact frame or a concatenation of exact
    frames with missing CR separators. If any trailing text is not itself a
    valid frame, reject the whole line instead of silently accepting a prefix.
    """
    frames: list[CanFrame] = []
    text = line
    while text:
        frame, consumed = _parse_slcan_frame_prefix(text)
        if frame is None or consumed <= 0:
            return []
        frames.append(frame)
        text = text[consumed:]
    return frames


@_dataclass
class _CanableConfig:
    port: str
    bitrate: int = 1_000_000
    mode: str = "normal"
    serial_bauds: tuple[int, ...] = SERIAL_BAUD_CANDIDATES
    tx_id: int = DEFAULT_RPC_TX_ID
    rx_id: int = DEFAULT_RPC_RX_ID
    frame_interval: float = 0.0
    reset_buffers: bool = True
    dtr: bool | None = None
    rts: bool | None = None
    debug: bool = False


class _CanableSlcan:
    """Minimal serial SLCAN adapter wrapper for CANable-class devices."""

    def __init__(
        self,
        port: str,
        *,
        serial_baud: int = SERIAL_BAUD_DEFAULT,
        timeout: float = 0.05,
        open_delay: float = 0.05,
        dtr: bool | None = None,
        rts: bool | None = None,
        reset_buffers: bool = True,
        debug: bool = False,
    ) -> None:
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
        if dtr is not None:
            self.ser.dtr = dtr
        if rts is not None:
            self.ser.rts = rts
        self.timeout = timeout
        self.debug = debug
        self._rx_frames: deque[CanFrame] = deque()
        self._version_text: str | None = None
        self._protocol = "unknown"
        if open_delay:
            time.sleep(open_delay)
        if reset_buffers:
            self.reset_input_buffer()

    @property
    def version_text(self) -> str | None:
        return self._version_text

    @property
    def protocol(self) -> str:
        return self._protocol

    def reset_input_buffer(self) -> None:
        self.ser.reset_input_buffer()
        self._rx_frames.clear()

    def close(self) -> None:
        try:
            self._write_command("C")
        except Exception:
            pass
        try:
            self.ser.close()
        except Exception:
            pass

    def __enter__(self) -> "_CanableSlcan":
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def _write_command(self, command: str) -> None:
        payload = command.encode("ascii") + b"\r"
        if self.debug:
            _log_can_rpc.debug("serial >>> %s", payload.rstrip().decode("ascii", errors="replace"))
        self.ser.write(payload)
        self.ser.flush()

    def _read_line(self, *, deadline: float | None) -> str | None:
        buf = bytearray()
        while True:
            remaining = _remaining(deadline)
            if remaining is not None and remaining <= 0:
                return None
            chunk = self.ser.read(1)
            if not chunk:
                continue
            byte = chunk[0]
            if byte == 0x0A:
                continue
            if byte == 0x0D:
                if self.debug:
                    _log_can_rpc.debug("serial <<< %s", _readable_ascii(bytes(buf)))
                return _readable_ascii(bytes(buf))
            buf.append(byte)

    def _queue_or_ignore(self, line: str) -> None:
        frames = _parse_slcan_frames(line)
        if frames:
            if self.debug and len(frames) > 1:
                _log_can_rpc.debug(
                    "serial <<< recovered %d concatenated SLCAN frames",
                    len(frames),
                )
            self._rx_frames.extend(frames)
            return
        if self.debug:
            _log_can_rpc.debug("serial event <<< %s", line)

    def _read_event_line(self, *, deadline: float | None) -> str | None:
        while True:
            line = self._read_line(deadline=deadline)
            if line is None:
                return None
            frames = _parse_slcan_frames(line)
            if frames:
                if self.debug and len(frames) > 1:
                    _log_can_rpc.debug(
                        "serial <<< recovered %d concatenated SLCAN frames",
                        len(frames),
                    )
                self._rx_frames.extend(frames)
                continue
            return line

    def _wait_feedback(self, *, deadline: float) -> None:
        while True:
            line = self._read_event_line(deadline=deadline)
            if line is None:
                raise TimeoutError("timeout waiting for SLCAN feedback")
            if line.startswith("#"):
                code = line[1:]
                if code == "":
                    return
                detail = SLCAN_FEEDBACK.get(code, f"unknown adapter feedback {code!r}")
                if code == "7":
                    raise CanTxBufferFull(f"SLCAN command failed: {detail}")
                raise TransportError(f"SLCAN command failed: {detail}")

    def command(self, command: str, *, expect_feedback: bool = False, expect_text: bool = False,
                timeout: float = 1.0) -> str | None:
        deadline = _deadline_after(timeout)
        self._write_command(command)
        if expect_text:
            while True:
                line = self._read_event_line(deadline=deadline)
                if line is None:
                    raise TimeoutError(f"timeout waiting for response to {command!r}")
                if line.startswith("+"):
                    return line[1:]
                if line.startswith("#"):
                    code = line[1:]
                    if code:
                        detail = SLCAN_FEEDBACK.get(code, f"unknown adapter feedback {code!r}")
                        if code == "7":
                            raise CanTxBufferFull(f"SLCAN command failed: {detail}")
                        raise TransportError(f"SLCAN command failed: {detail}")
                    continue
                return line
        if expect_feedback:
            self._wait_feedback(deadline=deadline)
        return None

    def _command_no_feedback(self, command: str, *, settle: float = 0.02) -> None:
        self._write_command(command)
        if settle > 0:
            time.sleep(settle)

    def _probe_version(self, *, timeout: float = 1.0) -> tuple[str, str]:
        version = self.command("V", expect_text=True, timeout=timeout)
        if version is None:
            raise TimeoutError("timeout waiting for version response")
        if "\t" in version or version.startswith("Board:") or version.startswith("Slcan:"):
            return "elmue", version
        return "legacy", version

    def configure(self, bitrate: int, mode: str) -> None:
        if mode not in MODE_TO_OPEN_COMMAND or mode not in LEGACY_MODE_TO_PREOPEN_COMMAND:
            raise ValueError(f"unsupported SLCAN mode {mode!r}")

        # Close/reset without waiting: both Elmue 2.5 and legacy CANable
        # firmwares keep this command silent.
        self._command_no_feedback("C", settle=0.05)
        time.sleep(0.05)
        self.reset_input_buffer()

        protocol, version = self._probe_version(timeout=1.0)
        self._protocol = protocol
        self._version_text = version
        if protocol == "elmue":
            if bitrate not in ELMUE_BITRATE_CODES:
                choices = ", ".join(str(v) for v in sorted(ELMUE_BITRATE_CODES))
                raise ValueError(f"unsupported Elmue SLCAN bitrate {bitrate}; choices: {choices}")
            self.command("MF", expect_feedback=True, timeout=1.0)
            self.command(f"S{ELMUE_BITRATE_CODES[bitrate]}", expect_feedback=True, timeout=1.0)
            self.command(MODE_TO_OPEN_COMMAND[mode], expect_feedback=True, timeout=1.0)
            return

        if bitrate not in LEGACY_BITRATE_CODES:
            choices = ", ".join(str(v) for v in sorted(LEGACY_BITRATE_CODES))
            raise ValueError(f"unsupported legacy CANable bitrate {bitrate}; choices: {choices}")
        self._command_no_feedback(f"S{LEGACY_BITRATE_CODES[bitrate]}")
        self._command_no_feedback(LEGACY_MODE_TO_PREOPEN_COMMAND[mode])
        self._command_no_feedback("O", settle=0.05)

    def read_frame(self, deadline: float | None = None) -> CanFrame | None:
        if self._rx_frames:
            return self._rx_frames.popleft()
        while deadline is None or time.monotonic() < deadline:
            line = self._read_line(deadline=deadline)
            if line is None:
                return None
            frames = _parse_slcan_frames(line)
            if frames:
                if self.debug and len(frames) > 1:
                    _log_can_rpc.debug(
                        "serial <<< recovered %d concatenated SLCAN frames",
                        len(frames),
                    )
                self._rx_frames.extend(frames[1:])
                return frames[0]
            if self.debug:
                _log_can_rpc.debug("serial event <<< %s", line)
        return None

    def read_pending_frame(self) -> CanFrame | None:
        if self._rx_frames:
            return self._rx_frames.popleft()
        return None

    def send_frame(self, can_id: int, data: bytes, *, extended: bool = False, remote: bool = False) -> None:
        cmd = _format_slcan_frame(can_id, data, extended=extended, remote=remote)
        if self._protocol == "elmue":
            self.command(cmd, expect_feedback=True, timeout=1.0)
            return
        self._command_no_feedback(cmd, settle=0.0)

    def send_frames_batch(self, can_id: int, frames: list[bytes], *,
                          extended: bool = False) -> None:
        for offset in range(0, len(frames), FRAME_BATCH_SIZE):
            batch = frames[offset:offset + FRAME_BATCH_SIZE]
            payload = b"".join(
                _format_slcan_frame(can_id, frame, extended=extended, remote=False).encode("ascii") + b"\r"
                for frame in batch
            )
            self.ser.write(payload)
            self.ser.flush()
            if FRAME_BATCH_INTERVAL > 0 and offset + FRAME_BATCH_SIZE < len(frames):
                time.sleep(FRAME_BATCH_INTERVAL)


class CanCanableTransport:
    """JSON-RPC transport over a CANable-style SLCAN serial adapter."""

    DEFAULT_TIMEOUT = DEFAULT_TIMEOUT

    def __init__(self, port: str, *, bitrate: int = 1_000_000,
                 mode: str = "normal", serial_bauds: tuple[int, ...] = SERIAL_BAUD_CANDIDATES,
                 tx_id: int = DEFAULT_RPC_TX_ID, rx_id: int = DEFAULT_RPC_RX_ID,
                 frame_interval: float = 0.0, reset_buffers: bool = True,
                 dtr: bool | None = None, rts: bool | None = None,
                 debug: bool = False) -> None:
        self._cfg = _CanableConfig(
            port=port,
            bitrate=bitrate,
            mode=mode,
            serial_bauds=tuple(serial_bauds),
            tx_id=tx_id,
            rx_id=rx_id,
            frame_interval=frame_interval,
            reset_buffers=reset_buffers,
            dtr=dtr,
            rts=rts,
            debug=debug,
        )
        self._dev: _CanableSlcan | None = None
        self._rx_codec = CanDatagramCodec()
        self._rpc_id = 0
        self._notification_handler = None
        self._notification_stop = False

    @classmethod
    def from_args(cls, target: str, args: argparse.Namespace) -> "CanCanableTransport":
        if hasattr(args, "serial_baud"):
            serial_bauds = (int(args.serial_baud),)
        else:
            serial_bauds = SERIAL_BAUD_CANDIDATES
        return cls(
            port=target,
            bitrate=getattr(args, "bitrate", 1_000_000),
            mode=getattr(args, "mode", "normal"),
            serial_bauds=serial_bauds,
            tx_id=getattr(args, "tx_id", DEFAULT_RPC_TX_ID),
            rx_id=getattr(args, "rx_id", DEFAULT_RPC_RX_ID),
            frame_interval=getattr(args, "frame_interval", 0.0),
            reset_buffers=not getattr(args, "no_reset_buffers", False),
            dtr=getattr(args, "dtr", None),
            rts=getattr(args, "rts", None),
            debug=getattr(args, "debug", False),
        )

    @property
    def name(self) -> str:
        return f"can:slcan:{self._cfg.port}"

    @property
    def supports_encrypted(self) -> bool:
        return False

    @property
    def dev(self) -> _CanableSlcan:
        if self._dev is None:
            raise TransportError("transport not connected")
        return self._dev

    def connect(self) -> None:
        if self._dev is not None:
            return
        cfg = self._cfg
        errors: list[str] = []
        for serial_baud in cfg.serial_bauds:
            dev: _CanableSlcan | None = None
            try:
                if cfg.debug and len(cfg.serial_bauds) > 1:
                    _log_can_rpc.debug("probing %s at serial baud %d", cfg.port, serial_baud)
                dev = _CanableSlcan(
                    port=cfg.port,
                    serial_baud=serial_baud,
                    timeout=0.05,
                    open_delay=0.05,
                    dtr=cfg.dtr,
                    rts=cfg.rts,
                    reset_buffers=cfg.reset_buffers,
                    debug=cfg.debug,
                )
                dev.configure(cfg.bitrate, cfg.mode)

                time.sleep(0.1)
                dev.reset_input_buffer()
                self._dev = dev
                self._rx_codec = CanDatagramCodec()
                return
            except Exception as exc:
                errors.append(f"{serial_baud}: {exc}")
                if dev is not None:
                    try:
                        dev.close()
                    except Exception:
                        pass
        tried = ", ".join(str(v) for v in cfg.serial_bauds)
        detail = "; ".join(errors) if errors else "no usable serial baud found"
        raise TransportError(f"CANable open failed on {cfg.port} after trying {tried}: {detail}")

    def close(self) -> None:
        if self._dev is not None:
            try:
                self._dev.close()
            finally:
                self._dev = None

    def __enter__(self) -> "CanCanableTransport":
        self.connect()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def _next_id(self) -> int:
        self._rpc_id += 1
        return self._rpc_id

    def send_payload(self, payload: bytes) -> None:
        frames = CanDatagramCodec.encode(payload)
        if self._cfg.frame_interval <= 0:
            self.dev.send_frames_batch(self._cfg.tx_id, frames, extended=False)
            if self._cfg.debug:
                for frame in frames:
                    _log_can_rpc.debug("TX 0x%03X %s", self._cfg.tx_id, hex_bytes(frame))
            return
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


__all__ = [
    "CanCanableTransport",
    "SERIAL_BAUD_CANDIDATES",
    "SERIAL_BAUD_DEFAULT",
]

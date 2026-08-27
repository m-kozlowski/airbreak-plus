"""AirMini FIG/JSON-RPC transport over Bluetooth Classic RFCOMM.

The implementation uses Linux's native RFCOMM socket API and therefore does
not require PyBluez.  Bluetooth bonding (the link-level PIN exchange) is left
to the operating system; this module implements the separate FIG SRP pairing
and encrypted-session restore used by the application protocol.
"""

from __future__ import annotations

import json
import logging
import re
import socket
import struct
import threading
import time
from typing import Callable

from as11_rpc import AIRMINI_RPC_PROFILE, TransportError, rpc_version
from resmed_fig import (
    FIG_VCID_RPC,
    FIG_VCID_RPC_ENC,
    FIG_VCID_RX_ENC,
    FigCodec,
    SRPClient,
    aes_decrypt,
    aes_encrypt,
    derive_session_key,
    session_integrity_response,
)
from resmed_credentials import (
    credential_family,
    load_credentials,
    resolve_address,
    save_credentials,
)


SPP_UUID = "00001101-0000-1000-8000-00805f9b34fb"
DEFAULT_RFCOMM_CHANNEL = 5
DEFAULT_KEEPALIVE_INTERVAL = 4.0

log = logging.getLogger("airmini.spp")


def resolve_addr(target: str | None = None) -> str:
    return resolve_address(
        target,
        env_var="AIRMINI_ADDR",
        allow_uuid=False,
        expected_family="mini",
    )


class AirMiniSppTransport:
    """Synchronous AirMini JSON-RPC transport over an RFCOMM stream."""

    DEFAULT_TIMEOUT = 10.0

    def __init__(self, address: str, *, channel: int = DEFAULT_RFCOMM_CHANNEL,
                 connect_timeout: float = 20.0, debug: bool = False,
                 restore_session: bool = True,
                 socket_factory: Callable[[], socket.socket] | None = None) -> None:
        self._address = resolve_addr(address)
        if not 1 <= channel <= 30:
            raise ValueError("RFCOMM channel must be in range 1..30")
        self._channel = channel
        self._connect_timeout = connect_timeout
        self._debug = debug
        self._restore_session = restore_session
        self._socket_factory = socket_factory

        self._socket: socket.socket | None = None
        self._codec = FigCodec()
        self._session_key: bytes | None = None
        self._authenticated = False
        self._rpc_id = 0
        self._id_lock = threading.Lock()
        self._send_lock = threading.Lock()
        self._response_condition = threading.Condition()
        self._responses: dict[int, dict] = {}
        self._reader_error: BaseException | None = None
        self._reader_thread: threading.Thread | None = None
        self._stop_reader = threading.Event()
        self._notification_handler = None
        self._notification_stop: threading.Event | None = None
        self._stop_keepalive = threading.Event()
        self._keepalive_thread: threading.Thread | None = None

    @classmethod
    def from_args(cls, target: str, args) -> "AirMiniSppTransport":
        return cls(
            target,
            debug=getattr(args, "debug", False),
        )

    @property
    def name(self) -> str:
        return f"mini-spp:{self._address}"

    @property
    def supports_encrypted(self) -> bool:
        return True

    @property
    def authenticated(self) -> bool:
        return self._authenticated

    def _new_socket(self) -> socket.socket:
        if self._socket_factory is not None:
            return self._socket_factory()
        required = ("AF_BLUETOOTH", "BTPROTO_RFCOMM")
        if any(not hasattr(socket, name) for name in required):
            raise TransportError(
                "native RFCOMM sockets are unavailable on this Python/platform"
            )
        return socket.socket(
            socket.AF_BLUETOOTH, socket.SOCK_STREAM, socket.BTPROTO_RFCOMM
        )

    def connect(self) -> None:
        if self._socket is not None:
            return
        self._codec = FigCodec()
        self._responses.clear()
        sock = self._new_socket()
        try:
            sock.settimeout(self._connect_timeout)
            sock.connect((self._address, self._channel))
            sock.settimeout(0.5)
            self._socket = sock
            self._stop_reader.clear()
            self._reader_error = None
            self._reader_thread = threading.Thread(
                target=self._reader_loop,
                name="airmini-rfcomm-reader",
                daemon=True,
            )
            self._reader_thread.start()
            log.info("connected to %s on RFCOMM channel %d",
                     self._address, self._channel)

            credentials = (load_credentials(self._address)
                           if self._restore_session else {})
            if credentials and credential_family(credentials) != "mini":
                credentials = {}
            client_id = credentials.get("clientId")
            master_pair_key = credentials.get("masterPairKey")
            if client_id and master_pair_key:
                try:
                    self.reconnect(client_id, master_pair_key)
                except Exception as exc:
                    self._session_key = None
                    self._authenticated = False
                    log.warning("AirMini session restore failed: %s", exc)
            else:
                log.info("AirMini has no stored FIG pairing; run "
                         "`devices pair mini-spp:%s`", self._address)
        except OSError as exc:
            if self._socket is sock:
                self.close()
            else:
                sock.close()
            raise TransportError(
                f"cannot connect to AirMini {self._address} on RFCOMM "
                f"channel {self._channel}: {exc}"
            ) from exc
        except Exception:
            if self._socket is sock:
                self.close()
            else:
                sock.close()
            raise

    def close(self) -> None:
        self._stop_keepalive.set()
        self._stop_reader.set()
        sock, self._socket = self._socket, None
        with self._response_condition:
            self._response_condition.notify_all()
        if sock is not None:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                sock.close()
            except OSError:
                pass
        thread, self._reader_thread = self._reader_thread, None
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=2.0)
        keepalive, self._keepalive_thread = self._keepalive_thread, None
        if keepalive is not None and keepalive is not threading.current_thread():
            keepalive.join(timeout=2.0)
        self._session_key = None
        self._authenticated = False
        self._codec = FigCodec()
        self._responses.clear()

    def __enter__(self) -> "AirMiniSppTransport":
        self.connect()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def _reader_loop(self) -> None:
        try:
            while not self._stop_reader.is_set():
                sock = self._socket
                if sock is None:
                    return
                try:
                    data = sock.recv(4096)
                except socket.timeout:
                    continue
                if not data:
                    raise TransportError("AirMini closed the RFCOMM connection")
                if self._debug:
                    log.debug("RX RFCOMM (%d bytes): %s", len(data), data.hex())
                self._codec.feed(data)
                for vcid, payload in self._codec.decode():
                    self._handle_packet(vcid, payload)
        except BaseException as exc:
            if not self._stop_reader.is_set():
                self._reader_error = exc
                log.warning("AirMini RFCOMM reader stopped: %s", exc)
        finally:
            with self._response_condition:
                self._response_condition.notify_all()

    def _decode_json_payload(self, vcid: int, payload: bytes) -> dict:
        if vcid in (FIG_VCID_RX_ENC, 0x0394, 0x0380):
            if self._session_key is None:
                raise TransportError(
                    f"received encrypted FIG VCID 0x{vcid:04x} without a session key"
                )
            payload = aes_decrypt(payload, self._session_key)

        try:
            return json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as first_error:
            if len(payload) >= 2:
                size = struct.unpack_from("<H", payload, 0)[0]
                candidate = payload[2:2 + size]
                try:
                    return json.loads(candidate.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    pass
            raise TransportError(
                f"non-JSON FIG payload on VCID 0x{vcid:04x}"
            ) from first_error

    def _handle_packet(self, vcid: int, payload: bytes) -> None:
        try:
            message = self._decode_json_payload(vcid, payload)
        except Exception as exc:
            log.warning("discarding AirMini packet: %s", exc)
            return

        if "method" in message and "id" not in message:
            handler = self._notification_handler
            if handler is not None:
                try:
                    if handler(message) and self._notification_stop is not None:
                        self._notification_stop.set()
                except Exception as exc:
                    log.warning("AirMini notification handler raised: %s", exc)
            return

        response_id = message.get("id")
        if not isinstance(response_id, int):
            log.debug("ignoring AirMini JSON without integer id: %s", message)
            return
        with self._response_condition:
            self._responses[response_id] = message
            self._response_condition.notify_all()

    def _next_rpc_id(self) -> int:
        with self._id_lock:
            self._rpc_id += 1
            return self._rpc_id

    def _send_rpc(self, method: str, params: object | None = None, *,
                  timeout: float = DEFAULT_TIMEOUT, encrypted: bool = False,
                  raise_rpc_error: bool = True,
                  post_send_delay: float = 0.0) -> dict:
        sock = self._socket
        if sock is None:
            raise TransportError("AirMini SPP transport is not connected")
        if encrypted and self._session_key is None:
            raise TransportError("AirMini encrypted session is not authenticated")

        rpc_id = self._next_rpc_id()
        request = {
            "jsonrpc": rpc_version(method, AIRMINI_RPC_PROFILE),
            "method": method,
            "id": rpc_id,
        }
        if params is not None:
            request["params"] = params
        json_payload = json.dumps(request, separators=(",", ":")).encode("utf-8")
        if encrypted:
            payload = aes_encrypt(json_payload, self._session_key)
            vcid = FIG_VCID_RPC_ENC
        else:
            payload = json_payload
            vcid = FIG_VCID_RPC
        frame = FigCodec.encode(vcid, payload)

        if self._debug:
            log.debug("TX %s id=%d vcid=0x%04x frame=%s",
                      method, rpc_id, vcid, frame.hex())
        else:
            log.info("RPC >>> %s id=%d", method, rpc_id)
        with self._send_lock:
            try:
                sock.sendall(frame)
            except OSError as exc:
                raise TransportError(f"AirMini RFCOMM send failed: {exc}") from exc
        if post_send_delay:
            time.sleep(post_send_delay)

        deadline = time.monotonic() + timeout
        with self._response_condition:
            while rpc_id not in self._responses:
                if self._socket is None or self._stop_reader.is_set():
                    raise TransportError("AirMini SPP transport was closed")
                if self._reader_error is not None:
                    raise TransportError(
                        f"AirMini RFCOMM receive failed: {self._reader_error}"
                    ) from self._reader_error
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError(f"no response to {method} within {timeout}s")
                self._response_condition.wait(remaining)
            response = self._responses.pop(rpc_id)

        if raise_rpc_error and "error" in response:
            error = response["error"]
            raise RuntimeError(
                f"RPC error {error.get('code', '?')}: {error.get('message', '?')}"
            )
        log.info("RPC <<< %s id=%d", method, rpc_id)
        return response

    def rpc(self, method: str, params: object | None = None, *,
            timeout: float = DEFAULT_TIMEOUT, encrypted: bool | None = None,
            post_send_delay: float = 0.0, **_kwargs) -> dict:
        if encrypted is None:
            encrypted = self._authenticated
        return self._send_rpc(
            method,
            params,
            timeout=timeout,
            encrypted=encrypted,
            post_send_delay=post_send_delay,
        )

    def pair(self, passkey: str) -> dict:
        """Perform the low-level FIG SRP exchange and persist reusable keys."""
        if not re.fullmatch(r"\d{4}", passkey):
            raise ValueError("AirMini FIG passkey must contain exactly four digits")
        srp = SRPClient(passkey)
        response = self._send_rpc(
            "StartKeyExchange",
            {"clientPk": srp.public_key_hex},
            timeout=10.0,
            encrypted=False,
            raise_rpc_error=False,
        )
        if "error" in response:
            raise RuntimeError(f"StartKeyExchange failed: {response['error']}")
        result = response.get("result", {})
        server_key = result.get("serverPk")
        salt = result.get("salt")
        if not server_key or not salt:
            raise TransportError("StartKeyExchange response has no serverPk/salt")
        srp.process(server_key, salt)

        confirmation = self._send_rpc(
            "ConfirmKeyExchange",
            {"clientConfirmation": srp.client_proof_hex},
            timeout=10.0,
            encrypted=False,
            raise_rpc_error=False,
        )
        if "error" in confirmation:
            raise RuntimeError(f"ConfirmKeyExchange failed: {confirmation['error']}")
        result = confirmation.get("result", {})
        client_id = result.get("clientId")
        nonce = result.get("nonce")
        server_proof = result.get("serverConfirmation")
        if not client_id or not nonce or not server_proof:
            raise TransportError(
                "ConfirmKeyExchange response lacks clientId/nonce/serverConfirmation"
            )
        srp.verify_server(server_proof)
        self._session_key = bytes.fromhex(srp.derive_session_key(nonce))
        self._authenticated = True

        credentials = {
            "clientId": client_id,
            "masterPairKey": srp.session_key_hex,
            "family": "mini",
        }
        save_credentials(self._address, credentials)
        self._start_keepalive()
        return credentials

    def reconnect(self, client_id: str, master_pair_key: str) -> dict:
        """Restore an encrypted FIG session from saved AirMini credentials."""
        try:
            pair_key = bytes.fromhex(master_pair_key)
        except ValueError as exc:
            raise TransportError("stored AirMini masterPairKey is not hex") from exc
        if len(pair_key) != 32:
            raise TransportError("stored AirMini masterPairKey must be 32 bytes")

        response = self._send_rpc(
            "RequestSession",
            {"clientId": client_id},
            timeout=10.0,
            encrypted=False,
            raise_rpc_error=False,
        )
        if "error" in response:
            raise RuntimeError(f"RequestSession failed: {response['error']}")
        result = response.get("result", {})
        challenge = result.get("challenge")
        nonce = result.get("nonce")
        if not challenge or not nonce:
            raise TransportError("RequestSession response has no challenge/nonce")
        try:
            challenge_bytes = bytes.fromhex(challenge)
            nonce_bytes = bytes.fromhex(nonce)
        except ValueError as exc:
            raise TransportError("RequestSession returned invalid hex") from exc

        integrity = session_integrity_response(pair_key, challenge_bytes)
        confirmation = self._send_rpc(
            "CheckSessionIntegrity",
            {"response": integrity.hex().upper()},
            timeout=10.0,
            encrypted=False,
            raise_rpc_error=False,
        )
        if "error" in confirmation:
            raise RuntimeError(f"CheckSessionIntegrity failed: {confirmation['error']}")
        confirmation_result = confirmation.get("result")
        if isinstance(confirmation_result, dict):
            accepted = confirmation_result.get("confirmation", True)
            if accepted is False:
                raise TransportError("AirMini rejected session integrity proof")

        self._session_key = derive_session_key(pair_key, nonce_bytes)
        self._authenticated = True
        self._start_keepalive()
        return {"clientId": client_id, "nonce": nonce}

    def _start_keepalive(self) -> None:
        if self._keepalive_thread is not None and self._keepalive_thread.is_alive():
            return
        self._stop_keepalive.clear()

        def run() -> None:
            while not self._stop_keepalive.wait(DEFAULT_KEEPALIVE_INTERVAL):
                try:
                    self._send_rpc(
                        "GetDateTime", timeout=5.0, encrypted=True
                    )
                except Exception as exc:
                    if not self._stop_keepalive.is_set():
                        log.warning("AirMini keepalive failed: %s", exc)
                    return

        self._keepalive_thread = threading.Thread(
            target=run, name="airmini-keepalive", daemon=True
        )
        self._keepalive_thread.start()

    def set_notification_handler(self, handler) -> None:
        self._notification_handler = handler
        if handler is None:
            self._notification_stop = None
        else:
            self._notification_stop = threading.Event()

    def listen_for_notifications(self, *, duration: float | None = None) -> None:
        deadline = time.monotonic() + duration if duration is not None else None
        try:
            while not self._stop_reader.is_set():
                if self._reader_error is not None:
                    raise TransportError(
                        f"AirMini RFCOMM receive failed: {self._reader_error}"
                    ) from self._reader_error
                if (self._notification_stop is not None
                        and self._notification_stop.is_set()):
                    return
                if deadline is not None and time.monotonic() >= deadline:
                    return
                time.sleep(0.05)
        except KeyboardInterrupt:
            return


__all__ = [
    "SPP_UUID", "DEFAULT_RFCOMM_CHANNEL", "DEFAULT_KEEPALIVE_INTERVAL",
    "resolve_addr", "AirMiniSppTransport",
]

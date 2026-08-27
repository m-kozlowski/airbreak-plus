"""AS11 BLE transport core.

Classes and helpers used by as11_config.py and as11_flash.py:
    SRPClient        SRP-6a key exchange
    FigCodec         FIG packet framing
    As11Connection   async BLE link + RPC plumbing
    BleTransport     sync wrapper implementing the as11_rpc.Transport
                     protocol; runs an asyncio event loop in a background
                     thread so callers stay synchronous like CAN does

Uses the shared Bluetooth credential store at ~/.as11_ble.json.

"""

from __future__ import annotations

import asyncio
import json
import logging
import struct
import sys
import threading
import time

try:
    from bleak import BleakClient, BleakScanner
except ImportError:
    sys.exit("bleak not installed. Run: pip install bleak")

from cryptography.hazmat.primitives import hashes, hmac

# lib/ is on sys.path; import the shared Transport surface.
from as11_rpc import (
    AIRMINI_RPC_PROFILE,
    AS11_RPC_PROFILE,
    TransportError,
    rpc_version,
)
from resmed_fig import (
    FIG_HEADER_LEN,
    FIG_SYNC,
    FIG_SYNC_BYTES,
    FIG_VCID_RPC,
    FIG_VCID_RPC_ENC,
    FIG_VCID_RX_ENC,
    FigCodec,
    H,
    SRPClient,
    aes_decrypt,
    aes_encrypt,
    derive_session_key,
    session_integrity_response,
)
from resmed_credentials import (
    CRED_FILE,
    MAC_RE,
    UUID_RE,
    credential_family,
    load_all_credentials,
    load_credentials,
    resolve_address,
    save_all_credentials,
    save_credentials,
)


# GATT UUIDs + FIG constants.

SERVICE_UUID = "0000fd56-0000-1000-8000-00805f9b34fb"
TX_CHAR_UUID = "a6220002-35f1-4b20-afae-cb089d2044aa"   # app -> device
RX_CHAR_UUID = "a6220003-35f1-4b20-afae-cb089d2044aa"   # device -> app

DEVICE_NAME_PREFIX = "ResMed"

log = logging.getLogger("as11.ble")


def decode_ncp_packet(payload: bytes):
    """Best-effort decoder for the binary NCP command envelope."""
    if len(payload) < 4:
        return None
    ncp_len = struct.unpack_from('<H', payload, 0)[0]
    if ncp_len + 2 > len(payload) or ncp_len < 2:
        return None

    code = payload[2]
    seq = payload[3]
    body = payload[4:4 + ncp_len - 2]
    out = {
        "length": ncp_len,
        "code": f"0x{code:02x}",
        "seq": seq,
        "bodyHex": body.hex(),
    }
    if body:
        try:
            out["bodyText"] = body.rstrip(b"\x00").decode("utf-8")
        except UnicodeDecodeError:
            pass
    if code == 0xfd and len(body) >= 4:
        err_code, msg_len = struct.unpack_from('<HH', body, 0)
        msg = body[4:4 + msg_len].rstrip(b"\x00")
        out["errorCode"] = f"0x{err_code:04x}"
        try:
            out["errorText"] = msg.decode("utf-8")
        except UnicodeDecodeError:
            pass
    return out



class As11Connection:
    def __init__(self, debug=False, rpc_profile=AS11_RPC_PROFILE):
        self._client = None
        self._codec = FigCodec()
        self._rpc_id = 0
        self._response_event = asyncio.Event()
        self._response_data = None
        self._mtu = 244
        self._write_without_response = False
        self._session_key = None
        self._notification_cb = None
        self._raw_packet_cb = None
        self._plain_vcids = set()
        self._rpc_profile = rpc_profile
        self.debug = debug

    def set_session_key(self, key_hex):
        """AES-256 session key from SHA256 output."""
        self._session_key = bytes.fromhex(key_hex[:64])
        log.info("session key set (%d bytes): %s...",
                 len(self._session_key), key_hex[:16])

    def _aes_encrypt(self, plaintext, length_prefix=True):
        """AES-CBC(key, random IV). Wire: [IV][cipher([u16 len][payload][zero pad])]."""
        return aes_encrypt(plaintext, self._session_key,
                           length_prefix=length_prefix)

    def _aes_decrypt(self, data):
        return aes_decrypt(data, self._session_key)

    @staticmethod
    async def scan(timeout=10.0, include_all=False):
        """Return address, name, RSSI, and advertised service UUIDs."""
        scan_args = {"timeout": timeout, "return_adv": True}
        if not include_all:
            scan_args["service_uuids"] = [SERVICE_UUID]
        devices = await BleakScanner.discover(**scan_args)
        results = []
        for addr, (dev, adv) in devices.items():
            name = dev.name or adv.local_name or ""
            if include_all or name.startswith(DEVICE_NAME_PREFIX):
                results.append((
                    dev.address,
                    name,
                    adv.rssi,
                    tuple(adv.service_uuids or ()),
                ))
        return results

    async def connect(self, address: str):
        self._client = BleakClient(address, timeout=20.0)
        await self._client.connect()
        log.info("connected to %s", address)

        # A JSON-RPC response acknowledges the complete FIG packet, so write
        # commands can carry every fragment when the characteristic allows it.
        try:
            svcs = self._client.services
            for svc in svcs:
                for char in svc.characteristics:
                    if char.uuid == TX_CHAR_UUID:
                        self._mtu = char.max_write_without_response_size
                        properties = set(char.properties)
                        self._write_without_response = (
                            "write-without-response" in properties
                        )
                        break
        except Exception:
            pass
        if self._mtu < 244:
            self._mtu = 244
        if self._write_without_response:
            mode = "write commands"
        else:
            mode = "acknowledged writes"
        log.info("write chunk size: %d (%s)", self._mtu, mode)

        STEEHL_CHARS = [
            "3d5085ac-d8a2-4a56-8d2e-1dc7508e67bc",
            "1681c44f-2798-4bfa-b11a-65e9f55c2082",
            "e5e33ba4-c823-4a86-9b15-1bf2acb27a1c",
        ]
        for uuid in STEEHL_CHARS:
            try:
                val = await self._client.read_gatt_char(uuid)
                log.info("Steehl %s: %s", uuid[:8], val.hex())
            except Exception as e:
                log.debug("Steehl %s: %s", uuid[:8], e)

        SVC_CHANGED_UUID = "00002a05-0000-1000-8000-00805f9b34fb"
        try:
            await self._client.start_notify(SVC_CHANGED_UUID, lambda s, d:
                log.debug("Service Changed indication: %s", d.hex()))
            log.info("Service Changed indication enabled")
        except Exception as e:
            log.debug("Service Changed: %s", e)

        await self._client.start_notify(RX_CHAR_UUID, self._on_notify)
        log.info("RX notifications enabled")

        if self.debug:
            for svc in self._client.services:
                log.debug("Service: %s", svc.uuid)
                for char in svc.characteristics:
                    props = ",".join(char.properties)
                    log.debug("  Char: %s [%s]", char.uuid, props)
                    for desc in char.descriptors:
                        log.debug("    Desc: %s", desc.uuid)

    async def disconnect(self):
        if self._client and self._client.is_connected:
            await self._client.disconnect()
            log.info("disconnected")

    def _on_notify(self, sender, data: bytearray):
        if self.debug:
            log.debug("RX notify (%d bytes): %s", len(data), data.hex())
        self._codec.feed(bytes(data))

        for vcid, raw_payload in self._codec.decode():
            log.debug("FIG packet: vcid=%d len=%d", vcid, len(raw_payload))
            if self.debug:
                log.debug("  raw payload hex: %s", raw_payload.hex())

            # 0x0396 = Level 2 patient, 0x0394/0x0380 = possible Level 3 service
            if vcid in (FIG_VCID_RX_ENC, 0x0394, 0x0380) and self._session_key and vcid not in self._plain_vcids:
                try:
                    raw_payload = self._aes_decrypt(raw_payload)
                    if self.debug:
                        log.debug("  decrypted: %s", raw_payload[:100])
                except Exception as e:
                    log.warning("decrypt failed on vcid %d: %s", vcid, e)
                    continue

            if self._raw_packet_cb:
                self._raw_packet_cb(vcid, raw_payload)
                self._response_data = {"vcid": vcid, "payloadHex": raw_payload.hex()}
                self._response_event.set()
                continue

            payload = raw_payload
            try:
                text = payload.decode('utf-8')
                msg = json.loads(text)
            except (UnicodeDecodeError, json.JSONDecodeError):
                if len(raw_payload) >= 2:
                    dg_len = struct.unpack_from('<H', raw_payload, 0)[0]
                    payload = raw_payload[2:2 + dg_len]
                try:
                    text = payload.decode('utf-8')
                    msg = json.loads(text)
                except (UnicodeDecodeError, json.JSONDecodeError) as e:
                    log.warning("non-JSON payload on vcid %d: %r", vcid, raw_payload)
                    continue

            if "method" in msg and "id" not in msg:
                log.info("RX notification: %s(%s)",
                         msg["method"], json.dumps(msg.get("params", {}))[:100])
                if self._notification_cb:
                    self._notification_cb(msg)
                continue

            if self.debug:
                log.debug("  JSON response: %s", json.dumps(msg)[:300])
            self._response_data = msg
            self._response_event.set()

    async def _send_raw(self, data: bytes):
        chunk_size = max(self._mtu, 20)
        for offset in range(0, len(data), chunk_size):
            chunk = data[offset:offset + chunk_size]
            response = not self._write_without_response
            if self.debug:
                log.debug("TX chunk (%d/%d bytes, response=%s): %s",
                          len(chunk), len(data), response, chunk.hex())
            await self._client.write_gatt_char(
                TX_CHAR_UUID, chunk, response=response
            )

    async def send_rpc(self, method: str, params=None, timeout: float = 60.0,
                       encrypted: bool = False, vcid_override: int = None,
                       length_prefix: bool = True, hmac_key: bytes = None,
                       post_send_delay: float = 0.1) -> dict:
        self._rpc_id += 1
        # Preserve the AS11 BLE transport's historic 2.0 fallback. AirMini
        # uses its own profile default for unknown extension methods.
        fallback = "2.0" if self._rpc_profile == AS11_RPC_PROFILE else None
        version = rpc_version(method, self._rpc_profile, default=fallback)
        msg = {"id": self._rpc_id, "jsonrpc": version, "method": method}
        if params:
            msg["params"] = params

        json_bytes = json.dumps(msg, separators=(',', ':')).encode('utf-8')

        if encrypted and self._session_key:
            payload = self._aes_encrypt(json_bytes, length_prefix=length_prefix)
            if hmac_key:
                h = hmac.HMAC(hmac_key, hashes.SHA256())
                h.update(payload)
                payload = payload + h.finalize()
            vcid = vcid_override or FIG_VCID_RPC_ENC
        else:
            payload = json_bytes
            vcid = vcid_override or FIG_VCID_RPC

        packet = FigCodec.encode(vcid, payload)

        log.info("RPC >>> %s(%s)", method, json.dumps(params or {}))
        if self.debug:
            log.debug("TX packet (%d bytes): %s", len(packet), packet.hex())

        self._response_event.clear()
        self._response_data = None

        await self._send_raw(packet)

        if post_send_delay > 0:
            await asyncio.sleep(post_send_delay)

        try:
            await asyncio.wait_for(self._response_event.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            raise TimeoutError(f"no response to {method} within {timeout}s")

        resp = self._response_data
        if "error" in resp:
            err = resp["error"]
            raise RuntimeError(f"RPC error {err.get('code', '?')}: {err.get('message', '?')}")

        log.info("RPC <<< %s", json.dumps(resp.get("result", resp))[:200])
        return resp

    async def reconnect(self, client_id: str, master_pair_key: str) -> dict:
        """Re-establish encrypted session from stored credentials.

        RequestSession(clientId) -> {challenge, nonce}
        response = HMAC-SHA256(K, challenge)
        CheckSessionIntegrity(response)
        session_key = SHA256(K || nonce)
        """
        log.info("reconnect: RequestSession clientId=%s...", client_id[:8])
        resp = await self.send_rpc_raw(
            "RequestSession", {"clientId": client_id}, timeout=10.0
        )

        if not resp or "error" in resp:
            err = (resp or {}).get("error", {"message": "no response"})
            raise RuntimeError(f"RequestSession failed: {err}")

        result = resp.get("result", {})
        challenge_hex = result.get("challenge", "")
        nonce_hex = result.get("nonce", "")
        if not challenge_hex or not nonce_hex:
            raise RuntimeError("RequestSession: missing challenge/nonce")

        log.info("reconnect: challenge=%s... nonce=%s...",
                 challenge_hex[:16], nonce_hex[:16])

        K_bytes = bytes.fromhex(master_pair_key)
        challenge_bytes = bytes.fromhex(challenge_hex)
        response_hex = session_integrity_response(
            K_bytes, challenge_bytes
        ).hex().upper()
        log.info("reconnect: response=%s...", response_hex[:16])

        resp2 = await self.send_rpc_raw(
            "CheckSessionIntegrity", {"response": response_hex}, timeout=10.0
        )
        if not resp2 or "error" in resp2:
            err = (resp2 or {}).get("error", {"message": "no response"})
            raise RuntimeError(f"CheckSessionIntegrity failed: {err}")

        log.info("reconnect: session verified")

        nonce_bytes = bytes.fromhex(nonce_hex)
        aes_key = derive_session_key(K_bytes, nonce_bytes)
        aes_key_hex = aes_key.hex().upper()
        self.set_session_key(aes_key_hex)
        log.info("reconnect: AES key=%s...", aes_key_hex[:16])

        return {"clientId": client_id,
                "sessionKey": aes_key_hex[:32],
                "nonce": nonce_hex}

    async def send_rpc_raw(self, method: str, params: dict = None,
                           timeout: float = 10.0) -> dict:
        """send_rpc without error-raising; returns raw response dict or None."""
        self._rpc_id += 1
        msg = {"id": self._rpc_id, "jsonrpc": "2.0", "method": method}
        if params:
            msg["params"] = params

        payload = json.dumps(msg, separators=(',', ':')).encode('utf-8')
        packet = FigCodec.encode(FIG_VCID_RPC, payload)

        log.info("RPC >>> %s(%s)", method, json.dumps(params or {}))
        if self.debug:
            log.debug("TX packet (%d bytes): %s", len(packet), packet.hex())

        self._response_event.clear()
        self._response_data = None
        await self._send_raw(packet)

        try:
            await asyncio.wait_for(self._response_event.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            return None

        return self._response_data

    async def pair(self, passkey: str = None) -> dict:
        """SRP key exchange using the 4-digit passkey shown on the device screen."""
        log.info("SRP: generating keypair")
        srp = SRPClient(passkey or "")
        log.info("SRP: A = %s...", srp.public_key_hex[:32])

        resp = await self.send_rpc("StartKeyExchange",
                                   {"clientPk": srp.public_key_hex})
        if resp is None:
            raise RuntimeError("no response to StartKeyExchange")
        if "error" in resp:
            raise RuntimeError("StartKeyExchange error: %s" % resp["error"])

        result = resp.get("result", {})
        server_pk = result.get("serverPk", "")
        salt = result.get("salt", "")
        log.info("SRP: B = %s...", server_pk[:32])
        log.info("SRP: salt = %s", salt)

        if not passkey:
            passkey = input("Enter passkey shown on device screen: ").strip()
            if not passkey:
                raise RuntimeError("no passkey entered")
            srp.passkey = passkey

        srp.process(server_pk, salt)
        log.info("SRP: K = %s...", srp.session_key_hex[:32])
        log.info("SRP: M1 = %s...", srp.client_proof_hex[:32])

        resp2 = await self.send_rpc("ConfirmKeyExchange",
                                    {"clientConfirmation": srp.client_proof_hex})
        if resp2 is None:
            raise RuntimeError("no response to ConfirmKeyExchange")
        if "error" in resp2:
            raise RuntimeError("ConfirmKeyExchange error: %s" % resp2["error"])

        result2 = resp2.get("result", {})
        log.info("SRP: paired! result: %s", json.dumps(result2)[:200])

        server_confirmation = result2.get("serverConfirmation", "")
        if server_confirmation:
            srp.verify_server(server_confirmation)

        nonce = result2.get("nonce", "")
        aes_key_hex = srp.derive_session_key(nonce)
        self.set_session_key(aes_key_hex)
        log.info("AES key: %s...", aes_key_hex[:32])

        return {
            "clientId": result2.get("clientId", ""),
            "masterPairKey": srp.session_key_hex,
            "sessionKey": aes_key_hex[:32],
            "serverPk": server_pk,
            "nonce": result2.get("nonce", ""),
            "serverConfirmation": server_confirmation,
        }


def resolve_addr(arg: str = None) -> str:
    """MAC/UUID -> as-is (MAC uppercased). Alias -> looked up from credentials.
    None falls back to $AS11_ADDR."""
    return resolve_address(
        arg,
        env_var="AS11_ADDR",
        allow_uuid=True,
        expected_family="as11",
    )


class BleTransport:
    """Sync JSON-RPC transport over BLE.

    Internally runs an asyncio event loop in a background thread so that
    every public method is blocking and the interface matches
    CanWaveshareTransport. The loop is created on connect() and stopped
    in close(); one BleTransport == one connection.

    Unlike CAN, BLE has an encrypted admin VCID; `supports_encrypted`
    reports True, and rpc(..., encrypted=True) goes out on 0x0397 with
    the SRP-derived session key. The transport does not gate methods;
    the caller is responsible for not pointing the gun at its own foot.
    """

    DEFAULT_TIMEOUT = 10.0

    def __init__(self, address: str, *, debug: bool = False,
                 scan_timeout: float = 20.0,
                 rpc_profile: str = AS11_RPC_PROFILE,
                 family: str = "as11", name_prefix: str = "ble",
                 address_env: str = "AS11_ADDR") -> None:
        self._address = resolve_address(
            address,
            env_var=address_env,
            allow_uuid=True,
            expected_family=family,
        )
        self._debug = debug
        self._scan_timeout = scan_timeout
        self._rpc_profile = rpc_profile
        self._family = family
        self._name_prefix = name_prefix
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._conn: As11Connection | None = None
        self._authenticated = False
        self._notification_stop: threading.Event | None = None


    @classmethod
    def from_args(cls, target: str, args) -> "BleTransport":
        """Construct from a `ble:<addr>` target + parsed CLI args."""
        return cls(address=target, debug=getattr(args, "debug", False))


    @property
    def name(self) -> str:
        return f"{self._name_prefix}:{self._address}"

    @property
    def supports_encrypted(self) -> bool:
        return True

    @property
    def conn(self) -> As11Connection:
        if self._conn is None:
            raise TransportError("transport not connected")
        return self._conn

    def _submit(self, coro, *, timeout: float | None = None):
        """Schedule coro onto the background loop and wait for the result."""
        if self._loop is None:
            raise TransportError("transport not connected")
        fut = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return fut.result(timeout=timeout)

    def _start_loop(self) -> None:
        ready = threading.Event()

        def runner():
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
            ready.set()
            try:
                self._loop.run_forever()
            finally:
                # Drain any pending tasks cleanly.
                pending = asyncio.all_tasks(self._loop)
                for t in pending:
                    t.cancel()
                self._loop.run_until_complete(
                    asyncio.gather(*pending, return_exceptions=True)
                )
                self._loop.close()

        self._thread = threading.Thread(target=runner, name="ble-loop",
                                        daemon=True)
        self._thread.start()
        ready.wait()

    def _stop_loop(self) -> None:
        if self._loop is None:
            return
        self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread is not None:
            self._thread.join(timeout=5.0)
        self._loop = None
        self._thread = None

    def connect(self) -> None:
        """Connect BLE, then reconnect with stored credentials if present
        so the session is immediately usable for encrypted RPCs."""
        if self._conn is not None:
            return
        self._start_loop()
        try:
            self._conn = As11Connection(
                debug=self._debug, rpc_profile=self._rpc_profile
            )
            self._submit(self._conn.connect(self._address),
                         timeout=self._scan_timeout + 5)
            creds = load_credentials(self._address)
            if creds and credential_family(creds) != self._family:
                creds = {}
            if creds.get("clientId") and creds.get("masterPairKey"):
                try:
                    new_creds = self._submit(
                        self._conn.reconnect(
                            creds["clientId"], creds["masterPairKey"]
                        ),
                        timeout=15.0,
                    )
                    creds.update(new_creds)
                    save_credentials(self._address, creds)
                    self._authenticated = True
                except Exception as exc:
                    log.warning("reconnect failed: %s", exc)
            else:
                log.info("no stored credentials for %s; run `devices pair` first "
                         "for encrypted RPCs", self._address)
        except Exception:
            self._stop_loop()
            self._conn = None
            raise

    def close(self) -> None:
        if self._conn is None:
            self._stop_loop()
            return
        try:
            self._submit(self._conn.disconnect(), timeout=10.0)
        except Exception as exc:
            log.warning("disconnect error: %s", exc)
        finally:
            self._conn = None
            self._stop_loop()

    def __enter__(self) -> "BleTransport":
        self.connect()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()


    def rpc(self, method: str, params: object | None = None,
            *, timeout: float = DEFAULT_TIMEOUT,
            encrypted: bool | None = None, **kw) -> dict:

        if encrypted is None:
            encrypted = self._authenticated
        return self._submit(
            self.conn.send_rpc(method, params, timeout=timeout,
                               encrypted=encrypted, **kw),
            timeout=timeout + 5,
        )


    def set_notification_handler(self, handler) -> None:
        """Install a persistent notification handler that fires on every
        device notification, including during other RPC calls. The
        As11Connection _on_notify path calls _notification_cb when it
        decodes a "method"+no-"id" payload; we wire that to `handler`
        via a wrapper that also tracks the "stop" signal."""
        if handler is None:
            self.conn._notification_cb = None
            self._notification_stop = None
            return
        stop_flag = threading.Event()
        self._notification_stop = stop_flag

        def _wrap(msg):
            try:
                if handler(msg):
                    stop_flag.set()
            except Exception as exc:
                log.warning("notification handler raised: %s", exc)

        self.conn._notification_cb = _wrap

    def listen_for_notifications(self,
                                 *, duration: float | None = None) -> None:
        """Block until `duration` elapses, KeyboardInterrupt, disconnect,
        or the installed notification handler returns truthy.
        """
        stop_flag = getattr(self, "_notification_stop", None)
        deadline = (time.monotonic() + duration) if duration else None
        try:
            while True:
                if stop_flag is not None and stop_flag.is_set():
                    return
                if deadline is not None and time.monotonic() >= deadline:
                    return
                if self.conn._client is None or not self.conn._client.is_connected:
                    return
                time.sleep(0.05)
        except KeyboardInterrupt:
            return


class MiniBleTransport(BleTransport):
    """Experimental AirMini FIG transport over the known ResMed BLE GATT.

    This is deliberately a probe: it assumes the same FD56 service and A622
    characteristics as AS11, while selecting AirMini JSON-RPC versions and
    the shared Mini credential family.
    """

    def __init__(self, address: str, *, debug: bool = False,
                 scan_timeout: float = 20.0) -> None:
        super().__init__(
            address,
            debug=debug,
            scan_timeout=scan_timeout,
            rpc_profile=AIRMINI_RPC_PROFILE,
            family="mini",
            name_prefix="mini-ble",
            address_env="AIRMINI_ADDR",
        )

    @classmethod
    def from_args(cls, target: str, args) -> "MiniBleTransport":
        return cls(address=target, debug=getattr(args, "debug", False))


__all__ = [
    # Constants
    "SERVICE_UUID", "TX_CHAR_UUID", "RX_CHAR_UUID", "DEVICE_NAME_PREFIX",
    "FIG_SYNC", "FIG_SYNC_BYTES", "FIG_HEADER_LEN",
    "FIG_VCID_RPC", "FIG_VCID_RPC_ENC", "FIG_VCID_RX_ENC",
    "CRED_FILE", "MAC_RE", "UUID_RE",
    # Classes
    "SRPClient", "FigCodec", "As11Connection", "BleTransport",
    "MiniBleTransport",
    # Helpers
    "H", "decode_ncp_packet",
    "load_all_credentials", "save_all_credentials",
    "load_credentials", "save_credentials",
    "resolve_addr",
]

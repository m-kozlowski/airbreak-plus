"""AS11 BLE transport core.

Classes and helpers used by as11_config.py and as11_flash.py:
    SRPClient        SRP-6a key exchange
    FigCodec         FIG packet framing
    As11Connection   async BLE link + RPC plumbing
    BleTransport     sync wrapper implementing the as11_rpc.Transport
                     protocol; runs an asyncio event loop in a background
                     thread so callers stay synchronous like CAN does

Plus a credentials file at ~/.as11_ble.json and address/alias resolution.

"""

from __future__ import annotations

import asyncio
import binascii
import hashlib
import json
import logging
import os
import re
import struct
import sys
import threading
import time
from pathlib import Path

try:
    from bleak import BleakClient, BleakScanner
except ImportError:
    sys.exit("bleak not installed. Run: pip install bleak")

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives import hashes, hmac

# lib/ is on sys.path; import the shared Transport surface.
from as11_rpc import RPC_VERSIONS, TransportError


# GATT UUIDs + FIG constants.

SERVICE_UUID = "0000fd56-0000-1000-8000-00805f9b34fb"
TX_CHAR_UUID = "a6220002-35f1-4b20-afae-cb089d2044aa"   # app -> device
RX_CHAR_UUID = "a6220003-35f1-4b20-afae-cb089d2044aa"   # device -> app

DEVICE_NAME_PREFIX = "ResMed"

FIG_SYNC       = 0xCAFEBABE
FIG_SYNC_BYTES = struct.pack('<I', FIG_SYNC)
FIG_HEADER_LEN = 12
FIG_VCID_RPC       = 0x0393  # plaintext, key exchange only
FIG_VCID_RPC_ENC   = 0x0397  # encrypted TX
FIG_VCID_RX_ENC    = 0x0396  # encrypted RX

CRED_FILE = Path.home() / ".as11_ble.json"

log = logging.getLogger("as11.ble")


# SRP-6a (RFC 5054 2048-bit group, SHA-256, no identity).

_SRP_N = int(
    "AC6BDB41324A9A9BF166DE5E1389582FAF72B6651987EE07FC3192943DB56050"
    "A37329CBB4A099ED8193E0757767A13DD52312AB4B03310DCD7F48A9DA04FD50"
    "E8083969EDB767B0CF6095179A163AB3661A05FBD5FAAAE82918A9962F0B93B"
    "855F97993EC975EEAA80D740ADBF4FF747359D041D5C33EA71D281E446B1477"
    "3BCA97B43A23FB801676BD207A436C6481F1D2B9078717461A5B9D32E688F87"
    "748544523B524B0D57D5EA77A2775D2ECFA032CFBDBF52FB3786160279004E5"
    "7AE6AF874E7303CE53299CCC041C7BC308D82A5698F3A8D0C38271AE35F8E9D"
    "BFBB694B5C803D89F7AE435DE236D525F54759B65E372FCD68EF20FA7111F9E"
    "4AFF73", 16)
_SRP_G = 2
_SRP_PAD_LEN = 256


def _srp_pad(n):
    return n.to_bytes(_SRP_PAD_LEN, "big")


def H(*args):
    """SHA-256 of concatenated byte arguments (ints padded to 256 bytes BE)."""
    h = hashlib.sha256()
    for a in args:
        if isinstance(a, int):
            a = _srp_pad(a)
        h.update(a)
    return h.digest()


class SRPClient:
    def __init__(self, passkey):
        self.passkey = passkey
        self.a = int.from_bytes(os.urandom(32), "big")
        self.A = pow(_SRP_G, self.a, _SRP_N)
        self.S = None
        self.K = None
        self.M1 = None
        self.M2 = None

    @property
    def public_key_hex(self):
        return _srp_pad(self.A).hex().upper()

    def process(self, server_pk_hex, salt_hex):
        B = int(server_pk_hex, 16)
        if B % _SRP_N == 0:
            raise ValueError("invalid server public key (B mod N == 0)")

        k = int.from_bytes(H(_srp_pad(_SRP_N), _srp_pad(_SRP_G)), "big")
        salt = bytes.fromhex(salt_hex)
        x = int.from_bytes(H(salt, H(self.passkey.encode('ascii'))), "big")
        u = int.from_bytes(H(_srp_pad(self.A), _srp_pad(B)), "big")
        if u == 0:
            raise ValueError("invalid u (== 0)")

        self.S = pow(B - k * pow(_SRP_G, x, _SRP_N), self.a + u * x, _SRP_N) % _SRP_N
        self.K = H(_srp_pad(self.S))

        h_N = H(_srp_pad(_SRP_N))
        h_g = H(_srp_pad(_SRP_G))
        h_xor = bytes(a ^ b for a, b in zip(h_N, h_g))
        self.M1 = H(h_xor, salt, _srp_pad(self.A), _srp_pad(B), self.K)
        self.M2 = H(_srp_pad(self.A), self.M1, self.K)

    @property
    def client_proof_hex(self):
        return self.M1.hex().upper()

    @property
    def session_key_hex(self):
        return self.K.hex().upper()

    def derive_session_key(self, nonce_hex):
        """SHA256(K || nonce) - matches figlib SrpKeyExchange::GenerateSessionKey."""
        self.aes_key = H(self.K, bytes.fromhex(nonce_hex))
        return self.aes_key.hex().upper()

    def verify_server(self, server_proof_hex):
        if server_proof_hex.upper() != self.M2.hex().upper():
            raise ValueError("server proof mismatch")


# FIG codec.

class FigCodec:
    """FIG packet encoder/decoder.

    Frame: [4 SYNC] [2 VCID] [2 LEN] [4 PAYLOAD_CRC] [4 HEADER_CRC] [N PAYLOAD]
    All integers little-endian, CRC32 IEEE.
    """

    def __init__(self):
        self._rx_buf = bytearray()

    @staticmethod
    def crc32(data: bytes) -> int:
        return binascii.crc32(data) & 0xFFFFFFFF

    @staticmethod
    def encode(vcid: int, payload: bytes) -> bytes:
        payload_crc = FigCodec.crc32(payload)
        header = struct.pack('<HH I', vcid, len(payload), payload_crc)
        header_crc = FigCodec.crc32(header)
        return FIG_SYNC_BYTES + header + struct.pack('<I', header_crc) + payload

    def feed(self, data: bytes):
        self._rx_buf.extend(data)

    def decode(self) -> list:
        """Pop complete packets from RX buffer. Returns [(vcid, payload), ...]."""
        packets = []
        while True:
            idx = self._rx_buf.find(FIG_SYNC_BYTES)
            if idx < 0:
                if len(self._rx_buf) > 3:
                    self._rx_buf = self._rx_buf[-3:]
                break

            if idx > 0:
                log.debug("discarding %d bytes before sync", idx)
                self._rx_buf = self._rx_buf[idx:]

            if len(self._rx_buf) < 4 + FIG_HEADER_LEN:
                break

            hdr = bytes(self._rx_buf[4:16])
            vcid, payload_len, payload_crc, header_crc = struct.unpack('<HH II', hdr)

            if FigCodec.crc32(hdr[:8]) != header_crc:
                log.warning("header CRC mismatch, skipping sync")
                self._rx_buf = self._rx_buf[4:]
                continue

            total = 4 + FIG_HEADER_LEN + payload_len
            if len(self._rx_buf) < total:
                break

            payload = bytes(self._rx_buf[16:16 + payload_len])

            if FigCodec.crc32(payload) != payload_crc:
                log.warning("payload CRC mismatch (vcid=%d len=%d)", vcid, payload_len)
                self._rx_buf = self._rx_buf[4:]
                continue

            packets.append((vcid, payload))
            self._rx_buf = self._rx_buf[total:]

        return packets


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
    def __init__(self, debug=False):
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
        self.debug = debug

    def set_session_key(self, key_hex):
        """AES-256 session key from SHA256 output."""
        self._session_key = bytes.fromhex(key_hex[:64])
        log.info("session key set (%d bytes): %s...",
                 len(self._session_key), key_hex[:16])

    def _aes_encrypt(self, plaintext, length_prefix=True):
        """AES-CBC(key, random IV). Wire: [IV][cipher([u16 len][payload][zero pad])]."""
        if length_prefix:
            framed = struct.pack('<H', len(plaintext)) + plaintext
        else:
            framed = plaintext
        pad_len = (16 - len(framed) % 16) % 16
        padded = framed + b'\x00' * pad_len
        iv = os.urandom(16)
        cipher = Cipher(algorithms.AES(self._session_key), modes.CBC(iv))
        enc = cipher.encryptor()
        ct = enc.update(padded) + enc.finalize()
        return iv + ct

    def _aes_decrypt(self, data):
        iv = data[:16]
        ct = data[16:]
        cipher = Cipher(algorithms.AES(self._session_key), modes.CBC(iv))
        dec = cipher.decryptor()
        plaintext = dec.update(ct) + dec.finalize()
        if len(plaintext) >= 2:
            payload_len = struct.unpack_from('<H', plaintext, 0)[0]
            return plaintext[2:2 + payload_len]
        return plaintext.rstrip(b'\x00')

    @staticmethod
    async def scan(timeout=10.0):
        """Returns [(address, name, rssi), ...]."""
        devices = await BleakScanner.discover(
            timeout=timeout,
            service_uuids=[SERVICE_UUID],
            return_adv=True,
        )
        results = []
        for addr, (dev, adv) in devices.items():
            name = dev.name or adv.local_name or ""
            if name.startswith(DEVICE_NAME_PREFIX):
                results.append((dev.address, name, adv.rssi))
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
        version = RPC_VERSIONS.get(method, "2.0")
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
        h = hmac.HMAC(K_bytes, hashes.SHA256())
        h.update(challenge_bytes)
        response_hex = h.finalize().hex().upper()
        log.info("reconnect: response=%s...", response_hex[:16])

        resp2 = await self.send_rpc_raw(
            "CheckSessionIntegrity", {"response": response_hex}, timeout=10.0
        )
        if not resp2 or "error" in resp2:
            err = (resp2 or {}).get("error", {"message": "no response"})
            raise RuntimeError(f"CheckSessionIntegrity failed: {err}")

        log.info("reconnect: session verified")

        nonce_bytes = bytes.fromhex(nonce_hex)
        aes_key = H(K_bytes, nonce_bytes)
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


# Credentials + address resolution.

MAC_RE  = re.compile(r'^[0-9A-Fa-f]{2}(:[0-9A-Fa-f]{2}){5}$')
UUID_RE = re.compile(r'^[0-9A-Fa-f]{8}-([0-9A-Fa-f]{4}-){3}[0-9A-Fa-f]{12}$')


def load_all_credentials() -> dict:
    if not CRED_FILE.exists():
        return {}
    return json.loads(CRED_FILE.read_text())


def save_all_credentials(all_creds: dict):
    CRED_FILE.write_text(json.dumps(all_creds, indent=2))


def save_credentials(address: str, creds: dict):
    all_creds = load_all_credentials()
    existing = all_creds.get(address, {})
    existing.update(creds)
    all_creds[address] = existing
    save_all_credentials(all_creds)
    log.info("credentials saved to %s", CRED_FILE)


def load_credentials(address: str) -> dict:
    return load_all_credentials().get(address, {})


def resolve_addr(arg: str = None) -> str:
    """MAC/UUID -> as-is (MAC uppercased). Alias -> looked up from credentials.
    None falls back to $AS11_ADDR."""
    if arg is None:
        arg = os.environ.get("AS11_ADDR")
    if not arg:
        raise SystemExit("no address: pass --addr or set AS11_ADDR")

    if MAC_RE.match(arg):
        return arg.upper()
    if UUID_RE.match(arg):
        return arg

    for addr, data in load_all_credentials().items():
        if data.get("alias") == arg:
            return addr
    raise SystemExit(f"no MAC/UUID/alias matched: {arg!r}")


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
                 scan_timeout: float = 20.0) -> None:
        self._address = resolve_addr(address) if address else resolve_addr(None)
        self._debug = debug
        self._scan_timeout = scan_timeout
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
        return f"ble:{self._address}"

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
            self._conn = As11Connection(debug=self._debug)
            self._submit(self._conn.connect(self._address),
                         timeout=self._scan_timeout + 5)
            creds = load_credentials(self._address)
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


__all__ = [
    # Constants
    "SERVICE_UUID", "TX_CHAR_UUID", "RX_CHAR_UUID", "DEVICE_NAME_PREFIX",
    "FIG_SYNC", "FIG_SYNC_BYTES", "FIG_HEADER_LEN",
    "FIG_VCID_RPC", "FIG_VCID_RPC_ENC", "FIG_VCID_RX_ENC",
    "CRED_FILE", "MAC_RE", "UUID_RE",
    # Classes
    "SRPClient", "FigCodec", "As11Connection", "BleTransport",
    # Helpers
    "H", "decode_ncp_packet",
    "load_all_credentials", "save_all_credentials",
    "load_credentials", "save_credentials",
    "resolve_addr",
]

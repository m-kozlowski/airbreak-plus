"""Shared ResMed FIG framing, encryption, and SRP session primitives.

The AirSense 11 BLE and AirMini Bluetooth Classic transports carry the same
FIG frames and use the same SRP/AES session construction.  This module has no
Bluetooth dependency, which keeps the wire protocol reusable and testable
without a radio or ``bleak``.
"""

from __future__ import annotations

import binascii
import hashlib
import os
import struct

from cryptography.hazmat.primitives import hashes, hmac
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes


FIG_SYNC = 0xCAFEBABE
FIG_SYNC_BYTES = struct.pack("<I", FIG_SYNC)
FIG_HEADER_LEN = 12

# Host request / device response lanes used by the JSON-RPC session.
FIG_VCID_RPC = 0x0393
FIG_VCID_RX = 0x0392
FIG_VCID_RPC_ENC = 0x0397
FIG_VCID_RX_ENC = 0x0396


# SRP-6a: RFC 5054 2048-bit group, SHA-256, no identity string.
_SRP_N = int(
    "AC6BDB41324A9A9BF166DE5E1389582FAF72B6651987EE07FC3192943DB56050"
    "A37329CBB4A099ED8193E0757767A13DD52312AB4B03310DCD7F48A9DA04FD50"
    "E8083969EDB767B0CF6095179A163AB3661A05FBD5FAAAE82918A9962F0B93B"
    "855F97993EC975EEAA80D740ADBF4FF747359D041D5C33EA71D281E446B1477"
    "3BCA97B43A23FB801676BD207A436C6481F1D2B9078717461A5B9D32E688F87"
    "748544523B524B0D57D5EA77A2775D2ECFA032CFBDBF52FB3786160279004E5"
    "7AE6AF874E7303CE53299CCC041C7BC308D82A5698F3A8D0C38271AE35F8E9D"
    "BFBB694B5C803D89F7AE435DE236D525F54759B65E372FCD68EF20FA7111F9E"
    "4AFF73",
    16,
)
_SRP_G = 2
_SRP_PAD_LEN = 256


def _srp_pad(value: int) -> bytes:
    return value.to_bytes(_SRP_PAD_LEN, "big")


def sha256_concat(*parts: bytes | int) -> bytes:
    """SHA-256 concatenation used by FIG's SRP and session derivation."""
    digest = hashlib.sha256()
    for part in parts:
        if isinstance(part, int):
            part = _srp_pad(part)
        digest.update(part)
    return digest.digest()


# Compatibility name used by the original AS11 implementation.
H = sha256_concat


def derive_session_key(master_pair_key: bytes, nonce: bytes) -> bytes:
    return sha256_concat(master_pair_key, nonce)


def session_integrity_response(master_pair_key: bytes, challenge: bytes) -> bytes:
    digest = hmac.HMAC(master_pair_key, hashes.SHA256())
    digest.update(challenge)
    return digest.finalize()


def aes_encrypt(plaintext: bytes, key: bytes, *, length_prefix: bool = True,
                iv: bytes | None = None) -> bytes:
    """Encrypt a FIG application payload using AES-256-CBC and zero padding."""
    if len(key) != 32:
        raise ValueError(f"FIG AES key must be 32 bytes, got {len(key)}")
    if iv is None:
        iv = os.urandom(16)
    if len(iv) != 16:
        raise ValueError(f"FIG AES IV must be 16 bytes, got {len(iv)}")

    framed = struct.pack("<H", len(plaintext)) + plaintext if length_prefix else plaintext
    pad_len = (-len(framed)) % 16
    padded = framed + b"\x00" * pad_len
    encryptor = Cipher(algorithms.AES(key), modes.CBC(iv)).encryptor()
    return iv + encryptor.update(padded) + encryptor.finalize()


def aes_decrypt(data: bytes, key: bytes, *, length_prefix: bool = True) -> bytes:
    """Decrypt and validate a FIG application payload."""
    if len(key) != 32:
        raise ValueError(f"FIG AES key must be 32 bytes, got {len(key)}")
    if len(data) < 32 or (len(data) - 16) % 16:
        raise ValueError("invalid FIG AES payload length")

    iv, ciphertext = data[:16], data[16:]
    decryptor = Cipher(algorithms.AES(key), modes.CBC(iv)).decryptor()
    plaintext = decryptor.update(ciphertext) + decryptor.finalize()
    if not length_prefix:
        return plaintext.rstrip(b"\x00")
    if len(plaintext) < 2:
        raise ValueError("FIG AES plaintext has no length prefix")
    payload_len = struct.unpack_from("<H", plaintext, 0)[0]
    if payload_len > len(plaintext) - 2:
        raise ValueError("FIG AES plaintext length exceeds decrypted payload")
    return plaintext[2:2 + payload_len]


class SRPClient:
    """Client side of the ResMed SRP-6a first-pairing exchange."""

    def __init__(self, passkey: str, *, private_value: int | None = None):
        self.passkey = passkey
        self.a = (private_value if private_value is not None
                  else int.from_bytes(os.urandom(32), "big"))
        self.A = pow(_SRP_G, self.a, _SRP_N)
        self.S: int | None = None
        self.K: bytes | None = None
        self.M1: bytes | None = None
        self.M2: bytes | None = None

    @property
    def public_key_hex(self) -> str:
        return _srp_pad(self.A).hex().upper()

    def process(self, server_pk_hex: str, salt_hex: str) -> None:
        server_key = int(server_pk_hex, 16)
        if server_key % _SRP_N == 0:
            raise ValueError("invalid server public key (B mod N == 0)")

        multiplier = int.from_bytes(
            sha256_concat(_srp_pad(_SRP_N), _srp_pad(_SRP_G)), "big"
        )
        salt = bytes.fromhex(salt_hex)
        private_key = int.from_bytes(
            sha256_concat(salt, sha256_concat(self.passkey.encode("ascii"))), "big"
        )
        scrambling = int.from_bytes(
            sha256_concat(_srp_pad(self.A), _srp_pad(server_key)), "big"
        )
        if scrambling == 0:
            raise ValueError("invalid SRP scrambling parameter (u == 0)")

        base = server_key - multiplier * pow(_SRP_G, private_key, _SRP_N)
        self.S = pow(base, self.a + scrambling * private_key, _SRP_N)
        self.K = sha256_concat(_srp_pad(self.S))

        h_n = sha256_concat(_srp_pad(_SRP_N))
        h_g = sha256_concat(_srp_pad(_SRP_G))
        h_xor = bytes(left ^ right for left, right in zip(h_n, h_g))
        self.M1 = sha256_concat(
            h_xor, salt, _srp_pad(self.A), _srp_pad(server_key), self.K
        )
        self.M2 = sha256_concat(_srp_pad(self.A), self.M1, self.K)

    def _require_processed(self) -> None:
        if self.K is None or self.M1 is None or self.M2 is None:
            raise ValueError("SRP server key has not been processed")

    @property
    def client_proof_hex(self) -> str:
        self._require_processed()
        return self.M1.hex().upper()

    @property
    def session_key_hex(self) -> str:
        self._require_processed()
        return self.K.hex().upper()

    def derive_session_key(self, nonce_hex: str) -> str:
        self._require_processed()
        return derive_session_key(self.K, bytes.fromhex(nonce_hex)).hex().upper()

    def verify_server(self, server_proof_hex: str) -> None:
        self._require_processed()
        if server_proof_hex.upper() != self.M2.hex().upper():
            raise ValueError("server proof mismatch")


class FigCodec:
    """Incremental FIG frame encoder/decoder.

    Frame::

        [sync:4] [vcid:2] [len:2] [payload_crc:4] [header_crc:4] [payload]

    Integers are little-endian and both checksums are IEEE CRC32.
    """

    def __init__(self):
        self._rx_buf = bytearray()

    @staticmethod
    def crc32(data: bytes) -> int:
        return binascii.crc32(data) & 0xFFFFFFFF

    @staticmethod
    def encode(vcid: int, payload: bytes) -> bytes:
        payload_crc = FigCodec.crc32(payload)
        header = struct.pack("<HHI", vcid, len(payload), payload_crc)
        header_crc = FigCodec.crc32(header)
        return FIG_SYNC_BYTES + header + struct.pack("<I", header_crc) + payload

    def feed(self, data: bytes) -> None:
        self._rx_buf.extend(data)

    def decode(self) -> list[tuple[int, bytes]]:
        packets: list[tuple[int, bytes]] = []
        while True:
            sync_index = self._rx_buf.find(FIG_SYNC_BYTES)
            if sync_index < 0:
                if len(self._rx_buf) > 3:
                    self._rx_buf = self._rx_buf[-3:]
                break
            if sync_index:
                self._rx_buf = self._rx_buf[sync_index:]
            if len(self._rx_buf) < 4 + FIG_HEADER_LEN:
                break

            header = bytes(self._rx_buf[4:16])
            vcid, payload_len, payload_crc, header_crc = struct.unpack("<HHII", header)
            if self.crc32(header[:8]) != header_crc:
                self._rx_buf = self._rx_buf[4:]
                continue

            total = 4 + FIG_HEADER_LEN + payload_len
            if len(self._rx_buf) < total:
                break
            payload = bytes(self._rx_buf[16:total])
            if self.crc32(payload) != payload_crc:
                self._rx_buf = self._rx_buf[4:]
                continue

            packets.append((vcid, payload))
            self._rx_buf = self._rx_buf[total:]
        return packets


__all__ = [
    "FIG_SYNC", "FIG_SYNC_BYTES", "FIG_HEADER_LEN",
    "FIG_VCID_RPC", "FIG_VCID_RX", "FIG_VCID_RPC_ENC", "FIG_VCID_RX_ENC",
    "H", "sha256_concat", "derive_session_key", "session_integrity_response",
    "aes_encrypt", "aes_decrypt", "SRPClient", "FigCodec",
]

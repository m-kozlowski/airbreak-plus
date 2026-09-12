"""ResMed FIG framing, SRP-6a key exchange, and AES payload encryption."""

import binascii
import hashlib
import logging
import os
import struct

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes


FIG_SYNC       = 0xCAFEBABE
FIG_SYNC_BYTES = struct.pack('<I', FIG_SYNC)
FIG_HEADER_LEN = 12
FIG_VCID_RPC       = 0x0393  # plaintext, key exchange only
FIG_VCID_RPC_ENC   = 0x0397  # encrypted TX
FIG_VCID_RX_ENC    = 0x0396  # encrypted RX

# Keep the existing logger name for transport diagnostics.
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


def aes_encrypt(plaintext, key, length_prefix=True):
    """AES-CBC(key, random IV). Wire: [IV][cipher([u16 len][payload][zero pad])]."""
    if len(key) != 32:
        raise ValueError(f"FIG AES key must be 32 bytes, got {len(key)}")
    if length_prefix:
        framed = struct.pack('<H', len(plaintext)) + plaintext
    else:
        framed = plaintext
    pad_len = (16 - len(framed) % 16) % 16
    padded = framed + b'\x00' * pad_len
    iv = os.urandom(16)
    cipher = Cipher(algorithms.AES(key), modes.CBC(iv))
    enc = cipher.encryptor()
    ct = enc.update(padded) + enc.finalize()
    return iv + ct


def aes_decrypt(data, key):
    """Decrypt a FIG payload and validate its length prefix."""
    if len(key) != 32:
        raise ValueError(f"FIG AES key must be 32 bytes, got {len(key)}")
    if len(data) < 32 or (len(data) - 16) % 16:
        raise ValueError("invalid FIG AES payload length")
    iv = data[:16]
    ct = data[16:]
    cipher = Cipher(algorithms.AES(key), modes.CBC(iv))
    dec = cipher.decryptor()
    plaintext = dec.update(ct) + dec.finalize()
    payload_len = struct.unpack_from('<H', plaintext, 0)[0]
    if payload_len > len(plaintext) - 2:
        raise ValueError("FIG AES plaintext length exceeds decrypted payload")
    return plaintext[2:2 + payload_len]

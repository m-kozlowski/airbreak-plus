# Air11 Bluetooth Protocol

Air11 Bluetooth uses a BLE GATT pipe carrying FIG packets. Normal local RPC
traffic runs inside an SRP-derived AES session.

The BLE radio is handled by a separate network coprocessor. The STM32 firmware
contains the RPC dispatcher and the FIG/security plumbing, but not every
low-level GATT detail.

## Contents

- [GATT](#gatt)
- [FIG packet format](#fig-packet-format)
- [VCIDs](#vcids)
- [Security/session model](#securitysession-model)
- [First pairing flow](#first-pairing-flow)
  - [SRP formulas](#srp-formulas)
  - [RPC sequence](#rpc-sequence)
- [Reconnection flow](#reconnection-flow)
- [Encrypted payload format](#encrypted-payload-format)
- [Local credential file](#local-credential-file)
- [Heartbeat and notifications](#heartbeat-and-notifications)

## GATT

Service and characteristics:

| Item | UUID | Direction |
|------|------|-----------|
| Service | `0000fd56-0000-1000-8000-00805f9b34fb` | advertised service |
| TX characteristic | `a6220002-35f1-4b20-afae-cb089d2044aa` | app to device |
| RX characteristic | `a6220003-35f1-4b20-afae-cb089d2044aa` | device to app |
| CCCD | `00002902-0000-1000-8000-00805f9b34fb` | notifications |

Advertisements use names beginning with `ResMed`.

Writes are chunked to the negotiated GATT write size. The device reassembles
FIG packets above the GATT characteristic layer.

## FIG packet format

All integer fields are little-endian. CRC is IEEE CRC32.

```
[sync:4] [vcid:2] [payload_len:2] [payload_crc32:4] [header_crc32:4] [payload]
```

| Offset | Size | Field |
|--------|------|-------|
| `0x00` | 4 | sync, literal `0xCAFEBABE` as little-endian bytes |
| `0x04` | 2 | VCID |
| `0x06` | 2 | payload length |
| `0x08` | 4 | CRC32 over payload |
| `0x0c` | 4 | CRC32 over bytes `0x04..0x0b` |
| `0x10` | variable | payload |

The FIG decoder scans for the sync word, validates the header CRC, waits for
the full payload, then validates the payload CRC.

## VCIDs

BLE RPC/session lanes:

| Device TX / permission selector | Device RX / host request VCID | Payload | Device TX/RX buffers | Notes |
|-------------------------------|-------------------------------|---------|----------------------|-------|
| `0x0390` | `0x0391` | plaintext `NcpCommandBuffer` RPC | 600 / 600 bytes | small binary lane |
| `0x0392` | `0x0393` | plaintext JSON | 7650 / 7650 bytes | security/session lane used by current tools |
| `0x0394` | `0x0395` | encrypted `NcpCommandBuffer` RPC | 632 / 600 bytes | small binary lane |
| `0x0396` | `0x0397` | encrypted JSON | 7682 / 7650 bytes | application lane used by current tools |

The binary RPC stack and record format are documented in the
[NCP binary RPC protocol](ncp_protocol.md). Standard RPC services retain their
normal per-channel permissions. The stock permission table denies the
additional DataItem, memory-window, mapping, and diagnostic commands on both
BLE binary lanes.

The plaintext JSON path accepts only the key exchange/session methods.
Ordinary JSON calls such as `GetVersion`, `Get`, and `Set` require the
encrypted session.

## Security/session model

BLE has two different protocol phases:

| Phase | TX VCID | RX VCID | Payload | Purpose |
|-------|---------|---------|---------|---------|
| Plaintext security/session | `0x0393` | `0x0392` | raw UTF-8 JSON | first pairing and session resume only |
| Encrypted application RPC | `0x0397` | `0x0396` | AES-CBC encrypted JSON | normal `GetVersion`, `Get`, `Set`, OTA, stream, spool |

The plaintext phase does not expose the normal application RPC surface. It is
used to prove a pairing secret and derive the per-connection AES key. After
that, application RPCs move to the encrypted VCIDs.

The important key distinction:

| Name | Size | Lifetime | Meaning |
|------|------|----------|---------|
| passkey | 4 ASCII digits | one pairing attempt | shown on the device screen |
| `K` / `masterPairKey` | 32 bytes | reusable pairing credential | SRP session key stored by the client after pairing |
| `clientId` | string | reusable pairing credential | device-assigned identifier for this paired client |
| `nonce` | hex bytes from device | one BLE session | mixed with `K` to derive this session's AES key |
| AES session key | 32 bytes | one BLE session | `SHA256(K || nonce_raw)`; used for encrypted VCID traffic |

Only `clientId` and `masterPairKey` are needed to reconnect later. A saved
`sessionKey` value is diagnostic/cache data, not a reusable credential and
not the source used for reconnect.

## First pairing flow

First pairing uses a custom SRP-6a variant with the RFC 5054 2048-bit group,
generator `g = 2`, and SHA-256 throughout. The user enters the 4-digit
passkey shown on the device screen.

All pairing messages are plaintext JSON inside FIG packets on VCID `0x0393`,
with responses on `0x0392`.

### SRP formulas

All big integers are serialized as 256-byte big-endian values before hashing.

| Symbol | Formula |
|--------|---------|
| `k` | `H(pad(N) || pad(g))` |
| `x` | `H(salt_raw || H(passkey_ascii))` |
| `u` | `H(pad(A) || pad(B))` |
| `S` | `(B - k * g^x)^(a + u * x) mod N` |
| `K` | `H(pad(S))` |
| `M1` | `H((H(N) xor H(g)) || salt_raw || pad(A) || pad(B) || K)` |
| `M2` | `H(pad(A) || M1 || K)` |

There is no SRP identity string and no `identity:password` hash. `H(...)`
means SHA-256 over concatenated byte strings.

### RPC sequence

1. Client creates a random private value `a`, computes `A = g^a mod N`, and
   sends:

```json
{"jsonrpc":"2.0","method":"StartKeyExchange","id":1,"params":{"clientPk":"<512 hex A>"}}
```

2. Device returns the server public key and salt:

```json
{"jsonrpc":"2.0","id":1,"result":{"serverPk":"<512 hex B>","salt":"<hex salt>"}}
```

3. Client computes `x`, `u`, `S`, `K`, and proof `M1`, then sends:

```json
{"jsonrpc":"2.0","method":"ConfirmKeyExchange","id":2,"params":{"clientConfirmation":"<64 hex M1>"}}
```

4. Device verifies `M1` and returns:

```json
{
  "jsonrpc": "2.0",
  "id": 2,
  "result": {
    "clientId": "<device assigned id>",
    "serverConfirmation": "<64 hex M2>",
    "nonce": "<64 hex>"
  }
}
```

5. Client should verify `serverConfirmation` against its expected `M2`.
6. Client saves `clientId` and `K` (`masterPairKey`) as the reusable pairing
   credentials.
7. Client derives the immediate AES session key from the returned `nonce`:

```text
session_key = SHA256(K || nonce_raw)
```

After step 7, encrypted application RPC can be sent on `0x0397` and responses
are received on `0x0396`.

## Reconnection flow

A paired client can reconnect without showing a new passkey. This is a
challenge/response proof that the client still knows `K`.

1. Client sends plaintext `RequestSession` with its saved `clientId`:

```json
{"jsonrpc":"2.0","method":"RequestSession","id":1,"params":{"clientId":"<client id>"}}
```

2. Device returns a challenge and a fresh nonce:

```json
{"jsonrpc":"2.0","id":1,"result":{"challenge":"<hex challenge>","nonce":"<hex nonce>"}}
```

3. Client computes:

```text
response = HMAC-SHA256(K, challenge_raw)
```

4. Client sends:

```json
{"jsonrpc":"2.0","method":"CheckSessionIntegrity","id":2,"params":{"response":"<64 hex response>"}}
```

5. If accepted, both sides derive:

```
session_key = SHA256(K || nonce_raw)
```

6. Continue on encrypted VCIDs `0x0397/0x0396`.

The reconnect path does not use the 4-digit passkey. It uses only
`clientId`, `masterPairKey`, the device challenge, and the fresh nonce.

## Encrypted payload format

Encrypted FIG payload:

```
[iv:16] [AES-256-CBC([payload_len:2 LE] [json_payload] [zero padding])]
```

Rules:

- IV is random per packet.
- The plaintext starts with a 16-bit little-endian JSON length.
- Padding is zero bytes up to the next 16-byte AES block boundary.
- Decryption reads the length field and ignores padding.

The encrypted JSON is the RPC payload described in the
[RPC protocol](rpc_protocol.md).

## Local credential file

| Field | Meaning |
|-------|---------|
| `clientId` | device-assigned pairing identifier |
| `masterPairKey` | SRP `K`, reused for challenge HMAC |
| `sessionKey` | local cache/display field; not used for reconnect and may not contain the full AES key |
| `nonce` | latest nonce used for key derivation |
| `serverPk` | server SRP public key returned during pairing |
| `serverConfirmation` | server SRP proof returned during pairing |

Only `clientId` and `masterPairKey` are logically required for reconnect.
`sessionKey` must be regenerated after every successful `ConfirmKeyExchange`
or `RequestSession` because the device provides a fresh nonce.

## Heartbeat and notifications

`HeartBeat` notifications can arrive on the plaintext RX VCID. Encrypted RPC
notifications use the encrypted RX VCID after session setup.

Clients must handle notifications while waiting for a request response.

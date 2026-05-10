# AS11 RPC Protocol

AirSense 11 and AirCurve 11 use a JSON-RPC-like command layer above the
local transports. BLE, CAN, and the cellular/cloud path all converge on the
same firmware RPC dispatcher.

This document describes the application RPC payloads. Transport framing is
covered separately in `bluetooth_protocol.md` and `can_protocol.md`.

## Contents

- [Message format](#message-format)
- [GetVersion](#getversion)
- [Get and Set](#get-and-set)
- [Notifications](#notifications)
- [Stream RPC](#stream-rpc)
- [Spool RPC](#spool-rpc)
- [Method sets](#method-sets)
  - [Plaintext BLE security/session VCID](#plaintext-ble-securitysession-vcid)
  - [Patient / myAir BLE](#patient--myair-ble)
  - [Service / CAN](#service--can)
- [Error codes](#error-codes)

## Message format

Requests are UTF-8 JSON objects:

```json
{"jsonrpc":"1.0","method":"Get","id":1,"params":["_MOP","_GOM","_TOM"]}
```

Responses are JSON objects with the matching `id`:

```json
{"jsonrpc":"1.0","id":1,"result":{"_MOP":"CpapProfile"}}
```

Errors use the usual JSON-RPC-style `error` object:

```json
{"jsonrpc":"1.0","id":1,"error":{"code":-11202,"message":"SettingApplicationFailure"}}
```

The `jsonrpc` field is not a strict JSON-RPC protocol version in all AS11
paths. The local tools fill it from the method capability table, so
`GetVersion` uses `"2.0"`, `SetDateTime` uses `"1.1"`, and most other methods
use `"1.0"`.

## GetVersion

`GetVersion` returns identification profiles plus the visible RPC method set.
The exact method list depends on the transport and access level.

```json
{"jsonrpc":"2.0","method":"GetVersion","id":1}
```

The method table is nested under `result.FlowGenerator.RPC`. The response can also include Bluetooth and cellular module
identity blocks:

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "result": {
    "FlowGenerator": {
      "IdentificationProfiles": {
        "Software": {
          "ApplicationIdentifier": "SW04600.15.8.4.0.791777c3b",
          "BootloaderIdentifier": "SW04601.00.1.1.0.736edbdfd",
          "ConfigurationIdentifier": "CF04600.15.03.00.791777c3b",
          "DataModelVersionIdentifier": "v2.15.2.7fc2c6467"
        },
        "Hardware": {
          "HardwareIdentifier": "(90)R390-....(91)....(21)...."
        },
        "Product": {
          "UniversalIdentifier": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
        }
      },
      "RPC": {
        "GetDateTime": "1.0",
        "GetVersion": "2.0",
        "StartStream": "1.0",
        "InitiateUpgrade": "1.0",
        "UpgradeDataBlock": "1.0",
        "CheckUpgradeFile": "1.0",
        "EnterStandby": "1.0",
        "EnterTherapy": "1.0",
        "SubscribeEvent": "1.0",
        "EraseData": "1.0",
        "EnterMaskFit": "2.0",
        "ApplyAuthenticatedUpgrade": "1.0",
        "Get": "1.0",
        "Set": "1.0",
        "GenerateAuthCode": "1.1",
        "DiscardPairKey": "1.0",
        "StartSpool": "1.0",
        "PullSpoolFragments": "1.0",
        "EnterTestDrive": "1.0"
      }
    },
    "BluetoothModule": {
      "IdentificationProfiles": {
        "Software": {
          "ApplicationIdentifier": "ST290.2.12.3.151.5"
        },
        "Hardware": {
          "HardwareIdentifier": "(90)R390-....(91)....(21)...."
        },
        "Product": {
          "UniversalIdentifier": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
        }
      }
    },
    "CellularModule": {
      "IdentificationProfiles": {
        "Product": {
          "UniversalIdentifier": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
        },
        "Hardware": {
          "HardwareIdentifier": "(90)R390-....(91)....(21)...."
        },
        "Software": {
          "ApplicationIdentifier": "SW04600.15.8.4.0.791777c3b"
        },
        "CellularProfile": {
          "Equipment": {
            "Software": {
              "ApplicationIdentifier": "Cinterion EXS62-W REVISION 01.200 A-REVISION 01.000.01,No midlet on this module"
            }
          }
        }
      }
    }
  }
}
```

## Get and Set

`Get` reads keys from the RPC/CDX naming layer. In practice the useful forms
are:

| Form | Example | Notes |
|------|---------|-------|
| Long RPC/CDX name | `Language`, `ActiveTherapyProfile` | preferred spelling when known |
| Underscore alias | `_LAN`, `_MOP` | firmware alias for many CONF three-letter tags |
| Aggregate/subtree name | `FeatureProfiles`, `TherapyProfiles` | returns a nested object when exposed |


```json
{"jsonrpc":"1.0","method":"Get","id":2,"params":["_LAN","Language","_MOP"]}
```

Result:

```json
{
  "_LAN": "English",
  "Language": "English",
  "_MOP": "CpapProfile"
}
```

`Set` takes an object of RPC key to value. Use the same long-name or
underscore-alias spelling accepted by `Get`:

```json
{"jsonrpc":"1.0","method":"Set","id":3,"params":{"_RPE":"On"}}
```

Result echoes the accepted values:

```json
{"_RPE":"On"}
```

The value type matters. Some settings accept enum strings, some accept
integers, and a few accept numeric-looking strings. A failed application can
still have side effects if the setting layer applied part of the change before
returning an error.

## Notifications

Device-initiated messages have a `method` and no `id`:

```json
{"jsonrpc":"1.0","method":"HeartBeat","params":{}}
```

Notifications can arrive while a request is waiting for its response. A
transport implementation must skip notifications until the response with the
matching `id` is received.

## Stream RPC

`StartStream` starts periodic signal reporting.

Observed parameter fields:

| Field | Meaning |
|-------|---------|
| `dataIds` | Array of data identifiers to stream |
| `sampleIntervalMs` | Sampling interval in milliseconds |
| `reportIntervalMs` | Reporting interval in milliseconds |

Observed constraints:

| Constraint | Value |
|------------|-------|
| Minimum interval | 10 ms |
| Interval granularity | 10 ms |
| Maximum sample interval | 65000 ms |
| Maximum report interval | 300000 ms |
| `reportIntervalMs` | must not exceed `sampleIntervalMs * 5` |
| Maximum `dataIds` | 30 |

The firmware rounds both intervals down to the nearest 10 ms. The shortest
accepted sample interval observed in the request parser is therefore 10 ms.

The response contains a `streamId` plus a `dataIds` array. Each requested item
is echoed as an object with `dataId` and `valid`, so clients can probe stream
names without guessing from the final data notifications.

Stream payloads are returned as notifications, usually with method
`StreamData`. Accepted names include direct signal names such as `Leak-50hz`,
`PatientFlow-100hz`, `MaskPressure-TwoSecond`, `HeartRate`, and `SpO2`, plus
summary/statistic names such as `Summary-Leak-50`.
Known stream data IDs and EDF-oriented aliases are listed in
[AS11 RPC Stream Reference](rpc_streams.md). The generated EDF file layout is
documented separately in [AirSense 11 EDF Signal Reference](edf_signals.md).

## Spool RPC

`StartSpool` and `PullSpoolFragments` are used for larger asynchronous data
pulls. The firmware starts pushing notifications immediately after the request
arrives, so clients must install the notification handler before issuing the
first spool RPC.

Start one spool round:

```json
{
  "spoolAddress": {
    "Summary": {
      "fromDateTime": "2026-04-29T00:00:00.000Z"
    }
  },
  "maxSpoolSize": 4096
}
```

Response:

```json
{"spoolId": 12}
```

Pull fragments for that spool id:

```json
{
  "spoolId": 12,
  "maxFragmentSize": 4096,
  "maxNotifications": 0
}
```

Observed request fields:

| RPC | Field | Meaning |
|-----|-------|---------|
| `StartSpool` | `spoolAddress` | Object with exactly one spool type key |
| `StartSpool` | `spoolAddress.<type>.fromDateTime` | Lower bound timestamp for the requested spool |
| `StartSpool` | `maxSpoolSize` | Maximum raw bytes to collect in this round |
| `PullSpoolFragments` | `spoolId` | Id returned by `StartSpool` |
| `PullSpoolFragments` | `maxFragmentSize` | Maximum raw bytes per `SpoolFragment` notification |
| `PullSpoolFragments` | `maxNotifications` | Notification count limit; `0` means no explicit limit |

Parameter checks seen on 15.8.4.0:

| Parameter shape | Result |
|-----------------|--------|
| `{"Summary":{"fromDateTime":"..."}}` | accepted |
| `{"Summary":{}}` | `Invalid Params` |
| `{"Summary":{"FromDateTime":"..."}}` | `Invalid Params` |
| `{"Summary":{"fromdatetime":"..."}}` | `Invalid Params` |
| `{"Summary":{"toDateTime":"..."}}` | `Invalid Params` |

When a round does not contain all available data, the terminal `SpoolFragment`
contains `nextSpoolAddress`, which is another address object of the same
shape and should be passed back to `StartSpool` for the next round.

Fragments arrive as notifications:

```json
{
  "method": "SpoolFragment",
  "params": {
    "seq": 0,
    "data": "<base64>",
    "status": "SPOOL_COMPLETE_MORE_DATA_PENDING",
    "spoolHash": "<SHA256 of concatenated raw data>",
    "nextSpoolAddress": {
      "Summary": {
        "fromDateTime": "2026-04-29T11:00:00.000Z"
      }
    }
  }
}
```

Known terminal statuses:

| Status | Meaning |
|--------|---------|
| `SPOOL_INCOMPLETE` | More fragments are expected for the current round |
| `SPOOL_COMPLETE_MORE_DATA_PENDING` | This round is complete, but another round is available |
| `SPOOL_COMPLETE_NO_MORE_DATA` | This round is complete and no continuation is pending |

`PullSpoolFragments` looks like a read, but it advances a cursor. It should
not be blindly retried after a framing failure. Each `StartSpool` creates a
fresh cursor keyed to the supplied `fromDateTime`.

Known spool types, payload families, wire field numbers, and inner record
shapes are listed in [AS11 RPC Spool Reference](rpc_spools.md).

## Method sets

The capability strings are embedded in firmware. The visible set varies by
transport and access level.

### Plaintext BLE security/session VCID

The plaintext BLE VCID is used to create or resume an encrypted session.

Known plaintext requests:

| Method | Version | Notes |
|--------|---------|-------|
| `StartKeyExchange` | 2.0 | first SRP pairing request; sends client public key |
| `ConfirmKeyExchange` | 2.0 | completes SRP pairing after passkey proof |
| `RequestSession` | 2.0 | reconnect using an existing `clientId` |
| `CheckSessionIntegrity` | 2.0 | HMAC response for reconnect challenge |

`HeartBeat` notifications can also appear on the plaintext RX VCID. Normal
application RPCs such as `GetVersion`, `Get`, `Set`, and OTA calls require
the SRP/AES session described in `bluetooth_protocol.md`.

Older notes and figlib-derived tooling names such as `GetPairKey` and
`GetSessionKey` are host-side abstractions for the pairing/session sequence,
not confirmed raw firmware RPC method names.

### Patient / myAir BLE

Observed methods:

| Method | Version | Notes |
|--------|---------|-------|
| `GetDateTime` | 1.0 | read clock |
| `GetVersion` | 2.0 | read capability set |
| `StartStream` | 1.0 | start streaming |
| `InitiateUpgrade` | 1.0 | OTA staging |
| `UpgradeDataBlock` | 1.0 | OTA staging |
| `CheckUpgradeFile` | 1.0 | OTA verification |
| `EnterStandby` | 1.0 | state change |
| `EnterTherapy` | 1.0 | state change |
| `SubscribeEvent` | 1.0 | notifications |
| `EraseData` | 1.0 | destructive |
| `EnterMaskFit` | 2.0 | state change |
| `ApplyAuthenticatedUpgrade` | 1.0 | authenticated OTA apply |
| `Get` | 1.0 | read settings |
| `Set` | 1.0 | write settings |
| `GenerateAuthCode` | 1.1 | security/auth material path |
| `DiscardPairKey` | 1.0 | security state mutation |
| `StartSpool` | 1.0 | spool protocol |
| `PullSpoolFragments` | 1.0 | spool protocol |
| `EnterTestDrive` | 1.0 | state change |

### Service / CAN

The CAN service endpoint exposes the broadest local method set observed so
far:

| Method | Version | Notes |
|--------|---------|-------|
| `GetDateTime` | 1.0 | read clock |
| `SetDateTime` | 1.1 | write clock |
| `GetVersion` | 2.0 | read capability set |
| `StartStream` | 1.0 | start streaming |
| `InitiateUpgrade` | 1.0 | OTA staging |
| `UpgradeDataBlock` | 1.0 | OTA staging |
| `CheckUpgradeFile` | 1.0 | OTA verification |
| `ApplyUpgrade` | 1.1 | plain OTA apply, service path |
| `GetLedStatus` | 1.0 | status |
| `EnterStandby` | 1.0 | state change |
| `EnterTherapy` | 1.0 | state change |
| `SetNextPowerUpDateTime` | 1.0 | power scheduling |
| `SubscribeEvent` | 1.0 | notifications |
| `EraseData` | 1.0 | destructive |
| `ResetDevice` | 1.0 | reset |
| `StoreSecurityData` | 1.0 | security state mutation |
| `EnterMaskFit` | 2.0 | state change |
| `ApplyAuthenticatedUpgrade` | 1.0 | authenticated OTA apply |
| `Get` | 1.0 | read settings |
| `Set` | 1.0 | write settings |
| `VerifySecurityData` | 1.0 | security/auth material path |
| `GenerateAuthCode` | 1.1 | security/auth material path |
| `ClearAutoConnectList` | 1.0 | security/connectivity mutation |
| `DiscardPairKey` | 1.0 | security state mutation |
| `StartSpool` | 1.0 | spool protocol |
| `PullSpoolFragments` | 1.0 | spool protocol |
| `EnterTestDrive` | 1.0 | state change |
| `EnableSecurity` | 1.0 | security state mutation |

## Error codes

Observed errors:

| Code | Message | Notes |
|------|---------|-------|
| `-32700` | `Parse Error` | JSON or wrong VCID/path |
| `-11202` | `SettingApplicationFailure` | setting rejected or failed during apply |
| `-11305` | `UpgradeFileIntegrityFailure` | OTA hash/CRC/descriptor mismatch |
| `-11306` | `UpgradeFileAuthenticationFailure` | OTA HMAC/authentication mismatch |
| `-11308` | `UpgradeFileIncompatible` | OTA format/component/target rejected |
| `-11309` | `UpgradeFileInvalid` | OTA container invalid |

# Air11 RPC Protocol

Air11 firmware exposes a JSON-RPC command layer over BLE, CAN, and internal
cellular channels. All channels use the same method dispatcher, with separate
method permissions and payload-size limits.

This document is the command reference. Transport framing is documented in
the [Bluetooth protocol](bluetooth_protocol.md) and
[CAN protocol](can_protocol.md). Event selectors, stream data IDs, spool
formats, and upgrade containers have separate references linked from the
relevant methods below.

## Contents

- [Message format](#message-format)
- [Method index](#method-index)
- [Method reference](#method-reference) (alphabetical)
- [Notifications](#notifications)
- [Permission channels](#permission-channels)
- [Error codes](#error-codes)

## Message format

Requests are UTF-8 JSON objects. The `jsonrpc` value is the contract version
listed in the [method index](#method-index):

```json
{"jsonrpc":"1.0","method":"Get","id":1,"params":["_MOP"]}
```

Firmware responses use `jsonrpc: "2.0"` and echo the request `id`:

```json
{"jsonrpc":"2.0","id":1,"result":{"_MOP":"CpapProfile"}}
```

Errors replace `result` with an `error` object:

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "error": {
    "code": -11202,
    "message": "SettingApplicationFailure",
    "data": {"_RPE": "Off"}
  }
}
```

Methods without parameters omit `params`. An omitted member, an empty object,
an empty array, and JSON `null` are not interchangeable. Method names and
parameter keys are case-sensitive.

Request examples show the complete JSON-RPC envelope. Response examples show
the `result` value unless the complete envelope matters.

## Method index

`Version` is the request contract version advertised by `GetVersion`, or the
native `2.0` version used by plaintext BLE pairing methods. A dash marks a name
omitted from the capability map. `Stock access` refers only to the permission
sets in [Permission channels](#permission-channels); it does not bypass a
method's state or hardware gates. Method availability can vary by firmware
release and channel; the device's `GetVersion` result is authoritative for
advertised methods. Select a method name to open its full reference.

| Method | Version | Stock access | Parameters | Purpose |
|--------|---------|--------------|------------|---------|
| [`ApplyAuthenticatedUpgrade`](#applyauthenticatedupgrade) | 1.0 | all | `upgradeFileHash`, `authentication` | apply a staged upgrade using an HMAC |
| [`ApplyUpgrade`](#applyupgrade) | 1.1 | service | `upgradeFileHash`, `resetSettingsToDefault` | apply a staged upgrade without HMAC authentication |
| [`CheckSessionIntegrity`](#checksessionintegrity) | 2.0 | BLE plaintext | `response` | finish BLE session authentication |
| [`CheckUpgradeFile`](#checkupgradefile) | 1.0 | all | `upgradeFileHash` | validate a completely transferred upgrade file |
| [`ClearAutoConnectList`](#clearautoconnectlist) | 1.0 | service | none | clear the Bluetooth auto-connect list |
| [`ConfirmKeyExchange`](#confirmkeyexchange) | 2.0 | BLE plaintext | `clientConfirmation` | confirm first-pairing SRP key exchange |
| [`DiscardPairKey`](#discardpairkey) | 1.0 | BLE encrypted | none | remove stored BLE pairing material |
| [`EnableSecurity`](#enablesecurity) | 1.0 | service | none | store the retained security-request marker |
| [`EnterLearnTargets`](#enterlearntargets) | 1.0 | application | none | enter learn-targets state |
| [`EnterMaskFit`](#entermaskfit) | 2.0 | application | `maskFitPressure` | enter mask-fit state at a requested pressure |
| [`EnterStandby`](#enterstandby) | 1.0 | application | none | request standby state |
| [`EnterTest`](#entertest) | - | service | `testMode` | enter a manufacturing or diagnostic test mode |
| [`EnterTestDrive`](#entertestdrive) | 1.0 | BLE encrypted | none | enter test-drive state |
| [`EnterTherapy`](#entertherapy) | 1.0 | application | none | request therapy state |
| [`EraseData`](#erasedata) | 1.0 | application | `eraseMethod`, `dataTypes` | erase selected persistent data classes |
| [`GenerateAuthCode`](#generateauthcode) | 1.1 | application | `nonce`, `keyLocation`, `algorithm` | compute an HMAC from a device key-provider entry |
| [`Get`](#get) | 1.0 | application | array of object names | read settings, profiles, and data items |
| [`GetDateTime`](#getdatetime) | 1.0 | all | none | read device date and time |
| [`GetLedStatus`](#getledstatus) | 1.0 | service | none | read LED and LCD-backlight output state |
| [`GetRtcAndSystemClocks`](#getrtcandsystemclocks) | - | service | none | read RTC and high-resolution clocks |
| [`GetVersion`](#getversion) | 2.0 | all | none | read identification and advertised RPC capabilities |
| [`InitiateUpgrade`](#initiateupgrade) | 1.0 | all | `upgradeFileSize` | create an upgrade transfer session |
| [`InjectLoggedEvent`](#injectloggedevent) | - | service | `EventType`, `EventCode` | inject an event into a selected log family |
| [`InsertSdCard`](#insertsdcard) | - | service | `writeProtected`, `size`, `error`, `pendingError` | populate the service SD-card proxy |
| [`PullSpoolFragments`](#pullspoolfragments) | 1.0 | application | `spoolId`, `maxFragmentSize`, `maxNotifications` | request fragments from an open spool |
| [`RemoveSdCard`](#removesdcard) | - | service | none | clear the service SD-card proxy |
| [`RequestSession`](#requestsession) | 2.0 | BLE plaintext | `clientId` | begin reconnect authentication for a paired client |
| [`ResetDevice`](#resetdevice) | 1.0 | service | `type` | request a controlled device reset |
| [`Set`](#set) | 1.0 | application | object of names and values | write settings and data items |
| [`SetDateTime`](#setdatetime) | 1.1 | service | `dateTime` | set device date and time |
| [`SetNextPowerUpDateTime`](#setnextpowerupdatetime) | 1.0 | service | `value` | set the RTC value restored at the next application startup |
| [`StartKeyExchange`](#startkeyexchange) | 2.0 | BLE plaintext | `clientPk` | begin first-pairing SRP key exchange |
| [`StartSpool`](#startspool) | 1.0 | application | `spoolAddress`, `maxSpoolSize` | open a stored-data spool |
| [`StartStream`](#startstream) | 1.0 | application | `dataIds`, `sampleIntervalMs`, `reportIntervalMs` | start periodic live-data reporting |
| [`StoreSecurityData`](#storesecuritydata) | 1.0 | service | `verifier`, `data` | store a verified security-data block |
| [`SubscribeEvent`](#subscribeevent) | 1.0 | application | `dataIds` | subscribe to event families or DataItem value changes |
| [`UpgradeDataBlock`](#upgradedatablock) | 1.0 | all | `fileOffset`, `encoding`, `data` | transfer one upgrade-file block |
| [`VerifySecurityData`](#verifysecuritydata) | 1.0 | service | `verifier` | verify stored security data |

### Unregistered method names

The following names occur in the firmware method-name table but have no
registered synchronous or asynchronous command handler in releases 14.8.3.0
through 17.8.6.0:

```text
CheckLcdBitmap
CheckLcdLine
CheckLcdRectFilled
CheckLcdText
CheckLcdWindow
GetBitmapInfo
ShowAllMenuListItems
```

They are not callable RPC methods. A request using one of these names reaches
the command dispatcher without an executable service and returns `Method Not
Found`.

## Method reference

Methods are ordered alphabetically. The [method index](#method-index) links
directly to every entry.

### ApplyAuthenticatedUpgrade

`ApplyAuthenticatedUpgrade` authenticates and applies a completely staged
upgrade container. It requires an HMAC derived from the device-specific OTA
key. The container must first be staged with
[`InitiateUpgrade`](#initiateupgrade), transferred with
[`UpgradeDataBlock`](#upgradedatablock), and accepted by
[`CheckUpgradeFile`](#checkupgradefile).

Request:

```json
{
  "jsonrpc": "1.0",
  "method": "ApplyAuthenticatedUpgrade",
  "id": 1,
  "params": {
    "upgradeFileHash": "<64 hexadecimal SHA-256>",
    "authentication": "<64 hexadecimal HMAC-SHA256>"
  }
}
```

Parameters:

| Field | Type | Meaning |
|-------|------|---------|
| `upgradeFileHash` | string | 64 hexadecimal characters; SHA-256 of the complete transferred container |
| `authentication` | string | 64 hexadecimal characters; HMAC-SHA256 authentication value |

An accepted request reports the apply decision and expected duration:

```json
{
  "confirmResult": "MatchingFileUpgradeTriggered",
  "estimatedApplySec": 40
}
```

`MatchingFileUpgradeTriggered` confirms that the firmware has scheduled the
apply operation. Applying the image subsequently restarts the device and closes
the transport connection.
The HMAC construction and OTA key are documented in the
[OTA protocol](ota_protocol.md).

### ApplyUpgrade

`ApplyUpgrade` applies a completely staged upgrade through the
unauthenticated service path. It can optionally reset persistent settings to
the defaults supplied by the installed firmware. The staging sequence is
[`InitiateUpgrade`](#initiateupgrade),
[`UpgradeDataBlock`](#upgradedatablock), then
[`CheckUpgradeFile`](#checkupgradefile).

Request:

```json
{
  "jsonrpc": "1.1",
  "method": "ApplyUpgrade",
  "id": 1,
  "params": {
    "upgradeFileHash": "<64 hexadecimal SHA-256>",
    "resetSettingsToDefault": false
  }
}
```

Parameters:

| Field | Type | Meaning |
|-------|------|---------|
| `upgradeFileHash` | string | 64 hexadecimal characters; SHA-256 of the complete transferred container |
| `resetSettingsToDefault` | boolean | request a settings reset while the accepted image is installed |

The accepted result has the same `confirmResult` and `estimatedApplySec` fields as
[`ApplyAuthenticatedUpgrade`](#applyauthenticatedupgrade). Send
`resetSettingsToDefault` explicitly rather than relying on the firmware's
omitted-field behavior. Applying the image subsequently restarts the device and
closes the transport connection.

### CheckSessionIntegrity

`CheckSessionIntegrity` completes BLE reconnection authentication. It verifies
that the client knows the master pair key established during initial pairing.

Request:

```json
{
  "jsonrpc": "2.0",
  "method": "CheckSessionIntegrity",
  "id": 1,
  "params": {"response":"<64 hexadecimal characters>"}
}
```

`response` is `HMAC-SHA256(K, challenge)`, where `K` is the stored master pair
key and `challenge` came from [`RequestSession`](#requestsession).

Result:

```json
{"confirmation":true}
```

The client then derives the encrypted-session key from the fresh nonce. See
the [Bluetooth protocol](bluetooth_protocol.md#reconnection-flow).

### CheckUpgradeFile

`CheckUpgradeFile` validates the fully transferred upgrade container before an
apply method can install it.

Request:

```json
{
  "jsonrpc": "1.0",
  "method": "CheckUpgradeFile",
  "id": 1,
  "params": {"upgradeFileHash":"<64 hexadecimal SHA-256>"}
}
```

The hash covers the complete transferred container. The method validates the
staged file and returns `true` on success. Validation details are documented
in the [OTA protocol](ota_protocol.md).

### ClearAutoConnectList

`ClearAutoConnectList` clears the Bluetooth auto-connect list exposed by the
Bluetooth-parameter test mode. It does not remove the Air11 pairing key.

Request:

```json
{"jsonrpc":"1.0","method":"ClearAutoConnectList","id":1}
```

The `params` member is omitted.

The method is accepted only while `FGState` is `TestMode` and the selected
`testMode` is `BluetoothParameters`. A successful request returns `true`.

### ConfirmKeyExchange

`ConfirmKeyExchange` completes the initial BLE SRP exchange. It verifies the
client proof and returns the device proof, assigned client ID, and first
encrypted-session nonce.

Request:

```json
{
  "jsonrpc": "2.0",
  "method": "ConfirmKeyExchange",
  "id": 1,
  "params": {"clientConfirmation":"<64 hexadecimal SRP proof M1>"}
}
```

Result:

```json
{
  "clientId": "<device-assigned client id>",
  "serverConfirmation": "<64 hexadecimal SRP proof M2>",
  "nonce": "<hexadecimal session nonce>"
}
```

The client must verify `serverConfirmation` before saving `clientId` and the
derived master pair key. See the
[Bluetooth protocol](bluetooth_protocol.md#first-pairing-flow).

### DiscardPairKey

`DiscardPairKey` removes the stored pairing material associated with the
current encrypted BLE client.

Request:

```json
{"jsonrpc":"1.0","method":"DiscardPairKey","id":1}
```

The `params` member is omitted.

A successful request returns a boolean success value.

### EnableSecurity

`EnableSecurity` records a retained service request for the lower security
path. The application handler itself does not change live RPC or BLE
permissions.

Request:

```json
{"jsonrpc":"1.0","method":"EnableSecurity","id":1}
```

The `params` member is omitted.

The method is accepted only when the active software-identification record has
passed the firmware validity check. It then stores the retained request marker
`0xA1C01075` in the fatal-error state. The APPL handler does not directly
change BLE, RPC, or runtime security permissions. The success result shape and
the lower-level consumer of the retained marker have not been identified.

### EnterLearnTargets

`EnterLearnTargets` requests the flow generator's learn-targets operating
state.

Request:

```json
{"jsonrpc":"1.0","method":"EnterLearnTargets","id":1}
```

The `params` member is omitted.

The result contains the accepted `FGState`. The state transition continues
asynchronously after the RPC response.

### EnterMaskFit

`EnterMaskFit` requests mask-fit operating state at the supplied test
pressure.

Request:

```json
{
  "jsonrpc": "2.0",
  "method": "EnterMaskFit",
  "id": 1,
  "params": {"maskFitPressure":10.0}
}
```

`maskFitPressure` is a number in `cmH2O`. The native client normally requests
`10.0`.

Result:

```json
{"FGState":"MaskFit","maskFitPressure":10.0}
```

### EnterStandby

`EnterStandby` requests transition of the flow generator into standby.

Request:

```json
{"jsonrpc":"1.0","method":"EnterStandby","id":1}
```

The `params` member is omitted.

The result contains the accepted `FGState`. A successful result means that the
request was accepted; activity events report the subsequent state transition.

### EnterTest

`EnterTest` enters, selects, or leaves a manufacturing or diagnostic test
mode. Available modes cover sensors, outputs, storage, security, Bluetooth,
climate, and blower-control paths.

Request:

```json
{
  "jsonrpc": "1.0",
  "method": "EnterTest",
  "id": 1,
  "params": {"testMode":"PressureControl"}
}
```

`testMode` accepts these symbols:

| Value | Test path |
|-------|-----------|
| `Off` | leave the selected test mode |
| `PressureControl` | pressure-control test |
| `AmbientSensors` | ambient-sensor test |
| `ButtonTest` | button-input test |
| `LedTest` | LED-output test |
| `StorageSflash` | serial-flash storage test |
| `EraseMedia` | media erase test |
| `SpeedControl` | blower-speed control test |
| `FlowControl` | flow-control test |
| `BluetoothTest` | Bluetooth test |
| `SecurityData` | security-data test |
| `BluetoothParameters` | Bluetooth-parameter test |
| `ClimateControl` | climate-control test |
| `SdCard` | SD-card test |
| `SoundCheck` | acoustic diagnostic |

The normal result contains `FGState` and `testMode`. `EraseMedia` also returns
`timeToFinish`, an estimated duration in seconds. The handler is gated by
manufacturing and service state.

### EnterTestDrive

`EnterTestDrive` requests the test-drive operating state.

Request:

```json
{"jsonrpc":"1.0","method":"EnterTestDrive","id":1}
```

The `params` member is omitted.

The result contains the accepted `FGState`. The method is available on the
encrypted BLE service path in the stock permission table.

### EnterTherapy

`EnterTherapy` requests transition of the flow generator into therapy.

Request:

```json
{"jsonrpc":"1.0","method":"EnterTherapy","id":1}
```

The `params` member is omitted.

The result contains the accepted `FGState`. Therapy startup continues
asynchronously after the response.

### EraseData

`EraseData` starts asynchronous erasure of selected persistent data classes.
It can erase sleep data, settings, logs, or any combination of those classes.

Request:

```json
{
  "jsonrpc": "1.0",
  "method": "EraseData",
  "id": 1,
  "params": {
    "eraseMethod": "full",
    "dataTypes": ["SleepData", "Settings", "Logs"]
  }
}
```

| Field | Requirement |
|-------|-------------|
| `eraseMethod` | literal string `full` |
| `dataTypes` | non-empty array containing each selected value at most once |

`dataTypes` accepts:

| Value | Data erased |
|-------|-------------|
| `SleepData` | recorded therapy, compliance, and sleep data |
| `Settings` | persistent settings; reset to firmware defaults |
| `Logs` | persistent diagnostic, exception, and activity logs |

The method operates on only the selected classes. `full` is the erase method
name, not a request to erase firmware or the entire flash device.

Result:

```json
{
  "results": true,
  "eraseMethod": "full",
  "dataTypes": ["SleepData", "Settings", "Logs"]
}
```

The request requires standby. Erasure is asynchronous; the result acknowledges
the request rather than proving that every backend has finished.

### GenerateAuthCode

`GenerateAuthCode` computes an HMAC-SHA256 over caller-supplied bytes using a
32-byte entry selected from the firmware key-provider interface.

Request:

```json
{
  "jsonrpc": "1.1",
  "method": "GenerateAuthCode",
  "id": 1,
  "params": {
    "nonce": "<hexadecimal input>",
    "keyLocation": 3,
    "algorithm": "HMAC_SHA256"
  }
}
```

| Field | Requirement |
|-------|-------------|
| `nonce` | 64 through 1024 hexadecimal characters; length must be even |
| `keyLocation` | integer key-provider offset `0..255`; selects a 32-byte key, wrapping at offset `0x100` |
| `algorithm` | literal string `HMAC_SHA256` |

Result:

```json
{"authCode":"<64 hexadecimal HMAC-SHA256>"}
```

### Get

`Get` reads the current JSON representation of one or more named data-model
items. A selector can resolve to a scalar DataItem, a complete object subtree,
or a value produced by a dedicated formatter. The method does not return raw
descriptor storage: enum values can be represented by symbolic strings and
aggregate selectors produce nested JSON objects.

Request:

```json
{
  "jsonrpc": "1.0",
  "method": "Get",
  "id": 1,
  "params": ["ActiveTherapyProfile", "VAutoProfile"]
}
```

The `params` member must be a non-empty array of non-empty strings. Names are
case-sensitive. Each selector is resolved independently and the result object
uses the requested string as its key. A different parameter shape, an empty
array, or an empty selector returns `-32602 Invalid Params`.

Accepted name forms are:

| Form | Example | Result |
|------|---------|--------|
| long data-item name | `Language`, `ActiveTherapyProfile` | one value |
| underscored short tag | `_LAN`, `_MOP` | the same data item through its short tag |
| named object selector | `TherapyProfiles`, `VAutoProfile` | one object subtree |

Firmware first applies an exact object-alias lookup, then tries the registered
DataItem, schema-object, configuration, and dedicated formatter families. A
dotted path is accepted only when that complete string has a firmware alias;
arbitrary traversal such as `TherapyProfiles.VAutoProfile` is not supported.
To read one child object, request its registered name directly, for example
`VAutoProfile`.

Example result:

```json
{
  "ActiveTherapyProfile": "VAutoProfile",
  "VAutoProfile": {
    "TherapyMode": "VAuto",
    "MaxInspiratoryPressure": 25.0,
    "MinExpiratoryPressure": 4.0,
    "StartPressure": 4.0,
    "SetPressureSupport": 4.0,
    "TriggerSensitivity": "Medium",
    "CycleSensitivity": "Medium"
  }
}
```

For a DataItem selector, recognition of the name does not guarantee that a
value is currently available. Its descriptor must permit RPC reads and be
active, its producer must have supplied a value, and its runtime suppress flag
must be clear. A selector can therefore return `InvalidObject` on one product
variant or in one device state while succeeding elsewhere.

For a named object selector, firmware serializes the currently exposed child
nodes. Product configuration and RPC visibility flags can change the contents
of that object. `TherapyProfiles`, for example, returns therapy profile
objects; it does not identify the selected profile. Read
`ActiveTherapyProfile` or `_MOP` for the current selection.

If every selector resolves and has a value, `result` contains one member per
requested selector. If only part of the request succeeds, firmware returns
`-11201 InvalidObject`; its `data` member retains successful values and lists
the failed selectors in `InvalidObjects`:

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "error": {
    "code": -11201,
    "message": "InvalidObject",
    "data": {
      "ActiveTherapyProfile": "VAutoProfile",
      "InvalidObjects": ["NoSuchObject"]
    }
  }
}
```

Accepted DataItem names, object selectors, runtime availability rules, and
technical input forms are documented in the
[Get input reference](rpc_get_inputs.md).

The maintained object-selector list is available offline:

```console
python3 python/as11_config.py known vars subtrees
```

Known leaf names, short tags, ranges, and enum options are listed in the
[variable reference](var_reference.tsv). The [`as11_config.py`
reference](../tools/as11_config.md) describes the offline `known` catalog, and
the [`as11_descriptors.py` reference](../tools/as11_descriptors.md) describes
how to inspect the data model of a particular firmware image.

### GetDateTime

`GetDateTime` reads the current device date and time as an ISO 8601 timestamp.

Request:

```json
{"jsonrpc":"1.0","method":"GetDateTime","id":1}
```

The `params` member is omitted.

Result:

```json
{"dateTime":"2026-08-12T14:25:31.000Z"}
```

### GetLedStatus

`GetLedStatus` reads the current output state of the power LEDs, SD-card LED,
and LCD backlight.

Request:

```json
{"jsonrpc":"1.0","method":"GetLedStatus","id":1}
```

The `params` member is omitted.

The result has four output members:

| Member | Fields |
|--------|--------|
| `PowerWhite` | `intensityPercentage`, `status` |
| `PowerGreen` | `intensityPercentage`, `status` |
| `SdCardBlue` | `intensityPercentage`, `status` |
| `LcdBacklight` | `intensityPercentage`, `status` |

Both fields are numeric. This method reads current output state.

### GetRtcAndSystemClocks

`GetRtcAndSystemClocks` reads the wall-clock RTC and the current
high-resolution system clock in one response.

Request:

```json
{"jsonrpc":"1.0","method":"GetRtcAndSystemClocks","id":1}
```

The `params` member is omitted.

Result:

```json
{
  "RtcTime": "2026-08-12T14:25:31.000Z",
  "HighResTime": 123456789
}
```

`HighResTime` is the current 32-bit high-resolution system clock, not an
absolute timestamp.

### GetVersion

`GetVersion` returns identification profiles for the available device modules
and the RPC capability map visible on the current channel.

Request:

```json
{"jsonrpc":"2.0","method":"GetVersion","id":1}
```

The `params` member is omitted.

The result contains abbreviated identification profiles for the installed
modules and the RPC capabilities visible on the current channel. The RPC map
in this example is shortened:

```json
{
  "FlowGenerator": {
    "IdentificationProfiles": {
      "Software": {
        "ApplicationIdentifier": "SW04600.15.8.4.0.791777c3b",
        "BootloaderIdentifier": "SW04601.00.1.1.0.736edbdfd",
        "ConfigurationIdentifier": "CF04600.15.03.00.791777c3b",
        "DataModelVersionIdentifier": "v2.15.2.7fc2c6467"
      },
      "Hardware": {
        "HardwareIdentifier": "(90)...(91)...(21)..."
      },
      "Product": {
        "UniversalIdentifier": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
      }
    },
    "RPC": {
      "GetVersion": "2.0",
      "Get": "1.0",
      "Set": "1.0"
    }
  },
  "BluetoothModule": {
    "IdentificationProfiles": {
      "Software": {
        "ApplicationIdentifier": "ST290.2.12.3.151.5"
      },
      "Hardware": {
        "HardwareIdentifier": "(90)...(91)...(21)..."
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
        "HardwareIdentifier": "(90)...(91)...(21)..."
      },
      "Software": {
        "ApplicationIdentifier": "SW04600.15.8.4.0.791777c3b"
      }
    }
  }
}
```

`BluetoothModule`, `CellularModule`, and `AlarmModule` are present only when
the corresponding module profile is available. The cellular profile can also
contain its modem identification under
`CellularProfile.Equipment.Software.ApplicationIdentifier`.

Use [`Get`](#get) with `IdentificationProfiles` for the complete flow-generator
profile, including serial number, product code and name, platform and variant
identifiers, and the remaining software identifiers.

`FlowGenerator.RPC` maps advertised method names to request contract versions.
It is channel-specific and is not an inventory of every name in the firmware
method table. In particular, service diagnostics can have permission entries
without appearing in this map.

### InitiateUpgrade

`InitiateUpgrade` creates the staging session for an upgrade container and
returns the maximum raw block size accepted by that session.

Request:

```json
{
  "jsonrpc": "1.0",
  "method": "InitiateUpgrade",
  "id": 1,
  "params": {"upgradeFileSize":1966256}
}
```

`upgradeFileSize` is the exact container size in bytes.

Result:

```json
{"xferBlockSize":500}
```

`xferBlockSize` is the maximum raw payload accepted by each subsequent
[`UpgradeDataBlock`](#upgradedatablock) request.

### InjectLoggedEvent

`InjectLoggedEvent` submits a numeric event code to one selected diagnostic,
activity, cellular, calibration, or alarm log family.

Request:

```json
{
  "jsonrpc": "1.0",
  "method": "InjectLoggedEvent",
  "id": 1,
  "params": {"EventType":"ApplicationError","EventCode":11551}
}
```

`EventCode` is an unsigned 16-bit integer. `EventType` accepts:

```text
ApplicationError
FrequentActivityEvent
SporadicActivityEvent
CellularActivityEvent
CALSystemError
AlarmApplicationError
```

`ApplicationError`, `CALSystemError`, and `AlarmApplicationError` retain the
full 16-bit event code. Frequent, sporadic, and cellular activity events use
only its low byte. A successful request returns `true`.

### InsertSdCard

`InsertSdCard` populates the service SD-card proxy used by diagnostic paths.

Request:

```json
{
  "jsonrpc": "1.0",
  "method": "InsertSdCard",
  "id": 1,
  "params": {
    "writeProtected": 0,
    "size": 1073741824,
    "error": 0,
    "pendingError": 0
  }
}
```

All four parameters are required integers:

| Field | Meaning |
|-------|---------|
| `writeProtected` | `0` reports writable media; any other value reports write-protected media |
| `size` | media capacity in bytes; reported block count is `size / 512`, rounded down |
| `error` | `0` clears the current error flag; any other value sets it |
| `pendingError` | pending-error code; the proxy uses its low 16 bits |

A successful request returns `true`. The proxy is separate from the physical
SD-card driver's insertion and mount state.

<a id="spool-rpc"></a>

### PullSpoolFragments

`PullSpoolFragments` advances an open spool reader and requests that stored
payload data be emitted as `SpoolFragment` notifications.

Request:

```json
{
  "jsonrpc": "1.0",
  "method": "PullSpoolFragments",
  "id": 1,
  "params": {
    "spoolId": 12,
    "maxFragmentSize": 3000,
    "maxNotifications": 0
  }
}
```

| Field | Requirement |
|-------|-------------|
| `spoolId` | ID returned by `StartSpool` |
| `maxFragmentSize` | positive maximum raw bytes in one fragment notification; firmware clamps values above `3576` bytes |
| `maxNotifications` | non-negative notification count; `0` removes the count limit for this pull |

All three fields are required and parsed as integers. A positive
`maxNotifications` value pauses delivery after that many notifications; call
`PullSpoolFragments` again with the same active `spoolId` to continue.
The immediate result echoes the active spool ID:

```json
{"spoolId":12}
```

Payload data arrives in `SpoolFragment` notifications. The request advances
the active spool reader.

See [`StartSpool`](#startspool) and the
[RPC spool reference](rpc_spools.md).

### RemoveSdCard

`RemoveSdCard` clears the service SD-card proxy populated by
[`InsertSdCard`](#insertsdcard).

Request:

```json
{"jsonrpc":"1.0","method":"RemoveSdCard","id":1}
```

The `params` member is omitted.

A successful request returns `true`. The method does not directly command the
physical SD driver to unmount media.

### RequestSession

`RequestSession` starts BLE reconnection authentication for a previously
paired client and returns a fresh challenge and session nonce.

Request:

```json
{
  "jsonrpc": "2.0",
  "method": "RequestSession",
  "id": 1,
  "params": {"clientId":"<saved client id>"}
}
```

Result:

```json
{"challenge":"<hexadecimal challenge>","nonce":"<hexadecimal nonce>"}
```

The client proves possession of the stored master pair key with
[`CheckSessionIntegrity`](#checksessionintegrity). See the
[Bluetooth protocol](bluetooth_protocol.md#reconnection-flow).

### ResetDevice

`ResetDevice` restarts the device. The `type` parameter selects how the final
processor reset is triggered after firmware shuts down peripherals and commits
its shutdown state.

Request:

```json
{
  "jsonrpc": "1.0",
  "method": "ResetDevice",
  "id": 1,
  "params": {"type":"TriggerWatchdog"}
}
```

`type` is a symbolic enum:

| Value | Raw | Reset path |
|-------|----:|------------|
| `Off` | 0 | no restart |
| `TriggerWatchdog` | 1 | stop servicing the hardware watchdog and wait for its reset |
| `Fast` | 3 | request an immediate NVIC system reset after shutdown |
| `TriggerPowerLoss` | 4 | drive `PH8` low and enter STOP mode after shutdown |

The parser accepts these exact symbolic values; numeric values and other enum
labels return `Invalid Params`.

### Set

`Set` writes one or more named DataItems through their normal firmware
validation and application callbacks.

Request:

```json
{
  "jsonrpc": "1.0",
  "method": "Set",
  "id": 1,
  "params": {"RampEnable":"Auto","RampTime":20}
}
```

The `params` member is one object containing one or more setting names and
values.

The JSON type is part of each setting's contract. Numeric fields take JSON
numbers, fields defined as booleans take JSON booleans, and enum fields
normally take their symbolic string labels.

Therapy-profile fields use mode-prefixed write names. For example, the
`MaxInspiratoryPressure` member of `VAutoProfile` is written as
`VAuto-MaxInspiratoryPressure`. Feature-profile fields generally use the
field name exposed in the feature object, such as `RampEnable` or `EprEnable`.
Underscored short aliases can also be writable when exported by the RPC data
model.

The result echoes accepted values. A multi-key request is not transactional:
earlier keys can be applied before a later key fails. Descriptor visibility or
editability does not bypass the setting's runtime mode, range, state, and
application callbacks.

```json
{"RampEnable":"Auto","RampTime":20}
```

### SetDateTime

`SetDateTime` immediately sets the device date and time from an ISO 8601
timestamp.

Request:

```json
{
  "jsonrpc": "1.1",
  "method": "SetDateTime",
  "id": 1,
  "params": {"dateTime":"2026-08-12T14:25:31.000Z"}
}
```

The result contains the accepted `dateTime` value. When writing the RTC, the
firmware discards the fractional-second part of the timestamp and sets the
clock at whole-second resolution.

### SetNextPowerUpDateTime

`SetNextPowerUpDateTime` stores a one-shot RTC value that early application
startup applies after the next reset or power cycle.

Request:

```json
{
  "jsonrpc": "1.0",
  "method": "SetNextPowerUpDateTime",
  "id": 1,
  "params": {"value":"2026-08-13T06:30:00.000Z"}
}
```

Early firmware initialization consumes the saved value after applying it. The
method does not schedule or power on the device. A successful request returns
`true`.

### StartKeyExchange

`StartKeyExchange` begins initial BLE pairing by accepting the client's SRP
public value and returning the device public value and salt.

Request:

```json
{
  "jsonrpc": "2.0",
  "method": "StartKeyExchange",
  "id": 1,
  "params": {"clientPk":"<512 hexadecimal characters>"}
}
```

`clientPk` is the 256-byte SRP public value `A`, serialized big-endian.

Result:

```json
{
  "serverPk": "<512 hexadecimal characters>",
  "salt": "<hexadecimal salt>"
}
```

Continue with [`ConfirmKeyExchange`](#confirmkeyexchange). The full SRP
variant is documented in the
[Bluetooth protocol](bluetooth_protocol.md#first-pairing-flow).

### StartSpool

`StartSpool` opens a stored-data spool at the requested address and returns an
ID for subsequent fragment pulls.

Request:

```json
{
  "jsonrpc": "1.0",
  "method": "StartSpool",
  "id": 1,
  "params": {
    "spoolAddress": {
      "Summary": {
        "fromDateTime": "2026-04-29T00:00:00.000Z"
      }
    },
    "maxSpoolSize": 4096
  }
}
```

| Field | Requirement |
|-------|-------------|
| `spoolAddress` | object whose member name selects the spool type |
| `spoolAddress.<type>.fromDateTime` | optional ISO 8601 starting timestamp; records before this time are skipped |
| `maxSpoolSize` | round-wide limit for unencoded payload bytes; parsed as a positive signed 32-bit integer |

One `StartSpool` request selects one spool type. If `spoolAddress` contains
multiple members, the parser retains only the last member. When
`fromDateTime` is omitted, the selected spool reader uses its default starting
position. `maxSpoolSize` limits the complete round, while
`PullSpoolFragments.maxFragmentSize` limits each fragment notification.

Result:

```json
{"spoolId":12}
```

Use the returned ID with [`PullSpoolFragments`](#pullspoolfragments). Known
spool names and record formats are documented in the
[RPC spool reference](rpc_spools.md).

<a id="stream-rpc"></a>

### StartStream

`StartStream` creates a live periodic data stream for one or more DataItems.
Samples are delivered asynchronously in `StreamData` notifications.

Request:

```json
{
  "jsonrpc": "1.0",
  "method": "StartStream",
  "id": 1,
  "params": {
    "dataIds": ["PatientFlow", "MaskPressure"],
    "sampleIntervalMs": 40,
    "reportIntervalMs": 200
  }
}
```

| Field | Type | Constraint |
|-------|------|------------|
| `dataIds` | array of strings | 1 through 30 entries |
| `sampleIntervalMs` | integer | 10 through 65000 ms |
| `reportIntervalMs` | integer | 10 through 300000 ms and at most `sampleIntervalMs * 5` |

Intervals are quantized to 10 ms. One `sampleIntervalMs` applies to every data
ID in the stream. Requesting a slowly updated source at a shorter interval
repeats its current value; it does not increase the source resolution.

Result:

```json
{
  "streamId": 12,
  "dataIds": [
    {"dataId":"PatientFlow","valid":true},
    {"dataId":"MaskPressure","valid":true}
  ]
}
```

Samples arrive in `StreamData` notifications. Missing values are JSON `null`.
There is no `StopStream` method; streams end with the RPC connection. Known
data IDs and EDF-oriented aliases are documented in the
[RPC stream reference](rpc_streams.md).

### StoreSecurityData

`StoreSecurityData` verifies and stores a complete 512-byte service security
object, then reads it back and verifies it again.

Request:

```json
{
  "jsonrpc": "1.0",
  "method": "StoreSecurityData",
  "id": 1,
  "params": {
    "verifier": "<64 hexadecimal SHA-256 digest>",
    "data": "<1024 hexadecimal characters>"
  }
}
```

`data` encodes the complete 512-byte security-data object. `verifier` is the
SHA-256 digest of those decoded bytes. The firmware verifies the supplied
digest, writes the object, reads it back, and verifies the digest again. A
successful request returns `true`.

<a id="event-rpc"></a>

### SubscribeEvent

`SubscribeEvent` subscribes the current RPC connection to one or more live
event-family selectors or ordinary DataItems.

Request:

```json
{
  "jsonrpc": "1.0",
  "method": "SubscribeEvent",
  "id": 1,
  "params": {
    "dataIds": [
      "TherapyEvents-RespiratoryEvents",
      "_ROP"
    ]
  }
}
```

Result:

```json
{
  "subscriptionId": 7,
  "dataIds": [
    {"dataId":"TherapyEvents-RespiratoryEvents","valid":true},
    {"dataId":"_ROP","valid":true}
  ]
}
```

Event-family selectors produce the records documented in the
[RPC event reference](rpc_events.md). A DataItem subscription immediately
reports its current value and then reports subsequent changes as
`event: "ValueChange"`. Enum values use their symbolic label; other values are
reported as raw integers rather than with the scaling and formatting applied
by [`Get`](#get).

Volatile-text DataItems cannot be subscribed. There is no unsubscribe method;
subscriptions belong to the current RPC connection and end with it.

### UpgradeDataBlock

`UpgradeDataBlock` writes one block of hexadecimal container data into the
active upgrade staging session.

Request:

```json
{
  "jsonrpc": "1.0",
  "method": "UpgradeDataBlock",
  "id": 1,
  "params": {
    "fileOffset": 0,
    "encoding": "AsciiHex",
    "data": "<hexadecimal container bytes>"
  }
}
```

`fileOffset` is a byte offset in the original container. After hexadecimal
decoding, `data` must contain no more than the `xferBlockSize` returned by
[`InitiateUpgrade`](#initiateupgrade). `encoding` accepts the literal
`AsciiHex`. A successful block returns `true`.

### VerifySecurityData

`VerifySecurityData` verifies the SHA-256 digest of the stored 512-byte service
security object.

Request:

```json
{
  "jsonrpc": "1.0",
  "method": "VerifySecurityData",
  "id": 1,
  "params": {"verifier":"<64 hexadecimal SHA-256 digest>"}
}
```

The firmware reads the stored 512-byte security-data object, computes its
SHA-256 digest, and returns `true` when it matches `verifier`.

## Notifications

Device-initiated messages have a `method` and no `id`. They use
`jsonrpc: "2.0"` and can arrive while a request is waiting for its response.

| Method | Source | Payload |
|--------|--------|---------|
| `HeartBeat` | active RPC session | no application payload |
| `EventNotification` | `SubscribeEvent` | subscription ID, selector, event records |
| `StreamData` | `StartStream` | stream ID, start time, interval, sample arrays |
| `SpoolFragment` | `PullSpoolFragments` | spool ID, sequence, encoded data, status, terminal metadata |

### EventNotification

```json
{
  "jsonrpc": "2.0",
  "method": "EventNotification",
  "params": {
    "subscriptionId": 7,
    "dataId": "TherapyEvents-RespiratoryEvents",
    "events": [
      {
        "reportTime": "2026-06-12T11:47:49.765Z",
        "event": "ObstructiveApneaEnd",
        "durationSeconds": 15
      }
    ]
  }
}
```

Event fields depend on the selector and event type.

For a subscribed DataItem:

```json
{
  "jsonrpc": "2.0",
  "method": "EventNotification",
  "params": {
    "subscriptionId": 4,
    "dataId": "_ROP",
    "events": [
      {
        "reportTime": "2026-08-13T23:47:46.289Z",
        "event": "ValueChange",
        "value": 1
      }
    ]
  }
}
```

### StreamData

```json
{
  "jsonrpc": "2.0",
  "method": "StreamData",
  "params": {
    "data": [
      {"PatientFlow":[0.24,0.19,0.15,0.11,0.06]},
      {"MaskPressure":[12.4,12.4,12.1,11.9,11.5]}
    ],
    "intervalMs": 40,
    "startTime": "2026-06-13T11:16:01.105Z",
    "streamId": 12
  }
}
```

### SpoolFragment

```json
{
  "jsonrpc": "2.0",
  "method": "SpoolFragment",
  "params": {
    "spoolId": 12,
    "seq": 0,
    "data": "<base64>",
    "status": "SPOOL_COMPLETE_MORE_DATA_PENDING",
    "spoolHash": "<SHA-256 of concatenated raw data>",
    "nextSpoolAddress": {
      "Summary": {
        "fromDateTime": "2026-04-29T11:00:00.000Z"
      }
    }
  }
}
```

| Status | Meaning |
|--------|---------|
| `SPOOL_INCOMPLETE` | more fragments are expected in this round |
| `SPOOL_COMPLETE_MORE_DATA_PENDING` | this round is complete; continue from `nextSpoolAddress` |
| `SPOOL_COMPLETE_NO_MORE_DATA` | this round is complete and no continuation remains |
| `ERROR_DATA_UNAVAILABLE` | requested spool data is unavailable |

`data` is Base64 text. Data-bearing `seq` values start at zero for each round
and increase without gaps. `spoolHash` appears on the terminal fragment and
covers the concatenated decoded `data` bytes for that round. A terminal
fragment for an empty round can contain no `data`.

<a id="rpc-permission-selectors"></a>

## Permission channels

The firmware permission table is keyed by the even VCID used for
device-to-host responses. The adjacent odd VCID carries host-to-device
requests.

| Permission VCID | Request VCID | Buffer | Channel role |
|-----------------|--------------|-------:|--------------|
| `0x0380` | `0x0381` | 600 | CAN small RPC |
| `0x0382` | `0x0383` | 7650 | CAN large/service RPC |
| `0x0390` | `0x0391` | 600 | BLE plaintext small RPC |
| `0x0392` | `0x0393` | 7650 | BLE plaintext large pairing/session RPC |
| `0x0394` | `0x0395` | 632 | BLE encrypted small RPC |
| `0x0396` | `0x0397` | 7682 | BLE encrypted large application RPC |
| `0x0398` | unknown | unknown | permission selector without a matching endpoint-catalog row |
| `0x0780` | `0x0781` | 1024 | internal/cellular small RPC |
| `0x0788` | `0x0789` | 7650 | internal/cellular large RPC |

The stock access names used in the method index expand to:

| Access set | Permission VCIDs |
|------------|------------------|
| all | `0x0380`, `0x0382`, `0x0390`, `0x0392`, `0x0394`, `0x0396`, `0x0398`, `0x0780`, `0x0788` |
| application | `0x0380`, `0x0382`, `0x0394`, `0x0396`, `0x0398`, `0x0780`, `0x0788` |
| service | `0x0380`, `0x0382`, `0x0780`, `0x0788` |
| BLE plaintext | `0x0390`, `0x0392` |
| BLE encrypted | `0x0394`, `0x0396`, `0x0398` |

A permission bit controls whether the dispatcher accepts a method from that
channel. Method-specific parameter, state, hardware, and authentication gates
still apply.

## Error codes

Standard JSON-RPC errors:

| Code | Message | Meaning |
|------|---------|---------|
| `-32700` | `Parse Error` | malformed JSON payload |
| `-32600` | `Invalid Request` | valid JSON but invalid RPC request object |
| `-32601` | `Method Not Found` | unknown method or method unavailable on the selected channel |
| `-32602` | `Invalid Params` | missing, malformed, or unsupported parameters |
| `-32603` | `Internal Error` | method failed without a more specific application error |

Common Air11 application errors:

| Code | Message | Meaning |
|------|---------|---------|
| `-11201` | `InvalidObject` | one or more requested data-model objects are unavailable |
| `-11202` | `SettingApplicationFailure` | a setting was parsed but rejected while being applied |
| `-11303` | `UpgradeFileIsTooLarge` | proposed upgrade file exceeds the accepted size |
| `-11305` | `UpgradeFileIntegrityFailure` | upgrade hash, descriptor, or embedded integrity verification failed |
| `-11306` | `UpgradeFileAuthenticationFailure` | authenticated-upgrade HMAC verification failed |
| `-11308` | `UpgradeFileIncompatible` | component, target, or compatibility checks rejected the container |
| `-11309` | `UpgradeFileInvalid` | upgrade container structure is invalid |

The optional error `data` object is method-specific. `Get` can return valid
values alongside `InvalidObjects`; `Set` can return current or partially
applied values after `SettingApplicationFailure`.

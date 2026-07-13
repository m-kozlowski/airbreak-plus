# AS11 Power Supply Detection

AS11 derives the connected supply capacity and source type from a 16-byte
DatagramCan message received on CAN ID `0x259`.

## Contents

- [CAN endpoint](#can-endpoint)
- [Identification payload](#identification-payload)
- [Example payloads](#example-payloads)
- [Detection lifecycle](#detection-lifecycle)
- [Runtime effects](#runtime-effects)

## CAN endpoint

| Property | Value |
|----------|-------|
| CAN ID | `0x259`, supply-side accessory to AS11 |
| Internal endpoint code | `0x0e` |
| Payload size | 16 bytes |

See [Physical bus](can_protocol.md#physical-bus) for common CAN parameters and
[DatagramCan frame format](can_protocol.md#datagramcan-frame-format) for
fragmentation and CRC handling.

## Identification payload

Only two bytes affect power-supply classification:

| Offset | Value | Effect |
|--------|-------|--------|
| `0` | `0x00` | Set `_PSC` to `PowerSupply90W` and `_PSD` to `Yes` |
| `0` | any other value | Do not change capacity |
| `6` | `0x00` | Set `_PSU` to `AcMains` |
| `6` | `0x01` | Set `_PSU` to `DcMains` |
| `6` | any other value | Do not change source type |

The two tests are independent. A nonzero byte 0 is not a positive 65 W
identification; it only leaves `_PSC` unchanged. Bytes 6 equal to `0x00` or
`0x01` update `_PSU` regardless of byte 0.

The other 14 bytes do not affect power-supply classification.

## Example payloads

A valid 90 W AC payload is all zeroes:

```text
00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00
```

Its CRC32 is `0xECBB4B55`, encoded in the DatagramCan start frame as
`55 4B BB EC`.

A valid 90 W DC payload differs at byte 6:

```text
00 00 00 00 00 00 01 00 00 00 00 00 00 00 00 00
```

Its CRC32 is `0x0379206B`, encoded in the DatagramCan start frame as
`6B 20 79 03`.

A received payload never selects `PowerSupply65W`. It is the default and
timeout result.

## Detection lifecycle

At detector initialization, the relevant defaults are:

| Variable | Default |
|----------|---------|
| `_PSC` (`PowerSupplyCapacity`) | `PowerSupply65W` |
| `_PSU` (`PowerSupplyType`) | `Unknown` |
| `_PSD` | `No` |

The firmware opens CAN ID `0x259`, polls for complete DatagramCan messages, and
classifies each 16-byte payload. The first recognized AC or DC source type emits
`PowerSupplyACMains90W` or `PowerSupplyDCMains90W`, respectively.

After 3000 ms, if `_PSC` is still `PowerSupply65W`, the detector emits
`PowerSupply65W` and sets `_PSD` to `Yes`. This is a fallback timer, not a
received 65 W identification.

A later valid 90 W payload still updates `_PSC`, `_PSD`, and `_PSU`. It does not
clear an insufficient-supply warning that has already been latched.

The event names are also listed in [RPC events](rpc_events.md).

## Runtime effects

| Variable | Role |
|----------|------|
| `_PSC` (`PowerSupplyCapacity`) | Runtime capacity: `PowerSupply90W` or `PowerSupply65W` |
| `_PSU` (`PowerSupplyType`) | Runtime source: `Unknown`, `AcMains`, or `DcMains` |
| `_PSD` | Detection or fallback has completed |
| `_P90` | Product configuration requires a 90 W supply |
| `_SCL` | Lower-controller parameter derived from `_PSC` and `_TXC` |

The insufficient-supply warning requires all three conditions:

```text
_PSD == Yes
_PSC == PowerSupply65W
_P90 == Yes
```

`_P90` is product configuration and is not written by the detector.

`_SCL` is selected from `_PSC`:

| Capacity | `_SCL` |
|----------|--------|
| `PowerSupply65W` | `2625` |
| `PowerSupply90W` | `3638` |

The firmware subtracts `208` while `_TXC` (`TxLink2Connected`) is any value
other than `No`, then forwards `_SCL` to the lower controller.

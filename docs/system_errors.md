# Air 10 System Errors

The LCD shows a system error as a three-digit code derived from two bitmask
variables:

| Variable | Valid bits | Displayed code | Stored stream |
|----------|------------|----------------|---------------|
| `SYS` | 0..12 (`0x1FFF`) | Bit index + 1 | `TXE` |
| `SYT` | 0..9 (`0x03FF`) | Bit index + 17 | `TXW` |

The display selects the first set `SYS` bit. If `SYS` is zero, it selects the
first set `SYT` bit. More than one bit can be set, so the display can hide further
errors. [`resmed_config.py errors`](tools/resmed_config.md#errors) reports every
set bit.

Bits 13..15 of `SYS` would display as 014-016. These codes have no assigned
error.

## Shared Errors

Thresholds are in internal numeric units.

| Code | Bit | Recorded condition |
|------|-----|--------------------|
| 001-005 | `SYS` 0-4 | Motor driver fault code 1-5 |
| 006 | `SYS` 5 | Motor driver fault code 6, or software commutation fault |
| 007 | `SYS` 6 | Motor driver fault code 7, or startup feedback outside 1800..2300 |
| 008 | `SYS` 7 | Motor speed too low for the drive command |
| 009 | `SYS` 8 | Repeated motor drive feedback limit condition |
| 010 | `SYS` 9 | Flow reading below valid range: `BFL` <= -334 |
| 011 | `SYS` 10 | High flow at low motor speed: `SPD` < 4500 and `BFL` > 1416 |
| 012 | `SYS` 11 | Flow sensor communication failure count above 1000 |
| 013 | `SYS` 12 | Low, steady flow with negative blower pressure |
| 017 | `SYT` 0 | Settings file failed reading or validation, other than `BGL`/`NGL` |
| 018 | `SYT` 1 | Settings file failed reading or validation, `BGL` or `NGL` |
| 019 | `SYT` 2 | Motor protection interrupt with no nonzero driver fault code |
| 020 | `SYT` 3 | Flow sensor CRC failure count above 100 |

### Motor driver: 001-009, 019

The motor protection interrupt packs GPIOG pins 14, 13, and 12 into bits 0, 1,
and 2 of a driver code. Codes 001-005 report this raw value; firmware assigns no
further meaning to individual codes.

Software checks produce further driver codes. The translation to system errors
is not one-to-one:

| Driver code | Source | System error |
|-------------|--------|--------------|
| 1-7 | Protection interrupt inputs; 7 also from the startup feedback check | 001-007 |
| 8 | Protection interrupt with no nonzero fault code | 019 |
| 9 | Repeated feedback limit condition | 009 |
| 10 | Speed and drive-command check | 008 |

### Flow checks: 010-013

Code 013 examines a window of 100 `BFL` samples, with `abs(BFL)` < 67, a window
range below 34, `TEM` in -5..60, and `BPF` < -100, subject to further activation
conditions.

These codes report that a detection condition was met. They do not identify a
particular failed sensor or an obstruction.

### Settings files: 017, 018

These codes apply to nonempty EEPROM settings files. Failure covers read errors,
an unexpected size, and CRC mismatches, so changing a stored group's definition
can cause 017 on working hardware.
[Custom settings](custom_settings.md#persistence) use a separate group name to
avoid this.

## Saved Restart Errors

Motor and flow faults are written to `ZRE`, which holds `SYS` in its low 16 bits
and `SYT` in its high 16 bits. `ZRE` is restored into both variables when the
saved error matches `RFR` and the restart interval is under 60 seconds.

A changed or non-recent nonzero `ZRE` is copied to `ZSE`, and `RFR` is updated.
The [`ZRL` stream](config_variables.md#g19----eeprom-stream-table) records `ZSE`.

## Lumis Alarm-Board Errors

Codes 021-026 are produced on Lumis devices using the external alarm module,
selected by a nonzero `AOA`. On Air 10, the only direct `SYT` writes are 017 and
018.

| Code | Bit | Recorded condition |
|------|-----|--------------------|
| 021 | `SYT` 4 | Main and alarm-board pressure readings disagree |
| 022 | `SYT` 5 | Alarm-board communication timeout, 20 seconds |
| 023 | `SYT` 6 | Reported module state differs from the requested state |
| 024 | `SYT` 7 | State still differs after a retry, or repeated negative command acknowledgement |
| 025 | `SYT` 8 | Module status `AST` bit `0x0400` |
| 026 | `SYT` 9 | Module status `AST` bit `0x0200` |

### Pressure comparison: 021

Firmware compares two measurement paths: `ZFP`, the filtered main `BPR` reading,
and `APF`, decoded from the module's reply. The error requires:

- `abs(ZFP - APF)` >= 76 and `abs(BFF)` < 1083
- at least 20000 ms since the latest increase of `ARS`, which is updated when
  status bit `0x80` takes the module reinitialization path
- `AOA` equal to 1, and the shared alarm condition framework

### Communication and state: 022-024

A successful transaction resets the communication timer. After 20000 ms without
one, firmware records 022.

Firmware compares the received status bits selected by `0x42` with the requested
state and the active comparison mask. A mismatch of exactly bit `0x02` is retried
once. Any other first mismatch records 023, and a mismatch after the retry records
024. The first negative command acknowledgement keeps the command for one retry,
and the second records 024.

### Module status: 025, 026

The module's status word is stored in `AST`. These codes report its flags and
leave the failed component inside the module unidentified.

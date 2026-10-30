# Air 10 RTC Backup Registers

The STM32 RTC provides twenty 32-bit backup registers, at
`0x40002850 + 4 * index`. They survive ordinary processor resets, so the
bootloader (BLX) and application (CDX) use them to pass state across a reset.

## Register Map

`low16` means that firmware consumes only the low halfword. The application's
halfword write sign-extends its argument and writes the whole register, so
writing `0xFFFF` this way produces `0xFFFFFFFF`.

| Register | Address | Use | Values |
|----------|---------|-----|--------|
| BKP0R | `0x40002850` | No fixed use | |
| BKP1R | `0x40002854` | Firmware update marker | `low16=0x7231`: update completed; cleared after configuration handling |
| BKP2R | `0x40002858` | Power-supply identification result | `4`: ratio accepted; `3`: ratio outside the window |
| BKP3R | `0x4000285C` | CCX/CDX incompatibility request to BLX | `low16=0x5346` (`SF`): enter the firmware-service path |
| BKP4R | `0x40002860` | No fixed use | |
| BKP5R | `0x40002864` | Previous CCX variant ID | `low16`: VID; `0`: initialize; `99`: suppress change detection |
| BKP6R | `0x40002868` | One-shot application boot request | `0x1B183CA7`: enter CDX; replaced by `0x91C1D9AA` at reset |
| BKP7R | `0x4000286C` | Retained BLX status | `low16`: zero for success, otherwise a status code |
| BKP8R | `0x40002870` | RTC initialization marker | Whole word `0x000096E0`: keep the retained RTC configuration |
| BKP9R | `0x40002874` | SD write active at system exit | `low16=1` set at exit; nonzero records `AER` `0x284E` at startup |
| BKP10R | `0x40002878` | Application exit reason or startup stage | Whole word, see [BKP10R](#bkp10r-exit-reason-and-stage) |
| BKP11R | `0x4000287C` | Exception PC | Whole word saved from exception stack frame; `0x7FFFFFFF` is the initialized sentinel |
| BKP12R | `0x40002880` | Shutdown completion and duration | `low16`: `0` cleared; `0xFFFF` started, not completed; positive: duration |
| BKP13R | `0x40002884` | Fatal-error detail | `low16`: see [BKP13R](#bkp13r-fatal-error-detail) |
| BKP14R | `0x40002888` | Pending date | `low16`: days since 1970-01-01; `0x7FFF`: unchanged |
| BKP15R | `0x4000288C` | Pending time | Signed `low16`: minutes relative to noon; `0x7FFF`: unchanged |
| BKP16R | `0x40002890` | Pending date/time integrity | `low16`: CRC-16 of BKP14R and BKP15R |
| BKP17R | `0x40002894` | One-shot `TMD` transport configuration | `low16`: routing and proxy flags |
| BKP18R | `0x40002898` | `ROP` retention | Bits 0..15: `ROP`; bits 16..31: CRC-16 |
| BKP19R | `0x4000289C` | Proxy transport diagnostics | Error flags and two byte counters |

## Boot and Configuration State

### BKP1R: firmware update marker

BLX writes `0x7231` when a completion frame finishes a CCX, CDX, or CMX
transfer, but not a BLX transfer. The marker denotes protocol completion, not an
independent image CRC check.

When `ROP` is not 5, the application responds by reinitializing configuration
groups other than `BGL` and `NGL` and restoring product identity defaults.
Configuration loading then clears the marker.

### BKP2R: power-supply result

BLX identifies the power supply from the ratio of two ADC channels. It collects
35000 samples and compares the averages:

```
0.2233 < average(channel_2) / average(channel_1) < 0.3924
```

Inside this window, BLX writes 4 and the test passes. Outside it, BLX writes 3
and the test fails. A channel 1 sample below `0x8CE` makes BLX take a reset path
before writing a result.

### BKP3R: CCX/CDX compatibility

At scheduler startup, the application compares `PVD` and `MID` from
[CCX g[0]](config_variables.md#g0----device-identity) with the copies at CDX+0x24
and CDX+0x20. If either differs, it writes `0x5346` and stops in an infinite
loop. If both match, it clears the marker.

BLX consumes and clears the marker, then takes the same waiting path as a CCX or
CDX CRC failure. A CRC failure does not set this marker.

### BKP5R: variant change

The application compares the low halfword with the VID in CCX g[0]+8:

| Stored value | Result |
|--------------|--------|
| `0` | Initialize from CCX; no change reported |
| Current VID | No change |
| `99` | Comparison suppressed; value kept |
| Any other value | Replaced with the current VID; change reported |

A reported change selects the initial compliance-reset state and sets `REM`. The
comparison reads the VID stored in CCX, not a runtime value set by VID spoofing.

### BKP6R and BKP7R: boot gate and status

`0x1B183CA7` is the fast path to CDX. At reset, BLX reads BKP6R, replaces it with
`0x91C1D9AA`, and enters CDX only if it read that value. A successful BLX reset
sets it.

BLX loads BKP7R as its status. Its timeout path allows a fast application boot
only when the status is zero and either no firmware-service condition is active
or flashing has completed. Otherwise it performs an ordinary reset and returns
to BLX. A retained nonzero BKP7R can therefore keep the device in this loop even
after CCX and CDX have been restored and their CRCs are valid.

Status codes are listed under [Flash Data Protocol](serial_protocol.md#flash-data-protocol).
`0x7016` is recorded only when the previous status was zero. A BLX self-CRC
failure loops before BKP7R is loaded.

### BKP8R: RTC marker

If the whole word equals `0x96E0`, the application keeps the retained RTC
configuration. Otherwise it sets the clock to 2008-01-01 00:00:00 and writes the
marker.

## Exit and Startup Diagnostics

Startup replaces several of these values, so registers read after startup may
hold new markers. The values below reach the
[stored streams](config_variables.md#g19----eeprom-stream-table): `AER` in `ERR`,
`ELV` in `ELI`, and `FAT` in `ABR`. Record timestamps belong to the startup that
processed a value, not to the original failure. Read the streams with
[`resmed_config.py errors`](tools/resmed_config.md#errors).

### Startup sequence

Scheduler startup handles the registers in this order:

1. Copy the signed low halfword of BKP12R to `ZPT`.
2. Record `AER` `0x284D` if BKP12R is `0xFFFF`.
3. Process BKP10R and BKP11R only if BKP12R is zero or `0xFFFF`. Any other value
   means the previous shutdown completed, and this step is skipped.
4. Clear BKP12R, set BKP10R to 7, and reset BKP11R to `0x7FFFFFFF`.
5. Check and clear BKP9R.

BKP10R must therefore be interpreted together with BKP12R.

### BKP9R: SD write at exit

The exit path sets this register to 1 if the local or proxy SD backend is still
writing. The next startup records `AER` `0x284E` for any nonzero low halfword,
then clears it.

### BKP10R: exit reason and stage

| Value | Meaning | `AER` at next startup |
|-------|---------|-----------------------|
| `0x00` | Exit without `RES`=1, 2, or 3 | None |
| `0x01` | `RES`=1 | None |
| `0x02` | `RES`=3 | None |
| `0x03` | `RES`=2 | `0x29B3` |
| `0x04` | EEPROM proxy communication failed | `0x29B4` |
| `0x05` | SD proxy transmit completion timed out | `0x29B5` |
| `0x06` | Fatal error; detail in BKP13R | `0x29B6` |
| `0x07` | Scheduler initialization started | `0x29BE` |
| `0x08` | Stop condition during task phase initialization | `0x29B7` |
| `0x09` | Stop condition during task member initialization | `0x29B8` |
| `0x0A` | NMI | `0x29B9` |
| `0x0B` | HardFault | `0x29BA` |
| `0x0C` | MemManage | `0x29BB` |
| `0x0D` | BusFault | `0x29BC` |
| `0x0E` | UsageFault | `0x29BD` |
| `0x0000FFFF` | Normal marker, set during 10 ms task initialization | `0x284C` |
| Other | Not interpreted | `0x284C` |

The EEPROM proxy replaces the local EEPROM driver with requests to an external
host over the binary transport. Code `0x04` covers request transmission timeouts
and, during proxy identification or write-enable setup, response timeouts and
response CRC failures.

`RES` selects how the application exits:

| `RES` | Task shutdown pass | Final reset | BKP10R |
|-------|--------------------|-------------|--------|
| 1 | Yes | Halt, then watchdog reset | `0x01` |
| 2 | No | Halt, then watchdog reset | `0x03` |
| 3 | Yes | Direct `NVIC_SystemReset()` | `0x02` |

The stop condition for `0x08` and `0x09` is any of: ADC logical channel 2 below
1999, `ZPD`=1, `RES`=1, 2, or 3, or a newly captured saved system error.

The NMI handler clears the clock-security interrupt flag when set and records
`0x0A` for any NMI.

`0xFFFF` is a deliberate write, not corrupted backup RAM.

### BKP11R: exception PC

The five application exception handlers save the stacked return PC here and the
reason in BKP10R, stop therapy control, and halt. For reasons `0x0A` to `0x0E`,
startup copies the PC to `ELV`. The BLX HardFault handler only loops and writes
neither register.

### BKP12R: shutdown completion

The exit path writes `0xFFFF` before closing services. A task shutdown pass
replaces it with the elapsed TIM5 count (prescaler 83) divided by 1000, as a
signed 16-bit value of at least 1.

### BKP13R: fatal-error detail

A fatal error stores its detail here, sets BKP10R to 6, and halts. During the next
10 ms task initialization, values `0x01` to `0x52` are copied to `FAT` and the
register is cleared.

| Value | Failed condition |
|-------|------------------|
| `0x11` | STR record buffer smaller than the required record size |
| `0x13` | Hash-table capacity below 2 |
| `0x14` | Hash-table capacity not a power of two |
| `0x15` | Negative insertion bucket index |
| `0x16` | Insertion bucket index outside capacity |
| `0x17` | Negative lookup bucket index |
| `0x18` | Lookup bucket index outside capacity |
| `0x19` | Negative hash-entry index |
| `0x1A` | Initial hash-entry assignment with nonzero state byte |
| `0x1B` | Hash-entry reuse with zero state byte |
| `0x1C` | Missing front-panel update dispatch target |
| `0x1D` | Missing front-panel reset dispatch target |
| `0x1E` | Missing GUI update target |
| `0x1F` | Hash bucket allocation failed |
| `0x20` | Missing hash bucket storage during rehash |
| `0x21` | Missing date/time source object |
| `0x22` | Reminder dependency allocation failed |
| `0x23` | Missing font pointer |
| `0x24` | Too many root-screen right-side widgets |
| `0x25` | Scrollable-window item storage allocation failed |
| `0x26` | Scrollbar or menu item capacity exceeded |
| `0x27` | GUI child window creation failed |
| `0x28` | Date editor variable cannot be resolved to g[4] |
| `0x29` | Menu entry type absent from the factory table |
| `0x2A` | Missing action-dialog callback |
| `0x2C` | Missing yes/no-dialog callback |
| `0x2D` | Left side of a two-sided row exceeds capacity |
| `0x2E` | Right side of a two-sided row exceeds capacity |
| `0x2F` | Transmission started while a frame is already active |
| `0x30` | Transmission submitted without an active frame |
| `0x31` | Transmit frame queue insertion failed |
| `0x32` | Segment appended without an active frame |
| `0x33` | Transmit segment queue insertion failed |
| `0x34` | Segment queue extraction failed |
| `0x35` | Scatter buffer consumed beyond its segment |
| `0x36` | Scatter buffer segment capacity exceeded |
| `0x37` | STR field adapter allocation failed |
| `0x38` | Unknown STR field adapter type |
| `0x39` | Unsupported source type in STR ratio adapter |
| `0x3A` | EEPROM `ERRORLOG` file open failed |
| `0x3B` | Summary source sample buffer allocation failed |
| `0x3C` | Active g[21] record has a nonzero byte at +0x04 in summary preparation |
| `0x3E` | Therapy component ID differs from the selected matrix record ID |
| `0x3F` | Enum option index exceeds 255 |
| `0x40` | Radio menu has no allowed children |
| `0x41` | Unsupported source in mask-time STR adapter |
| `0x42` | Task member initialization failed |
| `0x43` | STR field index outside descriptor count |
| `0x44` | Missing numerator or denominator reference in STR ratio adapter |
| `0x45` | Missing source reference in STR rate adapter |
| `0x46` | `CMS` STR record exceeds the 349-byte UART buffer |
| `0x47` | EEPROM session record exceeds the 5120-byte buffer |
| `0x48` | EDF exporter allocation failed |
| `0x49` | Session STR export allocation failed |
| `0x4A` | EDF header buffer allocation failed |
| `0x4D` | Identification file text construction failed |
| `0x4E` | Settings TGT text construction failed |
| `0x4F` | Missing session STR export source |
| `0x50` | OS task creation failed |
| `0x51` | OS timer creation failed |
| `0x52` | OS semaphore creation failed |

## Pending Date and Time: BKP14R to BKP16R

A date or time change can be staged here and applied at the next startup.

| Register | Content |
|----------|---------|
| BKP14R | Days since 1970-01-01 |
| BKP15R | Signed minutes relative to 12:00: `-720` midnight, `0` noon, `719` 23:59 |
| BKP16R | CRC-16 over date low, date high, time low, and time high bytes |

The checksum is CRC-16/CCITT-FALSE. Only
its low halfword is compared, because the halfword write can sign-extend it.
`0x7FFF` in BKP14R or BKP15R leaves that component unchanged.

Startup validates the CRC before applying the components and their range checks:

| Condition | Result |
|-----------|--------|
| Applied | BKP14R and BKP15R become `0x7FFF`; BKP16R is unchanged |
| CRC mismatch | Record left untouched |
| Both components zero | No update; both become `0x7FFF` |

## Transport Configuration: BKP17R

A nonzero `TMD` is copied to this register and `TMD` is cleared. Peripheral startup
then consumes and clears the register before loading the flags.

| Mask | Meaning |
|------|---------|
| `0x0003` | Proxy transport UART selector; see below |
| `0x0004` | Use the EEPROM proxy backend |
| `0x0008` | Use the SD proxy backend |
| `0x0010` | Enable the SD proxy on its first retrieval |
| `0x0020` | Enable the SD proxy in write-protected mode |

On SX567-0402, the UART selector assigns the ports as follows:

| `TMD & 0x0003` | Binary proxy transport | Ordinary Q-frame protocol |
|----------------|------------------------|---------------------------|
| `0` | No UART backend | USART1 and USART3 |
| `1` | USART1, internal cellular-module connection (transport 0) | USART3, external service connector |
| `2` | USART3, external service connector (transport 2) | USART1, internal cellular-module connection |
| `3` | Invalid selection; initialization enters an infinite loop | Initialization does not complete |

The Q-frame receiver excludes the port assigned to the proxy. Q-frame output
normally sent to both ports is restricted to the remaining port. The two
protocols can therefore coexist on separate UARTs, but do not share one UART.
Transport 1 is USART2, used for auxiliary-controller communication.

EEPROM and SD proxy traffic use separate channels of the same binary transport.
The SD proxy replaces the local SDIO backend with host-served 512-byte sectors;
the device still manages the filesystem and its files.

## ROP Retention: BKP18R

```
word = ROP_u16 | (CRC16(little_endian_u16(ROP)) << 16)
```

The checksum is CRC-16/CCITT-FALSE. `ROP` is
restored only when it matches. `0x1D0F0000` is a valid saved `ROP=0`. A zero word
is not.

## Proxy Diagnostics: BKP19R

This word collects diagnostics for framed transport, the EEPROM and SD proxies,
and validation of binary service-command sequences.

| Bits or mask | Meaning |
|--------------|---------|
| Bits 0..7 | Integrity-error counter |
| Bits 8..15 | Response-timeout counter |
| `0x00100000` | EEPROM proxy read request: transmit completion timeout |
| `0x00200000` | EEPROM proxy read response timeout; increments the timeout counter |
| `0x00400000` | EEPROM proxy read response CRC-32 mismatch; increments the integrity counter |
| `0x00800000` | EEPROM proxy write request: transmit completion timeout |
| `0x01000000` | Invalid binary service-command sequence length |
| `0x02000000` | Binary service-command sequence CRC-32 mismatch; increments the integrity counter |
| `0x04000000` | Framed transport header checksum mismatch; increments the integrity counter |
| `0x08000000` | SD proxy read response timeout; increments the timeout counter |
| `0x10000000` | SD proxy read response CRC-32 mismatch; increments the integrity counter |
| `0x80000000` | A byte counter overflowed |

Masks are ORed into the existing word. Counters wrap modulo 256 and set bit 31 on
overflow.

EEPROM transmit timeouts also set BKP10R to 4. SD transmit timeouts set BKP10R to
5.

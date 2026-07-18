# Air11 Connection

The first Air11 installation normally uses SWD. If a complete, unmodified
firmware image is already available for local patching, CAN can be used without
opening the device.

## SWD

### Hardware

- an SWD programmer, such as ST-Link or WeAct MiniDebugger
- a [TC2050-IDC](https://www.digikey.com/product-detail/en/TC2050-IDC/TC2050-IDC-ND/2605366)
  cable or TC2050-IDC-NL probe
- jumper wires matching the programmer header

After [opening the device](disassembly.md), fit the TC2050 connector with its
pin 1 marker aligned to pin 1 on the board footprint.

### Programmer Wiring

Connect these TC2050 cable pins:

| TC2050 pin | Programmer signal | Use |
|------------|-------------------|-----|
| `1` | `VREF` | target-voltage sense for a genuine ST-Link |
| `2` | `SWDIO` | required |
| `4` | `SWCLK` | required |
| `5` | `GND` | required |
| `10` | `NRST` | required |

![TC2050 connector pinout](../../images/tc2050_pinout.jpg)

A genuine ST-Link/V2 uses pins `1`, `7`, `9`, `20`, and `15` respectively.
Programmer clones use different header layouts; follow the signal names rather
than copying the ST-Link/V2 pin numbers.

Power the Air11 from its normal PSU. `VREF` senses the device voltage; it is not
a power input. Do not connect a programmer power output to the Air11 board.

The programmer-side ST-Link/V2 header and TC2050 cable orientation are shown in
the [TC2050 wiring reference](../wiring.md#tc2050-ribbon-cable-pinout-top-view).

Continue with [OpenOCD and Firmware Dump](openocd.md).

## CAN

CAN is the optional installation path when an unmodified firmware image is
available for local patching. The device remains powered by its normal PSU
while a USB-CAN adapter is connected in parallel through a pass-through cable.

Connector pinout, cable construction, tested adapters, and the SocketCAN setup
are documented in [Air11 CAN Connection](../../as11/can_connection.md).

The command-line target follows the host adapter:

| Adapter interface | Device target |
|-------------------|---------------|
| serial SLCAN on Linux | `can:/dev/ttyACM0` or `can:/dev/ttyUSB0` |
| serial SLCAN on Windows | `can:COM5` |
| SocketCAN | `can:can0` |

Continue with [Patching](patching.md) after the adapter is connected.

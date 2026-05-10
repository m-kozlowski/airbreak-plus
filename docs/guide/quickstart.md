# Quickstart

End-to-end guide for unlocking a ResMed AirSense 10 / AirCurve 10.

## What you need

Two paths depending on whether you have an original firmware image.

### Path A: already have a firmware image

If you obtained an original firmware dump elsewhere and don’t need to back up the current firmware, you can skip the device disassembly and SWD hardware entirely and [flash over UART](serial_connection.md).

Copy original firmware to cloned directory as `stm32.bin` and jump to [step 4 (patch)](#4-patch).

### Path B: dump firmware from device

Requires opening the device and connecting a SWD programmer to read the flash.

**Hardware:**
- Torx T10 screwdriver
- SWD programmer: genuine ST-Link, [WeAct MiniDebugger](https://github.com/WeActStudio/MiniDebugger) (recommended clone), or similar
- Connection to the programming header -- pick one:
  - [TC2050-IDC](https://www.digikey.com/product-detail/en/TC2050-IDC/TC2050-IDC-ND/2605366) adapter + 4-5 jumper wires (cleanest)
  - Pogo pins on the TC2050 footprint / [test points](../images/testpoints.jpg)
  - Direct soldering to the [test points](../images/testpoints.jpg)
- 1" jumper wires to connect SWDIO, SWCLK, GND, NRST (and VREF if using genuine ST-Link), see [wiring](wiring.md))

**Software:**
- OpenOCD
- Python 3.10+
- arm-none-eabi-gcc

On Windows, see [WSL2 setup](wsl_setup.md) for installing the toolchain.

## Steps

### 1. [Device disassembly](disassembly.md)

Pop off faceplate, remove 4 screws, pry off top cover, pull off knob, unclip LCD cover. No board removal needed.

### 2. [Wire up the programmer](wiring.md)

Connect SWD wires from programmer to the programming header.

### 3. [Dump the firmware](openocd.md)

*Path B only.*

```
 openocd -f interface/stlink.cfg -f tcl/airsense.cfg
```
or simply `./run-ocd.sh` inside cloned repo directory
Then in another terminal type:
```
telnet localhost 4444
> dump
```

**Keep `stm32.bin` safe. This is your only backup.**

### 4. [Patch](patching.md)

```
make
```

### 5. [Flash](flashing.md)

OpenOCD (path B):
```
> flash_new build/stm32-patched.bin
```

UART (path A or B):
```
./python/resmed_flash.py -p /dev/ttyACM0 -f build/stm32-patched.bin
```

### 6. Verify

Hold **Home** + push knob for 3 seconds to enter clinical menu. All therapy modes should be visible.

## Restoring to stock

OpenOCD:
```
> flash_new stm32.bin
```

UART:
```
./python/resmed_flash.py -p /dev/ttyACM0 -f stm32.bin
```

## Detailed guides

| Guide | Content |
|-------|---------|
| [WSL2 setup (Windows)](wsl_setup.md) | Bootstrapping the build environment on Windows |
| [Disassembly](disassembly.md) | Opening the device |
| [SWD wiring](wiring.md) | Programming header connections |
| [Serial connection](serial_connection.md) | UART accessory port |
| [OpenOCD](openocd.md) | Firmware dump and basic interaction |
| [Patching](patching.md) | Building, patch options, customization |
| [Flashing](flashing.md) | SWD and UART flashing |

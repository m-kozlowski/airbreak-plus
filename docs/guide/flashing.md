# Flashing

Two methods: SWD (via OpenOCD) or UART (via [`resmed_flash.py`](../tools/resmed_flash.md)).

## Method 1: OpenOCD (SWD)

Requires the device to be [opened](disassembly.md) with a [programmer attached](wiring.md) and [OpenOCD running](openocd.md).

### Flash patched firmware

In the OpenOCD console:
```
flash_new build/stm32-patched.bin
```

Takes about 30 seconds. The device reboots automatically.

### Restore original firmware

```
flash_new stm32.bin
```

### From AirBreaker

[AirBreaker](airbreaker.md#flashing) runs these commands from a window.

## Method 2: UART

Uses the USART3 accessory port. Requires a [serial connection](serial_connection.md) - either a USB-serial adapter with [edge connector breakout PCB](../adapter_pcbs), or [AirBridge](https://github.com/m-kozlowski/airbridge) over WiFi.

Does not require opening the device.

### Direct serial connection

```
./python/resmed_flash.py -p /dev/ttyACM0 -f build/stm32-patched.bin
```

### Via AirBridge (WiFi)

```
./python/resmed_flash.py -p tcp:airbridge-host -f build/stm32-patched.bin
```

### Flash specific blocks

By default, `resmed_flash.py` flashes CMX (CCX+CDX combined). To flash only one region:

```
./python/resmed_flash.py -p /dev/ttyACM0 -f build/stm32-patched.bin --block ccx
./python/resmed_flash.py -p /dev/ttyACM0 -f build/stm32-patched.bin --block cdx
```
For block description see [Firmware regions](#firmware-regions)

### Restore original firmware

```
./python/resmed_flash.py -p /dev/ttyACM0 -f stm32.bin
```

## Firmware regions

The 1MB flash is divided into regions:

| Region | Offset | Size | Content |
|--------|--------|------|---------|
| BLX | 0x00000 | 16 KB | Bootloader |
| CCX | 0x04000 | 240 KB | Configuration (variable descriptors, signal tables, strings) |
| CDX | 0x40000 | 768 KB | Application firmware (therapy algorithms, GUI, drivers) |
| CMX | -- | -- | CCX+CDX combined (used by the flash protocol as a single block) |

All devices within the same firmware version share the same CDX. The CCX determines which features and therapy modes are enabled.
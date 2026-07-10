# airbreak-plus

Firmware modification toolkit for ResMed AirSense 10 / AirCurve 10, AirSense 11 and partial support for Series 9.

## What it does

- [Unlocks all therapy modes](docs/guide/features/general.md#all-therapy-modes)
- [Unlocks clinical settings menu with full pressure range](docs/guide/features/general.md#clinical-settings-and-pressure-range)
- [Removes motor runtime hours nag screen](docs/guide/features/general.md#motor-runtime-warning)
- [Full EDF signal recording in all therapy modes](docs/guide/features/general.md#edf-recording)
- [Maintains myAir cloud compatibility across therapy modes](docs/guide/features/general.md#myair-cloud-compatibility)
- [Custom ASV pressure support](docs/guide/features/custom_asv.md) in the VAuto slot
- [Continuous LCD and button brightness adaptation](docs/guide/features/backlight.md)
- [ILI9325/ILI9328 LCD driver](docs/guide/features/general.md#replacement-lcd-driver) (the most common replacement panel available for these devices)

Best support for SX567-0401 and SX567-0402 firmware. Other versions are handled with reduced feature coverage.

## Getting started

See the [quickstart guide](docs/guide/quickstart.md) for a full walkthrough.

| Guide | Content |
|-------|---------|
| [Quickstart](docs/guide/quickstart.md) | End-to-end overview |
| [Disassembly](docs/guide/disassembly.md) | Opening the device |
| [SWD wiring](docs/guide/wiring.md) | Programming header connections |
| [Serial connection](docs/guide/serial_connection.md) | UART accessory port (for flashing without SWD) |
| [OpenOCD](docs/guide/openocd.md) | Firmware dump |
| [Patching](docs/guide/patching.md) | Building, patch options, customization |
| [Flashing](docs/guide/flashing.md) | SWD and UART flashing |

## Reference

| Document | Content |
|----------|---------|
| [resmed_config](docs/tools/resmed_config.md) | UART configuration tool |
| [resmed_flash](docs/tools/resmed_flash.md) | UART firmware flash tool |
| [Config variables](docs/config_variables.md) | Firmware variable system and globals[] structures |
| [Variable reference](docs/var_reference.tsv) | Firmware variables with var_id, UART name, EDF signal |
| [Patching: Custom settings](docs/custom_settings.md) | Reclaimed variables, persistence, menu registry, and payload fallbacks |
| [Patching: Patch payloads](docs/patch_payloads.md) | Versioned payload build, code-cave allocation, stubs, and ABI slots |
| [eeprom_tool](docs/eeprom_tool.md) | SPI EEPROM access (deprecated, see [native support](https://github.com/m-kozlowski/airbreak-plus/blob/master/docs/tools/resmed_config.md#calibration-eeprom) |
| [UART protocol](docs/serial_protocol.md) | Frame format and commands |
| [oximeter protocol](docs/oximeter_protocol.md) | Oximetry data submission specification |

## Related

- [airbridge](https://github.com/m-kozlowski/airbridge) - ESP32 WiFi bridge for AirSense 10 service port
- [aircannect](https://github.com/m-kozlowski/aircannect) - Wireless adapter for AirSense/AirCurve 11 devices 

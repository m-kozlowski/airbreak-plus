# resmed_config

UART configuration tool for ResMed Air 10 / s9 series

Read, write, dump, and restore device variables over the serial port. Works with direct serial, TCP via AirBridge, and offline by writing a `Settings.ecp` file to an SD card for the device to consume on next mount.

## Connection

```
resmed_config.py -p /dev/ttyACM0 ...                 # direct serial
resmed_config.py -p tcp:airbridge-host ...           # AirBridge TCP
resmed_config.py -p ecp:/sdcard/SETTINGS/ ...        # SD-card Settings.ecp (offline)
```

### `ecp:` backend

Instead of talking to a live device, prepare a `Settings.ecp` file to be put into `SETTINGS` directory on SD card.
When the SD card is inserted, the device reads `Settings.ecp` and applies the listed setting changes automatically.

Required `Settings.crc` file is written automatically whenever `Settings.ecp` is updated.


## Commands

### info

Show device identity (BID, SID, serial number, product name).

```
resmed_config.py -p /dev/ttyACM0 info
```

### get

Read one or more variables by name or group.

```
resmed_config.py -p /dev/ttyACM0 get IPC MPA MPI
resmed_config.py -p /dev/ttyACM0 get MGL
resmed_config.py -p /dev/ttyACM0 get all
```

### set / setv

Write one or more variables. `set` takes raw hex values, `setv` takes human-readable values with automatic scaling. Multiple `VAR VALUE` pairs may be passed in a single invocation.

```
resmed_config.py -p /dev/ttyACM0 set IPC 01F4
resmed_config.py -p /dev/ttyACM0 set SPT 0001 EPR 0002
resmed_config.py -p /dev/ttyACM0 setv IPC 10.0
resmed_config.py -p /dev/ttyACM0 setv MOP AutoSet
resmed_config.py -p ecp:/media/RESMED set PNA AirSense_10_airbreak
```

### dump / restore

Save all variables to JSON and restore them later.

```
resmed_config.py -p /dev/ttyACM0 dump -o config.json
resmed_config.py -p /dev/ttyACM0 dump --groups MGL EGL -o therapy.json
resmed_config.py -p /dev/ttyACM0 restore -i config.json
resmed_config.py -p /dev/ttyACM0 restore -i config.json --exclude-groups BGL
```

### list

Offline listing of known variables and descriptions.

```
resmed_config.py list
resmed_config.py list --groups MGL DGL
```

### caps

Query variable values and limits from the device.

```
resmed_config.py -p /dev/ttyACM0 caps IPC MOP EPR
```

### calibration eeprom

Run the stock firmware EEPROM/SD maintenance service (`CAL=000B`) from the
normal UART variable protocol. These commands use fixed device-side SD paths;
they do not read or write host files directly.

```
resmed_config.py -p /dev/ttyACM0 calibration eeprom sd-backup-raw
resmed_config.py -p /dev/ttyACM0 calibration eeprom sd-export-tree
resmed_config.py -p /dev/ttyACM0 calibration eeprom sd-restore-raw --yes
resmed_config.py -p /dev/ttyACM0 calibration eeprom sd-import-tree --yes
resmed_config.py -p /dev/ttyACM0 calibration eeprom erase-logical-pages --yes --really
resmed_config.py -p /dev/ttyACM0 calibration eeprom format-eep-fat --yes --really
```

The command enters calibration mode with `ROP=0004`, selects `CAL=000B`, starts
the selected `ETR` command, polls until `ETR=0000`, then restores the original
`CAL` and `ROP` values. If `ETR` does not return to `0000`, it does not clear
`ETR` blindly.

| Action | `ETR` | Firmware behavior |
|--------|-------|-------------------|
| `sd-backup-raw` | `0003` | raw EEPROM to `mmc:0:EEPROM\EEPROM.dat` |
| `sd-restore-raw` | `0004` | `mmc:0:EEPROM\EEPROM.dat` to raw EEPROM |
| `sd-export-tree` | `0005` | copy `eep:0:` tree to `mmc:0:EEPROM` |
| `sd-import-tree` | `0006` | copy fixed `mmc:0:EEPROM` paths back to `eep:0:` |
| `erase-logical-pages` | `0001` | zero EEPROM logical pages |
| `format-eep-fat` | `0002` | formats/reinitializes the `eep:0` FAT filesystem |

## Variable groups

| Group | Content |
|-------|---------|
| AGL | AutoSet params |
| BGL | Board/identity |
| CGL | CPAP params |
| DGL | Bilevel timing |
| EGL | EPR params |
| IGL | Bilevel pressure |
| MGL | Machine settings |
| NGL | Backlight (?) |
| PGL | Peripherals/accessories |
| QXH | ASVAuto params |
| QXJ | iVAPS params |
| RGL | Reminders/replacement |
| SGL | System settings |
| UGL | Usage data |
| VGL | VAuto params |
| XGL | ASV fixed params |

# OpenOCD and firmware dump

## Install OpenOCD

Most Linux distributions package OpenOCD:
```
sudo apt install openocd        # Debian/Ubuntu
sudo pacman -S openocd          # Arch
brew install openocd            # macOS
```

Windows: download from [openocd.org](https://openocd.org/pages/getting-openocd.html) or use the xPack build.

## Start OpenOCD

With the programmer [wired up](wiring.md) and the AirSense plugged in:

```
./run-ocd.sh
```

This is a convenience wrapper that runs `openocd -f interface/stlink.cfg -f tcl/airsense.cfg`. On WSL2 it also auto-attaches the ST-Link USB device. Pass a config name to use a different target:

```
./run-ocd.sh airsense     # default, same as no argument
```

Or run OpenOCD directly:

```
openocd -f interface/stlink.cfg -f tcl/airsense.cfg
```

Successful output ends with:
```
Info : stm32f4x.cpu: hardware has 6 breakpoints, 4 watchpoints
```

Leave this terminal running.

## Connect to OpenOCD

In a second terminal:
```
telnet localhost 4444
```

You should see the OpenOCD prompt.

## Dump firmware

> **This step is mandatory.** The dump is your only way to restore the device. Keep it safe.

```
dump
```

This creates `stm32.bin` in the working directory (exactly 1,048,576 bytes). Verify the size:
```
ls -la stm32.bin
```


## Useful commands

| Command | What it does |
|---------|-------------|
| `dump` | Dump full 1MB flash to `stm32.bin` |
| `dump filename.bin` | Dump to a specific file |
| `verify stm32.bin` | Compare file against flash |
| `flash_new patched.bin` | Write a firmware image to flash |
| `flash_blx image.bin` | Flash only the bootloader from a full image or bootloader block |
| `reset` | Reset the device |
| `halt` | Halt the CPU |
| `resume` | Resume execution |

## Next

[Building and patching](patching.md)

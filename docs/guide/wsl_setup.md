# WSL2 setup (Windows)

Bootstrapping an Airbreak Plus build environment on Windows.

After this guide you'll have WSL2 installed, the toolchain ready, the repo cloned, and (if you plan to use a SWD programmer) usbipd-win configured to forward your ST-Link into WSL2.

From there:

- Build the patched firmware -- [Patching](patching.md)
- Dump and flash over SWD -- [OpenOCD](openocd.md)
- Flash over UART without opening the device -- [Serial connection](serial_connection.md) + [Flashing](flashing.md)

## Contents

- [Install WSL2](#install-wsl2)
- [Update Linux packages](#update-linux-packages)
- [Install the toolchain](#install-the-toolchain)
- [Forward ST-Link into WSL2 (optional)](#forward-st-link-into-wsl2-optional)
- [Clone the repository](#clone-the-repository)
- [Working between WSL and Windows](#working-between-wsl-and-windows)
- [Next](#next)

## Install WSL2

Open PowerShell as Administrator (right-click the **Start** button -> **PowerShell (Admin)**) and run:

```powershell
wsl --install
```

This enables WSL2 and installs the default Ubuntu distribution. Reboot Windows.

After reboot, launch the Ubuntu shell from the Start menu (or just run `wsl` from any console).

## Update Linux packages

In the Ubuntu shell:

```bash
sudo apt update
sudo apt upgrade
```

After the upgrade completes, restart the WSL guest. From an Administrative PowerShell:

```powershell
wsl --shutdown
```

Reopen the Ubuntu shell - the next launch brings up a fresh kernel and init.

## Install the toolchain

In Ubuntu:

```bash
sudo apt install openocd python3-pip gcc-arm-none-eabi
```

Same packages as the [patching prerequisites](patching.md#prerequisites).

## Forward ST-Link into WSL2 (optional)

Skip this section if you'll only flash over UART.

WSL2 doesn't see USB devices natively - you forward them in with [usbipd-win](https://github.com/dorssel/usbipd-win).

1. Install `usbipd-win` - either `winget install usbipd` from PowerShell, or download the MSI from the project page.

2. Plug in the ST-Link. In an Administrative PowerShell:

   ```powershell
   usbipd list                    # find the BUSID of the ST-Link line
   usbipd bind --busid <busid>    # one-time, marks the device shareable
   ```

3. Verify from inside WSL:

   ```bash
   lsusb | grep -iE 'st-?link'
   ```

The included `./run-ocd.sh` helper auto-attaches any already-bound devices at the start of each session, so you only need to repeat the `bind` step if the device changes ports or you reinstall usbipd. The rest of the OpenOCD workflow lives in [OpenOCD](openocd.md).

## Clone the repository

```bash
mkdir -p ~/git
cd ~/git
git clone https://github.com/m-kozlowski/airbreak-plus
cd airbreak-plus
```

## Working between WSL and Windows

Your Ubuntu home is visible from Windows Explorer at:

```
\\wsl.localhost\Ubuntu\home\<your-user>\
```

(or `\\wsl$\Ubuntu\...` on older Windows builds.)

The fastest way to jump there is from inside WSL:

```bash
explorer.exe .
```

This opens Windows Explorer at the current WSL directory - handy for dropping in your `stm32.bin` firmware dump and pulling patched binaries back out of `build/` afterwards.

## Next

- [Patching](patching.md) -- build the patched firmware
- [OpenOCD](openocd.md) -- dump current firmware over SWD and flash
- [Serial connection](serial_connection.md) / [Flashing](flashing.md) -- flash over UART without opening the device

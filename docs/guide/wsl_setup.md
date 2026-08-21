# WSL2 setup (Windows)

Bootstrapping an Airbreak Plus build environment on Windows.

After this guide you'll have WSL2 installed, the toolchain ready, the repo cloned, and (if you plan to use a SWD programmer) usbipd-win configured to forward it into WSL2.

From there, continue with the quickstart for the target platform:

- [Air10 Quickstart](quickstart.md)
- [Air11 Quickstart](as11/quickstart.md)

## Contents

- [Install WSL2](#install-wsl2)
- [Update Linux packages](#update-linux-packages)
- [Install the toolchain](#install-the-toolchain)
- [Forward an SWD programmer into WSL2 (optional)](#forward-an-swd-programmer-into-wsl2-optional)
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
sudo apt install git make openocd python3-pip \
    gcc-arm-none-eabi binutils-arm-none-eabi telnet-ssl
```

For an Air10 UART or Air11 serial SLCAN connection, also install:

```bash
sudo apt install python3-serial
```

## Forward an SWD programmer into WSL2 (optional)

Skip this section when using only an Air10 UART or Air11 CAN connection.

WSL2 doesn't see USB devices natively - you forward them in with [usbipd-win](https://github.com/dorssel/usbipd-win).

1. Install `usbipd-win` - either `winget install usbipd` from PowerShell, or download the MSI from the project page.

2. Plug in the programmer. In an Administrative PowerShell:

   ```powershell
   usbipd list                          # find the programmer BUSID
   usbipd bind --busid <busid>          # one-time, marks the device shareable
   usbipd attach --wsl --busid <busid>  # attach it to WSL
   ```

3. Verify from inside WSL. For an ST-Link-compatible programmer:

   ```bash
   lsusb | grep -iE 'st-?link'
   ```

The included `./run-ocd.sh` helper auto-attaches already-bound devices at the
start of each session. Repeat the `bind` step only after changing USB ports or
reinstalling usbipd. Continue with the OpenOCD instructions in the selected
platform guide.

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

This opens Windows Explorer at the current WSL directory - handy for moving a
firmware dump into the repository and retrieving generated files from
`build/`.

## Next

- [Air10 Quickstart](quickstart.md)
- [Air11 Quickstart](as11/quickstart.md)

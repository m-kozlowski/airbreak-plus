# AirBreaker

AirBreaker is a window for choosing patches, building a patched firmware image and
flashing it to an AirSense / AirCurve 10 or 11, without typing commands. It runs
the same `make` builds and `run-ocd.sh` commands as the command line and reads
the same presets and local options files.

The window can:

- tick the patches you want and set their parameters
- save the choice as a [preset](../patch_options.md#presets), optionally on top of
  another preset such as `plus`
- build the selected platform's firmware with `make`, payloads included, and
  show what the patcher did
- dump, flash, verify and reset the device over SWD

Select the platform, `air10` or `air11`, at the top of the window. For device preparation,
see the [Air10 quickstart](quickstart.md) or [Air11 quickstart](as11/quickstart.md).

## What you need

| Need | Why |
|------|-----|
| An original firmware image: `stm32.bin` for Air10 or `as11.bin` for Air11 | The patcher starts from the original. Follow the quickstart for your device |
| Python 3.10 or newer with tkinter | Runs the window |
| `make`, `python3` and `arm-none-eabi-gcc` | Build the image. On Windows they live in [WSL](wsl_setup.md) |
| OpenOCD and an SWD programmer | Only for the Flash device section. See [Air10 wiring](wiring.md) or [Air11 connection](as11/connection.md#swd) |

You can build without any hardware. Only the Flash device section needs the
programmer and an opened device.

## Start the window

| System | Where the window runs | Where make and OpenOCD run |
|--------|-----------------------|----------------------------|
| [Windows](#windows) | Windows | In WSL |
| [Linux](#linux) | Linux | Directly on Linux |
| [WSL](#wsl-window-inside-wsl) | Inside WSL, shown through WSLg | Directly inside WSL |

### Windows

1. Install Python 3 from [python.org](https://www.python.org/downloads/windows/)
   (optional when WSL is set up). In the installer, keep **py launcher** and
   **tcl/tk and IDLE** selected.
2. Set up [WSL2](wsl_setup.md) with the toolchain, and with OpenOCD for flashing.
3. Double-click `airbreaker.bat` in the repository folder. It opens the window
   without a console. Without Windows Python it runs the window with `python3`
   in WSL instead, shown through WSLg; when `python3-tk` is missing there, it
   asks before installing it with `sudo apt-get`. If neither Python is
   available, the batch file tells you what to install.

`python python\airbreaker.py` in a terminal shows the same window, with error
output in the terminal.

Keep the repository in a normal Windows folder, for example under
`C:\Users\you`; make and OpenOCD run in WSL from that folder. Files outside it
are passed to WSL as converted paths.

When `make`, `python3` or the ARM toolchain is missing in WSL, the window lists
the packages and offers to open a WSL console that installs them with
`sudo apt-get`, where sudo asks for your WSL password. On a WSL distribution
without `apt-get`, install them with its own package manager.

### Linux

From the repository folder:

```bash
sudo apt install python3-tk make gcc-arm-none-eabi binutils-arm-none-eabi openocd usbutils
python3 python/airbreaker.py
```

On other distributions, install tkinter (`tk` on Arch, `python3-tkinter` on
Fedora), `make`, the ARM GCC toolchain and OpenOCD with the package manager.

The window needs a graphical session, or X forwarding over SSH.

If OpenOCD cannot open the programmer, you may need a udev rule or group
membership. The OpenOCD package normally installs the rules; unplug and replug
the programmer after installing.

### WSL (window inside WSL)

Use this if you cloned the repository inside WSL and want the window there.
Current WSL versions show Linux windows through WSLg; older setups need an X
server. From the repository folder:

```bash
sudo apt install python3-tk
python3 python/airbreaker.py
```

The toolchain from the [WSL setup](wsl_setup.md) is used as it is. If no window
appears, check that `echo $DISPLAY` is not empty and that WSLg is up to date
(`wsl --update` in PowerShell).

If you would rather keep the repository in Windows and only use WSL for the
tools, follow the [Windows](#windows) route instead.

## A tour of the window

A row of **Steps** runs along the top: choose patches, build, dump backup,
flash. A green tick means the step is done: the window built the image from
the current options and input, a backup file exists, and the device was flashed
from this window with the built image.

Below it, the options are at the top and the build and flash sections at the
bottom. You can drag the divider between them.

**Options (top)**

- **Platform** selects `air10` or `air11`. Each has its own patches, presets and
  output image, and its own remembered input, firmware and backup paths.
- **Patch groups** organize options by purpose, such as therapy unlocks,
  reporting and quality of life. Each patch has a checkbox with its description
  and a field below it for each parameter, such as `--target-rh` of
  `--patch-target-rh`.
- **Hover** a patch for its option name, default, parameters, what it requires
  and what requires it, and which file sets it now.
- Ticking a patch also ticks the patches it needs; unticking one unticks the
  patches that need it. The status line says which ones changed.
- **Preset (optional)**: pick a user preset from the list, or leave the field
  empty to start from the local options file and the defaults. Typing a new
  name and pressing Enter starts a new preset.
- **Based on**: a preset this one builds on, such as `plus` (Air10, the
  optional therapy payloads of `build/stm32-plus.bin`). Its options apply first.
- **Bold** entries are the options the preset sets itself. Save writes them and
  the base preset selection; everything else keeps following the base preset
  and the local options file.
- **Save** writes `presets/user/PLATFORM/NAME.config`, ignored by Git. Without
  a name it asks for one; with a changed name it saves a copy under that name.
  **Reload** reads the preset again. **Clear own options** shows only the base
  preset; nothing is written until you press Save.
- **Preset file** shows what Save writes, in command-line form.
- Repeatable parameters, such as Air11 `--rpc-permission`, show the inherited
  entries below the field. The field holds the preset's own additional entries.
- An orange note lists the options of the platform's local options file, if it
  has any. That file is edited by hand and applies under presets and the form;
  see [patch options](../patch_options.md#precedence).
- The title bar shows `*` when there are unsaved changes.

**Build firmware (bottom left)**

- **Input firmware**: the original image.
- **Output firmware**: `build/stm32-patched.bin` for Air10 or
  `build/as11-patched.bin` for Air11.
- **Build** runs Make with every patch and parameter as shown, through
  `AIR10_PATCH_ARGS` or `AIR11_PATCH_ARGS`, and does not save the preset. Make
  builds the payloads when needed and rebuilds the image only when the options
  or the input change.
- **Stop** ends the running command. **Verbose** (`V=1`) lists what each patch did.

**Flash device (bottom right)**

- **Adapter**: one of the adapters `run-ocd.sh` supports (`stlink`, `jlink`).
  **Serial** (optional) selects one of several connected programmers.
- **Firmware**: the image to flash or verify. **Backup (dump)**: where the
  stock dump is written.

Each button runs `run-ocd.sh` once with the platform's OpenOCD configuration
(`airsense` or `as11`), the adapter, one command and `shutdown`:

| Button | OpenOCD command |
|--------|-----------------|
| Check device | none; the configuration reports the device when it connects |
| Dump backup | `dump BACKUP` |
| Flash | `flash_new FIRMWARE`, which also verifies the written image |
| Verify | `verify FIRMWARE` |
| Reset | `reset run` |

The log at the bottom shows the output. Green lines are successful steps,
orange are warnings or skipped patches, red are errors. When a command ends
the log says `Done` or `Failed` and may add a hint.

## Building a firmware image

1. Select the platform, `air10` or `air11`.
2. Tick the patches you want, starting from a saved preset or from
   **Based on** `plus` (Air10) if you like. Hover a patch to read what it does.
3. Choose the **Input firmware** for that platform.
4. Press **Build**. The first build compiles the payloads and can take a few
   minutes. The log lists each patch as `[OK]`, `[SKIP]` or `[ERROR]` and ends
   with `Done` and the output image path.

Press **Save** to keep the selection as a preset for later builds; building
does not need one.

To build a saved preset from a terminal:

```bash
make AIR10_FIRMWARE=stm32.bin AIR10_PATCH_ARGS='--preset NAME' build/stm32-patched.bin
make AS11_FIRMWARE=as11.bin AIR11_PATCH_ARGS='--preset NAME' build/as11-patched.bin
```

## Flashing

> **Dump first.** The dump of the stock firmware is the only way to restore the
> device. Do it once, on stock firmware, and keep the file safe.

1. Open the device and connect the programmer as in [Air10 wiring](wiring.md)
   or [Air11 connection](as11/connection.md#swd). Power the device and select
   the matching platform in the window.
2. Choose the **Adapter**, and its **Serial** if several are connected.
3. Press **Check device**. The log reports the connection and the device.
4. Press **Dump backup** once, on stock firmware. The window asks before it
   overwrites an existing backup.
5. Set **Firmware** to the patched image and press **Flash**. The window asks
   you to confirm and warns when no backup exists. Keep the device and
   programmer connected until the log says `Done`.
6. Optionally press **Verify** to compare the device with the file, then
   **Reset** to restart it.

Flash needs a full image of the selected platform: 1 MB for Air10, 2 MB for
Air11. Verify compares the file, which may be shorter, with the start of the
flash. Closing the window while flashing asks for confirmation,
because stopping a flash can leave the device without working firmware.

On Windows and in WSL, OpenOCD runs in WSL. It needs `openocd` and `usbutils`
there (`sudo apt install openocd usbutils`) and a one-time `usbipd bind`; see
the [WSL setup](wsl_setup.md#forward-an-swd-programmer-into-wsl2-optional).
`run-ocd.sh` attaches the programmer when WSL does not see it yet.

UART flashing of the Air10 and CAN or BLE updates of the Air11 use the
command-line tools; see [Air10 flashing](flashing.md) and
[Air11 flashing](as11/flashing.md).

## Troubleshooting

| Message or symptom | What to do |
|--------------------|------------|
| Python 3 was not found (Windows) | Install Python from python.org with tcl/tk selected, or set up WSL |
| `No module named 'tkinter'` | Install tkinter: `sudo apt install python3-tk` |
| `WSL is missing: ...` | Let the window open the install console, or run the `sudo apt-get install` command it shows |
| `flash_new: expected a ... full image` | Check the selected platform and use a full image: 1 MB for Air10, 2 MB for Air11 |
| `openocd: command not found` | Install OpenOCD (in WSL: `sudo apt install openocd usbutils`) |
| `Error: open failed` | OpenOCD found no programmer: check the cable and driver, or in WSL that usbipd shares it |
| `WSL cannot reach <file>` | Move the file into the repository folder |
| A patch shows `[SKIP]` | It does not apply to this firmware version, or a required option is off. Read the log line |
| A setting is missing from the device menu | The build ran out of menu slots or labels; the verbose log says which. See [custom settings](../custom_settings.md) |
| Save asks about replacing the file | The preset was not written by this window, or the name is taken; saving replaces its comments and layout |

## Files

| File | What it is |
|------|------------|
| `presets/user/air10/NAME.config`, `presets/user/air11/NAME.config` | Your saved presets, ignored by Git. See [presets](../patch_options.md#presets) |
| `patch-airsense.config`, `patch-airsense-s11.config` | Local options files, edited by hand |
| `build/stm32-patched.bin`, `build/as11-patched.bin` | The images the window builds |
| `build/airbreaker-air10-input.bin`, `build/airbreaker-air11-input.bin` | Copy of an input image whose path Make cannot take, such as one with spaces; the log says when it is used |
| `stm32.bin`, `as11.bin` | Default paths of the stock dumps (the backups) |
| `.airbreaker.json` | In your home folder: the selected platform, file paths, presets, adapter, serial and Verbose |

## See also

- [Patching guide](patching.md) and [Air11 patching](as11/patching.md): what each patch does
- [Air10 flashing](flashing.md) and [Air11 flashing](as11/flashing.md): the same steps by hand, and the other methods
- [Patch options](../patch_options.md): presets, the local options files and command-line options
- [WSL setup](wsl_setup.md) and [OpenOCD](openocd.md)

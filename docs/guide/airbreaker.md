# AirBreaker

AirBreaker is a window for choosing patches, building a patched firmware image and
flashing it to an AirSense 10 / AirCurve 10, without typing commands. It uses the
same option declarations, presets, `make` and `run-ocd.sh` as the command line;
use whichever you prefer.

The window can:

- tick the patches you want and set their parameters
- save the choice as a [preset](../patch_options.md#presets), optionally on top of
  another preset such as `plus`
- build `build/stm32-patched.bin` with `make`, payloads included, and show what
  the patcher did
- dump, flash, verify and reset the device over SWD (`run-ocd.sh`)

It covers the Air10 only. The Air11 uses the [Air11 quickstart](as11/quickstart.md).

## What you need

| Need | Why |
|------|-----|
| An original firmware image, for example `stm32.bin` | The patcher starts from the original. See the [quickstart](quickstart.md) for getting one |
| Python 3.10 or newer with tkinter | Runs the window |
| `make`, `python3` and `arm-none-eabi-gcc` | Build the image. On Windows they live in [WSL](wsl_setup.md) |
| OpenOCD and an SWD programmer | Only for the Flash device section. See [wiring](wiring.md) and [OpenOCD](openocd.md) |

You can build without any hardware. Only the Flash device section needs the
programmer and an opened device.

## Start the window

Run it from the repository folder. Pick your platform:

| Platform | Where the window runs | Where make and OpenOCD run |
|----------|-----------------------|----------------------------|
| [Windows](#windows) | Windows | In WSL |
| [Linux](#linux) | Linux | Directly on Linux |
| [WSL](#wsl-window-inside-wsl) | Inside WSL, shown through WSLg | Directly inside WSL |

### Windows

1. Install Python 3 from [python.org](https://www.python.org/downloads/windows/)
   (optional when WSL is set up). In the installer, keep **py launcher** and **tcl/tk and IDLE** selected.
2. Set up [WSL2](wsl_setup.md) with the toolchain, and with OpenOCD for flashing.
   On Windows the window runs `make` and `run-ocd.sh` in WSL.
3. Double-click `airbreaker.bat` in the repository folder. It opens the
   window without a console. Without Windows Python it runs the window with
   `python3` in WSL instead (shown through WSLg). When `python3-tk` is missing
   there, it asks before installing it with `sudo apt-get`; sudo asks for your
   WSL password in the console. The window itself offers to install `make` and
   the ARM toolchain when a build needs them. On a WSL distribution without
   `apt-get` you install them yourself. If neither Python is available, the
   batch file tells you what to install.

Without the batch file: `python python\airbreaker.py` in a terminal
shows the same window, with error output in the terminal.

Keep the repository in a normal Windows folder (for example under `C:\Users\you`).
The window runs make and OpenOCD with `wsl --cd <repository>`, which works best
with a Windows path.

### Linux

```bash
sudo apt install python3-tk make gcc-arm-none-eabi binutils-arm-none-eabi openocd usbutils
python3 python/airbreaker.py
```

On other distributions, install tkinter (`tk` on Arch, `python3-tkinter` on
Fedora), `make`, the ARM GCC toolchain and OpenOCD with the package manager.
Run the command from the repository folder.

The window uses a desktop session, so it needs a graphical login (or X
forwarding over SSH).

### WSL (window inside WSL)

Use this if you cloned the repository inside WSL and want the window there.
Current WSL versions show Linux windows through WSLg; older setups need an X
server.

```bash
sudo apt install python3-tk
python3 python/airbreaker.py
```

The toolchain from the [WSL setup](wsl_setup.md) is used as it is. Flashing
runs `run-ocd.sh`, which attaches the programmer with `./usbattach.sh` when
WSL does not see it yet. The first time, run `usbipd bind` once as described
in the [WSL setup](wsl_setup.md#forward-an-swd-programmer-into-wsl2-optional).

If you would rather keep the repository in Windows and only use WSL for the
tools, follow the [Windows](#windows) route instead.

## A tour of the window

A row of **Steps** runs along the top: choose patches, save, build, dump
backup, flash. A green tick means the step is done: the preset is saved, the
window built the patched firmware from the saved options and the chosen input,
a backup file exists, and the device was flashed from this window with that
built image. Work through them from left to right; hover the row for a reminder.

Below it, the top part is the options and the bottom part builds and flashes.
You can drag the divider between them.

**Options (top)**

- **Patch groups**: one box per patch phase, in the order the patcher applies
  them. Each patch has a checkbox with its description and its option name (for
  example `--patch-header-clock`). A patch with parameters, such as
  `--patch-target-rh`, shows a field for each one below it.
- **Hover** a patch to see its declaration: description, default, parameters,
  what it requires and what requires it, and which file sets it now.
- Ticking a patch also ticks the patches it needs; unticking one unticks the
  patches that need it. The status line says which ones changed.
- **Preset**: the user preset the window edits, saved as
  `presets/user/air10/NAME.config` (not tracked by Git). Pick one from the list,
  or type a new name and press Enter. The default is `airbreaker`.
- **Based on**: another preset this one builds on, such as `plus` (the optional
  therapy payloads of `build/stm32-plus.bin`). Its options apply first; your
  preset only stores what differs from it.
- **Bold** entries are the options your preset sets itself. Only those are saved.
- **Save** writes the preset. With a changed name it saves a copy under that
  name. **Reload** reads it again. **Clear own options** shows only the base
  preset; nothing is written until you press Save.
- **Preset file** shows what Save writes, in command-line form.
- An orange note names the options of `patch-airsense.config`, if it has any.
  That local options file is edited by hand and applies under every preset,
  also in the window's builds. See [patch options](../patch_options.md#precedence).
- The title bar shows `*` when there are unsaved changes.

**Build firmware (bottom left)**

- **Input firmware**: the original image.
- **Output firmware**: `build/stm32-patched.bin`, the Makefile target the
  window builds.
- **Build**: saves the preset, then runs
  `make AIR10_FIRMWARE=INPUT PATCH_ARGS='--preset NAME' build/stm32-patched.bin`.
  make builds the payloads when needed, patches the image and records the
  options and the input image, so it rebuilds the image whenever they change.
- **Stop** ends the running command. **Verbose** (`V=1`) lists what each patch did.

**Flash device (bottom right)**

- **Adapter**: `stlink` or `jlink`. **Serial**: optional, selects one of several
  connected programmers (`run-ocd.sh -s SERIAL`).
- **Firmware**: the image to flash or verify. **Backup (dump)**: where the
  stock dump is written.
- Buttons: **Check device**, **Dump backup**, **Flash**, **Verify**, **Reset**.
  Hover a button for what it does.

The black box at the bottom is the log. Green lines are successful steps,
orange are warnings or skipped patches, red are errors. When a command ends
the log says `Done` or `Failed` and may add a hint.

The window remembers the file paths and choices in `.airbreaker.json`
in your home folder.

## Building a firmware image

1. Choose a **Preset** name, and **Based on** `plus` if you want the plus image's
   payloads.
2. Tick the patches you want. Hover to read what each one does. The defaults
   are a good start.
3. Press **Save**.
4. Choose the **Input firmware**, for example `stm32.bin`.
5. Press **Build**. The first build compiles the payloads and can take a few
   minutes. The log lists each patch as `[OK]`, `[SKIP]` or `[ERROR]` and ends
   with `Done: build/stm32-patched.bin built`.

When a menu control does not fit in the custom settings menu, the patcher says
so in the log. Tick **Verbose** for the details.

The same build from a terminal:

```bash
make AIR10_FIRMWARE=stm32.bin PATCH_ARGS='--preset airbreaker' build/stm32-patched.bin
```

## Flashing

> **Dump first.** The dump of the stock firmware is the only way to restore the
> device. Do it once, on stock firmware, and keep the file safe.

1. Open the device and connect the programmer as in [wiring](wiring.md). Power
   the device.
2. Choose the **Adapter**, and its **Serial** if several are connected.
3. Press **Check device**. The log reports that it connected and whether the
   device has stock or patched firmware.
4. Press **Dump backup** once, on stock firmware. The window asks before it
   overwrites an existing backup.
5. Set **Firmware** to the patched image and press **Flash**. The window asks
   you to confirm and warns when no backup exists. It takes about 30 seconds;
   keep the device and programmer connected until the log says `Done`.
6. Optionally press **Verify** to compare the device with the file, then
   **Reset** to restart it.

Flash and Verify only accept a full 1 MB image.

Closing the window while flashing asks for confirmation, because stopping a
flash can leave the device without working firmware.

Each button runs `run-ocd.sh` once; see [Flashing](flashing.md#from-airbreaker).
In WSL you need `openocd` and `usbutils` (`sudo apt install openocd usbutils`)
and the one-time `usbipd bind`; see the
[WSL setup](wsl_setup.md#forward-an-swd-programmer-into-wsl2-optional).

## Platform notes

**Windows**

- The ST-Link is shared into WSL with usbipd; `run-ocd.sh` attaches it. If
  OpenOCD says `open failed`, check the USB cable and that usbipd shares it.
- When make or Python is missing in WSL, the window lists the packages and
  offers to open a WSL console that runs `sudo apt-get install`. Nothing is
  installed without asking.
- Paths: files outside the repository folder are passed to WSL as converted
  paths. If WSL cannot reach a file, move it into the repository folder.

**Linux**

- If OpenOCD cannot open the programmer, you may need a udev rule or group
  membership. The OpenOCD package normally installs the rules; unplug and
  replug the programmer after installing.
- The mouse wheel scrolls the option list while the pointer is over it; the scroll
  bar always works.

**WSL**

- If no window appears, check that `echo $DISPLAY` is not empty and that WSLg
  is up to date (`wsl --update` in PowerShell).

## Troubleshooting

| Message or symptom | What to do |
|--------------------|------------|
| Python 3 was not found (Windows) | Install Python from python.org with tcl/tk selected, or set up WSL |
| `No module named 'tkinter'` | Install tkinter: `sudo apt install python3-tk` |
| `WSL is missing: ...` | Let the window open the install console, or run the `sudo apt-get install` command it shows |
| `make cannot read ...` | Copy the input image into the repository folder, for example as `stm32.bin`; make cannot take paths with spaces |
| `... is N bytes; a full 1 MB image is needed` | Flash and Verify need the whole flash image, not a partial file |
| `openocd: command not found` | Install OpenOCD (in WSL: `sudo apt install openocd usbutils`) |
| `Error: open failed` | OpenOCD found no programmer: check the cable and driver, or in WSL that usbipd shares it |
| `WSL cannot reach <file>` | Move the file into the repository folder |
| A patch shows `[SKIP]` | It does not apply to this firmware version, or a required option is off. Read the log line |
| A setting is missing from the device menu | The build ran out of menu slots or labels; the verbose log says which. See [custom settings](../custom_settings.md) |
| Options differ from what the window shows | Check the orange note: `patch-airsense.config` applies under every preset |
| Save asks about replacing the file | The preset was not written by this window, or the name is taken; saving replaces its comments and layout |

## Files

| File | What it is |
|------|------------|
| `presets/user/air10/NAME.config` | Your saved preset; not tracked by Git. See [presets](../patch_options.md#presets) |
| `patch-airsense.config` | The local options file, edited by hand; applies under every preset |
| `.airbreaker.json` | The window's remembered paths and choices, in your home folder |
| `build/stm32-patched.bin` | The image the window builds |
| `stm32.bin` | The default place for the stock dump (the backup) |

## See also

- [Patching guide](patching.md): what each patch does
- [Flashing](flashing.md): the same flashing steps by hand
- [Patch options](../patch_options.md): presets, the local options file and command-line options
- [WSL setup](wsl_setup.md) and [OpenOCD](openocd.md)

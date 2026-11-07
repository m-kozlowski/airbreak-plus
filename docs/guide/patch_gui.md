# AirBreaker

AirBreaker is a window for choosing patches, patching a firmware image and flashing it to an
AirSense 10 / AirCurve 10, without typing commands. It does the same as the
command line and `make`; use whichever you prefer.

The window can:

- tick the patches you want and set their parameters
- save the choice to `patch-airsense.config`
- build the compiled payloads (`make binaries`)
- patch a firmware image and show what the patcher did
- dump, flash, verify and reset the device over SWD (OpenOCD)

It covers the Air10 only. The Air11 uses the [Air11 quickstart](as11/quickstart.md).

## What you need

| Need | Why |
|------|-----|
| An original firmware image, for example `stm32.bin` | The patcher starts from the original. See the [quickstart](quickstart.md) for getting one |
| Python 3.10 or newer with tkinter | Runs the window |
| `make` and `arm-none-eabi-gcc` | Build the payloads. On Windows they live in [WSL](wsl_setup.md) |
| OpenOCD and an SWD programmer | Only for the Flash device section. See [wiring](wiring.md) and [OpenOCD](openocd.md) |

You can patch without any hardware. Only the Flash device section needs the
programmer and an opened device.

## Start the window

Run it from the repository folder. Pick your platform:

| Platform | Where the window runs | Where the build and flashing run |
|----------|-----------------------|----------------------------------|
| [Windows](#windows) | Windows | Build in WSL; flash with a Windows `openocd.exe` or through WSL |
| [Linux](#linux) | Linux | Directly on Linux |
| [WSL](#wsl-window-inside-wsl) | Inside WSL, shown through WSLg | Directly inside WSL |

### Windows

1. Install Python 3 from [python.org](https://www.python.org/downloads/windows/).
   In the installer, keep **py launcher** and **tcl/tk and IDLE** selected.
2. Set up [WSL2](wsl_setup.md) with the toolchain. It is only needed for
   *Build payloads* (and for flashing through WSL).
3. Double-click `airbreaker.bat` in the repository folder. It opens the
   window without a console. If Python is not found, the batch file tells you
   what to install.

Without the batch file: `python python\airbreaker.py` in a terminal
shows the same window, with error output in the terminal.

Keep the repository in a normal Windows folder (for example under `C:\Users\you`).
The window runs the build and WSL flashing with `wsl --cd <repository>`, which
works best with a Windows path.

### Linux

```bash
sudo apt install python3-tk make gcc-arm-none-eabi binutils-arm-none-eabi openocd
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

The toolchain from the [WSL setup](wsl_setup.md) is used as it is, so *Build
payloads* runs `make binaries` directly. Before flashing, attach the
programmer to WSL yourself: run `./usbattach.sh` in the repository, or
`usbipd attach --wsl --busid <busid>` in PowerShell, and check with
`lsusb | grep -i st-link`. The first time, run `usbipd bind` once as described
in the [WSL setup](wsl_setup.md#forward-an-swd-programmer-into-wsl2-optional).

If you would rather keep the repository in Windows and only use WSL for the
tools, follow the [Windows](#windows) route instead.

## A tour of the window

A row of **Steps** runs along the top: choose patches, save, build payloads,
patch, dump backup, flash. A green tick means the step is done: the options are
saved, the payloads are built, the patched firmware exists, a backup file exists,
and the device was flashed from this window. Work through them from left to
right; hover the row for a reminder.

Below it, the top part is the options and the bottom part patches and flashes.
You can drag the divider between them.

**Options (top)**

- **Custom settings menu** counter: how many of the reclaimed menu slots the
  selected patches use (on/off settings, value settings and new labels). If a
  setting does not fit it is left out, and an orange note names the ones that may
  be. Hover the counter or the note for the details. See [custom settings](../custom_settings.md).
- **Patch groups**: one box per patch phase. Each patch has a checkbox, its
  option name (for example `--patch-graph`) and some have a value box.
- **Bold** entries differ from the built-in default. Only those are saved.
- **Palette colors**: under *Patch the custom color palette*, each color swatch
  is one group of display colors (text, background, accent, ...). Click a
  swatch to pick a color. *Custom palette colors* puts back the built-in amber
  palette, *Stock ResMed colors* the original white, grey and blue. Colors that
  differ from the built-in palette are saved as `--palette-colors`.
- **Hover** a patch to see its description from the [patching guide](patching.md),
  what it requires, and the menu items it adds.
- Ticking a patch also ticks the patches it needs; unticking one unticks the
  patches that need it. The status line says which ones changed.
- **Save** writes `patch-airsense.config`. **Reload** reads it again.
  **Reset to defaults** shows the built-in defaults; nothing is written until
  you press Save.
- **Plus preset** selects the patches of `build/stm32-plus.bin` (graph, Custom
  VAuto, ASV backup-rate control, Square Wave, Fall Time, ST iBR and iVAPS
  AutoEPAP) and puts everything else back to its default. Add more patches
  on top, then Save.
- **Command line** shows your saved options in command-line form. Copy it to
  use as `AIR10_PATCH_ARGS` with `make`.
- The title bar shows `*` when there are unsaved changes.

**Patch firmware (bottom left)**

- **Input firmware**: the original image. **Output firmware**: where the
  patched image is written (default `build/stm32-patched.bin`).
- **Patch**: saves the options and patches the image.
- **Build payloads (make binaries)**: compiles the payloads. Needed once, and
  again after the files in `patches/` change.
- **Stop** ends the running command. **Verbose** lists what each patch did.

**Flash device (bottom right)**

- **OpenOCD**: which OpenOCD to use (see [Flashing](#flashing)). **Adapter**:
  `stlink` or `jlink`.
- **Firmware**: the image to flash or verify. **Backup (dump)**: where the
  stock dump is written.
- Buttons: **Check device**, **Dump backup**, **Flash**, **Verify**, **Reset**.
  Hover a button for what it does.

The black box at the bottom is the log. Green lines are successful steps,
orange are warnings or skipped patches, red are errors. When a command ends
the log says `Done` or `Failed` and may add a hint.

The window remembers the file paths and choices in `.airbreak_patch_gui.json`
in your home folder.

## Patching a firmware image

1. Tick the patches you want. Hover to read what each one does. The defaults
   are a good start.
2. Check the counter under *Custom settings menu*. A note in orange means a
   setting was left out for lack of a free slot or label; untick a patch you do
   not need to free one.
3. Press **Save**.
4. Press **Build payloads (make binaries)**. The first time can take a few
   minutes. Wait for `Done: payloads built`.
5. Choose the **Input firmware**, for example `stm32.bin`.
6. Press **Patch**. The log lists each patch as `[OK]`, `[SKIP]` or `[ERROR]`
   and ends with `Done: ... written`.

An existing output file is replaced. The window refuses to run if the output is
the same file as the input.

If the log says to run `make binaries`, press *Build payloads* and then Patch
again.

## Flashing

> **Dump first.** The dump of the stock firmware is the only way to restore the
> device. Do it once, on stock firmware, and keep the file safe.

1. Open the device and connect the programmer as in [wiring](wiring.md). Power
   the device.
2. Choose how OpenOCD runs (see below).
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

### Which OpenOCD

| Choice | Use it when |
|--------|-------------|
| **Windows openocd.exe** | You have OpenOCD on Windows (for example the xPack build). The window looks in the usual install folders; otherwise press **Browse...** and choose `openocd.exe` |
| **OpenOCD on this system** | Linux and WSL: the only choice. It uses the `openocd` in your path, shown in the box below, or one you choose with **Browse...** |
| **WSL (run-ocd.sh)** | You run the window on Windows and OpenOCD lives in WSL. It starts `run-ocd.sh`, which attaches the programmer with usbipd |

For WSL you need `openocd` and `usbutils` installed there (`sudo apt install
openocd usbutils`) and the one-time `usbipd bind`; see the
[WSL setup](wsl_setup.md#forward-an-swd-programmer-into-wsl2-optional).

The **WSL (run-ocd.sh)** choice appears only when the window runs on Windows.
The **Adapter** list switches between an ST-Link and a J-Link.

## Platform notes

**Windows**

- An ST-Link needs its driver. If OpenOCD says `open failed`, check the USB
  cable and driver.
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
- `lsusb | grep -i st-link` must show the programmer before you use the Flash
  buttons.

## Troubleshooting

| Message or symptom | What to do |
|--------------------|------------|
| Python 3 was not found (Windows) | Install Python from python.org with tcl/tk selected |
| `No module named 'tkinter'` | Install tkinter: `sudo apt install python3-tk` |
| `make was not found` | Install the toolchain; on Windows set up [WSL](wsl_setup.md) |
| Log says to run `make binaries` | Press **Build payloads**, then Patch again |
| `The output would overwrite the original firmware image` | Choose a different output file |
| `... is N bytes; a full 1 MB image is needed` | Flash and Verify need the whole flash image, not a partial file |
| `openocd: command not found` | Install OpenOCD (in WSL: `sudo apt install openocd usbutils`) |
| `Error: open failed` | OpenOCD found no programmer: check the cable and driver, or in WSL that usbipd shares it |
| `WSL cannot reach <file>` | Move the file into the repository folder, or use Windows `openocd.exe` |
| A patch shows `[SKIP]` | It does not apply to this firmware version, or a required option is off. Read the log line |
| A setting is missing from the device menu | The build ran out of menu slots or labels. See the counter and [custom settings](../custom_settings.md) |
| Options in the window do not match the config | `PATCH_*` environment variables override the config. The log notes any it finds |
| Save asks about replacing the file | The config was not written by this window; saving replaces its comments and layout |

## Files

| File | What it is |
|------|------------|
| `patch-airsense.config` | Your saved options, in the repository folder; not tracked by Git. See [patch options](../patch_options.md) |
| `.airbreak_patch_gui.json` | The window's remembered paths and choices, in your home folder |
| `build/stm32-patched.bin` | The default patched output |
| `stm32.bin` | The default place for the stock dump (the backup) |

## See also

- [Patching guide](patching.md): what each patch does
- [Flashing](flashing.md): the same flashing steps by hand
- [Patch options](../patch_options.md): the config file and command-line options
- [WSL setup](wsl_setup.md) and [OpenOCD](openocd.md)

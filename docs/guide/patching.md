# Building and patching

## Prerequisites

- `arm-none-eabi-gcc` (for compiled patches)
- Python 3.10+ (for the Python patcher and EDF merge)
- `stm32.bin` firmware dump in the repo root (see [firmware dump](openocd.md))

Install the toolchain:
```
sudo apt install gcc-arm-none-eabi     # Debian/Ubuntu
sudo pacman -S arm-none-eabi-gcc       # Arch
brew install arm-none-eabi-gcc         # macOS
```

On Windows, see [WSL2 setup](wsl_setup.md).

## Quick start

### Default patch (recommended)

```
make
```

This builds compiled patches and produces following images:

| Output | Content |
|--------|---------|
| `build/stm32-patched.bin` | unlocked stock-ish |
| `build/stm32-plus.bin` | Custom VAuto, ASV backup-rate control, Square Wave, Fall Time, ST iBR, iVAPS AutoEPAP |

The additional features in `plus` have runtime controls in the clinical menu.
`build/stm32-plus.bin` selects them with the [`plus` preset](../patch_options.md#presets).

The console shows compact patch status by default. A verbose transcript of the
latest build is written to `make.log`; use `make V=1` to also show it on the
console.

### Command-line patchers

`patch-airsense` runs the Python patcher with the `PATCH` operation,
overwrites an existing output and passes further options to the patcher:
```
./patch-airsense stm32.bin build/stm32-patched.bin
```

Equivalent Python command:
```
python3 python/patch-airsense.py stm32.bin build/stm32-patched.bin PATCH --overwrite
```

## What each patch does

All patches below are **enabled by default** unless noted.

### Therapy unlocks

| Patch | What it does | Switch |
|-------|-------------|--------|
| Unlock all modes | Enables all built-in therapy modes and their respiratory-event reporting | `--patch-extra-modes` |
| Unlock options | Enables all built-in tube and ramp choices, including the 3m tube and Auto ramp | `--patch-unlock-options` |
| Unlock settings | Makes the clinical settings used by unlocked modes available and editable | `--patch-gui-config` |
| iVAPS settings | Restores height controls and calculated MV, Vt, and Vt/kg IBW values | `--patch-ivaps-settings` |
| [Learn Targets](features/general.md#learn-targets) | Calculates iVAPS therapy targets from breathing. Requires custom settings. Off by default. | `--patch-learn-targets` |
| Unlock pressure range | Expands standard pressure settings to 1.0-30.0 cmH2O | `--patch-unlock-uilimits` |
| Unlock ASV PS range | Expands ASV/ASVAuto pressure support to 0-25 cmH2O, allows Max PS below Min PS + 5, and raises fixed ASV EPAP to the device pressure limit | `--patch-asv-ps-range` |
| Adjustable ASV pressure limit | Allows setting the limit from 10 cmH2O to the factory maximum. Off by default. | `--patch-adjustable-mcp` |
| Unlock iVAPS PS range | Clears ZLL, removing the additional 8 cmH2O Max PS minimum with AutoEPAP; skipped when ZLL is absent | `--patch-ivaps-ps-range` |

### Therapy data and reporting

| Patch | What it does | Switch |
|-------|-------------|--------|
| EDF signal merge | Expands SD-card therapy data recording across unlocked modes | `--patch-edf-merge` |
| VID spoof | Sets variant ID for the active therapy mode and selects a regional variant where known | `--patch-fw-vidspoof` |

### Quality of life

| Patch | What it does | Switch |
|-------|-------------|--------|
| Motor nag removal | Removes the "Motor life exceeded" message that appears after ~20,000 runtime hours | `--patch-motor-nagscreen` |
| Past date | Allows setting date to past values via menu and UART | `--patch-past-date` |
| Unlock languages | Enables all built-in languages | `--patch-unlock-languages` |
| Language fonts | Selects the correct font for each language, including the language selection list | `--patch-language-fonts` |
| Ukrainian font (opt-in) | Adds missing Ukrainian letters to the standard font; does not add translations or change the language list | `--patch-font-ua Y` |
| [Therapy screen](features/general.md#therapy-screen) | Adds selectable therapy screen styles and live graphs | `--patch-therapy-screen` |
| Keep graph screen on | Keeps the screen awake during therapy while the graph is enabled. Requires the therapy-screen patch. Off by default. | `--patch-graph-keep-screen-on` |
| Defaults | Sets firmware defaults (English, cmH2O, pillows mask, slim tube) | `--patch-defaults` |
| Bypass integrity check | Disables firmware integrity checks that prevent boot on CRC mismatch | `--patch-integrity-check` |
| Bypass PSU check | Disables power supply ID check at startup | `--patch-bypass-psuid` |
| Color palette | Applies custom color scheme | `--patch-custom-palette` |
| [Backlight adaptation](features/backlight.md) | Continuously adjusts LCD and button brightness to ambient light | `--patch-fw-backlight` |
| [Keep backlight](features/general.md#keep-backlight) | Hold the dial to toggle screen keep-awake | `--patch-keep-backlight` |
| [Header clock](features/general.md#header-clock) | Adds Clock in Configuration to show time on Home and therapy screens | `--patch-header-clock` |
| [Custom settings](../custom_settings.md) | Exposes menu settings for active compiled payloads and optional features | `--patch-custom-settings` |
| [Target humidity](features/general.md#target-humidity) | Adjusts target humidity in Auto and Manual; adds a menu control with custom settings | `--patch-target-rh`, with `--target-rh PERCENT` (default 85) |


### Therapy modifications

These optional payloads require `arm-none-eabi-gcc` and are off by default.

| Switch | What it does |
|--------|-------------|
| `--patch-fw-squarewave y` | Enable [Square Wave](features/squarewave.md) pressure shaping in S, ST, T, and PAC |
| `--patch-fw-asv-wrapper y` | Add [runtime control](features/asv_backup_rate.md) for stock ASV/ASVAuto backup rate |
| `--patch-fw-vauto-wrapper y` | Add [Custom VAuto](features/custom_vauto.md) pressure shaping and trigger/cycle assist |
| `--patch-fall-time y` | Add [Fall Time](features/general.md#fall-time) in S/ST/T/PAC/iVAPS through custom settings |
| `--patch-st-ibr y` | Add [adaptive backup timing in ST](features/general.md#st-ibr) through custom settings |
| `--patch-autoepap y` | Add [iVAPS AutoEPAP](features/general.md#ivaps-autoepap); requires font repacking and expanded heap |
| `--patch-humid-start y` | Add [Humid Start](features/humid_start.md), which holds the heated tube back while the humidifier warms up; no menu setting, SX567 only, requires font repacking; `--humid-start-min-tube DEGC` sets the [Min Tube](features/humid_start.md#min-tube) temperature (16-30, default 16) |

Example with custom VAuto:
```
./patch-airsense stm32.bin build/stm32-custom.bin --patch-fw-asv-wrapper y --patch-fw-vauto-wrapper y
```

### Miscellaneous

| Patch | What it does | Switch |
|-------|-------------|--------|
| Expand heap | Adds about 13.5 KiB of runtime allocation space on SX567 firmware | `--patch-expand-heap` |
| Repack fonts | Frees over 36 KiB of flash for patches without changing the available characters or their appearance | `--patch-font-repack` |
| UART dump/restore | Adds flash dump and EEPROM dump/restore over UART | `--patch-blx-dump` |
| UART metadata | Reports live-stream layouts and custom-settings menu metadata through `G C` | `--patch-uart-stream-schema` |
| Replacement LCD | Adds the ILI9325/ILI9328 LCD driver | `--patch-fw-lcd` |

## Selecting patches

Use `y` to enable a patch or `n` to disable it. For example, to disable
Square Wave even when the [local options file](../patch_options.md#files) selects it:

```bash
python3 python/patch-airsense.py stm32.bin build/stm32-custom.bin PATCH \
    --patch-fw-squarewave n
```

`--preset NAME` applies a saved set of options, such as `--preset plus`; other
options on the command line override it.

When building through Make, options can also be passed with `AIR10_PATCH_ARGS`,
or with `PATCH_ARGS` when `AIR10_PATCH_ARGS` is not set.
See [patch options](../patch_options.md) for examples, saved preferences and
user presets.

## Next

- [Flashing](flashing.md)

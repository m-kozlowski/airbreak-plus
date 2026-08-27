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
| `build/stm32-graph.bin` | graph overlay injected |
| `build/stm32-asv-plus.bin` | Custom ASV algo in VAuto slot, backup-rate suppression, squarewave |
| `build/stm32-asv-plus_no-squarewave.bin` | same as stm32-asv-plus minus squarewave |
| `build/stm32-asv-plus_with-backup.bin` | same as stm32-asv-plus minus backup-rate suppression |

The console shows compact patch status by default. A verbose transcript of the
latest build is written to `make.log`; use `make V=1` to also show it on the
console.

### Command-line patchers

The compatibility command used by the Makefile is:
```
./patch-airsense stm32.bin build/stm32-patched.bin
```

`patch-airsense` accepts the environment variables listed below and invokes the
Python patcher:
```
./python/patch-airsense.py stm32.bin build/stm32-patched.bin PATCH
```

## What each patch does

All patches below are **enabled by default** unless noted.

### Therapy unlocks

| Patch | What it does | Switch |
|-------|-------------|--------|
| Unlock all modes | Enables all built-in therapy modes and their respiratory-event reporting | `--patch-extra-modes` |
| Unlock options | Enables all built-in tube and ramp choices, including the 3m tube and Auto ramp | `--patch-unlock-options` |
| Unlock settings | Makes the clinical settings used by unlocked modes available and editable | `--patch-gui-config` |
| Unlock pressure range | Expands standard pressure settings to 1.0-30.0 cmH2O | `--patch-unlock-uilimits` |
| Unlock ASV PS range | Expands ASV/ASVAuto pressure support to 0-25 cmH2O, allows Max PS below Min PS + 5, and raises fixed ASV EPAP to the device pressure limit | `--patch-asv-ps-range` |

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
| Therapy screen | Enables additional information on the therapy screen | `--patch-therapy-screen` |
| Defaults | Sets firmware defaults (English, cmH2O, pillows mask, slim tube) | `--patch-defaults` |
| Bypass integrity check | Disables firmware integrity checks that prevent boot on CRC mismatch | `--patch-integrity-check` |
| Bypass PSU check | Disables power supply ID check at startup | `--patch-bypass-psuid` |
| Color palette | Applies custom color scheme | `--patch-custom-palette` |
| [Backlight adaptation](features/backlight.md) | Continuously adjusts LCD and button brightness to ambient light | `--patch-fw-backlight` |
| [Custom settings](../custom_settings.md) | Exposes menu settings for active compiled payloads | `--patch-custom-settings` |


### Therapy modifications

These optional payloads require `arm-none-eabi-gcc` and are controlled by
environment variables.

| Env variable | What it does |
|-------------|-------------|
| `PATCH_CODE=1` | Add the therapy graph overlay and its shared code |
| `PATCH_S=1` | Enable [Square Wave](features/squarewave.md) pressure shaping in S, ST, T, and PAC; requires `PATCH_VAUTO_WRAPPER=1` |
| `PATCH_ASV_TASK_WRAPPER=1` | Add [runtime control](features/asv_backup_rate.md) for stock ASV/ASVAuto backup rate |
| `PATCH_VAUTO_WRAPPER=1` | Add [Custom VAuto](features/custom_vauto.md) pressure shaping and trigger/cycle assist; the wrapper also selects its shared code |

With custom settings, `Monitoring` in clinical Options enables or disables the
flow and pressure graph. Without custom settings, the graph remains enabled.

Example with custom VAuto:
```
export PATCH_CODE=1
export PATCH_ASV_TASK_WRAPPER=1
export PATCH_VAUTO_WRAPPER=1
./patch-airsense stm32.bin build/stm32-asv-plus.bin
```

### Miscellaneous

| Patch | What it does | Switch |
|-------|-------------|--------|
| UART firmware dump | Adds the SX577 bootloader command used by `resmed_flash.py --dump` | `--patch-blx-dump` |
| UART stream schema | Reports current live-stream fields and widths through `G C &TAG` | `--patch-uart-stream-schema` |
| Replacement LCD | Adds the ILI9325/ILI9328 LCD driver | `--patch-fw-lcd` or `PATCH_S10_LCD=1` |

## Selecting patches

Pass `n` to disable a default patch or `y` to enable an optional patch. Boolean
values are case-insensitive. The compatibility wrapper forwards additional
options to Python, so both forms below are valid:
```
./patch-airsense stm32.bin out.bin --patch-gui-config n
./python/patch-airsense.py stm32.bin out.bin PATCH --patch-gui-config=n
```

Direct Python selections enforce payload dependencies: graph and Custom VAuto
require common code, while Square Wave requires both common code and Custom
VAuto.

List all flags:
```
./python/patch-airsense.py --help
```

## Next

- [Flashing](flashing.md)

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

### Alternative patchers

Bash (same as Makefile default):
```
./patch-airsense stm32.bin build/stm32-patched.bin
```

Python:
```
./python/patch-airsense.py stm32.bin build/stm32-patched.bin PATCH
```

## What each patch does

All patches below are **enabled by default** unless noted.

### Therapy unlocks

| Patch | What it does | Bash function | Python switch |
|-------|-------------|---------------|---------------|
| Unlock all modes | Enables all therapy modes in the mode selector (CPAP, AutoSet, VAuto, ASV, ASVAuto, iVAPS, ...) | `extra_modes` | `--patch-extra-modes` |
| Unlock settings | Exposes all settings linked to unlocked modes by toggling their visibility flag | `gui_config` | `--patch-gui-config` |
| Unlock pressure range | Extends min/max pressure limits to 1.0-30.0 cmH2O for all modes | `unlock_ui_limits` | `--patch-unlock-uilimits` |
| Unlock ASV PS range | Removes the Min PS + 5 cmH2O floor on ASV/ASVAuto pressure support | `asv_unlock_ps_range` | `--patch-asv-ps-range` |

### Data and recording

| Patch | What it does | Bash function | Python switch |
|-------|-------------|---------------|---------------|
| EDF signal merge | Expands STR.edf to 116-channel superset so all signals are recorded regardless of therapy mode | `patch_edf_merge` | `--patch-edf-merge` |
| VID spoof | Sets variant ID for the active therapy mode and selects a regional variant where known | `patch_vid_spoof` | `--patch-fw-vidspoof` |

### Quality of life

| Patch | What it does | Bash function | Python switch |
|-------|-------------|---------------|---------------|
| Motor nag removal | Removes the "Motor life exceeded" message that appears after ~20,000 runtime hours | `motor_nagscreen` | `--patch-motor-nagscreen` |
| Past date | Allows setting date to past values via menu and UART | `patch_past_date` | `--patch-past-date` |
| Unlock languages | Enables all built-in languages | `unlock_languages` | `--patch-unlock-languages` |
| Extra debug | Enables additional info in the sleep report screen | `extra_debug` | `--patch-extra-debug` |
| Defaults | Sets firmware defaults (English, cmH2O, pillows mask, slim tube) | `patch_defaults` | `--patch-defaults` |
| Bypass integrity check | Disables firmware integrity checks that prevent boot on crc mismatch | `patch_tamper` | `--patch-bypass-start` |
| Bypass PSU check | Disables power supply ID check at startup | `patch_psu_id` | `--patch-bypass-psuid` |
| Color palette | Applies custom color scheme | `custom_palette` | `--patch-custom-palette` |
| [Backlight adaptation](features/backlight.md) | Continuously adjusts LCD and button brightness to ambient light | `patch_backlight_adapt` | `--patch-fw-backlight` |
| [Custom settings](../custom_settings.md) | Exposes menu settings for active compiled payloads | `custom_patch_settings` | `--patch-custom-settings` |


### Therapy modifications

These optional payloads require `arm-none-eabi-gcc` and are controlled by
environment variables.

| Env variable | What it does |
|-------------|-------------|
| `PATCH_CODE=1` | Add the therapy graph overlay and inject shared code used by the other therapy payloads |
| `PATCH_S=1` | Enable [Square Wave](features/squarewave.md) pressure shaping in S, ST, T, and PAC (requires `PATCH_CODE=1`) |
| `PATCH_ASV_TASK_WRAPPER=1` | Add [runtime control](features/asv_backup_rate.md) for stock ASV/ASVAuto backup rate (requires `PATCH_CODE=1`) |
| `PATCH_VAUTO_WRAPPER=1` | Add [Custom VAuto](features/custom_vauto.md) pressure shaping and trigger/cycle assist (requires `PATCH_CODE=1`) |

Example with custom VAuto:
```
export PATCH_CODE=1
export PATCH_ASV_TASK_WRAPPER=1
export PATCH_VAUTO_WRAPPER=1
./patch-airsense stm32.bin build/stm32-asv-plus.bin
```

### Other

| Env variable | What it does |
|-------------|-------------|
| `PATCH_S10_LCD=1` | ILI9325/ILI9328 LCD driver |

## Disabling a default patch

### Bash patcher

Comment out the function call at the bottom of `patch-airsense`. For example, to skip the color palette:
```bash
# custom_palette
```

### Python patcher

Pass `n` to the corresponding flag:
```
./python/patch-airsense.py stm32.bin out.bin PATCH --patch-gui-config=n
```

List all flags:
```
./python/patch-airsense.py --help
```

## Next

- [Flashing](flashing.md)

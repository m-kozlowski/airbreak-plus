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
| VID spoof | Dynamically sets variant ID per therapy mode so myAir reports correctly | `patch_vid_spoof` | `--patch-fw-vidspoof` |

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
| Backlight adaptation | Continuously adjusts LCD and button brightness to ambient light | `patch_backlight_adapt` | `--patch-fw-backlight` |
| Custom settings | Exposes persistent settings for active compiled payloads | `custom_patch_settings` | `--patch-custom-settings` |

### Custom settings

The framework is currently supported on SX567-0401 and SX567-0402. It removes
the stock Reminders menu and background processing, reuses selected Reminder
variables, and stores the custom values in new `CSG.set`. Stock settings files
and the original `RGL.set` are left separate.

| Setting | What it does | Menu section | Visible modes | Default | Behavior without `custom_settings` |
|---------|--------------|--------------|---------------|---------|------------------------------------|
| Custom ASV | Enables adaptive inspiratory pressure boost in the VAuto slot | Therapy | VAuto | Off | Custom ASV is active |
| ASV Max | Limits additional adaptive boost above the base VAuto pressure shape | Therapy | VAuto | 3.0 cmH2O | Extra boost limit is `2 * VAuto PS` |
| ASV Sens | Scales how strongly the adaptive controller responds to breath error | Therapy | VAuto | Normal | Normal, multiplier 1.0 |
| Custom T/C | Enables custom trigger and cycle assistance independently of Custom ASV | Therapy | S, ST, T, VAuto, PAC | Off | Custom trigger and cycle assist are active where supported by the runtime path |
| Square Wave | Selects the square-wave inspiratory pressure path | Therapy | S, ST, T, PAC | On | Square Wave is active |
| Ambient Low | Sets the ambient reading where LCD and button targets start rising from LLL and LBL | Configuration | all modes | 590 | Backlight patch uses the patched ATH default of 590 |
| Ambient High | Sets the ambient reading where LCD and button targets reach LLH and LBH; zero selects stock handling | Configuration | all modes | 3070 | Backlight patch uses the fixed fallback `0xC00` |

The variable pools, persistence, menu registry, and payload ABI are documented
in [Custom settings](../custom_settings.md).

### Compiled patches (off by default)

These require `arm-none-eabi-gcc` and are controlled by environment variables:

| Env variable | What it does |
|-------------|-------------|
| `PATCH_CODE=1` | Inject shared code library + graph overlay |
| `PATCH_S=1` | Enable the Square Wave pressure path in S, ST, T, and PAC (requires PATCH_CODE) |
| `PATCH_ASV_TASK_WRAPPER=1` | Suppress ASV backup breathing rate (requires PATCH_CODE) |
| `PATCH_VAUTO_WRAPPER=1` | Add Custom ASV pressure shaping and trigger/cycle assist (requires PATCH_CODE) |
| `PATCH_S10_LCD=1` | ILI9325/ILI9328 LCD driver |

Example with custom ASV:
```
export PATCH_CODE=1
export PATCH_ASV_TASK_WRAPPER=1
export PATCH_VAUTO_WRAPPER=1
./patch-airsense stm32.bin build/stm32-asv-plus.bin
```

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

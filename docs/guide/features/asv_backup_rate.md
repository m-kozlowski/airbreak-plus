# ASV Backup Rate Control

This payload controls the stock timed backup response in ASV and ASVAuto. It is
separate from Custom VAuto and does not add a backup rate to VAuto.

<p align="center">
  <img src="../../images/asv-backup-rate-setting.png" alt="Backup Rate setting in ASVAuto" width="240">
</p>

## Control

| Setting | UART | Range | Default | Menu | Visible modes | Function | Without `custom_settings` |
|---------|------|-------|---------|------|---------------|----------|---------------------------|
| Backup Rate | `RPW` | Off, On | Off | Therapy | ASV, ASVAuto | Off suppresses the stock timed backup response; On preserves stock behavior | Off |

Firmware variable assignment and persistence are listed in the
[custom settings registry](../../custom_settings.md#assignments).

## Build availability

| Build | Behavior |
|-------|----------|
| `build/stm32-asv-plus.bin` | Backup Rate control available |
| `build/stm32-asv-plus_no-squarewave.bin` | Backup Rate control available |
| `build/stm32-asv-plus_with-backup.bin` | Wrapper absent; stock behavior is always preserved |

When the wrapper is present without `custom_settings`, its fallback is Off and
the stock timed backup response remains suppressed.

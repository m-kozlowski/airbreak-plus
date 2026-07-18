# Square Wave

The Square Wave payload replaces the stock pressure-shaping handler used by S,
ST, T, and PAC. It does not affect CPAP, AutoSet, VAuto, ASV, ASVAuto, or iVAPS.

<p align="center">
  <img src="../../images/custom-square-wave.png" alt="Square Wave setting in the clinical Therapy menu" width="240">
</p>

## Control

| Setting | UART | Range | Default | Menu | Visible modes | Function | Without `custom_settings` |
|---------|------|-------|---------|------|---------------|----------|---------------------------|
| Square Wave | `RPF` | Off, On | On | Therapy | S, ST, T, PAC | On selects custom pressure shaping; Off calls the stock handler | On |

Firmware variable assignment and persistence are listed in the
[custom settings registry](../../custom_settings.md#assignments).

## Pressure Shape

During inspiration, commanded pressure support starts near 10% of the configured
support and rises toward the full value using Rise Time and breath progress.
Pre-cycle detection can begin reducing support before expiration is formally
detected.

During expiration, support falls from its final inspiratory value toward zero
over approximately 0.8 seconds. It may then become negative, lowering the
pressure target by up to 0.8 cmH2O below EPAP. This exhale relief is shaped by
expired volume and expiration time.

The resulting pressure target is bounded between EPAP minus 0.8 cmH2O and the
configured IPAP.

The S EasyBreathe runtime path does not use the Square Wave handler.

## Build availability

| Build | Behavior |
|-------|----------|
| `build/stm32-asv-plus.bin` | Square Wave control available |
| `build/stm32-asv-plus_no-squarewave.bin` | Payload absent |
| `build/stm32-asv-plus_with-backup.bin` | Square Wave control available |

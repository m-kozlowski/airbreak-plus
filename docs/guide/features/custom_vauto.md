# Custom VAuto

The `stm32-asv-plus` builds add adaptive pressure support to the VAuto therapy
slot. This is separate from the stock ASV and ASVAuto modes.

- select VAuto on the device
- use the normal VAuto pressure settings
- enable Custom VAuto in the clinical Therapy menu
- expect reports to identify the session as VAuto

Stock ASV and ASVAuto settings do not control the custom VAuto algorithm.

## Controls

| Setting | UART | Range | Default | Menu | Visible modes | Function | Without `custom_settings` |
|---------|------|-------|---------|------|---------------|----------|---------------------------|
| Custom VAuto | `RPO` | Off, On | Off | Therapy | VAuto | Enables the complete custom VAuto wrapper; Off preserves stock VAuto behavior | On |
| ASV Max | `RCM` | 0.0 to 10.0 cmH2O, step 0.2 | 3.0 cmH2O | Therapy | VAuto | Limits adaptive boost above the base VAuto pressure shape; zero disables adaptive boost | `2 * VAuto PS` |
| ASV Sens | `RXM` | Very Low, Low, Med, High, Very High | Med | Therapy | VAuto | Scales the adaptive controller response | Med |
| Custom T/C | `RPH` | Off, On | Off | Therapy | S, ST, T, VAuto, PAC | Selects custom trigger and cycle decisions; Off preserves the configured stock sensitivities | On where supported by the runtime path |

Firmware variable assignments and persistence are listed in the
[custom settings registry](../../custom_settings.md#assignments).

ASV Max is not an absolute pressure setting. It limits only the additional
adaptive boost above the base pressure shape. Max IPAP and the stock firmware
pressure limiter still apply to the final command.

VAuto PS remains a valid zero setting. At zero, the custom wrapper uses the
stock VAuto pressure path because there is no pressure-support shape to adapt.

ASV Sens uses these controller multipliers:

| Setting | Multiplier |
|---------|------------|
| Very Low | 0.50 |
| Low | 0.75 |
| Med | 1.00 |
| High | 1.25 |
| Very High | 1.50 |

Changing ASV Sens changes how strongly the controller responds to breath error.
It does not directly add a fixed pressure amount and does not bypass ASV Max.

Ti Min remains a normal VAuto timing setting. It is not used as the Custom VAuto
enable switch.

## Therapy behavior

The algorithm tracks recent valid breaths and builds a moving reference breath.
It does not use a fixed tidal-volume target.

During inspiration it compares cumulative inspired volume with the reference at
roughly 50 ms checkpoints:

| Current breath | Response |
|----------------|----------|
| Smaller than the recent reference | Increase adaptive pressure support |
| Close to the recent reference | Stay near the base VAuto support shape |
| Larger than the recent reference | Reduce adaptive boost without going below the custom base shape |

The baseline neutral range is approximately 94 to 96 percent of the recent
inspiratory-volume curve. After an unusually large breath, the controller
temporarily lowers this range to damp the following response. Its
pressure-shaping factor is limited internally, then ASV Max limits the resulting
extra boost in cmH2O.

EPAP remains under stock VAuto control. The wrapper reshapes pressure support,
ASV Max limits the adaptive addition above its custom base shape, and the stock
downstream pressure limiter applies the configured Max IPAP ceiling to the final
command.

## Pressure shape

During inspiration:

- pressure support starts from the custom base VAuto shape
- weak breaths can receive additional support within the same inspiration
- the first part of a new breath is limited to reduce false-trigger response
- the largest pressure reached is retained for the expiratory downslope

During expiration:

- support falls from the final inspiratory value
- exhale relief magnitude depends on current EPAP, VAuto PS, and the adaptive
  support reached during inspiration
- relief fades according to the remaining integrated breath volume and current
  and recent expiratory timing
- a small pre-trigger assist may be added when an inspiration is expected

## Stabilizers

| Behavior | Purpose |
|----------|---------|
| Two-stage moving reference | Limits how strongly one breath can change the reference curve |
| Early-inspiration limiting | Gradually enables the adaptive factor during the beginning of each inspiration |
| Boost engagement limiting | Limits the initial response when adaptive boost engages or re-engages |
| Post-large-breath dampening | Temporarily lowers the target after an unusually large breath |
| ASV Max | Places an explicit pressure cap on adaptive boost |

## Trigger and cycle

Custom T/C controls custom trigger and cycle assistance. The setting is shown
in S, ST, T, VAuto, and PAC.

Trigger assistance uses flow, early inspiratory volume, pressure below target,
and expected breath timing. Cycle assistance can delay or force the transition
to expiration from inspiratory flow shape and timing.

Off leaves the configured stock trigger and cycle sensitivities unchanged. In
VAuto, Custom T/C applies only while Custom VAuto is On. S, ST, T, and PAC use
the shared S runtime path, where Custom T/C remains independent of the Custom
VAuto switch. The EasyBreathe-specific S path does not apply Custom T/C.

## Backup rate

Custom VAuto does not provide timed backup breaths. Control of the stock ASV
and ASVAuto backup response is a separate
[ASV backup-rate feature](asv_backup_rate.md).

## Caveats

- Large leaks or unstable triggering can distort the reference breath.
- Low Max IPAP can clip the adaptive response before ASV Max is reached.
- VAuto PS set to zero selects the stock VAuto pressure path and disables the
  custom trigger and cycle path in VAuto.
- Custom VAuto Off bypasses the complete custom VAuto wrapper and preserves
  stock VAuto pressure behavior.
- ASV Max and ASV Sens affect only adaptive boost. They have no effect while
  Custom VAuto is Off, and ASV Sens has no pressure effect while ASV Max is zero.
- In VAuto, Custom T/C has no effect while Custom VAuto is Off. In S, ST, T,
  and PAC it remains independently controlled.
- ASV and ASVAuto settings are not used by the custom VAuto behavior.

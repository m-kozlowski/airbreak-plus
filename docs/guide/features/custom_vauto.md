# Custom VAuto

The `stm32-asv-plus` builds can replace the stock VAuto within-breath
pressure-support behavior with Custom VAuto.

The therapy mode remains VAuto. Stock VAuto continues to control EPAP, and the
configured VAuto PS and Max IPAP settings remain in effect. Custom VAuto changes
how pressure support is delivered during inspiration and expiration, and can
add breath-by-breath adaptive support.

This is separate from the stock ASV and ASVAuto modes. It does not use their
settings and does not add a timed backup rate.

- select VAuto on the device
- use the normal VAuto pressure settings
- enable Custom VAuto in the clinical Therapy menu
- expect reports to identify the session as VAuto

<p align="center">
  <img src="../../images/custom-vauto-settings.png" alt="Custom VAuto settings in the clinical Therapy menu" width="240">
</p>

## Operating states

| Configuration | Pressure behavior |
|---------------|-------------------|
| Custom VAuto Off | Complete stock VAuto pressure behavior |
| Custom VAuto On, ASV Max zero | Custom inspiratory and expiratory pressure shape without adaptive boost |
| Custom VAuto On, ASV Max above zero | Custom pressure shape with breath-by-breath adaptive boost |

VAuto PS set to zero bypasses the custom wrapper. The device continues to run
the stock VAuto controller with zero pressure support: EPAP remains under stock
VAuto control, while custom pressure shaping, adaptive boost, expiratory relief,
pre-trigger assist, and Custom T/C are disabled.

## Controls

| Setting | UART | Range | Default | Menu | Visible modes | Function | Without `custom_settings` |
|---------|------|-------|---------|------|---------------|----------|---------------------------|
| Custom VAuto | `RPO` | Off, On | Off | Therapy | VAuto | Selects stock VAuto or the complete custom pressure-support path | On |
| ASV Max | `RCM` | 0.0 to 10.0 cmH2O, step 0.2 | 3.0 cmH2O | Therapy | VAuto | Limits adaptive boost above the custom base pressure shape; zero disables adaptive boost | `2 * VAuto PS` |
| ASV Sens | `RXM` | Very Low, Low, Med, High, Very High | Med | Therapy | VAuto | Scales the adaptive controller response | Med |
| Custom T/C | `RPH` | Off, On | Off | Therapy | S, ST, T, VAuto, PAC | Uses custom multi-signal trigger and flow-shape cycle decisions | On where supported by the runtime path |

Firmware variable assignments and persistence are listed in the
[custom settings registry](../../custom_settings.md#assignments).

ASV Sens uses these controller multipliers:

| Setting | Multiplier |
|---------|------------|
| Very Low | 0.50 |
| Low | 0.75 |
| Med | 1.00 |
| High | 1.25 |
| Very High | 1.50 |

Ti Min remains a normal VAuto timing setting. It is not used as the Custom VAuto
enable switch.

## Therapy behavior

### Stock behavior retained

Custom VAuto uses the stock VAuto pressure phase as its input, replaces the
within-breath pressure-support calculation, then passes the result through the
stock final pressure limiter.

| Behavior | Stock VAuto | Custom VAuto |
|----------|-------------|--------------|
| EPAP | Selected by the stock VAuto controller | Unchanged |
| Configured PS | Defines the difference between EPAP and full inspiratory pressure | Defines the nominal support range used by the custom pressure shape |
| Inspiration | Stock VAuto pressure waveform | Custom base shape with optional adaptive boost |
| Expiration | Stock pressure return toward EPAP | Custom downslope with calculated exhale relief |
| Trigger preparation | Stock response | May add up to 0.4 cmH2O of pre-trigger pressure assist |
| Trigger and cycle decisions | Configured stock thresholds | Stock thresholds or Custom T/C decisions |
| Final pressure | Limited by Max IPAP | Limited by the same stock Max IPAP path |
| Backup rate | None | None |
| Reported mode | VAuto | VAuto |

### Base pressure-support shape

Let:

- `PS` be the configured VAuto pressure support
- `x` be the stock VAuto pressure phase from 0 to 1
- `e` be the current expiratory offset, at or below zero

The non-adaptive custom support shape is:

```text
base(x) = 0.45 + lerp(e, PS - 0.45, x)
```

At full inspiration, `base(1) = PS`. During the transition, the custom curve
connects the expiratory offset to the configured support. This base shape
remains active when ASV Max is zero.

### Adaptive boost

The adaptive controller tracks recent valid breaths and builds a moving
reference breath. It does not use a fixed tidal-volume target. At roughly 50 ms
checkpoints it compares cumulative inspired volume with the reference at the
same point in the breath:

```text
volume_ratio(t) = current_volume(t) / reference_volume(t)
```

A ratio between approximately `0.94` and `0.96` is treated as neutral. Lower
values request more support. Higher values reduce the adaptive contribution,
but never below the custom base shape.

| Current breath | Response |
|----------------|----------|
| Smaller than the recent reference | Increase adaptive pressure support |
| Close to the recent reference | Stay near the custom base pressure shape |
| Larger than the recent reference | Reduce adaptive boost |

The controller output is scaled by ASV Sens and gradually enabled at the start
of inspiration:

```text
adaptive_factor =
    clamp(1 + sensitivity * PID(volume_error) * startup_ramp, 1, 2.5)
```

The adaptive branch uses a steeper pressure-phase curve:

```text
q(x) = 0.75x + 0.25(1 - (1 - x)^4)
```

The adaptive factor blends or scales this curve. ASV Max then places a relative
limit on the resulting support:

```text
support(x) = min(adaptive_shape(x), base(x) + ASV Max)
```

ASV Max is not an absolute pressure setting. ASV Sens changes the strength of
the controller response rather than adding a fixed pressure amount.

The adaptive response is stabilized by:

| Behavior | Purpose |
|----------|---------|
| Two-stage moving reference | Limits how strongly one breath can change the reference curve |
| Early-inspiration limiting | Gradually enables the adaptive factor at the start of inspiration |
| Boost engagement limiting | Limits the first breaths when adaptive boost engages or re-engages |
| Post-large-breath dampening | Temporarily lowers the neutral comparison range after an unusually large breath |

### Expiration and pre-trigger assist

The largest support reached during inspiration is retained as the start of the
expiratory downslope. After an inspiration lasting at least 0.7 seconds, the
initial exhale-relief magnitude is calculated as:

```text
relief = clamp(0.2 * (EPAP - PS), 0.4, 1.6)
relief = max(0, relief - 0.25 * (peak_support - PS))
```

The relief fades with remaining integrated breath volume and with current and
recent expiratory timing. The expiratory phase is curved as follows:

```text
x_exp = 0.25x + 0.75x^2
support_exp = lerp(exhale_offset, peak_support, x_exp)
```

During expiration, the wrapper also projects flow approximately 80 ms ahead.
When the projected flow crosses the trigger threshold and current flow is
positive, it can add 0.2 or 0.4 cmH2O of support before the detected inspiration.

### Trigger and cycle

Custom T/C is available in S, ST, T, VAuto, and PAC. The EasyBreathe pressure
waveform does not use Custom T/C.

Custom trigger combines:

- current positive patient flow
- accumulated positive-flow volume
- pressure below the current target
- proximity to the recent typical breath timing

The custom score takes control when commanded pressure is stable or the
projected flow indicates a likely inspiration. A score at or above `1.0` forces
inspiration; a lower score prevents an early trigger. At other times, the
configured stock trigger threshold remains in use.

Custom cycle compares basal-leak-corrected flow with the peak inspiratory flow
of the same breath. The configured Cycle setting supplies the stock fraction
`s`, from which the custom threshold is calculated:

```text
custom_cycle_fraction = 0.5s - 0.225
```

Expiration is selected when flow falls below that custom fraction of peak flow,
or when the stock cycle condition has remained present for approximately
600 ms. This delays cycling through short flow reductions while retaining a
bounded path to expiration.

When Custom T/C is Off, the configured stock trigger and cycle sensitivities
remain in use.

### Pressure limits

EPAP remains under stock VAuto control. The configured VAuto PS defines the
nominal full-inspiration support. ASV Max limits only the adaptive addition above
the custom base shape, while the stock final pressure limiter continues to apply
the configured Max IPAP ceiling.

A low Max IPAP can therefore limit adaptive support before ASV Max is reached.

## Backup rate

Custom VAuto does not provide timed backup breaths. Control of the stock ASV
and ASVAuto backup response is a separate
[ASV backup-rate feature](asv_backup_rate.md).

## Caveats

- Large leaks or unstable triggering can distort flow and volume tracking.
- The moving reference is updated only from breaths accepted as valid by the
  custom breath tracker.
- ASV and ASVAuto settings do not control Custom VAuto.

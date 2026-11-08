# Air 10 Therapy Float Variables

`fvars` is the shared RAM array used by therapy workers for flow and pressure
inputs, cached settings, intermediate results, and pressure commands.

## Table of contents

- [Storage and indexing](#storage-and-indexing)
- [Flow and pressure inputs](#flow-and-pressure-inputs)
- [Cached settings](#cached-settings)
- [Pressure commands and phase](#pressure-commands-and-phase)
- [Leak estimation](#leak-estimation)
- [Other results](#other-results)
- [SX584 correspondence](#sx584-correspondence)

## Storage and indexing

Each slot holds a little-endian IEEE-754 binary32 value. All slot indices in
this document are hexadecimal; `F[index]` denotes `fvars[index]`.

| Firmware | `fvars` base |
|----------|--------------|
| SX567-0302, 0305, 0306, 0401 | `0x2000E948` |
| SX567-0402 | `0x2000E954` |

These versions share the slot numbering in the main tables. Selected
SX584-0205 equivalents are listed under [SX584 correspondence](#sx584-correspondence).

```text
address(F[index]) = fvars_base + 4 * index
```

For example, `F[23]` is the float at offset `0x8C` from the array base.
Workers retain pointers into this array across updates.

The [CCX variable system](config_variables.md) supplies settings and receives
reported values. Its [RAM shadow](config_variables.md#ram-shadow) stores
descriptor-backed values separately from the therapy working floats.

Settings caches refresh when their owning settings component runs. Waveform
and flow workers update during therapy; other slots update on breath events.
Inactive workers can leave values from an earlier mode in their slots.

`TAG_raw` in the tables denotes the raw integer value of a UART variable.
Names and descriptor IDs are listed in the [variable reference](var_reference.tsv).

## Flow and pressure inputs

| Slot | Meaning | Units | Source / use |
|------|---------|-------|--------------|
| `00` | Flow after subtracting the selected mask's intentional vent estimate: `(HFL_raw - DFL_raw) * 0.12` | L/min | Flow measurement; input to adaptive leak estimation |
| `01` | Estimated mask pressure: `MKP_raw / 50` | cmH2O | Pressure measurement; compensation and control feedback |
| `03` | Calibrated blower flow: `BFL_raw * 0.12` | L/min | Flow measurement |
| `22` | Reference square root of mask pressure, paired with reference leak flow | sqrt(cmH2O) | Leak-reference blend; denominator for pressure-dependent leak estimation |
| `23` | Routed reference leak flow before adjustment to instantaneous pressure | L/min | Default router copies `F[44]` |
| `24` | Routed additional-leak estimate at instantaneous pressure | L/min | Default router copies `F[45]` |
| `25` | Routed patient flow after adaptive leak subtraction | L/min | Default router copies `F[47]` |
| `26` | Respiratory-flow input selected for downstream workers | L/min | Flow router; source selected by internal therapy profile |

### Respiratory-flow routing

The flow router selects the following sources for `F[26]`.
Profile numbers are internal runtime states, separate from `MOP` option indices.

| Router branch | Source | Flow supplied to downstream workers |
|---------------|--------|------------------------------------|
| Default | `F[46]` | Filtered compensated flow |
| Profiles 6 and 7 | `F[47]` | Unfiltered compensated flow, also routed to `F[25]` |
| Profile 9 | `F[6A]` | Alternate filtered flow used by the ASV path |

Profile 5 uses a separate flow router.
The respiratory-flow publisher exports `F[26]` through `RFL` when active.

## Cached settings

A slot's meaning depends on the active therapy settings component. Pressure
values are converted from descriptor raw units to cmH2O.

| Slot | Mode / context | Meaning |
|------|----------------|---------|
| `05` | CPAP | Ramp start pressure, `STP_raw / 50` |
| `05` | AutoSet / APAP | Ramp start pressure, `STU_raw / 50` |
| `05` | VAuto | Ramp start reference, `(STV_raw + floor(SPT_raw / 2)) / 50` |
| `05` | iVAPS | Ramp start EPAP, `IVS_raw / 50` |
| `06` | CPAP | Set pressure, `IPC_raw / 50` |
| `07` | Trigger-capable profiles | Effective trigger flow threshold, L/min |
| `08` | Cycle-capable profiles | Effective cycle threshold, fraction of peak inspiratory flow |
| `09` | AutoSet / APAP | Upper pressure bound, `MPA_raw / 50`; the activation path can substitute the minimum |
| `0A` | AutoSet / APAP | Lower pressure bound, `MPI_raw / 50` |
| `09` | VAuto | Upper working-pressure bound, `(MXI_raw - floor(SPT_raw / 2)) / 50` |
| `0A` | VAuto | Lower working-pressure bound, `(MNE_raw + floor(SPT_raw / 2)) / 50` |
| `0B` | VAuto | Configured PS, `SPT_raw / 50` |
| `0D` | Final pressure limiter | Upper pressure cap before FOT addition; VAuto activation loads the upper allowed bound of `MXI` |
| `0E` | S / ST / T / PAC | IPAP, `IPP_raw / 50` |
| `0F` | S / ST / T / PAC | EPAP, `EPP_raw / 50` |
| `0F` | iVAPS | Fixed EPAP, `EPI_raw / 50` |
| `18` | iVAPS | Target alveolar ventilation, `WMV_raw / 10`, L/min |
| `19` | iVAPS | Target patient rate, `IBR_raw / 5`, breaths/min |
| `1B` | iVAPS | Maximum PS, `WPA_raw / 50` |
| `1C` | iVAPS | Minimum PS, `WPM_raw / 50` |
| `1D` | iVAPS | Estimated dead-space volume, `ZDS_raw * 1000 / 500`, mL |
| `1E` | SmartStart | Positive flow threshold selected by `MSK`, L/min |
| `1F` | SmartStart | Negative flow threshold selected by `MSK`, L/min |

### VAuto pressure representation

VAuto uses a working-pressure reference centered between EPAP and IPAP.
With PS = 3, Min EPAP = 9, and Max IPAP = 25 cmH2O:

```text
F[09] = 25 - 3/2 = 23.5
F[0A] =  9 + 3/2 = 10.5
F[0B] = 3
```

The controller limits its reference with `F[09]` and `F[0A]`. Adding the
normal inspiratory half-PS to the upper bound gives the selected Max IPAP.

`F[0D]` holds the upper allowed bound of `MXI`. VAuto activation loads this
bound, initialized from `MXI.G4_MAX`. This is the setting's permitted
maximum, rather than the user's selected value. In the stock 37101 CCX it is
25 cmH2O; the [pressure-range patch](guide/features/general.md#clinical-settings-and-pressure-range)
raises it to 30 cmH2O.

### Trigger and cycle thresholds

`F[07]` holds the effective flow threshold in L/min. `F[08]` holds the
effective fraction of peak inspiratory flow: `0.45` represents 45%.

| Option | Label | Trigger, L/min | Cycle, iVAPS | Cycle, VAuto |
|--------|-------|----------------|--------------|--------------|
| 0 | Very Low | 13.2 | 0.08 | 0.15 |
| 1 | Low | 8.1 | 0.15 | 0.30 |
| 2 | Med | 4.8 | 0.25 | 0.45 |
| 3 | High | 3.3 | 0.35 | 0.60 |
| 4 | Very High | 1.8 | 0.50 | 0.75 |

Firmware stores cycle values as integer percentages and divides them by 100.
Custom T/C uses these configured values to prepare separate phase decisions;
its behavior is described in
[Custom VAuto](guide/features/custom_vauto.md#trigger-and-cycle).

## Pressure commands and phase

| Slot | Meaning | Units | Source / use |
|------|---------|-------|--------------|
| `20` | Commanded breath phase in S/VAuto/iVAPS: inspiration below 0.5, expiration from 0.5 | Cycle fraction | Breath-phase workers |
| `28` | Pressure reference before ramp processing; EPAP in iVAPS, midpoint pressure in VAuto | cmH2O | Mode-specific pressure generator; input to the ramp path |
| `29` | Additive pressure-waveform component relative to the ramped reference | cmH2O | Pressure-waveform publisher; final limiter input |
| `2A` | Therapy pressure command after waveform addition, upper limiting, and FOT addition | cmH2O | Final pressure limiter output |
| `2D` | Ramped pressure reference; ramped EPAP in iVAPS | cmH2O | Ramp output; final limiter input |
| `2E` | Remaining ramp time | Minutes | Ramp state |
| `34` | Forced oscillation technique (FOT) pressure excitation | cmH2O | Added after pressure limiting |
| `49` | Phase reference used to select the leak-estimation history window | Cycle fraction | Leak-history selection |
| `55` | Stock ASV phase estimate from weighted phase candidates | Cycle fraction | ASV phase estimator |
| `56` | Stock ASV phase difference | Cycle fraction | ASV phase estimator |
| `90` | VAuto waveform correction added to the cached baseline | cmH2O | VAuto pressure shaping; input to waveform publisher |

The final limiter combines the ramped reference and waveform component:

```text
F[2A] = min(F[2D] + F[29], F[0D]) + F[34]
```

In the stock VAuto waveform:

```text
F[29] = baseline - F[2D] + F[90]
```

`F[29]` is signed. Outside ramp transitions, it ranges around the midpoint
reference, from `-PS/2` at expiration to `+PS/2` at full inspiration.
`F[2A]` is an instantaneous command throughout the breath; mask-pressure
feedback is supplied separately through `F[01]`.

For example, a 10.5 cmH2O reference and PS of 3 cmH2O give commands of
9 cmH2O at expiration and 12 cmH2O at full inspiration, before FOT addition.

## Leak estimation

| Slot | Meaning | Units | Source / use |
|------|---------|-------|--------------|
| `27` | Adaptation value controlling the historical/current reference blend | Dimensionless | Phase adaptation; input to leak-reference blend |
| `3D` | Historical flow reference from the selected history window | L/min | Leak-history selection |
| `3E` | Historical square-root-pressure reference from the same window | sqrt(cmH2O) | Leak-history selection |
| `40` | Square root of current mask pressure | sqrt(cmH2O) | Leak-estimator input, from `F[01]` |
| `41` | Filtered residual flow | L/min | Leak-estimator input, from `F[00]` |
| `42` | Filtered square root of mask pressure | sqrt(cmH2O) | Leak-estimator input, from `F[40]` |
| `44` | Blended reference leak flow | L/min | Leak-reference blend; routed to `F[23]` |
| `45` | Additional-leak estimate at instantaneous pressure | L/min | Leak estimator; routed to `F[24]` |
| `46` | Filtered compensated patient flow | L/min | Fourth-order filter applied to `F[47]` |
| `47` | Unfiltered compensated patient flow, `F[00] - F[45]` | L/min | Leak estimator; routed to `F[25]` |
| `48` | Reference leak conductance, `F[44] / F[22]` | L/min/sqrt(cmH2O) | Updated on the pressure-scaled branch of the leak estimator |
| `B7` | Minimum reference square-root pressure for pressure-dependent leak scaling | sqrt(cmH2O) | Leak estimator compares against `F[22]` |

With sufficient reference pressure, the estimator scales reference leak flow
by the ratio of current and reference square-root pressures:

```text
F[45] = F[44] / F[22] * F[40]
F[47] = F[00] - F[45]
```

When the reference pressure is insufficient, it uses `F[44]` directly as
`F[45]` and retains the previous `F[48]`. Reference flow and estimated leak
are signed and can be negative.

## Other results

| Slot | Meaning | Units | Source / use |
|------|---------|-------|--------------|
| `B5` | Relative deviation of achieved alveolar ventilation from Target Va: `(achieved_Va - F[18]) / F[18]` | Dimensionless | iVAPS ventilation estimator; input to rate adaptation |
| `D0` | Filtered respiratory flow for SmartStart's positive/negative excursion detector | L/min | SmartStart detector, from `F[26]` |

## SX584 correspondence

The following slots have corresponding roles in the iVAPS paths of the two
firmware families. The mapping is not a fixed offset between arrays.

| Meaning | Units | SX567 | SX584-0205 |
|---------|-------|-------|------------|
| Target alveolar ventilation | L/min | `18` | `1A` |
| Dead-space volume | mL | `1D` | `1F` |
| iVAPS breath phase | Cycle fraction | `20` | `24` |
| Routed reference leak flow | L/min | `23` | `27` |
| Unfiltered compensated flow | L/min | `25` | `29` |
| Filtered compensated flow used by AutoEPAP | L/min | `46` | `2A` |
| EPAP command before ramp | cmH2O | `28` | `2C` |
| Ramped EPAP | cmH2O | `2D` | `31` |
| Remaining ramp time | Minutes | `2E` | `33` |
| Relative Target Va deviation | Dimensionless | `B5` | `BB` |

SX584-0205 native AutoEPAP uses `F[D7]` for current EPAP and `F[D8]` for
target EPAP.

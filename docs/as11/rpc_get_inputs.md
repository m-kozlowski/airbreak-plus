# Air11 RPC Get and Set Reference

The [`Get`](rpc_protocol.md#get) and [`Set`](rpc_protocol.md#set) methods use
case-sensitive names from the Air11 data model. `Get` reads individual values
and complete objects. `Set` writes individual settings.

## Contents

- [Addressing model](#addressing-model)
- [Individual variables](#individual-variables)
- [Object selectors](#object-selectors)
- [Settings and profiles](#settings-and-profiles)
- [Field schemas and limits](#field-schemas-and-limits)
- [Identification](#identification)
- [Device state and configuration values](#device-state-and-configuration-values)
- [Data delivery and metrics](#data-delivery-and-metrics)
- [Manufacturing data](#manufacturing-data)
- [Errors](#errors)

## Addressing Model

Individual variables can be addressed by long name or by an underscored
three-character tag. Both forms select the same value:

| Form | Examples |
|------|----------|
| Long name | `ActiveTherapyProfile`, `RampTime`, `SerialNumber` |
| Short tag | `_MOP`, `_RMT`, `_SRN` |

Named object selectors such as `TherapyProfiles` and `VAutoProfile` return
structured, read-only views. Their individual fields are written through the
corresponding long variable name or short tag.

`Get` accepts a non-empty array containing one or more variable names or object
selectors:

```json
{
  "jsonrpc": "1.0",
  "method": "Get",
  "id": 1,
  "params": ["ActiveTherapyProfile", "VAutoProfile", "_SRN"]
}
```

Enum values are normally returned as symbolic strings. Numeric values are
returned in the units exposed by the data model.

`Set` accepts an object whose keys are individual variable names:

```json
{
  "jsonrpc": "1.0",
  "method": "Set",
  "id": 1,
  "params": {
    "RampEnable": "Auto",
    "RampTime": 20
  }
}
```

The value type must match the setting: enum labels are strings, numeric
settings are numbers, and boolean settings are JSON booleans. Underscored
short tags can also be used when the corresponding variable is writable.

Therapy-profile settings use mode-prefixed write names. For example, the
`MaxInspiratoryPressure` field returned by `VAutoProfile` is written as
`VAuto-MaxInspiratoryPressure`. Feature settings generally use the same field
name shown in the feature object, such as `RampEnable` or `EprEnable`.

A recognized variable can be unavailable on a particular product variant or
in the current device state. `Get` reports it as `InvalidObject`.

## Individual Variables

The complete mapping of known long names and short tags is maintained in the
[variable reference](var_reference.tsv). The [`as11_config.py` known
command](../tools/as11_config.md#known) provides an offline searchable catalog.

## Object Selectors

The selectors below are predefined `Get` targets beyond individual variables.
They are not accepted as `Set` keys.

### Settings and Profiles

| Selector | Result |
|----------|--------|
| `SettingProfiles` | top-level settings-profile object |
| `ActiveProfiles` | selected therapy profile and the active feature-profile names |
| `_ActiveFeatureProfiles` | active feature-profile names without the enclosing `ActiveProfiles` object |
| `TherapyProfiles` | therapy profile objects exposed by the current product configuration |
| `FeatureProfiles` | feature profile objects exposed by the current product configuration |
| `AlarmProfiles` | alarm settings object |

For example, `ActiveProfiles` has this form:

```json
{
  "ActiveProfiles": {
    "TherapyProfile": "VAutoProfile",
    "FeatureProfiles": [
      "AutoRampFeature",
      "SmartStartStopFeature",
      "CircuitFeature",
      "ClimateFeature"
    ]
  }
}
```

`TherapyProfiles` returns the available profile objects and their settings. It
does not identify the selected mode; that is reported by `ActiveProfiles` or
the `ActiveTherapyProfile` variable.

An individual therapy-profile selector returns only that mode's fields:

| Therapy family | Selector |
|----------------|----------|
| CPAP | `CpapProfile` |
| AutoSet | `AutoSetProfile` |
| AutoSet for Her | `AutoSetForHerProfile` |
| Spontaneous | `SpontProfile` |
| Spontaneous/Timed | `STProfile` |
| Timed | `TimedProfile` |
| VAuto | `VAutoProfile` |
| ASV | `ASVProfile` |
| ASVAuto | `ASVAutoProfile` |
| iVAPS | `iVAPSProfile` |
| PAC | `PACProfile` |

`_ActiveFeatureProfiles` lists the feature profiles enabled by the current
product configuration. Their values are returned under `FeatureProfiles`.
Only profiles marked below as direct selectors can also be requested by name.

| Feature profile | Contents | Direct `Get` selector |
|-----------------|----------|-----------------------|
| `ComfortFeature` | `AutoSetComfort` | yes |
| `EprFeature` | EPR enable, type, pressure, and patient access | yes |
| `AutoRampFeature` | maximum and selected ramp time, enable, and patient access | yes |
| `SmartStartStopFeature` | SmartStart and SmartStop settings | yes |
| `CircuitFeature` | mask, tube, and antibacterial-filter settings | yes |
| `ClimateFeature` | humidifier, heated-tube, and climate-control settings | yes |
| `LanguageFeature` | language configuration, language, and language-selection access | no |
| `UserSolutionFeature` | survey personalization state | no |
| `TemperatureFeature` | temperature unit | no |
| `CareCheckFeature` | Care Check toggle | no |
| `TimeZoneFeature` | time-zone offset | no |
| `DeviceHealthFeature` | SoundCheck toggle and run frequency | no |
| `PatientViewFeature` | patient view and AHI display | no |
| `ReminderFeature` | mask, tubing, filter, and humidifier reminders | no |
| `DisplayFeature` | usage, splash-screen, cycle-display, Care Check, myAir, and clinical-confirmation display settings | no |
| `ConfirmStopFeature` | therapy-stop confirmation | no |
| `TherapyLEDFeature` | therapy LED behavior | no |
| `RampDownFeature` | maximum and selected ramp-down time, enable, and patient access | yes |
| `HeightFeature` | height unit | no |
| `MaskSenseFeature` | MaskSense toggle | no |

### Field Schemas and Limits

These selectors describe the fields exposed by a profile, including enum
choices and numeric limits:

| Selector | Describes |
|----------|-----------|
| `TherapyProfilesConfiguration` | therapy profile fields |
| `FeatureProfilesConfiguration` | feature profile fields |
| `AlarmProfilesConfiguration` | alarm profile fields |
| `RealTimeDataConfiguration` | real-time measurement fields |

### Identification

| Selector | Result |
|----------|--------|
| `IdentificationProfiles` | flow-generator product, hardware, and software identification |
| `CellularIdentificationProfiles` | cellular-module identification |
| `DeviceRegistration` | device-registration identification object |

### Device State and Configuration Values

| Selector | Result |
|----------|--------|
| `_CurrentDateTime` | current device date and time as an ISO 8601 string |
| `CellularModule` | cellular-module identification and configuration object |
| `DeviceControl` | device control and state object |
| `ConfigurationProfiles` | current flow-generator configuration values |
| `CellularConfigurationProfiles` | current cellular configuration values |
| `DeviceConfigurationSettings` | device configuration settings object |
| `DynamicMessage` | current dynamic-message object |

### Data Delivery and Metrics

| Selector | Result |
|----------|--------|
| `DataDeliveryControl` | current data-delivery controls |
| `StoredDataDeliveryControl` | stored data-delivery controls |
| `MachineMetrics` | current machine metrics |
| `CellularDataUsage` | current cellular data-usage metrics |


### Manufacturing Data

| Selector | Result |
|----------|--------|
| `ManufacturingData` | Base64-encoded manufacturing data block |
| `ManufacturingTestRecord` | Base64-encoded manufacturing test record |

## Errors

`Get` returns `InvalidObject` when a requested value is unavailable. In a
mixed request, successfully read values are retained in the error's `data`
object alongside `InvalidObjects`.

`Set` returns `SettingApplicationFailure` when firmware rejects a value. A
multi-setting request is not transactional: settings accepted before the
failure may already have been applied.

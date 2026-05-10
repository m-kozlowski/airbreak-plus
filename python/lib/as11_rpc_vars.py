"""AS11 RPC-surface name catalog.

Enumerations of valid RPC parameter values (variable names, spool
types, stream/event ids, etc.).

Contents:
    VAR_GROUPS                   Get/Set firmware-subtree-keyed var groups
    resolve_group/expand_groups  helpers for CLI --group expansion
    SPOOL_REGISTRY               single source of truth for StartSpool spool types
    SPOOL_TYPES                  StartSpool valid spool_type values (derived)
    SPOOL_GROUPS                 grouped display order for `known spools` (derived)
    SPOOL_FORMATS                per-type format hint (derived)
    SPOOL_FAMILIES               per-type protobuf family (derived)
    SPOOL_FIELDS                 wire_field -> [spool_type, ...] autodetect (derived)
    STREAM_DATA_IDS              StartStream valid data_ids
    EVENT_IDS                    SubscribeEvent valid event names
    VAR_NAMES                    [(long_name, short_tag), ...] every known var
    VAR_SUBTREES                 names that Get accepts as aggregate-subtree targets
    VAR_MODE_PREFIXES            human-friendly therapy-mode prefix groupings
    VAR_TOPIC_KEYWORDS           human-friendly topic substring groupings
    REGISTRIES                   {action: (data, description)} for `known`
    filter_vars/var_groups_summary/print_var_pairs   helpers for `known`

"""

from __future__ import annotations


VAR_GROUPS: dict[str, list[str]] = {
    "ConfigurationProfiles": [
        "DataMode",
        "ServiceHost",
        "ServicePort",
        "PeriodicBrokerContactPeriod",
        "UpgradeAbandonPeriod",
        "UpgradeReportPeriod",
        "OtaUpgradeStatus",
        "DataCollectAndSend",
        "DataCollectAndSendAsync",
        "DownloadBytesDelta",
        "UploadBytesDelta",
        "LastDataPostDateTime",
    ],
    "Network": [
        "AccessPointName",
    ],
    "DeviceConfiguration": [
        "FlightMode", "VALOTriggerSeconds",
        "RequestTestDriveState", "TestDrivePressure", "TestDriveType",
        "ExpiratoryPressure", "LearnTargetsExpiratoryPressure",
        "LearnTargetsPressureSupport", "LearnTargetsSetDuration",
        "HardwareIdentifier", "UniversalIdentifier", "SerialNumber",
        "ProductCode", "ProductName", "FdaUniqueDeviceIdentifier",
        "ProductGeographicIdentifier", "BootloaderIdentifier",
        "ApplicationIdentifier", "ConfigurationIdentifier",
        "PlatformIdentifier", "VariantIdentifier", "RegionIdentifier",
        "ProfileVariantIdentifier", "DataVersionIdentifier",
        "DataModelVersionIdentifier",
    ],
    "ManufacturingSettings": [
        "PhantomKey", "RequestLEDState", "CalibrationPressure",
        "SetMotorSpeed", "BluetoothPassthrough", "HumidifierPower",
        "HeatedTubePower", "RequestSDCardTest", "RequestLCDColour",
        "MotorFlowDrive", "MicrophoneEnabled", "SoundDownloadAllowed",
        "SoundcheckTestCount", "CALEnable",
        "MotorCurrent", "MotorSpeed", "AdcPressure",
        "AdcPressureMonitoring", "RawFlow",
        "RawAmbHumidity", "RawAmbTemperature", "RawAmbLight",
        "ButtonRegMap", "CurrentLEDState", "EndCapDetection",
        "LCDTouchStatus", "LCDConnector", "SDCardTestStatus",
        "SDCardSocketStatus", "IsReadyForShipping", "IsReadyForUpgrade",
        "IsFileSystemReady", "MotorType", "EraseMediaSignature",
        "SoundcheckStatus", "CALStatus", "SecurityStatus",
        "PressureGain", "PressureOffset", "FlowGain", "FlowOffset",
        "PressureMonitorGain", "PressureMonitorOffset",
        "LastTherapyUseDateTime", "LastEraseDataDateTime",
        "TherapyRunMeter", "MotorRunMeter",
        "MotorRunSinceLastServiceMeter", "MachineRunMeter",
        "LastMachineServiceDateTime",
        "AmbientHumidity-Estimated", "AmbientTemperature-Estimated",
        "AmbientLight", "FGState", "TestDriveState",
        "SystemError", "RecoverableError", "ActiveAlarms",
        "PowerSupplyType", "PowerSupplyCapacity", "TxLink2Connected",
        "HumidifierConnected", "TubeConnected",
        "BlowerFlow-100hz", "BlowerPressure-100hz",
        "HumidifierPlateCurrent", "HeatedTubeCurrent", "HumidifierPWM",
        "HumidifierPWMMinuteAverage", "HeatedTubePWM",
        "HeatedTubePWMMinuteAverage", "BlowerPressureMonitoring",
        "HumidifierPlateTemperature",
        "HumidifierPlateTemperatureMinuteAverage",
        "HeatedTubeOutletTemperature",
        "HeatedTubeOutletTemperatureMinuteAverage",

        "CalManufacturingMode", "DeviceIdStatus", "LearnMode",
        "CepstrumAverageCount", "CepstrumStartDelay",
        "CamlData", "ApplicationData", "PeripheralMsg",
        "OobxOnStartup", "PhantomTouch",
        "SettingsHistoryChangeCount", "StorageVersionId",
        "TOTAL_USED_HOURS_NAME",
    ],
    "TherapyProfile": [
        "ActiveTherapyProfile",
    ],
    "AlarmProfiles": [
        "AlarmVolumeLevel",
        "ApneaAlarmEnable", "ApneaAlarmThreshold",
        "HighLeakAlarmEnable",
        "LowMinuteVentAlarmEnable", "LowMinuteVentAlarmThreshold",
        "NonVentedMaskAlarmEnable",
    ],
    "FeatureProfiles": [
        # Ramp / AutoRamp / RampDown
        "MaxRampTime", "RampTime", "RampEnable", "RampEnablePatientAccess",
        "MaxRampDownTime", "RampDownTime", "RampDownEnable",
        "RampDownEnablePatientAccess",
        # Circuit
        "MaskType", "TubeType", "AntiBacterialFilter",
        # Climate / humidifier
        "ClimateControl", "HumidifierSettingEnable", "HumidifierLevel",
        "HeatedTubeSettingEnable", "HeatedTubeTemperature",
        "ExternalHumidifier",
        # Comfort
        "AutoSetComfort",
        # Confirm-stop
        "ConfirmStopEnable",
        # Care check
        "CareCheckToggle", "CareCheckInAvailable",
        # Device health / user solution
        "SoundcheckFeatureToggle", "SoundcheckRunFrequency",
        "ClinicalConfirmation", "MyAirScreens",
        # Display
        "TotalUsedHoursDisplayToggle", "SplashScreenDisplaySelection",
        "CycleDisplayFormat", "DisplayAHI",
        # EPR
        "EprEnablePatientAccess", "EprEnable", "EprType", "EprPressure",
        # Height
        "HeightDisplayUnit",
        # Language
        "LanguageConfiguration", "Language", "LanguageSelection",
        # Mask sense
        "MaskSenseToggle",
        # Patient view
        "PatientView",
        # Reminders
        "ReminderFilterEnable", "ReminderFilterDate", "ReminderFilterPeriod",
        "ReminderHumidifierEnable", "ReminderHumidifierDate",
        "ReminderHumidifierPeriod", "ReminderMaskEnable",
        "ReminderMaskDate", "ReminderMaskPeriod", "ReminderTubingEnable",
        "ReminderTubingDate", "ReminderTubingPeriod",
        # Smart start/stop
        "SmartStart", "SmartStop",
        # Temperature
        "TemperatureUnit",
        # Therapy LED
        "TherapyLEDAlwaysOn",
        # Time zone
        "TimeZoneOffset",
    ],
    "TherapyMode": [
        "ASVAuto-MinExpiratoryPressure", "ASVAuto-MaxExpiratoryPressure",
        "ASVAuto-StartPressure", "ASVAuto-MinPressureSupport",
        "ASVAuto-MaxPressureSupport", "ASV-TargetExpiratoryPressure",
        "ASV-MinPressureSupport", "ASV-MaxPressureSupport",
        "ASV-StartPressure", "HerAuto-MaxPressure", "HerAuto-MinPressure",
        "HerAuto-StartPressure", "AutoSet-MaxPressure",
        "AutoSet-MinPressure", "AutoSet-StartPressure", "Cpap-SetPressure",
        "Cpap-StartPressure", "Cpap-TriggerSensitivity",
        "PAC-TargetInspiratoryPressure", "PAC-TargetExpiratoryPressure",
        "PAC-StartPressure", "PAC-SetRespiratoryRate",
        "PAC-SetInspiratoryTime", "PAC-RiseTimeEnable", "PAC-RiseTime",
        "PAC-FallTimeEnable", "PAC-FallTime", "PAC-TriggerSensitivity",
        "ST-TargetInspiratoryPressure", "ST-TargetExpiratoryPressure",
        "ST-StartPressure", "ST-IntelligentBackupRateEnable",
        "ST-TargetRespiratoryRate", "ST-SetRespiratoryRate",
        "ST-SetMaxInspiratoryTime", "ST-SetMinInspiratoryTime",
        "ST-RiseTimeEnable", "ST-RiseTime", "ST-FallTimeEnable",
        "ST-FallTime", "ST-TriggerSensitivity", "ST-CycleSensitivity",
        "Spont-TargetInspiratoryPressure", "Spont-TargetExpiratoryPressure",
        "Spont-StartPressure", "Spont-RespiratoryRateEnable",
        "Spont-SetMaxInspiratoryTime", "Spont-SetMinInspiratoryTime",
        "Spont-EasyBreatheEnable", "Spont-RiseTimeEnable", "Spont-RiseTime",
        "Spont-FallTimeEnable", "Spont-FallTime",
        "Spont-TriggerSensitivity", "Spont-CycleSensitivity",
        "Timed-TargetInspiratoryPressure", "Timed-TargetExpiratoryPressure",
        "Timed-StartPressure", "Timed-SetRespiratoryRate",
        "Timed-SetInspiratoryTime", "Timed-RiseTimeEnable", "Timed-RiseTime",
        "Timed-FallTimeEnable", "Timed-FallTime",
        "VAuto-MaxInspiratoryPressure", "VAuto-MinExpiratoryPressure",
        "VAuto-StartPressure", "VAuto-SetMaxInspiratoryTime",
        "VAuto-SetMinInspiratoryTime", "VAuto-SetPressureSupport",
        "VAuto-TriggerSensitivity", "VAuto-CycleSensitivity",
        "iVAPS-PatientHeight", "iVAPS-AutoEPAPEnable",
        "iVAPS-MaxExpiratoryPressure", "iVAPS-MinExpiratoryPressure",
        "iVAPS-TargetExpiratoryPressure", "iVAPS-MinPressureSupport",
        "iVAPS-MaxPressureSupport", "iVAPS-StartPressure",
        "iVAPS-TargetAlveolarVentilation", "iVAPS-TargetRespiratoryRate",
        "iVAPS-SetMaxInspiratoryTime", "iVAPS-SetMinInspiratoryTime",
        "iVAPS-RiseTimeEnable", "iVAPS-RiseTime", "iVAPS-FallTimeEnable",
        "iVAPS-FallTime", "iVAPS-TriggerSensitivity",
        "iVAPS-CycleSensitivity",
    ],
    "CellularModule": [
        "CellularApplicationIdentifier",
        "CellularProductModel",
        "CellularProductProvider",
        "CellularDataPreamble",
        "IMEI",
        "IMSI",
        "SIMID",
    ],
    "BluetoothModule": [
        "BluetoothApplicationIdentifier",
        "BluetoothBootloaderIdentifier",
        "BluetoothName",
        "BluetoothPassthrough",
        "BluetoothProductModel",
        "BluetoothProductProvider",
    ],
    "TherapyMeasurements": [
        "RespiratoryEvent", "StatusEvent", "IsRamping", "TriggerCycleEvent",
        "IsRampingDown",
        "InspiratoryPressure", "ExpiratoryPressure", "RespiratoryRate",
        "HeartRate", "SpO2", "IeRatio", "Leak", "RawLeak",
        "MinuteVentilation", "TidalVolume", "AlveolarMinuteVentilation",
        "InspiratoryDuration", "ExpiratoryDuration",
        "TargetMinuteVentilation", "FlowLimitation", "SnoreIndex",
        "RemainingRampTime", "RemainingRampDownTime",
        "MaskPressure", "SetPressureWithoutCAD", "PatientFlow",
        "ExpirationSetPressure", "InspirationSetPressure", "CpapSetPressure",
    ],
}


def resolve_group(name: str) -> str | None:
    """Return canonical VAR_GROUPS key for `name`, or None if not present"""
    if name in VAR_GROUPS:
        return name
    lower_map = {k.lower(): k for k in VAR_GROUPS}
    return lower_map.get(name.lower())


def expand_groups(group_names: list[str]) -> list[str]:
    """Expand a list of --group arguments into the variable name list"""
    out: list[str] = []
    for g in group_names:
        canon = resolve_group(g)
        if canon is None:
            known = ", ".join(sorted(VAR_GROUPS))
            raise ValueError(f"unknown group {g!r}; known: {known}")
        out.extend(VAR_GROUPS[canon])
    return out



# Single source of truth for spool types. Each entry covers:
#   group       display group used by `known spools`/--list-types
#   format      one-line human description of the on-wire payload
#   family      structural class used for dispatch in as11_spool.py
#               (one of: summary, profile, config, event, periodic,
#                periodic_compressed, metric, rc03, diag_vector,
#                diag_blob, audio)
#   wire_field  outer protobuf field number observed on a populated
#               spool, or None when the spool has not yet been seen
#               with data on a test device. Multiple spools may share
#               a wire_field (event subfamilies do).
#   gate_var    name of the firmware setting that must be enabled for
#               the dispatcher to accept this spool. Optional.
#
# Insertion order is preserved and drives both SPOOL_TYPES and the
# grouped display in SPOOL_GROUPS, so keep entries clustered by group.
SPOOL_REGISTRY: dict[str, dict] = {
    # session/profile data
    "Summary": {
        "group": "session/profile data",
        "format": "summary protobuf",
        "family": "summary",
        "wire_field": 2,
    },
    "SettingProfilesCollection": {
        "group": "session/profile data",
        "format": "profile snapshot protobuf",
        "family": "profile",
        "wire_field": 3,
    },
    "ConfigurationProfilesCollection": {
        "group": "session/profile data",
        "format": "config snapshot protobuf",
        "family": "config",
        "wire_field": 23,
    },

    # therapy data
    "UsageEvents-TherapyStatusEvents": {
        "group": "therapy data",
        "format": "event protobuf",
        "family": "event",
        "wire_field": 6,
    },
    "TherapyEvents-RespiratoryEvents": {
        "group": "therapy data",
        "format": "event protobuf",
        "family": "event",
        "wire_field": None,
    },
    "TherapyOneMinutePeriodic": {
        "group": "therapy data",
        "format": "periodic protobuf",
        "family": "periodic",
        "wire_field": 5,
    },

    # system and diagnostic events
    "SystemActivityEvents-FrequentActivityEvents": {
        "group": "system and diagnostic events",
        "format": "event protobuf",
        "family": "event",
        "wire_field": 10,
    },
    "SystemActivityEvents-SporadicActivityEvents": {
        "group": "system and diagnostic events",
        "format": "event protobuf",
        "family": "event",
        "wire_field": 10,
    },
    "SystemExceptionEvents-SystemErrors": {
        "group": "system and diagnostic events",
        "format": "error event protobuf",
        "family": "event",
        "wire_field": None,
    },
    "SystemExceptionEvents-RecoverableErrors": {
        "group": "system and diagnostic events",
        "format": "error event protobuf",
        "family": "event",
        "wire_field": 7,
    },
    "SystemExceptionEvents-HumidifierErrors": {
        "group": "system and diagnostic events",
        "format": "error event protobuf",
        "family": "event",
        "wire_field": None,
    },
    "SystemExceptionEvents-HeatedTubeErrors": {
        "group": "system and diagnostic events",
        "format": "error event protobuf",
        "family": "event",
        "wire_field": None,
    },
    "DiagnosticExceptionEvents-AppErrors": {
        "group": "system and diagnostic events",
        "format": "error event protobuf",
        "family": "event",
        "wire_field": 9,
    },
    "DiagnosticExceptionEvents-FatalErrors": {
        "group": "system and diagnostic events",
        "format": "error event protobuf",
        "family": "event",
        "wire_field": None,
    },
    "DiagnosticExceptionEvents-ResettableErrors": {
        "group": "system and diagnostic events",
        "format": "error event protobuf",
        "family": "event",
        "wire_field": None,
    },
    "DiagnosticExceptionEvents-AlarmAppErrors": {
        "group": "system and diagnostic events",
        "format": "error event protobuf",
        "family": "event",
        "wire_field": None,
    },
    "GUIActivityEvents": {
        "group": "system and diagnostic events",
        "format": "event protobuf",
        "family": "event",
        "wire_field": 13,
    },
    "SurveyEvents": {
        "group": "system and diagnostic events",
        "format": "event protobuf",
        "family": "event",
        "wire_field": None,
    },
    "alarmEvents": {
        "group": "system and diagnostic events",
        "format": "event protobuf",
        "family": "event",
        "wire_field": None,
    },
    "alarmDiagnosticEvents": {
        "group": "system and diagnostic events",
        "format": "event protobuf",
        "family": "event",
        "wire_field": None,
    },

    # periodic metrics
    "DiagnosticTenMinutePeriodic": {
        "group": "periodic metrics",
        "format": "periodic compressed (two-stream)",
        "family": "periodic_compressed",
        "wire_field": 17,
    },
    "MachineMetrics": {
        "group": "periodic metrics",
        "format": "metric snapshot",
        "family": "metric",
        "wire_field": 8,
    },
    "MemoryMetrics": {
        "group": "periodic metrics",
        "format": "metric snapshot",
        "family": "metric",
        "wire_field": 16,
    },
    "CellularActivityEvents": {
        "group": "periodic metrics",
        "format": "event protobuf",
        "family": "event",
        "wire_field": 12,
    },
    "CellularDataUsage": {
        "group": "periodic metrics",
        "format": "metric snapshot",
        "family": "metric",
        "wire_field": 22,
    },

    # archived signals
    "atmosphericPressure10min": {
        "group": "archived signals",
        "format": "periodic compressed (two-stream)",
        "family": "periodic_compressed",
        "wire_field": None,
    },
    "RespiratoryFlow6p25Hz": {
        "group": "archived signals",
        "format": "RC03 compressed signal",
        "family": "rc03",
        "wire_field": 18,
    },
    "MaskPressure6p25Hz": {
        "group": "archived signals",
        "format": "RC03 compressed signal",
        "family": "rc03",
        "wire_field": 19,
    },
    "InspiratoryPressure0p5Hz": {
        "group": "archived signals",
        "format": "RC03 compressed signal",
        "family": "rc03",
        "wire_field": 21,
    },
    "Leak0p5Hz": {
        "group": "archived signals",
        "format": "RC03 compressed signal",
        "family": "rc03",
        "wire_field": 20,
    },

    # diagnostic blobs
    "SoundcheckVector": {
        "group": "diagnostic blobs",
        "format": "diagnostic vector",
        "family": "diag_vector",
        "wire_field": 15,
    },
    "AcousticSignatureV2": {
        "group": "diagnostic blobs",
        "format": "diagnostic acoustic blob",
        "family": "diag_blob",
        "wire_field": None,
    },
    "RecordedSound": {
        "group": "diagnostic blobs",
        "format": "audio recording (gated by SoundDownloadAllowed)",
        "family": "audio",
        "wire_field": None,
        "gate_var": "SoundDownloadAllowed",
    },
}


def _build_spool_groups() -> list[tuple[str, list[str]]]:
    """Group entries by `group`, preserving registry insertion order."""
    out: list[tuple[str, list[str]]] = []
    by_title: dict[str, list[str]] = {}
    for name, info in SPOOL_REGISTRY.items():
        title = info["group"]
        if title not in by_title:
            by_title[title] = []
            out.append((title, by_title[title]))
        by_title[title].append(name)
    return out


SPOOL_TYPES: list[str] = list(SPOOL_REGISTRY)

SPOOL_GROUPS: list[tuple[str, list[str]]] = _build_spool_groups()

SPOOL_FORMATS: dict[str, str] = {
    name: info["format"] for name, info in SPOOL_REGISTRY.items()
}

SPOOL_FAMILIES: dict[str, str] = {
    name: info["family"] for name, info in SPOOL_REGISTRY.items()
}


def _build_spool_fields() -> dict[int, list[str]]:
    """Map outer-wrapper wire field number -> list of spool names."""
    out: dict[int, list[str]] = {}
    for name, info in SPOOL_REGISTRY.items():
        field = info.get("wire_field")
        if field is None:
            continue
        out.setdefault(field, []).append(name)
    return out


SPOOL_FIELDS: dict[int, list[str]] = _build_spool_fields()


def spool_info(spool_type: str) -> dict | None:
    """Return the registry entry for spool_type, or None."""
    return SPOOL_REGISTRY.get(spool_type)


def spool_types_in_family(family: str) -> list[str]:
    """All spool types whose `family` field equals `family`."""
    return [name for name, info in SPOOL_REGISTRY.items()
            if info["family"] == family]
# Direct StartStream names embedded in the 15.8.4 APPL image.
STREAM_DIRECT_GROUPS = [
    ("live waveform/control data IDs", [
        "PatientFlow-100hz",
        "MaskPressure-100hz",
        "BlowerFlow-100hz",
        "BlowerPressure-100hz",
        "SetPressure-100hz",
    ]),
    ("therapy/respiratory data IDs", [
        "InspiratoryPressure-50hz",
        "ExpiratoryPressure-50hz",
        "ApneaTreatmentPressure-50hz",
        "AutoSetTreatmentPressure-50hz",
        "FlowLimitationTreatmentPressure-50hz",
        "FlowLimitation-50hz",
        "Leak-50hz",
        "RawLeak-50hz",
        "MinuteVentilation-50hz",
        "TargetMinuteVentilation",
        "IeRatio",
        "InspiratoryDuration",
        "RespiratoryRate-50hz",
        "TidalVolume-50hz",
        "SnoreIndex-50hz",
        "SnoreTreatmentPressure-50hz",
        "RemainingRampTime-50hz",
    ]),
    ("oximetry data IDs", [
        "HeartRate",
        "SpO2",
    ]),
    ("downsampled/estimated live data IDs", [
        "MaskPressure-TwoSecond",
        "InspiratoryPressure-TwoSecond",
        "ExpiratoryPressure-TwoSecond",
        "MaskPressure-OneMinute",
        "InspiratoryPressure-OneMinute",
        "BlowerPressure-OneMinute",
        "AmbientHumidity-Estimated",
        "AmbientTemperature-Estimated",
    ]),
]

STREAM_DIRECT_DATA_IDS = [
    item for _title, group_items in STREAM_DIRECT_GROUPS
    for item in group_items
]

# Summary data IDs are accepted by StartStream too. They are session/statistic
# values rather than waveform signals, but valid:true on the device.
STREAM_SUMMARY_DATA_IDS = [
    "Summary-AmbientHumidity-50",
    "Summary-ApneaHypopneaIndex",
    "Summary-ApneaIndex",
    "Summary-BlowerFlow-50",
    "Summary-BlowerPressure-5",
    "Summary-BlowerPressure-95",
    "Summary-CentralApneaIndex",
    "Summary-ExpiratoryPressure-100",
    "Summary-ExpiratoryPressure-50",
    "Summary-ExpiratoryPressure-95",
    "Summary-HeartRate-100",
    "Summary-HeartRate-50",
    "Summary-HeartRate-95",
    "Summary-HeatedTubePower-50",
    "Summary-HeatedTubeTemperature-50",
    "Summary-HumidifierConnected",
    "Summary-HumidifierPower-50",
    "Summary-HumidifierTemperature-50",
    "Summary-HypopneaIndex",
    "Summary-IeRatio-100",
    "Summary-IeRatio-50",
    "Summary-IeRatio-95",
    "Summary-InspiratoryDuration-100",
    "Summary-InspiratoryDuration-50",
    "Summary-InspiratoryDuration-95",
    "Summary-InspiratoryPressure-100",
    "Summary-InspiratoryPressure-50",
    "Summary-InspiratoryPressure-95",
    "Summary-Leak-100",
    "Summary-Leak-50",
    "Summary-Leak-75",
    "Summary-Leak-95",
    "Summary-MeanMaskPressure-100",
    "Summary-MeanMaskPressure-50",
    "Summary-MeanMaskPressure-95",
    "Summary-MinuteVentilation-100",
    "Summary-MinuteVentilation-50",
    "Summary-MinuteVentilation-95",
    "Summary-ObstructiveApneaIndex",
    "Summary-ReraIndex",
    "Summary-RespiratoryFlow-5",
    "Summary-RespiratoryFlow-95",
    "Summary-RespiratoryRate-100",
    "Summary-RespiratoryRate-50",
    "Summary-RespiratoryRate-95",
    "Summary-SpO2-100",
    "Summary-SpO2-50",
    "Summary-SpO2-95",
    "Summary-SpontCyclePercentage",
    "Summary-SpontTriggerPercentage",
    "Summary-TargetMinuteVentilation-100",
    "Summary-TargetMinuteVentilation-50",
    "Summary-TargetMinuteVentilation-95",
    "Summary-TidalVolume-100",
    "Summary-TidalVolume-50",
    "Summary-TidalVolume-95",
    "Summary-TubeConnected",
    "Summary-UnknownApneaIndex",
]

STREAM_DATA_IDS = sorted(set(STREAM_DIRECT_DATA_IDS + STREAM_SUMMARY_DATA_IDS))

STREAM_GROUPS = STREAM_DIRECT_GROUPS + [
    ("summary/statistic data IDs", STREAM_SUMMARY_DATA_IDS),
]

# Convenience groups that mirror the generated live EDF files.
STREAM_EDF_ALIASES: dict[str, tuple[str, ...]] = {
    "BRP": (
        "PatientFlow-100hz",
        "MaskPressure-100hz",
    ),
    "PLD": (
        "MaskPressure-TwoSecond",
        "InspiratoryPressure-TwoSecond",
        "ExpiratoryPressure-TwoSecond",
        "Leak-50hz",
        "RespiratoryRate-50hz",
        "TidalVolume-50hz",
        "MinuteVentilation-50hz",
        "TargetMinuteVentilation",
        "IeRatio",
        "SnoreIndex-50hz",
        "FlowLimitation-50hz",
        "InspiratoryDuration",
    ),
    "SA2": (
        "HeartRate",
        "SpO2",
    ),
}

STREAM_EDF_SAMPLE_MS: dict[str, int] = {
    "BRP": 40,
    "PLD": 2000,
    "SA2": 1000,
}

EVENT_IDS = [
    # mask / therapy lifecycle
    "MaskFitStart", "MaskFitStop", "MaskOn", "MaskOff",
    "MaskReminderAcknowledged",
    "PressureStart", "PressureStop",
    "RampDownStarted", "RampDownCompleted",
    # sensor / hardware anomalies
    "PressureStuckHigh", "PressureStuckLow", "PressureStuckMid",
    "PressureSensorDrift", "PressureSensorsPlausibility",
    "SensorFail",
    # alarm subsystem
    "AlarmImageRestored", "AlarmMuteState",
    "AlarmModuleCommunicationError", "AlarmSelfTestFailure",
    # upgrade lifecycle
    "AlarmUpgradeInitiated", "AlarmUpgradeSuccessful", "AlarmUpgradeFailed",
    "AlarmUpgradeFileTransferRequested",
    "AlarmUpgradeFileTransferCompleted", "AlarmUpgradeFileTransferFailed",
    "AlarmUpgradeFileSignatureMismatch",
    "UpgradePrepStarted",
    # device check
    "DeviceCheckInitiated", "DeviceCheckPassed", "DeviceCheckSystemError",
    "DeviceCheckNotificationDisplayed",
    # system errors
    "SystemErrorStarted",
    "SystemErrorCalibrationReset", "SystemErrorSettingsReset",
    "SystemErrorFastOverPressure", "SystemErrorSlowOverPressure",
    "SystemErrorOverTemperature", "SystemErrorOverVoltage",
    "SystemErrorImplausibleSupplyVoltage",
    "SystemErrorFaultyHWFaultDetectionCircuitry",
    "SystemErrorFlowSensorStuckHigh", "SystemErrorFlowSensorStuckLow",
    "SystemErrorNoFlowData",
    "SystemErrorPressureSensorDrift", "SystemErrorPressureSensorsPlausibility",
    "SystemErrorPressureStuckHigh", "SystemErrorPressureStuckLow",
    "SystemErrorPressureStuckMid",
    "SystemErrorMotorESD", "SystemErrorMotorFETs",
    "SystemErrorMotorHwFault", "SystemErrorMotorHwMitigationIC",
    "SystemErrorMotorStallHW", "SystemErrorMotorStallSW",
    "SystemErrorMotorSticky",
    # notifications observed on the wire
    "SpoolFragment",
]

# Names the device's `Get` RPC accepts as aggregate-subtree targets
# passing one of these returns the whole subtree in one call.
VAR_SUBTREES: frozenset[str] = frozenset({
    "ActiveProfiles",
    "AlarmProfiles",
    "ASVAutoProfile",
    "ASVProfile",
    "AutoRampFeature",
    "AutoSetForHerProfile",
    "AutoSetProfile",
    "CellularConfigurationProfiles",
    "CellularDataUsage",
    "CellularIdentificationProfiles",
    "CellularModule",
    "CircuitFeature",
    "ClimateFeature",
    "ComfortFeature",
    "ConfigurationProfiles",
    "CpapProfile",
    "DataDeliveryControl",
    "DeviceConfigurationSettings",
    "DeviceRegistration",
    "EprFeature",
    "FeatureProfiles",
    "IdentificationProfiles",
    "iVAPSProfile",
    "MachineMetrics",
    "PACProfile",
    "RampDownFeature",
    "SettingProfiles",
    "SmartStartStopFeature",
    "SpontProfile",
    "StoredDataDeliveryControl",
    "STProfile",
    "TherapyProfiles",
    "TimedProfile",
    "VAutoProfile",
})

# Short->path name map found in firmware (table at 0x08144cbc).
# NOT Get-able. Kept for documentation / future use.
VAR_PATH_ALIASES = {
    "alarmEvents":                                      "FlowGenerator.eventProfiles.alarmEvents",
    "alarmDiagnosticEvents":                            "FlowGenerator.eventProfiles.alarmDiagnosticEvents",
    "CellularBrokerURI":                                "CellularModule.ConfigurationProfiles.TherapySystemBrokerUniformResourceIdentifier",
    "CellularInternalModule":                           "CellularModule.IdentificationProfiles.CellularProfile.InternalModule",
    "CellularNetworkGeneration":                        "CellularModule.IdentificationProfiles.CellularProfile.Network.GenerationIdentifier",
    "CellularNetworkPlan":                              "CellularModule.IdentificationProfiles.CellularProfile.Network.PlanIdentifier",
    "CellularNetworkProvider":                          "CellularModule.IdentificationProfiles.CellularProfile.Network.ProviderIdentifier",
    "CellularNetworkProvisionedDateTime":               "CellularModule.IdentificationProfiles.CellularProfile.Network.ProvisionedDateTime",
    "CellularRegistrationURI":                          "CellularModule.ConfigurationProfiles.TherapySystemRegistrationUniformResourceIdentifier",
    "Diagnostic25HzPeriodic-BlowerFlow":                "FlowGenerator.MeasurementProfiles.Diagnostic25HzPeriodic.BlowerFlow",
    "Diagnostic25HzPeriodic-BlowerPressure":            "FlowGenerator.MeasurementProfiles.Diagnostic25HzPeriodic.BlowerPressure",
    "DiagnosticExceptionEvents-AlarmAppError":          "FlowGenerator.MeasurementProfiles.DiagnosticExceptionEvents.AlarmAppErrors.AlarmAppError",
    "DiagnosticExceptionEvents-AppError":               "FlowGenerator.MeasurementProfiles.DiagnosticExceptionEvents.AppErrors.AppError",
    "DiagnosticExceptionEvents-ErrorLogInfo":           "FlowGenerator.MeasurementProfiles.DiagnosticExceptionEvents.ErrorLogInfos.ErrorLogInfo",
    "DiagnosticExceptionEvents-FatalError":             "FlowGenerator.MeasurementProfiles.DiagnosticExceptionEvents.FatalErrors.FatalError",
    "DiagnosticExceptionEvents-ResettableError":        "FlowGenerator.MeasurementProfiles.DiagnosticExceptionEvents.ResettableErrors.ResettableError",
    "DiagnosticTenMinutePeriodic-CellularSignalQuality2G":   "FlowGenerator.MeasurementProfiles.DiagnosticTenMinutePeriodic.CellularSignalQuality2G",
    "DiagnosticTenMinutePeriodic-CellularSignalQuality3G":   "FlowGenerator.MeasurementProfiles.DiagnosticTenMinutePeriodic.CellularSignalQuality3G",
    "DiagnosticTenMinutePeriodic-CellularSignalQualityLTE":  "FlowGenerator.MeasurementProfiles.DiagnosticTenMinutePeriodic.CellularSignalQualityLTE",
    "DiagnosticTenMinutePeriodic-CellularSignalStrength":    "FlowGenerator.MeasurementProfiles.DiagnosticTenMinutePeriodic.CellularSignalStrength",
    "Summary":                                          "FlowGenerator.MeasurementProfiles.Summary",
    "SystemActivityEvents-FrequentActivityEvent":       "FlowGenerator.MeasurementProfiles.SystemActivityEvents.FrequentActivityEvents.FrequentActivityEvent",
    "SystemActivityEvents-SporadicActivityEvent":       "FlowGenerator.MeasurementProfiles.SystemActivityEvents.SporadicActivityEvents.SporadicActivityEvent",
    "SystemExceptionEvents-HeatedTubeError":            "FlowGenerator.MeasurementProfiles.SystemExceptionEvents.HeatedTubeErrors.HeatedTubeError",
    "SystemExceptionEvents-HumidifierError":            "FlowGenerator.MeasurementProfiles.SystemExceptionEvents.HumidifierErrors.HumidifierError",
    "SystemExceptionEvents-RecoverableError":           "FlowGenerator.MeasurementProfiles.SystemExceptionEvents.RecoverableErrors.RecoverableError",
    "SystemExceptionEvents-SystemError":                "FlowGenerator.MeasurementProfiles.SystemExceptionEvents.SystemErrors.SystemError",
    "TherapyEvents-RespiratoryEvent":                   "FlowGenerator.MeasurementProfiles.TherapyEvents.RespiratoryEvents.RespiratoryEvent",
    "TherapyOneHzPeriodic-HeartRate":                   "FlowGenerator.MeasurementProfiles.TherapyOneHzPeriodic.HeartRate",
    "TherapyOneHzPeriodic-SpO2":                        "FlowGenerator.MeasurementProfiles.TherapyOneHzPeriodic.SpO2",
    "TherapyOneMinutePeriodic-AlveolarMinuteVentilation": "FlowGenerator.MeasurementProfiles.TherapyOneMinutePeriodic.AlveolarMinuteVentilation",
    "TherapyOneMinutePeriodic-ExpiratoryPressure":      "FlowGenerator.MeasurementProfiles.TherapyOneMinutePeriodic.ExpiratoryPressure",
    "TherapyOneMinutePeriodic-HeartRate":               "FlowGenerator.MeasurementProfiles.TherapyOneMinutePeriodic.HeartRate",
    "TherapyOneMinutePeriodic-IeRatio":                 "FlowGenerator.MeasurementProfiles.TherapyOneMinutePeriodic.IeRatio",
    "TherapyOneMinutePeriodic-InspiratoryDuration":     "FlowGenerator.MeasurementProfiles.TherapyOneMinutePeriodic.InspiratoryDuration",
    "TherapyOneMinutePeriodic-InspiratoryPressure":     "FlowGenerator.MeasurementProfiles.TherapyOneMinutePeriodic.InspiratoryPressure",
    "TherapyOneMinutePeriodic-Leak":                    "FlowGenerator.MeasurementProfiles.TherapyOneMinutePeriodic.Leak",
    "TherapyOneMinutePeriodic-MinuteVentilation":       "FlowGenerator.MeasurementProfiles.TherapyOneMinutePeriodic.MinuteVentilation",
    "TherapyOneMinutePeriodic-RespiratoryRate":         "FlowGenerator.MeasurementProfiles.TherapyOneMinutePeriodic.RespiratoryRate",
    "TherapyOneMinutePeriodic-SpO2":                    "FlowGenerator.MeasurementProfiles.TherapyOneMinutePeriodic.SpO2",
    "TherapyOneMinutePeriodic-TidalVolume":             "FlowGenerator.MeasurementProfiles.TherapyOneMinutePeriodic.TidalVolume",
    "TherapyTwentyFiveHzPeriodic-MaskPressure":         "FlowGenerator.MeasurementProfiles.TherapyTwentyFiveHzPeriodic.MaskPressure",
    "TherapyTwentyFiveHzPeriodic-RespiratoryFlow":      "FlowGenerator.MeasurementProfiles.TherapyTwentyFiveHzPeriodic.RespiratoryFlow",
    "TherapyTwoSecondPeriodic-ExpiratoryPressure":      "FlowGenerator.MeasurementProfiles.TherapyTwoSecondPeriodic.ExpiratoryPressure",
    "TherapyTwoSecondPeriodic-FlowLimitation":          "FlowGenerator.MeasurementProfiles.TherapyTwoSecondPeriodic.FlowLimitation",
    "TherapyTwoSecondPeriodic-IeRatio":                 "FlowGenerator.MeasurementProfiles.TherapyTwoSecondPeriodic.IeRatio",
    "TherapyTwoSecondPeriodic-InspiratoryDuration":     "FlowGenerator.MeasurementProfiles.TherapyTwoSecondPeriodic.InspiratoryDuration",
    "TherapyTwoSecondPeriodic-InspiratoryPressure":     "FlowGenerator.MeasurementProfiles.TherapyTwoSecondPeriodic.InspiratoryPressure",
    "TherapyTwoSecondPeriodic-Leak":                    "FlowGenerator.MeasurementProfiles.TherapyTwoSecondPeriodic.Leak",
    "TherapyTwoSecondPeriodic-MaskPressure":            "FlowGenerator.MeasurementProfiles.TherapyTwoSecondPeriodic.MaskPressure",
    "TherapyTwoSecondPeriodic-MinuteVentilation":       "FlowGenerator.MeasurementProfiles.TherapyTwoSecondPeriodic.MinuteVentilation",
    "TherapyTwoSecondPeriodic-RespiratoryRate":         "FlowGenerator.MeasurementProfiles.TherapyTwoSecondPeriodic.RespiratoryRate",
    "TherapyTwoSecondPeriodic-SnoreIndex":              "FlowGenerator.MeasurementProfiles.TherapyTwoSecondPeriodic.SnoreIndex",
    "TherapyTwoSecondPeriodic-TargetMinuteVentilation": "FlowGenerator.MeasurementProfiles.TherapyTwoSecondPeriodic.TargetMinuteVentilation",
    "TherapyTwoSecondPeriodic-TidalVolume":             "FlowGenerator.MeasurementProfiles.TherapyTwoSecondPeriodic.TidalVolume",
    "UsageEvents-TherapyStatusEvent":                   "FlowGenerator.MeasurementProfiles.UsageEvents.TherapyStatusEvents.TherapyStatusEvent",
}


VAR_NAMES = [
    ("ASV-MaxPressureSupport", "XC2"),
    ("ASV-MinPressureSupport", "XC3"),
    ("ASV-StartPressure", "XC0"),
    ("ASV-TargetExpiratoryPressure", "XC1"),
    ("ASVAuto-MaxExpiratoryPressure", "XD1"),
    ("ASVAuto-MaxPressureSupport", "XD3"),
    ("ASVAuto-MinExpiratoryPressure", "XD2"),
    ("ASVAuto-MinPressureSupport", "XD4"),
    ("ASVAuto-StartPressure", "XD0"),
    ("AccessPointName", "CLA"),
    ("ActiveAlarms", "AER"),
    ("ActiveTherapyProfile", "MOP"),
    ("AdcPressure", "PRS"),
    ("AdcPressureMonitoring", "PR2"),
    ("AlarmVolumeLevel", "AVQ"),
    ("AlveolarMinuteVentilation", "AAV"),
    ("AmbientHumidity-Estimated", "ABH"),
    ("AmbientLight", "ALS"),
    ("AmbientTemperature-Estimated", "HAT"),
    ("AntiBacterialFilter", "ABF"),
    ("ApneaAlarmEnable", "ANC"),
    ("ApneaAlarmThreshold", "APV"),
    ("ApneaTreatmentPressure-50hz", "AP5"),
    ("ApplicationData", "MAD"),
    ("ApplicationIdentifier", "SID"),
    ("AutoSet-MaxPressure", "MPA"),
    ("AutoSet-MinPressure", "MPI"),
    ("AutoSet-StartPressure", "STU"),
    ("AutoSetComfort", "AFC"),
    ("AutoSetTreatmentPressure-50hz", "AT5"),
    ("BlowerFlow-100hz", "BFT"),
    ("BlowerPressure-100hz", "BPT"),
    ("BlowerPressure-OneMinute", "BPA"),
    ("BlowerPressureMonitoring", "BPS"),
    ("BluetoothApplicationIdentifier", "BTV"),
    ("BluetoothBootloaderIdentifier", "BBV"),
    ("BluetoothName", "BTN"),
    ("BluetoothPassthrough", "BNP"),
    ("BluetoothProductModel", "BPM"),
    ("BluetoothProductProvider", "BPP"),
    ("BootloaderIdentifier", "BID"),
    ("ButtonRegMap", "KPT"),
    ("CALEnable", "MEN"),
    ("CALStatus", "CST"),
    ("CalManufacturingMode", "CMM"),
    ("CalibrationPressure", "CPR"),
    ("CamlData", "CMD"),
    ("CareCheckInAvailable", "CCA"),
    ("CareCheckToggle", "MAI"),
    ("CellularApplicationIdentifier", "CSI"),
    ("CellularDataPreamble", "CDP"),
    ("CellularProductModel", "CPM"),
    ("CellularProductProvider", "CPP"),
    ("CepstrumAverageCount", "EIC"),
    ("CepstrumStartDelay", "EST"),
    ("ClimateControl", "CCO"),
    ("ClinicalConfirmation", "CFC"),
    ("ConfigurationIdentifier", "CID"),
    ("ConfirmStopEnable", "SCF"),
    ("Cpap-SetPressure", "IPC"),
    ("Cpap-StartPressure", "STP"),
    ("Cpap-TriggerSensitivity", "C11"),
    ("CpapSetPressure", "CSP"),
    ("CurrentLEDState", "CLS"),
    ("CycleDisplayFormat", "SSY"),
    ("DataCollectAndSend", "DSS"),
    ("DataCollectAndSendAsync", "ADS"),
    ("DataMode", "CDM"),
    ("DataModelVersionIdentifier", "DMV"),
    ("DataVersionIdentifier", "PVD"),
    ("DeviceIdStatus", "DIS"),
    ("DisplayAHI", "DAH"),
    ("DownloadBytesDelta", "DDD"),
    ("EndCapDetection", "ECD"),
    ("EprEnable", "EPX"),
    ("EprEnablePatientAccess", "EPA"),
    ("EprPressure", "EPR"),
    ("EprType", "EPT"),
    ("EraseMediaSignature", "EMS"),
    ("ExpirationSetPressure", "ESP"),
    ("ExpiratoryDuration", "EXT"),
    ("ExpiratoryPressure", "EXP"),
    ("ExpiratoryPressure-50hz", "EP5"),
    ("ExpiratoryPressure-TwoSecond", "MKE"),
    ("ExternalHumidifier", "EXH"),
    ("FGState", "ZRM"),
    ("FdaUniqueDeviceIdentifier", "UDI"),
    ("FlightMode", "QFC"),
    ("FlowGain", "FLG"),
    ("FlowLimitation", "FFL"),
    ("FlowLimitation-50hz", "FF5"),
    ("FlowLimitationTreatmentPressure-50hz", "FL5"),
    ("FlowOffset", "FLZ"),
    ("HardwareIdentifier", "PCB"),
    ("HeartRate", "HRT"),
    ("HeatedTubeCurrent", "HTL"),
    ("HeatedTubeOutletTemperature", "HTT"),
    ("HeatedTubeOutletTemperatureMinuteAverage", "HTA"),
    ("HeatedTubePWM", "HBP"),
    ("HeatedTubePWMMinuteAverage", "ABP"),
    ("HeatedTubePower", "HTP"),
    ("HeatedTubeSettingEnable", "HTX"),
    ("HeatedTubeTemperature", "HTS"),
    ("HeightDisplayUnit", "IHU"),
    ("HerAuto-MaxPressure", "HMA"),
    ("HerAuto-MinPressure", "HMI"),
    ("HerAuto-StartPressure", "HSP"),
    ("HighLeakAlarmEnable", "HLA"),
    ("HumidifierConnected", "HCR"),
    ("HumidifierLevel", "HMS"),
    ("HumidifierPWM", "HUP"),
    ("HumidifierPWMMinuteAverage", "AHP"),
    ("HumidifierPlateCurrent", "HCL"),
    ("HumidifierPlateTemperature", "HPT"),
    ("HumidifierPlateTemperatureMinuteAverage", "HHT"),
    ("HumidifierPower", "HPW"),
    ("HumidifierSettingEnable", "HMX"),
    ("IMEI", "CIE"),
    ("IMSI", "CIM"),
    ("IeRatio", "IET"),
    ("InspirationSetPressure", "ISP"),
    ("InspiratoryDuration", "INT"),
    ("InspiratoryPressure", "INP"),
    ("InspiratoryPressure-50hz", "INH"),
    ("InspiratoryPressure-OneMinute", "AIP"),
    ("InspiratoryPressure-TwoSecond", "MKI"),
    ("IsFileSystemReady", "IRF"),
    ("IsRamping", "ZRP"),
    ("IsRampingDown", "RPD"),
    ("IsReadyForShipping", "IRS"),
    ("IsReadyForUpgrade", "IRU"),
    ("LCDConnector", "LCS"),
    ("LCDTouchStatus", "LTS"),
    ("Language", "LAN"),
    ("LanguageConfiguration", "LNC"),
    ("LanguageSelection", "SLS"),
    ("LastDataPostDateTime", "LDT"),
    ("LastEraseDataDateTime", "CED"),
    ("LastMachineServiceDateTime", "LMS"),
    ("LastTherapyUseDateTime", "CUD"),
    ("Leak", "LKF"),
    ("Leak-50hz", "LK5"),
    ("LearnMode", "TLM"),
    ("LearnTargetsExpiratoryPressure", "ZIE"),
    ("LearnTargetsPressureSupport", "ZLP"),
    ("LearnTargetsSetDuration", "ZIC"),
    ("LowMinuteVentAlarmEnable", "LMC"),
    ("LowMinuteVentAlarmThreshold", "LMT"),
    ("MachineRunMeter", "MHU"),
    ("MaskPressure", "MKP"),
    ("MaskPressure-100hz", "MK1"),
    ("MaskPressure-OneMinute", "MAP"),
    ("MaskPressure-TwoSecond", "MKF"),
    ("MaskSenseToggle", "MKD"),
    ("MaskType", "MSK"),
    ("MaxRampDownTime", "MRD"),
    ("MaxRampTime", "MRT"),
    ("MicrophoneEnabled", "MIC"),
    ("MinuteVentilation", "MV6"),
    ("MinuteVentilation-50hz", "MVH"),
    ("MotorCurrent", "CUR"),
    ("MotorFlowDrive", "CFL"),
    ("MotorRunMeter", "MHR"),
    ("MotorRunSinceLastServiceMeter", "MHS"),
    ("MotorSpeed", "SPD"),
    ("MotorType", "BMT"),
    ("MyAirScreens", "MAS"),
    ("NonVentedMaskAlarmEnable", "NMA"),
    ("OobxOnStartup", "SOS"),
    ("OtaUpgradeStatus", "OUS"),
    ("PAC-FallTime", "P12"),
    ("PAC-FallTimeEnable", "P11"),
    ("PAC-RiseTime", "PA4"),
    ("PAC-RiseTimeEnable", "PA3"),
    ("PAC-SetInspiratoryTime", "PA5"),
    ("PAC-SetRespiratoryRate", "PA6"),
    ("PAC-StartPressure", "PA0"),
    ("PAC-TargetExpiratoryPressure", "PA2"),
    ("PAC-TargetInspiratoryPressure", "PA1"),
    ("PAC-TriggerSensitivity", "PA7"),
    ("PatientFlow", "RFL"),
    ("PatientFlow-100hz", "RF5"),
    ("PatientView", "ACC"),
    ("PeriodicBrokerContactPeriod", "BCP"),
    ("PeripheralMsg", "PMS"),
    ("PhantomKey", "KEY"),
    ("PhantomTouch", "TCH"),
    ("PlatformIdentifier", "MID"),
    ("PowerSupplyCapacity", "PSC"),
    ("PowerSupplyType", "PSU"),
    ("PressureGain", "PSH"),
    ("PressureMonitorGain", "PS1"),
    ("PressureMonitorOffset", "PZ1"),
    ("PressureOffset", "PZH"),
    ("ProductCode", "PCD"),
    ("ProductGeographicIdentifier", "PGI"),
    ("ProductName", "PNA"),
    ("ProfileVariantIdentifier", "PVI"),
    ("RampDownEnable", "RDE"),
    ("RampDownEnablePatientAccess", "DPE"),
    ("RampDownTime", "SRT"),
    ("RampEnable", "RMA"),
    ("RampEnablePatientAccess", "RPE"),
    ("RampTime", "RMT"),
    ("RawAmbHumidity", "AHR"),
    ("RawAmbLight", "RAL"),
    ("RawAmbTemperature", "ATR"),
    ("RawFlow", "FLW"),
    ("RawLeak", "SFK"),
    ("RawLeak-50hz", "SF5"),
    ("RecoverableError", "RYS"),
    ("RegionIdentifier", "RID"),
    ("RemainingRampDownTime", "RDD"),
    ("RemainingRampTime", "ZRC"),
    ("RemainingRampTime-50hz", "ZR5"),
    ("ReminderFilterDate", "RTF"),
    ("ReminderFilterEnable", "RIF"),
    ("ReminderFilterPeriod", "RDF"),
    ("ReminderHumidifierDate", "RTH"),
    ("ReminderHumidifierEnable", "RIC"),
    ("ReminderHumidifierPeriod", "RDH"),
    ("ReminderMaskDate", "RTM"),
    ("ReminderMaskEnable", "RIM"),
    ("ReminderMaskPeriod", "RDM"),
    ("ReminderTubingDate", "RTT"),
    ("ReminderTubingEnable", "RIT"),
    ("ReminderTubingPeriod", "RDT"),
    ("RequestLCDColour", "RLC"),
    ("RequestLEDState", "RLS"),
    ("RequestSDCardTest", "RST"),
    ("RequestTestDriveState", "RTS"),
    ("RespiratoryEvent", "AET"),
    ("RespiratoryRate", "RR6"),
    ("RespiratoryRate-50hz", "RR5"),
    ("SDCardSocketStatus", "SSS"),
    ("SDCardTestStatus", "STS"),
    ("SIMID", "CCD"),
    ("ST-CycleSensitivity", "XAB"),
    ("ST-FallTime", "XAP"),
    ("ST-FallTimeEnable", "XAM"),
    ("ST-IntelligentBackupRateEnable", "XAC"),
    ("ST-RiseTime", "XAA"),
    ("ST-RiseTimeEnable", "XA9"),
    ("ST-SetMaxInspiratoryTime", "XA7"),
    ("ST-SetMinInspiratoryTime", "XA8"),
    ("ST-SetRespiratoryRate", "XA6"),
    ("ST-StartPressure", "XA3"),
    ("ST-TargetExpiratoryPressure", "XA2"),
    ("ST-TargetInspiratoryPressure", "XA1"),
    ("ST-TargetRespiratoryRate", "XAD"),
    ("ST-TriggerSensitivity", "ZU1"),
    ("SecurityStatus", "SBE"),
    ("SerialNumber", "SRN"),
    ("ServiceHost", "CLU"),
    ("ServicePort", "CLP"),
    ("SetMotorSpeed", "SSD"),
    ("SetPressure-100hz", "SPH"),
    ("SetPressureWithoutCAD", "OPP"),
    ("SettingsHistoryChangeCount", "SHC"),
    ("SmartStart", "SST"),
    ("SmartStop", "SSP"),
    ("SnoreIndex", "SNI"),
    ("SnoreIndex-50hz", "SN5"),
    ("SnoreTreatmentPressure-50hz", "SR5"),
    ("SoundDownloadAllowed", "DSA"),
    ("SoundcheckFeatureToggle", "SCO"),
    ("SoundcheckRunFrequency", "SCK"),
    ("SoundcheckStatus", "STT"),
    ("SoundcheckTestCount", "SSC"),
    ("SpO2", "SAO"),
    ("SplashScreenDisplaySelection", "SSE"),
    ("Spont-CycleSensitivity", "Z12"),
    ("Spont-EasyBreatheEnable", "ZZ4"),
    ("Spont-FallTime", "Z17"),
    ("Spont-FallTimeEnable", "Z16"),
    ("Spont-RespiratoryRateEnable", "ZZ5"),
    ("Spont-RiseTime", "Z10"),
    ("Spont-RiseTimeEnable", "ZZ9"),
    ("Spont-SetMaxInspiratoryTime", "ZZ7"),
    ("Spont-SetMinInspiratoryTime", "ZZ8"),
    ("Spont-StartPressure", "ZZ3"),
    ("Spont-TargetExpiratoryPressure", "ZZ2"),
    ("Spont-TargetInspiratoryPressure", "ZZ1"),
    ("Spont-TriggerSensitivity", "Z11"),
    ("StatusEvent", "THS"),
    ("StorageVersionId", "SVD"),
    ("Summary-AmbientHumidity-50", "AUM"),
    ("Summary-ApneaHypopneaIndex", "AHI"),
    ("Summary-ApneaIndex", "ASC"),
    ("Summary-BlowerFlow-50", "BFM"),
    ("Summary-BlowerPressure-5", "BP5"),
    ("Summary-BlowerPressure-95", "BP9"),
    ("Summary-CentralApneaIndex", "OSC"),
    ("Summary-ExpiratoryPressure-100", "PEA"),
    ("Summary-ExpiratoryPressure-50", "PEM"),
    ("Summary-ExpiratoryPressure-95", "PE9"),
    ("Summary-HeartRate-100", "HRX"),
    ("Summary-HeartRate-50", "HRM"),
    ("Summary-HeartRate-95", "HR9"),
    ("Summary-HeatedTubePower-50", "AHM"),
    ("Summary-HeatedTubeTemperature-50", "HTE"),
    ("Summary-HumidifierConnected", "HUC"),
    ("Summary-HumidifierPower-50", "APM"),
    ("Summary-HumidifierTemperature-50", "HHE"),
    ("Summary-HypopneaIndex", "HSC"),
    ("Summary-IeRatio-100", "IEA"),
    ("Summary-IeRatio-50", "IEM"),
    ("Summary-IeRatio-95", "IE9"),
    ("Summary-InspiratoryDuration-100", "ISA"),
    ("Summary-InspiratoryDuration-50", "ISM"),
    ("Summary-InspiratoryDuration-95", "IS9"),
    ("Summary-InspiratoryPressure-100", "PIA"),
    ("Summary-InspiratoryPressure-50", "PIM"),
    ("Summary-InspiratoryPressure-95", "PI9"),
    ("Summary-Leak-100", "LMX"),
    ("Summary-Leak-50", "LKM"),
    ("Summary-Leak-75", "LK7"),
    ("Summary-Leak-95", "LK9"),
    ("Summary-MeanMaskPressure-100", "PMA"),
    ("Summary-MeanMaskPressure-50", "MSP"),
    ("Summary-MeanMaskPressure-95", "PM9"),
    ("Summary-MinuteVentilation-100", "VTA"),
    ("Summary-MinuteVentilation-50", "VTM"),
    ("Summary-MinuteVentilation-95", "VT9"),
    ("Summary-ObstructiveApneaIndex", "CSC"),
    ("Summary-ReraIndex", "RCC"),
    ("Summary-RespiratoryFlow-5", "RFM"),
    ("Summary-RespiratoryFlow-95", "R95"),
    ("Summary-RespiratoryRate-100", "RRA"),
    ("Summary-RespiratoryRate-50", "RRM"),
    ("Summary-RespiratoryRate-95", "RR9"),
    ("Summary-SpO2-100", "SOX"),
    ("Summary-SpO2-50", "SOM"),
    ("Summary-SpO2-95", "SO9"),
    ("Summary-SpontCyclePercentage", "VCR"),
    ("Summary-SpontTriggerPercentage", "VSR"),
    ("Summary-TargetMinuteVentilation-100", "VAA"),
    ("Summary-TargetMinuteVentilation-50", "VAM"),
    ("Summary-TargetMinuteVentilation-95", "VA9"),
    ("Summary-TidalVolume-100", "TVA"),
    ("Summary-TidalVolume-50", "TVM"),
    ("Summary-TidalVolume-95", "TV9"),
    ("Summary-TubeConnected", "ZHT"),
    ("Summary-UnknownApneaIndex", "USC"),
    ("SystemError", "FSE"),
    ("TOTAL_USED_HOURS_NAME", "PHR"),
    ("TargetMinuteVentilation", "TVP"),
    ("TemperatureUnit", "TMU"),
    ("TestDrivePressure", "TDP"),
    ("TestDriveState", "TDS"),
    ("TestDriveType", "TDT"),
    ("TherapyLEDAlwaysOn", "TLF"),
    ("TherapyRunMeter", "PHM"),
    ("TidalVolume", "TID"),
    ("TidalVolume-50hz", "TI5"),
    ("TimeZoneOffset", "TZO"),
    ("Timed-FallTime", "XBA"),
    ("Timed-FallTimeEnable", "XB9"),
    ("Timed-RiseTime", "XB7"),
    ("Timed-RiseTimeEnable", "XB6"),
    ("Timed-SetInspiratoryTime", "XB5"),
    ("Timed-SetRespiratoryRate", "XB4"),
    ("Timed-StartPressure", "XB0"),
    ("Timed-TargetExpiratoryPressure", "XB2"),
    ("Timed-TargetInspiratoryPressure", "XB1"),
    ("TotalUsedHoursDisplayToggle", "TUD"),
    ("TriggerCycleEvent", "BTE"),
    ("TubeConnected", "ZHR"),
    ("TubeType", "TBT"),
    ("TxLink2Connected", "TXC"),
    ("UniversalIdentifier", "GUD"),
    ("UpgradeAbandonPeriod", "OAP"),
    ("UpgradeReportPeriod", "ORP"),
    ("UploadBytesDelta", "DUD"),
    ("VALOTriggerSeconds", "VTD"),
    ("VAuto-CycleSensitivity", "XE7"),
    ("VAuto-MaxInspiratoryPressure", "XE1"),
    ("VAuto-MinExpiratoryPressure", "XE2"),
    ("VAuto-SetMaxInspiratoryTime", "XE4"),
    ("VAuto-SetMinInspiratoryTime", "XE5"),
    ("VAuto-SetPressureSupport", "XE3"),
    ("VAuto-StartPressure", "XE0"),
    ("VAuto-TriggerSensitivity", "XE6"),
    ("VariantIdentifier", "VID"),
    ("iVAPS-AutoEPAPEnable", "IEU"),
    ("iVAPS-CycleSensitivity", "VCS"),
    ("iVAPS-FallTime", "IRL"),
    ("iVAPS-FallTimeEnable", "IRZ"),
    ("iVAPS-MaxExpiratoryPressure", "IMX"),
    ("iVAPS-MaxPressureSupport", "WPA"),
    ("iVAPS-MinExpiratoryPressure", "IMN"),
    ("iVAPS-MinPressureSupport", "WPM"),
    ("iVAPS-PatientHeight", "PHT"),
    ("iVAPS-RiseTime", "IRT"),
    ("iVAPS-RiseTimeEnable", "IRC"),
    ("iVAPS-SetMaxInspiratoryTime", "IVX"),
    ("iVAPS-SetMinInspiratoryTime", "IVN"),
    ("iVAPS-StartPressure", "IVS"),
    ("iVAPS-TargetAlveolarVentilation", "ITV"),
    ("iVAPS-TargetExpiratoryPressure", "EPI"),
    ("iVAPS-TargetRespiratoryRate", "IBR"),
    ("iVAPS-TriggerSensitivity", "VTS"),
]


REGISTRIES = {
    "vars":     (VAR_NAMES,                   "variable names (for `get` / `set`)"),
    "subtrees": (sorted(VAR_SUBTREES, key=str.lower),
                 "aggregate `get` targets (whole-subtree names, verified)"),
#    "reserved": (VAR_RESERVED,               "reserved `_NAME` specials"),
    "streams":  (STREAM_DATA_IDS,            "stream data IDs (for `stream --data-ids`)"),
    "edf":      (sorted(STREAM_EDF_ALIASES),  "EDF stream aliases (for `stream --edf`)"),
    "events":   (EVENT_IDS,                  "event IDs (for `subscribe --events`)"),
    "spools":   (SPOOL_TYPES,                "spool types (for `spool`)"),
}

# Therapy-mode prefixes: `known vars cpap` -> Cpap-* (exact prefix match).
VAR_MODE_PREFIXES = {
    "cpap": "Cpap-", "autoset": "AutoSet-", "herauto": "HerAuto-",
    "asv": "ASV-", "asvauto": "ASVAuto-", "vauto": "VAuto-",
    "ivaps": "iVAPS-", "st": "ST-", "spont": "Spont-",
    "timed": "Timed-", "pac": "PAC-",
}

# Topic groups: `known vars summary` -> case-insensitive substring match.
VAR_TOPIC_KEYWORDS = {
    "summary":    ("summary",),
    "alarm":      ("alarm",),
    "ramp":       ("ramp",),
    "humidifier": ("humidifier",),
    "tube":       ("tube",),
    "reminder":   ("reminder",),
    "cellular":   ("cellular", "imei", "imsi", "sim", "accesspoint"),
    "bluetooth":  ("bluetooth",),
    "identifier": ("identifier", "serialnumber", "productcode", "productname"),
    "learn":      ("learn",),
    "streaming":  ("-50hz", "-100hz", "-twosecond", "-oneminute", "-estimated"),
}



def filter_vars(pat: str) -> list[tuple[str, str]]:
    """Group-aware filtering over (name, tag) pairs. Falls back to substring."""
    key = pat.lower()
    if key in VAR_MODE_PREFIXES:
        prefix = VAR_MODE_PREFIXES[key]
        return [(n, t) for n, t in VAR_NAMES if n.startswith(prefix)]
    if key in VAR_TOPIC_KEYWORDS:
        keywords = VAR_TOPIC_KEYWORDS[key]
        return [(n, t) for n, t in VAR_NAMES
                if any(k in n.lower() for k in keywords)]
    # substring match against either the long name or the _TAG short form
    return [(n, t) for n, t in VAR_NAMES
            if key in n.lower() or key in f"_{t}".lower()]


def var_groups_summary() -> None:
    print("therapy modes (exact prefix):")
    for key, prefix in sorted(VAR_MODE_PREFIXES.items()):
        n = sum(1 for name, _ in VAR_NAMES if name.startswith(prefix))
        print(f"  {key:<10}  {prefix:<10}  {n:3d}")
    print()
    print("topics (substring):")
    for key, keywords in sorted(VAR_TOPIC_KEYWORDS.items()):
        n = sum(1 for name, _ in VAR_NAMES
                if any(k in name.lower() for k in keywords))
        hint = ", ".join(keywords)
        print(f"  {key:<10}  {n:3d}  ({hint})")
    print()
    print("firmware subtree groups (for `get --group`):")
    non_empty = [(g, v) for g, v in VAR_GROUPS.items() if v]
    for g, v in sorted(non_empty, key=lambda x: -len(x[1])):
        print(f"  {g:<24s}  {len(v):3d}")
    print()


def print_var_pairs(pairs: list[tuple[str, str]]) -> None:
    """Two-column output: long name left, _TAG right."""
    if not pairs:
        return
    width = max(len(n) for n, _ in pairs)
    for name, tag in sorted(pairs):
        print(f"{name:<{width}}  _{tag}")

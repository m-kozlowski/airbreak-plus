# AS11 RPC Event Reference

This document lists the live event-profile selectors accepted by
`SubscribeEvent` and the payload labels each selector carries. Protocol
mechanics (request fields, response shape, the `subscriptionId` cursor, the
unsubscribe state) are described in
[AS11 RPC Protocol](rpc_protocol.md#event-rpc). Historical event spools live
in [AS11 RPC Spool Reference](rpc_spools.md).

## Contents

- [Subscription selectors](#subscription-selectors)
- [Event families](#event-families)
  - [Therapy and usage](#therapy-and-usage)
  - [System activity](#system-activity)
  - [System exceptions](#system-exceptions)
  - [Diagnostic exceptions](#diagnostic-exceptions)
  - [Alarm profiles](#alarm-profiles)

## Subscription selectors

Live selectors accepted by `SubscribeEvent.params.dataIds` on 15.8.4.0.

| Selector | Labels | Notes |
|----------|--------|-------|
| `UsageEvents-TherapyStatusEvents` | 10 | therapy on/off and mode/status lifecycle |
| `TherapyEvents-RespiratoryEvents` | 8 | respiratory event reporting, including `NoEvent` sentinel |
| `SystemActivityEvents-FrequentActivityEvents` | 52 | frequent system activity events |
| `SystemActivityEvents-SporadicActivityEvents` | 76 | sporadic system activity events |
| `SystemExceptionEvents-SystemErrors` | 22 | system errors |
| `SystemExceptionEvents-RecoverableErrors` | 4 | recoverable errors |
| `SystemExceptionEvents-HumidifierErrors` | 5 | humidifier errors |
| `SystemExceptionEvents-HeatedTubeErrors` | 9 | heated tube errors |
| `DiagnosticExceptionEvents-AppErrors` | n/a | application diagnostic errors |
| `DiagnosticExceptionEvents-FatalErrors` | n/a | fatal diagnostic errors |
| `DiagnosticExceptionEvents-ResettableErrors` | n/a | resettable diagnostic errors |
| `DiagnosticExceptionEvents-AlarmAppErrors` | n/a | alarm application errors |
| `DiagnosticExceptionEvents-ErrorLogInfos` | n/a | error-log info records |
| `alarmEvents` | 9 | alarm event profile |
| `alarmDiagnosticEvents` | 26 | alarm diagnostic event profile |

`SubscribeEvent` accepts unknown selector names and reports them as
`valid: false` in the response. Clients should reject a subscription if every
requested selector is invalid.

## Event families

Payload labels listed below come from the 15.8.4.0 firmware formatter tables
and the decoded historical event spools. They are grouped by the subscription
selector that delivers them.

### Therapy and usage

`UsageEvents-TherapyStatusEvents`:

- `NoUsage`, `MaskOff`, `MaskOn`, `PowerOff`
- `MaskFitStart`, `MaskFitStop`
- `TherapyStart`, `TherapyStop`
- `LearnTargetsStart`, `LearnTargetsStop`

`TherapyEvents-RespiratoryEvents`:

- `NoEvent`
- `HypopneaEnd`, `CentralApneaEnd`, `ObstructiveApneaEnd`, `ApneaEnd`
- `ReraEnd`
- `CsrStart`, `CsrEnd`

The apnea, hypopnea, and RERA labels are completion events. Their
`reportTime` is the end of the event; payloads carry `durationSeconds`.

### System activity

`SystemActivityEvents-FrequentActivityEvents`:

- Lifecycle: `PowerUp`, `PowerDown`, `StandbyStarted`, `TherapyStarted`,
  `MaskfitStarted`, `WarmupStarted`, `WarmupStopped`, `CooldownStarted`,
  `CooldownStopped`, `BackupStarted`, `MockdownStarted`,
  `MockdownInterrupted`, `MockdownFinished`, `RampDownStarted`,
  `RampDownCompleted`
- Pressure control: `PressureStart`, `PressureStop`, `SmartStarted`,
  `SmartStopped`, `TherapyStopConfirmed`
- RPC stubs: `RpcStartTherapy`, `RpcStopTherapy`
- Button/UI: `ButtonPressStartStop`, `EnterClinicalMenu`, `ExitClinicalMenu`
- Bluetooth: `BluetoothConnected`, `BTDisconnected`,
  `BluetoothSecureSessionEstablished`, `BluetoothDiscoverable`,
  `BluetoothApplicationPairingAllowed`,
  `BluetoothApplicationPairingEstablished`,
  `BluetoothApplicationPairingDisallowed`,
  `BluetoothOximeterConnected`, `BluetoothOximeterPairingFailed`,
  `BluetoothOximeterDisconnected`
- Hardware: `SDCardInserted`, `HeatedTubeConnected`,
  `HeatedTubeDisconnected`, `AmalfiTubeConnected`, `HeatedTubeFailed`,
  `AlarmModuleComms`, `TxLink2Connected`
- Power supply: `PowerSupplyACMains90W`, `PowerSupplyDCMains90W`,
  `PowerSupply65W`
- Audio/soundcheck: `MicrophoneStartedRecording`,
  `MicrophoneStoppedRecording`, `SoundcheckStarted`, `SoundcheckCompleted`,
  `SoundcheckAcknowledged`, `CepstrumCalculated`
- Self-limit: `FrequentEventsFloodingMitigated`

`SystemActivityEvents-SporadicActivityEvents`:

- `DataResetStarted`, `CalibrationStarted`, `SystemErrorStarted`,
  `UpgradePrepStarted`, `TestDriveStarted`
- `FlightModeOn`, `FlightModeOff`
- RPC echoes: `RpcComplianceEraseRequest`,
  `RpcComplianceEraseRequestFailure`, `RpcEraseData`, `RpcEraseDataFailure`,
  `RpcError`, `RPCResetRequest`, `RPCInitiateUpgradeRequest`,
  `RPCApplyUpgradeSuccessfulResponse`, `RPCApplyUpgradeFailureResponse`,
  `RPCAuthenticatedApplyUpgradeSuccessfulResponse`,
  `RPCAuthenticatedApplyUpgradeFailureResponse`
- Storage: `FlashFormattedSettings`, `FlashFormattedData`,
  `FlashFormattedUpgrade`, `ComplianceEraseComplete`,
  `EventLogsEraseComplete`, `ResetToDefaultsComplete`, `EraseMediaComplete`,
  `SDCardFormatted`, `SDCardRemoved`, `SDCardReadError`,
  `SDCardWriteError`, `SDReadOnlyCardInserted`, `DataIntegrityFailure`,
  `EventLogDataError`, `SDCardFull`
- Bluetooth/security: `BluetoothSecureCodeInvalid`,
  `BTIncorrectAuthenticationResponse`, `BTOutOfSequenceMessage`,
  `BluetoothDataCorruption`, `BTSecureRPCOnInsecureChannel`,
  `BluetoothPeripheralScanningAvailableDevices`, `BluetoothOximeterFound`,
  `BluetoothOximeterJustWorksPairingEstablished`,
  `BluetoothOximeterIncompatibleDevice`, `BluetoothOximeterForgotten`
- Upgrade/signature failures: `IncorrectUpgradeType`,
  `UpgradeFileIntegrityFailure`, `FgUpgradeFileFingerprintMismatch`,
  `FgUpgradeFileSignatureMismatch`, `AlarmUpgradeFileSignatureMismatch`,
  `InvalidUpdaterSoftware`
- Hardware/UI: `BlockedOutlet`, `BlockedInlet`, `EndcapConnected`,
  `EndcapDisconnected`, `LimpModeOn`, `LimpModeOff`,
  `TouchScreenI2CError`, `TubRemovedDuringSoundcheck`,
  `MotorEndOfLifeReached`
- Data mode: `DataModeSilent`, `DataModeActive`
- Learn targets/device checks: `LearnTargetsStarted`,
  `LearnTargetsStopped`, `LearnTargetsFailed`, `LearnTargetsCompleted`,
  `LearnTargetsAccepted`, `DeviceCheckInitiated`, `DeviceCheckPassed`,
  `DeviceCheckSystemError`, `DeviceCheckNotificationDisplayed`
- Reminders/test drive: `MaskReminderAcknowledged`,
  `TubingReminderAcknowledged`, `FilterReminderAcknowledged`,
  `HumidifierReminderAcknowledged`, `TestDriveTimedOut`
- Self-limit/setup: `SporadicEventsFloodingMitigated`,
  `SetupExperienceBypassed`

### System exceptions

`SystemExceptionEvents-SystemErrors`:

- `NoError`
- Motor: `MotorStallHW`, `MotorStallSW`, `MotorHwFault`, `MotorSticky`,
  `MotorFETs`, `MotorHwMitigationIC`
- Pressure: `FastOverPressure`, `PressureStuckHigh`, `PressureStuckLow`,
  `PressureStuckMid`, `PressureSensorDrift`, `PressureSensorsPlausibility`
- Flow: `NoFlowData`, `FlowSensorStuckLow`, `FlowSensorStuckHigh`
- Power/temp: `OverTemperature`, `OverVoltage`, `ImplausibleSupplyVoltage`,
  `FaultyHWFaultDetectionCircuitry`
- Settings: `SettingsReset`, `CalibrationReset`

`SystemExceptionEvents-RecoverableErrors`:

- `NoError`, `HoseBlocked`, `HoseDisconnected`, `HumidifierTubRemoved`

`SystemExceptionEvents-HumidifierErrors`:

- `NoError`, `OverCurrent`, `ProtectionFETShortCircuit`,
  `ControlFETShortCircuit`, `OpenCircuit`

`SystemExceptionEvents-HeatedTubeErrors`:

- `NoError`, `OverPower`, `OverTemperature`, `ProtectionFETShortCircuit`,
  `ControlFETShortCircuit`, `HeatingOpenCircuit`, `HeatingNTCOpenCircuit`,
  `SensorFail`, `OverCurrent`

### Diagnostic exceptions

`DiagnosticExceptionEvents-AppErrors`,
`DiagnosticExceptionEvents-FatalErrors`,
`DiagnosticExceptionEvents-ResettableErrors`,
`DiagnosticExceptionEvents-AlarmAppErrors`,
`DiagnosticExceptionEvents-ErrorLogInfos`

`AppErrors`, `FatalErrors`, `ResettableErrors`, and `AlarmAppErrors` use a raw
16-bit payload. Their code domains are selector-specific and must not be
decoded through the system-error or alarm-event dictionaries.

`AppErrors` includes direct application codes, translated filesystem/backend
statuses, and the `0x2d76` flood marker. For translated statuses below 2000,
the stored code is `uint16(status + 0x2d7e)`; statuses of 2000 or greater are
stored as `0x354e`. Direct application codes overlap this numeric range, so a
code can have more than one valid interpretation.

`FatalErrors` contains the fatal code retained before a reset. A valid retained
code in the range 1 through 70 is published during the next startup and then
cleared. Source filename and line are not included in the event.

`ResettableErrors` contains a persisted resettable-error snapshot. Firmware
stores the error code with date and time, then publishes the snapshot when a
valid settings unit is loaded. Codes can come from a mapped lower-controller
status or from direct internal producers; no complete symbolic code dictionary
is available.

`AlarmAppErrors` contains the unmodified `EventCode` received from the alarm
application. The selector is present in the checked 8.4.0 and 8.5.0 images but
not in 8.3.0. The flow-generator application does not provide a local symbolic
dictionary for these values.

`ErrorLogInfos` uses a different payload: an 8-bit type followed by a 32-bit
value. For type 1, the value is the stacked program counter retained by an NMI,
HardFault, MemManage, BusFault, or UsageFault reset path. The record does not
identify which of those five reset causes produced it.

### Alarm profiles

`alarmEvents`:

- `HighLeakAlarm`, `NonVentedMaskAlarm`, `LowMinuteVentilationAlarm`,
  `ApneaAlarm`
- `RecoverableErrorHoseBlockedAlarm`,
  `RecoverableErrorHoseDisconnectedAlarm`,
  `RecoverableErrorHumidifierTubRemovedAlarm`
- `AlarmModuleCommunicationError`, `AlarmMute`

`alarmDiagnosticEvents`:

- Self-test: `IndicatorSelfTestInitiated`, `IndicatorSelfTestPass`,
  `IndicatorSelfTestFail`, `PrimaryLEDFail`, `SecondaryLEDFail`,
  `BuzzerFail`, `MuteButtonStuckOn`, `SelfTestInitiated`
- Supercap: `SupercapacitorSelfTestInitiated`,
  `SupercapacitorSelfTestPass`, `SupercapacitorSelfTestFail`,
  `SupercapacitorVoltage`, `SupercapacitorCapacitance`,
  `SupercapacitorESR`
- Upgrade lifecycle: `AlarmUpgradeInitiated`, `AlarmUpgradeSuccessful`,
  `AlarmUpgradeFailed`, `InitiateAlarmUpgradeRequested`,
  `InitiateAlarmUpgradeCompleted`, `InitiateAlarmUpgradeFailed`,
  `AlarmUpgradeFileTransferRequested`,
  `AlarmUpgradeFileTransferCompleted`,
  `AlarmUpgradeFileTransferFailed`, `ApplyAlarmUpgradeRequested`,
  `ApplyAlarmUpgradeCompleted`, `ApplyAlarmUpgradeFailed`

#!/usr/bin/env python3
"""S11 EDF superset patch helpers.

This module is intentionally separate from patch-airsense-s11.py. The main
patcher owns firmware loading, option handling, and CRC refresh; this helper
owns the EDF-specific CONF edits.
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import struct
import sys
from pathlib import Path


STREAM_HEADER_SIZE = 16
STREAM_SIGNAL_SIZE = 16
SUMMARY_RECORD_SIZE = 36
EVENT_SCHEMA_SIZE = 28
LEGACY_EVENT_SCHEMA_SIZE = 20
STR_RECORD_SETTING = 0x00
STR_RECORD_SUMMARY = 0x01


# Format: var short name, EDF label, EDF physical unit, firmware scale.
BRP_STREAM_SIGNALS = (
    ("RFL", "Flow.40ms", "L/s", 500.0),
    ("MKP", "Press.40ms", "cmH2O", 50.0),
)


SA2_STREAM_SIGNALS = (
    ("HRT", "Pulse.1s", "bpm", 1.0),
    ("SAO", "SpO2.1s", "%", 1.0),
)


PLD_SUPERSET_SIGNALS = (
    ("MKF", "MaskPress.2s", "cmH2O", 50.0),
    ("MKI", "Press.2s", "cmH2O", 50.0),
    ("MKE", "EprPress.2s", "cmH2O", 50.0),
    ("LKF", "Leak.2s", "L/s", 50.0),
    ("RR2", "RespRate.2s", "bpm", 5.0),
    ("TD2", "TidVol.2s", "L", 50.0),
    ("MV2", "MinVent.2s", "L/min", 8.0),
    ("TGT", "TgtVent.2s", "L/min", 8.0),
    ("IE2", "IERatio.2s", "%", 1.0),
    ("SNI", "Snore.2s", "", 50.0),
    ("FFL", "FlowLim.2s", "", 100.0),
    ("INT", "Ti.2s", "seconds", 50.0),
)


STREAM_SCHEMAS = (
    ("BRP", BRP_STREAM_SIGNALS),
    ("SA2", SA2_STREAM_SIGNALS),
    ("PLD", PLD_SUPERSET_SIGNALS),
)


# STR formatter metadata from the active-row union of official S11 8.4.0 variants.
# record_class is 0 for setting snapshots and 1 for summary/status rows.
# reserved16 is always zero in checked official active rows.
# Format: key, EDF label, EDF unit, logical scale, EDF output scale,
# record_class, reserved16
STR_SUPERSET_METADATA = (
    ((0, 3, 0x7FFF, 0x7FFF, 0x0000), "", "", 1, 1, 0x01, 0x0000),  # n/a
    ((1, 2, 0x02B6, 0x7FFF, 0x0000), "Duration", "min.", 1, 1, 0x01, 0x0000),  # PPD
    ((3, 0, 0x040E, 0x7FFF, 0x0000), "Mode", "", 1, 1, 0x00, 0x0000),  # ActiveTherapyProfile
    ((4, 0, 0x02A8, 0x7FFF, 0x0000), "S.C.StartPress", "cmH2O", 0.0199999996, 50, 0x00, 0x0000),  # Cpap-StartPressure
    ((5, 0, 0x0105, 0x7FFF, 0x0000), "S.C.Press", "cmH2O", 0.0199999996, 50, 0x00, 0x0000),  # Cpap-SetPressure
    ((7, 0, 0x02A7, 0x7FFF, 0x0000), "S.A.StartPress", "cmH2O", 0.0199999996, 50, 0x00, 0x0000),  # AutoSet-StartPressure
    ((8, 0, 0x01F1, 0x7FFF, 0x0000), "S.A.MaxPress", "cmH2O", 0.0199999996, 50, 0x00, 0x0000),  # AutoSet-MaxPressure
    ((9, 0, 0x0208, 0x7FFF, 0x0000), "S.A.MinPress", "cmH2O", 0.0199999996, 50, 0x00, 0x0000),  # AutoSet-MinPressure
    ((10, 0, 0x007C, 0x7FFF, 0x0000), "S.AFH.StartPress", "cmH2O", 0.0199999996, 50, 0x00, 0x0000),  # HerAuto-StartPressure
    ((11, 0, 0x007A, 0x7FFF, 0x0000), "S.AFH.MaxPress", "cmH2O", 0.0199999996, 50, 0x00, 0x0000),  # HerAuto-MaxPressure
    ((12, 0, 0x007B, 0x7FFF, 0x0000), "S.AFH.MinPress", "cmH2O", 0.0199999996, 50, 0x00, 0x0000),  # HerAuto-MinPressure
    ((13, 0, 0x0319, 0x7FFF, 0x0000), "S.VA.StartPress", "cmH2O", 0.0199999996, 50, 0x00, 0x0000),  # VAuto-StartPressure
    ((14, 0, 0x0316, 0x7FFF, 0x0000), "S.VA.MaxIPAP", "cmH2O", 0.0199999996, 50, 0x00, 0x0000),  # VAuto-MaxInspiratoryPressure
    ((15, 0, 0x0317, 0x7FFF, 0x0000), "S.VA.MinEPAP", "cmH2O", 0.0199999996, 50, 0x00, 0x0000),  # VAuto-MinExpiratoryPressure
    ((16, 0, 0x0318, 0x7FFF, 0x0000), "S.VA.PS", "cmH2O", 0.0199999996, 50, 0x00, 0x0000),  # VAuto-SetPressureSupport
    ((17, 0, 0x031A, 0x7FFF, 0x0000), "S.VA.TiMax", "seconds", 20, 50, 0x00, 0x0000),  # VAuto-SetMaxInspiratoryTime
    ((18, 0, 0x031B, 0x7FFF, 0x0000), "S.VA.TiMin", "seconds", 20, 50, 0x00, 0x0000),  # VAuto-SetMinInspiratoryTime
    ((19, 0, 0x049E, 0x7FFF, 0x0000), "S.VA.Trigger", "", 1, 1, 0x00, 0x0000),  # VAuto-TriggerSensitivity
    ((20, 0, 0x049D, 0x7FFF, 0x0000), "S.VA.Cycle", "", 1, 1, 0x00, 0x0000),  # VAuto-CycleSensitivity
    ((21, 0, 0x02C8, 0x7FFF, 0x0000), "S.S.StartPress", "cmH2O", 0.0199999996, 50, 0x00, 0x0000),  # Spont-StartPressure
    ((22, 0, 0x02C5, 0x7FFF, 0x0000), "S.S.IPAP", "cmH2O", 0.0199999996, 50, 0x00, 0x0000),  # Spont-TargetInspiratoryPressure
    ((23, 0, 0x02C0, 0x7FFF, 0x0000), "S.S.EPAP", "cmH2O", 0.0199999996, 50, 0x00, 0x0000),  # Spont-TargetExpiratoryPressure
    ((24, 0, 0x047A, 0x7FFF, 0x0000), "S.S.EasyBreathe", "", 1, 1, 0x00, 0x0000),  # Spont-EasyBreatheEnable
    ((25, 0, 0x047C, 0x7FFF, 0x0000), "S.S.RespRateEn", "", 1, 1, 0x00, 0x0000),  # Spont-RespiratoryRateEnable
    ((26, 0, 0x02C9, 0x7FFF, 0x0000), "S.S.TiMax", "seconds", 20, 50, 0x00, 0x0000),  # Spont-SetMaxInspiratoryTime
    ((27, 0, 0x02CA, 0x7FFF, 0x0000), "S.S.TiMin", "seconds", 20, 50, 0x00, 0x0000),  # Spont-SetMinInspiratoryTime
    ((28, 0, 0x047D, 0x7FFF, 0x0000), "S.S.RiseEnable", "", 1, 1, 0x00, 0x0000),  # Spont-RiseTimeEnable
    ((29, 0, 0x02C7, 0x7FFF, 0x0000), "S.S.RiseTime", "msec", 1, 1, 0x00, 0x0000),  # Spont-RiseTime
    ((32, 0, 0x047E, 0x7FFF, 0x0000), "S.S.Trigger", "", 1, 1, 0x00, 0x0000),  # Spont-TriggerSensitivity
    ((33, 0, 0x0477, 0x7FFF, 0x0000), "S.S.Cycle", "", 1, 1, 0x00, 0x0000),  # Spont-CycleSensitivity
    ((34, 0, 0x02B1, 0x7FFF, 0x0000), "S.ST.StartPress", "cmH2O", 0.0199999996, 50, 0x00, 0x0000),  # ST-StartPressure
    ((35, 0, 0x02AE, 0x7FFF, 0x0000), "S.ST.IPAP", "cmH2O", 0.0199999996, 50, 0x00, 0x0000),  # ST-TargetInspiratoryPressure
    ((36, 0, 0x02AA, 0x7FFF, 0x0000), "S.ST.EPAP", "cmH2O", 0.0199999996, 50, 0x00, 0x0000),  # ST-TargetExpiratoryPressure
    ((37, 0, 0x02AF, 0x7FFF, 0x0000), "S.ST.RespRate", "bpm", 0.200000003, 5, 0x00, 0x0000),  # ST-SetRespiratoryRate
    ((38, 0, 0x02B3, 0x7FFF, 0x0000), "S.ST.TiMax", "seconds", 20, 50, 0x00, 0x0000),  # ST-SetMaxInspiratoryTime
    ((39, 0, 0x02B4, 0x7FFF, 0x0000), "S.ST.TiMin", "seconds", 20, 50, 0x00, 0x0000),  # ST-SetMinInspiratoryTime
    ((40, 0, 0x046E, 0x7FFF, 0x0000), "S.ST.RiseEnable", "", 1, 1, 0x00, 0x0000),  # ST-RiseTimeEnable
    ((41, 0, 0x02B0, 0x7FFF, 0x0000), "S.ST.RiseTime", "msec", 1, 1, 0x00, 0x0000),  # ST-RiseTime
    ((44, 0, 0x046F, 0x7FFF, 0x0000), "S.ST.Trigger", "", 1, 1, 0x00, 0x0000),  # ST-TriggerSensitivity
    ((45, 0, 0x0469, 0x7FFF, 0x0000), "S.ST.Cycle", "", 1, 1, 0x00, 0x0000),  # ST-CycleSensitivity
    ((48, 0, 0x030D, 0x7FFF, 0x0000), "S.T.StartPress", "cmH2O", 0.0199999996, 50, 0x00, 0x0000),  # Timed-StartPressure
    ((49, 0, 0x030A, 0x7FFF, 0x0000), "S.T.IPAP", "cmH2O", 0.0199999996, 50, 0x00, 0x0000),  # Timed-TargetInspiratoryPressure
    ((50, 0, 0x0307, 0x7FFF, 0x0000), "S.T.EPAP", "cmH2O", 0.0199999996, 50, 0x00, 0x0000),  # Timed-TargetExpiratoryPressure
    ((51, 0, 0x030B, 0x7FFF, 0x0000), "S.T.RespRate", "bpm", 0.200000003, 5, 0x00, 0x0000),  # Timed-SetRespiratoryRate
    ((52, 0, 0x030E, 0x7FFF, 0x0000), "S.T.Ti", "seconds", 20, 50, 0x00, 0x0000),  # Timed-SetInspiratoryTime
    ((53, 0, 0x0495, 0x7FFF, 0x0000), "S.T.RiseEnable", "", 1, 1, 0x00, 0x0000),  # Timed-RiseTimeEnable
    ((54, 0, 0x030C, 0x7FFF, 0x0000), "S.T.RiseTime", "msec", 1, 1, 0x00, 0x0000),  # Timed-RiseTime
    ((57, 0, 0x00A4, 0x7FFF, 0x0000), "S.AV.StartPress", "cmH2O", 0.0199999996, 50, 0x00, 0x0000),  # ASV-StartPressure
    ((58, 0, 0x00A3, 0x7FFF, 0x0000), "S.AV.EPAP", "cmH2O", 0.0199999996, 50, 0x00, 0x0000),  # ASV-TargetExpiratoryPressure
    ((59, 0, 0x00A1, 0x7FFF, 0x0000), "S.AV.MaxPS", "cmH2O", 0.0199999996, 50, 0x00, 0x0000),  # ASV-MaxPressureSupport
    ((60, 0, 0x00A2, 0x7FFF, 0x0000), "S.AV.MinPS", "cmH2O", 0.0199999996, 50, 0x00, 0x0000),  # ASV-MinPressureSupport
    ((61, 0, 0x00A0, 0x7FFF, 0x0000), "S.AA.StartPress", "cmH2O", 0.0199999996, 50, 0x00, 0x0000),  # ASVAuto-StartPressure
    ((62, 0, 0x009C, 0x7FFF, 0x0000), "S.AA.MaxEPAP", "cmH2O", 0.0199999996, 50, 0x00, 0x0000),  # ASVAuto-MaxExpiratoryPressure
    ((63, 0, 0x009E, 0x7FFF, 0x0000), "S.AA.MinEPAP", "cmH2O", 0.0199999996, 50, 0x00, 0x0000),  # ASVAuto-MinExpiratoryPressure
    ((64, 0, 0x009D, 0x7FFF, 0x0000), "S.AA.MaxPS", "cmH2O", 0.0199999996, 50, 0x00, 0x0000),  # ASVAuto-MaxPressureSupport
    ((65, 0, 0x009F, 0x7FFF, 0x0000), "S.AA.MinPS", "cmH2O", 0.0199999996, 50, 0x00, 0x0000),  # ASVAuto-MinPressureSupport
    ((94, 0, 0x034F, 0x7FFF, 0x0000), "S.AS.Comfort", "", 1, 1, 0x00, 0x0000),  # AutoSetComfort
    ((95, 0, 0x0429, 0x7FFF, 0x0000), "S.RampEnable", "", 1, 1, 0x00, 0x0000),  # RampEnable
    ((96, 0, 0x0250, 0x7FFF, 0x0000), "S.RampTime", "min.", 1, 1, 0x00, 0x0000),  # RampTime
    ((99, 0, 0x039E, 0x7FFF, 0x0000), "S.EPR.ClinEnable", "", 1, 1, 0x00, 0x0000),  # EprEnablePatientAccess
    ((100, 0, 0x039F, 0x7FFF, 0x0000), "S.EPR.EPREnable", "", 1, 1, 0x00, 0x0000),  # EprEnable
    ((101, 0, 0x0134, 0x7FFF, 0x0000), "S.EPR.Level", "cmH2O", 0.0199999996, 50, 0x00, 0x0000),  # EprPressure
    ((102, 0, 0x03A0, 0x7FFF, 0x0000), "S.EPR.EPRType", "", 1, 1, 0x00, 0x0000),  # EprType
    ((103, 0, 0x045D, 0x7FFF, 0x0000), "S.SmartStart", "", 1, 1, 0x00, 0x0000),  # SmartStart
    ((104, 0, 0x0419, 0x7FFF, 0x0000), "S.PtAccess", "", 1, 1, 0x00, 0x0000),  # PatientView
    ((105, 0, 0x033A, 0x7FFF, 0x0000), "S.ABFilter", "", 1, 1, 0x00, 0x0000),  # AntiBacterialFilter
    ((106, 0, 0x03FE, 0x7FFF, 0x0000), "S.Mask", "", 1, 1, 0x00, 0x0000),  # MaskType
    ((107, 0, 0x03CB, 0x7FFF, 0x0000), "S.Tube", "", 1, 1, 0x00, 0x0000),  # TubeType
    ((108, 0, 0x036B, 0x7FFF, 0x0000), "S.ClimateControl", "", 1, 1, 0x00, 0x0000),  # ClimateControl
    ((109, 0, 0x03D6, 0x7FFF, 0x0000), "S.HumEnable", "", 1, 1, 0x00, 0x0000),  # HumidifierSettingEnable
    ((110, 0, 0x0188, 0x7FFF, 0x0000), "S.HumLevel", "", 1, 1, 0x00, 0x0000),  # HumidifierLevel
    ((111, 0, 0x03C4, 0x7FFF, 0x0000), "S.TempEnable", "", 1, 1, 0x00, 0x0000),  # HeatedTubeSettingEnable
    ((112, 0, 0x0175, 0x7FFF, 0x0000), "S.Temp", "Celsius", 0.100000001, 10, 0x00, 0x0000),  # HeatedTubeTemperature
    ((127, 0, 0x03CD, 0x7FFF, 0x0000), "HeatedTube", "", 1, 1, 0x01, 0x0000),  # Summary-TubeConnected
    ((128, 0, 0x03D1, 0x7FFF, 0x0000), "Humidifier", "", 1, 1, 0x01, 0x0000),  # Summary-HumidifierConnected
    ((129, 7, 0x00D2, 0x7FFF, 0x005F), "BlowPress.95", "cmH2O", 2, 50, 0x01, 0x0000),  # Summary-BlowerPressure-95
    ((130, 7, 0x00D1, 0x7FFF, 0x0005), "BlowPress.5", "cmH2O", 2, 50, 0x01, 0x0000),  # Summary-BlowerPressure-5
    ((131, 7, 0x00BF, 0x7FFF, 0x005F), "Flow.95", "L/s", 0.200000003, 500, 0x01, 0x0000),  # Summary-RespiratoryFlow-95
    ((132, 7, 0x00BE, 0x7FFF, 0x0005), "Flow.5", "L/s", 0.200000003, 500, 0x01, 0x0000),  # Summary-RespiratoryFlow-5
    ((133, 7, 0x00B7, 0x7FFF, 0x0032), "BlowFlow.50", "L/s", 0.200000003, 500, 0x01, 0x0000),  # Summary-BlowerFlow-50
    ((134, 7, 0x00AB, 0x7FFF, 0x0032), "AmbHumidity.50", "mg/L", 10, 10, 0x01, 0x0000),  # Summary-AmbientHumidity-50
    ((135, 7, 0x00B2, 0x7FFF, 0x0032), "HumTemp.50", "Celsius", 10, 10, 0x01, 0x0000),  # Summary-HumidifierTemperature-50
    ((136, 7, 0x00B0, 0x7FFF, 0x0032), "HTubeTemp.50", "Celsius", 10, 10, 0x01, 0x0000),  # Summary-HeatedTubeTemperature-50
    ((137, 7, 0x00AE, 0x7FFF, 0x0032), "HTubePow.50", "%", 10, 10, 0x01, 0x0000),  # Summary-HeatedTubePower-50
    ((138, 7, 0x00B4, 0x7FFF, 0x0032), "HumPow.50", "%", 10, 10, 0x01, 0x0000),  # Summary-HumidifierPower-50
    ((139, 6, 0x029F, 0x7FFF, 0x0032), "SpO2.50", "%", 100, 1, 0x01, 0x0000),  # Summary-SpO2-50
    ((140, 6, 0x029D, 0x7FFF, 0x005F), "SpO2.95", "%", 100, 1, 0x01, 0x0000),  # Summary-SpO2-95
    ((141, 6, 0x029E, 0x7FFF, 0x0064), "SpO2.Max", "%", 100, 1, 0x01, 0x0000),  # Summary-SpO2-100
    ((142, 1, 0x02A0, 0x7FFF, 0x0000), "SpO2Thresh", "min.", 1, 1, 0x01, 0x0000),  # SAU
    ((146, 5, 0x02A4, 0x02FF, 0x0000), "SpontTrig%", "%", 50, 2, 0x01, 0x0000),  # Summary-SpontTriggerPercentage
    ((147, 5, 0x02A3, 0x02FE, 0x0000), "SpontCyc%", "%", 50, 2, 0x01, 0x0000),  # Summary-SpontCyclePercentage
    ((148, 7, 0x01EB, 0x7FFF, 0x0032), "MaskPress.50", "cmH2O", 2, 50, 0x01, 0x0000),  # Summary-MeanMaskPressure-50
    ((149, 7, 0x01E9, 0x7FFF, 0x005F), "MaskPress.95", "cmH2O", 2, 50, 0x01, 0x0000),  # Summary-MeanMaskPressure-95
    ((150, 7, 0x01E8, 0x7FFF, 0x0064), "MaskPress.Max", "cmH2O", 2, 50, 0x01, 0x0000),  # Summary-MeanMaskPressure-100
    ((151, 6, 0x01B1, 0x7FFF, 0x0032), "TgtIPAP.50", "cmH2O", 2, 50, 0x01, 0x0000),  # Summary-InspiratoryPressure-50
    ((152, 6, 0x01AC, 0x7FFF, 0x005F), "TgtIPAP.95", "cmH2O", 2, 50, 0x01, 0x0000),  # Summary-InspiratoryPressure-95
    ((153, 6, 0x01B0, 0x7FFF, 0x0064), "TgtIPAP.Max", "cmH2O", 2, 50, 0x01, 0x0000),  # Summary-InspiratoryPressure-100
    ((154, 6, 0x0137, 0x7FFF, 0x0032), "TgtEPAP.50", "cmH2O", 2, 50, 0x01, 0x0000),  # Summary-ExpiratoryPressure-50
    ((155, 6, 0x0135, 0x7FFF, 0x005F), "TgtEPAP.95", "cmH2O", 2, 50, 0x01, 0x0000),  # Summary-ExpiratoryPressure-95
    ((156, 6, 0x0136, 0x7FFF, 0x0064), "TgtEPAP.Max", "cmH2O", 2, 50, 0x01, 0x0000),  # Summary-ExpiratoryPressure-100
    ((157, 6, 0x01C4, 0x7FFF, 0x0032), "Leak.50", "L/s", 2, 50, 0x01, 0x0000),  # Summary-Leak-50
    ((158, 6, 0x01C1, 0x7FFF, 0x005F), "Leak.95", "L/s", 2, 50, 0x01, 0x0000),  # Summary-Leak-95
    ((159, 6, 0x01C0, 0x7FFF, 0x0046), "Leak.70", "L/s", 2, 50, 0x01, 0x0000),  # Summary-Leak-75
    ((160, 6, 0x01C3, 0x7FFF, 0x0064), "Leak.Max", "L/s", 2, 50, 0x01, 0x0000),  # Summary-Leak-100
    ((161, 6, 0x020B, 0x7FFF, 0x0032), "MinVent.50", "L/min", 12.5, 8, 0x01, 0x0000),  # Summary-MinuteVentilation-50
    ((162, 6, 0x0209, 0x7FFF, 0x005F), "MinVent.95", "L/min", 12.5, 8, 0x01, 0x0000),  # Summary-MinuteVentilation-95
    ((163, 6, 0x020A, 0x7FFF, 0x0064), "MinVent.Max", "L/min", 12.5, 8, 0x01, 0x0000),  # Summary-MinuteVentilation-100
    ((164, 6, 0x0270, 0x7FFF, 0x0032), "RespRate.50", "bpm", 20, 5, 0x01, 0x0000),  # Summary-RespiratoryRate-50
    ((165, 6, 0x026E, 0x7FFF, 0x005F), "RespRate.95", "bpm", 20, 5, 0x01, 0x0000),  # Summary-RespiratoryRate-95
    ((166, 6, 0x026F, 0x7FFF, 0x0064), "RespRate.Max", "bpm", 20, 5, 0x01, 0x0000),  # Summary-RespiratoryRate-100
    ((167, 6, 0x031E, 0x7FFF, 0x0032), "TidVol.50", "L", 2, 50, 0x01, 0x0000),  # Summary-TidalVolume-50
    ((168, 6, 0x031C, 0x7FFF, 0x005F), "TidVol.95", "L", 2, 50, 0x01, 0x0000),  # Summary-TidalVolume-95
    ((169, 6, 0x031D, 0x7FFF, 0x0064), "TidVol.Max", "L", 2, 50, 0x01, 0x0000),  # Summary-TidalVolume-100
    ((170, 6, 0x02CF, 0x7FFF, 0x0032), "TgtVent.50", "L/min", 12.5, 8, 0x01, 0x0000),  # Summary-TargetMinuteVentilation-50
    ((171, 6, 0x02CD, 0x7FFF, 0x005F), "TgtVent.95", "L/min", 12.5, 8, 0x01, 0x0000),  # Summary-TargetMinuteVentilation-95
    ((172, 6, 0x02CE, 0x7FFF, 0x0064), "TgtVent.Max", "L/min", 12.5, 8, 0x01, 0x0000),  # Summary-TargetMinuteVentilation-100
    ((173, 6, 0x01B4, 0x7FFF, 0x0032), "IERatio.50", "%", 100, 1, 0x01, 0x0000),  # Summary-IeRatio-50
    ((174, 6, 0x01B2, 0x7FFF, 0x005F), "IERatio.95", "%", 100, 1, 0x01, 0x0000),  # Summary-IeRatio-95
    ((175, 6, 0x01B3, 0x7FFF, 0x0064), "IERatio.Max", "%", 100, 1, 0x01, 0x0000),  # Summary-IeRatio-100
    ((176, 6, 0x0193, 0x7FFF, 0x0032), "Ti.50", "seconds", 20, 50, 0x01, 0x0000),  # Summary-InspiratoryDuration-50
    ((177, 6, 0x0191, 0x7FFF, 0x005F), "Ti.95", "seconds", 20, 50, 0x01, 0x0000),  # Summary-InspiratoryDuration-95
    ((178, 6, 0x0192, 0x7FFF, 0x0064), "Ti.Max", "seconds", 20, 50, 0x01, 0x0000),  # Summary-InspiratoryDuration-100
    ((179, 4, 0x007D, 0x7FFF, 0x0000), "AHI", "", 10, 10, 0x01, 0x0000),  # Summary-ApneaHypopneaIndex
    ((180, 4, 0x017D, 0x7FFF, 0x0000), "HI", "", 10, 10, 0x01, 0x0000),  # Summary-HypopneaIndex
    ((181, 4, 0x007F, 0x7FFF, 0x0000), "AI", "", 10, 10, 0x01, 0x0000),  # Summary-ApneaIndex
    ((182, 4, 0x00E4, 0x7FFF, 0x0000), "OAI", "", 10, 10, 0x01, 0x0000),  # Summary-ObstructiveApneaIndex
    ((183, 4, 0x0215, 0x7FFF, 0x0000), "CAI", "", 10, 10, 0x01, 0x0000),  # Summary-CentralApneaIndex
    ((184, 4, 0x030F, 0x7FFF, 0x0000), "UAI", "", 10, 10, 0x01, 0x0000),  # Summary-UnknownApneaIndex
    ((185, 4, 0x0272, 0x7FFF, 0x0000), "RIN", "", 10, 10, 0x01, 0x0000),  # Summary-ReraIndex
    ((186, 2, 0x010A, 0x7FFF, 0x0000), "CSR", "", 1, 1, 0x01, 0x0000),  # CSD
)


STR_SUPERSET_KEYS = tuple(row[0] for row in STR_SUPERSET_METADATA)


STR_SUPERSET_SELECTED_NAMES = (
    "",
    "PPD",
    "ActiveTherapyProfile",
    "Cpap-StartPressure",
    "Cpap-SetPressure",
    "AutoSet-StartPressure",
    "AutoSet-MaxPressure",
    "AutoSet-MinPressure",
    "HerAuto-StartPressure",
    "HerAuto-MaxPressure",
    "HerAuto-MinPressure",
    "VAuto-StartPressure",
    "VAuto-MaxInspiratoryPressure",
    "VAuto-MinExpiratoryPressure",
    "VAuto-SetPressureSupport",
    "VAuto-SetMaxInspiratoryTime",
    "VAuto-SetMinInspiratoryTime",
    "VAuto-TriggerSensitivity",
    "VAuto-CycleSensitivity",
    "Spont-StartPressure",
    "Spont-TargetInspiratoryPressure",
    "Spont-TargetExpiratoryPressure",
    "Spont-EasyBreatheEnable",
    "Spont-RespiratoryRateEnable",
    "Spont-SetMaxInspiratoryTime",
    "Spont-SetMinInspiratoryTime",
    "Spont-RiseTimeEnable",
    "Spont-RiseTime",
    "Spont-TriggerSensitivity",
    "Spont-CycleSensitivity",
    "ST-StartPressure",
    "ST-TargetInspiratoryPressure",
    "ST-TargetExpiratoryPressure",
    "ST-SetRespiratoryRate",
    "ST-SetMaxInspiratoryTime",
    "ST-SetMinInspiratoryTime",
    "ST-RiseTimeEnable",
    "ST-RiseTime",
    "ST-TriggerSensitivity",
    "ST-CycleSensitivity",
    "Timed-StartPressure",
    "Timed-TargetInspiratoryPressure",
    "Timed-TargetExpiratoryPressure",
    "Timed-SetRespiratoryRate",
    "Timed-SetInspiratoryTime",
    "Timed-RiseTimeEnable",
    "Timed-RiseTime",
    "ASV-StartPressure",
    "ASV-TargetExpiratoryPressure",
    "ASV-MaxPressureSupport",
    "ASV-MinPressureSupport",
    "ASVAuto-StartPressure",
    "ASVAuto-MaxExpiratoryPressure",
    "ASVAuto-MinExpiratoryPressure",
    "ASVAuto-MaxPressureSupport",
    "ASVAuto-MinPressureSupport",
    "AutoSetComfort",
    "RampEnable",
    "RampTime",
    "EprEnablePatientAccess",
    "EprEnable",
    "EprPressure",
    "EprType",
    "SmartStart",
    "PatientView",
    "AntiBacterialFilter",
    "MaskType",
    "TubeType",
    "ClimateControl",
    "HumidifierSettingEnable",
    "HumidifierLevel",
    "HeatedTubeSettingEnable",
    "HeatedTubeTemperature",
    "Summary-TubeConnected",
    "Summary-HumidifierConnected",
    "Summary-BlowerPressure-95",
    "Summary-BlowerPressure-5",
    "Summary-RespiratoryFlow-95",
    "Summary-RespiratoryFlow-5",
    "Summary-BlowerFlow-50",
    "Summary-AmbientHumidity-50",
    "Summary-HumidifierTemperature-50",
    "Summary-HeatedTubeTemperature-50",
    "Summary-HeatedTubePower-50",
    "Summary-HumidifierPower-50",
    "Summary-SpO2-50",
    "Summary-SpO2-95",
    "Summary-SpO2-100",
    "SAU",
    "Summary-SpontTriggerPercentage",
    "Summary-SpontCyclePercentage",
    "Summary-MeanMaskPressure-50",
    "Summary-MeanMaskPressure-95",
    "Summary-MeanMaskPressure-100",
    "Summary-InspiratoryPressure-50",
    "Summary-InspiratoryPressure-95",
    "Summary-InspiratoryPressure-100",
    "Summary-ExpiratoryPressure-50",
    "Summary-ExpiratoryPressure-95",
    "Summary-ExpiratoryPressure-100",
    "Summary-Leak-50",
    "Summary-Leak-95",
    "Summary-Leak-75",
    "Summary-Leak-100",
    "Summary-MinuteVentilation-50",
    "Summary-MinuteVentilation-95",
    "Summary-MinuteVentilation-100",
    "Summary-RespiratoryRate-50",
    "Summary-RespiratoryRate-95",
    "Summary-RespiratoryRate-100",
    "Summary-TidalVolume-50",
    "Summary-TidalVolume-95",
    "Summary-TidalVolume-100",
    "Summary-TargetMinuteVentilation-50",
    "Summary-TargetMinuteVentilation-95",
    "Summary-TargetMinuteVentilation-100",
    "Summary-IeRatio-50",
    "Summary-IeRatio-95",
    "Summary-IeRatio-100",
    "Summary-InspiratoryDuration-50",
    "Summary-InspiratoryDuration-95",
    "Summary-InspiratoryDuration-100",
    "Summary-ApneaHypopneaIndex",
    "Summary-HypopneaIndex",
    "Summary-ApneaIndex",
    "Summary-ObstructiveApneaIndex",
    "Summary-CentralApneaIndex",
    "Summary-UnknownApneaIndex",
    "Summary-ReraIndex",
    "CSD",
)


def align_up(value: int, align: int) -> int:
    return (value + align - 1) & ~(align - 1)


class S11EdfSupersetPatcher:
    def __init__(self, asf):
        self.asf = asf

    def stream_headers(self):
        base = self.asf.globals_offset(16)
        out = []
        for index in range(8):
            off = base + index * STREAM_HEADER_SIZE
            period = self.asf.u16(off)
            samples = self.asf.u16(off + 2)
            count = self.asf.u32(off + 4)
            tag_ptr = self.asf.u32(off + 8)
            table_ptr = self.asf.u32(off + 12)
            tag = self.asf.string_at_ptr(tag_ptr)
            table_off = self.asf.ptr_to_off(table_ptr)
            if not tag or table_off is None or count > 128 or period == 0:
                break
            out.append({
                "index": index,
                "offset": off,
                "tag": tag,
                "period_ms": period,
                "samples_per_60s": samples,
                "signal_count": count,
                "signal_table_ptr": table_ptr,
                "signal_table_off": table_off,
            })
        return out

    def stream_signals(self, stream):
        out = []
        for index in range(stream["signal_count"]):
            off = stream["signal_table_off"] + index * STREAM_SIGNAL_SIZE
            name_ptr = self.asf.u32(off + 4)
            unit_ptr = self.asf.u32(off + 8)
            out.append({
                "index": index,
                "offset": off,
                "id": self.asf.u32(off),
                "name_ptr": name_ptr,
                "name": self.asf.string_at_ptr(name_ptr) or "",
                "unit_ptr": unit_ptr,
                "unit": self.asf.string_at_ptr(unit_ptr, allow_empty=True) or "",
                "scale": struct.unpack_from("<f", self.asf.fw, off + 12)[0],
            })
        return out

    def find_stream(self, tag):
        for stream in self.stream_headers():
            if stream["tag"] == tag:
                return stream
        raise ValueError("EDF stream %s not found" % tag)

    def resolve_stream_signals(self, wanted_signals):
        out = []
        for var_name, label, unit, scale in wanted_signals:
            rows = self.asf.find_descriptors_by_name(var_name)
            if not rows:
                raise ValueError("EDF stream variable %s not found" % var_name)
            if len(rows) != 1:
                raise ValueError("EDF stream variable %s is ambiguous (%d matches)" % (var_name, len(rows)))
            out.append((rows[0]["var_id"], label, unit, scale))
        return out

    def find_existing_string_ptr(self, text):
        if text == "":
            return None
        needle = text.encode("ascii") + b"\x00"
        pos = bytes(self.asf.fw).find(needle)
        if pos < 0:
            return None
        return self.asf.off_to_addr(pos)

    def resolve_str_string_ptrs(self, texts):
        ptrs = {"": 0}
        needed = []
        needed_set = set()
        for text in texts:
            if text in ptrs:
                continue
            ptr = self.find_existing_string_ptr(text)
            if ptr is None:
                if text not in needed_set:
                    needed_set.add(text)
                    needed.append(text)
            else:
                ptrs[text] = ptr

        if not needed:
            return ptrs, 0

        alloc_size = sum(len(text.encode("ascii")) + 1 for text in needed)
        off = self.find_conf_slack(alloc_size, align=4)
        for text in needed:
            ptrs[text] = self.asf.off_to_addr(off)
            raw = text.encode("ascii") + b"\x00"
            self.asf.fw[off:off + len(raw)] = raw
            off += len(raw)
        return ptrs, len(needed)

    def find_conf_slack(self, size, align=4):
        start = self.asf.CONF_OFF
        end = self.asf.CONF_OFF + self.asf.CONF_SIZE - 2
        data = self.asf.fw
        best = None
        off = start
        while off < end:
            while off < end and data[off] != 0xFF:
                off += 1
            run_start = off
            while off < end and data[off] == 0xFF:
                off += 1
            run_end = off
            candidate = align_up(run_start, align)
            if candidate + size <= run_end:
                best = candidate
        if best is None:
            raise ValueError("not enough erased CONF slack for %d-byte EDF patch" % size)
        return best

    def stream_is_already_superset(self, stream, resolved_signals):
        signals = self.stream_signals(stream)
        if len(signals) != len(resolved_signals):
            return False
        for got, want in zip(signals, resolved_signals):
            sig_id, name, unit, scale = want
            if got["id"] != sig_id or got["name"] != name or got["unit"] != unit:
                return False
            if abs(got["scale"] - scale) > 0.00001:
                return False
        return True

    def patch_stream_schema(self, tag, wanted_signals):
        stream = self.find_stream(tag)
        resolved_signals = self.resolve_stream_signals(wanted_signals)
        if self.stream_is_already_superset(stream, resolved_signals):
            print("Patching EDF %s stream... already superset" % tag)
            return 0

        existing_signals = self.stream_signals(stream)
        existing_strings = {}
        for sig in existing_signals:
            existing_strings.setdefault(sig["name"], sig["name_ptr"])
            existing_strings.setdefault(sig["unit"], sig["unit_ptr"])

        needed_strings = []
        needed_set = set()
        ptrs = {}
        for _sig_id, name, unit, _scale in resolved_signals:
            for text in (name, unit):
                if text in ptrs:
                    continue
                ptr = existing_strings.get(text)
                if ptr is None:
                    ptr = self.find_existing_string_ptr(text)
                if ptr is None:
                    if text not in needed_set:
                        needed_set.add(text)
                        needed_strings.append(text)
                else:
                    ptrs[text] = ptr

        table_size = len(resolved_signals) * STREAM_SIGNAL_SIZE
        strings_size = sum(len(text.encode("ascii")) + 1 for text in needed_strings)
        strings_start_rel = align_up(table_size, 4)
        alloc_size = strings_start_rel + strings_size
        alloc_off = self.find_conf_slack(alloc_size, align=4)
        table_off = alloc_off
        string_off = alloc_off + strings_start_rel

        for text in needed_strings:
            ptrs[text] = self.asf.off_to_addr(string_off)
            raw = text.encode("ascii") + b"\x00"
            self.asf.fw[string_off:string_off + len(raw)] = raw
            string_off += len(raw)

        for index, (sig_id, name, unit, scale) in enumerate(resolved_signals):
            off = table_off + index * STREAM_SIGNAL_SIZE
            struct.pack_into(
                "<IIIf",
                self.asf.fw,
                off,
                sig_id,
                ptrs[name],
                ptrs[unit],
                scale,
            )

        self.asf.write_u32(stream["offset"] + 4, len(resolved_signals))
        self.asf.write_u32(stream["offset"] + 12, self.asf.off_to_addr(table_off))
        print(
            "Patching EDF %s stream... %d signals, table 0x%06X, %d strings"
            % (tag, len(resolved_signals), table_off, len(needed_strings))
        )
        return 1

    def patch_stream_schemas(self):
        changed = 0
        for tag, signals in STREAM_SCHEMAS:
            changed += self.patch_stream_schema(tag, signals)
        return changed

    def find_csl_event_schema(self):
        base = self.asf.globals_offset(17)
        end = min(len(self.asf.fw), self.asf.CONF_OFF + self.asf.CONF_SIZE)
        for schema_bytes in (EVENT_SCHEMA_SIZE, LEGACY_EVENT_SCHEMA_SIZE):
            off = base
            while off + schema_bytes <= end:
                if schema_bytes == EVENT_SCHEMA_SIZE:
                    label_count = self.asf.u16(off + 2)
                    flags_off = off + 0x0c
                    tag_ptr = self.asf.u32(off + 0x10)
                    label_table = self.asf.u32(off + 0x18)
                else:
                    label_count = self.asf.u16(off)
                    flags_off = off + 8
                    tag_ptr = self.asf.u32(off + 0x0c)
                    label_table = self.asf.u32(off + 0x10)

                tag = self.asf.string_at_ptr(tag_ptr)
                if not tag:
                    break
                if tag == "CSL":
                    table_off = self.asf.ptr_to_off(label_table)
                    if (label_count == 0 or table_off is None or
                            table_off + label_count * 4 > len(self.asf.fw)):
                        raise ValueError("invalid CSL event label table")
                    labels = []
                    for index in range(label_count):
                        label = self.asf.string_at_ptr(
                            self.asf.u32(table_off + index * 4),
                            allow_empty=True,
                        )
                        if label is None:
                            raise ValueError("invalid CSL event label")
                        labels.append(label)
                    return flags_off, labels
                off += schema_bytes
        raise ValueError("CSL event schema not found")

    def patch_csl_events(self):
        flags_off, labels = self.find_csl_event_schema()
        if labels != ["", "CSR Start", "CSR End"]:
            raise ValueError("unexpected CSL event labels: %r" % labels)
        if self.asf.u8(flags_off + 1) == 0:
            raise ValueError("CSL event schema does not backdate boundary onsets")
        if self.asf.u8(flags_off) != 0:
            print("Patching EDF CSL events... already enabled")
            return 0
        self.asf.write_u8(flags_off, 1)
        print("Patching EDF CSL events... enabled")
        return 1

    def summary_key(self, off):
        kind = self.asf.u32(off + 4)
        var_a = self.asf.u16(off + 8)
        var_b = self.asf.u16(off + 10)
        selected = var_b if kind < 3 else var_a
        return (
            self.asf.u32(off),
            kind,
            selected,
            self.asf.u16(off + 12),
            self.asf.u16(off + 14),
        )

    def summary_selected_name(self, off):
        kind = self.asf.u32(off + 4)
        selected = self.asf.u16(off + 10) if kind < 3 else self.asf.u16(off + 8)
        if selected == 0x7FFF:
            return ""
        return self.asf.var_name(selected)

    def patch_str_summary(self):
        header = self.asf.globals_offset(15)
        count = self.asf.u16(header + 4)
        table_off = self.asf.ptr_to_off(self.asf.u32(header + 8))
        if table_off is None:
            raise ValueError("STR SummaryRecord pointer is outside image")

        metadata_by_key = {row[0]: row[1:] for row in STR_SUPERSET_METADATA}
        wanted_keys = set(STR_SUPERSET_KEYS)
        if set(metadata_by_key) != wanted_keys:
            raise ValueError("STR metadata/key table mismatch")
        if len(STR_SUPERSET_SELECTED_NAMES) != len(STR_SUPERSET_METADATA):
            raise ValueError("STR selected-name table length mismatch")
        metadata_by_name = {}
        for name, row in zip(STR_SUPERSET_SELECTED_NAMES, STR_SUPERSET_METADATA):
            if not name:
                continue
            if name in metadata_by_name:
                raise ValueError("duplicate STR selected name %s" % name)
            metadata_by_name[name] = row[1:]

        strings = []
        for _key, label, unit, _logical_scale, _edf_scale, _record_class, _reserved16 in STR_SUPERSET_METADATA:
            strings.append(label)
            strings.append(unit)
        string_ptrs, strings_written = self.resolve_str_string_ptrs(strings)

        found = set()
        activated = 0
        hydrated = 0
        for index in range(count):
            off = table_off + index * SUMMARY_RECORD_SIZE
            key = self.summary_key(off)
            selected_name = self.summary_selected_name(off)
            metadata = metadata_by_name.get(selected_name)
            found_id = selected_name
            if metadata is None:
                metadata = metadata_by_key.get(key)
                found_id = key
            if metadata is None:
                continue
            found.add(found_id)
            label, unit, logical_scale, edf_scale, record_class, reserved16 = metadata
            before = bytes(self.asf.fw[off + 16:off + 36])
            struct.pack_into("<f", self.asf.fw, off + 16, logical_scale)
            self.asf.write_u8(off + 20, record_class)
            if self.asf.u8(off + 21) == 0:
                self.asf.write_u8(off + 21, 1)
                activated += 1
            self.asf.write_u16(off + 22, reserved16)
            self.asf.write_u32(off + 24, string_ptrs[label])
            self.asf.write_u32(off + 28, string_ptrs[unit])
            struct.pack_into("<f", self.asf.fw, off + 32, edf_scale)
            if bytes(self.asf.fw[off + 16:off + 36]) != before:
                hydrated += 1

        wanted_names = set(name for name in STR_SUPERSET_SELECTED_NAMES if name)
        missing = len(wanted_names - found)
        if STR_SUPERSET_KEYS[0] not in found:
            missing += 1
        if missing:
            print("  WARN: %d STR superset rows were not found in this image" % missing)
        print(
            "Patching EDF STR summary... %d rows activated, %d rows hydrated, %d strings, %d/%d present"
            % (activated, hydrated, strings_written, len(found), len(STR_SUPERSET_METADATA))
        )
        return activated + hydrated + strings_written

    def patch(self):
        changed = self.patch_stream_schemas()
        changed += self.patch_csl_events()
        changed += self.patch_str_summary()
        return changed


def patch_edf_superset(asf):
    return S11EdfSupersetPatcher(asf).patch()


def load_patch_module():
    here = Path(__file__).resolve().parent
    path = here / "patch-airsense-s11.py"
    spec = importlib.util.spec_from_file_location("patch_airsense_s11", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load %s" % path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def build_arg_parser():
    parser = argparse.ArgumentParser(description="Patch S11 EDF superset metadata.")
    parser.add_argument("infile", help="Input full S11 firmware image")
    parser.add_argument("outfile", help="Output patched firmware image")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite output file")
    return parser


def main(argv=None):
    args = build_arg_parser().parse_args(argv)
    patch_module = load_patch_module()
    with open(args.infile, "rb") as f:
        asf = patch_module.S11Firmware(f)
    patch_edf_superset(asf)
    asf.fix_crcs()
    asf.write_output(args.outfile, args.overwrite)
    return 0


if __name__ == "__main__":
    script_dir = os.path.dirname(os.path.abspath(__file__))
    if script_dir not in sys.path:
        sys.path.insert(0, script_dir)
    raise SystemExit(main())

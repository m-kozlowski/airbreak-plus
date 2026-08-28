"""Spool (device-side data archive) support. Transport-agnostic.

Protocol dance plus protobuf payload decoders. 
"""

from __future__ import annotations

import base64
import binascii
from collections import Counter
import csv
import hashlib
import json
import re
import sys
import textwrap
from typing import Iterator

from as11_rpc_vars import EVENT_FAMILIES, SPOOL_REGISTRY

try:
    from as11_diagnostic_errors import (
        SELECTOR_BY_SPOOL, summarize_diagnostic_code,
    )
except ModuleNotFoundError as exc:
    if exc.name != "as11_diagnostic_errors":
        raise
    SELECTOR_BY_SPOOL = {}
    summarize_diagnostic_code = None


SPOOL_FRAGMENT_SIZE = 3000
SPOOL_FRAGMENT_SIZE_LIMIT = 3576
SPOOL_OUTPUT_FORMATS = ("json", "csv", "table", "summary")
SPOOL_OUTPUT_DEFAULT = "table"


class SpoolError(Exception):
    """A spool RPC round failed or returned an invalid fragment sequence.

    The original JSON-RPC response (when applicable) is exposed as
    `.response`, with the device's error code/message split out as
    `.code` and `.message`.
    """

    def __init__(self, message: str, *, response: dict | None = None,
                 code: int | None = None):
        super().__init__(message)
        self.response = response
        self.message = message
        self.code = code


class SpoolDecodeError(ValueError):
    """A spool payload could not be decoded completely."""


# Single-round spool cycle. Transport-agnostic.

def spool_one_round(transport, spool_address: dict, max_size: int,
                    *, fragment_timeout: float = 30.0,
                    fragment_max: int = SPOOL_FRAGMENT_SIZE,
                    verbose: bool = True,
                    ) -> tuple[bytes, str, dict | None, int]:
    """Run one StartSpool -> PullSpoolFragments cycle against `transport`.

    Returns (data_bytes, status, next_spool_address_or_None, frag_count).
    Verifies per-round SHA256 against spoolHash reported by the device.

    Raises `SpoolError` for rejected RPC calls, incomplete or malformed
    fragment sequences, and hash mismatches.

    `transport` must implement the as11_rpc.Transport protocol with a
    working `listen_for_notifications`.
    """
    if not isinstance(max_size, int) or isinstance(max_size, bool):
        raise SpoolError("maxSpoolSize must be an integer")
    if max_size <= 0 or max_size > 0x7FFFFFFF:
        raise SpoolError("maxSpoolSize must be in range 1..2147483647")
    if not isinstance(fragment_max, int) or isinstance(fragment_max, bool):
        raise SpoolError("maxFragmentSize must be an integer")
    if fragment_max <= 0:
        raise SpoolError("maxFragmentSize must be positive")

    fragments: list[tuple[int, bytes]] = []
    state = {
        "status": "", "hash": "", "next": None, "done": False,
        "error": None, "spool_id": None,
    }

    def on_notify(msg: dict):
        if msg.get("method") != "SpoolFragment":
            return None
        params = msg.get("params", {})
        if not isinstance(params, dict):
            state["error"] = "SpoolFragment params is not an object"
            state["done"] = True
            return True
        notify_spool_id = params.get("spoolId")
        if (state["spool_id"] is not None
                and notify_spool_id != state["spool_id"]):
            return None
        seq = params.get("seq", -1)
        data_b64 = params.get("data", "")
        status = params.get("status", "")
        raw = b""
        if data_b64:
            if not isinstance(seq, int) or isinstance(seq, bool) or seq < 0:
                state["error"] = f"invalid fragment sequence number {seq!r}"
                state["done"] = True
                return True
            if not isinstance(data_b64, str):
                state["error"] = f"fragment {seq} data is not Base64 text"
                state["done"] = True
                return True
            try:
                raw = base64.b64decode(data_b64, validate=True)
            except (ValueError, binascii.Error) as exc:
                state["error"] = f"fragment {seq} Base64 decode failed: {exc}"
                state["done"] = True
                return True
            fragments.append((seq, raw))
        if verbose:
            print(f"  fragment seq={seq} len={len(raw)} status={status}",
                  file=sys.stderr, flush=True)
        state["status"] = status
        state["hash"] = params.get("spoolHash", "")
        state["next"] = params.get("nextSpoolAddress")
        if status != "SPOOL_INCOMPLETE":
            state["done"] = True
            return True   # stop listener
        return None

    transport.set_notification_handler(on_notify)
    try:
        resp = transport.rpc("StartSpool", {
            "spoolAddress": spool_address,
            "maxSpoolSize": max_size,
        })
        err = resp.get("error") if isinstance(resp, dict) else None
        if err:
            code = err.get("code")
            msg = err.get("message", "")
            raise SpoolError(
                f"StartSpool refused: {msg or 'unknown error'} (code {code})",
                response=resp, code=code,
            )
        spool_id = resp.get("result", {}).get("spoolId", 0)
        if verbose:
            print(f"StartSpool: spoolId={spool_id}", file=sys.stderr)
        if spool_id == 0:
            raise SpoolError("StartSpool returned spoolId=0", response=resp)
        state["spool_id"] = spool_id

        pull_resp = transport.rpc("PullSpoolFragments", {
            "spoolId": spool_id,
            "maxFragmentSize": fragment_max,
            "maxNotifications": 0,
        }, timeout=5.0)
        pull_err = (pull_resp.get("error")
                    if isinstance(pull_resp, dict) else None)
        if pull_err:
            code = pull_err.get("code")
            msg = pull_err.get("message", "")
            raise SpoolError(
                f"PullSpoolFragments refused: "
                f"{msg or 'unknown error'} (code {code})",
                response=pull_resp, code=code,
            )

        if not state["done"]:
            transport.listen_for_notifications(duration=fragment_timeout)
    finally:
        transport.set_notification_handler(None)

    if state["error"]:
        raise SpoolError(str(state["error"]))
    if not state["done"]:
        raise SpoolError(
            f"no terminal fragment received within {fragment_timeout:g}s"
        )

    fragments.sort(key=lambda x: x[0])
    seqs = [seq for seq, _data in fragments]
    if seqs != list(range(len(seqs))):
        raise SpoolError(f"invalid fragment sequence: {seqs}")
    data = b"".join(f[1] for f in fragments)

    expected = state["hash"]
    if not isinstance(expected, str) or len(expected) != 64:
        raise SpoolError("terminal fragment did not contain a valid SHA256")
    try:
        bytes.fromhex(expected)
    except ValueError as exc:
        raise SpoolError("terminal fragment contained an invalid SHA256") from exc
    actual = hashlib.sha256(data).hexdigest().upper()
    if actual != expected.upper():
        raise SpoolError(
            f"spool SHA256 mismatch: expected {expected.upper()}, got {actual}"
        )
    if verbose:
        print(f"  SHA256: OK ({len(data)} bytes, {len(fragments)} fragments)",
              file=sys.stderr)

    return data, state["status"], state["next"], len(fragments)



_PROTO_WIRE = {0: "varint", 1: "64-bit", 2: "bytes", 5: "32-bit"}


def _proto_read_varint(data, i):
    v = 0
    shift = 0
    while shift < 70:
        if i >= len(data):
            raise ValueError("truncated protobuf varint")
        b = data[i]
        i += 1
        v |= (b & 0x7F) << shift
        if (b & 0x80) == 0:
            return v, i
        shift += 7
    raise ValueError("protobuf varint exceeds 10 bytes")


def proto_decode(data: bytes) -> list[tuple[int, int, object]]:
    """Walk protobuf wire format. Returns [(field, wire, value), ...]."""
    out = []
    i = 0
    while i < len(data):
        key, i = _proto_read_varint(data, i)
        field = key >> 3
        wire = key & 7
        if field == 0:
            raise ValueError(f"invalid protobuf field 0 at offset {i}")
        if wire == 0:
            v, i = _proto_read_varint(data, i); out.append((field, wire, v))
        elif wire == 1:
            if i + 8 > len(data):
                raise ValueError(f"truncated 64-bit field {field}")
            out.append((field, wire, int.from_bytes(data[i:i + 8], "little"))); i += 8
        elif wire == 2:
            ln, i = _proto_read_varint(data, i)
            if i + ln > len(data):
                raise ValueError(
                    f"truncated bytes field {field}: need {ln}, "
                    f"have {len(data) - i}"
                )
            out.append((field, wire, bytes(data[i:i + ln]))); i += ln
        elif wire == 5:
            if i + 4 > len(data):
                raise ValueError(f"truncated 32-bit field {field}")
            out.append((field, wire, int.from_bytes(data[i:i + 4], "little"))); i += 4
        else:
            raise ValueError(f"unsupported wire type {wire} at offset {i}")
    return out


def _event_code_map(selector: str, codes: tuple[int, ...],
                    *, labels_from: str | None = None) -> dict[int, str]:
    labels = EVENT_FAMILIES[labels_from or selector]
    if len(codes) != len(labels):
        raise RuntimeError(
            f"{selector}: {len(codes)} wire codes for {len(labels)} labels"
        )
    if len(set(codes)) != len(codes):
        raise RuntimeError(f"{selector}: duplicate wire event code")
    return dict(zip(codes, labels))


_SYSTEM_ERROR_CODES = (
    1, 2, 4, 5, 6, 7, 8, 9, 10, 12, 13, 14, 15, 16, 17, 18,
    21, 22, 19, 20, 23, 24, 25,
)

SPOOL_LEGENDS: dict[str, dict] = {
    "UsageEvents-TherapyStatusEvents": {
        "event_types": _event_code_map(
            "UsageEvents-TherapyStatusEvents",
            (1, 2, 3, 4, 5, 6, 7, 8, 10, 11),
        ),
    },
    "TherapyEvents-RespiratoryEvents": {
        "event_types": _event_code_map(
            "TherapyEvents-RespiratoryEvents",
            (1, 2, 3, 4, 5, 6, 8, 9),
        ),
    },
    "SystemActivityEvents-FrequentActivityEvents": {
        "event_types": _event_code_map(
            "SystemActivityEvents-FrequentActivityEvents",
            (
                1, 2, 3, 4, 5, 7, 10, 11, 16, 17, 20, 76, 29, 31,
                32, 80, 75, 77, 79, 78, 101, 103, 102, 106, 92, 62,
                89, 90, 84, 85, 111, 112, 113, 120, 121, 122, 116,
                117, 118, 119, 130, 129, 131, 134, 135, 137, 138,
                148, 149, 150, 156, 157,
            ),
        ),
    },
    "SystemActivityEvents-SporadicActivityEvents": {
        "event_types": _event_code_map(
            "SystemActivityEvents-SporadicActivityEvents",
            (
                1, 107, 12, 13, 15, 91, 23, 24, 94, 95, 33, 108,
                93, 97, 99, 98, 96, 110, 109, 39, 41, 42, 43, 44,
                45, 46, 82, 49, 53, 54, 55, 57, 58, 81, 64, 63,
                66, 67, 74, 87, 88, 34, 61, 104, 105, 100, 65, 52,
                114, 115, 123, 124, 125, 126, 127, 128, 132, 133,
                136, 139, 140, 141, 142, 143, 144, 145, 146, 147,
                151, 152, 153, 154, 155, 158, 159, 160, 161, 162,
            ),
        ),
    },
    "SystemExceptionEvents-SystemErrors": {
        "event_types": _event_code_map(
            "SystemExceptionEvents-SystemErrors", _SYSTEM_ERROR_CODES
        ),
    },
    "SystemExceptionEvents-RecoverableErrors": {
        "event_types": _event_code_map(
            "SystemExceptionEvents-RecoverableErrors", (1, 2, 3, 4)
        ),
    },
    "SystemExceptionEvents-HumidifierErrors": {
        "event_types": _event_code_map(
            "SystemExceptionEvents-HumidifierErrors", (1, 2, 3, 4, 5, 6)
        ),
    },
    "SystemExceptionEvents-HeatedTubeErrors": {
        "event_types": _event_code_map(
            "SystemExceptionEvents-HeatedTubeErrors",
            (1, 2, 3, 4, 5, 6, 7, 8),
        ),
    },
    "alarmEvents": {
        "event_types": _event_code_map(
            "alarmEvents", tuple(range(40))
        ),
    },
    "alarmDiagnosticEvents": {
        "event_types": _event_code_map(
            "alarmDiagnosticEvents", tuple(range(22))
        ),
    },
    "GUIActivityEvents": {
        "record_kind": "gui",
        "event_types": {
            1: "ActiveScreen",
            2: "TouchItem",
            3: "Swipe",
            4: "Multitouch",
            5: "ScreenState",
        },
    },
    "SurveyEvents": {
        "record_kind": "survey",
    },
    "DiagnosticExceptionEvents-AppErrors": {
        "record_kind": "diagnostic_error",
    },
    "DiagnosticExceptionEvents-FatalErrors": {
        "record_kind": "diagnostic_error",
    },
    "DiagnosticExceptionEvents-ResettableErrors": {
        "record_kind": "diagnostic_error",
    },
    "DiagnosticExceptionEvents-AlarmAppErrors": {
        "record_kind": "diagnostic_error",
    },
    "CellularActivityEvents": {
        "string_field": 17,
        "event_types": {
            2: "CellularComponentsStarting",
            3: "CellularComponentsStopping",
            5: "NetworkGeneration",
            6: "TcpConnectStarted",
            7: "PdpContextActivated",
            9: "PdpContextDeactivated",
            10: "TcpConnected",
            11: "TcpDisconnected",
            12: "TcpConnectFailed",
            13: "HttpResponseStatus",
            14: "RegistrationSucceeded",
            15: "RegistrationFailed",
            16: "SessionResponseValid",
            17: "SessionResponseInvalid",
            22: "SessionExpired",
            23: "DataSpoolReadStarted",
            24: "DataSendSucceeded",
            25: "DataSendFailed",
            27: "DataSpoolReadFailed",
            33: "CellularInitializerStarted",
            60: "MobileNetworkCode",
            61: "MobileCountryCode",
            62: "HttpResponseTimeout",
            87: "NetworkCellIdentifier",
            88: "DataModeSilent",
            89: "DataModeActive",
            90: "CALSystemError",
            91: "PreInitializationStarted",
            92: "PreInitializationCompleted",
            95: "ApplicationLogRecord",
            108: "NetworkLocation",
        },
        "extra_fields": {
            (5, 5): "generation",
            (13, 6): "http_status",
            (24, 16): "result_code",
            (25, 16): "result_code",
            (60, 8): "mnc",
            (61, 9): "mcc",
            (87, 12): "cell_id",
            (90, 13): "cal_system_error_code",
            (95, 15): "report_class",
        },
        "extra_enums": {
            (5, 5): {
                1: "2G",
                2: "3G",
                3: "4G",
                4: "LTE-M",
            },
        },
        "log_error_ids": {
            32: "RpcResponseInvalid",
        },
    },
}


# Family-derived sets pulled from the spool registry. The registry in
# as11_rpc_vars.py is the single source of truth for spool metadata.
RC03_SPOOL_FIELDS: dict[str, int] = {
    name: info["wire_field"]
    for name, info in SPOOL_REGISTRY.items()
    if info["family"] == "rc03" and info.get("wire_field") is not None
}

EVENT_SPOOL_TYPES: set[str] = {
    name for name, info in SPOOL_REGISTRY.items()
    if info["family"] == "event"
}

METRIC_SPOOL_TYPES: set[str] = {
    name for name, info in SPOOL_REGISTRY.items()
    if info["family"] == "metric"
}

PERIODIC_COMPRESSED_SPOOL_TYPES: set[str] = {
    name for name, info in SPOOL_REGISTRY.items()
    if info["family"] == "periodic_compressed"
}


DATA_DELIVERY_FIELDS: dict[int, str] = {
    1: "ConfigurationProfilesCollection",
    2: "SettingProfilesCollection",
    3: "TherapyOneMinutePeriodic",
    4: "MachineMetrics",
    5: "UsageEvents",
    6: "TherapyEvents",
    7: "SystemExceptionEvents",
    8: "SystemActivityEvents",
    9: "DiagnosticExceptionEvents",
    10: "Summary",
    12: "CellularActivityEvents",
    13: "GUIActivityEvents",
    14: "SurveyEvents",
    15: "SoundcheckVector",
    16: "MemoryMetrics",
    17: "DiagnosticTenMinutePeriodic",
    18: "RespiratoryFlow6p25Hz",
    19: "MaskPressure6p25Hz",
    20: "Leak0p5Hz",
    21: "InspiratoryPressure0p5Hz",
    22: "CellularDataUsage",
    23: "AcousticSignatureV2",
    24: "alarmEvents",
    25: "alarmDiagnosticEvents",
    26: "atmosphericPressure10min",
}

# SettingProfiles.ActiveProfiles uses the same exported therapy-mode codes as
# STR Mode, rather than the local ActiveTherapyProfile option indexes.
ACTIVE_THERAPY_PROFILE_NAMES: dict[int, str] = {
    1: "AutoSetProfile",
    2: "AutoSetForHerProfile",
    3: "CpapProfile",
    4: "SpontProfile",
    5: "iVAPSProfile",
    6: "ASVProfile",
    7: "ASVAutoProfile",
    8: "VAutoProfile",
    9: "PACProfile",
    10: "STProfile",
    16: "TimedProfile",
}

# Known _ActiveFeatureProfiles IDs. Firmware's JSON formatter has no named
# entries for the reserved range 8..12, so those values remain numeric.
ACTIVE_FEATURE_PROFILE_NAMES: dict[int, str] = {
    1: "ComfortFeature",
    2: "EprFeature",
    3: "AutoRampFeature",
    4: "RampDownFeature",
    5: "SmartStartStopFeature",
    6: "CircuitFeature",
    7: "ClimateFeature",
    13: "LanguageFeature",
    14: "UserSolutionFeature",
    15: "TemperatureFeature",
    16: "PatientViewFeature",
    17: "TimeZoneFeature",
    18: "CareCheckFeature",
    19: "DeviceHealthFeature",
    20: "ReminderFeature",
    21: "DisplayFeature",
    22: "ConfirmStopFeature",
    23: "TherapyLEDFeature",
    24: "HeightFeature",
    25: "MaskSenseFeature",
}

THERAPY_PROFILE_FIELDS: dict[int, tuple[str, tuple[tuple[int, str, str], ...]]] = {
    1: ("AutoSetProfile", (
        (1, "TherapyModeRaw", "raw"),
        (2, "StartPressure", "pressure"),
        (3, "MinPressure", "pressure"),
        (4, "MaxPressure", "pressure"),
    )),
    2: ("AutoSetForHerProfile", (
        (1, "TherapyModeRaw", "raw"),
        (2, "StartPressure", "pressure"),
        (3, "MinPressure", "pressure"),
        (4, "MaxPressure", "pressure"),
    )),
    3: ("CpapProfile", (
        (1, "TherapyModeRaw", "raw"),
        (2, "SetPressure", "pressure"),
        (3, "StartPressure", "pressure"),
        (4, "TriggerSensitivityRaw", "raw"),
    )),
    4: ("SpontProfile", (
        (1, "TherapyModeRaw", "raw"),
        (2, "StartPressure", "pressure"),
        (3, "TargetInspiratoryPressure", "pressure"),
        (4, "TargetExpiratoryPressure", "pressure"),
        (5, "EasyBreatheEnableRaw", "raw"),
        (6, "RespiratoryRateEnableRaw", "raw"),
        (8, "SetMaxInspiratoryTime", "seconds"),
        (9, "SetMinInspiratoryTime", "seconds"),
        (10, "RiseTimeEnableRaw", "raw"),
        (11, "RiseTime", "milliseconds"),
        (12, "TriggerSensitivityRaw", "raw"),
        (13, "CycleSensitivityRaw", "raw"),
        (14, "FallTimeEnableRaw", "raw"),
        (15, "FallTime", "milliseconds"),
    )),
    5: ("STProfile", (
        (1, "TherapyModeRaw", "raw"),
        (2, "StartPressure", "pressure"),
        (3, "TargetInspiratoryPressure", "pressure"),
        (4, "TargetExpiratoryPressure", "pressure"),
        (6, "SetRespiratoryRate", "bpm_scaled"),
        (7, "SetMaxInspiratoryTime", "seconds"),
        (8, "SetMinInspiratoryTime", "seconds"),
        (9, "RiseTimeEnableRaw", "raw"),
        (10, "RiseTime", "milliseconds"),
        (11, "TriggerSensitivityRaw", "raw"),
        (12, "CycleSensitivityRaw", "raw"),
        (13, "IntelligentBackupRateEnableRaw", "raw"),
        (14, "TargetRespiratoryRate", "bpm_scaled"),
        (15, "FallTimeEnableRaw", "raw"),
        (16, "FallTime", "milliseconds"),
    )),
    6: ("TimedProfile", (
        (1, "TherapyModeRaw", "raw"),
        (2, "StartPressure", "pressure"),
        (3, "TargetInspiratoryPressure", "pressure"),
        (4, "TargetExpiratoryPressure", "pressure"),
        (6, "SetRespiratoryRate", "bpm_scaled"),
        (7, "SetInspiratoryTime", "seconds"),
        (8, "RiseTimeEnableRaw", "raw"),
        (9, "RiseTime", "milliseconds"),
    )),
    7: ("ASVProfile", (
        (1, "TherapyModeRaw", "raw"),
        (2, "StartPressure", "pressure"),
        (3, "TargetExpiratoryPressure", "pressure"),
        (4, "MaxPressureSupport", "pressure"),
        (5, "MinPressureSupport", "pressure"),
    )),
    8: ("ASVAutoProfile", (
        (1, "TherapyModeRaw", "raw"),
        (2, "StartPressure", "pressure"),
        (3, "MaxExpiratoryPressure", "pressure"),
        (4, "MinExpiratoryPressure", "pressure"),
        (5, "MaxPressureSupport", "pressure"),
        (6, "MinPressureSupport", "pressure"),
    )),
    9: ("VAutoProfile", (
        (1, "TherapyModeRaw", "raw"),
        (2, "StartPressure", "pressure"),
        (3, "MaxInspiratoryPressure", "pressure"),
        (4, "MinExpiratoryPressure", "pressure"),
        (5, "SetPressureSupport", "pressure"),
        (6, "SetMaxInspiratoryTime", "seconds"),
        (7, "SetMinInspiratoryTime", "seconds"),
        (8, "TriggerSensitivityRaw", "raw"),
        (9, "CycleSensitivityRaw", "raw"),
    )),
    10: ("PACProfile", (
        (1, "TherapyModeRaw", "raw"),
        (2, "StartPressure", "pressure"),
        (3, "TargetInspiratoryPressure", "pressure"),
        (4, "TargetExpiratoryPressure", "pressure"),
        (5, "SetRespiratoryRate", "bpm_scaled"),
        (6, "SetInspiratoryTime", "centiseconds"),
        (7, "RiseTimeEnableRaw", "raw"),
        (8, "RiseTime", "milliseconds"),
        (9, "TriggerSensitivityRaw", "raw"),
        (10, "FallTimeEnableRaw", "raw"),
        (11, "FallTime", "milliseconds"),
    )),
    11: ("iVAPSProfile", (
        (1, "TherapyModeRaw", "raw"),
        (2, "StartPressure", "pressure"),
        (3, "PatientHeight", "centimeters"),
        (4, "AutoEPAPEnableRaw", "raw"),
        (5, "MaxExpiratoryPressure", "pressure"),
        (6, "MinExpiratoryPressure", "pressure"),
        (7, "TargetExpiratoryPressure", "pressure"),
        (8, "MaxPressureSupport", "pressure"),
        (9, "MinPressureSupport", "pressure"),
        (10, "TargetAlveolarVentilation", "l_min_scaled"),
        (11, "TargetRespiratoryRate", "bpm_scaled"),
        (12, "SetMaxInspiratoryTime", "seconds"),
        (13, "SetMinInspiratoryTime", "seconds"),
        (14, "RiseTimeEnableRaw", "raw"),
        (15, "RiseTime", "milliseconds"),
        (16, "TriggerSensitivityRaw", "raw"),
        (17, "CycleSensitivityRaw", "raw"),
        (18, "FallTimeEnableRaw", "raw"),
        (19, "FallTime", "milliseconds"),
    )),
}

FEATURE_PROFILE_FIELDS: dict[int, tuple[str, tuple[tuple[int, str, str], ...]]] = {
    1: ("ComfortFeature", (
        (1, "AutoSetComfortRaw", "raw"),
    )),
    2: ("EprFeature", (
        (1, "EprEnablePatientAccessRaw", "raw"),
        (2, "EprEnableRaw", "raw"),
        (3, "EprTypeRaw", "raw"),
        (4, "EprPressure", "pressure"),
    )),
    3: ("AutoRampFeature", (
        (1, "RampEnableRaw", "raw"),
        (2, "RampTime", "minutes_scaled"),
        (3, "RampEnablePatientAccessRaw", "raw"),
    )),
    4: ("SmartStartStopFeature", (
        (1, "SmartStartRaw", "raw"),
        (2, "SmartStopRaw", "raw"),
    )),
    5: ("CircuitFeature", (
        (1, "MaskTypeRaw", "raw"),
        (2, "TubeTypeRaw", "raw"),
        (3, "AntiBacterialFilterRaw", "raw"),
    )),
    6: ("ClimateFeature", (
        (1, "ClimateControlRaw", "raw"),
        (2, "HumidifierSettingEnableRaw", "raw"),
        (3, "HumidifierLevel", "raw"),
        (4, "HeatedTubeSettingEnableRaw", "raw"),
        (5, "HeatedTubeTemperature", "celsius"),
        (6, "ExternalHumidifierRaw", "raw"),
    )),
    7: ("LanguageFeature", (
        (1, "LanguageRaw", "raw"),
        (2, "LanguageConfiguration", "raw"),
        (3, "LanguageSelectionRaw", "raw"),
    )),
    8: ("UserSolutionFeature", (
        (1, "SurveyPersonaliseRaw", "raw"),
    )),
    9: ("TemperatureFeature", (
        (1, "TemperatureUnitRaw", "raw"),
    )),
    10: ("CareCheckFeature", (
        (1, "CareCheckToggleRaw", "raw"),
        (2, "CareCheckInAvailableRaw", "raw"),
    )),
    11: ("TimeZoneFeature", (
        (1, "TimeZoneOffsetMin", "raw"),
    )),
    12: ("DeviceHealthFeature", (
        (1, "SoundcheckFeatureToggleRaw", "raw"),
    )),
    13: ("PatientViewFeature", (
        (1, "DisplayAHIRaw", "raw"),
        (2, "PatientViewRaw", "raw"),
    )),
    15: ("DisplayFeature", (
        (1, "TotalUsedHoursDisplayToggleRaw", "raw"),
        (2, "SplashScreenDisplaySelectionRaw", "raw"),
        (3, "CycleDisplayFormatRaw", "raw"),
        (4, "CareCheckInAvailableRaw", "raw"),
        (5, "MyAirScreensRaw", "raw"),
        (6, "ClinicalConfirmationRaw", "raw"),
        (7, "DynamicMessageToggleRaw", "raw"),
    )),
    16: ("ConfirmStopFeature", (
        (1, "ConfirmStopEnableRaw", "raw"),
    )),
    17: ("TherapyLEDFeature", (
        (1, "TherapyLEDAlwaysOnRaw", "raw"),
    )),
    18: ("RampDownFeature", (
        (1, "RampDownEnableRaw", "raw"),
        (2, "RampDownTime", "minutes_scaled"),
        (3, "RampDownEnablePatientAccessRaw", "raw"),
        (4, "MaxRampDownTime", "minutes_scaled"),
    )),
    19: ("HeightFeature", (
        (1, "HeightDisplayUnitRaw", "raw"),
    )),
    20: ("MaskSenseFeature", (
        (1, "MaskSenseToggleRaw", "raw"),
    )),
}

REMINDER_FIELDS: dict[int, str] = {
    1: "ReminderMask",
    2: "ReminderTubing",
    3: "ReminderFilter",
    4: "ReminderHumidifier",
}

ALARM_PROFILE_FIELDS: dict[int, tuple[str, tuple[tuple[int, str, str], ...]]] = {
    1: ("AlarmVolumeProfile", (
        (1, "AlarmVolumeLevelRaw", "raw"),
    )),
    2: ("HighLeakAlarmProfile", (
        (1, "HighLeakAlarmEnableRaw", "raw"),
    )),
    3: ("NonVentedMaskAlarmProfile", (
        (1, "NonVentedMaskAlarmEnableRaw", "raw"),
    )),
    4: ("LowMinuteVentAlarmProfile", (
        (1, "LowMinuteVentAlarmEnableRaw", "raw"),
        (2, "LowMinuteVentAlarmThreshold", "l_min_scaled"),
    )),
    5: ("ApneaAlarmProfile", (
        (1, "ApneaAlarmEnableRaw", "raw"),
        (2, "ApneaAlarmThreshold", "seconds"),
    )),
}


THERAPY_1MINUTE_FIELDS: dict[int, dict] = {
    # The payload carries per-field int16 series. Fields 1..7, 18, and 21 use
    # headerless second-difference/Rice compression. Fields 8/9 are raw packed
    # int16 when oximetry exists.
    1:  {"name": "Leak", "column": "leak_l_min", "unit": "L/min",
         "scale": 60.0 / 50.0, "rice_m": 4},
    2:  {"name": "InspiratoryPressure", "column": "insp_pressure_cmH2O",
         "unit": "cmH2O", "scale": 1.0 / 5.0, "rice_m": 4},
    3:  {"name": "ExpiratoryPressure", "column": "exp_pressure_cmH2O",
         "unit": "cmH2O", "scale": 1.0 / 5.0, "rice_m": 2},
    4:  {"name": "RespiratoryRate", "column": "resp_rate_bpm",
         "unit": "bpm", "scale": 1.0 / 4.0, "rice_m": 4},
    5:  {"name": "InspiratoryDuration", "column": "insp_duration_s",
         "unit": "s", "scale": 1.0 / 25.0, "rice_m": 4},
    6:  {"name": "MinuteVentilation", "column": "minute_vent_l_min",
         "unit": "L/min", "scale": 2.0 / 5.0, "rice_m": 8},
    7:  {"name": "IeRatio", "column": "ie_ratio_pct",
         "unit": "%", "scale": 4.0, "rice_m": 4},
    8:  {"name": "SpO2", "column": "spo2_pct",
         "unit": "%", "scale": 1.0, "rice_m": None},
    9:  {"name": "HeartRate", "column": "heart_rate_bpm",
         "unit": "bpm", "scale": 1.0, "rice_m": None},
    18: {"name": "AlveolarMinuteVentilation",
         "column": "alveolar_minute_vent_l_min", "unit": "L/min",
         "scale": 2.0 / 5.0, "rice_m": 8},
    21: {"name": "MeanInspiratoryTime",
         "column": "mean_inspiratory_time_s", "unit": "s",
         "scale": 1.0 / 10.0, "rice_m": 4},
}

METRIC_SPOOL_DEFS: dict[str, dict] = {
    "MachineMetrics": {
        "wire_field": 8,
        "fields": {
            1: ("OriginRaw", "raw"),
            2: ("Attributes", "attributes"),
            3: ("LastTherapyUseDateTime", "timestamp"),
            4: ("LastEraseDataDateTime", "timestamp"),
            5: ("TherapyRunMeter", "duration_ms"),
            6: ("MotorRunMeter", "duration_ms"),
            7: ("MotorRunSinceLastServiceMeter", "duration_ms"),
            8: ("MachineRunMeter", "duration_ms"),
            9: ("LastMachineServiceDateTime", "timestamp"),
        },
    },
    "CellularDataUsage": {
        "wire_field": 22,
        "fields": {
            1: ("OriginRaw", "raw"),
            2: ("Attributes", "attributes"),
            3: ("ApplicationTotalUpload", "bytes"),
            4: ("ApplicationTotalDownload", "bytes"),
        },
    },
}

MEMORY_METRIC_SETS: dict[int, tuple[str, tuple[tuple[str, str], ...]]] = {
    # Local NOR regions 0, 1, 2 are serialized as wire sets 2, 3, 1.
    1: ("UPGRADE", (
        ("FWC", "write_requests_ge_2kib"),
        ("FE2", "erase_64k_requests"),
        ("FM2", "max_erase_generation"),
    )),
    2: ("SETTINGS", (
        ("FW0", "write_requests_ge_2kib"),
        ("FE0", "erase_64k_requests"),
        ("FM0", "max_erase_generation"),
    )),
    3: ("DATALOG", (
        ("FW1", "write_requests_ge_2kib"),
        ("FE1", "erase_64k_requests"),
        ("FM1", "max_erase_generation"),
    )),
}

DIAG_10MIN_FIELDS: dict[int, dict] = {
    2: {"name": "CellularSignalStrength", "column": "signal_strength",
        "rice_m": 4, "scale": 1.0},
    3: {"name": "CellularSignalQuality2G", "column": "signal_quality_2g",
        "rice_m": 2, "scale": 1.0},
    4: {"name": "CellularSignalQuality3G", "column": "signal_quality_3g",
        "rice_m": 2, "scale": 1.0},
    5: {"name": "CellularSignalQualityLTE", "column": "signal_quality_lte",
        "rice_m": 2, "scale": 1.0},
}

ATMOSPHERIC_PRESSURE_FIELD = {
    "name": "AtmosphericPressure",
    "column": "atmospheric_pressure",
    "rice_m": 4,
    "scale": 2.0,
}


def _therapy_1minute_decode_values(blob: bytes, rice_m: int | None) -> list[int]:
    """Decode one TherapyOneMinutePeriodic int16 series."""
    if rice_m is None or len(blob) <= 4:
        return [
            int.from_bytes(blob[off:off + 2], "little", signed=True)
            for off in range(0, len(blob) - 1, 2)
        ]

    values = [
        int.from_bytes(blob[0:2], "little", signed=True),
        int.from_bytes(blob[2:4], "little", signed=True),
    ]
    bits = _rc03_bits(blob[4:])
    while True:
        try:
            encoded = _rc03_read_rice(bits, rice_m)
        except StopIteration:
            break
        delta2 = _zigzag_decode(encoded)
        values.append(2 * values[-1] - values[-2] + delta2)
    return values


def _therapy_1minute_signal(data: bytes, field: int) -> dict:
    spec = THERAPY_1MINUTE_FIELDS[field]
    status = None
    start_ms = None
    blob = None
    extras = []
    for sf, sw, sv in proto_decode(data):
        if sf == 1 and sw == 0:
            status = sv
        elif sf == 2 and sw == 0:
            start_ms = sv
        elif sf == 3 and sw == 2:
            blob = sv
        else:
            extras.append((sf, sw, sv))

    if blob is None:
        raise ValueError("missing sample blob")
    raw = _therapy_1minute_decode_values(blob, spec["rice_m"])
    scale = float(spec["scale"])
    values = [v * scale for v in raw]
    return {
        "field": field,
        "spec": spec,
        "status": status,
        "start_ms": start_ms,
        "blob": blob,
        "raw": raw,
        "values": values,
        "extras": extras,
    }


def _therapy_1minute_interval_ms(token: int | None) -> int:
    if token is None:
        return 60000
    if token < 1000:
        return token * 60000
    return token


def _therapy_1minute_records(data: bytes) -> list[bytes]:
    top = proto_decode(data)
    if top and all(field == 5 and wire == 2 for field, wire, _value in top):
        return [value for _field, _wire, value in top]
    return [data]


def _setting_profile_records(data: bytes) -> list[bytes]:
    top = proto_decode(data)
    if top and all(field == 3 and wire == 2 for field, wire, _value in top):
        return [value for _field, _wire, value in top]
    return [data]


def _config_profile_records(data: bytes) -> list[bytes]:
    top = proto_decode(data)
    if top and all(field == 23 and wire == 2 for field, wire, _value in top):
        return [value for _field, _wire, value in top]
    return [data]


def _wrapped_records(data: bytes, expected_field: int | None) -> list[bytes]:
    top = proto_decode(data)
    if not top:
        return []
    if expected_field is not None:
        if all(field == expected_field and wire == 2
               for field, wire, _value in top):
            return [value for _field, _wire, value in top]
        return [data]
    if all(wire == 2 for _field, wire, _value in top):
        return [value for _field, _wire, value in top]
    return [data]


def _delivery_status(value: int) -> str:
    if value == 1:
        return "Off"
    if value == 2:
        return "On"
    return str(value)


def _periodic_compressed_interval_ms(token: int | None) -> int:
    if token is None:
        return 600000
    if token < 1000:
        return token * 60000
    return token


def _periodic_compressed_signal(field: int, data: bytes) -> dict:
    spec = DIAG_10MIN_FIELDS.get(field, {
        "name": f"Signal{field}",
        "column": f"signal_{field}",
        "rice_m": 4,
        "scale": 1.0,
    })
    interval = None
    start_ms = None
    blob = None
    extras = []
    for sf, sw, sv in proto_decode(data):
        if sf == 1 and sw == 0:
            interval = sv
        elif sf == 2 and sw == 0:
            start_ms = sv
        elif sf == 3 and sw == 2:
            blob = sv
        else:
            extras.append((sf, sw, sv))
    if blob is None:
        raise ValueError("missing sample blob")
    raw = _therapy_1minute_decode_values(blob, spec["rice_m"])
    scale = float(spec["scale"])
    return {
        "field": field,
        "spec": spec,
        "interval_ms": _periodic_compressed_interval_ms(interval),
        "start_ms": start_ms,
        "blob": blob,
        "raw": raw,
        "values": [v * scale for v in raw],
        "extras": extras,
    }


def _atmospheric_pressure_record(data: bytes) -> dict:
    marker = None
    interval = None
    start_ms = None
    blob = None
    extras = []
    for field, wire, value in proto_decode(data):
        if field == 1 and wire == 0:
            marker = value
        elif field == 2 and wire == 0:
            interval = value
        elif field == 3 and wire == 0:
            start_ms = value
        elif field == 4 and wire == 2:
            blob = value
        else:
            extras.append((field, wire, value))
    if blob is None:
        raise ValueError("missing atmospheric-pressure sample blob")
    raw = _therapy_1minute_decode_values(
        blob, ATMOSPHERIC_PRESSURE_FIELD["rice_m"]
    )
    scale = float(ATMOSPHERIC_PRESSURE_FIELD["scale"])
    return {
        "marker": marker,
        "interval_ms": _periodic_compressed_interval_ms(interval),
        "start_ms": start_ms,
        "blob": blob,
        "raw": raw,
        "values": [value * scale for value in raw],
        "extras": extras,
    }


def _fmt_utc_ms(value: int) -> str:
    from datetime import datetime, timezone
    try:
        return datetime.fromtimestamp(value / 1000, timezone.utc).isoformat()
    except (OverflowError, OSError, TypeError, ValueError):
        return str(value)


def _rc03_parse(blob: bytes) -> dict:
    if len(blob) < 6:
        raise ValueError("too short for RC03")
    header_len = blob[0]
    if len(blob) < 1 + header_len:
        raise ValueError("truncated RC03 header")
    header = blob[1:1 + header_len]
    if not header.startswith(b"RC03"):
        raise ValueError("missing RC03 magic")
    body = blob[1 + header_len:]
    params = _rc03_decode_params(header[4:])
    seed = []
    for off in range(0, min(4, len(body)), 2):
        if off + 2 <= len(body):
            seed.append(int.from_bytes(body[off:off + 2], "little", signed=True))
    return {
        "header_len": header_len,
        "header": header,
        "params": params,
        "raw_params": header[4:],
        "body": body,
        "seed": seed,
    }


def _rc03_decode_params(data: bytes) -> list[int]:
    params = []
    i = 0
    while i < len(data):
        value, i = _proto_read_varint(data, i)
        params.append(_zigzag_decode(value))
    return params


def _zigzag_decode(value: int) -> int:
    return (value >> 1) ^ -(value & 1)


def _rc03_bits(data: bytes):
    for byte in data:
        for bit in range(7, -1, -1):
            yield (byte >> bit) & 1


def _rc03_read_rice(bits, m: int) -> int:
    if m <= 0 or m & (m - 1):
        raise ValueError(f"unsupported Rice modulus {m}")
    q = 0
    while True:
        bit = next(bits)
        if bit == 0:
            break
        q += 1
    rem = 0
    for _ in range(m.bit_length() - 1):
        rem = (rem << 1) | next(bits)
    return q * m + rem


def _rc03_scale(params: list[int]) -> float:
    if len(params) < 2:
        return 1.0
    return 2.0 * (10.0 ** params[1])


def rc03_decode_block(block: bytes, sample_count: int) -> dict:
    rc03 = _rc03_parse(block)
    params = rc03["params"]
    if len(params) < 5:
        raise ValueError("RC03 header has too few parameters")
    m = params[4]
    body = rc03["body"]
    values = []
    off = 0
    if sample_count >= 1:
        if len(body) < 2:
            raise ValueError("RC03 body missing first seed")
        values.append(int.from_bytes(body[0:2], "little", signed=True))
        off = 2
    if sample_count >= 2:
        if len(body) < 4:
            raise ValueError("RC03 body missing second seed")
        values.append(int.from_bytes(body[2:4], "little", signed=True))
        off = 4
    bits = _rc03_bits(body[off:])
    while len(values) < sample_count:
        try:
            encoded = _rc03_read_rice(bits, m)
        except StopIteration as exc:
            raise ValueError("RC03 bitstream ended early") from exc
        delta2 = _zigzag_decode(encoded)
        values.append(2 * values[-1] - values[-2] + delta2)
    scale = _rc03_scale(params)
    return {
        **rc03,
        "m": m,
        "scale": scale,
        "values": values,
        "physical": [v * scale for v in values],
    }


_SUMMARY_FIELDS = {
    1:  "f1_init_marker",
    2:  "PeriodStart",
    3:  "PeriodEnd",
    4:  "TimeZoneOffsetMin",
    5:  "DurationMin",
    6:  "SessionDurationEntries",
    7:  "AHI (Summary-ApneaHypopneaIndex)",
    8:  "ApneaIndex",
    9:  "HypopneaIndex",
    10: "ObstructiveApneaIndex",
    11: "CentralApneaIndex",
    12: "UnknownApneaIndex",
    13: "ReraIndex",
    14: "Leak",
    15: "InspiratoryPressure",
    16: "CSR",
    17: "SpO2Thresh",
    18: "SpontTriggerPercentage",
    19: "SpontCyclePercentage",
    20: "ExpiratoryPressure",
    21: "MeanMaskPressure",
    22: "TidalVolume",
    23: "MinuteVentilation",
    24: "TargetMinuteVentilation",
    25: "RespiratoryRate",
    26: "InspiratoryDuration",
    27: "IeRatio",
    28: "SpO2",
    29: "AmbientHumidity",
    30: "HumidifierTemperature",
    31: "HeatedTubeTemperature",
    32: "HumidifierPower",
    33: "HeatedTubePower",
    34: "HumidifierConnected (enum)",
    35: "TubeConnected (enum)",
    36: "BlowerPressure",
    37: "RespiratoryFlow",
    38: "BlowerFlow",
    39: "SessionCount",
    40: "RecordTimestamp",
    41: "HeartRate",
    42: "AlveolarMinuteVentilation",
    43: "SmdSmtTimestamp",
}

_SUMMARY_SCALAR_SCALES = {
    # Summary index fields are read from g2 DataItems in 0.1 units and the
    # protobuf formatter multiplies them by 10, so the wire value is centi-units
    # but only carries one decimal digit of source precision.
    7: 0.01,   # AHI
    8: 0.01,   # ApneaIndex
    9: 0.01,   # HypopneaIndex
    10: 0.01,  # ObstructiveApneaIndex
    11: 0.01,  # CentralApneaIndex
    12: 0.01,  # UnknownApneaIndex
    13: 0.01,  # ReraIndex
    18: 0.01,  # SpontTriggerPercentage
    19: 0.01,  # SpontCyclePercentage
}

_SUMMARY_SUBFIELDS = {
    14: {2: 50, 3: 70, 4: 95, 5: 100},
    15: {2: 50, 3: 95, 4: 100},
    20: {2: 50, 3: 95, 4: 100},
    21: {2: 50, 3: 95, 4: 100},
    22: {2: 50, 3: 95, 4: 100},
    23: {2: 50, 3: 95, 4: 100},
    24: {2: 50, 3: 95, 4: 100},
    25: {2: 50, 3: 95, 4: 100},
    26: {2: 50, 3: 95, 4: 100},
    27: {2: 50, 3: 95, 4: 100},
    28: {2: 50, 3: 95, 4: 100},
    29: {2: 50},
    30: {2: 50},
    31: {2: 50},
    32: {2: 50},
    33: {2: 50},
    36: {1: 5, 3: 95},
    37: {1: 5, 3: 95},
    38: {2: 50},
    41: {2: 50, 3: 95, 4: 100},
    42: {2: 50, 3: 95, 4: 100},
}

_SUMMARY_METRIC_SCALES = {
    14: (0.01, "L/s"),
    15: (0.01, "cmH2O"),
    20: (0.01, "cmH2O"),
    21: (0.01, "cmH2O"),
    22: (0.01, "L"),
    23: (0.01, "L/min"),
    24: (0.01, "L/min"),
    25: (0.01, "bpm"),
    26: (0.001, "s"),
    27: (0.01, "%"),
    28: (0.01, "%"),
    29: (0.01, "mg/L"),
    30: (0.01, "C"),
    31: (0.01, "C"),
    32: (0.01, "%"),
    33: (0.01, "%"),
    36: (0.01, "cmH2O"),
    37: (0.01, "L/s"),
    38: (0.01, "L/s"),
    41: (0.01, "bpm"),
    42: (0.01, "L/min"),
}


def _summary_metric_name(label: str) -> str:
    return label.split(" (", 1)[0]


def _decode_summary_session_entries(data: bytes) -> dict:
    entries = []
    unknown = []
    wrappers = proto_decode(data)
    for field, wire, value in wrappers:
        if field != 1 or wire != 2:
            unknown.append(_decoded_wire_field(field, wire, value))
            continue
        entry = {"unknownFields": []}
        fields = proto_decode(value)
        for sf, sw, sv in fields:
            if sf == 1 and sw == 0:
                entry.update(_timestamp_fields("startTime", int(sv)))
            elif sf == 2 and sw == 0:
                entry["durationMin"] = int(sv)
            else:
                entry["unknownFields"].append(
                    _decoded_wire_field(sf, sw, sv)
                )
        entries.append(entry)
    return {"entries": entries, "unknownFields": unknown}


def spool_walk_events(data: bytes, depth: int = 0) -> Iterator[bytes]:
    """Yield event records (field 1 innermost repeated) from spool payload."""
    try:
        fields = proto_decode(data)
    except (ValueError, IndexError):
        return
    for _field, wire, value in fields:
        if wire != 2:
            continue
        if _event_record(value) is not None:
            yield value
        elif depth < 2:
            yield from spool_walk_events(value, depth + 1)


def _decode_records_strict(data: bytes, decoder, depth: int = 0) -> list[dict]:
    record = decoder(data)
    if record is not None:
        return [record]
    records = []
    for field, wire, value in proto_decode(data):
        if wire != 2:
            raise SpoolDecodeError(
                f"unexpected envelope field f{field}/"
                f"{_PROTO_WIRE.get(wire, wire)}"
            )
        nested = decoder(bytes(value))
        if nested is not None:
            records.append(nested)
        elif depth < 2:
            records.extend(_decode_records_strict(
                bytes(value), decoder, depth + 1
            ))
        else:
            raise SpoolDecodeError(
                f"unrecognized record at envelope field f{field}"
            )
    return records


def _event_record(data: bytes) -> dict | None:
    try:
        fields = proto_decode(data)
    except (ValueError, IndexError):
        return None
    out = {"type": None, "start": None, "end": None, "duration": None,
           "extras": []}
    for field, wire, value in fields:
        if wire == 0 and field == 1:
            out["type"] = value
        elif wire == 0 and field == 2:
            out["start"] = value
        elif wire == 0 and field == 3:
            out["end"] = value
        elif wire == 0 and field == 4:
            out["duration"] = value
        else:
            out["extras"].append((field, wire, value))
    if out["type"] is None or out["start"] is None or out["end"] is None:
        return None
    return out


def _gui_event_record(data: bytes) -> dict | None:
    try:
        fields = proto_decode(data)
    except (ValueError, IndexError):
        return None
    out = {"type": None, "timestamp": None, "value": None,
           "value_wire": None, "extras": []}
    for field, wire, value in fields:
        if field == 1 and wire == 0:
            out["type"] = value
        elif field == 2 and wire == 0:
            out["timestamp"] = value
        elif field == 3:
            out["value"] = value
            out["value_wire"] = wire
        else:
            out["extras"].append((field, wire, value))
    if (out["type"] is None or out["timestamp"] is None
            or out["value"] is None):
        return None
    return out


def _event_name(spool_type: str, event_type: int) -> str:
    legend = SPOOL_LEGENDS.get(spool_type, {})
    return legend.get("event_types", {}).get(event_type, "")


def spool_payload_first_field(data: bytes) -> int | None:
    """Return the field number of the outer protobuf record, or None."""
    if not data:
        return None
    try:
        fields = proto_decode(data)
    except (ValueError, IndexError):
        return None
    if not fields:
        return None
    return fields[0][0]


def detect_spool_type(data: bytes) -> tuple[str | None, list[str]]:
    """Identify a captured payload by its outer protobuf field number.

    Returns (best_match, all_candidates). When the wire field is unique
    in the registry, best_match is the only candidate. When event spools
    share a wire field, their observed event codes are scored against the
    firmware maps. A tie retains registry order. The full candidate list
    is always returned.
    Returns (None, []) when the payload could not be parsed or no
    registered spool uses that wire field.
    """
    from as11_rpc_vars import SPOOL_FIELDS  # late import to avoid cycle
    field = spool_payload_first_field(data)
    if field is None:
        return None, []
    candidates = list(SPOOL_FIELDS.get(field, []))
    if not candidates:
        return None, []
    if len(candidates) == 1:
        return candidates[0], candidates

    observed = []
    for record_data in spool_walk_events(data):
        record = _event_record(record_data)
        if record is not None:
            observed.append(int(record["type"]))
    if observed:
        scores = []
        for index, candidate in enumerate(candidates):
            known = SPOOL_LEGENDS.get(candidate, {}).get("event_types", {})
            matched = sum(event_type in known for event_type in observed)
            scores.append((matched, -index, candidate))
        return max(scores)[2], candidates
    return candidates[0], candidates


def _decoded_wire_value(wire: int, value: object) -> object:
    if wire == 2:
        raw = bytes(value)
        return {
            "length": len(raw),
            "base64": base64.b64encode(raw).decode("ascii"),
        }
    return value


def _decoded_wire_field(field: int, wire: int, value: object) -> dict:
    return {
        "field": field,
        "wireType": _PROTO_WIRE.get(wire, str(wire)),
        "value": _decoded_wire_value(wire, value),
    }


def _decoded_wire_fields(fields) -> list[dict]:
    return [_decoded_wire_field(field, wire, value)
            for field, wire, value in fields]


def _timestamp_fields(prefix: str, value: int | None) -> dict:
    if value is None:
        return {}
    return {prefix + "Ms": value, prefix: _fmt_utc_ms(value)}


_PROFILE_VALUE_KINDS = {
    "pressure": (0.01, "cmH2O"),
    "seconds": (0.001, "s"),
    "centiseconds": (0.01, "s"),
    "milliseconds": (1.0, "ms"),
    "minutes_scaled": (0.01, "min"),
    "celsius": (0.01, "C"),
    "centimeters": (1.0, "cm"),
    "bpm_scaled": (0.01, "bpm"),
    "l_min_scaled": (0.01, "L/min"),
}


def _decoded_profile_value(raw: int, kind: str) -> dict:
    out = {"raw": raw}
    scale_unit = _PROFILE_VALUE_KINDS.get(kind)
    if scale_unit is not None:
        scale, unit = scale_unit
        out.update(value=raw * scale, unit=unit)
    return out


def _store_decoded_value(values: dict, name: str, value: object) -> None:
    previous = values.get(name)
    if previous is None:
        values[name] = value
    elif isinstance(previous, list):
        previous.append(value)
    else:
        values[name] = [previous, value]


def _decode_named_profile_message(
        data: bytes, definitions: tuple[tuple[int, str, str], ...]) -> dict:
    by_field = {field: (name, kind) for field, name, kind in definitions}
    values = {}
    unknown = []
    for field, wire, value in proto_decode(data):
        definition = by_field.get(field)
        if definition is None or wire != 0:
            unknown.append(_decoded_wire_field(field, wire, value))
            continue
        name, kind = definition
        _store_decoded_value(values, name,
                             _decoded_profile_value(int(value), kind))
    return {"values": values, "unknownFields": unknown}


def _decode_profile_attributes(data: bytes) -> dict:
    out = {"unknownFields": []}
    for field, wire, value in proto_decode(data):
        if field == 1 and wire == 0:
            out.update(_timestamp_fields("appliedDateTime", int(value)))
        elif field in (2, 3) and wire == 2:
            raw = bytes(value)
            try:
                out["source"] = raw.decode("utf-8")
            except UnicodeDecodeError:
                out["sourceBase64"] = base64.b64encode(raw).decode("ascii")
        elif field in (3, 4) and wire == 0:
            out["transaction"] = int(value)
        else:
            out["unknownFields"].append(
                _decoded_wire_field(field, wire, value)
            )
    return out


def _decode_active_profiles(data: bytes) -> dict:
    out = {"featureProfiles": [], "unknownFields": []}
    for field, wire, value in proto_decode(data):
        if field == 1 and wire == 0:
            raw = int(value)
            out["therapyProfile"] = {
                "raw": raw,
                "name": ACTIVE_THERAPY_PROFILE_NAMES.get(raw),
            }
        elif field == 2 and wire == 0:
            raw = int(value)
            out["featureProfiles"].append({
                "raw": raw,
                "name": ACTIVE_FEATURE_PROFILE_NAMES.get(raw),
            })
        else:
            out["unknownFields"].append(
                _decoded_wire_field(field, wire, value)
            )
    return out


def _decode_profile_group(data: bytes, definitions: dict[int, tuple]) -> dict:
    profiles = []
    unknown = []
    for field, wire, value in proto_decode(data):
        if wire != 2:
            unknown.append(_decoded_wire_field(field, wire, value))
            continue
        name, field_defs = definitions.get(
            field, (f"Profile{field}", ())
        )
        profile = {
            "field": field,
            "name": name,
            **_decode_named_profile_message(bytes(value), field_defs),
        }
        profiles.append(profile)
    return {"profiles": profiles, "unknownFields": unknown}


def _decode_reminders(data: bytes) -> dict:
    reminders = []
    unknown = []
    definitions = (
        (1, "EnableRaw", "raw"),
        (2, "StartDateTimeMs", "raw"),
        (3, "PeriodRaw", "raw"),
    )
    for field, wire, value in proto_decode(data):
        if wire != 2:
            unknown.append(_decoded_wire_field(field, wire, value))
            continue
        decoded = _decode_named_profile_message(bytes(value), definitions)
        start = decoded["values"].get("StartDateTimeMs")
        if isinstance(start, dict):
            start["value"] = _fmt_utc_ms(start["raw"])
        reminders.append({
            "field": field,
            "name": REMINDER_FIELDS.get(field, f"Reminder{field}"),
            **decoded,
        })
    return {"reminders": reminders, "unknownFields": unknown}


def _decode_feature_profiles(data: bytes) -> dict:
    profiles = []
    unknown = []
    for field, wire, value in proto_decode(data):
        if wire != 2:
            unknown.append(_decoded_wire_field(field, wire, value))
            continue
        if field == 14:
            profiles.append({
                "field": field,
                "name": "ReminderFeature",
                **_decode_reminders(bytes(value)),
            })
            continue
        name, field_defs = FEATURE_PROFILE_FIELDS.get(
            field, (f"FeatureProfile{field}", ())
        )
        profiles.append({
            "field": field,
            "name": name,
            **_decode_named_profile_message(bytes(value), field_defs),
        })
    return {"profiles": profiles, "unknownFields": unknown}


def _decode_setting_profiles(data: bytes) -> list[dict]:
    records = []
    for index, payload in enumerate(_setting_profile_records(data)):
        record = {"record": index, "unknownFields": []}
        for field, wire, value in proto_decode(payload):
            if field == 1 and wire == 2:
                record["attributes"] = _decode_profile_attributes(bytes(value))
            elif field == 2 and wire == 2:
                record["activeProfiles"] = _decode_active_profiles(bytes(value))
            elif field == 3 and wire == 2:
                record["therapyProfiles"] = _decode_profile_group(
                    bytes(value), THERAPY_PROFILE_FIELDS
                )
            elif field == 4 and wire == 2:
                record["featureProfiles"] = _decode_feature_profiles(
                    bytes(value)
                )
            elif field == 5 and wire == 2:
                record["alarmProfiles"] = _decode_profile_group(
                    bytes(value), ALARM_PROFILE_FIELDS
                )
            else:
                record["unknownFields"].append(
                    _decoded_wire_field(field, wire, value)
                )
        records.append(record)
    return records


def _decode_delivery_control(data: bytes) -> dict:
    values = []
    unknown = []
    for field, wire, value in proto_decode(data):
        if wire != 0:
            unknown.append(_decoded_wire_field(field, wire, value))
            continue
        raw = int(value)
        values.append({
            "field": field,
            "name": DATA_DELIVERY_FIELDS.get(field),
            "raw": raw,
            "value": _delivery_status(raw),
        })
    return {"values": values, "unknownFields": unknown}


def _decode_configuration_profiles(data: bytes) -> list[dict]:
    records = []
    for index, payload in enumerate(_config_profile_records(data)):
        record = {"record": index, "unknownFields": []}
        for field, wire, value in proto_decode(payload):
            if field == 1 and wire == 2:
                record["attributes"] = _decode_profile_attributes(bytes(value))
            elif field == 2 and wire == 2:
                record["dataDeliveryControlV2"] = _decode_delivery_control(
                    bytes(value)
                )
            else:
                record["unknownFields"].append(
                    _decoded_wire_field(field, wire, value)
                )
        records.append(record)
    return records


def _decode_metric_attributes(data: bytes) -> dict:
    out = {"unknownFields": []}
    for field, wire, value in proto_decode(data):
        if field == 1 and wire == 0:
            out.update(_timestamp_fields("reportDateTime", int(value)))
        else:
            out["unknownFields"].append(
                _decoded_wire_field(field, wire, value)
            )
    return out


def _decoded_metric_value(raw: int, kind: str) -> dict:
    if kind == "timestamp":
        return {"raw": raw, "value": _fmt_utc_ms(raw)}
    if kind == "duration_ms":
        return {"raw": raw, "value": raw, "unit": "ms"}
    if kind == "bytes":
        return {"raw": raw, "value": raw, "unit": "bytes"}
    return {"raw": raw}


def _decode_memory_metric_record(data: bytes) -> dict:
    record = {"metrics": [], "unknownFields": []}
    for field, wire, value in proto_decode(data):
        if field == 1 and wire == 2:
            record["attributes"] = _decode_metric_attributes(bytes(value))
            continue
        if field == 2 and wire == 2:
            fields = proto_decode(bytes(value))
            set_values = [int(sv) for sf, sw, sv in fields
                          if sf == 1 and sw == 0]
            set_id = set_values[0] if set_values else None
            metric_set = MEMORY_METRIC_SETS.get(set_id)
            metric = {
                "set": (set_values[0] if len(set_values) == 1
                        else set_values or None),
                "volume": metric_set[0] if metric_set else None,
                "values": {},
                "unknownFields": [],
            }
            definitions = {
                subfield: (source_tag, name)
                for subfield, (source_tag, name) in enumerate(
                    metric_set[1], start=2
                )
            } if metric_set is not None else {}
            for subfield, subwire, subvalue in fields:
                if subfield == 1 and subwire == 0:
                    continue
                definition = definitions.get(subfield)
                if definition is None or subwire != 0:
                    metric["unknownFields"].append(
                        _decoded_wire_field(subfield, subwire, subvalue)
                    )
                    continue
                source_tag, name = definition
                decoded_value = {
                    "sourceTag": source_tag,
                    "raw": int(subvalue),
                }
                _store_decoded_value(metric["values"], name, decoded_value)
            record["metrics"].append(metric)
            continue
        record["unknownFields"].append(
            _decoded_wire_field(field, wire, value)
        )
    return record


def _decode_metric_spool(spool_type: str, data: bytes) -> list[dict]:
    expected = (16 if spool_type == "MemoryMetrics"
                else METRIC_SPOOL_DEFS[spool_type]["wire_field"])
    records = []
    for index, payload in enumerate(_wrapped_records(data, expected)):
        if spool_type == "MemoryMetrics":
            record = _decode_memory_metric_record(payload)
            record["record"] = index
            records.append(record)
            continue
        definitions = METRIC_SPOOL_DEFS[spool_type]["fields"]
        record = {"record": index, "values": {}, "unknownFields": []}
        for field, wire, value in proto_decode(payload):
            definition = definitions.get(field)
            if definition is None:
                record["unknownFields"].append(
                    _decoded_wire_field(field, wire, value)
                )
                continue
            name, kind = definition
            if kind == "attributes" and wire == 2:
                record["attributes"] = _decode_metric_attributes(bytes(value))
            elif wire == 0:
                _store_decoded_value(
                    record["values"], name,
                    _decoded_metric_value(int(value), kind)
                )
            else:
                record["unknownFields"].append(
                    _decoded_wire_field(field, wire, value)
                )
        records.append(record)
    return records


def _decoded_signal(signal: dict, *, interval_ms: int | None = None) -> dict:
    spec = signal["spec"]
    out = {
        "field": signal["field"],
        "name": spec["name"],
        "column": spec["column"],
        "unit": spec.get("unit"),
        "scale": float(spec["scale"]),
        "sampleCount": len(signal["values"]),
        "rawValues": signal["raw"],
        "values": signal["values"],
        "compressedBytes": len(signal["blob"]),
        "unknownFields": _decoded_wire_fields(signal["extras"]),
    }
    if "status" in signal:
        out["status"] = signal["status"]
    out.update(_timestamp_fields("startTime", signal.get("start_ms")))
    actual_interval = (interval_ms if interval_ms is not None
                       else signal.get("interval_ms"))
    if actual_interval is not None:
        out["intervalMs"] = actual_interval
    return out


def _decode_therapy_one_minute(data: bytes) -> list[dict]:
    records = []
    for index, payload in enumerate(_therapy_1minute_records(data)):
        interval_token = None
        signals = []
        unknown = []
        for field, wire, value in proto_decode(payload):
            if field == 15 and wire == 0:
                interval_token = int(value)
            elif field in THERAPY_1MINUTE_FIELDS and wire == 2:
                try:
                    signals.append(_therapy_1minute_signal(bytes(value), field))
                except (ValueError, IndexError) as exc:
                    raise SpoolDecodeError(
                        f"TherapyOneMinutePeriodic record {index} field "
                        f"{field}: {exc}"
                    ) from exc
            else:
                unknown.append(_decoded_wire_field(field, wire, value))
        interval_ms = _therapy_1minute_interval_ms(interval_token)
        records.append({
            "record": index,
            "intervalToken": interval_token,
            "intervalMs": interval_ms,
            "signals": [_decoded_signal(signal, interval_ms=interval_ms)
                        for signal in signals],
            "unknownFields": unknown,
        })
    return records


def _decode_periodic_compressed(spool_type: str, data: bytes) -> list[dict]:
    expected = SPOOL_REGISTRY[spool_type]["wire_field"]
    records = []
    for index, payload in enumerate(_wrapped_records(data, expected)):
        if spool_type == "atmosphericPressure10min":
            try:
                decoded = _atmospheric_pressure_record(payload)
            except (ValueError, IndexError) as exc:
                raise SpoolDecodeError(
                    f"{spool_type} record {index}: {exc}"
                ) from exc
            signal = {
                "field": 4,
                "spec": ATMOSPHERIC_PRESSURE_FIELD,
                "interval_ms": decoded["interval_ms"],
                "start_ms": decoded["start_ms"],
                "blob": decoded["blob"],
                "raw": decoded["raw"],
                "values": decoded["values"],
                "extras": (),
            }
            records.append({
                "record": index,
                "marker": decoded["marker"],
                "signals": [_decoded_signal(signal)],
                "unknownFields": _decoded_wire_fields(decoded["extras"]),
            })
            continue

        origin = None
        signals = []
        unknown = []
        for field, wire, value in proto_decode(payload):
            if field == 1 and wire == 0:
                origin = int(value)
            elif wire == 2:
                try:
                    signals.append(_periodic_compressed_signal(
                        field, bytes(value)
                    ))
                except (ValueError, IndexError) as exc:
                    raise SpoolDecodeError(
                        f"{spool_type} record {index} field {field}: {exc}"
                    ) from exc
            else:
                unknown.append(_decoded_wire_field(field, wire, value))
        records.append({
            "record": index,
            "origin": origin,
            "signals": [_decoded_signal(signal) for signal in signals],
            "unknownFields": unknown,
        })
    return records


def _decode_rc03_spool(spool_type: str, data: bytes) -> list[dict]:
    expected_field = RC03_SPOOL_FIELDS[spool_type]
    records = []
    for index, (field, wire, value) in enumerate(proto_decode(data)):
        if field != expected_field or wire != 2:
            raise SpoolDecodeError(
                f"{spool_type} record {index}: expected "
                f"f{expected_field}/bytes, got "
                f"f{field}/{_PROTO_WIRE.get(wire, wire)}"
            )
        record_kind = None
        payload = None
        outer_unknown = []
        for subfield, subwire, subvalue in proto_decode(bytes(value)):
            if subfield == 1 and subwire == 0:
                record_kind = int(subvalue)
            elif subfield == 2 and subwire == 2:
                payload = bytes(subvalue)
            else:
                outer_unknown.append(
                    _decoded_wire_field(subfield, subwire, subvalue)
                )
        if payload is None:
            raise SpoolDecodeError(f"{spool_type} record {index}: missing payload")

        interval = None
        start = None
        end = None
        block = None
        payload_unknown = []
        for subfield, subwire, subvalue in proto_decode(payload):
            if subfield == 1 and subwire == 0:
                interval = int(subvalue)
            elif subfield == 2 and subwire == 0:
                start = int(subvalue)
            elif subfield == 3 and subwire == 0:
                end = int(subvalue)
            elif subfield == 4 and subwire == 2:
                block = bytes(subvalue)
            else:
                payload_unknown.append(
                    _decoded_wire_field(subfield, subwire, subvalue)
                )
        if interval is None or interval <= 0 or start is None or end is None:
            raise SpoolDecodeError(
                f"{spool_type} record {index}: incomplete sample timing"
            )
        if end < start:
            raise SpoolDecodeError(
                f"{spool_type} record {index}: end precedes start"
            )
        if block is None:
            raise SpoolDecodeError(
                f"{spool_type} record {index}: missing RC03 block"
            )
        sample_count = (end - start) // interval + 1
        try:
            decoded = rc03_decode_block(block, sample_count)
        except ValueError as exc:
            raise SpoolDecodeError(
                f"{spool_type} record {index}: {exc}"
            ) from exc
        record = {
            "record": index,
            "recordKind": record_kind,
            "intervalMs": interval,
            "sampleCount": sample_count,
            "scale": decoded["scale"],
            "rawValues": decoded["values"],
            "values": decoded["physical"],
            "compression": {
                "format": "RC03",
                "headerHex": decoded["header"].hex(),
                "headerLength": decoded["header_len"],
                "parameters": decoded["params"],
                "rawParametersHex": decoded["raw_params"].hex(),
                "riceM": decoded["m"],
                "seed": decoded["seed"],
                "bodyBytes": len(decoded["body"]),
            },
            "unknownFields": outer_unknown + payload_unknown,
        }
        record.update(_timestamp_fields("startTime", start))
        record.update(_timestamp_fields("endTime", end))
        records.append(record)
    return records


def _decode_soundcheck_vector(data: bytes) -> list[dict]:
    records = []
    for index, payload in enumerate(_wrapped_records(data, 15)):
        report_ms = None
        sample_rate = None
        vector = []
        peaks = []
        unknown = []
        for field, wire, value in proto_decode(payload):
            if field == 1 and wire == 0:
                report_ms = int(value)
            elif field == 2 and wire == 0:
                sample_rate = int(value)
            elif field == 3 and wire == 0:
                vector.append(int(value))
            elif field == 4 and wire == 2:
                for peak_field, peak_wire, peak_value in proto_decode(
                        bytes(value)):
                    if peak_field != 1 or peak_wire != 2:
                        unknown.append(_decoded_wire_field(
                            peak_field, peak_wire, peak_value
                        ))
                        continue
                    pair = {"unknownFields": []}
                    for pair_field, pair_wire, pair_value in proto_decode(
                            bytes(peak_value)):
                        if pair_field == 1 and pair_wire == 0:
                            _store_decoded_value(
                                pair, "a", int(pair_value)
                            )
                        elif pair_field == 2 and pair_wire == 0:
                            _store_decoded_value(
                                pair, "b", int(pair_value)
                            )
                        else:
                            pair["unknownFields"].append(
                                _decoded_wire_field(
                                    pair_field, pair_wire, pair_value
                                )
                            )
                    peaks.append(pair)
            else:
                unknown.append(_decoded_wire_field(field, wire, value))
        record = {
            "record": index,
            "sampleRateHz": sample_rate,
            "vector": vector,
            "peaks": peaks,
            "unknownFields": unknown,
        }
        record.update(_timestamp_fields("reportTime", report_ms))
        records.append(record)
    return records


_SUMMARY_TIMESTAMP_FIELDS = {2, 3, 40, 43}


def _summary_record_payloads(data: bytes) -> list[bytes]:
    fields = proto_decode(data)
    if fields and all(field == 2 and wire == 2
                      for field, wire, _value in fields):
        return [bytes(value) for _field, _wire, value in fields]
    while (len(fields) == 1 and fields[0][1] == 2
           and isinstance(fields[0][2], (bytes, bytearray))):
        data = bytes(fields[0][2])
        fields = proto_decode(data)
    return [data]


def _decode_summary_metric(field: int, data: bytes) -> dict:
    scale, unit = _SUMMARY_METRIC_SCALES[field]
    subfields = _SUMMARY_SUBFIELDS[field]
    percentiles = {}
    unknown = []
    for subfield, wire, value in proto_decode(data):
        percentile = subfields.get(subfield)
        if percentile is None or wire != 0:
            unknown.append(_decoded_wire_field(subfield, wire, value))
            continue
        raw = int(value)
        percentiles[str(percentile)] = {
            "raw": raw,
            "value": raw * scale,
        }
    return {
        "unit": unit,
        "percentiles": percentiles,
        "unknownFields": unknown,
    }


def _decode_summary_records(data: bytes) -> list[dict]:
    records = []
    for index, payload in enumerate(_summary_record_payloads(data)):
        record = {
            "record": index,
            "byteLength": len(payload),
            "values": {},
            "metrics": {},
            "unknownFields": [],
        }
        for field, wire, value in proto_decode(payload):
            name = _summary_metric_name(
                _SUMMARY_FIELDS.get(field, f"field_{field}")
            )
            if field == 6 and wire == 2:
                decoded_entries = _decode_summary_session_entries(bytes(value))
                record["sessionDurationEntries"] = decoded_entries["entries"]
                if decoded_entries["unknownFields"]:
                    record["sessionDurationUnknownFields"] = (
                        decoded_entries["unknownFields"]
                    )
                continue
            if field in _SUMMARY_SUBFIELDS and wire == 2:
                record["metrics"][name] = _decode_summary_metric(
                    field, bytes(value)
                )
                continue
            if wire == 0:
                raw = int(value)
                decoded = {"raw": raw}
                scale = _SUMMARY_SCALAR_SCALES.get(field)
                if scale is not None:
                    decoded["value"] = raw * scale
                if field in _SUMMARY_TIMESTAMP_FIELDS:
                    decoded["value"] = _fmt_utc_ms(raw)
                _store_decoded_value(record["values"], name, decoded)
                continue
            if wire in (1, 5):
                _store_decoded_value(
                    record["values"], name, {"raw": int(value)}
                )
                continue
            record["unknownFields"].append(
                _decoded_wire_field(field, wire, value)
            )
        records.append(record)
    return records


def _decode_event_extra(spool_type: str, event_type: int, field: int,
                        wire: int, value: object) -> dict:
    legend = SPOOL_LEGENDS.get(spool_type, {})
    if wire == 2 and field == legend.get("string_field"):
        name = "text"
    else:
        name = legend.get("extra_fields", {}).get((event_type, field))
    out = {
        "field": field,
        "wireType": _PROTO_WIRE.get(wire, str(wire)),
        "name": name,
        "raw": _decoded_wire_value(wire, value),
    }
    if (spool_type == "CellularActivityEvents" and event_type == 95
            and field == 14 and wire == 0):
        packed = int(value)
        error_id = (packed >> 12) & 0xFFF
        out["value"] = {
            "errorId": error_id,
            "errorName": legend.get("log_error_ids", {}).get(error_id),
            "detailId": packed & 0xFFF,
        }
    elif wire == 0:
        enum_name = legend.get("extra_enums", {}).get(
            (event_type, field), {}
        ).get(value)
        if enum_name is not None:
            out["value"] = enum_name
    elif wire == 2:
        raw = bytes(value)
        if raw and all(32 <= byte < 127 for byte in raw):
            out["value"] = raw.decode("ascii")
    return out


def _decode_gui_events(spool_type: str, data: bytes) -> list[dict]:
    records = []
    sources = _decode_records_strict(data, _gui_event_record)
    for index, source in enumerate(sources):
        event_type = int(source["type"])
        timestamp = int(source["timestamp"])
        record = {
            "record": index,
            "type": event_type,
            "name": _event_name(spool_type, event_type) or None,
            "value": _decoded_wire_value(
                source["value_wire"], source["value"]
            ),
            "valueWireType": _PROTO_WIRE.get(
                source["value_wire"], str(source["value_wire"])
            ),
            "extraFields": [
                _decode_event_extra(spool_type, event_type, *extra)
                for extra in source["extras"]
            ],
        }
        record.update(_timestamp_fields("timestamp", timestamp))
        records.append(record)
    return records


def _decode_survey_events(data: bytes) -> list[dict]:
    records = []
    for index, payload in enumerate(_wrapped_records(data, 14)):
        records.append({
            "record": index,
            "fields": _decoded_wire_fields(proto_decode(payload)),
        })
    return records


def _decode_events(spool_type: str, data: bytes,
                   app_version: str | None) -> list[dict]:
    record_kind = SPOOL_LEGENDS.get(spool_type, {}).get(
        "record_kind", "event"
    )
    if record_kind == "gui":
        return _decode_gui_events(spool_type, data)
    if record_kind == "survey":
        return _decode_survey_events(data)

    diagnostic = record_kind == "diagnostic_error"
    records = []
    decoded_records = _decode_records_strict(data, _event_record)
    for index, event in enumerate(decoded_records):
        event_type = int(event["type"])
        start = int(event["start"])
        end = int(event["end"])
        duration = event["duration"]
        if duration is None:
            duration = end - start
        record = {
            "record": index,
            "type": event_type,
            "name": _event_name(spool_type, event_type) or None,
            "durationMs": int(duration),
            "extraFields": [
                _decode_event_extra(spool_type, event_type, *extra)
                for extra in event["extras"]
            ],
        }
        record.update(_timestamp_fields("startTime", start))
        record.update(_timestamp_fields("endTime", end))
        if diagnostic and summarize_diagnostic_code is not None:
            record["interpretation"] = summarize_diagnostic_code(
                spool_type, event_type, app_version, details=True
            )
        records.append(record)
    return records


def _decode_diagnostic_blob(data: bytes) -> list[dict]:
    records = []
    for index, payload in enumerate(_wrapped_records(data, 11)):
        record = {
            "record": index,
            "byteLength": len(payload),
            "dataBase64": base64.b64encode(payload).decode("ascii"),
        }
        try:
            record["fields"] = _decoded_wire_fields(proto_decode(payload))
        except (ValueError, IndexError):
            pass
        records.append(record)
    return records


def _decode_audio(data: bytes) -> list[dict]:
    container = "RIFF/WAVE" if data.startswith(b"RIFF") else None
    return [{
        "record": 0,
        "container": container,
        "byteLength": len(data),
        "dataBase64": base64.b64encode(data).decode("ascii"),
    }] if data else []


def decode_spool(spool_type: str, data: bytes, *,
                 app_version: str | None = None) -> dict:
    """Decode a complete spool payload into a JSON-serializable model."""
    info = SPOOL_REGISTRY.get(spool_type)
    if info is None:
        raise SpoolDecodeError(f"unknown spool type: {spool_type}")
    family = info["family"]
    if not data:
        return {"spoolType": spool_type, "family": family, "records": []}
    try:
        if family == "summary":
            records = _decode_summary_records(data)
        elif family == "profile":
            records = _decode_setting_profiles(data)
        elif family == "config":
            records = _decode_configuration_profiles(data)
        elif family == "event":
            records = _decode_events(spool_type, data, app_version)
        elif family == "periodic":
            records = _decode_therapy_one_minute(data)
        elif family == "periodic_compressed":
            records = _decode_periodic_compressed(spool_type, data)
        elif family == "metric":
            records = _decode_metric_spool(spool_type, data)
        elif family == "rc03":
            records = _decode_rc03_spool(spool_type, data)
        elif family == "diag_vector":
            records = _decode_soundcheck_vector(data)
        elif family == "diag_blob":
            records = _decode_diagnostic_blob(data)
        elif family == "audio":
            records = _decode_audio(data)
        else:
            raise SpoolDecodeError(
                f"{spool_type}: unsupported spool family {family!r}"
            )
    except SpoolDecodeError:
        raise
    except (ValueError, IndexError) as exc:
        raise SpoolDecodeError(f"{spool_type}: {exc}") from exc
    return {
        "spoolType": spool_type,
        "family": family,
        "records": records,
    }


def _flatten_decoded(value: object, path: str = ""):
    if isinstance(value, dict):
        if not value:
            yield path, {}
            return
        for key, child in value.items():
            child_path = f"{path}.{key}" if path else str(key)
            yield from _flatten_decoded(child, child_path)
        return
    if isinstance(value, list):
        if not value:
            yield path, []
            return
        for index, child in enumerate(value):
            yield from _flatten_decoded(child, f"{path}[{index}]")
        return
    yield path, value


def _render_decoded_csv(decoded: dict, out) -> None:
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(("path", "value"))
    for path, value in _flatten_decoded(decoded):
        writer.writerow((path, json.dumps(value, ensure_ascii=True)))


def _table_cell(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, float):
        return f"{value:.10g}"
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=True, separators=(",", ":"))


def _table_time(value: object) -> str:
    text = _table_cell(value)
    if text.endswith("+00:00"):
        text = text[:-6] + "Z"
    if text.endswith("Z") and "." in text:
        text = text[:-1].rstrip("0").rstrip(".") + "Z"
    return text.replace("T", " ")


_ISO_DATETIME_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?"
    r"(?:Z|[+-]\d{2}:\d{2})?$"
)


def _is_iso_datetime(value: object) -> bool:
    return isinstance(value, str) and _ISO_DATETIME_RE.fullmatch(value) is not None


def _write_table(headers, rows, out, *, indent: str = "",
                 max_width: int | None = 40) -> None:
    rendered = [[_table_cell(cell) for cell in row] for row in rows]
    if not rendered:
        return
    widths = []
    for index, header in enumerate(headers):
        widest = max([len(str(header))] + [len(row[index]) for row in rendered])
        widths.append(widest if max_width is None else min(widest, max_width))

    def wrapped_row(row):
        columns = [textwrap.wrap(cell, width=max(width, 1),
                                 break_long_words=True,
                                 break_on_hyphens=False) or [""]
                   for cell, width in zip(row, widths)]
        for line in range(max(len(column) for column in columns)):
            yield [column[line] if line < len(column) else ""
                   for column in columns]

    header_row = [str(header) for header in headers]
    print(indent + "  ".join(
        cell.ljust(width) for cell, width in zip(header_row, widths)
    ).rstrip(), file=out)
    print(indent + "  ".join("-" * width for width in widths).rstrip(),
          file=out)
    for row in rendered:
        for line in wrapped_row(row):
            print(indent + "  ".join(
                cell.ljust(width) for cell, width in zip(line, widths)
            ).rstrip(), file=out)


def _decoded_value_cell(value: object) -> str:
    if not isinstance(value, dict):
        return _table_cell(value)
    if "value" in value or "raw" in value:
        display = value.get("value", value.get("name", value.get("raw")))
        if _is_iso_datetime(display):
            display = _table_time(display)
        text = _table_cell(display)
        if value.get("unit"):
            text += f" {value['unit']}"
        raw = value.get("raw")
        if raw is not None and display != raw:
            text += f" (raw {raw})"
        return text
    return _table_cell(value)


def _decoded_value_parts(value: object) -> tuple[object, str, object]:
    if not isinstance(value, dict):
        return value, "", ""
    display = value.get("value", value.get("name", value.get("raw", "")))
    if _is_iso_datetime(display):
        display = _table_time(display)
    raw = value.get("raw", "")
    return display, value.get("unit", ""), "" if display == raw else raw


def _is_table_scalar(value: object) -> bool:
    if not isinstance(value, (dict, list)):
        return True
    return (isinstance(value, dict)
            and ("value" in value or "raw" in value)
            and not any(isinstance(item, (dict, list))
                        for item in value.values()))


def _render_table_tree(title: str, value: object, out,
                       *, indent: str = "") -> None:
    if value in (None, [], {}):
        return
    print(f"{indent}{title}:", file=out)
    child_indent = indent + "  "
    if isinstance(value, dict):
        scalar_rows = [(key, _decoded_value_cell(item))
                       for key, item in value.items()
                       if _is_table_scalar(item)]
        _write_table(("Field", "Value"), scalar_rows, out,
                     indent=child_indent)
        for key, item in value.items():
            if not _is_table_scalar(item):
                _render_table_tree(str(key), item, out, indent=child_indent)
        return
    if isinstance(value, list):
        if all(_is_table_scalar(item) for item in value):
            _write_table(("#", "Value"),
                         ((index, _decoded_value_cell(item))
                          for index, item in enumerate(value)),
                         out, indent=child_indent)
        else:
            for index, item in enumerate(value):
                label = (item.get("name") if isinstance(item, dict)
                         else None) or str(index)
                _render_table_tree(str(label), item, out,
                                   indent=child_indent)
        return
    print(child_indent + _table_cell(value), file=out)


def _compact_event_extra(extra: dict) -> str:
    value = extra.get("value")
    if isinstance(value, dict) and "errorId" in value:
        error_id = value["errorId"]
        error_name = value.get("errorName")
        if error_name:
            error_id = f"{error_id}({error_name})"
        parts = [f"error_id={error_id}"]
        if value.get("detailId") is not None:
            parts.append(f"detail_id={value['detailId']}")
        return ",".join(parts)

    name = extra.get("name")
    if not name:
        name = f"f{extra.get('field')}/{extra.get('wireType')}"
    raw = extra.get("raw")
    if isinstance(value, str):
        if name == "text":
            display = repr(value)
        elif isinstance(raw, int) and value != raw:
            display = f"{raw}({value})"
        else:
            display = value
    elif value is not None:
        display = _table_cell(value)
    else:
        display = _table_cell(raw)
    return f"{name}={display}"


def _event_details_cell(record: dict) -> str:
    return ",".join(
        _compact_event_extra(extra)
        for extra in record.get("extraFields", [])
    )


def _unknown_event_extras(record: dict) -> list[dict]:
    unknown = []
    for extra in record.get("extraFields", []):
        value = extra.get("value")
        packed_log_error = isinstance(value, dict) and "errorId" in value
        if not extra.get("name") and not packed_log_error:
            unknown.append(extra)
    return unknown


def _render_event_table(decoded: dict, out, *, details: bool = False) -> None:
    records = decoded["records"]
    _write_table(
        ("#", "Event", "Type", "Start", "End", "Duration", "Details"),
        ((record.get("record"), record.get("name") or "unknown",
          record.get("type"), _table_time(record.get("startTime")),
          _table_time(record.get("endTime")), record.get("durationMs"),
          _event_details_cell(record))
         for record in records),
        out,
        max_width=None,
    )
    if not details:
        return
    for record in records:
        expanded = {
            key: record[key]
            for key in ("interpretation", "unknownFields")
            if record.get(key)
        }
        unknown_extras = _unknown_event_extras(record)
        if unknown_extras:
            expanded["unknownExtraFields"] = unknown_extras
        if expanded:
            _render_table_tree(f"Event {record.get('record')} details",
                               expanded, out)


def _render_summary_table(decoded: dict, out) -> None:
    records = decoded["records"]
    _write_table(
        ("#", "Period start", "Period end", "Minutes", "TZ", "Sessions"),
        ((record.get("record"),
          _table_time(_decoded_known_value(record, "PeriodStart")),
          _table_time(_decoded_known_value(record, "PeriodEnd")),
          _decoded_known_value(record, "DurationMin"),
          _decoded_known_value(record, "TimeZoneOffsetMin"),
          (_decoded_known_value(record, "SessionCount")
           if _decoded_known_value(record, "SessionCount") is not None
           else len(record.get("sessionDurationEntries", []))))
         for record in records),
        out,
    )
    for record in records:
        number = record.get("record")
        sessions = record.get("sessionDurationEntries", [])
        if sessions:
            print(f"\nRecord {number} sessions:", file=out)
            _write_table(
                ("#", "Start", "Minutes"),
                ((index, _table_time(session.get("startTime")),
                  session.get("durationMin"))
                 for index, session in enumerate(sessions)),
                out, indent="  ",
            )

        values = record.get("values", {})
        if values:
            print(f"\nRecord {number} values:", file=out)
            _write_table(
                ("Name", "Value", "Unit", "Raw"),
                ((name, *_decoded_value_parts(value))
                 for name, value in values.items()),
                out, indent="  ",
            )

        metrics = record.get("metrics", {})
        if metrics:
            percentile_names = ("5", "50", "70", "95", "100")
            print(f"\nRecord {number} metrics:", file=out)
            _write_table(
                ("Metric", "Unit", "p5", "p50", "p70", "p95", "p100"),
                ((name, metric.get("unit", ""),
                  *(_decoded_value_parts(
                      metric.get("percentiles", {}).get(percentile, {})
                    )[0] for percentile in percentile_names))
                 for name, metric in metrics.items()),
                out, indent="  ",
            )

        details = {
            key: record[key]
            for key in ("sessionDurationUnknownFields", "unknownFields")
            if record.get(key)
        }
        if details:
            _render_table_tree(f"Record {number} additional fields",
                               details, out)


def _sample_rows(sample: dict):
    raw_values = sample.get("rawValues", [])
    values = sample.get("values", [])
    count = max(len(raw_values), len(values))
    start = sample.get("startTimeMs")
    interval = sample.get("intervalMs")
    for index in range(count):
        timestamp = ""
        if start is not None and interval is not None:
            timestamp = _table_time(_fmt_utc_ms(start + index * interval))
        yield (
            index,
            timestamp,
            raw_values[index] if index < len(raw_values) else "",
            values[index] if index < len(values) else "",
        )


def _render_signal_table(decoded: dict, out) -> None:
    samples = []
    metadata = []
    for record in decoded["records"]:
        signals = record.get("signals")
        if signals is None and "values" in record:
            signals = [record]
        for signal_index, signal in enumerate(signals or []):
            name = signal.get("name") or decoded["spoolType"]
            metadata.append((
                record.get("record"), name,
                _table_time(signal.get("startTime")),
                _table_time(signal.get("endTime")),
                signal.get("intervalMs", record.get("intervalMs")),
                signal.get("sampleCount", len(signal.get("values", []))),
                min(signal["values"]) if signal.get("values") else "",
                max(signal["values"]) if signal.get("values") else "",
                signal.get("unit", ""),
            ))
            samples.append((record, signal_index, name, signal))
    _write_table(
        ("Record", "Signal", "Start", "End", "Interval", "Samples",
         "Min", "Max", "Unit"),
        metadata, out,
    )
    for record, signal_index, name, signal in samples:
        print(f"\nRecord {record.get('record')} {name} samples:", file=out)
        _write_table(("#", "Time", "Raw", "Value"),
                     _sample_rows(signal), out, indent="  ")

        details = {
            key: value for key, value in signal.items()
            if key not in {
                "name", "startTime", "startTimeMs", "endTime", "endTimeMs",
                "intervalMs", "sampleCount", "rawValues", "values", "unit",
            } and value not in (None, [], {})
        }
        if details:
            _render_table_tree("Details", details, out, indent="  ")

    for record in decoded["records"]:
        if "signals" not in record:
            continue
        details = {
            key: value for key, value in record.items()
            if key not in {"record", "signals"} and value not in (None, [], {})
        }
        if details:
            _render_table_tree(
                f"Record {record.get('record')} metadata", details, out
            )


def _render_decoded_table(decoded: dict, out, *, details: bool = False) -> None:
    print(f"{decoded['spoolType']} ({decoded['family']}), "
          f"{len(decoded['records'])} record(s)", file=out)
    if not decoded["records"]:
        return
    print(file=out)
    family = decoded["family"]
    if family == "event":
        _render_event_table(decoded, out, details=details)
    elif family == "summary":
        _render_summary_table(decoded, out)
    elif family in {"periodic", "periodic_compressed", "rc03"}:
        _render_signal_table(decoded, out)
    else:
        _render_table_tree("Records", decoded["records"], out)


def _decoded_known_value(record: dict, name: str):
    value = record.get("values", {}).get(name)
    if isinstance(value, dict):
        return value.get("value", value.get("raw"))
    return value


def _render_decoded_summary(decoded: dict, out) -> None:
    spool_type = decoded["spoolType"]
    family = decoded["family"]
    records = decoded["records"]
    print(f"{spool_type}: family={family} records={len(records)}", file=out)

    if family == "event":
        counts = Counter((record.get("name") or f"type={record.get('type')}")
                         for record in records)
        for name, count in sorted(counts.items()):
            print(f"  {name}: {count}", file=out)
        return

    if family == "summary":
        for record in records:
            start = _decoded_known_value(record, "PeriodStart")
            end = _decoded_known_value(record, "PeriodEnd")
            duration = _decoded_known_value(record, "DurationMin")
            sessions = _decoded_known_value(record, "SessionCount")
            if sessions is None:
                sessions = len(record.get("sessionDurationEntries", []))
            print(f"  record {record['record']}: {start} -> {end} "
                  f"duration_min={duration} sessions={sessions}", file=out)
        return

    found_samples = False
    for record in records:
        signals = record.get("signals", [])
        for signal in signals:
            values = signal.get("values", [])
            start = signal.get("startTime", "n/a")
            interval = signal.get("intervalMs", record.get("intervalMs"))
            bounds = ""
            if values:
                bounds = f" min={min(values):.8g} max={max(values):.8g}"
            print(f"  record {record['record']} {signal['name']}: "
                  f"start={start} interval_ms={interval} "
                  f"samples={len(values)}{bounds}", file=out)
            found_samples = True
        if "values" in record and "sampleCount" in record:
            values = record["values"]
            bounds = ""
            if values:
                bounds = f" min={min(values):.8g} max={max(values):.8g}"
            print(f"  record {record['record']}: "
                  f"start={record.get('startTime', 'n/a')} "
                  f"interval_ms={record.get('intervalMs')} "
                  f"samples={len(values)}{bounds}", file=out)
            found_samples = True
    if found_samples:
        return

    for record in records:
        keys = [key for key in record
                if key not in {"record", "unknownFields"}]
        print(f"  record {record.get('record')}: {', '.join(keys)}", file=out)


def render_spool(decoded: dict, output_format: str, out=None, *,
                 details: bool = False) -> None:
    """Render one decoded spool model."""
    if out is None:
        out = sys.stdout
    if output_format == "json":
        json.dump(decoded, out, indent=2, ensure_ascii=True)
        print(file=out)
    elif output_format == "csv":
        _render_decoded_csv(decoded, out)
    elif output_format == "table":
        _render_decoded_table(decoded, out, details=details)
    elif output_format == "summary":
        _render_decoded_summary(decoded, out)
    else:
        raise ValueError(f"unknown spool output format: {output_format}")


__all__ = [
    "SPOOL_FRAGMENT_SIZE", "SPOOL_FRAGMENT_SIZE_LIMIT",
    "SPOOL_OUTPUT_FORMATS", "SPOOL_OUTPUT_DEFAULT",
    "SPOOL_LEGENDS",
    "SpoolError", "SpoolDecodeError",
    "spool_one_round",
    "proto_decode", "spool_payload_first_field", "detect_spool_type",
    "SELECTOR_BY_SPOOL", "spool_walk_events",
    "decode_spool", "render_spool",
]

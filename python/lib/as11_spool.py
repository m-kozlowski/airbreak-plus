"""Spool (device-side data archive) support. Transport-agnostic.

Protocol dance plus protobuf payload decoders. 
"""

from __future__ import annotations

import base64
from collections import Counter
import hashlib
import logging
import sys
from typing import Iterator


log = logging.getLogger("as11.spool")


class SpoolError(Exception):
    """StartSpool failed before any fragment notifications could arrive.

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


# Single-round spool cycle. Transport-agnostic.

def spool_one_round(transport, spool_address: dict, max_size: int,
                    *, fragment_timeout: float = 30.0,
                    fragment_max: int = 2808,
                    verbose: bool = True,
                    ) -> tuple[bytes, str, dict | None, int]:
    """Run one StartSpool -> PullSpoolFragments cycle against `transport`.

    Returns (data_bytes, status, next_spool_address_or_None, frag_count).
    Verifies per-round SHA256 against spoolHash reported by the device.

    Raises `SpoolError` when `StartSpool` returns a JSON-RPC error or a
    zero spoolId. Callers that want best-effort probing should catch it.

    `transport` must implement the as11_rpc.Transport protocol with a
    working `listen_for_notifications`.
    """
    fragments: list[tuple[int, bytes]] = []
    state = {"status": "", "hash": "", "next": None, "done": False}

    def on_notify(msg: dict):
        if msg.get("method") != "SpoolFragment":
            return None
        params = msg.get("params", {})
        seq = params.get("seq", -1)
        data_b64 = params.get("data", "")
        status = params.get("status", "")
        if data_b64:
            try:
                fragments.append((seq, base64.b64decode(data_b64)))
            except Exception as exc:
                log.warning("SpoolFragment seq=%d base64 decode failed: %s",
                            seq, exc)
        if verbose:
            print(f"  fragment seq={seq} len={len(data_b64)} status={status}",
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

        transport.rpc("PullSpoolFragments", {
            "spoolId": spool_id,
            "maxFragmentSize": fragment_max,
            "maxNotifications": 0,
        }, timeout=5.0)

        transport.listen_for_notifications(duration=fragment_timeout)
    finally:
        transport.set_notification_handler(None)

    fragments.sort(key=lambda x: x[0])
    data = b"".join(f[1] for f in fragments)

    expected = state["hash"]
    if expected:
        actual = hashlib.sha256(data).hexdigest().upper()
        ok = "OK" if actual == expected.upper() else "MISMATCH"
        if verbose:
            print(f"  SHA256: {ok} ({len(data)} bytes, {len(fragments)} fragments)",
                  file=sys.stderr)
    elif not state["done"] and verbose:
        print(f"  warning: no terminal fragment received within "
              f"{fragment_timeout:.0f}s; got {len(fragments)} fragments "
              f"({len(data)} bytes)", file=sys.stderr)

    return data, state["status"], state["next"], len(fragments)



_PROTO_WIRE = {0: "varint", 1: "64-bit", 2: "bytes", 5: "32-bit"}


def _proto_read_varint(data, i):
    v = 0; shift = 0
    while True:
        b = data[i]; i += 1
        v |= (b & 0x7F) << shift
        if (b & 0x80) == 0:
            return v, i
        shift += 7


def proto_decode(data: bytes) -> list[tuple[int, int, object]]:
    """Walk protobuf wire format. Returns [(field, wire, value), ...]."""
    out = []
    i = 0
    while i < len(data):
        key, i = _proto_read_varint(data, i)
        field = key >> 3
        wire = key & 7
        if wire == 0:
            v, i = _proto_read_varint(data, i); out.append((field, wire, v))
        elif wire == 1:
            out.append((field, wire, int.from_bytes(data[i:i + 8], "little"))); i += 8
        elif wire == 2:
            ln, i = _proto_read_varint(data, i)
            out.append((field, wire, bytes(data[i:i + ln]))); i += ln
        elif wire == 5:
            out.append((field, wire, int.from_bytes(data[i:i + 4], "little"))); i += 4
        else:
            raise ValueError(f"unsupported wire type {wire} at offset {i}")
    return out


def proto_pretty(data: bytes, indent: int = 0, out=None) -> None:
    """Pretty-print protobuf blob with nested-message heuristic."""
    from datetime import datetime, timezone
    if out is None:
        out = sys.stdout
    pad = "  " * indent
    for field, wire, value in proto_decode(data):
        if wire == 2:
            try:
                sub = proto_decode(value)
                if sub and all(0 < f < 2**29 for f, _, _ in sub):
                    print(f"{pad}{field} (msg, {len(value)}B):", file=out)
                    proto_pretty(value, indent + 1, out)
                    continue
            except (ValueError, IndexError):
                pass
            if value and all(32 <= b < 127 for b in value):
                print(f"{pad}{field} (str): {value.decode()!r}", file=out)
            else:
                h = value.hex()
                if len(h) > 80:
                    h = h[:80] + "..."
                print(f"{pad}{field} (bytes {len(value)}B): {h}", file=out)
        elif wire == 0:
            note = ""
            if 10**12 < value < 2 * 10**12:
                try:
                    note = f" [~{datetime.fromtimestamp(value / 1000, timezone.utc).isoformat()}]"
                except (OverflowError, OSError):
                    pass
            elif 10**9 < value < 2 * 10**9:
                try:
                    note = f" [~{datetime.fromtimestamp(value, timezone.utc).isoformat()}]"
                except (OverflowError, OSError):
                    pass
            print(f"{pad}{field} (varint): {value}{note}", file=out)
        else:
            print(f"{pad}{field} ({_PROTO_WIRE.get(wire, wire)}): {value}", file=out)


def spool_payload_shape(data: bytes) -> str:
    """Compact protobuf field summary for probe output."""
    if not data:
        return "empty"
    try:
        fields = proto_decode(data)
    except (ValueError, IndexError) as exc:
        return f"non-protobuf: {exc}"
    counts = Counter((field, wire) for field, wire, _value in fields)
    parts = []
    for (field, wire), count in sorted(counts.items())[:8]:
        name = _PROTO_WIRE.get(wire, str(wire))
        parts.append(f"f{field}/{name}x{count}")
    if len(counts) > 8:
        parts.append("...")
    if b"RC03" in data:
        parts.append("RC03")
    return ", ".join(parts)



SPOOL_LEGENDS: dict[str, dict] = {
    "UsageEvents-TherapyStatusEvents": {
        "event_types": {
            1: "NoUsage", 2: "MaskOff", 3: "MaskOn", 4: "PowerOff",
            5: "MaskFitStart", 6: "MaskFitStop",
            7: "TherapyStart", 8: "TherapyStop",
            9: "LearnTargetsStart", 10: "LearnTargetsStop",
        },
    },
    "TherapyEvents-RespiratoryEvents": {
        "event_types": {
            2: "Hypopnea", 3: "CentralApnea", 4: "ObstructiveApnea",
            5: "Apnea", 6: "Arousal",
        },
    },
    "CellularActivityEvents": {
        "event_types": {
            2: "CellularComponentsStarting",
            3: "CellularComponentsStopping",
            5: "NetworkGeneration",
            6: "TcpConnectStarted",
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
            91: "PreInitializationStarted",
            92: "PreInitializationCompleted",
            95: "ApplicationLogRecord",
        },
        "extra_fields": {
            (5, 5): "generation",
            (13, 6): "http_status",
            (24, 16): "result_code",
            (25, 16): "result_code",
            (60, 8): "mnc",
            (61, 9): "mcc",
            (87, 12): "cell_id",
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
from as11_rpc_vars import SPOOL_REGISTRY  # noqa: E402

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
        (2, "SoundcheckRunFrequencyRaw", "raw"),
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


THERAPY_1MINUTE_FIELDS: dict[int, dict] = {
    # The payload carries per-field int16 series. Fields 1..7 are compressed
    # with the same second-difference/Rice scheme used by RC03, but without an
    # explicit header. Fields 8/9 are raw packed int16 when oximetry exists.
    1:  {"name": "Leak", "column": "leak_l_min", "unit": "L/min",
         "scale": 60.0 / 50.0, "rice_m": 4},
    2:  {"name": "InspiratoryPressure", "column": "insp_pressure_cmH2O",
         "unit": "cmH2O", "scale": 1.0 / 5.0, "rice_m": 4},
    3:  {"name": "ExpiratoryPressure", "column": "exp_pressure_cmH2O",
         "unit": "cmH2O", "scale": 1.0 / 5.0, "rice_m": 2},
    4:  {"name": "MinuteVentilation", "column": "minute_vent_l_min",
         "unit": "L/min", "scale": 1.0 / 8.0, "rice_m": 8},
    5:  {"name": "InspiratoryDuration", "column": "insp_duration_s",
         "unit": "s", "scale": 1.0 / 50.0, "rice_m": 4},
    6:  {"name": "RespiratoryRate", "column": "resp_rate_bpm",
         "unit": "bpm", "scale": 1.0, "rice_m": 4},
    7:  {"name": "IeRatio", "column": "ie_ratio_pct",
         "unit": "%", "scale": 4.0, "rice_m": 4},
    8:  {"name": "SpO2", "column": "spo2_pct",
         "unit": "%", "scale": 1.0, "rice_m": None},
    9:  {"name": "HeartRate", "column": "heart_rate_bpm",
         "unit": "bpm", "scale": 1.0, "rice_m": None},
    21: {"name": "MIS", "column": "mis",
         "unit": "raw/50", "scale": 1.0 / 50.0, "rice_m": 4},
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

MEMORY_METRIC_FIELDS: dict[int, str] = {
    1: "MemoryPoolRaw",
    2: "MetricA",
    3: "MetricB",
    4: "MetricC",
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


def _fmt_number(value) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:.8g}"
    return str(value)


def _fmt_duration_ms(value: int) -> str:
    if value % 1000 == 0:
        return f"{value // 1000}s"
    return f"{value}ms"


def _format_profile_value(value: int, kind: str) -> str:
    if kind == "pressure":
        return f"{value / 100.0:.8g} cmH2O"
    if kind == "seconds":
        return f"{value / 1000.0:.8g} s"
    if kind == "milliseconds":
        return f"{value} ms"
    if kind == "minutes_scaled":
        return f"{value / 100.0:.8g} min"
    if kind == "celsius":
        return f"{value / 100.0:.8g} C"
    if kind == "bpm_scaled":
        return f"{value / 100.0:.8g} bpm"
    return str(value)


def _format_metric_value(value: int, kind: str) -> str:
    if kind == "timestamp":
        return _fmt_utc_ms(value)
    if kind == "duration_ms":
        return _fmt_duration_ms(value)
    if kind == "bytes":
        return f"{value} B"
    return str(value)


def _decode_varint_message(data: bytes) -> dict[int, list[int]]:
    out: dict[int, list[int]] = {}
    for field, wire, value in proto_decode(data):
        if wire == 0:
            out.setdefault(field, []).append(value)
    return out


def _format_named_message(data: bytes,
                          defs: tuple[tuple[int, str, str], ...],
                          *, details: bool = False) -> str:
    values = _decode_varint_message(data)
    parts = []
    used = set()
    for field, name, kind in defs:
        if field not in values:
            continue
        used.add(field)
        if len(values[field]) == 1:
            value = _format_profile_value(values[field][0], kind)
        else:
            value = "[" + ",".join(
                _format_profile_value(item, kind) for item in values[field]
            ) + "]"
        parts.append(f"{name}={value}")
    if details:
        for field in sorted(set(values) - used):
            raw = ",".join(str(item) for item in values[field])
            parts.append(f"f{field}={raw}")
    return " ".join(parts)


def _profile_attr(data: bytes) -> tuple[int | None, str, int | None, list[str]]:
    applied_ms = None
    source = ""
    transaction = None
    extras = []
    for field, wire, value in proto_decode(data):
        if field == 1 and wire == 0:
            applied_ms = value
        elif field in (2, 3) and wire == 2:
            if value:
                try:
                    source = value.decode("utf-8")
                except UnicodeDecodeError:
                    source = value.hex()
        elif field in (3, 4) and wire == 0:
            transaction = value
        else:
            extras.append(f"f{field}/{_PROTO_WIRE.get(wire, wire)}")
    return applied_ms, source, transaction, extras


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


def _print_setting_delivery(data: bytes, out, *, details: bool) -> None:
    status = None
    enabled = []
    extras = []
    for field, wire, value in proto_decode(data):
        if field == 1 and wire == 0:
            status = value
        elif field == 2 and wire == 0:
            enabled.append(value)
        else:
            extras.append(f"f{field}/{_PROTO_WIRE.get(wire, wire)}")
    names = [
        DATA_DELIVERY_FIELDS.get(item, f"id{item}") for item in enabled
    ]
    status_text = f" status={status}" if status is not None else ""
    print(f"  StoredDataDeliveryControl:{status_text} "
          f"enabled={','.join(names)}", file=out)
    if details and extras:
        print(f"    extras={','.join(extras)}", file=out)


def _print_therapy_profiles(data: bytes, out, *, details: bool) -> None:
    print("  TherapyProfiles:", file=out)
    for field, wire, value in proto_decode(data):
        if wire != 2:
            if details:
                print(f"    f{field}/{_PROTO_WIRE.get(wire, wire)}", file=out)
            continue
        name, defs = THERAPY_PROFILE_FIELDS.get(
            field, (f"TherapyProfile{field}", ())
        )
        body = _format_named_message(value, defs, details=details or not defs)
        print(f"    {name}: {body}", file=out)


def _print_reminders(data: bytes, out, *, details: bool) -> None:
    for field, wire, value in proto_decode(data):
        name = REMINDER_FIELDS.get(field, f"Reminder{field}")
        if wire != 2:
            if details:
                print(f"      {name}: f{field}/{_PROTO_WIRE.get(wire, wire)}",
                      file=out)
            continue
        values = _decode_varint_message(value)
        parts = []
        if 1 in values:
            parts.append(f"EnableRaw={values[1][0]}")
        if 2 in values:
            parts.append(f"StartDateTime={_fmt_utc_ms(values[2][0])}")
        if 3 in values:
            parts.append(f"PeriodRaw={values[3][0]}")
        if details:
            for extra in sorted(set(values) - {1, 2, 3}):
                raw = ",".join(str(v) for v in values[extra])
                parts.append(f"f{extra}={raw}")
        print(f"      {name}: {' '.join(parts)}", file=out)


def _print_feature_profiles(data: bytes, out, *, details: bool) -> None:
    print("  FeatureProfiles:", file=out)
    for field, wire, value in proto_decode(data):
        if field == 14 and wire == 2:
            print("    ReminderFeature:", file=out)
            _print_reminders(value, out, details=details)
            continue
        if wire != 2:
            if details:
                print(f"    f{field}/{_PROTO_WIRE.get(wire, wire)}", file=out)
            continue
        name, defs = FEATURE_PROFILE_FIELDS.get(
            field, (f"FeatureProfile{field}", ())
        )
        body = _format_named_message(value, defs, details=details or not defs)
        print(f"    {name}: {body}", file=out)


def setting_profiles_pretty(spool_type: str, data: bytes, out=None,
                            *, details: bool = False) -> bool:
    """Print SettingProfilesCollection records."""
    if out is None:
        out = sys.stdout
    if spool_type != "SettingProfilesCollection":
        return False
    try:
        records = _setting_profile_records(data)
    except (ValueError, IndexError) as exc:
        print(f"# cannot decode SettingProfilesCollection protobuf: {exc}",
              file=out)
        return True

    print("# SettingProfilesCollection spool", file=out)
    for record_index, record in enumerate(records):
        try:
            fields = proto_decode(record)
        except (ValueError, IndexError) as exc:
            print(f"record {record_index}: invalid protobuf: {exc}", file=out)
            continue
        print(f"record {record_index}:", file=out)
        for field, wire, value in fields:
            if field == 1 and wire == 2:
                applied, source, transaction, extras = _profile_attr(value)
                source_part = f" source={source!r}" if source else ""
                tx_part = (f" transaction={transaction}"
                           if transaction is not None else "")
                print(f"  Attributes: AppliedDateTime={_fmt_utc_ms(applied)}"
                      f"{source_part}{tx_part}", file=out)
                if details and extras:
                    print(f"    extras={','.join(extras)}", file=out)
            elif field == 2 and wire == 2:
                _print_setting_delivery(value, out, details=details)
            elif field == 3 and wire == 2:
                _print_therapy_profiles(value, out, details=details)
            elif field == 4 and wire == 2:
                _print_feature_profiles(value, out, details=details)
            elif details:
                print(f"  f{field}/{_PROTO_WIRE.get(wire, wire)}", file=out)
    return True


def _print_data_delivery_control(data: bytes, out, *, details: bool) -> None:
    values = _decode_varint_message(data)
    parts = []
    for field in sorted(values):
        name = DATA_DELIVERY_FIELDS.get(field, f"id{field}")
        if len(values[field]) == 1:
            parts.append(f"{name}={_delivery_status(values[field][0])}")
        else:
            raw = ",".join(_delivery_status(item) for item in values[field])
            parts.append(f"{name}=[{raw}]")
    line = "    "
    for item in parts:
        if len(line) + len(item) > 100:
            print(line.rstrip(), file=out)
            line = "    "
        line += item + "  "
    if line.strip():
        print(line.rstrip(), file=out)
    if details:
        missing = sorted(set(DATA_DELIVERY_FIELDS) - set(values))
        if missing:
            names = ",".join(DATA_DELIVERY_FIELDS[item] for item in missing)
            print(f"    absent={names}", file=out)


def configuration_profiles_pretty(spool_type: str, data: bytes, out=None,
                                  *, details: bool = False) -> bool:
    """Print ConfigurationProfilesCollection records."""
    if out is None:
        out = sys.stdout
    if spool_type != "ConfigurationProfilesCollection":
        return False
    try:
        records = _config_profile_records(data)
    except (ValueError, IndexError) as exc:
        print(f"# cannot decode ConfigurationProfilesCollection protobuf: {exc}",
              file=out)
        return True

    print("# ConfigurationProfilesCollection spool", file=out)
    for record_index, record in enumerate(records):
        try:
            fields = proto_decode(record)
        except (ValueError, IndexError) as exc:
            print(f"record {record_index}: invalid protobuf: {exc}", file=out)
            continue
        print(f"record {record_index}:", file=out)
        for field, wire, value in fields:
            if field == 1 and wire == 2:
                applied, source, transaction, extras = _profile_attr(value)
                source_part = f" source={source!r}" if source else ""
                tx_part = (f" transaction={transaction}"
                           if transaction is not None else "")
                print(f"  Attributes: AppliedDateTime={_fmt_utc_ms(applied)}"
                      f"{source_part}{tx_part}", file=out)
                if details and extras:
                    print(f"    extras={','.join(extras)}", file=out)
            elif field == 2 and wire == 2:
                print("  DataDeliveryControlV2:", file=out)
                _print_data_delivery_control(value, out, details=details)
            elif details:
                print(f"  f{field}/{_PROTO_WIRE.get(wire, wire)}", file=out)
    return True


def _format_attr_message(data: bytes) -> str:
    fields = []
    for field, wire, value in proto_decode(data):
        if field == 1 and wire == 0:
            fields.append(f"ReportDateTime={_fmt_utc_ms(value)}")
        elif wire == 0:
            fields.append(f"f{field}={value}")
        elif wire == 2:
            fields.append(f"f{field}=bytes:{len(value)}")
        else:
            fields.append(f"f{field}/{_PROTO_WIRE.get(wire, wire)}={value}")
    return " ".join(fields)


def _metric_record_pretty(spool_type: str, record: bytes, out,
                          *, details: bool) -> None:
    spec = METRIC_SPOOL_DEFS[spool_type]
    field_defs = spec["fields"]
    for field, wire, value in proto_decode(record):
        label, kind = field_defs.get(field, (f"f{field}", "raw"))
        if kind == "attributes" and wire == 2:
            print(f"  {label}: {_format_attr_message(value)}", file=out)
        elif wire == 0:
            print(f"  {label}: {_format_metric_value(value, kind)}", file=out)
        elif details and wire == 2:
            print(f"  {label}: bytes={len(value)}", file=out)
        elif details:
            print(f"  {label}: {_PROTO_WIRE.get(wire, wire)}={value}",
                  file=out)


def _memory_metrics_pretty(record: bytes, out, *, details: bool) -> None:
    for field, wire, value in proto_decode(record):
        if field == 1 and wire == 2:
            print(f"  Attributes: {_format_attr_message(value)}", file=out)
            continue
        if field == 2 and wire == 2:
            values = _decode_varint_message(value)
            parts = []
            for subfield in sorted(values):
                name = MEMORY_METRIC_FIELDS.get(subfield, f"f{subfield}")
                raw = ",".join(str(item) for item in values[subfield])
                parts.append(f"{name}={raw}")
            print("  MemoryMetric: " + " ".join(parts), file=out)
            continue
        if details:
            print(f"  f{field}/{_PROTO_WIRE.get(wire, wire)}", file=out)


def metric_spool_pretty(spool_type: str, data: bytes, out=None,
                        *, details: bool = False) -> bool:
    """Print metric snapshot spools."""
    if out is None:
        out = sys.stdout
    if spool_type not in METRIC_SPOOL_TYPES:
        return False
    if not data:
        print(f"# {spool_type} spool is empty", file=out)
        return True

    if spool_type == "MemoryMetrics":
        expected_field = 16
    else:
        expected_field = METRIC_SPOOL_DEFS.get(spool_type, {}).get("wire_field")
    try:
        records = _wrapped_records(data, expected_field)
    except (ValueError, IndexError) as exc:
        print(f"# cannot decode {spool_type} protobuf: {exc}", file=out)
        return True

    print(f"# {spool_type} metric spool", file=out)
    for record_index, record in enumerate(records):
        print(f"record {record_index}:", file=out)
        if spool_type == "MemoryMetrics":
            _memory_metrics_pretty(record, out, details=details)
        elif spool_type in METRIC_SPOOL_DEFS:
            _metric_record_pretty(spool_type, record, out, details=details)
        else:
            proto_pretty(record, indent=1, out=out)
    return True


def therapy_one_minute_pretty(spool_type: str, data: bytes, out=None,
                              *, samples: bool = False,
                              details: bool = False) -> bool:
    """Print TherapyOneMinutePeriodic records as ranges or CSV samples."""
    if out is None:
        out = sys.stdout
    if spool_type != "TherapyOneMinutePeriodic":
        return False

    try:
        records = _therapy_1minute_records(data)
    except (ValueError, IndexError) as exc:
        print(f"# cannot decode TherapyOneMinutePeriodic protobuf: {exc}",
              file=out)
        return True

    columns = [
        THERAPY_1MINUTE_FIELDS[field]["column"]
        for field in sorted(THERAPY_1MINUTE_FIELDS)
    ]
    if samples:
        raw_columns = []
        if details:
            raw_columns = [
                "raw_" + THERAPY_1MINUTE_FIELDS[field]["column"]
                for field in sorted(THERAPY_1MINUTE_FIELDS)
            ]
        print(",".join(
            ["record", "index", "time_ms", "time_utc"] + columns + raw_columns
        ), file=out)
    else:
        print("# TherapyOneMinutePeriodic spool", file=out)
        print("# field 3 sample blocks are headerless int16 delta2/Rice series",
              file=out)

    for record_index, record in enumerate(records):
        try:
            fields = proto_decode(record)
        except (ValueError, IndexError) as exc:
            print(f"record {record_index}: invalid protobuf: {exc}", file=out)
            continue

        interval_token = None
        signals = {}
        extras = []
        for field, wire, value in fields:
            if field == 15 and wire == 0:
                interval_token = value
            elif field in THERAPY_1MINUTE_FIELDS and wire == 2:
                try:
                    signals[field] = _therapy_1minute_signal(value, field)
                except (ValueError, IndexError) as exc:
                    extras.append((field, f"decode_error={exc}"))
            else:
                extras.append((field, _PROTO_WIRE.get(wire, wire)))

        interval_ms = _therapy_1minute_interval_ms(interval_token)
        starts = [
            sig["start_ms"] for sig in signals.values()
            if sig["start_ms"] is not None
        ]
        start_ms = min(starts) if starts else None
        sample_count = max((len(sig["values"]) for sig in signals.values()),
                           default=0)

        if samples:
            for sample_index in range(sample_count):
                ts = ""
                ts_utc = ""
                if start_ms is not None:
                    ts = str(start_ms + sample_index * interval_ms)
                    ts_utc = _fmt_utc_ms(int(ts))
                values = []
                raw_values = []
                for field in sorted(THERAPY_1MINUTE_FIELDS):
                    sig = signals.get(field)
                    if sig is None or sample_index >= len(sig["values"]):
                        values.append("")
                        raw_values.append("")
                    else:
                        values.append(_fmt_number(sig["values"][sample_index]))
                        raw_values.append(str(sig["raw"][sample_index]))
                row = [str(record_index), str(sample_index), ts, ts_utc] + values
                if details:
                    row += raw_values
                print(",".join(row), file=out)
            continue

        signal_names = ",".join(
            THERAPY_1MINUTE_FIELDS[field]["name"]
            for field in sorted(signals)
        )
        print(f"record {record_index}: start={start_ms} "
              f"[{_fmt_utc_ms(start_ms) if start_ms is not None else ''}] "
              f"interval_ms={interval_ms} samples={sample_count} "
              f"signals={signal_names}", file=out)
        for field in sorted(signals):
            sig = signals[field]
            spec = sig["spec"]
            raw = sig["raw"]
            values = sig["values"]
            if not raw:
                print(f"  {spec['name']}: samples=0", file=out)
                continue
            detail = ""
            if details:
                detail = (f" status={sig['status']} "
                          f"blob_bytes={len(sig['blob'])}")
            print(
                f"  {spec['name']}: samples={len(values)} unit={spec['unit']} "
                f"raw_min={min(raw)} raw_max={max(raw)} "
                f"value_min={min(values):.8g} value_max={max(values):.8g}"
                f"{detail}",
                file=out,
            )
        if extras:
            print("  extras=" + ",".join(f"f{field}:{note}"
                                         for field, note in extras),
                  file=out)
    return True


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


def periodic_compressed_pretty(spool_type: str, data: bytes, out=None,
                               *, samples: bool = False,
                               details: bool = False) -> bool:
    """Print DiagnosticTenMinutePeriodic/related compressed series."""
    if out is None:
        out = sys.stdout
    if spool_type not in PERIODIC_COMPRESSED_SPOOL_TYPES:
        return False
    if not data:
        print(f"# {spool_type} spool is empty", file=out)
        return True

    expected = SPOOL_REGISTRY.get(spool_type, {}).get("wire_field")
    try:
        records = _wrapped_records(data, expected)
    except (ValueError, IndexError) as exc:
        print(f"# cannot decode {spool_type} protobuf: {exc}", file=out)
        return True

    if samples:
        print("record,signal,index,time_ms,time_utc,value_raw,value", file=out)
    else:
        print(f"# {spool_type} compressed periodic spool", file=out)
        print("# field 1 = origin/kind, signal fields carry interval, "
              "start timestamp, and a headerless int16 delta2/Rice block",
              file=out)

    for record_index, record in enumerate(records):
        try:
            fields = proto_decode(record)
        except (ValueError, IndexError) as exc:
            if not samples:
                print(f"record {record_index}: invalid protobuf: {exc}",
                      file=out)
            continue
        origin = None
        signals = []
        extras = []
        for field, wire, value in fields:
            if field == 1 and wire == 0:
                origin = value
            elif wire == 2:
                try:
                    signals.append(_periodic_compressed_signal(field, value))
                except (ValueError, IndexError) as exc:
                    extras.append(f"f{field}:decode_error={exc}")
            else:
                extras.append(f"f{field}/{_PROTO_WIRE.get(wire, wire)}")

        if samples:
            for sig in signals:
                name = sig["spec"]["name"]
                for sample_index, (raw, physical) in enumerate(
                        zip(sig["raw"], sig["values"])):
                    ts = ""
                    ts_utc = ""
                    if sig["start_ms"] is not None:
                        ts = str(sig["start_ms"]
                                 + sample_index * sig["interval_ms"])
                        ts_utc = _fmt_utc_ms(int(ts))
                    print(f"{record_index},{name},{sample_index},{ts},"
                          f"{ts_utc},{raw},{_fmt_number(physical)}",
                          file=out)
            continue

        print(f"record {record_index}: origin={origin} "
              f"signals={len(signals)}", file=out)
        for sig in signals:
            values = sig["values"]
            raw = sig["raw"]
            name = sig["spec"]["name"]
            start = sig["start_ms"]
            start_text = _fmt_utc_ms(start) if start is not None else "n/a"
            print(f"  {name}: start={start_text} "
                  f"interval_ms={sig['interval_ms']} samples={len(values)} "
                  f"raw_min={min(raw)} raw_max={max(raw)} "
                  f"value_min={_fmt_number(min(values))} "
                  f"value_max={_fmt_number(max(values))}",
                  file=out)
            print(f"    first_values={_rc03_preview(values[:8])}", file=out)
            print(f"    last_values={_rc03_preview(values[-8:])}", file=out)
            if details and sig["extras"]:
                print(f"    extras={sig['extras']}", file=out)
        if details and extras:
            print(f"  extras={extras}", file=out)
    return True


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


def _rc03_preview(values: list[float]) -> str:
    return "[" + ", ".join(f"{value:.8g}" for value in values) + "]"


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


def rc03_spool_pretty(spool_type: str, data: bytes, out=None,
                      *, samples: bool = False) -> bool:
    """Print archived RC03 signal records. Returns True when handled."""
    if out is None:
        out = sys.stdout
    expected_field = RC03_SPOOL_FIELDS.get(spool_type)
    if expected_field is None:
        return False

    try:
        records = proto_decode(data)
    except (ValueError, IndexError) as exc:
        print(f"# cannot decode outer protobuf: {exc}", file=out)
        return True

    print("# archived signal spool", file=out)
    print("# field 4 is an RC03 compressed sample block", file=out)
    if samples:
        print("record,index,time_ms,value_raw,value", file=out)
    for idx, (field, wire, value) in enumerate(records):
        if field != expected_field or wire != 2:
            print(f"record {idx}: unexpected f{field}/{_PROTO_WIRE.get(wire, wire)}",
                  file=out)
            continue
        outer = proto_decode(value)
        record_kind = None
        payload = None
        for sf, sw, sv in outer:
            if sf == 1 and sw == 0:
                record_kind = sv
            elif sf == 2 and sw == 2:
                payload = sv
        if payload is None:
            print(f"record {idx}: missing payload", file=out)
            continue
        fields = {}
        block = None
        for sf, sw, sv in proto_decode(payload):
            if sw == 0:
                fields[sf] = sv
            elif sf == 4 and sw == 2:
                block = sv
        interval = fields.get(1)
        start = fields.get(2)
        end = fields.get(3)
        count = "n/a"
        if interval and start is not None and end is not None and end >= start:
            count = (end - start) // interval + 1
        if block is None:
            if not samples:
                print(f"record {idx}: missing RC03 block", file=out)
            continue
        try:
            decoded = rc03_decode_block(block, int(count))
        except ValueError as exc:
            if not samples:
                print(f"record {idx}: {exc}", file=out)
            continue
        if samples:
            for sample_index, (raw, physical) in enumerate(
                    zip(decoded["values"], decoded["physical"])):
                ts = (start + sample_index * interval
                      if start is not None and interval else "")
                print(f"{idx},{sample_index},{ts},{raw},{physical:.8g}",
                      file=out)
            continue
        body = decoded["body"]
        compressed = max(0, len(body) - 2 * len(decoded["seed"]))
        physical = decoded["physical"]
        print(f"record {idx}: kind={record_kind} interval_ms={interval} "
              f"samples={count}", file=out)
        if start is not None and end is not None:
            print(f"  start={start} [{_fmt_utc_ms(start)}]", file=out)
            print(f"  end={end} [{_fmt_utc_ms(end)}]", file=out)
        print(f"  rc03_header={decoded['header'].hex()} "
              f"params={decoded['params']} raw_params={decoded['raw_params'].hex()} "
              f"rice_m={decoded['m']} scale={decoded['scale']:.8g}",
              file=out)
        print(f"  raw_seed={decoded['seed']} body_bytes={len(body)} "
              f"compressed_tail_bytes={compressed}", file=out)
        print(f"  raw_min={min(decoded['values'])} raw_max={max(decoded['values'])} "
              f"value_min={min(physical):.8g} value_max={max(physical):.8g}",
              file=out)
        print(f"  first_values={_rc03_preview(physical[:8])}", file=out)
        print(f"  last_values={_rc03_preview(physical[-8:])}", file=out)
    return True


def _hex_preview(data: bytes, limit: int = 64) -> str:
    out = data[:limit].hex()
    if len(data) > limit:
        out += "..."
    return out


def soundcheck_vector_pretty(spool_type: str, data: bytes, out=None,
                             *, samples: bool = False,
                             details: bool = False) -> bool:
    """Print SoundcheckVector records."""
    if out is None:
        out = sys.stdout
    if spool_type != "SoundcheckVector":
        return False
    if not data:
        print("# SoundcheckVector spool is empty", file=out)
        return True

    try:
        records = _wrapped_records(data, 15)
    except (ValueError, IndexError) as exc:
        print(f"# cannot decode SoundcheckVector protobuf: {exc}", file=out)
        return True

    if samples:
        print("record,kind,index,value_a,value_b", file=out)
    else:
        print("# SoundcheckVector spool", file=out)
        print("# field 3 values are the vector bins; field 4 contains "
              "repeated peak pairs", file=out)

    for record_index, record in enumerate(records):
        try:
            fields = proto_decode(record)
        except (ValueError, IndexError) as exc:
            if not samples:
                print(f"record {record_index}: invalid protobuf: {exc}",
                      file=out)
            continue
        report_ms = None
        sample_rate = None
        vector = []
        peaks = []
        extras = []
        for field, wire, value in fields:
            if field == 1 and wire == 0:
                report_ms = value
            elif field == 2 and wire == 0:
                sample_rate = value
            elif field == 3 and wire == 0:
                vector.append(value)
            elif field == 4 and wire == 2:
                try:
                    for pf, pw, pv in proto_decode(value):
                        if pf == 1 and pw == 2:
                            pair = _decode_varint_message(pv)
                            peaks.append((
                                pair.get(1, [None])[0],
                                pair.get(2, [None])[0],
                            ))
                        else:
                            extras.append(f"peak_f{pf}/{_PROTO_WIRE.get(pw, pw)}")
                except (ValueError, IndexError) as exc:
                    extras.append(f"peaks_decode_error={exc}")
            else:
                extras.append(f"f{field}/{_PROTO_WIRE.get(wire, wire)}")

        if samples:
            for idx, value in enumerate(vector):
                print(f"{record_index},vector,{idx},{value},", file=out)
            for idx, (a, b) in enumerate(peaks):
                print(f"{record_index},peak,{idx},{a},{b}", file=out)
            continue

        print(f"record {record_index}: report={_fmt_utc_ms(report_ms)} "
              f"sample_rate_hz={sample_rate} vector_bins={len(vector)} "
              f"peaks={len(peaks)}", file=out)
        print(f"  vector={_rc03_preview(vector)}", file=out)
        if peaks:
            peak_text = ", ".join(f"({a},{b})" for a, b in peaks)
            print(f"  peaks={peak_text}", file=out)
        if details and extras:
            print(f"  extras={extras}", file=out)
    return True


def diagnostic_blob_pretty(spool_type: str, data: bytes, out=None,
                           *, details: bool = False) -> bool:
    """Print currently unresolved diagnostic blob spools conservatively."""
    if out is None:
        out = sys.stdout
    if spool_type != "AcousticSignatureV2":
        return False
    print("# AcousticSignatureV2 diagnostic blob spool", file=out)
    if not data:
        print("empty", file=out)
        return True
    print(f"bytes={len(data)} hex={_hex_preview(data)}", file=out)
    try:
        fields = proto_decode(data)
    except (ValueError, IndexError):
        return True
    if details:
        proto_pretty(data, indent=1, out=out)
    else:
        parts = []
        for field, wire, value in fields:
            if wire == 2:
                parts.append(f"f{field}=bytes:{len(value)}")
            else:
                parts.append(f"f{field}/{_PROTO_WIRE.get(wire, wire)}")
        if parts:
            print("fields=" + " ".join(parts), file=out)
    return True


def audio_spool_pretty(spool_type: str, data: bytes, out=None,
                       *, details: bool = False) -> bool:
    """Print RecordedSound metadata without assuming a container format."""
    if out is None:
        out = sys.stdout
    if spool_type != "RecordedSound":
        return False
    print("# RecordedSound audio spool", file=out)
    if not data:
        print("empty", file=out)
        return True
    print(f"bytes={len(data)} hex={_hex_preview(data)}", file=out)
    if data.startswith(b"RIFF") and len(data) >= 44:
        print("container=RIFF/WAVE", file=out)
    elif details:
        try:
            proto_pretty(data, indent=1, out=out)
        except (ValueError, IndexError):
            pass
    return True


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
    14: {2: (50, 2.0), 3: (70, 2.0), 4: (95, 2.0), 5: (100, 2.0)},  # Leak
    15: {2: (50, 2.0), 3: (95, 2.0), 4: (100, 2.0)},
    20: {2: (50, 2.0), 3: (95, 2.0), 4: (100, 2.0)},
    21: {2: (50, 2.0), 3: (95, 2.0), 4: (100, 2.0)},
    22: {2: (50, 2.0), 3: (95, 2.0), 4: (100, 2.0)},
    23: {2: (50, 8.0), 3: (95, 8.0), 4: (100, 8.0)},
    24: {2: (50, 1.0), 3: (95, 1.0), 4: (100, 1.0)},
    25: {2: (50, 5.0), 3: (95, 5.0), 4: (100, 5.0)},
    26: {2: (50, 1.0), 3: (95, 1.0), 4: (100, 1.0)},
    27: {2: (50, 1.0), 3: (95, 1.0), 4: (100, 1.0)},
    28: {2: (50, 1.0), 3: (95, 1.0), 4: (100, 1.0)},
    29: {2: (50, 10.0)},
    30: {2: (50, 10.0)},
    31: {2: (50, 10.0)},
    32: {2: (50, 10.0)},
    33: {2: (50, 10.0)},
    36: {1: (5, 2.0),  3: (95, 2.0)},
    37: {1: (5, 0.2),  3: (95, 0.2)},
    38: {2: (50, 0.2)},
    41: {2: (50, 1.0), 3: (95, 1.0), 4: (100, 1.0)},
    42: {2: (50, 1.0), 3: (95, 1.0), 4: (100, 1.0)},
}


def _summary_record_pretty(data: bytes, out) -> None:
    for field, wire, value in proto_decode(data):
        label = _SUMMARY_FIELDS.get(field, f"field_{field}")
        if wire == 2:
            try:
                subs = proto_decode(value)
            except (ValueError, IndexError):
                subs = None
            if subs:
                print(f"{label} (msg, {len(value)}B):", file=out)
                submap = _SUMMARY_SUBFIELDS.get(field, {})
                for sf, sw, sv in subs:
                    if sf in submap:
                        pct, mult = submap[sf]
                        tail = f"  # p{pct}, mult={mult}x (wire=raw*mult)"
                    else:
                        tail = ""
                    print(f"  sub_f{sf} ({_PROTO_WIRE.get(sw, sw)}): {sv}{tail}",
                          file=out)
            else:
                h = value.hex()
                if len(h) > 80:
                    h = h[:80] + "..."
                print(f"{label} (bytes {len(value)}B): {h}", file=out)
        elif wire == 0:
            print(f"{label} (varint): {value}", file=out)
        elif wire == 1:
            print(f"{label} (u64): {value}", file=out)
        elif wire == 5:
            print(f"{label} (u32): {value}", file=out)
        else:
            print(f"{label} ({_PROTO_WIRE.get(wire, wire)}): {value}", file=out)


def _summary_metric_name(label: str) -> str:
    return label.split(" (", 1)[0]


def _summary_session_entries(data: bytes) -> list[tuple[int | None, int | None]]:
    entries = []
    try:
        wrappers = proto_decode(data)
    except (ValueError, IndexError):
        return entries
    for field, wire, value in wrappers:
        if field != 1 or wire != 2:
            continue
        ts = None
        duration_min = None
        try:
            fields = proto_decode(value)
        except (ValueError, IndexError):
            continue
        for sf, sw, sv in fields:
            if sf == 1 and sw == 0:
                ts = sv
            elif sf == 2 and sw == 0:
                duration_min = sv
        entries.append((ts, duration_min))
    return entries


def _summary_session_duration(duration_min: int | None) -> str:
    if duration_min is None:
        return "n/a"
    return str(duration_min)


def _summary_record_stats(data: bytes) -> dict:
    stats = {
        "scalars": [],
        "metrics": [],
        "session_entries": [],
    }
    for field, wire, value in proto_decode(data):
        label = _SUMMARY_FIELDS.get(field, f"field_{field}")
        if field == 6 and wire == 2:
            stats["session_entries"] = _summary_session_entries(value)
            continue
        if wire == 2:
            submap = _SUMMARY_SUBFIELDS.get(field)
            if submap:
                cols = {}
                extras = []
                try:
                    subs = proto_decode(value)
                except (ValueError, IndexError):
                    subs = []
                for sf, sw, sv in subs:
                    if sw == 0 and sf in submap:
                        pct, _mult = submap[sf]
                        cols[pct] = sv
                    else:
                        extras.append(f"f{sf}/{_PROTO_WIRE.get(sw, sw)}")
                stats["metrics"].append((_summary_metric_name(label), cols, extras))
            else:
                stats["scalars"].append((_summary_metric_name(label),
                                         f"{len(value)}B"))
            continue
        if wire == 0:
            scale = _SUMMARY_SCALAR_SCALES.get(field)
            if scale is not None:
                stats["scalars"].append((_summary_metric_name(label),
                                         value * scale, value))
            else:
                stats["scalars"].append((_summary_metric_name(label), value))
        elif wire == 1:
            stats["scalars"].append((_summary_metric_name(label), value))
        elif wire == 5:
            stats["scalars"].append((_summary_metric_name(label), value))
        else:
            stats["scalars"].append((_summary_metric_name(label),
                                     f"{_PROTO_WIRE.get(wire, wire)}:{value}"))
    return stats


def _summary_scalar(stats: dict, name: str):
    for item in stats["scalars"]:
        key, value = item[0], item[1]
        if key == name:
            return value
    return None


def _summary_record_compact(index: int, data: bytes, out) -> None:
    stats = _summary_record_stats(data)
    start = _summary_scalar(stats, "PeriodStart")
    end = _summary_scalar(stats, "PeriodEnd")
    tz_offset = _summary_scalar(stats, "TimeZoneOffsetMin")
    duration = _summary_scalar(stats, "DurationMin")
    session_count = _summary_scalar(stats, "SessionCount")
    if session_count is None:
        session_count = len(stats["session_entries"])
    record_ts = _summary_scalar(stats, "RecordTimestamp")
    smd_smt_ts = _summary_scalar(stats, "SmdSmtTimestamp")
    print(f"Summary record {index} ({len(data)}B):", file=out)
    if isinstance(start, int) and isinstance(end, int):
        print(f"  range: {_fmt_utc_ms(start)} -> {_fmt_utc_ms(end)}", file=out)
    bits = []
    if duration is not None:
        bits.append(f"duration_min={duration}")
    bits.append(f"sessions={session_count}")
    if tz_offset is not None:
        bits.append(f"tz_offset_min={tz_offset}")
    if isinstance(record_ts, int):
        bits.append(f"record_ts={_fmt_utc_ms(record_ts)}")
    if isinstance(smd_smt_ts, int):
        bits.append(f"smd_smt_ts={_fmt_utc_ms(smd_smt_ts)}")
    print("  " + " ".join(bits), file=out)

    if stats["session_entries"]:
        print("  session_entries:", file=out)
        for ts, duration_min in stats["session_entries"]:
            when = _fmt_utc_ms(ts) if isinstance(ts, int) else "n/a"
            print(f"    {when}  duration_min={_summary_session_duration(duration_min)}",
                  file=out)

    skip_scalars = {
        "f1_init_marker", "PeriodStart", "PeriodEnd",
        "TimeZoneOffsetMin", "DurationMin", "SessionCount",
        "RecordTimestamp", "SmdSmtTimestamp",
    }
    scalars = [item for item in stats["scalars"]
               if item[0] not in skip_scalars]
    if scalars:
        print("  scalars:", file=out)
        line = "    "
        for scalar in scalars:
            name, value = scalar[0], scalar[1]
            if len(scalar) > 2:
                item = f"{name}={value:g} (raw={scalar[2]})"
            else:
                item = f"{name}={value}"
            if len(line) + len(item) + 2 > 96:
                print(line.rstrip(), file=out)
                line = "    "
            line += item + "  "
        if line.strip():
            print(line.rstrip(), file=out)

    if stats["metrics"]:
        print("  metrics (wire values):", file=out)
        for name, cols, extras in stats["metrics"]:
            parts = [f"p{pct}={cols[pct]}" for pct in (5, 50, 70, 95, 100)
                     if pct in cols]
            if extras:
                parts.append("extra=" + ",".join(extras))
            print(f"    {name}: " + " ".join(parts), file=out)


def summary_pretty(data: bytes, out=None, *, details: bool = False) -> None:
    """Pretty-print the Summary protobuf using firmware-verified field names."""
    if out is None:
        out = sys.stdout

    try:
        top = proto_decode(data)
    except (ValueError, IndexError):
        return

    # Summary spool payloads are usually repeated field-2 wrapper records.
    if top and all(field == 2 and wire == 2 for field, wire, _value in top):
        for idx, (_field, _wire, value) in enumerate(top, 1):
            if details:
                print(f"Summary record {idx} ({len(value)}B):", file=out)
                _summary_record_pretty(value, out)
            else:
                _summary_record_compact(idx, value, out)
        return

    while (len(top) == 1 and top[0][1] == 2
           and isinstance(top[0][2], (bytes, bytearray))):
        data = top[0][2]
        try:
            top = proto_decode(data)
        except (ValueError, IndexError):
            return
    if details:
        _summary_record_pretty(data, out)
    else:
        _summary_record_compact(1, data, out)


def print_spool_legend(spool_type: str) -> None:
    legend = SPOOL_LEGENDS.get(spool_type)
    if not legend:
        return
    et = legend.get("event_types")
    if et:
        print("# event record layout: field 1 = type, field 2 = start_ms, "
              "field 3 = end_ms, field 4 = duration_ms")
        parts = ", ".join(f"{k}={v}" for k, v in sorted(et.items()))
        print(f"# event types: {parts}")
        print()


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


def _event_name(spool_type: str, event_type: int) -> str:
    legend = SPOOL_LEGENDS.get(spool_type, {})
    return legend.get("event_types", {}).get(event_type, "")


def _event_extra(spool_type: str, event_type: int, field: int,
                 wire: int, value: object) -> str:
    legend = SPOOL_LEGENDS.get(spool_type, {})
    if (spool_type == "CellularActivityEvents" and event_type == 95
            and field == 14 and wire == 0):
        packed = int(value)
        error_id = (packed >> 12) & 0xFFF
        detail_id = packed & 0xFFF
        error_name = legend.get("log_error_ids", {}).get(error_id)
        error = f"{error_id}({error_name})" if error_name else str(error_id)
        return f"error_id={error},detail_id={detail_id}"

    name = legend.get("extra_fields", {}).get((event_type, field))
    if name is None:
        name = f"f{field}/{_PROTO_WIRE.get(wire, wire)}"
    if wire == 0:
        enum_name = legend.get("extra_enums", {}).get(
            (event_type, field), {}
        ).get(value)
        if enum_name:
            value = f"{value}({enum_name})"
    elif wire == 2:
        raw = bytes(value)
        value = repr(raw.decode("ascii")) if (
            raw and all(32 <= byte < 127 for byte in raw)
        ) else "0x" + raw.hex()
    return f"{name}={value}"


def event_spool_pretty(spool_type: str, data: bytes, out=None) -> bool:
    """Print common AS11 event-spool records as a compact table."""
    if out is None:
        out = sys.stdout
    if spool_type not in EVENT_SPOOL_TYPES:
        return False
    records = []
    for ev in spool_walk_events(data):
        record = _event_record(ev)
        if record is not None:
            records.append(record)
    if not records:
        return False

    print("# event spool", file=out)
    print("idx\ttype\tname\tstart_ms\tstart_utc\tend_ms\tend_utc\tduration_ms\textras",
          file=out)
    for idx, record in enumerate(records):
        event_type = int(record["type"])
        start = int(record["start"])
        end = int(record["end"])
        duration = record["duration"]
        if duration is None:
            duration = end - start
        extras = ",".join(
            _event_extra(spool_type, event_type, field, wire, value)
            for field, wire, value in record["extras"]
        )
        name = _event_name(spool_type, event_type) or "unknown"
        print(
            f"{idx}\t{event_type}\t{name}\t"
            f"{start}\t{_fmt_utc_ms(start)}\t"
            f"{end}\t{_fmt_utc_ms(end)}\t{duration}\t{extras}",
            file=out,
        )

    counts = Counter(int(record["type"]) for record in records)
    print("", file=out)
    print(f"# summary: {len(records)} events", file=out)
    for event_type in sorted(counts):
        name = _event_name(spool_type, event_type)
        label = f"{event_type}"
        if name:
            label += f" {name}"
        print(f"#   {label:28s} {counts[event_type]:6d}", file=out)
    return True


def print_spool_summary(spool_type: str, data: bytes) -> None:
    legend = SPOOL_LEGENDS.get(spool_type)
    if not legend:
        return
    et = legend.get("event_types")
    if not et:
        return
    from collections import Counter
    counts = Counter()
    total = 0
    for ev in spool_walk_events(data):
        total += 1
        try:
            for field, wire, value in proto_decode(ev):
                if field == 1 and wire == 0:
                    counts[value] += 1
                    break
        except (ValueError, IndexError):
            pass
    if total:
        print()
        print(f"# summary: {total} events")
        for k in sorted(counts):
            print(f"#   {et.get(k, f'type={k}'):20s} {counts[k]:6d}")


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
    in the registry, best_match is the only candidate. When two or more
    spool types share the same wire field (e.g. ActivityEvents-Frequent
    vs -Sporadic on f10), best_match is the first registry entry that
    matches; the full list of candidates is available for display.
    Returns (None, []) when the payload could not be parsed or no
    registered spool uses that wire field.
    """
    from as11_rpc_vars import SPOOL_FIELDS  # late import to avoid cycle
    field = spool_payload_first_field(data)
    if field is None:
        return None, []
    candidates = SPOOL_FIELDS.get(field, [])
    if not candidates:
        return None, []
    return candidates[0], list(candidates)


__all__ = [
    "SPOOL_LEGENDS",
    "SpoolError",
    "spool_one_round",
    "proto_decode", "proto_pretty",
    "summary_pretty",
    "spool_payload_shape", "spool_payload_first_field", "detect_spool_type",
    "setting_profiles_pretty", "configuration_profiles_pretty",
    "metric_spool_pretty", "periodic_compressed_pretty",
    "soundcheck_vector_pretty", "diagnostic_blob_pretty",
    "audio_spool_pretty", "rc03_spool_pretty", "therapy_one_minute_pretty",
    "event_spool_pretty",
    "print_spool_legend", "print_spool_summary", "spool_walk_events",
]

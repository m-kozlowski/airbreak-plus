"""AS11 JSON-RPC core. Transport-agnostic.

Defines the `Transport` protocol every backend implements plus
shared tables and CLI helpers
"""

from __future__ import annotations

import binascii
import datetime as _dt
import json
import struct
import sys
from pathlib import Path
from typing import Protocol, runtime_checkable


AS11_RPC_PROFILE = "as11"
AIRMINI_RPC_PROFILE = "airmini"


AS11_RPC_VERSIONS: dict[str, str] = {
    "GetDateTime": "1.0", "SetDateTime": "1.1", "GetVersion": "2.0",
    "StartStream": "1.0", "InitiateUpgrade": "1.0", "UpgradeDataBlock": "1.0",
    "CheckUpgradeFile": "1.0", "ApplyUpgrade": "1.1", "GetLedStatus": "1.0",
    "EnterStandby": "1.0", "EnterTherapy": "1.0", "SetNextPowerUpDateTime": "1.0",
    "SubscribeEvent": "1.0", "EraseData": "1.0", "ResetDevice": "1.0",
    "StoreSecurityData": "1.0", "EnterMaskFit": "2.0",
    "ApplyAuthenticatedUpgrade": "1.0", "Get": "1.0", "Set": "1.0",
    "VerifySecurityData": "1.0", "GenerateAuthCode": "1.1",
    "ClearAutoConnectList": "1.0", "DiscardPairKey": "1.0",
    "StartSpool": "1.0", "PullSpoolFragments": "1.0",
    "EnterTestDrive": "1.0", "EnableSecurity": "1.0",
    "StartKeyExchange": "2.0", "ConfirmKeyExchange": "2.0",
    "RequestSession": "2.0", "CheckSessionIntegrity": "2.0",
}

# AirMini shares most command contracts with AirSense 11, but the versions of
# these methods differ in the AirMini firmware.  Its SDK-facing methods and
# unknown extension calls use JSON-RPC 2.0.
AIRMINI_RPC_VERSIONS: dict[str, str] = {
    **AS11_RPC_VERSIONS,
    "SetDateTime": "1.0",
    "EnterMaskFit": "1.0",
    "GetPairKey": "2.0",
    "GetSessionKey": "2.0",
    "GetLoggedData": "2.0",
    "GetHistory": "2.0",
    "BtDisconnect": "2.0",
}

RPC_VERSION_PROFILES: dict[str, dict[str, str]] = {
    AS11_RPC_PROFILE: AS11_RPC_VERSIONS,
    AIRMINI_RPC_PROFILE: AIRMINI_RPC_VERSIONS,
}
RPC_DEFAULT_VERSIONS: dict[str, str] = {
    AS11_RPC_PROFILE: "1.0",
    AIRMINI_RPC_PROFILE: "2.0",
}

# Backwards-compatible name for callers that are explicitly AS11-only.
RPC_VERSIONS = AS11_RPC_VERSIONS


def rpc_version(method: str, profile: str = AS11_RPC_PROFILE, *,
                default: str | None = None) -> str:
    """Return the request contract version for one device-family profile."""
    try:
        versions = RPC_VERSION_PROFILES[profile]
        profile_default = RPC_DEFAULT_VERSIONS[profile]
    except KeyError as exc:
        raise ValueError(f"unknown RPC profile: {profile!r}") from exc
    return versions.get(method, profile_default if default is None else default)


class TransportError(RuntimeError):
    """Link-level failure (disconnected, bus-off, etc.)."""


class FramingError(TransportError):
    """Response framing/CRC failed. Request likely delivered, response unverified;
    post-call device state is UNKNOWN. Blind retry is unsafe."""


@runtime_checkable
class Transport(Protocol):

    def connect(self) -> None: ...
    def close(self) -> None: ...

    def __enter__(self) -> "Transport": ...
    def __exit__(self, exc_type, exc, tb) -> None: ...

    def rpc(self, method: str, params: object | None = None,
            *, timeout: float = 5.0,
            post_send_delay: float = 0.0) -> dict: ...

    def set_notification_handler(self, handler) -> None:
        """Install a persistent notification handler.

        `handler(msg)` is called for every device-initiated RPC
        notification (JSON with "method" but no "id"), including during
        RPC calls and not just during listen_for_notifications. This
        matters for protocols like StartSpool where the device starts
        pushing notifications immediately after the request arrives,
        which can happen before listen_for_notifications starts blocking.

        `handler` may return truthy to request the listener to stop (used
        by listen_for_notifications and examined by spool_one_round).
        Returning None or falsy is the common case.

        Pass None to clear.
        """
        ...

    def listen_for_notifications(self,
                                 *,
                                 duration: float | None = None) -> None:
        """Block, consuming any incoming bus traffic, and dispatch
        notifications to the handler set via set_notification_handler.

        `duration` is seconds; None means run until KeyboardInterrupt,
        disconnection, or the handler returning truthy. Implementations
        MUST return on Ctrl-C.
        """
        ...

    @property
    def name(self) -> str: ...

    @property
    def supports_encrypted(self) -> bool:
        """True if this transport can reach the encrypted admin VCID
        (BLE or AirMini SPP). False for plaintext CAN. Consulted by the OTA flow to
        pick the default apply mode."""
        ...



def build_request(method: str, params: object | None, rpc_id: int, *,
                  profile: str = AS11_RPC_PROFILE) -> bytes:
    """Produce the JSON-RPC request payload for a given method.

    Callers supply the id; transports own their own id counters.
    """
    req: dict = {
        "jsonrpc": rpc_version(method, profile),
        "method": method,
        "id": rpc_id,
    }
    if params is not None:
        req["params"] = params
    return json.dumps(req, separators=(",", ":")).encode("utf-8")


def parse_response(raw: bytes, expected_id: int | None = None) -> dict:
    """Decode a JSON-RPC response payload.

    If `expected_id` is provided, raises TransportError on id mismatch.
    """
    obj = json.loads(raw.decode("utf-8", errors="replace"))
    if expected_id is not None and obj.get("id") != expected_id:
        raise TransportError(
            f"RPC id mismatch: expected {expected_id}, got {obj.get('id')}"
        )
    return obj



TYPE_COERCE = {
    "str":   lambda v: v,
    "int":   int,
    "float": float,
    "bool":  lambda v: {"true": True, "1": True, "yes": True,
                        "false": False, "0": False, "no": False}[v.lower()],
    "json":  json.loads,
}


def parse_set_items(items: list[str]) -> list[tuple[str, str, str]]:
    """[Name Value (--type T)?]* -> [(name, value_str, type)]."""
    pairs: list[tuple[str, str, str]] = []
    pending: tuple[str, str] | None = None
    i = 0
    while i < len(items):
        tok = items[i]
        if tok == "--type" or tok.startswith("--type="):
            if pending is None:
                raise SystemExit("--type must follow a name/value pair")
            if tok == "--type":
                if i + 1 >= len(items):
                    raise SystemExit("--type requires a type name")
                t = items[i + 1]
                i += 2
            else:
                t = tok.split("=", 1)[1]
                i += 1
            if t not in TYPE_COERCE:
                raise SystemExit(
                    f"unknown type {t!r}, expected one of {list(TYPE_COERCE)}"
                )
            pairs.append((*pending, t))
            pending = None
        else:
            if pending is not None:
                pairs.append((*pending, "str"))
            if i + 1 >= len(items):
                raise SystemExit(f"value missing for {tok!r}")
            pending = (tok, items[i + 1])
            i += 2
    if pending is not None:
        pairs.append((*pending, "str"))
    return pairs


def load_json_blob(spec: str, what: str = "--json") -> object:
    """Load a JSON blob from a literal string, a file, or stdin.

    Recognises:
      - '-'          -> stdin
      - '@PATH'      -> read from file at PATH
      - otherwise    -> the string itself is JSON
    """
    if spec == "-":
        raw = sys.stdin.read()
    elif spec.startswith("@"):
        path = Path(spec[1:])
        raw = path.read_text(encoding="utf-8")
    else:
        raw = spec
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"{what}: invalid JSON ({exc})")


def set_params_from_args(args) -> dict:
    """Build the Set RPC params dict from either --json or NAME VALUE pairs.

    `args` must have attributes `json_payload` and `rest`. Returns a dict
    suitable for passing as `Set` params.
    """
    if getattr(args, "json_payload", None):
        obj = load_json_blob(args.json_payload)
        if not isinstance(obj, dict):
            raise SystemExit("--json: must be a JSON object for Set")
        return obj
    pairs = parse_set_items(list(args.rest))
    if not pairs:
        raise SystemExit(
            "set: at least one name/value pair required "
            "(e.g. 'set RampEnable true --type bool')"
        )
    out: dict = {}
    for name, value, t in pairs:
        try:
            out[name] = TYPE_COERCE[t](value)
        except (ValueError, KeyError) as exc:
            raise SystemExit(f"{name}: cannot coerce {value!r} as {t} ({exc})")
    return out


def format_datetime_iso(dt: _dt.datetime) -> str:
    """Format a datetime in the SetDateTime wire format
    ('YYYY-MM-DDTHH:MM:SS.mmmZ'). Naive datetimes are treated as local."""
    if dt.tzinfo is None:
        dt = dt.astimezone()   # naive -> local-aware
    dt = dt.astimezone(_dt.timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def host_datetime_iso() -> str:
    return format_datetime_iso(_dt.datetime.now(_dt.timezone.utc))


def parse_flex_datetime(s: str) -> _dt.datetime:
    """Parse flexible date/time into a timezone-aware datetime.

    Accepts:
      - "" or "now"                   -> current UTC
      - "+1h" / "-30m" / "+7d" / "+90s"  -> relative to now
      - "1777061617" (unix seconds)   -> absolute UTC
      - "2026-04-24T12:30:00Z"        -> ISO-8601 with TZ
      - "2026-04-24T12:30:00.123"     -> ISO-8601 no TZ (assumed local)
      - "2026-04-24 12:30[:ss[.ms]]"  -> space variant
      - "2026-04-24" / "2026/04/24" / "24.04.2026"  -> midnight local
      - "12:30" / "12:30:45"          -> today at that time, local

    Raises ValueError on unrecognised input.
    """
    import re
    s = (s or "").strip()
    if not s or s.lower() == "now":
        return _dt.datetime.now(_dt.timezone.utc)

    m = re.fullmatch(r"([-+])(\d+)([smhd])", s)
    if m:
        sign, n, unit = m.groups()
        mul = {"s": 1, "m": 60, "h": 3600, "d": 86400}[unit]
        delta = _dt.timedelta(seconds=int(n) * mul)
        if sign == "-":
            delta = -delta
        return _dt.datetime.now(_dt.timezone.utc) + delta

    # Unix epoch seconds (roughly 2001..5138)
    if s.isdigit() and 10 <= len(s) <= 11:
        return _dt.datetime.fromtimestamp(int(s), tz=_dt.timezone.utc)

    # ISO-like: permit space-as-T and Z as UTC alias.
    iso_candidate = s.replace(" ", "T", 1).replace("Z", "+00:00")
    try:
        dt = _dt.datetime.fromisoformat(iso_candidate)
        if dt.tzinfo is None:
            dt = dt.astimezone()   # treat as local
        return dt.astimezone(_dt.timezone.utc)
    except ValueError:
        pass

    # Time-only HH:MM[:SS] -> today local
    for fmt in ("%H:%M:%S", "%H:%M"):
        try:
            t = _dt.datetime.strptime(s, fmt).time()
        except ValueError:
            continue
        today = _dt.date.today()
        return _dt.datetime.combine(today, t).astimezone(_dt.timezone.utc)

    # Date-only
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%d.%m.%Y", "%d-%m-%Y", "%d/%m/%Y"):
        try:
            d = _dt.datetime.strptime(s, fmt)
        except ValueError:
            continue
        return d.astimezone(_dt.timezone.utc)

    raise ValueError(f"couldn't parse {s!r} as a datetime")


__all__ = [
    "AS11_RPC_PROFILE",
    "AIRMINI_RPC_PROFILE",
    "AS11_RPC_VERSIONS",
    "AIRMINI_RPC_VERSIONS",
    "RPC_VERSION_PROFILES",
    "RPC_DEFAULT_VERSIONS",
    "RPC_VERSIONS",
    "rpc_version",
    "Transport",
    "TransportError",
    "FramingError",
    "build_request",
    "parse_response",
    "TYPE_COERCE",
    "parse_set_items",
    "load_json_blob",
    "set_params_from_args",
    "host_datetime_iso",
    "format_datetime_iso",
    "parse_flex_datetime",
]

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
    "TherapyEvents-RespiratoryEvents": {
        "event_types": {
            2: "Hypopnea", 3: "CentralApnea", 4: "ObstructiveApnea",
            5: "Apnea", 6: "Arousal",
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


def _fmt_utc_ms(value: int) -> str:
    from datetime import datetime, timezone
    try:
        return datetime.fromtimestamp(value / 1000, timezone.utc).isoformat()
    except (OverflowError, OSError, ValueError):
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


_SUMMARY_FIELDS = {
    1:  "f1_init_marker",
    2:  "PeriodStart",
    3:  "PeriodEnd",
    4:  "TimeZoneOffsetMin",
    5:  "DurationMin",
    6:  "SessionModeEntries",
    7:  "AHI (Summary-ApneaHypopneaIndex)",
    8:  "ApneaIndex",
    9:  "HypopneaIndex",
    10: "ObstructiveApneaIndex",
    11: "CentralApneaIndex",
    12: "UnknownApneaIndex",
    13: "ReraIndex",
    14: "Leak",
    15: "InspiratoryPressure",
    16: "f16_CSD",
    17: "f17_SAU",
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
    40: "ClockB",
    41: "HeartRate",
    42: "f42_AV*",
    43: "UnknownTimestamp",
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
        mode = None
        try:
            fields = proto_decode(value)
        except (ValueError, IndexError):
            continue
        for sf, sw, sv in fields:
            if sf == 1 and sw == 0:
                ts = sv
            elif sf == 2 and sw == 0:
                mode = sv
        entries.append((ts, mode))
    return entries


def _summary_session_code(mode: int | None) -> str:
    if mode is None:
        return "n/a"
    return str(mode)


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
    for key, value in stats["scalars"]:
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
    clock = _summary_scalar(stats, "ClockB")
    print(f"Summary record {index} ({len(data)}B):", file=out)
    if isinstance(start, int) and isinstance(end, int):
        print(f"  range: {_fmt_utc_ms(start)} -> {_fmt_utc_ms(end)}", file=out)
    bits = []
    if duration is not None:
        bits.append(f"duration_min={duration}")
    bits.append(f"sessions={session_count}")
    if tz_offset is not None:
        bits.append(f"tz_offset_min={tz_offset}")
    if isinstance(clock, int):
        bits.append(f"clock={_fmt_utc_ms(clock)}")
    print("  " + " ".join(bits), file=out)

    if stats["session_entries"]:
        print("  session_entries:", file=out)
        for ts, mode in stats["session_entries"]:
            when = _fmt_utc_ms(ts) if isinstance(ts, int) else "n/a"
            print(f"    {when}  code={_summary_session_code(mode)}", file=out)

    skip_scalars = {
        "f1_init_marker", "PeriodStart", "PeriodEnd",
        "TimeZoneOffsetMin", "DurationMin", "SessionCount", "ClockB",
        "UnknownTimestamp",
    }
    scalars = [(name, value) for name, value in stats["scalars"]
               if name not in skip_scalars]
    if scalars:
        print("  scalars:", file=out)
        line = "    "
        for name, value in scalars:
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
        for field, wire, value in proto_decode(data):
            if wire == 2:
                if depth < 2:
                    yield from spool_walk_events(value, depth + 1)
                elif depth == 2 and field == 1:
                    yield value
    except (ValueError, IndexError):
        pass


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
            f"f{field}/{_PROTO_WIRE.get(wire, wire)}"
            for field, wire, _value in record["extras"]
        )
        print(
            f"{idx}\t{event_type}\t{_event_name(spool_type, event_type)}\t"
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
    "rc03_spool_pretty", "event_spool_pretty",
    "print_spool_legend", "print_spool_summary", "spool_walk_events",
]

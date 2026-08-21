#!/usr/bin/env python3
"""AS11 Config Tool.

Get/Set settings, run JSON-RPC, stream/subscribe/spool data. Picks
transport from -d/--device:

    -d ble:<mac|alias>          BLE (via bleak + SRP pairing)
    -d can:<target>             CAN target (slcan, socketcan, or waveshare)
    -d tcp:<host>[:<port>]      AirCANnect TCP bridge (default port 39011)

Compat aliases:
    --addr <ble-target>         same as -d ble:<ble-target>
    -p/--port <can-target>      same as -d can:<can-target>
    $AS11_ADDR / $AS11_CAN_PORT / $AS11_AIRCANNECT env fallbacks

"""

from __future__ import annotations

import argparse
import atexit
import base64
import hashlib
import json
import logging
import math
import os
import shlex
import sys
import time
from contextlib import nullcontext
from pathlib import Path


_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_HERE / "lib"))

try:  # optional: only used to register CAN-specific CLI args
    import as11_can_transport as _can_transport  # noqa: E402
except ModuleNotFoundError as exc:  # pragma: no cover - dev setups may omit CAN support
    if exc.name == "as11_can_transport":
        _can_transport = None
    else:
        raise

try:  # optional: AirCANnect TCP bridge
    import as11_aircannect as _aircannect_transport  # noqa: E402
except ModuleNotFoundError as exc:  # pragma: no cover
    if exc.name == "as11_aircannect":
        _aircannect_transport = None
    else:
        raise

from as11_rpc import (  # noqa: E402
    Transport, TransportError, FramingError,
    load_json_blob,
    set_params_from_args,
    host_datetime_iso, parse_flex_datetime, format_datetime_iso,
)
from as11_rpc_vars import (  # noqa: E402
    VAR_GROUPS, expand_groups, resolve_group,
    SPOOL_GROUPS, SPOOL_FORMATS, SPOOL_REGISTRY,
    VAR_NAMES, VAR_SUBTREES, STREAM_EDF_ALIASES, STREAM_EDF_SAMPLE_MS,
    STREAM_GROUPS, EVENT_FAMILIES,
    REGISTRIES,
    filter_vars, print_var_pairs,
)
from as11_spool import (  # noqa: E402
    SPOOL_FRAGMENT_SIZE, SPOOL_FRAGMENT_SIZE_LIMIT,
    SPOOL_OUTPUT_FORMATS, SPOOL_OUTPUT_DEFAULT,
    SpoolError, SpoolDecodeError, spool_one_round,
    decode_spool, render_spool,
    spool_payload_first_field, detect_spool_type,
    SELECTOR_BY_SPOOL,
)


log = logging.getLogger("as11.config")


def eprint(*a, **kw):
    print(*a, file=sys.stderr, **kw)


def positive_int_arg(value: str) -> int:
    parsed = int(value, 0)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return parsed


def spool_size_arg(value: str) -> int:
    parsed = positive_int_arg(value)
    if parsed > 0x7FFFFFFF:
        raise argparse.ArgumentTypeError("must not exceed 2147483647")
    return parsed


def positive_float_arg(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed) or parsed <= 0:
        raise argparse.ArgumentTypeError("must be a positive number")
    return parsed


def spool_datetime_arg(value: str) -> str:
    try:
        return format_datetime_iso(parse_flex_datetime(value))
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def _normalize_cli_args(argv: list[str] | None) -> list[str]:
    args = list(sys.argv[1:] if argv is None else argv)
    index = 0
    while index + 1 < len(args):
        value = args[index + 1]
        relative = (
            len(value) >= 3
            and value[0] in "+-"
            and value[-1] in "smhd"
            and value[1:-1].isdigit()
        )
        if args[index] == "--from-dt" and relative:
            args[index:index + 2] = [f"--from-dt={value}"]
        index += 1
    return args


SESSION_META_COMMANDS = ("quit", "exit", "q", "help")


def session_history_path() -> Path:
    env = os.environ.get("AS11_SESSION_HISTORY")
    if env:
        return Path(env).expanduser()
    state_home = os.environ.get("XDG_STATE_HOME")
    if state_home:
        return Path(state_home).expanduser() / "airsense11" / "as11_config_history"
    return Path.home() / ".as11_config_history"


def setup_session_readline(command_names: tuple[str, ...]) -> None:
    """Enable persistent history and tab completion for an interactive session."""
    if not sys.stdin.isatty():
        return
    try:
        import readline  # type: ignore
    except ImportError:
        return

    history = session_history_path()
    try:
        history.parent.mkdir(parents=True, exist_ok=True)
        readline.read_history_file(str(history))
    except FileNotFoundError:
        pass
    except OSError:
        pass

    def save_history() -> None:
        try:
            readline.write_history_file(str(history))
        except OSError:
            pass

    atexit.register(save_history)

    try:
        readline.set_history_length(1000)
    except AttributeError:
        pass

    def completion_names(items):
        for item in items:
            if isinstance(item, str):
                yield item
            elif isinstance(item, (tuple, list)) and item and isinstance(item[0], str):
                yield item[0]

    session_commands = command_names + SESSION_META_COMMANDS
    completion_words = sorted(
        set(session_commands)
        | set(completion_names(REGISTRIES))
        | set(completion_names(VAR_NAMES))
        | {tag for _, tag in VAR_NAMES}
        | set(VAR_GROUPS)
        | set(completion_names(VAR_SUBTREES))
    )

    def completer(text: str, state: int) -> str | None:
        line = readline.get_line_buffer()
        begidx = readline.get_begidx()
        stripped = line.lstrip()
        if begidx == len(line) - len(stripped):
            matches = [word + " " for word in session_commands
                       if word.startswith(text)]
        else:
            matches = [word for word in completion_words
                       if word.startswith(text)]
        if state < len(matches):
            return matches[state]
        return None

    try:
        readline.set_completer(completer)
        readline.set_completer_delims(" \t\n")
        readline.parse_and_bind("tab: complete")
    except (AttributeError, OSError):
        pass


def normalize_ota_key_hex(text: str, *, source: str) -> str:
    clean = "".join(text.split())
    try:
        raw = bytes.fromhex(clean)
    except ValueError as exc:
        raise SystemExit(f"{source}: OTA key must be hex: {exc}") from exc
    if len(raw) != 32:
        raise SystemExit(
            f"{source}: OTA key must be exactly 32 bytes, got {len(raw)}"
        )
    return raw.hex().upper()


def load_ota_key_hex(*, key_hex: str | None, key_file: str | None) -> str:
    if key_hex and key_file:
        raise SystemExit("pass only one of OTA key hex or --key-file")
    if key_hex:
        return normalize_ota_key_hex(key_hex, source="ota-key")
    if key_file:
        data = Path(key_file).read_bytes()
        if len(data) == 32:
            return data.hex().upper()
        return normalize_ota_key_hex(
            data.decode("ascii"), source=f"--key-file {key_file}"
        )
    raise SystemExit("ota-key: pass a key, --key, --key-file, or --clear")


def find_paired_device_key(creds: dict, target: str) -> str | None:
    target_upper = target.upper()
    for addr, data in creds.items():
        if addr.upper() == target_upper:
            return addr
        if data.get("alias") == target:
            return addr
    return None


def resolve_device_spec(args: argparse.Namespace) -> str:
    """Turn --device / --addr / --port / env into a canonical spec string.

    Returns one of:
        "ble:<addr-or-alias>"
        "can:<port>"
        "tcp:<host>[:<port>]"
    """
    if getattr(args, "device", None):
        return args.device
    if getattr(args, "addr", None):
        return f"ble:{args.addr}"
    if getattr(args, "port", None):
        return f"can:{args.port}"
    if os.environ.get("AS11_ADDR"):
        return f"ble:{os.environ['AS11_ADDR']}"
    if os.environ.get("AS11_CAN_PORT"):
        return f"can:{os.environ['AS11_CAN_PORT']}"
    if os.environ.get("AS11_AIRCANNECT"):
        return f"tcp:{os.environ['AS11_AIRCANNECT']}"
    raise SystemExit(
        "no device: pass -d/--device ble:<mac|alias>, can:<port>, or "
        "tcp:<host>[:<port>]; or set AS11_ADDR / AS11_CAN_PORT / "
        "AS11_AIRCANNECT"
    )


def build_transport(args: argparse.Namespace) -> Transport:
    """Factory: parse the device spec, return a configured but not-yet-
    connected Transport. Caller is responsible for calling connect()."""
    spec = resolve_device_spec(args)

    if spec.startswith("ble:"):
        target = spec[4:]
        if not target:
            raise SystemExit("ble: spec needs MAC / UUID / alias")
        from as11_ble import BleTransport
        return BleTransport.from_args(target, args)

    if spec.startswith("can:"):
        target = spec[4:]
        if not target:
            raise SystemExit("can: spec needs adapter target (serial path or interface name)")
        if _can_transport is not None:
            return _can_transport.from_args(target, args)
        from as11_can_transport import from_args as can_transport_from_args
        return can_transport_from_args(target, args)

    if spec.startswith("tcp:"):
        target = spec[4:]
        if not target:
            raise SystemExit("tcp: spec needs host[:port]")
        if _aircannect_transport is not None:
            return _aircannect_transport.from_args(target, args)
        from as11_aircannect import from_args as aircannect_from_args
        return aircannect_from_args(target, args)

    raise SystemExit(
        f"unrecognised device spec {spec!r}; "
        "expected ble:<addr>, can:<port>, or tcp:<host>[:<port>]"
    )


def connect_transport(args: argparse.Namespace):
    borrowed = getattr(args, "_borrowed_transport", None)
    if borrowed is not None:
        return nullcontext(borrowed)
    t = build_transport(args)
    t.connect()
    return t



def call_rpc(t: Transport, args: argparse.Namespace,
             method: str, params) -> dict:
    try:
        return t.rpc(method, params, timeout=args.timeout)
    except FramingError as exc:
        eprint(f"\n{method}: framing/CRC error, device state is UNKNOWN. {exc}")
        raise


def print_response(resp: dict) -> None:
    print(json.dumps(resp, indent=2))


def normalize_var_selector(name: str) -> str:
    if len(name) == 3 and name.isascii() and name.isalnum():
        return "_" + name.upper()
    return name



def cmd_get(args: argparse.Namespace) -> int:
    if getattr(args, "list_groups", False):
        for name, members in sorted(VAR_GROUPS.items(),
                                    key=lambda kv: -len(kv[1])):
            print(f"  {name:<24s}  {len(members):3d} vars")
        return 0

    names: list[str] = []
    groups = list(args.groups or [])
    for target in args.names or []:
        group = resolve_group(target)
        if group is not None and len(group) == 3:
            groups.append(group)
        else:
            names.append(target)
    if groups:
        try:
            names.extend(expand_groups(groups))
        except ValueError as exc:
            raise SystemExit(f"get: {exc}")
    if not names:
        raise SystemExit(
            "get: at least one name or --group required "
            "(use --list-groups to see known groups)"
        )
    names = [normalize_var_selector(name) for name in names]
    seen: set[str] = set()
    unique = [name for name in names if not (name in seen or seen.add(name))]
    with connect_transport(args) as t:
        resp = call_rpc(t, args, "Get", unique)
    print_response(resp)
    return 0


def cmd_rpc(args: argparse.Namespace) -> int:
    params = None
    if args.params is not None:
        params = load_json_blob(args.params, what="--params")
    with connect_transport(args) as t:
        resp = call_rpc(t, args, args.method, params)
    print_response(resp)
    return 0


def cmd_set(args: argparse.Namespace) -> int:
    params = set_params_from_args(args)
    if args.json_payload is None:
        params = {normalize_var_selector(name): value
                  for name, value in params.items()}
    with connect_transport(args) as t:
        resp = call_rpc(t, args, "Set", params)
    print_response(resp)
    return 0


def cmd_gettime(args: argparse.Namespace) -> int:
    with connect_transport(args) as t:
        resp = call_rpc(t, args, "GetDateTime", None)
    print_response(resp)
    return 0


def cmd_settime(args: argparse.Namespace) -> int:
    if args.time:
        try:
            dt_obj = parse_flex_datetime(args.time)
        except ValueError as exc:
            raise SystemExit(f"settime: {exc}")
        stamp = format_datetime_iso(dt_obj)
    else:
        stamp = host_datetime_iso()
    params = {"dateTime": stamp}
    if args.dry_run:
        print(json.dumps(
            {"method": "SetDateTime", "params": params}, indent=2
        ))
        return 0
    with connect_transport(args) as t:
        resp = call_rpc(t, args, "SetDateTime", params)
    print_response(resp)
    return 0


def cmd_session(args: argparse.Namespace) -> int:
    """Interactive CLI using one persistent transport where possible."""
    session_parser = build_parser()
    command_names: tuple[str, ...] = ()
    for action in session_parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            command_names = tuple(action.choices)
            break
    setup_session_readline(command_names)

    t = build_transport(args)
    t.connect()
    try:
        if sys.stdin.isatty():
            print(f"AS11 session on {t.name}.")
            print("Enter any as11_config command; use `help [COMMAND]` for help.")
            print("Use `quit` or `exit` to leave.")

        while True:
            if sys.stdin.isatty():
                try:
                    line = input("as11> ")
                except (EOFError, KeyboardInterrupt):
                    print()
                    break
            else:
                line = sys.stdin.readline()
                if not line:
                    break

            line = line.strip()
            if not line or line.startswith("#"):
                continue
            try:
                tokens = shlex.split(line)
            except ValueError as exc:
                eprint(f"parse error: {exc}")
                continue
            if not tokens:
                continue

            verb = tokens[0].lower()
            if verb in {"quit", "exit", "q"}:
                break
            if verb == "help":
                if len(tokens) == 1:
                    session_parser.print_help()
                    continue
                tokens = tokens[1:] + ["--help"]

            try:
                command_args = session_parser.parse_args(
                    _normalize_cli_args(tokens)
                )
                if command_args.command == "session":
                    raise SystemExit("session: a session cannot be nested")

                explicit_device = any(
                    hasattr(command_args, name)
                    for name in ("device", "addr", "port")
                )
                merged = vars(args).copy()
                merged.update(vars(command_args))
                command_args = argparse.Namespace(**merged)
                _apply_common_defaults(command_args)

                # SubscribeEvent has no unsubscribe operation. Preserve the
                # normal CLI behavior by running it on an owned connection,
                # then restore the session connection when it ends.
                reconnect = (
                    command_args.command == "subscribe" and not explicit_device
                )
                if reconnect:
                    t.close()
                elif not explicit_device:
                    command_args._borrowed_transport = t

                try:
                    command_args.func(command_args)
                finally:
                    if reconnect:
                        t = build_transport(args)
                        t.connect()
            except TimeoutError as exc:
                eprint(f"timeout: {exc}")
            except SystemExit as exc:
                if isinstance(exc.code, str):
                    eprint(exc.code)
            except Exception as exc:
                eprint(f"error: {exc}")
    finally:
        t.close()
    return 0


def split_csv(text: str | None) -> list[str]:
    if not text:
        return []
    return [part.strip() for part in text.split(",") if part.strip()]


def unique_ordered(items: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


def event_selectors_for_label(label: str) -> list[str]:
    """Resolve one payload event label to SubscribeEvent selector names."""
    key = label.strip().lower()
    if not key:
        return []
    for selector in EVENT_FAMILIES:
        if selector.lower() == key:
            return [selector]
    out = []
    for selector, labels in EVENT_FAMILIES.items():
        if any(name.lower() == key for name in labels):
            out.append(selector)
    return out


def event_selector_rows(pattern: str = "") -> tuple[list[tuple[str, str]],
                                                  list[tuple[str, int]]]:
    """Return (label rows, selector rows) matching an event search pattern."""
    key = pattern.lower()
    label_rows: list[tuple[str, str]] = []
    selector_rows: list[tuple[str, int]] = []
    for selector, labels in EVENT_FAMILIES.items():
        selector_hit = bool(key and key in selector.lower())
        matched_labels = [label for label in labels
                          if not key or key in label.lower()]
        for label in matched_labels:
            label_rows.append((label, selector))
        if selector_hit or (not key and not matched_labels):
            selector_rows.append((selector, len(labels)))
    return label_rows, selector_rows


def print_event_lookup(pattern: str = "", *, selector: str | None = None) -> None:
    if selector:
        key = selector.lower()
        rows = [(sel, labels) for sel, labels in EVENT_FAMILIES.items()
                if key in sel.lower()]
        for sel, labels in rows:
            print(f"{sel}")
            if labels:
                for label in labels:
                    print(f"  {label}")
            else:
                print("  labels: n/a")
            print()
        return

    if not pattern:
        rows = [
            (sel, len(labels))
            for sel, labels in EVENT_FAMILIES.items()
        ]
        w0 = max(len("subscribe selector"), max(len(row[0]) for row in rows))
        print(f"{'subscribe selector':<{w0}}  labels")
        for sel, count in sorted(rows, key=lambda r: r[0].lower()):
            label_text = f"{count} labels" if count else "n/a"
            print(f"{sel:<{w0}}  {label_text}")
        return

    label_rows, selector_rows = event_selector_rows(pattern)
    if label_rows:
        w0 = max(len("event"), max(len(row[0]) for row in label_rows))
        w1 = max(len("subscribe selector"),
                 max(len(row[1]) for row in label_rows))
        print(f"{'event':<{w0}}  subscribe selector")
        for label, sel in sorted(label_rows, key=lambda r: r[0].lower()):
            print(f"{label:<{w0}}  {sel}")
    if selector_rows:
        if label_rows:
            print()
        w0 = max(len("subscribe selector"),
                 max(len(row[0]) for row in selector_rows))
        print(f"{'subscribe selector':<{w0}}  labels")
        for sel, count in sorted(selector_rows, key=lambda r: r[0].lower()):
            label_text = f"{count} labels" if count else "n/a"
            print(f"{sel:<{w0}}  {label_text}")


def expand_edf_stream_aliases(spec: str | None) -> tuple[list[str], list[int]]:
    data_ids: list[str] = []
    sample_ms: list[int] = []
    for alias in split_csv(spec):
        key = alias.upper()
        if key not in STREAM_EDF_ALIASES:
            known = ", ".join(sorted(STREAM_EDF_ALIASES))
            raise SystemExit(f"stream: unknown EDF alias {alias!r}; known: {known}")
        data_ids.extend(STREAM_EDF_ALIASES[key])
        sample_ms.append(STREAM_EDF_SAMPLE_MS[key])
    return data_ids, sample_ms


def normalize_stream_intervals(sample_ms: int, report_ms: int) -> tuple[int, int]:
    if sample_ms < 10 or sample_ms > 65000:
        raise SystemExit("stream: sample interval must be 10..65000 ms")
    if report_ms < 10 or report_ms > 300000:
        raise SystemExit("stream: report interval must be 10..300000 ms")

    norm_sample = (sample_ms // 10) * 10
    norm_report = (report_ms // 10) * 10
    if norm_sample != sample_ms:
        eprint(f"stream: sample interval rounded down to {norm_sample} ms")
    if norm_report != report_ms:
        eprint(f"stream: report interval rounded down to {norm_report} ms")

    if norm_report < norm_sample:
        raise SystemExit("stream: report interval must be at least sample interval")
    if norm_report > norm_sample * 5:
        raise SystemExit("stream: report interval must not exceed 5 * sample interval")
    return norm_sample, norm_report


def print_spool_types(pattern: str = "") -> None:
    key = pattern.lower()
    for title, group_items in SPOOL_GROUPS:
        group_match = bool(key and key in title.lower())
        hits = []
        for item in group_items:
            info = SPOOL_REGISTRY[item]
            search_terms = (
                item,
                info.get("format", ""),
                *info.get("sources", ()),
            )
            if (not key or group_match
                    or any(key in term.lower() for term in search_terms)):
                hits.append(item)
        if not hits:
            continue
        print(f"{title}:")
        width = max(len(item) for item in hits)
        for item in hits:
            fmt = SPOOL_FORMATS.get(item, "")
            print(f"  {item:<{width}}  {fmt}")
        print()


def spool_address_for(spool_type: str, from_dt: str) -> dict:
    return {spool_type: {"fromDateTime": from_dt}}


def _decode_spool_file(path: str, spool_type: str | None,
                       output_format: str | None,
                       app_version: str | None) -> int:
    try:
        with open(path, "rb") as f:
            data = f.read()
    except OSError as exc:
        raise SystemExit(f"spool: cannot read {path}: {exc}")
    if spool_type is not None and spool_type not in SPOOL_REGISTRY:
        raise SystemExit(f"spool: unknown spool type {spool_type!r}")
    if not data:
        if spool_type is None:
            raise SystemExit(f"spool: {path} is empty")
        render_spool(
            decode_spool(spool_type, data, app_version=app_version),
            output_format or SPOOL_OUTPUT_DEFAULT,
        )
        return 0

    if spool_type is None:
        best, candidates = detect_spool_type(data)
        if best is None:
            field = spool_payload_first_field(data)
            field_str = f"f{field}" if field is not None else "no protobuf field"
            raise SystemExit(
                f"spool: could not autodetect spool type ({field_str}); "
                f"pass the type before --input"
            )
        spool_type = best
        if len(candidates) > 1:
            alternatives = [item for item in candidates if item != spool_type]
            eprint(f"# autodetected: {spool_type} "
                   f"(field shared with {', '.join(alternatives)})")

    render_spool(
        decode_spool(spool_type, data, app_version=app_version),
        output_format or SPOOL_OUTPUT_DEFAULT,
    )
    return 0


def cmd_stream(args: argparse.Namespace) -> int:
    """Start a real-time data stream; emit NDJSON, one notification per line.
       On exit, calls `StartStream` with dataIds=[] to disarm.
    """
    edf_ids, edf_sample_ms = expand_edf_stream_aliases(args.edf)
    data_ids = unique_ordered(edf_ids + split_csv(args.data_ids))
    defaulting_to_edf = False
    if not data_ids:
        defaulting_to_edf = True
        data_ids = unique_ordered([
            item for alias in sorted(STREAM_EDF_ALIASES)
            for item in STREAM_EDF_ALIASES[alias]
        ])

    if len(data_ids) > 30:
        raise SystemExit("stream: firmware accepts at most 30 dataIds")

    if args.sample_ms is not None:
        sample_ms = args.sample_ms
    elif defaulting_to_edf:
        sample_ms = 10
    elif edf_sample_ms and not args.data_ids:
        sample_ms = min(edf_sample_ms)
    else:
        sample_ms = 200
    report_ms = args.report_ms if args.report_ms is not None else sample_ms * 5
    sample_ms, report_ms = normalize_stream_intervals(sample_ms, report_ms)

    params = {
        "dataIds": data_ids,
        "sampleIntervalMs": sample_ms,
        "reportIntervalMs": report_ms,
    }

    def handler(msg: dict):
        print(json.dumps(msg, separators=(",", ":")), flush=True)
        return None

    with connect_transport(args) as t:
        t.set_notification_handler(handler)
        try:
            resp = call_rpc(t, args, "StartStream", params)
            eprint(json.dumps(resp.get("result", resp)))
            t.listen_for_notifications(duration=args.duration)
        except KeyboardInterrupt:
            pass
        finally:
            try:
                stop_params = dict(params, dataIds=[])
                t.rpc("StartStream", stop_params, timeout=args.timeout)
            except Exception as exc:
                eprint(f"stream stop failed (non-fatal): {exc}")
            t.set_notification_handler(None)
    return 0


def cmd_subscribe(args: argparse.Namespace) -> int:
    """Subscribe to device events; emit NDJSON, one notification per line."""
    selector_ids = list(getattr(args, "selectors", []) or [])
    for label in split_csv(args.events):
        matches = event_selectors_for_label(label)
        if not matches:
            raise SystemExit(
                f"subscribe: no event label {label!r}; "
                f"use `known events {label}` to browse"
            )
        for selector in matches:
            eprint(f"subscribe: {label} -> {selector}")
        selector_ids.extend(matches)
    params = {"dataIds": unique_ordered(selector_ids)}

    def handler(msg: dict):
        print(json.dumps(msg, separators=(",", ":")), flush=True)
        return None

    with connect_transport(args) as t:
        t.set_notification_handler(handler)
        try:
            resp = call_rpc(t, args, "SubscribeEvent", params)
            eprint(json.dumps(resp.get("result", resp)))
            t.listen_for_notifications(duration=args.duration)
        except KeyboardInterrupt:
            pass
        finally:
            t.set_notification_handler(None)
    return 0


def cmd_spool(args: argparse.Namespace) -> int:
    """Download spool data or decode a captured payload.

    Calls StartSpool -> PullSpoolFragments, optionally iterating rounds
    to follow `SPOOL_COMPLETE_MORE_DATA_PENDING` continuation tokens.
    Writes raw binary to --output (if given) and emits decoded data or a
    Base64 envelope to stdout.
    """
    if getattr(args, "list_types", False):
        print_spool_types()
        return 0
    if args.input:
        if args.no_decode:
            raise SystemExit("spool: --no-decode cannot be used with --input")
        return _decode_spool_file(
            args.input, args.spool_type, args.format, args.app_version
        )
    if not getattr(args, "spool_type", None):
        raise SystemExit(
            "spool: spool_type required (or use --input/--list-types)"
        )
    if args.no_decode and args.format is not None:
        raise SystemExit("spool: --format cannot be used with --no-decode")
    spool_type = args.spool_type
    from_dt = args.from_dt or "2000-01-01T00:00:00.000Z"
    spool_address = spool_address_for(spool_type, from_dt)

    all_data = bytearray()
    total_fragments = 0
    round_num = 0
    final_status = ""
    last_next = None
    app_version = args.app_version
    transfer_verbose = args.verbose or args.debug

    with connect_transport(args) as t:
        if (not args.no_decode and spool_type in SELECTOR_BY_SPOOL
                and app_version is None):
            try:
                version_resp = call_rpc(
                    t, args, "Get", ["ApplicationIdentifier"]
                )
                app_version = version_resp.get("result", {}).get(
                    "ApplicationIdentifier"
                )
                if app_version:
                    eprint(f"# diagnostic APPX: {app_version}")
                else:
                    eprint("# warning: ApplicationIdentifier unavailable; "
                           "comparing all bundled diagnostic manifests")
            except Exception as exc:
                eprint("# warning: could not query ApplicationIdentifier; "
                       f"comparing all bundled diagnostic manifests: {exc}")
        while True:
            round_num += 1
            if round_num > 1 and transfer_verbose:
                eprint(f"--- round {round_num} (continuing from nextSpoolAddress) ---")
            data, status, nxt, n_frags = spool_one_round(
                t, spool_address, args.max_size,
                fragment_timeout=args.fragment_timeout,
                fragment_max=args.fragment_max,
                verbose=transfer_verbose,
            )
            all_data.extend(data)
            total_fragments += n_frags
            final_status = status
            last_next = nxt
            if args.no_follow:
                break
            if status != "SPOOL_COMPLETE_MORE_DATA_PENDING" or not nxt:
                break
            if args.max_rounds is not None and round_num >= args.max_rounds:
                eprint(f"  stopping: hit --max-rounds {args.max_rounds}")
                break
            spool_address = nxt

    data = bytes(all_data)

    if args.output:
        with open(args.output, "wb") as f:
            f.write(data)
        eprint(f"Saved {len(data)} bytes to {args.output} "
               f"({total_fragments} fragments, {round_num} rounds, "
               f"status={final_status})")
        if last_next and final_status == "SPOOL_COMPLETE_MORE_DATA_PENDING":
            eprint(f"  nextSpoolAddress: {json.dumps(last_next)}")

    if not args.no_decode:
        render_spool(
            decode_spool(spool_type, data, app_version=app_version),
            args.format or SPOOL_OUTPUT_DEFAULT,
        )
        if last_next and final_status == "SPOOL_COMPLETE_MORE_DATA_PENDING":
            eprint(f"\n# status={final_status}")
            eprint(f"# nextSpoolAddress: {json.dumps(last_next)}")
        return 0

    if args.output:
        return 0

    out = {
        "spoolType": spool_type,
        "fromDateTime": from_dt,
        "status": final_status,
        "rounds": round_num,
        "dataBase64": base64.b64encode(data).decode(),
        "dataLength": len(data),
        "fragments": total_fragments,
        "sha256": hashlib.sha256(data).hexdigest().upper(),
    }
    if last_next and final_status == "SPOOL_COMPLETE_MORE_DATA_PENDING":
        out["nextSpoolAddress"] = last_next
    print(json.dumps(out, indent=2))
    return 0



def cmd_known(args: argparse.Namespace) -> int:
    """List names the firmware RPC surface accepts. Pure offline, no device.

    `known`               list registries (vars, streams, events, spools, ...)
    `known <reg> [pat]`   list one registry, optionally filtered
    `known groups [name]` list groups or members of one group
    `known vars <pat>`    filter known name/tag pairs by mode/topic/substring
    """
    action = args.known_action
    if not action:
        for name, (_, desc) in REGISTRIES.items():
            print(f"  {name:<8}  {desc}")
        print()
        print("  hint: `known groups <group>` lists members of one group")
        print("  hint: `known subtrees` lists non-DataItem Get targets "
              "(SettingProfiles, CpapProfile, ...)")
        return 0

    pat = args.pattern or ""

    # vars has rich filtering and tabular output
    if action == "vars":
        pairs = filter_vars(pat) if pat else list(VAR_NAMES)
        print_var_pairs(pairs)

        if pat:
            key = pat.lower()
            sub_hits = [s for s in VAR_SUBTREES if key in s.lower()]
            if sub_hits:
                if pairs:
                    print()
                width = max(len(n) for n in sub_hits)
                for name in sorted(sub_hits, key=str.lower):
                    print(f"{name:<{width}}  ~subtree")
        return 0

    if action == "groups":
        if not pat:
            for name, members in sorted(VAR_GROUPS.items(), key=lambda item: item[0].lower()):
                print(f"  {name:<24} ({len(members)} vars)")
            return 0

        canon = resolve_group(pat)
        if canon is None:
            known = ", ".join(sorted(VAR_GROUPS))
            raise SystemExit(f"known groups: unknown group {pat!r}; known: {known}")
        members = VAR_GROUPS[canon]
        tag_names = {tag: name for name, tag in VAR_NAMES}
        display = [member[1:] if member.startswith("_") else member
                   for member in members]
        width = max(len(member) for member in display)
        print(f"  {canon}  ({len(members)} vars)")
        for member, shown in zip(members, display):
            long_name = tag_names.get(shown) if member.startswith("_") else None
            suffix = f"  {long_name}" if long_name else ""
            print(f"    {shown:<{width}}{suffix}")
        return 0

    if action == "streams":
        key = pat.lower()
        aliases = [alias.upper().removesuffix(".EDF")
                   for alias in split_csv(pat)]
        if aliases and all(alias in STREAM_EDF_ALIASES for alias in aliases):
            for alias in aliases:
                print(f"EDF {alias} data IDs:")
                for item in STREAM_EDF_ALIASES[alias]:
                    print(f"  {item}")
                print()
            return 0

        for title, group_items in STREAM_GROUPS:
            hits = [item for item in group_items
                    if not key or key in item.lower()]
            if not hits:
                continue
            print(f"{title}:")
            for item in hits:
                print(f"  {item}")
            print()
        return 0

    if action == "spools":
        print_spool_types(pat)
        return 0

    if action == "events":
        print_event_lookup(pat, selector=getattr(args, "selector", None))
        return 0

    if action not in REGISTRIES:
        raise SystemExit(f"known: unknown registry {action!r}; "
                         f"choose from {list(REGISTRIES)}")
    items, _ = REGISTRIES[action]
    key = pat.lower()
    for item in sorted(items):
        if not key or key in item.lower():
            print(item)
    return 0


def cmd_devices(args: argparse.Namespace) -> int:
    """BLE device management. Uses lib/as11_ble directly."""
    import asyncio
    from as11_ble import (
        As11Connection, load_all_credentials, save_all_credentials,
        save_credentials, load_credentials, resolve_addr,
    )

    action = getattr(args, "devices_action", None) or "list"

    if action == "scan":
        async def _scan():
            print(f"Scanning for AS11 devices ({args.timeout:.0f}s)...")
            devices = await As11Connection.scan(timeout=args.timeout)
            if not devices:
                print("No devices found.")
                return
            for addr, name, rssi in sorted(devices, key=lambda x: -x[2]):
                print(f"  {addr:<20}  rssi={rssi:>4}  {name}")
        asyncio.run(_scan())
        return 0

    if action == "list":
        creds = load_all_credentials()
        if not creds:
            print("No paired devices.")
            return 0
        print(f"{'address':<20}  {'alias':<16}  {'clientId':<12}  {'otaKey':<6}")
        print(f"{'-'*20:<20}  {'-'*16:<16}  {'-'*12:<12}  {'-'*6:<6}")
        for addr, data in sorted(creds.items()):
            alias = data.get("alias", "") or ""
            cid = (data.get("clientId", "") or "")[:12]
            ota = "yes" if data.get("otaKey") else ""
            print(f"{addr:<20}  {alias:<16}  {cid:<12}  {ota:<6}")
        return 0

    if action == "pair":
        addr = resolve_addr(args.target)
        async def _pair():
            conn = As11Connection(debug=args.debug)
            try:
                await conn.connect(addr)
                creds = load_credentials(addr)
                new = await conn.pair(passkey=getattr(args, "passkey", None))
                creds.update(new)
                save_credentials(addr, creds)
                print(f"Paired with {addr}. clientId={new.get('clientId', '')}")
            finally:
                await conn.disconnect()
        asyncio.run(_pair())
        return 0

    if action == "alias":
        target = args.target
        new_alias = args.name
        creds = load_all_credentials()
        # Resolve target: MAC, UUID, or existing alias
        key = find_paired_device_key(creds, target)
        if key is None:
            raise SystemExit(
                f"alias: {target!r} not found among paired devices"
            )
        # clear any existing use of new_alias
        for addr in creds:
            if creds[addr].get("alias") == new_alias:
                creds[addr].pop("alias", None)
        creds[key]["alias"] = new_alias
        save_all_credentials(creds)
        print(f"alias {new_alias} -> {key}")
        return 0

    if action == "unalias":
        name = args.name
        creds = load_all_credentials()
        removed = False
        for addr, data in creds.items():
            if data.get("alias") == name:
                data.pop("alias", None)
                removed = True
        if not removed:
            raise SystemExit(f"unalias: no alias named {name!r}")
        save_all_credentials(creds)
        print(f"removed alias {name}")
        return 0

    if action == "ota-key":
        target = args.target
        creds = load_all_credentials()
        key = find_paired_device_key(creds, target)
        if key is None:
            raise SystemExit(
                f"ota-key: {target!r} not found among paired devices"
            )

        if args.clear:
            if args.key or args.key_hex or args.key_file:
                raise SystemExit("ota-key: pass --clear without a key")
            removed = creds[key].pop("otaKey", None) is not None
            save_all_credentials(creds)
            print(("removed" if removed else "no") + f" OTA key for {target}")
            return 0

        if args.key and args.key_hex:
            raise SystemExit("ota-key: pass only one of positional key or --key")

        key_hex = args.key_hex or args.key

        if not key_hex and not args.key_file:
            state = "configured" if creds[key].get("otaKey") else "not configured"
            print(f"OTA key for {target}: {state}")
            return 0

        creds[key]["otaKey"] = load_ota_key_hex(
            key_hex=key_hex, key_file=args.key_file
        )
        save_all_credentials(creds)
        print(f"stored OTA key for {target}")
        return 0

    raise SystemExit(f"unknown devices action: {action!r}")



def add_logging_args(p: argparse.ArgumentParser) -> None:
    suppr = argparse.SUPPRESS
    p.add_argument("--debug", action="store_true", default=suppr,
                   help="verbose packet logging")
    p.add_argument("-v", "--verbose", action="store_true", default=suppr,
                   help="info-level logging")


def build_logging_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(add_help=False)
    add_logging_args(parser)
    return parser


def build_common_parser(*, show_transport_help: bool) -> argparse.ArgumentParser:
    SUPPR = argparse.SUPPRESS
    common = argparse.ArgumentParser(add_help=False)
    g = common.add_argument_group("device selection")
    g.add_argument(
        "-d", "--device", default=SUPPR,
        help=("device spec: ble:<mac|alias>, can:<port>, tcp:<host:port>"
              if show_transport_help else SUPPR)
    )
    g.add_argument(
        "--addr", default=SUPPR,
        help=("BLE MAC/UUID/alias (shortcut for -d ble:<addr>; "
              "env: AS11_ADDR)" if show_transport_help else SUPPR)
    )
    g.add_argument(
        "-p", "--port", default=SUPPR,
        help=("CAN target (shortcut for -d can:<target>; env: AS11_CAN_PORT)"
              if show_transport_help else SUPPR)
    )
    add_logging_args(common)
    if _can_transport is not None:
        _can_transport.add_args(common, show_help=show_transport_help)
    if _aircannect_transport is not None:
        _aircannect_transport.add_args(common)
    return common


def _apply_common_defaults(args: argparse.Namespace) -> None:
    for name, default in (
        ("device", None),
        ("addr", None),
        ("port", None),
        ("debug", False),
        ("verbose", False),
    ):
        if not hasattr(args, name):
            setattr(args, name, default)


def add_rpc_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--timeout", type=float, default=5.0,
                   help="RPC response timeout (seconds)")


def build_parser() -> argparse.ArgumentParser:
    common = build_common_parser(show_transport_help=True)
    command_common = build_common_parser(show_transport_help=False)
    logging_common = build_logging_parser()
    raw_fmt = argparse.RawDescriptionHelpFormatter

    p = argparse.ArgumentParser(
        description="Air11 configuration, RPC, and data access tool.",
        parents=[common],
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    sub = p.add_subparsers(dest="command", required=True)

    g = sub.add_parser(
        "get", parents=[command_common],
        help="read one or more config variables (Get RPC)",
        epilog="examples:\n"
               "  get SerialNumber\n"
               "  get MOP GOM TOM\n"
               "  get BGL\n"
               "  get --group DeviceConfiguration\n"
               "  get --group TherapyProfile --group FeatureProfiles\n"
               "  get SerialNumber --group Network\n",
        formatter_class=raw_fmt,
    )
    add_rpc_args(g)
    g.add_argument("names", nargs="*",
                   help="variable names or three-character CONF groups")
    g.add_argument("--group", "-g", dest="groups", action="append",
                   default=[], metavar="NAME",
                   help="expand to all vars in a group; repeat for multiple")
    g.add_argument("--list-groups", action="store_true",
                   help="list known groups and exit (no device needed)")
    g.set_defaults(func=cmd_get)

    r = sub.add_parser(
        "rpc", parents=[command_common],
        help="call an arbitrary JSON-RPC method",
        epilog="examples:\n"
               "  rpc --method GetVersion\n"
               "  rpc --method Get --params '[\"SerialNumber\"]'\n"
               "  rpc --method Set --params '{\"SetPressure\":10}'\n"
               "  rpc --method GetDateTime --params -       # JSON from stdin\n"
               "  rpc --method Set --params @params.json",
        formatter_class=raw_fmt,
    )
    add_rpc_args(r)
    r.add_argument("--method", required=True, help="RPC method name")
    r.add_argument("--params", default=None,
                   help="JSON params (literal, '-' stdin, or '@PATH')")
    r.set_defaults(func=cmd_rpc)

    st = sub.add_parser(
        "set", parents=[command_common],
        help="write one or more settings (Set RPC)",
        epilog="values default to string unless --type follows the pair.\n"
               "types: str (default), int, float, bool, json.\n\n"
               "examples:\n"
               "  set TherapyMode AutoSet\n"
               "  set MOP AutoSetProfile\n"
               "  set SetPressure 10 --type int Mode AutoSet\n"
               "  set RampEnable true --type bool\n"
               "  set --json '{\"SetPressure\":10}'\n"
               "  set --json -                      # JSON from stdin\n"
               "  set --json @params.json           # JSON from file",
        formatter_class=raw_fmt,
    )
    add_rpc_args(st)
    st.add_argument("--json", dest="json_payload", default=None,
                    help="params object as JSON literal, '-' stdin, or '@PATH'")
    st.add_argument("rest", nargs=argparse.REMAINDER,
                    help="NAME VALUE [--type T] [NAME2 VALUE2 [--type T2]] ...")
    st.set_defaults(func=cmd_set)

    gt = sub.add_parser(
        "gettime", parents=[command_common],
        help="GetDateTime",
    )
    add_rpc_args(gt)
    gt.set_defaults(func=cmd_gettime)

    dt = sub.add_parser(
        "settime", parents=[command_common],
        help="SetDateTime (default: host UTC now)",
        epilog="TIME (optional) accepts:\n"
               "  (empty) / now                  host UTC now\n"
               "  2026-04-24T12:30:00Z           explicit ISO-8601\n"
               "  2026-04-24T12:30:00            ISO, no TZ (local)\n"
               "  2026-04-24 12:30:00            space variant\n"
               "  2026-04-24                     midnight local\n"
               "  12:30 / 12:30:45               today at that time, local\n"
               "  +1h / -30m / +7d / +90s        relative to now\n"
               "  1777061617                     unix epoch (seconds)\n"
               "\nexamples:\n"
               "  settime\n"
               "  settime 2026-01-01T00:00:00Z\n"
               "  settime +1h\n"
               "  settime 12:30 --dry-run",
        formatter_class=raw_fmt,
    )
    add_rpc_args(dt)
    dt.add_argument("time", nargs="?", default=None,
                    help="flexible date/time (see below); default is host UTC now")
    dt.add_argument("--dry-run", action="store_true",
                    help="print the payload without transmitting")
    dt.set_defaults(func=cmd_settime)

    s = sub.add_parser("session", parents=[command_common],
                       help="interactive REPL, keeps the transport open")
    add_rpc_args(s)
    s.set_defaults(func=cmd_session)

    stream = sub.add_parser(
        "stream", parents=[command_common],
        help="start real-time data stream (NDJSON to stdout)",
        epilog="examples:\n"
               "  stream\n"
               "  stream --data-ids Leak-50hz,RespiratoryRate-50hz\n"
               "  stream --edf BRP\n"
               "  stream --edf BRP,PLD --sample-ms 40\n"
               "  stream --sample-ms 100 --report-ms 500\n"
               "  stream --duration 60                 # stop after 60s",
        formatter_class=raw_fmt,
    )
    add_rpc_args(stream)
    stream.add_argument("--data-ids", default=None,
                        help="comma-separated data IDs to stream "
                             "(default: all EDF aliases)")
    stream.add_argument("--edf", default=None,
                        help="comma-separated EDF aliases to stream "
                             "(BRP, PLD, SA2)")
    stream.add_argument("--sample-ms", type=int, default=None,
                        help="sample interval ms (default: 10 for plain "
                             "stream, alias natural period for --edf, or 200)")
    stream.add_argument("--report-ms", type=int, default=None,
                        help="report interval ms (default: 5 * sample)")
    stream.add_argument("--duration", type=float, default=None,
                        help="stop after N seconds (default: until Ctrl-C)")
    stream.set_defaults(func=cmd_stream)

    sub_p = sub.add_parser(
        "subscribe", parents=[command_common],
        help="subscribe to events or DataItem changes (NDJSON to stdout)",
    )
    add_rpc_args(sub_p)
    sub_p.add_argument("selectors", nargs="*",
                       help="event-family selectors or DataItem names")
    sub_p.add_argument("--events", "--event", default=None,
                       help="comma-separated payload event labels to resolve "
                            "to SubscribeEvent selectors")
    sub_p.add_argument("--duration", type=float, default=None,
                       help="stop after N seconds (default: until Ctrl-C)")
    sub_p.set_defaults(func=cmd_subscribe)

    sp = sub.add_parser(
        "spool", parents=[command_common],
        help="download or decode spool data",
        epilog="examples:\n"
               "  spool Summary\n"
               "  spool TherapyEvents-RespiratoryEvents\n"
               "  spool Summary --from-dt 2026-08-01 "
               "-o /tmp/summary.bin\n"
               "  spool --input /tmp/summary.bin\n"
               "  spool Summary --input /tmp/summary.bin\n"
               "  spool --list-types",
        formatter_class=raw_fmt,
    )
    add_rpc_args(sp)
    sp.add_argument("spool_type", nargs="?",
                    help="spool type; optional with --input (see --list-types)")
    sp.add_argument("--list-types", action="store_true",
                    help="print known spool types and exit")
    sp.add_argument(
        "--from-dt", type=spool_datetime_arg, default=None,
        help="earliest record time; accepts ISO 8601, a local date such as "
             "2026-08-01, or a relative value such as -7d; default: all",
    )
    sp.add_argument("--max-size", type=spool_size_arg, default=4096,
                    help="maxSpoolSize per round")
    sp.add_argument("--max-rounds", type=positive_int_arg, default=None,
                    help="optional cap on continuation rounds; default: unlimited")
    sp.add_argument("--no-follow", action="store_true",
                    help="stop after first round; do not follow continuations")
    sp.add_argument("--fragment-timeout", type=positive_float_arg,
                    default=30.0,
                    help="seconds to wait for all fragments of one round")
    sp.add_argument("--fragment-max", type=positive_int_arg,
                    default=SPOOL_FRAGMENT_SIZE,
                    help="maxFragmentSize passed to PullSpoolFragments "
                         f"(firmware caps it at {SPOOL_FRAGMENT_SIZE_LIMIT})")
    sp.add_argument("--no-decode", action="store_true",
                    help="return the raw payload as a Base64 JSON envelope")
    sp.add_argument("--format", choices=SPOOL_OUTPUT_FORMATS, default=None,
                    help="decoded output format; default: "
                         f"{SPOOL_OUTPUT_DEFAULT}")
    sp.add_argument("--app-version", default=None,
                    help="APPX version for diagnostic error decoding; queried "
                         "for live downloads when omitted")
    spool_file = sp.add_mutually_exclusive_group()
    spool_file.add_argument(
        "-i", "--input", default=None,
        help="decode a captured spool payload without contacting a device",
    )
    spool_file.add_argument("-o", "--output", default=None,
                            help="write downloaded raw payload to this file")
    sp.set_defaults(func=cmd_spool)

    kn = sub.add_parser(
        "known", parents=[logging_common],
        help="show known var/stream/event/spool names (offline, no device)",
        epilog="examples:\n"
               "  known                      list registries\n"
               "  known vars                 list every known variable\n"
               "  known groups               list variable groups\n"
               "  known groups HST           list members of one group\n"
               "  known subtrees             named non-DataItem Get targets\n"
               "  known vars autoset         filter by therapy-mode prefix\n"
               "  known vars cellular        filter by topic keyword\n"
               "  known vars Pressure        substring filter\n"
               "  known streams              valid `stream --data-ids`\n"
               "  known streams BRP          data IDs behind an EDF stream alias\n"
               "  known edf                  valid `stream --edf` aliases\n"
               "  known events PressureStart event label -> selector lookup\n"
               "  known events --selector SystemActivity list selector labels\n"
               "  known spools               valid `spool` types",
        formatter_class=raw_fmt,
    )
    kn.add_argument("known_action", nargs="?", choices=list(REGISTRIES),
                    help="registry to list")
    kn.add_argument("pattern", nargs="?", default=None,
                    help="optional filter or sub-action")
    kn.add_argument("--selector", default=None,
                    help="for known events: list labels under selectors "
                         "matching this text")
    kn.set_defaults(func=cmd_known)

    dev = sub.add_parser(
        "devices", parents=[logging_common],
        help="BLE device management (scan/pair/list/alias/unalias)",
    )
    dev_sub = dev.add_subparsers(dest="devices_action")

    dev_scan = dev_sub.add_parser("scan", help="scan for AS11 BLE devices")
    dev_scan.add_argument("--timeout", type=float, default=10.0)

    dev_sub.add_parser("list", help="list paired devices (default)")

    dev_pair = dev_sub.add_parser("pair", help="pair with a BLE device")
    dev_pair.add_argument("target", help="BLE MAC/UUID/alias")
    dev_pair.add_argument("--passkey", default=None,
                          help="4-digit passkey shown on the device screen "
                               "(prompted if omitted)")

    dev_alias = dev_sub.add_parser("alias", help="assign an alias")
    dev_alias.add_argument("target", help="MAC/UUID/existing alias")
    dev_alias.add_argument("name", help="new alias")

    dev_key = dev_sub.add_parser(
        "ota-key",
        help="store/clear default OTA key for a paired BLE alias/device",
    )
    dev_key.add_argument("target", help="MAC/UUID/existing alias")
    dev_key.add_argument("key", nargs="?",
                         help="OTA key as 64 hex chars")
    dev_key.add_argument("--key", dest="key_hex", metavar="HEX32",
                         help="OTA key as 64 hex chars")
    dev_key.add_argument("--key-file", metavar="PATH",
                         help="OTA key as a 32-byte binary file or hex text")
    dev_key.add_argument("--clear", action="store_true",
                         help="remove stored OTA key")

    dev_unalias = dev_sub.add_parser("unalias", help="remove an alias")
    dev_unalias.add_argument("name", help="alias to remove")

    dev.set_defaults(func=cmd_devices)

    return p


def _configure_logging(args: argparse.Namespace) -> None:
    if getattr(args, "debug", False):
        level = logging.DEBUG
    elif getattr(args, "verbose", False):
        level = logging.INFO
    else:
        level = logging.WARNING
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(_normalize_cli_args(argv))
    _apply_common_defaults(args)
    _configure_logging(args)
    return args.func(args)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\ninterrupted.", file=sys.stderr)
        raise SystemExit(130)
    except SystemExit:
        raise
    except argparse.ArgumentTypeError as exc:
        print(f"\nerror: {exc}", file=sys.stderr)
        raise SystemExit(2)
    except TimeoutError as exc:
        print(f"\ntimeout: {exc}", file=sys.stderr)
        raise SystemExit(1)
    except TransportError as exc:
        print(f"\ntransport error: {exc}", file=sys.stderr)
        raise SystemExit(1)
    except RuntimeError as exc:
        if str(exc).startswith("RPC error "):
            print(f"\n{exc}", file=sys.stderr)
            raise SystemExit(1)
        raise
    except SpoolError as exc:
        print(f"\nspool error: {exc.message}", file=sys.stderr)
        raise SystemExit(1)
    except SpoolDecodeError as exc:
        print(f"\nspool decode error: {exc}", file=sys.stderr)
        raise SystemExit(1)
    except Exception as exc:
        log.exception("fatal: %s", exc)
        raise SystemExit(1)

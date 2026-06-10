#!/usr/bin/env python3
"""edf_capture_data.py — BLE capture for AirSense 11 therapy sessions.

Records a session's raw BLE traffic into a RAW folder that ``edf_write.py``
later converts to CPAP-format SD-card EDF files (offline, re-runnable).

This script uses bleak directly (no proxy) and the ``BleTransport`` sync
wrapper from ``as11_ble``.  It is the upstream-blessed version of
``proxy/capture_data.py``.

Usage::

    python3 edf_capture_data.py <ADDR> --outdir sd_card
    python3 edf_write.py sd_card/RAW/<id> --outdir export_out

If the device is not yet paired, run the pairing helper first::

    python3 as11_config.py devices pair <ADDR>
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_HERE / "lib"))

from as11_ble import BleTransport, load_all_credentials, resolve_addr
from as11_spool import spool_one_round, SpoolError

# --------------------------------------------------------------------------- #
# Stream configuration (the BLE optimisation lives here)
# --------------------------------------------------------------------------- #

BRP_STREAMS = ["PatientFlow-100hz", "MaskPressure-100hz"]
PLD_STREAMS = [
    "MaskPressure-TwoSecond", "InspiratoryPressure-TwoSecond",
    "ExpiratoryPressure-TwoSecond", "Leak-50hz", "RespiratoryRate-50hz",
    "TidalVolume-50hz", "MinuteVentilation-50hz", "SnoreIndex-50hz",
    "FlowLimitation-50hz",
]
SA2_STREAMS = ["HeartRate", "SpO2"]

ALL_STREAMS = BRP_STREAMS + PLD_STREAMS + SA2_STREAMS

GROUPS = {
    "BRP": (BRP_STREAMS, 40, 200),     # 25 Hz
    "PLD": (PLD_STREAMS, 2000, 2000),  # 0.5 Hz
    "SA2": (SA2_STREAMS, 1000, 1000),  # 1 Hz
}

EVENT_SELECTORS = ["TherapyEvents-RespiratoryEvents", "UsageEvents-TherapyStatusEvents"]

QUERY_VARS = [
    "UniversalIdentifier", "SerialNumber", "ProductCode", "ProductName",
    "ProductGeographicIdentifier", "HardwareIdentifier", "BootloaderIdentifier",
    "ApplicationIdentifier", "ConfigurationIdentifier", "PlatformIdentifier",
    "VariantIdentifier", "RegionIdentifier", "ProfileVariantIdentifier",
    "DataVersionIdentifier", "DataModelVersionIdentifier",
]

PROBE_SPOOL_TYPES = [
    "Waveform", "Waveforms", "Flow", "PatientFlow", "HighResolution",
    "DetailedTherapy", "TherapyData", "BRP", "PLD", "Detailed",
]


# --------------------------------------------------------------------------- #
# Raw capture sink
# --------------------------------------------------------------------------- #

class RawCapture:
    """Writes a RAW/<id> folder consumable by edf_write.py."""

    def __init__(self, outdir: str):
        self.start_time = datetime.now(timezone.utc)
        self.session_id = self.start_time.strftime("%Y%m%d%H%M%S")
        self.raw_dir = Path(outdir) / "RAW" / self.session_id
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        self._fp = open(self.raw_dir / "notifications.jsonl", "w")

        self.therapy_stopped = False
        self.stream_active = False
        self.last_packet_time = time.time()
        self.therapy_start_ms = None
        self.seen_streams: dict[str, int] = {}
        self.n_stream_packets = 0
        self.n_events = 0

    def on_notify(self, obj):
        self._dump(obj)
        method = obj.get("method", "")
        params = obj.get("params", {}) if isinstance(obj.get("params"), dict) else {}
        if method == "StreamData":
            self.stream_active = True
            self.last_packet_time = time.time()
            self.n_stream_packets += 1
            for item in params.get("data", []):
                if isinstance(item, dict):
                    for sid in item:
                        self.seen_streams[sid] = self.seen_streams.get(sid, 0) + 1
        elif method == "EventNotification":
            self.n_events += 1
            self._handle_event(params)

    def _handle_event(self, params):
        if params.get("dataId") != "UsageEvents-TherapyStatusEvents":
            return
        for ev in params.get("events", []):
            lbl = ev.get("label") or ev.get("event") or ""
            if lbl == "TherapyStart" and self.therapy_start_ms is None:
                ts = ev.get("timestamp") or _iso_ms(ev.get("reportTime", ""))
                self.therapy_start_ms = ts
                print("  [event] TherapyStart")
            elif lbl == "TherapyStop":
                print("  [event] TherapyStop")
                self.therapy_stopped = True

    def _dump(self, obj):
        try:
            self._fp.write(json.dumps(
                {"_recv_ms": int(time.time() * 1000), "msg": obj},
                separators=(",", ":")
            ) + "\n")
            self._fp.flush()
        except Exception as exc:
            print(f"  raw dump failed: {exc}", file=sys.stderr)

    def save_json(self, name, obj):
        (self.raw_dir / name).write_text(json.dumps(obj, indent=2))

    def save_bytes(self, name, data: bytes):
        (self.raw_dir / name).write_bytes(data)
        print(f"  saved {name} ({len(data)} bytes)")

    def close(self):
        try:
            self._fp.close()
        except Exception:
            pass


def _iso_ms(s: str) -> int | None:
    if not s:
        return None
    try:
        return int(datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp() * 1000)
    except Exception:
        return None


# --------------------------------------------------------------------------- #
# Spool helpers
# --------------------------------------------------------------------------- #

def pull_spool(transport, spool_type: str, from_dt: str, max_size: int = 5_000_000) -> bytes:
    """Multi-round spool pull using the transport-agnostic ``spool_one_round``."""
    all_data = bytearray()
    spool_address = {spool_type: {"fromDateTime": from_dt}}
    rounds = 0
    while True:
        try:
            data, status, nxt, frags = spool_one_round(
                transport, spool_address, max_size,
                fragment_timeout=30.0, fragment_max=2808, verbose=False,
            )
        except SpoolError as exc:
            print(f"  StartSpool refused for '{spool_type}': {exc.message}", file=sys.stderr)
            break
        all_data.extend(data)
        if status != "SPOOL_COMPLETE_MORE_DATA_PENDING" or not nxt:
            break
        rounds += 1
        if rounds >= 20:
            print(f"  Warning: hit max rounds for {spool_type}", file=sys.stderr)
            break
        spool_address = nxt
    return bytes(all_data)


def probe_spools(transport, cap: RawCapture):
    """Best-effort probe for high-resolution history spools."""
    print("Probing for high-resolution history spools (best-effort)...")
    found = {}
    for stype in PROBE_SPOOL_TYPES:
        try:
            data = pull_spool(transport, stype, "2000-01-01T00:00:00.000Z", max_size=200_000)
            if data:
                found[stype] = len(data)
                cap.save_bytes(f"probe_{stype}.spool", data)
                print(f"  [HIT] spool '{stype}' -> {len(data)} bytes")
        except Exception as exc:
            print(f"  [miss] '{stype}': {str(exc)[:80]}")
    if not found:
        print("  no additional spool types responded.")
    return found


# --------------------------------------------------------------------------- #
# Streaming control
# --------------------------------------------------------------------------- #

def start_single(transport, rate_ms: int):
    print(f"Starting SINGLE stream: {len(ALL_STREAMS)} signals @ {rate_ms} ms "
          f"({1000 / rate_ms:.0f} Hz, ~{len(ALL_STREAMS) * 1000 // rate_ms} samples/s)")
    transport.rpc("StartStream", {
        "dataIds": ALL_STREAMS,
        "sampleIntervalMs": rate_ms,
        "reportIntervalMs": max(rate_ms * 5, 100),
    }, encrypted=True)


def start_grouped(transport):
    print("Starting GROUPED streams (experimental, per-group native rates):")
    for name, (ids, s_ms, r_ms) in GROUPS.items():
        print(f"  {name}: {len(ids)} signals @ {s_ms} ms")
        transport.rpc("StartStream", {
            "dataIds": ids,
            "sampleIntervalMs": s_ms,
            "reportIntervalMs": r_ms,
        }, encrypted=True)
        time.sleep(0.2)


def detect_grouped_ok(cap: RawCapture, timeout: float = 6.0) -> bool:
    need = set(ALL_STREAMS)
    deadline = time.time() + timeout
    while time.time() < deadline:
        if need.issubset(cap.seen_streams.keys()):
            return True
        time.sleep(0.5)
    missing = need - set(cap.seen_streams.keys())
    if missing:
        print(f"  grouped-mode check: missing streams after {timeout:.0f}s: {sorted(missing)}")
    return not missing


def stop_stream(transport):
    try:
        transport.rpc("StartStream", {"dataIds": [], "sampleIntervalMs": 40,
                                        "reportIntervalMs": 200}, encrypted=True)
    except Exception:
        pass


# --------------------------------------------------------------------------- #
# Main capture flow
# --------------------------------------------------------------------------- #

def run(addr: str, outdir: str, mode: str, rate_ms: int,
        do_probe: bool, timeout_sec: float):
    resolved = resolve_addr(addr)
    cap = RawCapture(outdir)
    print(f"RAW capture dir: {cap.raw_dir}")
    print(f"Connecting to {resolved} ...")

    transport = BleTransport(resolved)
    transport.connect()
    try:
        # --- device identity + settings + baseline summary -------------- #
        print("Fetching device vars ...")
        res = transport.rpc("Get", QUERY_VARS, encrypted=True)
        cap.save_json("get_vars.json", res.get("result", {}))
        try:
            rs = transport.rpc("Get", ["SettingProfiles"], encrypted=True)
            cap.save_json("get_settings.json", rs.get("result", {}).get("SettingProfiles"))
        except Exception as exc:
            print(f"  SettingProfiles fetch failed: {exc}", file=sys.stderr)
        try:
            s0 = pull_spool(transport, "Summary", "2000-01-01T00:00:00.000Z")
            cap.save_bytes("Summary_initial.spool", s0)
        except Exception as exc:
            print(f"  initial Summary pull failed: {exc}", file=sys.stderr)

        # Install notification handler so StreamData + EventNotification are captured
        transport.set_notification_handler(cap.on_notify)

        if do_probe:
            probe_spools(transport, cap)
            # Re-install our handler because spool_one_round clears it
            transport.set_notification_handler(cap.on_notify)

        # --- subscribe + stream ----------------------------------------- #
        print("Subscribing to events ...")
        transport.rpc("SubscribeEvent", {"dataIds": EVENT_SELECTORS}, encrypted=True)

        if mode == "grouped":
            start_grouped(transport)
            ok = detect_grouped_ok(cap)
            if not ok:
                print("  -> device did not honour concurrent subscriptions; "
                      "falling back to SINGLE mode.")
                stop_stream(transport)
                cap.seen_streams.clear()
                start_single(transport, rate_ms)
                # Re-install handler after the stop/start RPCs
                transport.set_notification_handler(cap.on_notify)
        else:
            start_single(transport, rate_ms)

        print(f"Capturing ... (Ctrl+C to stop; auto-stop {timeout_sec:.0f}s after data ends)")
        try:
            while not cap.therapy_stopped:
                time.sleep(0.5)
                if cap.stream_active and (time.time() - cap.last_packet_time > timeout_sec):
                    print(f"No stream data for {timeout_sec:.0f}s; assuming therapy stopped.")
                    break
        except KeyboardInterrupt:
            print("\nInterrupted.")
        finally:
            stop_stream(transport)

        # --- post-session: pull updated Summary + events --------------- #
        print("Waiting 5s for device to flush session-end data ...")
        time.sleep(5.0)
        # Re-install handler in case it was cleared by any internal RPC
        transport.set_notification_handler(cap.on_notify)
        try:
            s1 = pull_spool(transport, "Summary", "2000-01-01T00:00:00.000Z")
            cap.save_bytes("Summary_final.spool", s1)
        except Exception as exc:
            print(f"  final Summary pull failed: {exc}", file=sys.stderr)
        try:
            start_iso = datetime.fromtimestamp(
                (cap.therapy_start_ms or int(cap.start_time.timestamp() * 1000)) / 1000,
                timezone.utc,
            ).strftime("%Y-%m-%dT%H:%M:%S.000Z")
            ev = pull_spool(transport, "TherapyEvents-RespiratoryEvents", start_iso)
            cap.save_bytes("RespiratoryEvents.spool", ev)
        except Exception as exc:
            print(f"  RespiratoryEvents pull failed: {exc}", file=sys.stderr)

    finally:
        transport.set_notification_handler(None)
        cap.close()
        transport.close()

    _print_summary(cap)
    return 0


def _print_summary(cap: RawCapture):
    print("\n=== capture summary ===")
    print(f"  RAW dir          : {cap.raw_dir}")
    print(f"  stream packets   : {cap.n_stream_packets}")
    print(f"  event notifs     : {cap.n_events}")
    print(f"  signals received : {len(cap.seen_streams)}/{len(ALL_STREAMS)}")
    missing = set(ALL_STREAMS) - set(cap.seen_streams)
    if missing:
        print(f"  MISSING signals  : {sorted(missing)}")
    print(f"\nNext: python3 edf_write.py {cap.raw_dir} --outdir export_out")


def main():
    ap = argparse.ArgumentParser(description="BLE capture for AS11 therapy sessions.")
    ap.add_argument("addr", nargs="?", help="BLE MAC/alias (or env AS11_ADDR)")
    ap.add_argument("--outdir", default="sd_card", help="output root (RAW/<id> created within)")
    ap.add_argument("--mode", choices=["single", "grouped"], default="single",
                    help="single=one stream @ --rate-ms (safe, 4x cut); "
                         "grouped=per-group native rates (experimental, auto-fallback)")
    ap.add_argument("--rate-ms", type=int, default=40,
                    help="single-mode sample interval (default 40 ms = 25 Hz, BRP-native)")
    ap.add_argument("--probe-spools", action="store_true",
                    help="probe for high-resolution history spools (experimental)")
    ap.add_argument("--timeout", type=float, default=30.0,
                    help="auto-stop after this many seconds without stream data")
    args = ap.parse_args()

    addr = args.addr or os.environ.get("AS11_ADDR")
    if not addr:
        print("Error: no BLE address (pass ADDR or set AS11_ADDR).", file=sys.stderr)
        return 2
    return run(addr, args.outdir, args.mode, args.rate_ms,
               args.probe_spools, args.timeout)


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""edf_write.py — build ResMed AirSense 11 SD-card EDF files from a raw BLE capture.

This is an *offline* converter.  It consumes a RAW capture folder produced by
``edf_capture_data.py`` (``notifications.jsonl`` + ``get_vars.json`` +
``get_settings.json`` + optional ``*.spool``) and emits DATALOG EDF files in the
exact byte format the CPAP itself writes to its SD card:

    <out>/DATALOG/<YYYYMMDD>/<YYYYMMDD_HHMMSS>_BRP.edf   (Flow.40ms, Press.40ms)
                            /<YYYYMMDD_HHMMSS>_PLD.edf   (9 x .2s channels)
                            /<YYYYMMDD_HHMMSS>_SA2.edf   (Pulse.1s, SpO2.1s)
                            /<YYYYMMDD_HHMMSS>_EVE.edf   (annotations + events)
                            /<YYYYMMDD_HHMMSS>_CSL.edf   (annotations)
    <out>/Identification.json

Format details are documented in ``docs/as11/edf_spec.md``.

Usage::

    python3 edf_write.py <raw_dir> [--outdir OUT]
    python3 edf_write.py <raw_dir> --outdir OUT --compare <orig_session_dir>
"""

from __future__ import annotations

import argparse
import bisect
import glob
import json
import os
import struct
import sys
from datetime import datetime, timezone, timedelta


# --------------------------------------------------------------------------- #
# Low-level helpers
# --------------------------------------------------------------------------- #

def crc16_ccitt(data: bytes) -> int:
    """CRC-16/CCITT-FALSE (poly=0x1021, init=0xFFFF, no reflection, xorout=0)."""
    crc = 0xFFFF
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if (crc & 0x8000) else (crc << 1) & 0xFFFF
    return crc


def _afield(text: str, width: int) -> bytes:
    """ASCII field, left-justified, space-padded to width (truncated if longer)."""
    b = str(text).encode("ascii", "replace")[:width]
    return b + b" " * (width - len(b))


def iso_to_ms(s: str) -> int:
    return int(datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp() * 1000)


# --------------------------------------------------------------------------- #
# EDF signal / writer (ResMed-exact byte formatting)
# --------------------------------------------------------------------------- #

class Signal:
    """A regular EDF signal with explicit header strings and digital scaling."""

    def __init__(self, label, dim, pmin, pmax, dmin, dmax, spr,
                 pmin_str=None, pmax_str=None):
        self.label = label
        self.dim = dim
        self.pmin = float(pmin)
        self.pmax = float(pmax)
        self.dmin = int(dmin)
        self.dmax = int(dmax)
        self.spr = int(spr)
        self.pmin_str = pmin_str if pmin_str is not None else _num(self.pmin)
        self.pmax_str = pmax_str if pmax_str is not None else _num(self.pmax)
        self.records: list[list[int]] = []  # digital int16 samples per record

    def gain_offset(self):
        gain = (self.pmax - self.pmin) / (self.dmax - self.dmin)
        offset = self.pmax - gain * self.dmax
        return gain, offset

    def digitize(self, value: float) -> int:
        gain, offset = self.gain_offset()
        v = max(self.pmin, min(self.pmax, value))
        r = int(round((v - offset) / gain))
        return max(self.dmin, min(self.dmax, r))

    def add_record_physical(self, values: list, scale: float = 1.0,
                            none_digital: int | None = None):
        rec = []
        for v in values:
            if v is None:
                rec.append(none_digital if none_digital is not None else self.dmin)
            else:
                rec.append(self.digitize(v * scale))
        while len(rec) < self.spr:
            rec.append(0)
        self.records.append(rec[: self.spr])


class AnnotationSignal:
    """EDF+ annotation signal (TAL bytes packed as little-endian int16)."""

    def __init__(self, spr: int = 31):
        self.label = "EDF Annotations"
        self.dim = ""
        self.pmin, self.pmax = -32768.0, 32767.0
        self.dmin, self.dmax = -32768, 32767
        self.spr = int(spr)
        self.pmin_str, self.pmax_str = "-32768.0", "32767.00"
        self.records: list[bytes] = []  # raw TAL bytes per record (<= spr*2)

    def add_tal_record(self, tal: bytes):
        self.records.append(tal)

    def record_int16(self, idx: int) -> list[int]:
        tal = self.records[idx]
        tal = tal + b"\x00" * (self.spr * 2 - len(tal))
        return [struct.unpack("<h", tal[i:i + 2])[0] for i in range(0, self.spr * 2, 2)]


def crc_signal() -> Signal:
    return Signal("Crc16", "", -32768, 32767, -32768, 32767, 1,
                  pmin_str="-32768.0", pmax_str="32767.00")


def _num(x: float) -> str:
    """Format a physical min/max the ResMed way: 2 decimals, fit in 8 chars."""
    s = f"{x:.2f}"
    if len(s) > 8:
        s = f"{x:.1f}"[:8]
    return s


class EdfFile:
    """Assembles signals + trailing Crc16 and writes a byte-exact EDF."""

    def __init__(self, patient: str, recording: str, start: datetime,
                 dur_per_record: str, reserved: str, h2: str = "0000"):
        self.patient = patient
        self.h2 = h2
        self.recording = recording
        self.start = start
        self.dur_per_record = dur_per_record
        self.reserved = reserved
        self.signals: list = []
        self.annotation: AnnotationSignal | None = None

    def num_records(self) -> int:
        if self.annotation is not None:
            return len(self.annotation.records)
        return max((len(s.records) for s in self.signals), default=0)

    def _signal_list(self):
        out = list(self.signals)
        if self.annotation is not None:
            out = [self.annotation] + out
        out.append(crc_signal())
        return out

    def _header(self) -> bytes:
        sigs = self._signal_list()
        ns = len(sigs)
        nrec = self.num_records()
        header_bytes = 256 + ns * 256
        local = self.start.astimezone()
        h = b""
        h += _afield("0", 8)
        h += _afield(PATIENT_PREFIX, 80)
        h += _afield(self.recording, 80)
        h += _afield(local.strftime("%d.%m.%y"), 8)
        h += _afield(local.strftime("%H.%M.%S"), 8)
        h += _afield(str(header_bytes), 8)
        h += _afield(self.reserved, 44)
        h += _afield(str(nrec), 8)
        h += _afield(self.dur_per_record, 8)
        h += _afield(str(ns), 4)
        cols = [
            (16, lambda s: s.label),
            (80, lambda s: ""),
            (8, lambda s: s.dim),
            (8, lambda s: s.pmin_str),
            (8, lambda s: s.pmax_str),
            (8, lambda s: str(s.dmin)),
            (8, lambda s: str(s.dmax)),
            (80, lambda s: ""),
            (8, lambda s: str(s.spr)),
            (32, lambda s: ""),
        ]
        for width, getter in cols:
            for s in sigs:
                h += _afield(getter(s), width)
        return self._patch_patient_token(h)

    def _patch_patient_token(self, h: bytes) -> bytes:
        """Compute and insert the patient tokens H1 H2 into the header.

        H1 = CRC16/CCITT-FALSE(first 256 header bytes, token slot blank) ^ 0x3A78
        H2 = per-type constant (self.h2)
        Reverse-engineered from 1925 original ResMed EDF files (100% match).
        """
        buf = bytearray(h)
        buf[16:25] = b" " * 9
        h1 = crc16_ccitt(bytes(buf[:256])) ^ H1_XOR_CONST
        buf[16:25] = f"{h1:04X} {self.h2}".encode("ascii")
        return bytes(buf)

    def _record_bytes(self, rec_idx: int) -> bytes:
        out = b""
        if self.annotation is not None:
            out += b"".join(struct.pack("<h", v) for v in self.annotation.record_int16(rec_idx))
        for s in self.signals:
            rec = s.records[rec_idx] if rec_idx < len(s.records) else [0] * s.spr
            out += b"".join(struct.pack("<h", v) for v in rec)
        return out

    def to_bytes(self) -> bytes:
        out = self._header()
        for r in range(self.num_records()):
            body = self._record_bytes(r)
            crc = crc16_ccitt(body)
            out += body + struct.pack("<h", crc - 0x10000 if crc >= 0x8000 else crc)
        return out

    def write(self, path: str):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as fp:
            fp.write(self.to_bytes())


# --------------------------------------------------------------------------- #
# Signal definitions (label, dim, pmin, pmax, dmin, dmax, spr) — from edf_spec
# --------------------------------------------------------------------------- #

BRP_DEFS = [
    ("Flow.40ms",  "L/s",   -2, 3,  -1000, 1500, 1500, "PatientFlow-100hz",   1.0),
    ("Press.40ms", "cmH2O",  0, 40,     0, 2000, 1500, "MaskPressure-100hz",  1.0),
]
PLD_DEFS = [
    ("MaskPress.2s", "cmH2O", 0, 40, 0, 2000, 30, "MaskPressure-TwoSecond",        1.0),
    ("Press.2s",     "cmH2O", 0, 50, 0, 2500, 30, "InspiratoryPressure-TwoSecond", 1.0),
    ("EprPress.2s",  "cmH2O", 0, 30, 0, 1500, 30, "ExpiratoryPressure-TwoSecond",  1.0),
    ("Leak.2s",      "L/s",   0, 2,  0,  100, 30, "Leak-50hz",                     1.0 / 60.0),
    ("RespRate.2s",  "bpm",   0, 90, 0,  450, 30, "RespiratoryRate-50hz",          1.0),
    ("TidVol.2s",    "L",     0, 4,  0,  200, 30, "TidalVolume-50hz",              1.0),
    ("MinVent.2s",   "L/min", 0, 30, 0,  240, 30, "MinuteVentilation-50hz",        1.0),
    ("Snore.2s",     "",      0, 5,  0,  250, 30, "SnoreIndex-50hz",               1.0),
    ("FlowLim.2s",   "",      0, 1,  0,  100, 30, "FlowLimitation-50hz",           1.0),
]
SA2_DEFS = [
    ("Pulse.1s", "bpm", 0, 300, 0, 300, 60, "HeartRate", 1.0),
    ("SpO2.1s",  "%",   0, 100, 0, 100, 60, "SpO2",      1.0),
]

RESP_LABEL_MAP = {
    "CentralApnea": "Central Apnea",
    "ObstructiveApnea": "Obstructive Apnea",
    "Hypopnea": "Hypopnea",
    "Apnea": "Apnea",
    "RERA": "Arousal",
    "Arousal": "Arousal",
}


# --------------------------------------------------------------------------- #
# Capture parsing
# --------------------------------------------------------------------------- #

class Capture:
    """Parsed RAW capture: timestamped stream samples + events + device info."""

    def __init__(self, raw_dir: str):
        self.raw_dir = raw_dir
        self.streams: dict[str, list[tuple[int, float]]] = {}
        self.status_events: list[tuple[int, str]] = []
        self.resp_events: list[dict] = []
        self.vars: dict = {}
        self._load()

    def _load(self):
        gv = os.path.join(self.raw_dir, "get_vars.json")
        if os.path.exists(gv):
            self.vars = json.load(open(gv))
        nf = os.path.join(self.raw_dir, "notifications.jsonl")
        if not os.path.exists(nf):
            raise FileNotFoundError(f"no notifications.jsonl in {self.raw_dir}")
        for line in open(nf):
            line = line.strip()
            if not line:
                continue
            o = json.loads(line).get("msg", {})
            method = o.get("method", "")
            params = o.get("params", {}) if isinstance(o.get("params"), dict) else {}
            if method == "StreamData":
                self._ingest_stream(params)
            elif method == "EventNotification":
                self._ingest_event(params)
        for sid in self.streams:
            self.streams[sid].sort(key=lambda x: x[0])
        self.status_events.sort()

    def _ingest_stream(self, params):
        try:
            base = iso_to_ms(params.get("startTime", ""))
        except Exception:
            return
        iv = params.get("intervalMs", 10) or 10
        for item in params.get("data", []):
            if not isinstance(item, dict):
                continue
            for sid, samples in item.items():
                if not isinstance(samples, list):
                    continue
                bucket = self.streams.setdefault(sid, [])
                for i, v in enumerate(samples):
                    bucket.append((base + i * iv, v))

    def _ingest_event(self, params):
        did = params.get("dataId", "")
        for ev in params.get("events", []):
            label = ev.get("label") or ev.get("event") or ""
            ts = ev.get("timestamp")
            if ts is None and ev.get("reportTime"):
                ts = iso_to_ms(ev["reportTime"])
            if ts is None:
                continue
            if did == "UsageEvents-TherapyStatusEvents":
                self.status_events.append((int(ts), label))
            elif did == "TherapyEvents-RespiratoryEvents":
                self.resp_events.append({
                    "ts": int(ts), "label": label,
                    "dur": int(ev.get("duration", 0) or 0),
                })

    def sample_at(self, sid: str, t_ms: int, keep_none: bool):
        series = self.streams.get(sid, [])
        if not series:
            return None
        if not keep_none:
            series = self._nonnull_cache(sid)
            if not series:
                return None
        idx = bisect.bisect_right([s[0] for s in series], t_ms) - 1
        if idx < 0:
            idx = 0
        return series[idx][1]

    def _nonnull_cache(self, sid):
        cache = getattr(self, "_nn", None)
        if cache is None:
            cache = self._nn = {}
        if sid not in cache:
            cache[sid] = [(t, v) for (t, v) in self.streams.get(sid, []) if v is not None]
        return cache[sid]

    def sessions(self):
        starts = [t for t, l in self.status_events if l == "TherapyStart"]
        stops = [t for t, l in self.status_events if l == "TherapyStop"]
        mask_on = [t for t, l in self.status_events if l == "MaskOn"]
        mask_off = [t for t, l in self.status_events if l == "MaskOff"]
        out = []
        for i, ts_start in enumerate(starts):
            ts_stop = next((s for s in stops if s >= ts_start), None)
            if ts_stop is None:
                ts_stop = self._last_sample_ms() or ts_start
            mon = next((m for m in mask_on if m >= ts_start), ts_start)
            moff = None
            for m in mask_off:
                if mon <= m <= ts_stop:
                    moff = m
            if moff is None:
                moff = ts_stop
            out.append({"therapy_start": ts_start, "therapy_stop": ts_stop,
                        "mask_on": mon, "mask_off": moff})
        return out

    def _last_sample_ms(self):
        m = 0
        for s in self.streams.values():
            if s:
                m = max(m, s[-1][0])
        return m or None


# --------------------------------------------------------------------------- #
# Device identification fields
# --------------------------------------------------------------------------- #

def device_fields(vars_: dict):
    srn = vars_.get("SerialNumber", "")
    mid = vars_.get("PlatformIdentifier", "")
    vid = vars_.get("VariantIdentifier", "")
    return srn, mid, vid


def recording_field(start_local: datetime, srn, mid, vid) -> str:
    d = start_local.strftime("%d-%b-%Y").upper()
    return f"Startdate {d} X X X SRN={srn} MID={mid} VID={vid}"


# --------------------------------------------------------------------------- #
# Patient-field tokens (reverse-engineered from 1925 original EDF files)
# --------------------------------------------------------------------------- #
PATIENT_PREFIX = "X X X X"
H1_XOR_CONST = 0x3A78
PATIENT_TOKENS_H2 = {
    "BRP": "D4BA", "PLD": "A81F", "SA2": "6EAD", "CSL": "2B58", "EVE": "2B58",
}


# --------------------------------------------------------------------------- #
# Builders
# --------------------------------------------------------------------------- #

def _local(ms: int) -> datetime:
    return datetime.fromtimestamp(ms / 1000, timezone.utc).astimezone()


def _floor_sec_ms(ms: int) -> int:
    return (ms // 1000) * 1000


def build_signal_file(cap: Capture, sess, defs, kind, srn, mid, vid):
    """Build BRP/PLD/SA2. Returns (EdfFile, anchor_ms) or None if no full minute."""
    anchor = _floor_sec_ms(sess["mask_on"])
    end = sess["mask_off"]
    nrec = int((end - anchor) // 60000)
    if nrec < 1:
        return None
    start_dt = datetime.fromtimestamp(anchor / 1000, timezone.utc)
    edf = EdfFile(PATIENT_PREFIX,
                  recording_field(start_dt.astimezone(), srn, mid, vid),
                  start_dt, "60.00", "EDF", h2=PATIENT_TOKENS_H2[kind])
    sentinel = -1 if kind == "SA2" else None
    keep_none = (kind == "SA2")
    for label, dim, pmin, pmax, dmin, dmax, spr, sid, scale in defs:
        sig = Signal(label, dim, pmin, pmax, dmin, dmax, spr)
        step_ms = int(60000 / spr)
        for r in range(nrec):
            vals = []
            for i in range(spr):
                t = anchor + r * 60000 + i * step_ms
                v = cap.sample_at(sid, t, keep_none=keep_none)
                vals.append(v)
            sig.add_record_physical(vals, scale=scale, none_digital=sentinel)
        edf.signals.append(sig)
    return edf, anchor


def build_tal_recording_starts() -> bytes:
    return b"+0\x14\x14\x00+0\x150\x14Recording starts\x14"


def build_tal_event(onset_sec: int, dur_sec: int, label: str) -> bytes:
    return (b"+0\x14\x14\x00+" + str(onset_sec).encode() + b"\x15"
            + str(dur_sec).encode() + b"\x14" + label.encode("ascii", "replace") + b"\x14")


def build_eve(cap: Capture, sess, srn, mid, vid, with_events: bool):
    anchor = _floor_sec_ms(sess["therapy_start"])
    start_dt = datetime.fromtimestamp(anchor / 1000, timezone.utc)
    edf = EdfFile(PATIENT_PREFIX,
                  recording_field(start_dt.astimezone(), srn, mid, vid),
                  start_dt, "0.00", "EDF+D", h2=PATIENT_TOKENS_H2["EVE"])
    ann = AnnotationSignal(spr=31)
    ann.add_tal_record(build_tal_recording_starts())
    if with_events:
        evs = [e for e in cap.resp_events
               if sess["therapy_start"] <= e["ts"] <= sess["therapy_stop"]]
        evs.sort(key=lambda e: e["ts"])
        for e in evs:
            onset = int(round((e["ts"] - anchor) / 1000))
            dur = int(round(e["dur"] / 1000))
            label = RESP_LABEL_MAP.get(e["label"], e["label"])
            ann.add_tal_record(build_tal_event(onset, dur, label))
    edf.annotation = ann
    return edf


# --------------------------------------------------------------------------- #
# Identification.json
# --------------------------------------------------------------------------- #

def write_identification(vars_: dict, out_dir: str):
    p = vars_
    obj = {"FlowGenerator": {"IdentificationProfiles": {
        "Product": {
            "UniversalIdentifier": p.get("UniversalIdentifier", ""),
            "SerialNumber": p.get("SerialNumber", ""),
            "SerialNumberVerificationCode": "",
            "ProductCode": p.get("ProductCode", ""),
            "ProductName": p.get("ProductName", "").replace(" ", ""),
            "FdaUniqueDeviceIdentifier": "",
            "ProductGeographicIdentifier": p.get("ProductGeographicIdentifier", ""),
        },
        "Hardware": {"HardwareIdentifier": p.get("HardwareIdentifier", "")},
        "Software": {
            "BootloaderIdentifier": p.get("BootloaderIdentifier", ""),
            "ApplicationIdentifier": p.get("ApplicationIdentifier", ""),
            "ConfigurationIdentifier": p.get("ConfigurationIdentifier", ""),
            "PlatformIdentifier": p.get("PlatformIdentifier", ""),
            "VariantIdentifier": p.get("VariantIdentifier", ""),
            "RegionIdentifier": p.get("RegionIdentifier", ""),
            "ProfileVariationIdentifier": p.get("ProfileVariantIdentifier", ""),
            "DataVersionIdentifier": p.get("DataVersionIdentifier", ""),
            "DataModelVersionIdentifier": p.get("DataModelVersionIdentifier", ""),
        },
    }}}
    text = json.dumps(obj, separators=(",", ":"))
    with open(os.path.join(out_dir, "Identification.json"), "w") as fp:
        fp.write(text)


# --------------------------------------------------------------------------- #
# Day-folder (noon split) and session id
# --------------------------------------------------------------------------- #

def noon_day_folder(therapy_start_ms: int) -> str:
    local = _local(therapy_start_ms)
    day = local.date() if local.hour >= 12 else (local - timedelta(days=1)).date()
    return day.strftime("%Y%m%d")


def session_id(ms: int) -> str:
    return _local(ms).strftime("%Y%m%d_%H%M%S")


# --------------------------------------------------------------------------- #
# Main export
# --------------------------------------------------------------------------- #

def export(raw_dir: str, out_dir: str) -> list[str]:
    cap = Capture(raw_dir)
    srn, mid, vid = device_fields(cap.vars)
    os.makedirs(out_dir, exist_ok=True)
    write_identification(cap.vars, out_dir)
    written = []
    for sess in cap.sessions():
        folder = os.path.join(out_dir, "DATALOG", noon_day_folder(sess["therapy_start"]))
        eve_id = session_id(sess["therapy_start"])
        sig_id = session_id(sess["mask_on"])

        eve = build_eve(cap, sess, srn, mid, vid, with_events=True)
        p = os.path.join(folder, f"{eve_id}_EVE.edf"); eve.write(p); written.append(p)
        csl = build_eve(cap, sess, srn, mid, vid, with_events=False)
        p = os.path.join(folder, f"{eve_id}_CSL.edf"); csl.write(p); written.append(p)

        for kind, defs in (("BRP", BRP_DEFS), ("PLD", PLD_DEFS), ("SA2", SA2_DEFS)):
            res = build_signal_file(cap, sess, defs, kind, srn, mid, vid)
            if res is None:
                print(f"  {kind}: <1 full minute of data, skipping (matches CPAP)")
                continue
            edf, _ = res
            p = os.path.join(folder, f"{sig_id}_{kind}.edf")
            edf.write(p); written.append(p)
    return written


# --------------------------------------------------------------------------- #
# Comparison / verification
# --------------------------------------------------------------------------- #

def _parse_edf(path):
    b = open(path, "rb").read()
    ns = int(b[252:256]); p = 256
    lab = [b[p + i * 16:p + (i + 1) * 16].decode("latin1").rstrip() for i in range(ns)]; p += ns * 16
    p += ns * 80
    dim = [b[p + i * 8:p + (i + 1) * 8].decode("latin1").rstrip() for i in range(ns)]; p += ns * 8
    pmin = [float(b[p + i * 8:p + (i + 1) * 8]) for i in range(ns)]; p += ns * 8
    pmax = [float(b[p + i * 8:p + (i + 1) * 8]) for i in range(ns)]; p += ns * 8
    dmin = [int(b[p + i * 8:p + (i + 1) * 8]) for i in range(ns)]; p += ns * 8
    dmax = [int(b[p + i * 8:p + (i + 1) * 8]) for i in range(ns)]; p += ns * 8
    p += ns * 80
    spr = [int(b[p + i * 8:p + (i + 1) * 8]) for i in range(ns)]; p += ns * 8 + ns * 32
    nrec = int(b[236:244])
    recbytes = sum(s * 2 for s in spr)
    sigs = {}
    for i in range(ns):
        vals = []
        g = (pmax[i] - pmin[i]) / (dmax[i] - dmin[i]) if dmax[i] != dmin[i] else 1
        o = pmax[i] - g * dmax[i]
        for r in range(nrec):
            rp = p + r * recbytes + sum(spr[j] for j in range(i)) * 2
            raw = struct.unpack(f"<{spr[i]}h", b[rp:rp + spr[i] * 2])
            vals += [x * g + o for x in raw]
        sigs[lab[i]] = vals
    return {"header": b[:256 + ns * 256], "labels": lab, "dim": dim,
            "nrec": nrec, "start": b[176:184].decode(), "sigs": sigs, "raw": b}


def compare(gen_dir: str, ref_dir: str):
    print(f"\n=== COMPARE {gen_dir}  vs  {ref_dir} ===")
    for kind in ("BRP", "PLD", "SA2", "EVE", "CSL"):
        g = glob.glob(os.path.join(gen_dir, f"*_{kind}.edf"))
        r = glob.glob(os.path.join(ref_dir, f"*_{kind}.edf"))
        if not g or not r:
            print(f"[{kind}] missing (gen={len(g)} ref={len(r)})")
            continue
        G, R = _parse_edf(g[0]), _parse_edf(r[0])
        hdr_eq = G["header"] == R["header"]
        print(f"[{kind}] gen={os.path.basename(g[0])} ref={os.path.basename(r[0])}")
        print(f"    header identical: {hdr_eq}  nrec gen={G['nrec']} ref={R['nrec']}  "
              f"start gen={G['start']} ref={R['start']}")
        if not hdr_eq:
            _diff_headers(G, R)
        for lab in R["labels"]:
            if lab in ("Crc16", "EDF Annotations") or lab not in G["sigs"]:
                continue
            gv, rv = G["sigs"][lab], R["sigs"][lab]
            m = min(len(gv), len(rv))
            if m == 0:
                continue
            diff = [abs(gv[i] - rv[i]) for i in range(m)]
            print(f"    {lab:13s} n(g/r)={len(gv)}/{len(rv)} "
                  f"meanAbsDiff={sum(diff)/m:.4f} max={max(diff):.4f}")
        if kind in ("EVE", "CSL"):
            print(f"    full-file identical: {G['raw'] == R['raw']}")


def _diff_headers(G, R):
    a, b = G["header"], R["header"]
    fixed = [("patient", 8, 88), ("recording", 88, 168), ("startdate", 168, 176),
             ("starttime", 176, 184), ("reserved", 192, 236), ("nrec", 236, 244),
             ("dur", 244, 252)]
    for name, s, e in fixed:
        if a[s:e] != b[s:e]:
            print(f"      header.{name}: gen={a[s:e]!r} ref={b[s:e]!r}")


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def main():
    ap = argparse.ArgumentParser(description="Build CPAP-format SD-card EDF files from a RAW BLE capture.")
    ap.add_argument("raw_dir", help="RAW capture dir (contains notifications.jsonl, get_vars.json)")
    ap.add_argument("--outdir", default="export_out", help="output root (default: export_out)")
    ap.add_argument("--compare", default=None,
                    help="reference session DATALOG dir to diff generated files against")
    args = ap.parse_args()

    written = export(args.raw_dir, args.outdir)
    print(f"Wrote {len(written)} file(s):")
    for p in written:
        print(f"  {p}")

    if args.compare:
        gen_days = glob.glob(os.path.join(args.outdir, "DATALOG", "*"))
        gen_dir = gen_days[0] if gen_days else args.outdir
        compare(gen_dir, args.compare)


if __name__ == "__main__":
    main()

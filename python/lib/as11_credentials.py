"""Air11 Bluetooth pairing credentials and address/alias resolution."""

from __future__ import annotations

import json
import logging
import os
import re
import tempfile
from pathlib import Path

from as11_rpc import TransportError


CRED_FILE = Path.home() / ".as11_ble.json"
MAC_RE = re.compile(r'^[0-9A-Fa-f]{2}(:[0-9A-Fa-f]{2}){5}$')
UUID_RE = re.compile(r'^[0-9A-Fa-f]{8}-([0-9A-Fa-f]{4}-){3}[0-9A-Fa-f]{12}$')
log = logging.getLogger("as11.ble")


def load_all_credentials() -> dict:
    try:
        data = json.loads(CRED_FILE.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise TransportError(f"cannot read credentials {CRED_FILE}: {exc}") from exc
    if not isinstance(data, dict) or any(not isinstance(value, dict) for value in data.values()):
        raise TransportError(f"invalid credentials in {CRED_FILE}: expected address-to-object mapping")
    normalized = {}
    for address, value in data.items():
        key = address.upper() if MAC_RE.fullmatch(address) else address
        if key in normalized:
            raise TransportError(f"duplicate device address in {CRED_FILE}: {key}")
        normalized[key] = value
    return normalized


def save_all_credentials(all_creds: dict) -> None:
    payload = json.dumps(all_creds, indent=2) + "\n"
    CRED_FILE.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{CRED_FILE.name}.", dir=CRED_FILE.parent)
    temp_path = Path(temp_name)
    try:
        # mkstemp creates mode 0600 on POSIX; Windows uses inherited ACLs.
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            fd = -1
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, CRED_FILE)
    finally:
        if fd >= 0:
            os.close(fd)
        temp_path.unlink(missing_ok=True)


def save_credentials(address: str, creds: dict) -> None:
    address = address.upper() if MAC_RE.fullmatch(address) else address
    all_creds = load_all_credentials()
    existing = all_creds.get(address, {})
    existing.update(creds)
    all_creds[address] = existing
    save_all_credentials(all_creds)
    log.info("credentials saved to %s", CRED_FILE)


def load_credentials(address: str) -> dict:
    address = address.upper() if MAC_RE.fullmatch(address) else address
    return load_all_credentials().get(address, {})


def resolve_addr(arg: str = None) -> str:
    """Resolve MAC, UUID, or alias; default to AS11_ADDR."""
    if arg is None:
        arg = os.environ.get("AS11_ADDR")
    if not arg:
        raise SystemExit("no address: pass --addr or set AS11_ADDR")
    if MAC_RE.fullmatch(arg):
        return arg.upper()
    if UUID_RE.fullmatch(arg):
        return arg
    for addr, data in load_all_credentials().items():
        if data.get("alias") == arg:
            return addr
    raise SystemExit(f"no MAC/UUID/alias matched: {arg!r}")

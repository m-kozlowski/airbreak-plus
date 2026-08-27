"""Shared Bluetooth application credentials and address resolution.

The historical file name is retained so existing AirSense 11 pairings keep
working. Entries without a family field are existing AirSense 11 records.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path

from as11_rpc import TransportError


CRED_FILE = Path.home() / ".as11_ble.json"
MAC_RE = re.compile(r"^[0-9A-Fa-f]{2}(:[0-9A-Fa-f]{2}){5}$")
UUID_RE = re.compile(r"^[0-9A-Fa-f]{8}-([0-9A-Fa-f]{4}-){3}[0-9A-Fa-f]{12}$")


def _credential_key(address: str) -> str:
    return address.upper() if MAC_RE.fullmatch(address) else address


def load_all_credentials() -> dict:
    if not CRED_FILE.exists():
        return {}
    try:
        value = json.loads(CRED_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise TransportError(f"cannot read credentials {CRED_FILE}: {exc}") from exc
    if not isinstance(value, dict):
        raise TransportError(f"invalid credentials in {CRED_FILE}")
    return value


def save_all_credentials(credentials: dict) -> None:
    payload = json.dumps(credentials, indent=2) + "\n"
    CRED_FILE.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(
        prefix=f".{CRED_FILE.name}.", dir=CRED_FILE.parent
    )
    temp_path = Path(temp_name)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            fd = -1
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, CRED_FILE)
    finally:
        if fd >= 0:
            os.close(fd)
        try:
            temp_path.unlink()
        except FileNotFoundError:
            pass


def load_credentials(address: str) -> dict:
    return load_all_credentials().get(_credential_key(address), {})


def save_credentials(address: str, credentials: dict) -> None:
    address = _credential_key(address)
    all_credentials = load_all_credentials()
    existing = all_credentials.get(address, {})
    existing.update(credentials)
    all_credentials[address] = existing
    save_all_credentials(all_credentials)


def credential_family(credentials: dict) -> str:
    """Return the device family, preserving compatibility with old records."""
    return credentials.get("family") or "as11"


def resolve_address(
    target: str | None,
    *,
    env_var: str,
    allow_uuid: bool,
    expected_family: str | None = None,
) -> str:
    """Resolve a direct Bluetooth address or a shared credential alias."""
    if target is None:
        target = os.environ.get(env_var)
    if not target:
        raise SystemExit(f"no address: pass a device address or set {env_var}")
    if MAC_RE.fullmatch(target):
        return target.upper()
    if allow_uuid and UUID_RE.fullmatch(target):
        return target
    for address, credentials in load_all_credentials().items():
        if credentials.get("alias") == target:
            if (expected_family is not None
                    and credential_family(credentials) != expected_family):
                continue
            if not allow_uuid and not MAC_RE.fullmatch(address):
                continue
            return _credential_key(address)
    address_types = "MAC/UUID/alias" if allow_uuid else "MAC/alias"
    raise SystemExit(f"no {address_types} matched: {target!r}")


__all__ = [
    "CRED_FILE", "MAC_RE", "UUID_RE",
    "load_all_credentials", "save_all_credentials",
    "load_credentials", "save_credentials", "credential_family",
    "resolve_address",
]

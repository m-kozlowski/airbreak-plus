#!/usr/bin/env python3
"""CAN transport flavour selection."""

from __future__ import annotations

import argparse
import os
import re
from importlib import import_module


CAN_TRANSPORTS = {
    "slcan": ("as11_can_canable", "CanCanableTransport"),
    "waveshare": ("as11_can_waveshare", "CanWaveshareTransport"),
    "canable": ("as11_can_canable", "CanCanableTransport"),
    "socketcan": ("as11_can_socketcan", "CanSocketcanTransport"),
}
CAN_FLAVOUR_ALIASES = {
    "canable": "slcan",
}


def add_args(p: argparse.ArgumentParser, *, show_help: bool = True) -> None:
    suppr = argparse.SUPPRESS
    g = p.add_argument_group("CAN adapter (ignored unless -d can:...)")
    g.add_argument("--can-flavour", default=suppr,
                   choices=tuple(CAN_TRANSPORTS),
                   help=("CAN adapter protocol. By default this is inferred "
                         "from can:<target>") if show_help else suppr)


def split_flavour_target(target: str) -> tuple[str | None, str]:
    """Return (explicit_flavour, stripped_target) for can:<flavour>:<target>."""
    prefix, sep, rest = target.partition(":")
    if sep and prefix in CAN_TRANSPORTS:
        if not rest:
            raise SystemExit(f"can:{prefix}: needs adapter target")
        return CAN_FLAVOUR_ALIASES.get(prefix, prefix), rest
    return None, target


def infer_flavour(target: str) -> str:
    """Pick the most likely CAN backend from the target spelling."""
    if re.fullmatch(r"(?:v?can|slcan)\d+", target):
        return "socketcan"

    basename = os.path.basename(target).lower()
    if (basename.startswith("ttyacm") or basename.startswith("ttyusb")
            or re.fullmatch(r"com\d+", target.lower())):
        return "slcan"

    return "slcan"


def from_args(target: str, args: argparse.Namespace):
    target_flavour, target = split_flavour_target(target)
    arg_flavour = getattr(args, "can_flavour", None)
    if arg_flavour:
        arg_flavour = CAN_FLAVOUR_ALIASES.get(arg_flavour, arg_flavour)
    if arg_flavour and target_flavour and arg_flavour != target_flavour:
        raise SystemExit(
            f"CAN flavour mismatch: target requests {target_flavour!r}, "
            f"but --can-flavour is {arg_flavour!r}"
        )
    flavour = arg_flavour or target_flavour or infer_flavour(target)
    try:
        module_name, class_name = CAN_TRANSPORTS[flavour]
    except KeyError as exc:
        supported = ", ".join(repr(name) for name in sorted(CAN_TRANSPORTS))
        raise SystemExit(
            f"unsupported --can-flavour {flavour!r} (supported: {supported})"
        ) from exc
    module = import_module(module_name)
    transport_cls = getattr(module, class_name)
    return transport_cls.from_args(target, args)


__all__ = [
    "CAN_TRANSPORTS",
    "add_args",
    "from_args",
    "infer_flavour",
    "split_flavour_target",
]

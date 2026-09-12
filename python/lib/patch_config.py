"""Local patch options shared by patcher entry points and Make."""

import argparse
from copy import copy
import json
import os
from pathlib import Path
import shlex
import sys


LOCAL_FILES = {"air10": "patch-airsense.config", "air11": "patch-airsense-s11.config"}
AIR10_LEGACY_OPTIONS = {
    "PATCH_CODE": ("--patch-fw-common-code", "y", "--patch-fw-graph", "y"),
    "PATCH_VAUTO_WRAPPER": ("--patch-fw-common-code", "y", "--patch-fw-vauto-wrapper", "y"),
    "PATCH_S": ("--patch-fw-squarewave", "y"),
    "PATCH_ASV_TASK_WRAPPER": ("--patch-fw-asv-wrapper", "y"),
    "PATCH_S10_LCD": ("--patch-fw-lcd", "y"),
    "PATCH_GRAPH_KEEP_SCREEN_ON": ("--patch-graph-keep-screen-on", "y"),
    "FORCE_DEPRECATED": ("--force-deprecated",),
}


def option_layers(platform):
    path = Path(__file__).absolute().parents[2] / LOCAL_FILES[platform]
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        text = ""
    legacy = []
    if platform == "air10":
        if "PATCH_TARGET_RH" in os.environ:
            legacy.extend(("--patch-target-rh", os.environ["PATCH_TARGET_RH"]))
        for name, options in AIR10_LEGACY_OPTIONS.items():
            if os.environ.get(name) == "1":
                legacy.extend(options)
    return [shlex.split(text, comments=True), legacy, shlex.split(os.environ.get(platform.upper() + "_PATCH_ARGS", ""))]


def parse_patch_args(parser, argv, platform):
    # Reuse the CLI actions so local options have identical types and choices.
    options = argparse.ArgumentParser(add_help=False, allow_abbrev=False)
    for action in parser._actions:
        if action.option_strings and not isinstance(action, argparse._HelpAction):
            options._add_action(copy(action))
    try:
        layers = option_layers(platform)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    for layer in layers:
        options.parse_args(layer)
    return parser.parse_args([arg for layer in layers for arg in layer] + list(sys.argv[1:] if argv is None else argv))


def main():
    parser = argparse.ArgumentParser(description="Track local patch options for Make.")
    parser.add_argument("platform", choices=LOCAL_FILES)
    parser.add_argument("input")
    parser.add_argument("stamp")
    args = parser.parse_args()
    contents = json.dumps({
        "options": option_layers(args.platform),
        "input": os.path.abspath(args.input),
    }) + "\n"
    path = Path(args.stamp)
    if not path.exists() or path.read_text(encoding="utf-8") != contents:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(contents, encoding="utf-8")


if __name__ == "__main__":
    main()

"""Local patch options shared by patcher entry points and Make."""

import argparse
from copy import copy
import json
import os
from pathlib import Path
import shlex
import sys


LOCAL_FILES = {"air10": "patch-airsense.config", "air11": "patch-airsense-s11.config",
               "s9": "patch-airsense-s9.config"}


def str2bool(value):
    if isinstance(value, bool):
        return value
    if value.lower() in ("yes", "y", "true", "t", "on", "1"):
        return True
    if value.lower() in ("no", "n", "false", "f", "off", "0"):
        return False
    raise argparse.ArgumentTypeError("expected y/n, yes/no, true/false, on/off or 1/0")


def local_options(platform):
    path = Path(__file__).absolute().parents[2] / LOCAL_FILES[platform]
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return []
    return shlex.split(text, comments=True)


def parse_patch_args(parser, argv, platform):
    # Reuse the CLI actions so local options have identical types and choices.
    options = argparse.ArgumentParser(add_help=False, allow_abbrev=False)
    for action in parser._actions:
        if action.option_strings and not isinstance(action, argparse._HelpAction):
            options._add_action(copy(action))
    try:
        local = local_options(platform)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    options.parse_args(local)
    return parser.parse_args(local + list(sys.argv[1:] if argv is None else argv))


def main():
    parser = argparse.ArgumentParser(description="Track patch options for Make.")
    parser.add_argument("platform", choices=LOCAL_FILES)
    parser.add_argument("input")
    parser.add_argument("stamp")
    parser.add_argument("options", nargs=argparse.REMAINDER, help="options Make passes to the patcher")
    args = parser.parse_args()
    contents = json.dumps({
        "options": [local_options(args.platform), args.options],
        "input": os.path.abspath(args.input),
    }) + "\n"
    path = Path(args.stamp)
    if not path.exists() or path.read_text(encoding="utf-8") != contents:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(contents, encoding="utf-8")


if __name__ == "__main__":
    main()

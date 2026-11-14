"""Local patch options and presets shared by patcher entry points and Make."""

import argparse
from copy import copy
import json
import os
from pathlib import Path
import shlex
import sys


REPO = Path(__file__).absolute().parents[2]
LOCAL_FILES = {"air10": "patch-airsense.config", "air11": "patch-airsense-s11.config",
               "s9": "patch-airsense-s9.config"}
# Preset directories in lookup order: a user preset hides a built-in preset of the same name.
PRESET_DIRS = ("presets/user", "presets")


def read_options(path):
    try:
        return shlex.split(path.read_text(encoding="utf-8"), comments=True)
    except ValueError as exc:
        raise ValueError("%s: %s" % (path, exc)) from None


def local_options(platform):
    try:
        return read_options(REPO / LOCAL_FILES[platform])
    except FileNotFoundError:
        return []


def preset_dirs(platform):
    return ["%s/%s" % (directory, platform) for directory in PRESET_DIRS]


def split_presets(tokens):
    """Separate the --preset selections from the other options."""
    presets, options = [], []
    tokens = iter(tokens)
    for token in tokens:
        if token == "--preset":
            preset = next(tokens, None)
            if preset is None:
                raise ValueError("argument --preset: expected one argument")
            presets.append(preset)
        elif token.startswith("--preset="):
            presets.append(token[len("--preset="):])
        else:
            options.append(token)
    return presets, options


def preset_path(platform, preset, directory):
    """File of a preset name, or of a path relative to directory."""
    if Path(preset).name != preset:
        return (directory / preset).resolve()
    for presets in preset_dirs(platform):
        path = REPO / presets / (preset + ".config")
        if path.is_file():
            return path.resolve()
    raise ValueError("preset %s not found in %s" % (preset, " or ".join(preset_dirs(platform))))


def preset_options(platform, presets, directory, parser=None, chain=()):
    """Options of the selected presets, in order.

    The presets that a preset selects precede its own options. A parser, when
    given, validates the options of each preset.
    """
    options = []
    for preset in presets:
        path = preset_path(platform, preset, directory)
        if path in chain:
            raise ValueError("preset cycle: " + " -> ".join(map(str, chain + (path,))))
        nested, own = split_presets(read_options(path))
        if parser is not None:
            try:
                parser.parse_args(own)
            except ValueError as exc:
                raise ValueError("%s: %s" % (path, exc)) from None
        options += preset_options(platform, nested, path.parent, parser, chain + (path,)) + own
    return options


def patch_args(platform, argv, local_parser=None, preset_parser=None):
    """Arguments in the order the patcher parses them.

    The local options file comes first, then the presets selected on the
    command line, then the other command-line arguments. The options of the
    local file and of the command line follow the presets each selects. Parsers,
    when given, validate the local options and the options of each preset.
    """
    local_presets, local = split_presets(local_options(platform))
    if local_parser is not None:
        local_parser.parse_args(local)
    presets, argv = split_presets(argv)
    return (preset_options(platform, local_presets, REPO, preset_parser) + local
            + preset_options(platform, presets, Path.cwd(), preset_parser) + argv)


def parse_patch_args(parser, argv, platform):
    """Parse patcher arguments with the local options file and presets.

    platform is the patch_options.Platform of the patcher.
    """
    # Listed in --help; patch_args() expands the selections before parsing.
    parser.add_argument("--preset", action="append", metavar="NAME|PATH", help=(
        "Apply the options of a preset: NAME.config from %s, or a file. Repeatable; "
        "later presets override earlier ones, and the other command-line options "
        "override presets." % " or ".join(preset_dirs(platform.name))))
    # Reuse the CLI actions so local options have identical types and choices.
    options = argparse.ArgumentParser(add_help=False, allow_abbrev=False)
    for action in parser._actions:
        if action.option_strings and not isinstance(action, argparse._HelpAction):
            options._add_action(copy(action))
    try:
        args = patch_args(platform.name, sys.argv[1:] if argv is None else argv,
                          options, platform.options_parser())
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    return parser.parse_args(args)


def main():
    parser = argparse.ArgumentParser(description="Track patch options for Make.")
    parser.add_argument("platform", choices=LOCAL_FILES)
    parser.add_argument("input")
    parser.add_argument("stamp")
    parser.add_argument("options", nargs=argparse.REMAINDER, help="options Make passes to the patcher")
    args = parser.parse_args()
    try:
        options = patch_args(args.platform, args.options)
    except (OSError, ValueError) as exc:
        sys.exit("%s: %s" % (parser.prog, exc))
    contents = json.dumps({"options": options, "input": os.path.abspath(args.input)}) + "\n"
    path = Path(args.stamp)
    if not path.exists() or path.read_text(encoding="utf-8") != contents:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(contents, encoding="utf-8")


if __name__ == "__main__":
    main()

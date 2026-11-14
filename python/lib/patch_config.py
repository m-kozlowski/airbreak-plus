"""Patch options from the local options file, presets and the command line.

Shared by the patcher entry points, Make and other consumers. Library
functions raise OSError or ValueError for invalid configuration; only
parse_patch_args() reports errors on the command line.
"""

import argparse
from copy import copy
from dataclasses import dataclass
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


class OptionsParser(argparse.ArgumentParser):
    """Parser for options alone that raises ValueError for invalid options."""

    def __init__(self):
        super().__init__(add_help=False, allow_abbrev=False)

    def error(self, message):
        raise ValueError(message)


def options_parser(platform):
    """Parser for the patch options of a patch_options.Platform."""
    return platform.add_arguments(OptionsParser())


@dataclass(frozen=True)
class Layer:
    """Options of one configuration source."""
    # "local", "preset" or "command line".
    source: str
    # Local options file or preset; None for the command line.
    path: Path
    options: tuple


def read_options(path):
    try:
        return shlex.split(path.read_text(encoding="utf-8"), comments=True)
    except ValueError as exc:
        raise ValueError("%s: %s" % (path, exc)) from None


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


def check(parser, options, path):
    if parser is not None:
        try:
            parser.parse_args(options)
        except ValueError as exc:
            raise ValueError("%s: %s" % (path, exc)) from None


def preset_layers(platform, presets, directory, parser=None, chain=()):
    """Layers of the selected presets, in order; the presets a preset selects precede it."""
    layers = []
    for preset in presets:
        path = preset_path(platform, preset, directory)
        if path in chain:
            raise ValueError("preset cycle: " + " -> ".join(map(str, chain + (path,))))
        nested, options = split_presets(read_options(path))
        check(parser, options, path)
        layers += preset_layers(platform, nested, path.parent, parser, chain + (path,))
        layers.append(Layer("preset", path, tuple(options)))
    return layers


def config_layers(platform, argv, local_parser=None, preset_parser=None):
    """Configuration layers of a platform name, lowest precedence first.

    The local options file comes first, then the presets selected on the
    command line, then the other command-line arguments. The presets that the
    local file or the command line selects precede it. Parsers, when given,
    validate the local options and the options of each preset.
    """
    path = REPO / LOCAL_FILES[platform]
    try:
        local = read_options(path)
    except FileNotFoundError:
        local = []
    local_presets, local = split_presets(local)
    check(local_parser, local, path)
    presets, argv = split_presets(argv)
    return (preset_layers(platform, local_presets, REPO, preset_parser)
            + [Layer("local", path, tuple(local))]
            + preset_layers(platform, presets, Path.cwd(), preset_parser)
            + [Layer("command line", None, tuple(argv))])


def patch_args(platform, argv, local_parser=None, preset_parser=None):
    """Arguments in the order the patcher parses them; see config_layers()."""
    return [option for layer in config_layers(platform, argv, local_parser, preset_parser)
            for option in layer.options]


def format_value(value, syntax):
    if syntax is not None and syntax.format is not None:
        return syntax.format(value)
    if isinstance(value, bool):
        return "y" if value else "n"
    return str(value)


def option_lines(platform, values):
    """Arguments of option values, one list per option, in declaration order.

    values maps option names without -- to parsed values. None leaves an
    option out; a repeatable option takes a list of values.
    """
    syntax = {patch.option: None for patch in platform.patches()}
    syntax.update((parameter.option, parameter.value) for parameter in platform.all_parameters())
    unknown = [option for option in values if option not in syntax]
    if unknown:
        raise ValueError("unknown option: " + ", ".join("--" + option for option in unknown))
    lines = []
    for option, value_syntax in syntax.items():
        value = values.get(option)
        if value is None:
            continue
        for item in value if value_syntax is not None and value_syntax.repeat else (value,):
            lines.append(["--" + option, format_value(item, value_syntax)])
    return lines


def option_args(platform, values):
    """Command-line arguments of option values; see option_lines()."""
    return [arg for line in option_lines(platform, values) for arg in line]


def option_text(platform, values):
    """Options file text of option values, one option per line; see option_lines()."""
    return "".join(shlex.join(line) + "\n" for line in option_lines(platform, values))


def parse_patch_args(parser, argv, platform):
    """Parse patcher arguments with the local options file and presets.

    platform is the patch_options.Platform of the patcher.
    """
    # Listed in --help; config_layers() expands the selections before parsing.
    parser.add_argument("--preset", action="append", metavar="NAME|PATH", help=(
        "Apply the options of a preset: NAME.config from %s, or a file. Repeatable; "
        "later presets override earlier ones, and the other command-line options "
        "override presets." % " or ".join(preset_dirs(platform.name))))
    # Reuse the CLI actions so local options have identical types and choices.
    local_parser = OptionsParser()
    for action in parser._actions:
        if action.option_strings and not isinstance(action, argparse._HelpAction):
            local_parser._add_action(copy(action))
    try:
        args = patch_args(platform.name, sys.argv[1:] if argv is None else argv,
                          local_parser, options_parser(platform))
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

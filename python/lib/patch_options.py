"""Patch option declarations shared by the patchers and other consumers.

Declarations describe the available options only. Importing them requires no
firmware image or toolchain and does not import a firmware patcher.
"""

import argparse
from dataclasses import dataclass
import importlib
from typing import Callable


PLATFORM_MODULES = {"air10": "as10_patch_options", "air11": "as11_patch_options",
                    "s9": "s9_patch_options"}


def str2bool(value):
    if isinstance(value, bool):
        return value
    if value.lower() in ("yes", "y", "true", "t", "on", "1"):
        return True
    if value.lower() in ("no", "n", "false", "f", "off", "0"):
        return False
    raise argparse.ArgumentTypeError("expected y/n, yes/no, true/false, on/off or 1/0")


def dest(option):
    return option.replace("-", "_")


@dataclass(frozen=True)
class Value:
    """Command-line syntax of an option value."""
    type: Callable = None
    metavar: str = None
    choices: object = None
    repeat: bool = False
    # Text of a parsed value, where y/n for booleans and str() otherwise do not fit.
    format: Callable = None


@dataclass(frozen=True)
class Parameter:
    option: str
    description: str
    value: Value
    default: object = None


@dataclass(frozen=True)
class Patch:
    """A patch selected by a y/n switch; its settings are its parameters."""
    option: str
    description: str
    default: bool
    method: str
    requires: tuple = ()
    deprecated: str = None
    parameters: tuple = ()


# Unset patch switches are None on platforms that declare this parameter.
ALL_PATCHES = Parameter("all-patches", "Fallback for patch switches that are not set "
                        "individually; otherwise built-in defaults apply.",
                        Value(str2bool, "y/n"))


@dataclass(frozen=True)
class Phase:
    name: str
    patches: tuple


@dataclass(frozen=True)
class Platform:
    name: str
    # Phases and patches in execution order.
    phases: tuple
    parameters: tuple = ()

    def __post_init__(self):
        patches = {patch.option for patch in self.patches()}
        options = patches | {parameter.option for parameter in self.all_parameters()}
        if len(options) != len(list(self.patches())) + len(list(self.all_parameters())):
            raise ValueError("%s: duplicate option" % self.name)
        for patch in self.patches():
            for option in patch.requires:
                if option not in patches:
                    raise ValueError("%s: --%s requires unknown patch --%s" % (self.name, patch.option, option))

    @property
    def fallback(self):
        return ALL_PATCHES in self.parameters

    def patches(self):
        for phase in self.phases:
            yield from phase.patches

    def patch(self, option):
        for patch in self.patches():
            if patch.option == option:
                return patch
        raise KeyError(option)

    def all_parameters(self):
        """Platform parameters followed by the parameters of each patch."""
        yield from self.parameters
        for patch in self.patches():
            yield from patch.parameters

    def add_arguments(self, parser):
        """Add the patch switches and parameters to an argparse parser."""
        for patch in self.patches():
            add_argument(parser, patch.option,
                         "%s (default: %s)" % (patch.description,
                                               "enabled" if patch.default else "disabled"),
                         Value(str2bool, "Y/n" if patch.default else "y/N"),
                         None if self.fallback else patch.default)
        for parameter in self.parameters:
            add_argument(parser, parameter.option, parameter.description, parameter.value,
                         parameter.default)
        for patch in self.patches():
            if patch.parameters:
                group = parser.add_argument_group(patch.option + " parameters")
                for parameter in patch.parameters:
                    add_argument(group, parameter.option, parameter.description, parameter.value,
                                 parameter.default)
        return parser

    def selected(self, args, patch):
        value = getattr(args, dest(patch.option))
        if value is None and self.fallback:
            value = patch.default if args.all_patches is None else args.all_patches
        return value

    def dependency_errors(self, args):
        errors = []
        for patch in self.patches():
            if patch.requires and self.selected(args, patch):
                missing = [option for option in patch.requires
                           if not self.selected(args, self.patch(option))]
                if missing:
                    errors.append("--%s requires %s" % (
                        patch.option, " and ".join("--" + option for option in missing)))
        return errors


def add_argument(parser, option, description, value, default):
    kwargs = {"default": default, "help": description.replace("%", "%%")}
    if value.type is not None:
        kwargs["type"] = value.type
    if value.metavar is not None:
        kwargs["metavar"] = value.metavar
    if value.choices is not None:
        kwargs["choices"] = value.choices
    if value.repeat:
        kwargs["action"] = "append"
    parser.add_argument("--" + option, **kwargs)


def load(name):
    """Return the declarations of a platform: air10, air11 or s9."""
    return importlib.import_module("." + PLATFORM_MODULES[name], __package__).PLATFORM

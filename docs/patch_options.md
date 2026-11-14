# Patch Options

## Name

`patch-airsense.py`, `patch-airsense-s11.py`, `patch-airsense-s9.py` - Air 10, Air11 and S9
patcher configuration.

## Contents

- [Synopsis](#synopsis)
- [Description](#description)
- [Files](#files)
- [Presets](#presets)
- [Precedence](#precedence)
- [Make Variables](#make-variables)
- [Examples](#examples)
- [See Also](#see-also)

## Synopsis

```text
make [TARGET] [AIR10_PATCH_ARGS='OPTIONS']
make as11 [AIR11_PATCH_ARGS='OPTIONS']
make s9|s9_lcd [S9_PATCH_ARGS='OPTIONS']
patch-airsense.py INPUT OUTPUT PATCH [OPTIONS]
patch-airsense-s11.py INPUT OUTPUT PATCH [OPTIONS]
patch-airsense-s9.py INPUT OUTPUT PATCH [OPTIONS]
```

| Argument | Meaning |
|----------|---------|
| `INPUT` | Original firmware image |
| `OUTPUT` | Patched firmware image |
| `PATCH` | Literal operation name selecting firmware patching |
| `TARGET` | Make target; default builds `build/stm32-patched.bin` and `build/stm32-plus.bin`; `as11` builds the Air11 image; `s9` and `s9_lcd` build `build/stm32-s9.bin` and `build/stm32-s9-lcd.bin` |
| `OPTIONS` | Patcher options, using the same syntax as the CLI |

## Description

Configures patch selection and extended patch parameters for Python entry
points, shell wrappers, and Make builds. Supports persistent local settings,
presets, and one-off overrides.

## Files

| Platform | Local options file, relative to repository root | Example |
|----------|-------------------------------------------------|---------|
| Air 10 | `patch-airsense.config` | [Air 10 options](../patch-airsense.config.example) |
| Air11 | `patch-airsense-s11.config` | [Air11 options](../patch-airsense-s11.config.example) |
| S9 | `patch-airsense-s9.config` | [S9 options](../patch-airsense-s9.config.example) |

Local options files are optional and ignored by Git. They are loaded from the
repository root, independently of the working directory. Contents use CLI syntax:
whitespace-separated options, quoted values, and `#` comments. Unknown options
and invalid values are errors. The `.config.example` files are templates;
only `.config` files are loaded.

Each output has a separate `.config` state file. Changing or removing local
options, the contents of selected [presets](#presets) or
[Make variables](#make-variables) regenerates the affected image. Changing the
input image, including selecting another `AS11_FIRMWARE` path, also
regenerates the output.

Each patcher's `--help` lists available options and defaults.

## Presets

A preset is a file of patch options in the local options file syntax.
`--preset NAME` or `--preset PATH` selects one; the option is repeatable.

| Preset | File, relative to repository root |
|--------|-----------------------------------|
| Built-in | `presets/PLATFORM/NAME.config` |
| User | `presets/user/PLATFORM/NAME.config`, ignored by Git |

`PLATFORM` is `air10`, `air11` or `s9`. A user preset hides a built-in preset
of the same name. A value with a directory part, such as `./night.config`,
selects that file; a relative path is relative to the file that selects it, or
to the working directory on the command line.

Presets contain patch switches and patch parameters only; other patcher
options, such as `--overwrite`, are errors. A preset can select other presets
with `--preset`; selecting a preset that is already being applied, directly or
through other presets, is an error.

| Platform | Built-in preset | Options |
|----------|-----------------|---------|
| Air 10 | `plus` | Optional therapy payloads of `build/stm32-plus.bin` |

## Precedence

Lowest to highest; applies to Make builds, wrappers and Python entry points:

| Priority | Source |
|----------|--------|
| 1 | Built-in Python defaults |
| 2 | Local options file |
| 3 | Presets selected on the command line, in the order given |
| 4 | Other CLI arguments, including the options Make passes; see [Make variables](#make-variables) |

Presets that the local options file or a preset selects precede the options of
that file. Command-line options override the selected presets wherever
`--preset` appears on the command line.

Repeated scalar options use the last value. Air11 `--rpc-permission` rules
override earlier rules for the same target/selector. See
[RPC permission selectors](as11/rpc_protocol.md#rpc-permission-selectors).
Air11 `--all-patches` supplies the fallback for individually unset patch switches.

## Make Variables

| Variable | Value |
|----------|-------|
| `AIR10_PATCH_ARGS` | Air 10 options in CLI syntax |
| `AIR11_PATCH_ARGS` | Air11 options in CLI syntax |
| `S9_PATCH_ARGS` | S9 options in CLI syntax |
| `PATCH_ARGS` | Default for each variable above that is not set |

Make passes the variable to the patcher as CLI arguments, after the options
selected by the target, such as the `plus` preset of `build/stm32-plus.bin`.
An option the patcher does not have is an error. Variables can be set in the
environment or on the Make command line; command-line assignments override
environment values. Payload dependencies are validated after applying overrides.

## Examples

Create local defaults from the template, then build with a one-off override:

```sh
cp patch-airsense-s11.config.example patch-airsense-s11.config
make as11 AIR11_PATCH_ARGS='--patch-header-clock n'
```

Set an environment override, then supersede it for one build:

```sh
export AIR11_PATCH_ARGS='--patch-header-clock n'
make as11
make as11 AIR11_PATCH_ARGS='--patch-header-clock y'
```

Inspect available switches, then patch an image directly:

```sh
patch-airsense-s11.py --help
patch-airsense-s11.py as11.bin build/no-clock.bin PATCH --patch-header-clock n
```

The Air 10 and S9 option lists are available through `patch-airsense.py --help`
and `patch-airsense-s9.py --help`.

## See Also

[Air 10 patching guide](guide/patching.md),
[Air11 patching guide](guide/as11/patching.md),
[Air 10 configuration example](../patch-airsense.config.example),
[Air11 configuration example](../patch-airsense-s11.config.example),
[S9 configuration example](../patch-airsense-s9.config.example).

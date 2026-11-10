# Patch Options

## Name

`patch-airsense.py`, `patch-airsense-s11.py` - Air 10 and Air11 patcher configuration.

## Contents

- [Synopsis](#synopsis)
- [Description](#description)
- [Files](#files)
- [Precedence](#precedence)
- [Environment](#environment)
- [Examples](#examples)
- [See Also](#see-also)

## Synopsis

```text
make [TARGET] [AIR10_PATCH_ARGS='OPTIONS']
make as11 [AIR11_PATCH_ARGS='OPTIONS']
patch-airsense.py INPUT OUTPUT PATCH [OPTIONS]
patch-airsense-s11.py INPUT OUTPUT PATCH [OPTIONS]
```

| Argument | Meaning |
|----------|---------|
| `INPUT` | Original firmware image |
| `OUTPUT` | Patched firmware image |
| `PATCH` | Literal operation name selecting firmware patching |
| `TARGET` | Make target; default builds `build/stm32-patched.bin` and `build/stm32-plus.bin`; `as11` builds the Air11 image |
| `OPTIONS` | Patcher options, using the same syntax as the CLI |

## Description

Configures patch selection and extended patch parameters for Python entry
points, shell wrappers, and Make builds. Supports persistent local settings,
one-off overrides, and Air 10 legacy environment variables.

## Files

| Platform | Local options file, relative to repository root | Example |
|----------|-------------------------------------------------|---------|
| Air 10 | `patch-airsense.config` | [Air 10 options](../patch-airsense.config.example) |
| Air11 | `patch-airsense-s11.config` | [Air11 options](../patch-airsense-s11.config.example) |

Local options files are optional and ignored by Git. They are loaded from the
repository root, independently of the working directory. Contents use CLI syntax:
whitespace-separated options, quoted values, and `#` comments. Unknown options
and invalid values are errors. The `.config.example` files are templates;
only `.config` files are loaded.

Each output has a separate `.config` state file. Changing or removing local
options, patch-argument variables, or Air 10 legacy variables regenerates the
affected image. Changing the input image, including selecting another
`AS11_FIRMWARE` path, also regenerates the output.

Each patcher's `--help` lists available options and defaults.

## Precedence

Lowest to highest; applies to both wrappers and Python entry points:

| Priority | Source |
|----------|--------|
| 1 | Built-in Python defaults |
| 2 | Local options file |
| 3 | Air 10 legacy environment variables |
| 4 | `AIR10_PATCH_ARGS` or `AIR11_PATCH_ARGS` |
| 5 | Explicit CLI arguments |

Repeated scalar options use the last value. Air11 `--rpc-permission` rules
override earlier rules for the same target/selector. See
[RPC permission selectors](as11/rpc_protocol.md#rpc-permission-selectors).
Air11 `--all-patches` supplies the fallback for individually unset patch switches.

## Environment

| Variable | Value |
|----------|-------|
| `AIR10_PATCH_ARGS` | Air 10 options in CLI syntax |
| `AIR11_PATCH_ARGS` | Air11 options in CLI syntax |

Make command-line assignments override environment values.

Air 10 legacy variables:

| Variable | Options enabled when set to `1` |
|----------|--------------------------------|
| `PATCH_VAUTO_WRAPPER` | `--patch-fw-vauto-wrapper y` |
| `PATCH_S` | `--patch-fw-squarewave y` |
| `PATCH_ASV_TASK_WRAPPER` | `--patch-fw-asv-wrapper y` |
| `PATCH_FALL_TIME` | `--patch-fall-time y` |
| `PATCH_ST_IBR` | `--patch-st-ibr y` |
| `PATCH_S10_LCD` | `--patch-fw-lcd y` |
| `PATCH_GRAPH_KEEP_SCREEN_ON` | `--patch-graph-keep-screen-on y` |
| `FORCE_DEPRECATED` | `--force-deprecated` |

Unset variables and values other than `1` leave earlier settings unchanged.
`PATCH_TARGET_RH` supplies `--patch-target-rh VALUE` whenever set.
Payload dependencies are validated after applying overrides.

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

The Air 10 option list is available through `patch-airsense.py --help`.

## See Also

[Air 10 patching guide](guide/patching.md),
[Air11 patching guide](guide/as11/patching.md),
[Air 10 configuration example](../patch-airsense.config.example),
[Air11 configuration example](../patch-airsense-s11.config.example).

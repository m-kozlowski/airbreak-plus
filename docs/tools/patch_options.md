# Patch Options

Local configuration and command-line overrides for the Air10 and Air11 patchers.

## Synopsis

```sh
make [TARGET] AIR10_PATCH_ARGS='OPTIONS'
make as11 AIR11_PATCH_ARGS='OPTIONS'
python3 python/patch-airsense.py INPUT OUTPUT PATCH [OPTIONS]
python3 python/patch-airsense-s11.py INPUT OUTPUT PATCH [OPTIONS]
```

## Files

| Platform | Local options file, relative to repository root | Example |
|----------|-------------------------------------------------|---------|
| Air10 | `patch-airsense.config` | [Air10 options](../../patch-airsense.config.example) |
| Air11 | `patch-airsense-s11.config` | [Air11 options](../../patch-airsense-s11.config.example) |

Optional, ignored by Git, and located independently of the working directory.
Contents use CLI syntax: whitespace-separated options, quoted values, and `#`
comments. Unknown options and invalid values are errors.

Copy the corresponding `.config.example` file to `.config` and edit the options.
Example files are not loaded automatically.

## Precedence

Lowest to highest; applies to both wrappers and Python entry points:

| Priority | Source |
|----------|--------|
| 1 | Built-in Python defaults |
| 2 | Local options file |
| 3 | Air10 legacy environment variables |
| 4 | `AIR10_PATCH_ARGS` or `AIR11_PATCH_ARGS` |
| 5 | Explicit CLI arguments |

Repeated scalar options use the last value. Air11 `--rpc-permission` rules
override earlier rules for the same target/selector. See
[RPC permission selectors](../as11/rpc_protocol.md#rpc-permission-selectors).
Air11 `--all-patches` supplies the fallback for individually unset patch switches.

## Environment

| Variable | Value |
|----------|-------|
| `AIR10_PATCH_ARGS` | Air10 options in CLI syntax |
| `AIR11_PATCH_ARGS` | Air11 options in CLI syntax |

Make command-line assignments override environment values:

```sh
AIR11_PATCH_ARGS='--patch-header-clock n' make as11
make as11 AIR11_PATCH_ARGS='--patch-header-clock n'
```

Air10 legacy variables:

| Variable | Options enabled when set to `1` |
|----------|--------------------------------|
| `PATCH_CODE` | `--patch-fw-common-code y --patch-fw-graph y` |
| `PATCH_VAUTO_WRAPPER` | `--patch-fw-common-code y --patch-fw-vauto-wrapper y` |
| `PATCH_S` | `--patch-fw-squarewave y`; requires common code and Custom VAuto |
| `PATCH_ASV_TASK_WRAPPER` | `--patch-fw-asv-wrapper y` |
| `PATCH_S10_LCD` | `--patch-fw-lcd y` |
| `PATCH_GRAPH_KEEP_SCREEN_ON` | `--patch-graph-keep-screen-on y` |
| `FORCE_DEPRECATED` | `--force-deprecated` |

Unset variables and values other than `1` leave earlier settings unchanged.
`PATCH_TARGET_RH` supplies `--patch-target-rh VALUE` whenever set.
Payload dependencies are validated after applying overrides.

## Make Rebuilds

Each output has a separate `.config` state file. Changing or removing local
options, patch-argument variables, or Air10 legacy variables regenerates the
affected image. Changing the input image, including selecting another
`AS11_FIRMWARE` path, also regenerates the output.

## Option Lists

```sh
python3 python/patch-airsense.py --help
python3 python/patch-airsense-s11.py --help
```

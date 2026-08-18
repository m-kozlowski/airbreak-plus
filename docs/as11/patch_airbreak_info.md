# AirbreakInfo

`patch-airbreak-info` adds the read-only `AirbreakInfo` root to JSON RPC through
the shared RPC dispatcher. It identifies the Airbreak build and
describes changes whose runtime meaning is not represented by the stock
firmware identity.

Query it with the normal `Get` method. `_SID` remains the source for the stock
firmware identity:

```bash
./python/as11_config.py -d can:/dev/ttyACM0 get AirbreakInfo _SID
```

## Object format

| Field | Type | Meaning |
|-------|------|---------|
| `schema` | integer | `AirbreakInfo` object-format version |
| `version` | string | Airbreak build version |
| `builtAt` | string | UTC time when the patched image manifest was generated |
| `patches` | object | enabled patches grouped into `ok`, `warn`, and `skip` arrays; empty groups are omitted |
| `disabledFeatures` | array | stock features removed because their resources were reclaimed |
| `dataItems` | object | stock DataItems assigned a different runtime purpose |

Patch names omit the `patch-` command-line prefix.

Each `dataItems` member is keyed by its RPC short selector and has these
fields:

| Field | Type | Meaning |
|-------|------|---------|
| `name` | string | Airbreak runtime meaning |
| `owner` | string | patch that assigned the meaning |
| `stock` | string | original long name, when available |
| `menu.section` | string | custom-settings menu section |
| `menu.modes` | array | `_MOP` values for which the custom menu row is visible |
| `enum` | array | exact enum strings accepted and returned by JSON RPC |

A client may display a DataItem without `enum`, but must not infer an editor
from its name.

For example, an ASV backup-rate build with custom settings reports `_RIF` as
`ASVBackupRateEnable`, owned by `asv-backup-rate`, and reports
`Reminders` under `disabledFeatures`.

The patcher uses `AIRBREAK_VERSION` when that environment variable is set.
Otherwise it records `git describe --tags --always --dirty`; builds made
without repository metadata use `unknown`. `builtAt` uses the current
UTC time or `SOURCE_DATE_EPOCH` when reproducible build input is supplied.

# Air11 RPC Provider Interface

The Airbreak RPC dispatcher adds named root objects to the stock JSON RPC
`Get` and `Set` methods. A provider is a compiled payload that exports one or
more `rpc_object_t` descriptors. The Python patcher registers their final ELF
addresses with the shared dispatcher.

For example, a provider named `ExampleEnabled` is queried and changed through
the existing methods:

```bash
./python/as11_config.py -d can:/dev/ttyACM0 get ExampleEnabled
./python/as11_config.py -d can:/dev/ttyACM0 \
    set ExampleEnabled true --type bool
```

The dispatcher adds object names, not new JSON RPC method names.

## Runtime model

The dispatcher installs one registration in the firmware profile-formatter
registry during startup. Its patcher-populated table contains absolute
addresses of provider-owned `rpc_object_t` descriptors and ends with a
`0xFFFFFFFF` sentinel.

For each requested root name, the dispatcher:

1. compares the exact, case-sensitive name and length
2. creates a native formatter backed by the matching `rpc_object_t`
3. forwards availability, value, schema, validation, and error operations to
   the provider callbacks

The table currently has capacity for eight objects. The patcher rejects a
larger registration set.

## Provider ABI

The ABI is declared in [`patches/as11/rpc_object.h`](../../patches/as11/rpc_object.h):

```c
typedef struct {
    const char *name;
    unsigned short name_length;
    unsigned short dataitem_var_id;
    void *context;
    rpc_object_is_available_t is_available;
    rpc_object_write_json_t write_value;
    rpc_object_write_json_t write_schema;
    rpc_object_apply_json_t apply_value;
    rpc_object_write_error_t write_error;
} rpc_object_t;
```

| Member | Required | Contract |
|--------|----------|----------|
| `name` | yes | Stable, NUL-terminated root name. |
| `name_length` | yes | Name length without the terminating NUL. |
| `dataitem_var_id` | yes | DataItem reference used by native schema machinery; use `RPC_OBJECT_NO_DATAITEM` for an independent object. |
| `context` | no | Provider-owned pointer passed unchanged to every callback. |
| `is_available` | no | Nonzero makes the object available; a missing callback means always available. |
| `write_value` | yes | Emits exactly one JSON value and returns the encoder result. |
| `write_schema` | no | Emits the object's JSON schema; a missing callback emits `{}`. |
| `apply_value` | no | Validates and applies the raw JSON value from `Set`; nonzero accepts it. A missing callback makes the object read-only. |
| `write_error` | no | Emits the value included in a failed `Set` response; a missing callback echoes the rejected JSON value. |

| Operation | Provider calls |
|-----------|----------------|
| successful `Get` | `is_available`, then `write_value` |
| accepted `Set` | `apply_value`, then `write_value` for the result |
| rejected `Set` | `apply_value`, then `write_error` for the failure result |
| schema output | `is_available`, then `write_schema` |

The descriptor, its name, its context, and any data referenced by callbacks
must remain valid for the lifetime of the firmware process. Payload-owned
objects therefore normally use static storage.

`dataitem_var_id` does not automatically read or write a DataItem. Provider
callbacks remain responsible for the object's behavior. Independent objects
and objects with an explicit `write_schema` normally use
`RPC_OBJECT_NO_DATAITEM`.

## JSON spans

`apply_value` and `write_error` receive the complete JSON value as a half-open
byte span:

```c
typedef struct {
    const unsigned char *begin;
    const unsigned char *end;
} rpc_json_span_t;
```

The bytes are not NUL-terminated and have not been converted to a C type. A
JSON boolean arrives as `true` or `false`; a number arrives as its JSON decimal
representation; strings include their JSON quotes and escaping.

Compare or parse only the bytes in `[begin, end)`. Returning zero from
`apply_value` rejects the value and produces the stock
`SettingApplicationFailure` response.

Writers emit a complete JSON value with the native encoder. Static JSON can be
written with `json_encoder_write_raw_span()`:

```c
static int write_json(
    void *context,
    void *encoder,
    const unsigned char *begin,
    const unsigned char *end)
{
    const rpc_json_span_t span = {begin, end};

    return json_encoder_write_raw_span(context, encoder, &span);
}
```

## Boolean provider example

This provider exposes a boolean backed by a firmware DataItem. Replace
`VAR_ID_EXAMPLE` with the resolved variable macro used by the feature.

```c
#include "stubs.h"
#include "vars.h"
#include "rpc_object.h"

#define EXAMPLE_VAR_ID VAR_ID_EXAMPLE

static int span_equals(const rpc_json_span_t *span, const char *text)
{
    const unsigned char *cursor = span->begin;

    while (*text != '\0' && cursor != span->end) {
        if (*cursor++ != (unsigned char)*text++)
            return 0;
    }
    return *text == '\0' && cursor == span->end;
}

static int example_write_value(void *context, void *encoder)
{
    static const unsigned char json_false[] = "false";
    static const unsigned char json_true[] = "true";
    const unsigned char *begin;
    const unsigned char *end;
    rpc_json_span_t span;

    if (DataItem_read_value_by_id(EXAMPLE_VAR_ID) != 0) {
        begin = json_true;
        end = json_true + sizeof(json_true) - 1u;
    } else {
        begin = json_false;
        end = json_false + sizeof(json_false) - 1u;
    }
    span.begin = begin;
    span.end = end;
    return json_encoder_write_raw_span(context, encoder, &span);
}

static int example_write_schema(void *context, void *encoder)
{
    static const unsigned char schema[] = "{\"type\":\"boolean\"}";
    const rpc_json_span_t span = {
        schema,
        schema + sizeof(schema) - 1u,
    };

    return json_encoder_write_raw_span(context, encoder, &span);
}

static int example_apply_value(
    void *context, const rpc_json_span_t *value)
{
    if (span_equals(value, "true")) {
        DataItem_write_raw_by_id(EXAMPLE_VAR_ID, 1);
        return 1;
    }
    if (span_equals(value, "false")) {
        DataItem_write_raw_by_id(EXAMPLE_VAR_ID, 0);
        return 1;
    }
    return 0;
}

static const char example_name[] = "ExampleEnabled";

const rpc_object_t example_rpc_object
    __attribute__((used, section(".rodata.rpc_object"))) = {
        .name = example_name,
        .name_length = sizeof(example_name) - 1u,
        .dataitem_var_id = RPC_OBJECT_NO_DATAITEM,
        .write_value = example_write_value,
        .write_schema = example_write_schema,
        .apply_value = example_apply_value,
    };

void __attribute__((section(".text.0.main")))
start(void)
{
    /* Payload linker entry; registration uses example_rpc_object. */
}
```

Remove `example_apply_value` from the descriptor to expose the same object as
read-only. An object value may itself be a JSON object or array; the provider
still emits it as one complete value.

## Build registration

For a source file named `patches/as11/example.c`, use the payload name
`as11_example`.

1. Add `as11_example` to every applicable `AS11_PAYLOADS_<version>` list in
   `Makefile.as11`.
2. Include `stubs.h` and `rpc_object.h` in the provider source.
3. Add every native firmware function used by the provider to each applicable
   `stubs_<version>.S` file and declare it in `stubs.h`.
4. Build the final versioned ELF and binary with `make as11-binaries`.

The standard payload rules compile the source once per listed APPX version,
allocate code-cave storage, and expose final symbol addresses through the ELF.

## Patcher registration

The patcher resolves the provider descriptor from the final ELF. It registers
the object before injecting the payload:

```python
def patch_example_rpc(self):
    ver = self._payload_version_key()
    data, _ = self._load_versioned_bin("as11_example")
    if data is None:
        return PatchOutcome.skip("compiled payload unavailable")

    elf_path = self._versioned_artifact_path(
        "as11_example", "elf", ver
    )
    rpc_object = self._elf_symbol_addr(
        elf_path, "example_rpc_object"
    )

    outcome = self.rpc_object_register(rpc_object, "ExampleEnabled")
    if outcome.status != "OK":
        return outcome

    self._inject_payload("as11_example", data)
    return PatchOutcome.ok("Get/Set ExampleEnabled")
```

The runtime name comes from `rpc_object_t.name`. The name passed to
`rpc_object_register()` is only used in patcher output.

Resolve payload symbols and validate provider-specific firmware anchors before
calling `rpc_object_register()`. Registration performs the shared dispatcher
preflight. If the dispatcher has not been ported to the input APPX, the
provider returns `SKIP` before modifying the image.

Add the patch function to `PATCH_LIST` when it needs an independent command-line
switch. A provider whose manifest or parameters depend on other completed
patches may defer this function to the finalization phase, as
`AirbreakInfo` does.

The shared `patch_rpc_dispatcher()` finalizer runs after providers have
registered their objects. It injects the dispatcher, writes the object table,
and replaces the versioned formatter-registry initializer entry.

## Version port

The dispatcher requires these native symbols in each `stubs_<version>.S`:

- `heap_alloc`
- `rpc_profile_json_formatter_registry_ctor`
- `rpc_profile_json_formatter_registration_ctor`
- `json_encoder_write_raw_span`

It also requires `rpc_dispatcher.init_entry` in
`python/lib/as11_patch_versions.py`. This is the signed-REL32 initializer entry
that originally invokes `rpc_profile_json_formatter_registry_ctor`.

A provider needs additional version data only for the native functions or
firmware hooks that it uses itself. A provider that only emits patch-time JSON
can use identical C source across APPX versions; `AirbreakInfo` is the current
reference implementation.

# Air 10 Patch Payloads

Compiled Air 10 patches are linked into known erased CDX ranges. The build
system measures every payload, allocates non-overlapping addresses, links final
binaries at those addresses, and generates one layout per CDX version.

## Supported versions

The payload build currently defines layouts for:

- SX567-0302
- SX567-0305
- SX567-0306
- SX567-0401
- SX567-0402

The Makefile `PAYLOADS_<version>` lists are the source of truth for which
payloads are built for each version. A payload may be built and assigned space
without being enabled in a particular output image.

## Code caves

`patches/s10_code_caves.tsv` lists available half-open ranges:

```text
cdx_version  region  storage_start  storage_end  image_base  runtime_base
0402         cdx     0x080FCF98     0x080FFFFE   0x08000000  0x08000000
```

The format supports multiple sorted ranges per version. Ranges must start on a
4-byte boundary and must not overlap. The current registry contains one range
per supported version. `image_base` and `runtime_base` describe how stored
payload bytes map into the execution address space. They are equal for the
current CDX regions, so storage and runtime addresses are identical.

## Build pipeline

The payload layout is generated in two link passes:

1. compile versioned source with `CDX_VER_<version>`
2. probe-link each payload at `0x08000000`
3. convert each probe ELF to a binary and record its measured size
4. allocate payloads with first fit, from the lowest address of the first cave
5. align each allocation to 4 bytes
6. write `build/payload_layout_<version>.tsv`
7. link final ELFs at their assigned addresses
8. convert final ELFs to the binaries consumed by the patchers

The allocator processes payloads in the order emitted by
`payload_sizes_<version>.tsv`. It advances upward through each cave and moves to
the next cave when the current payload does not fit. Allocation fails if no cave
has enough remaining space.

Example generated layout:

```text
payload                  runtime      size  runtime_end  storage      storage_end
mop_callback_dispatcher  0x080FCF98   ...   ...          0x080FCF98   ...
vid_spoof                 ...          ...   ...          ...          ...
```

Inspect a layout with:

```bash
make binaries
cat build/payload_layout_0402.tsv
```

## Patcher checks

Both patchers consume the generated TSV layout. Before injection they verify:

- the payload exists in the selected CDX layout
- the binary size matches the measured layout size
- the final ELF is linked at the assigned runtime address
- flattening the final ELF reproduces the supplied binary exactly
- the complete destination range contains erased `0xFF` bytes
- the storage range lies inside the selected firmware region

Patch code resolves entry points and ABI objects from the final ELF symbol
table. Source code and patcher functions do not maintain duplicate payload
addresses.

## Versioned firmware symbols

Compiled payloads use two versioned symbol families.

### Variable IDs

`patches/s10_vars.h` selects one generated header:

```c
#if defined(CDX_VER_0402)
#include "s10_vars_0402.h"
#endif
```

The selected header defines `VAR_ID_<UART_NAME>` values for that CDX version.
The values come from the firmware globals[23] UART-name table. Payload source
uses these macros instead of embedding numeric IDs that can move between CDX
versions.

Reclaimed custom-setting assignments are not firmware-version constants. Their
resolved IDs are written to payload ABI slots by the patcher.

### Function and RAM symbols

`patches/s10_<version>_stubs.S` defines firmware function entry points and known
static RAM symbols for one CDX version. Payloads call those symbols through the
normal linker. New firmware entry points belong in the versioned stub file, not
in Makefile argument lists or generic C source.

## ABI slots

An ABI slot carries data that is known only while patching the selected image.
Current uses include:

- claimed custom-setting var IDs
- the original Square Wave handler pointer
- the generated custom menu registry address
- the custom settings globals[16] group index

An erased var-ID slot uses `0xFFFF`. Payloads must define an explicit fallback
for that state so they can run without `custom_settings`. Pointer slots use
`0xFFFFFFFF` when no target has been installed.

Firmware-stable var IDs belong in `s10_vars`. Firmware-stable function entry
points belong in versioned stubs. Neither should be passed through a new ABI
slot.

## MOP callback dispatcher

MOP-dependent payloads share one standalone dispatcher instead of replacing the
same firmware callback independently.

The patcher resolves `MOP.callback_id`, preserves the original callback pointer,
and replaces that callback-table entry with the dispatcher. Its handler table
contains:

1. the original stock callback
2. registered feature handlers
3. a `0xFFFFFFFF` sentinel

The stock callback therefore updates normal mode state before custom handlers
run. Current registered users are VID spoof and custom menu visibility.

## Payload families

| Family | Build behavior |
|--------|----------------|
| common-code dependent | imports symbols from the final `common_code` ELF during final linking |
| standalone | links source, optional `<payload>_abi.S`, and versioned stubs through the generic rule |
| dispatcher | owns a shared firmware callback and calls a generated handler list |

The generated layout is shared by all families.

## Adding a payload

1. add the payload name to each supported `PAYLOADS_<version>` list
2. provide source with a `start` entry point
3. include `s10_vars.h` for firmware variable IDs
4. add required firmware functions to each supported versioned stub
5. add an ABI assembly file only for patch-time values
6. add a generic build rule or use the standalone rule
7. inject by payload name through the patcher layout helper
8. resolve hook and ABI symbols from the final ELF
9. verify generated layouts and all intended output images

Do not add a fixed payload address to source, patcher code, or a second Makefile
variable. Code-cave ownership belongs to `s10_code_caves.tsv` and the generated
layout.

See [Custom settings](custom_settings.md) for menu and persistence integration.

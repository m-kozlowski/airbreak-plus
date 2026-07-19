# Air11 Patch Payloads

Compiled Air11 patches are linked into known erased APPL ranges. The build
system measures every payload, allocates non-overlapping addresses, links final
binaries at those addresses, and generates one layout per APPX version.

## Payload matrix

The current build matrix is defined by `AS11_PAYLOADS_<version>` in
`Makefile.as11`:

| APPX key | Payloads |
|----------|----------|
| `8_0_1` | `as11_mop_callback_dispatcher`, `as11_vid_spoof` |
| `8_3_0` | `as11_mop_callback_dispatcher`, `as11_vid_spoof`, `as11_asv_backup_rate` |
| `8_4_0` | `as11_mop_callback_dispatcher`, `as11_vid_spoof`, `as11_asv_backup_rate` |
| `8_5_0` | `as11_mop_callback_dispatcher`, `as11_vid_spoof`, `as11_asv_backup_rate` |

The patcher derives the key from the first three components of the application
version. For example, APPX `8.5.0.9cd562102` selects `8_5_0`.

The matrix controls which artifacts are built and assigned space. Building a
payload does not by itself enable its firmware patch.

## Code caves

`patches/as11_code_caves.tsv` lists available half-open APPL ranges:

```text
appx_version  start       end_exclusive
8_5_0         0x081DBAD0  0x081FFCF8
```

The format supports multiple sorted ranges per APPX key. Ranges must start on
a 4-byte boundary and must not overlap. The current registry contains one
range for each build key.

## Build pipeline

The Air11 payload layout is generated in two link passes:

1. compile each source with `APPX_VER_<version>` and the matching stubs
2. probe-link each payload at `0x08000000`
3. convert each probe ELF to a binary and record its measured size
4. allocate payloads with first fit, starting at the lowest cave address
5. align each allocation to 4 bytes
6. write `build/as11_payload_layout_<version>.tsv` and `.mk`
7. link final ELFs at their assigned addresses
8. convert final ELFs to the binaries consumed by the patcher

The allocator processes payloads in the order emitted by
`as11_payload_sizes_<version>.tsv`. It advances upward through each cave and
moves to the next cave when the current payload does not fit. Allocation fails
if no cave has enough remaining space.

Example generated 8.5.0 layout:

```text
payload                         address      size  end_exclusive
as11_mop_callback_dispatcher    0x081DBAD0   72    0x081DBB18
as11_vid_spoof                  0x081DBB18   51    0x081DBB4B
as11_asv_backup_rate            0x081DBB4C   68    0x081DBB90
```

Build all Air11 payloads and inspect a layout with:

```bash
make as11-binaries
cat build/as11_payload_layout_8_5_0.tsv
```

Dedicated build targets are also available:

```bash
make as11-mop-callback-dispatcher
make as11-vid-spoof
make as11-asv-backup-rate
```

## Patcher checks

`python/patch-airsense-s11.py` selects artifacts using the input image's APPX
key. Before injection it verifies:

- the payload exists in the generated layout for that key
- the binary size matches the measured layout size
- the final ELF `.text` address matches the assigned address
- flattening the final ELF reproduces the supplied binary exactly
- the allocation lies inside the APPL range
- the complete destination contains erased `0xFF` bytes

Patch-specific code separately validates the firmware hook and any native
function addresses used by the payload. A generated layout proves ownership of
the destination range; it does not prove that a hook is valid for an arbitrary
firmware release.

The `patch-airsense-s11` compatibility wrapper delegates payload injection to
the Python patcher. Payload addresses are not duplicated in the wrapper or in
payload source.

## Versioned firmware symbols

Compiled payloads use two versioned symbol families.

### Variable IDs

`patches/as11/vars.h` selects one APPX-specific header:

```c
#if defined(APPX_VER_8_5_0)
#include "vars_8_5_0.h"
#endif
```

The selected header defines `VAR_ID_<SHORT_NAME>` values from that APPX
descriptor namespace. Payload source uses these macros instead of embedding
numeric IDs that can move between firmware versions.

### Native functions

`patches/as11/stubs_<version>.S` defines native firmware entry points for one
APPX version. Payloads call those symbols through the linker. Native function
addresses belong in the versioned stub file, not in generic C source or
Makefile arguments.

Where a patch can rediscover the same functions from the target image, the
patcher compares the discovered addresses with the linked stub symbols before
installing the hook.

Adding pattern fallback for a firmware hook does not by itself add payload
support for a new APPX version. The build still needs a payload matrix entry,
variable header, native stubs, and code-cave range for that version.

## MOP callback dispatcher

MOP-dependent payloads share one `EnumDataItem` writeback hook instead of
replacing the same vtable entry independently.

The patcher fills `mop_callback_handler_table` with:

1. the original stock writeback function
2. registered feature handlers
3. a `0xFFFFFFFF` sentinel

The dispatcher always calls the stock writeback first. It invokes registered
handlers only when the committed DataItem is `MOP`. The current registered
handler is `as11_vid_spoof`.

The dispatcher is injected only when at least one selected patch registers a
handler. Its table reserves space for four feature handlers.

## Payload families

| Payload | APPX keys | Integration |
|---------|-----------|-------------|
| `as11_mop_callback_dispatcher` | `8_0_1`, `8_3_0`, `8_4_0`, `8_5_0` | owns the shared enum-writeback vtable slot and calls registered MOP handlers |
| `as11_vid_spoof` | `8_0_1`, `8_3_0`, `8_4_0`, `8_5_0` | MOP handler; reads `MOP` and writes `VID` through native DataItem functions |
| `as11_asv_backup_rate` | `8_3_0`, `8_4_0`, `8_5_0` | wraps the ASV feature update callback through its own vtable slot |

The ASV backup-rate payload is built by `make as11-binaries`, but its patch
switch remains opt-in in the standard compatibility wrapper.

## Adding a payload

1. add the payload name to each applicable `AS11_PAYLOADS_<version>` list
2. for payload `as11_<name>`, provide `patches/as11/<name>.c` with a `start` entry point
3. use `vars.h` for firmware variable IDs
4. add required native functions to every applicable versioned stub
5. use the generic versioned object and two-pass link rules in `Makefile.as11`
6. load and inject the payload by name through the patcher layout helper
7. resolve entry points or parameter objects from the final ELF symbol table
8. validate the firmware hook before changing its callback or vtable entry
9. verify generated layouts and patch every intended APPX version

A MOP-dependent payload should register its `start` symbol with the shared
dispatcher. A payload tied to another firmware callback should preserve the
stock call path unless replacing it is the explicit purpose of the patch.

Do not add a fixed payload address to source or patcher code. Code-cave
ownership belongs to `as11_code_caves.tsv` and the generated layout.

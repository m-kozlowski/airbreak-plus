# Custom Settings

The custom settings framework exposes persistent controls for injected Air 10
payloads in the stock clinical menu. It is separate from the payloads
themselves. A payload can run without the framework by recognizing unpatched
ABI slots and using its built-in fallback values.

The framework is supported on SX567-0302, SX567-0305, SX567-0306, SX567-0401,
and SX567-0402.

## Assignments

Only settings requested by active payloads are assigned. `Storage` names the
globals[16] persistence group used by the patched image.

| Feature | Setting | UART | Table | Storage |
|---------|---------|------|-------|---------|
| [Custom VAuto](guide/features/custom_vauto.md) | Custom VAuto | RPO | g[8] | CSG |
| [Custom VAuto](guide/features/custom_vauto.md) | ASV Max | RCM | g[4] | CSG |
| [Custom VAuto](guide/features/custom_vauto.md) | ASV Sens | RXM | g[8] | CSG |
| [Custom VAuto](guide/features/custom_vauto.md) | Custom T/C | RPH | g[8] | CSG |
| [ASV backup-rate control](guide/features/asv_backup_rate.md) | Backup Rate | RPW | g[8] | CSG |
| Therapy graph | Monitoring | RXH | g[8] | CSG |
| [Square Wave](guide/features/squarewave.md) | Square Wave | RPF | g[8] | CSG |
| [Backlight adaptation](guide/features/backlight.md) | Ambient Low | ATH | g[4] | NGL |
| [Backlight adaptation](guide/features/backlight.md) | Ambient High | RCF | g[4] | CSG |
| [Backlight adaptation](guide/features/backlight.md) | LCD / Low | LLL | g[4] | CSG |
| [Backlight adaptation](guide/features/backlight.md) | LCD / High | LLH | g[4] | CSG |
| [Backlight adaptation](guide/features/backlight.md) | Buttons / Low | LBL | g[4] | CSG |
| [Backlight adaptation](guide/features/backlight.md) | Buttons / High | LBH | g[4] | CSG |

## Application sequence

The patcher performs these operations when at least one active payload requests
custom settings:

1. disable stock Reminder processing and remove its menu row and page
2. rename the Reminder persistence group from `RGL` to `CSG`
3. reclaim selected Reminder variables and string IDs
4. let each active feature claim and redefine its variables
5. extend the CSG member list with any additional persistent firmware variables
6. emit the custom menu registry into reclaimed CDX space
7. inject the clinical menu hooks
8. register mode visibility with the MOP callback dispatcher

If no active feature requests settings, the framework is skipped and the stock
Reminder implementation remains unchanged.

## Payload fallback contract

An unpatched ABI slot contains `0xFFFF`. Payload code treats that value as a
request for its built-in fallback. The menu framework therefore configures a
payload but is not a runtime dependency of that payload.

## Persistence

Stock Reminder variables belong to the globals[16] group named `RGL`. The
framework renames that group to `CSG` before redefining its members. Reclaimed
Reminder variables retain that membership. Features may also append existing
firmware variables to the group. Both kinds are loaded from and saved to
`CSG.set` through the normal dependency-chain storage tracking.

The rename is storage-format isolation, not only a new label. Redefining group
members can change the expected length of the serialized group file. Reusing
the `RGL` name could make firmware load an existing stock `RGL.set` against the
new layout, fail validation, and raise a configuration fault. The separate
`CSG.set` namespace leaves `RGL.set` untouched and keeps custom descriptor
layouts separate from stock Reminder data.

Changing enabled features can change the serialized `CSG.set` layout. If stock
validation rejects that file, the custom menu payload reports it as empty only
on the validation-failure path. Firmware then truncates and rebuilds `CSG.set`
without raising the normal configuration fault. Error handling for stock groups
is unchanged.

## Reclaimed resources

The reclaim pass disables:

- periodic Reminder processing
- the hardcoded `RX*` to `RC*` state updater
- construction of the Reminder record list
- the Reminders row in clinical Options
- construction of the Reminders page

The removed menu code provides space for the generated registry. Its title and
message string IDs become candidates for the reclaimed string pool.

It then makes these variables available in typed pools:

| Table | Variables | Stock purpose |
|-------|-----------|---------------|
| g[8] | RPF, RPO, RPH, RPW | recurrence enable for Filter, Mask, Tube, and Water Tub |
| g[8] | RXF, RXM, RXH, RXW | reminder-date enable for Filter, Mask, Tube, and Water Tub |
| g[4] | RCF, RCM, RCH, RCW | recurrence period in months |
| g[4] | RDF, RDM, RDH, RDW | reminder due date |

Reclaiming a descriptor clears its stock callback and replaces its name, option,
and units string references with the firmware empty-string ID. The old string
IDs become candidates for the string pool only after a reference scan confirms
that no remaining descriptor or globals[5] entry uses them.

Feature patches claim an exact UART variable name from the matching pool. The
same variable cannot be claimed twice, and a request for a variable outside the
reclaimed pool stops patching. Exact claims keep the patched UART API stable
across feature combinations.

## Localized strings

Feature labels are indexed by ResMed language ID. The patcher updates only the
languages compiled into the current CCX. A missing translation points to the
English string.

String replacement follows this allocation order:

1. use the requested string ID, or allocate one from the reclaimed pool
2. reuse the existing raw string storage when the new text fits
3. otherwise scan backward through erased CCX space for the required bytes
4. update locale pointers and the g[2] maximum length

Supplying an explicit string ID requests replacement of that firmware string.
Pool membership is required only for automatic allocation.

## Menu registry

Feature settings and generated pages use one shared registry. Containers 0
through 4 represent the five stock clinical menu sections. Containers starting
at `0x80` represent generated pages in declaration order.

The patcher emits sentinel-terminated 8-byte records:

```c
typedef struct {
    uint8_t container;
    uint8_t flags;
    uint16_t item_id;
    uint32_t mode_mask;
} custom_menu_entry_t;
```

| Field | Meaning |
|-------|---------|
| container | stock clinical section or generated page |
| flags bit 0 | construct a g[4] numeric item; clear for g[8] enum items |
| flags bit 1 | construct a static heading; `item_id` is a string ID |
| flags bit 2 | construct a page link; `item_id` is the page title string ID |
| item_id | variable ID, heading string ID, or page title string ID |
| mode_mask | one bit per MOP option |

An entry with container `0xFF` or item ID `0xFFFF` terminates the registry.
Duplicate variable IDs are rejected before registry emission.

The payload hooks the final stock append operation in each clinical section.
It first appends the displaced stock item, then appends matching variable,
heading, and page-link records. The patcher increases the stock menu item
capacity only for records added directly to stock sections.

When the registry contains pages, the menu constructor preserves all stock page
pointers in a larger table and appends the generated pages. Each generated page
has a stock Back row followed by records assigned to its container. Page records
may use a stock section or an earlier generated page as their parent.

## UART discovery

The UART metadata patch exposes custom variables through `G C &CSG`. It
resolves variable names, categories, and localized strings from the patched
firmware, so external interfaces do not need a static list of reclaimed
assignments. Firmware page layout and static headings are not exposed. Current
values and writes continue to use the stock `G S #VAR` and `P S #VAR VALUE`
paths. Numeric limits and enum options remain available through the stock
`G C #VAR` capability path. See the
[serial protocol](serial_protocol.md#custom-settings-registry) for the record
format.

## Mode visibility

Clinical menu pages are constructed once. The MOP callback dispatcher calls the
stock MOP callback first, followed by the custom visibility handler. For every
variable entry, the handler tests the current MOP bit in `mode_mask` and updates
the variable handler's runtime VIS flag. Existing menu refresh code then shows
or hides the variable item. Static headings and page links are always visible.

## Adding a feature

A feature setup function should:

1. run only when its payload is active
2. claim exact g[4] or g[8] variables
3. allocate localized label strings
4. redefine complete variable descriptors
5. optionally declare generated pages and register each item with a container
   and MOP mask
6. patch payload ABI slots with resolved var IDs

Firmware-stable variables used directly by compiled code belong in the
versioned `s10_vars` headers. Reclaimed assignments and other patch-time choices
belong in ABI slots. See [Patch payloads](patch_payloads.md).

The patcher prints unused reclaimed variables and string IDs after patching.
This summary is the authoritative resource count for the selected feature set.

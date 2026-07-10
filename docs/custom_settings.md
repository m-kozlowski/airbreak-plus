# Custom Settings

The custom settings framework exposes persistent controls for injected Air 10
payloads in the stock clinical menu. It is separate from the payloads
themselves. A payload can run without the framework by using the fallback values
stored in its ABI slots.

The framework is supported on SX567-0401 and SX567-0402.

## Application sequence

The patcher performs these operations when at least one active payload requests
custom settings:

1. disable stock Reminder processing and remove its menu page
2. rename the Reminder persistence group from `RGL` to `CSG`
3. reclaim selected Reminder variables and string IDs
4. let each active feature claim and redefine its variables
5. emit the custom menu registry into reclaimed CCX space
6. inject the clinical-menu hook payload
7. register mode visibility with the MOP callback dispatcher

If no active feature requests settings, the framework is skipped and the stock
Reminder implementation remains unchanged.

## Payload fallback contract

User-visible settings, defaults, and behavior without the framework are listed
in the [custom settings table](guide/patching.md#custom-settings).

An unpatched ABI slot contains `0xFFFF`. Payload code treats that value as a
request for its built-in fallback. The menu framework therefore configures a
payload but is not a runtime dependency of that payload.

## Persistence

Stock Reminder variables belong to the globals[16] group named `RGL`. The
framework renames that group to `CSG` before redefining its members. Membership
and dependency-chain storage tracking remain in place, so reclaimed values are
loaded from and saved to `CSG.set`.

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
- the Reminders row in clinical Options
- construction of the Reminders submenu page

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

## Current assignments

| UART name | Table | Patched meaning | Menu visibility |
|-----------|-------|-----------------|-----------------|
| RPO | g[8] | Custom ASV | VAuto |
| RPH | g[8] | Custom T/C | S, ST, T, VAuto, PAC |
| RXM | g[8] | ASV Sens | VAuto |
| RPF | g[8] | Square Wave | S, ST, T, PAC |
| RCM | g[4] | ASV Max | VAuto |
| RCF | g[4] | Ambient High | all modes |
| ATH | g[4] | Ambient Low | all modes; stock variable, not reclaimed |

The stock meanings remain canonical for original firmware and continue to be
listed in `var_reference.tsv`. This table describes patched assignments only.

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

The patcher emits sentinel-terminated 8-byte records:

```c
typedef struct {
    uint8_t section;
    uint8_t flags;
    uint16_t var_id;
    uint32_t mode_mask;
} custom_menu_entry_t;
```

| Field | Meaning |
|-------|---------|
| section | Therapy, Comfort, Accessories, Options, or Configuration |
| flags bit 0 | construct a g[4] numeric item; clear for g[8] enum items |
| var_id | numeric firmware variable ID |
| mode_mask | one bit per MOP option |

An entry with section `0xFF` or var_id `0xFFFF` terminates the registry.
Duplicate var IDs are rejected before registry emission.

The payload hooks the final stock append operation in each clinical section.
It first appends the displaced stock item, then appends matching custom entries.
The patcher also increases the stock menu item capacity by the generated entry
count.

## Mode visibility

Clinical menu pages are constructed once. Per-mode visibility is therefore not
implemented by omitting items during construction.

The MOP callback dispatcher calls the stock MOP callback first, followed by the
custom visibility handler. For every registry entry, the handler tests the
current MOP bit in `mode_mask` and updates the variable handler's runtime VIS
flag. Existing menu refresh code then shows or hides the item.

The g[4] and g[8] dependency fields are not used for visibility. They retain
their normal update and persistence roles.

## Adding a feature

A feature setup function should:

1. run only when its payload is active
2. claim exact g[4] or g[8] variables
3. allocate localized label strings
4. redefine complete variable descriptors
5. register each menu item with a section and MOP mask
6. patch payload ABI slots with resolved var IDs

Firmware-stable variables used directly by compiled code belong in the
versioned `s10_vars` headers. Reclaimed assignments and other patch-time choices
belong in ABI slots. See [Patch payloads](patch_payloads.md).

Both patchers print unused reclaimed variables and string IDs after patching.
This summary is the authoritative resource count for the selected feature set.

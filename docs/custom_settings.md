# Custom Settings

The custom settings framework exposes persistent controls for injected Air 10
payloads in the stock clinical menu. It is separate from the payloads
themselves. A payload can run without the framework by recognizing unpatched
ABI slots and using its built-in fallback values.

The framework is supported on SX567-0302, SX567-0305, SX567-0306, SX567-0401,
SX567-0402, and Lumis SX584-0204/0205.

## Assignments

Settings are assigned when their corresponding patch or payload is active.
`Storage` names the globals[16] persistence group used by the patched image.
`PHT` is a stock variable with a native menu row; the iVAPS patch activates it.

| Feature | Setting | UART | Table | Storage |
|---------|---------|------|-------|---------|
| iVAPS | Height (cm) | PHT | g[4] | QXJ |
| iVAPS | Height (inches) | PHI | g[4] | QXJ |
| iVAPS | Height Units | IHU | g[8] | SGL |
| iVAPS | MV | ZMV | g[4] | - |
| iVAPS | Vt | ZTV | g[4] | - |
| iVAPS | Vt/kg IBW | ZVK | g[4] | - |
| [Custom VAuto](guide/features/custom_vauto.md) | Custom VAuto | RPO | g[8] | CSG |
| [Custom VAuto](guide/features/custom_vauto.md) | ASV Max | RCM | g[4] | CSG |
| [Custom VAuto](guide/features/custom_vauto.md) | ASV Sens | RXM | g[8] | CSG |
| [Custom VAuto](guide/features/custom_vauto.md) | EPS | RDH | g[4] | CSG |
| [Custom VAuto](guide/features/custom_vauto.md) | Exh. Shape | RDW | g[4] | CSG |
| [Custom VAuto](guide/features/custom_vauto.md) | Custom T/C | RPH | g[8] | CSG |
| [ASV backup-rate control](guide/features/asv_backup_rate.md) | Backup Rate | RPW | g[8] | CSG |
| [Therapy screen](guide/features/general.md#therapy-screen) | Therapy scr. | RXH | g[8] | CSG |
| [Header clock](guide/features/general.md#header-clock) | Clock | RXF | g[8] | CSG |
| [Square Wave](guide/features/squarewave.md) | Square Wave | RPF | g[8] | CSG |
| [Fall Time](guide/features/general.md#fall-time) | Fall Time | RCW | g[4] | CSG |
| [ST iBR](guide/features/general.md#st-ibr) | iBR | RXW | g[8] | CSG |
| [iVAPS AutoEPAP](guide/features/general.md#ivaps-autoepap) | AutoEPAP | RSA | g[8] | CSG |
| [iVAPS AutoEPAP](guide/features/general.md#ivaps-autoepap) | Min EPAP | RDF | g[4] | CSG |
| [iVAPS AutoEPAP](guide/features/general.md#ivaps-autoepap) | Max EPAP | RDM | g[4] | CSG |
| [Backlight adaptation](guide/features/backlight.md) | Ambient Low | ATH | g[4] | NGL |
| [Backlight adaptation](guide/features/backlight.md) | Ambient High | RCF | g[4] | CSG |
| [Backlight adaptation](guide/features/backlight.md) | LCD / Low | LLL | g[4] | CSG |
| [Backlight adaptation](guide/features/backlight.md) | LCD / High | LLH | g[4] | CSG |
| [Backlight adaptation](guide/features/backlight.md) | Buttons / Low | LBL | g[4] | CSG |
| [Backlight adaptation](guide/features/backlight.md) | Buttons / High | LBH | g[4] | CSG |
| [Target humidity](guide/features/general.md#target-humidity) | Target RH (%) | RCH | g[4] | CSG |


## Application sequence

The patcher performs these operations when at least one active patch or payload
requests custom settings:

1. disable stock Reminder processing and remove its menu row and page
2. rename the Reminder persistence group from `RGL` to `CSG`
3. reclaim selected Reminder variables and string IDs
4. let each active feature activate or redefine its variables
5. extend the CSG member list with any additional persistent firmware variables
6. resolve menu placement and emit the custom menu registry into reclaimed CDX space
7. emit the dispatch table and inject the required clinical menu hooks
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
- forwarding popup acknowledgements to `RSA`
- the Reminders row in clinical Options
- construction of the Reminders page

The removed menu code provides space for the generated registry. Its title and
message string IDs become candidates for the reclaimed string pool.

It then makes these variables available in typed pools:

| Table | Variables | Stock purpose |
|-------|-----------|---------------|
| g[8] | RPF, RPO, RPH, RPW | recurrence enable for Filter, Mask, Tube, and Water Tub |
| g[8] | RXF, RXM, RXH, RXW | reminder-date enable for Filter, Mask, Tube, and Water Tub |
| g[8] | RSA | runtime reminder acknowledgement request |
| g[8] | LET | `CAL=0x0008` placeholder service variable, registered but not processed |
| g[4] | RCF, RCM, RCH, RCW | recurrence period in months |
| g[4] | RDF, RDM, RDH, RDW | reminder due date |
| g[4] | LEF | `CAL=0x0008` placeholder service variable, registered but not processed |

`RSA`, `LET`, and `LEF` do not belong to a stock storage group. A feature that
stores one of them adds it to `CSG` and links its descriptor to the group
tracker.

Reclaiming a descriptor clears its stock callback and replaces its name, option,
and units string references with the firmware empty-string ID. The old string
IDs become candidates for the string pool only after a reference scan confirms
that no remaining descriptor or globals[5] entry uses them.

Feature patches claim an exact UART variable name from the matching pool. The
same variable cannot be claimed twice, and a request for a variable outside the
reclaimed pool stops patching. Exact claims keep the patched UART API stable
across feature combinations.

Feature callbacks use the [shared variable callback registry](patch_payloads.md#variable-callbacks).
Its returned callback IDs can be assigned when redefining variable descriptors.

## Localized strings

Feature labels are indexed by ResMed language ID. The patcher updates only the
languages compiled into the current CCX. A missing translation points to the
English string.

`redefine_fw_string(-1, strings, owner)` allocates a string ID in this order:

1. an unused ID from the reclaimed pool
2. a new ID after the last firmware string ID

Supplying an explicit string ID requests replacement of that firmware string.
Pool membership is required only for automatic allocation.

Patches only record the text. The `firmware-strings` finalization step runs
after all other patches and rebuilds the language tables once, from the
current image and the recorded strings. It writes the g[2] maximum lengths,
removes text that no longer has a reference, and keeps data that other patches
placed in the language area. The result is checked by reading every string
back.

g[2] has no room for further records in the stock image. The first new ID
therefore moves the g[2] table into the CCX language area, ends it with a zero
record, and updates the `globals[2]` pointer. The stock table is erased. The
firmware locates g[2] only through that pointer and does not check ID bounds.
String IDs are signed 16-bit values in firmware, so IDs up to `0x7FFF` are
available.

The text of a new ID is English for every compiled language without a supplied
translation.

## Menu placement

`custom_menu_add`, `custom_menu_add_heading`, and `custom_menu_add_page` accept
an optional `before` or `after` reference and return an item handle. Placement
is relative to another entry in the same section or generated page:

```python
from lib.custom_menu import stock, custom

self.custom_menu_add('therapy', 'PHI', height_mask, after=stock('PHT'))
mv = self.custom_menu_add('therapy', 'ZMV', ivaps_mask, after=stock('WMV'))
vt = self.custom_menu_add('therapy', 'ZTV', ivaps_mask, after=mv)
self.custom_menu_add('therapy', 'ZVK', ivaps_mask, after=vt)
```

`stock('PHT')` refers to a native row by its UART variable name.
`custom('ZMV')` refers to a registered custom variable, including one registered
later. Returned handles also identify headings and page links. An omitted
placement appends to the end of the section or generated page, in registration
order. Generated pages retain their Back row first.

Entries attached to the same side of an anchor retain registration order.
An entry and the entries attached to it stay together: if A is before a stock
row, B placed after A is still before that stock row. References cannot cross
containers. Both placement arguments together, cycles, missing custom entries,
and missing or ambiguous stock anchors stop patching.

Stock anchors are the append sites in the five clinical sections listed per
firmware version in [custom_menu_stock.py](../python/lib/custom_menu_stock.py).
The patcher checks their UART bindings and original append instructions.
Hidden rows can be used as anchors.
A combined widget is one anchor: either of its unique variable names refers
to the whole widget. For example, `HTX` occurs in two stock rows; use `HTS`
or `HTF` to distinguish them.

## Menu registry

Feature settings and generated pages use one shared registry. Containers 0
through 4 represent the five stock clinical menu sections. Containers starting
at `0x80` represent generated pages in page order after placement.

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
| flags bit 3 | append the g[4] variable units to its displayed value |
| item_id | variable ID, heading string ID, or page title string ID |
| mode_mask bits 0..11 | one bit per MOP option |
| mode_mask bit 31 | preserve visibility managed by stock firmware callbacks |

An entry with container `0xFF` or item ID `0xFFFF` terminates the registry.
Duplicate variable IDs are rejected before registry emission.
The registry holds at most 64 entries, followed by the terminator.

After feature registration, the patcher orders entries within each container.
It emits containers in section and page order. The registry supplies GUI
construction and UART group paths.

A separate dispatch table maps the return address of each hooked append call
to ranges of registry entries to insert before and after the stock item.
Only used anchors are hooked. The shared payload inserts those entries and
performs the stock append once.
The dispatch table uses the shared CCX allocator. The patcher increases the
stock list capacity by the number of entries added directly to stock sections.

When the registry contains pages, the menu constructor preserves all stock page
pointers in a larger table and appends the generated pages. Each generated page
has a stock Back row followed by records assigned to its container. Page records
may use a stock section or an earlier generated page as their parent.

## UART discovery

The UART metadata patch exposes custom variables through `G C &CSG`. It
resolves variable names, categories, and localized strings from the patched
firmware, so external interfaces do not need a static list of reclaimed
assignments. Page titles and section headings form a localized group path for
each variable; clients choose how to present that path. Current
values and writes continue to use the stock `G S #VAR` and `P S #VAR VALUE`
paths. Numeric limits and enum options remain available through the stock
`G C #VAR` capability path. See the
[serial protocol](serial_protocol.md#custom-settings-registry) for the record
format.

## Mode visibility

Clinical menu pages are constructed once. The MOP callback dispatcher calls the
stock MOP callback first, followed by the custom visibility handler. For every
variable entry, the handler tests the current MOP bit in `mode_mask` and updates
the variable handler's runtime VIS flag. Entries with bit 31 set retain the
visibility selected by stock firmware callbacks. Existing menu refresh code
then shows or hides the variable item. Static headings and page links are
always visible.

`custom_menu_add_condition(var, source, mode_mask=None, *, nonzero=True)` adds a
visibility condition to a registered variable. The source must be a g[4] or
g[8] variable. `nonzero=True` requires a nonzero raw value; `False` requires
zero. The mask selects the MOP modes in which this condition applies, defaulting
to all modes. Outside that mask the condition has no effect. All applicable
conditions must hold in addition to the menu entry's mode mask.

Conditions use a separate sentinel-terminated table:

| Offset | Type | Meaning |
|--------|------|---------|
| +0x00 | u16 | target variable ID; `0xFFFF` ends the table |
| +0x02 | u16 | source variable ID |
| +0x04 | u16 | applicable MOP bits 0..11 |
| +0x06 | u16 | required source state: 0 for zero, 1 for nonzero |

Targets must have framework-managed visibility; entries marked
`CUSTOM_MENU_MODE_KEEP_VISIBILITY` cannot have these conditions. The patcher
attaches the visibility handler to source callbacks, preserving existing
callbacks through the [callback registry](patch_payloads.md#variable-callbacks).
Menu construction also evaluates conditions from the loaded settings. Updating
VIS preserves the setting's value and its entry in UART discovery; the UART
menu registry does not export the condition table.

## Adding a feature

A feature setup function should:

1. run only when its corresponding patch or payload is active
2. claim exact g[4] or g[8] variables
3. allocate localized label strings
4. redefine complete variable descriptors
5. optionally declare generated pages and register each item with a container
   and MOP mask
6. patch payload ABI slots with resolved var IDs

Firmware-stable variables used directly by compiled code belong in the
versioned `s10_vars` headers. Reclaimed assignments and other patch-time choices
belong in ABI slots. See [Patch payloads](patch_payloads.md).

The patcher prints unused reclaimed variables and string IDs after patching,
and the new string IDs with their owners.
This summary is the authoritative resource count for the selected feature set.

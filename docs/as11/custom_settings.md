# Air11 Custom Settings

The custom settings framework provides persistent DataItems and clinical-menu
controls for compiled Air11 payloads. Storage, descriptor changes, menu rows,
and payload bindings are independent parts of the framework.

`patch-custom-settings` enables the finalization pass. When no active feature
requests a custom setting, the pass is skipped and stock firmware remains
unchanged.

## Current Assignments

| Feature | Setting | Backing field | Table | Section | Visible in | Default |
|---------|---------|---------------|-------|---------|------------|---------|
| [ASV Backup Rate](../guide/as11/features.md#asv-backup-rate) | Backup Rate | `RIF` / `ReminderFilterEnable` | g[5] | Therapy | ASV, ASVAuto | On |

For Backup Rate, `On` preserves stock ASV behavior. `Off` suppresses backup
breaths while leaving the stock no-breathing detector active.

## Application Sequence

Feature patches register their requirements while the normal patch list is
processed. Afterward, the custom settings finalizer:

1. resolves every referenced DataItem by short tag or long name
2. activates each reclaim provider used by a claimed field
3. loads the shared menu payload when rows must be added or removed
4. applies requested descriptor-field changes
5. writes resolved variable IDs into feature payload ABI slots
6. disables the stock consumers owned by active reclaim providers
7. fills the menu-entry and removed-row registries
8. redirects clinical-menu construction through the shared menu bridge
9. registers menu visibility with the MOP callback dispatcher

Reclaim providers and the menu payload are installed only when required by an
active feature.

## Optional Integration

Custom settings configure feature payloads but are not their runtime
dependency. A configurable payload reserves a 16-bit variable-ID slot with the
value `0xFFFF`. The finalizer replaces it with the claimed DataItem ID.

When `patch-custom-settings` is disabled, no field is reclaimed, no menu row is
added, and the slot remains `0xFFFF`. The feature payload must recognize that
sentinel and use its standalone behavior. The ASV backup-rate payload treats
it as backup rate disabled.

## Persistence

The reclaimed fields remain members of the stock `HST` storage set. The
framework does not create another settings file, change the HST member list,
or alter its serialized record length. Values are loaded and saved through the
normal HST dependency and dirty-tracking paths.

The descriptor default is used only when no persisted value is available. An
existing HST value takes precedence after boot.

Reclaiming a field does not rename its protocol identity. Its short tag, long
name, FeatureProfiles field, SettingProfilesCollection field, and any other
schema references remain stock unless another patch changes them explicitly.
The custom GUI label affects only the menu row.

## Reclaimed Resources

The current provider reclaims the persistent replacement-reminder profile:

| Table | Fields | Stock purpose |
|-------|--------|---------------|
| g[5] | `RIF`, `RIM`, `RIT`, `RIC` | reminder enable states |
| g[5] | `RDF`, `RDM`, `RDT`, `RDH` | reminder periods |
| g[2] | `RTF`, `RTM`, `RTT`, `RTH` | reminder dates |

Features claim exact fields rather than receiving the next free field by type.
A field cannot be claimed by two features, and an unknown field is rejected.

Claiming any member activates the provider for the complete pool. The provider
disables the reminder scheduler and removes the Reminders navigation row from
the clinical menu before the fields are used by custom features. Unclaimed
members remain available to later feature registrations but no longer receive
stock reminder updates.

## Descriptor Updates

A claimed field keeps its native descriptor type. The framework can replace
selected fields in g[1], g[2], g[3], or g[5] descriptors; it does not convert a
DataItem from one table to another. The current reclaim pool supplies g[2]
numeric and g[5] enum fields.

| Table | Descriptor fields |
|-------|-------------------|
| g[1] | `flags`, `data_rule_id`, `linked_counter_index`, `change_event_queue_index`, `buffer_capacity` |
| g[2] | `flags`, `data_rule_id`, `linked_counter_index`, `change_event_queue_index`, `default`, `max`, `min`, `decimal_places`, `scale`, `step`, `bounds_slot`, `sample_block_signal_id`, `quantity_class` |
| g[3] | `flags`, `data_rule_id`, `linked_counter_index`, `change_event_queue_index`, `default_mask`, `editable_mask`, `bit_count`, `selection_order_offset` |
| g[5] | `flags`, `data_rule_id`, `linked_counter_index`, `change_event_queue_index`, `default_option`, `n_options`, `reserved`, `option_mask` |

Only fields supplied by the feature are changed. This permits reuse of a stock
descriptor without rewriting unrelated metadata or option tables.

## GUI Labels

Menu entries use existing firmware GUI text IDs. Text IDs move between APPX
versions, so the feature owns the per-version label mapping. The framework
does not currently allocate new localized strings or rewrite the Markov text
tables.

The ASV backup-rate feature uses the stock localized `Backup Rate` text in each
supported application version.

## Menu Registry

The shared payload stores sentinel-terminated 8-byte menu records:

```c
typedef struct {
    uint16_t var_id;
    uint16_t label_id;
    uint16_t mode_mask;
    uint8_t section;
    uint8_t factory_index;
} custom_menu_entry_t;
```

| Field | Meaning |
|-------|---------|
| `var_id` | DataItem displayed and edited by the row |
| `label_id` | firmware GUI text ID used as the row label |
| `mode_mask` | one visibility bit per `ActiveTherapyProfile` option |
| `section` | stock clinical-menu section index |
| `factory_index` | index of the menu-item factory in the shared factory table |

`var_id == 0xFFFF` terminates the registry. The payload reserves 64 entries and
16 distinct factories. The registry supports MOP indexes `0..15`.

Section indexes are:

| Index | Section |
|------:|---------|
| 0 | Therapy |
| 1 | Comfort |
| 2 | Accessories |
| 3 | Options |
| 4 | Configuration |

The menu bridge wraps the final stock clinical-settings scroller constructor.
It identifies the five stock sections, copies their existing rows, omits row
indexes registered by reclaim providers, and appends custom entries to the
selected section. The current bridge adds DataItem rows to stock sections; it
does not create headings or additional pages.

Factory addresses are deduplicated in a separate table. The built-in
`text_value` factory creates a normal text-value list item. A feature may
instead register another factory with this interface:

```c
void *factory(uint32_t var_id, uint32_t label_id);
```

This keeps menu presentation independent from the descriptor table used for
storage. Numeric or otherwise specialized controls can supply a factory suited
to their native UI class.

## Mode Visibility

Clinical menu rows are constructed once. During construction, the menu bridge
reads `MOP`, tests its bit in each entry's `mode_mask`, and updates the backing
DataItem through the native visibility API.

The same visibility handler is registered with the shared MOP callback
dispatcher. It runs after stock MOP writeback so changing therapy mode updates
custom rows without reconstructing the menu.

## Adding a Feature

A feature using reclaimed persistence should:

1. install and validate its compiled payload independently
2. define standalone behavior for an unpatched `0xFFFF` ABI slot
3. claim an exact field from a reclaim pool
4. replace only the descriptor fields required by the new setting
5. optionally add a menu row with its section, label, mode mask, and factory
6. bind the resolved variable ID to the payload ABI slot

A feature may omit the claim when it only displays an existing DataItem. It may
also omit the menu row when the reclaimed field is controlled entirely by the
payload or another interface.

Adding another reclaim provider requires a verified field pool and a provider
handler that detaches every stock writer of those fields. Version-specific
menu and callsite anchors belong in the provider layout; setting semantics and
GUI labels remain in the feature patch.

Compiled payload layout and ABI conventions are documented in
[Air11 Patch Payloads](patch_payloads.md). DataItem descriptor layouts are
documented in [Air11 CONF Block Format](conf_block_format.md).

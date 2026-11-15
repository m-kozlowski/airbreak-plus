# Air11 Custom Settings

The custom settings framework provides persistent DataItems and clinical-menu
controls for Air11 feature patches. Storage, descriptor changes, menu rows,
and payload bindings are independent parts of the framework.

`patch-custom-settings` enables the finalization pass. When no active feature
registers settings, menu rows, bindings, or reclaim requests, the pass is skipped.

## Application Sequence

Feature patches register their requirements while the normal patch list is
processed. Afterward, the custom settings finalizer:

1. resolves every referenced DataItem by short tag or long name
2. activates each requested reclaim provider, including those used by claimed fields
3. loads the shared menu payload when rows must be added or removed
4. applies requested descriptor-field changes
5. writes resolved variable IDs into feature payload ABI slots
6. disables the stock consumers owned by active reclaim providers
7. fills the menu-entry and removed-row registries
8. redirects clinical-menu construction through the shared menu bridge
9. registers menu visibility with the MOP callback dispatcher

Reclaim providers and the menu payload are installed only when required by an
active feature.

Storage extensions and GUI enum-label registrations are finalized after the
custom settings pass. Requests from all features are merged before each table
is allocated and written.

## Optional Integration

For optional integration, a configurable payload reserves a 16-bit variable-ID
slot with the value `0xFFFF`. The finalizer replaces it with the claimed
DataItem ID.

When `patch-custom-settings` is disabled, no field is reclaimed, no menu row is
added, and the slot remains `0xFFFF`. The feature payload must recognize that
sentinel and use its standalone behavior.

A feature that requires reclaimed resources must skip installation when
`patch-custom-settings` is disabled.

## Persistence

The reclaimed fields remain members of the stock `HST` storage set. Values are
loaded and saved through the normal HST dependency and dirty-tracking paths.

Feature patches can also persist existing DataItems without reclaiming a donor:

```python
self.storage_register_members("HST", "TSS")
```

This registers a request without changing the image. `finalize_storage()`
merges requests per group, appends missing members, and relocates each extended
list once through the shared CONF allocator. The g[6] headers and filenames
stay unchanged; only the affected header's pointer and member count change.
Repeated members are included once.

The finalizer also assigns the group's update counter to each requested
DataItem, so changes schedule a storage write. This pass runs after descriptor
changes and does not require `patch-custom-settings`.

The descriptor default is used only when no persisted value is available. An
existing HST value takes precedence after boot.

Reclaiming a field does not rename its protocol identity. Its short tag, long
name, FeatureProfiles field, SettingProfilesCollection field, and any other
schema references remain stock unless another patch changes them explicitly.
The custom GUI label affects only the menu row.

A claim with `custom_name` publishes its runtime meaning under `dataItems` in
[AirbreakInfo](patch_airbreak_info.md). The entry is keyed by the unchanged RPC
short selector and includes the owning patch plus any menu and enum metadata
available to the framework. Claims without `custom_name` remain private to the
feature patch.

## Reclaimed Resources

The current provider reclaims the persistent replacement-reminder profile:

| Table | Fields | Stock purpose |
|-------|--------|---------------|
| g[5] | `RIF`, `RIM`, `RIT`, `RIC` | reminder enable states |
| g[5] | `RDF`, `RDM`, `RDT`, `RDH` | reminder periods |
| g[2] | `RTF`, `RTM`, `RTT`, `RTH` | reminder dates |

A feature can request reclaim without claiming a DataItem. This requires
`patch-custom-settings`:

```python
self.custom_settings_reclaim("reminders")
```

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

For an enum selector, a feature can associate raw values with existing GUI
text IDs through `custom_enum_labels(setting, {raw_value: text_id, ...})`.
`finalize_enum_labels()` merges these requests into the native option-label
table and relocates it into CONF. The native formatter and selector both use
the updated table. RPC symbols remain unchanged.

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
`text_value` factory creates a native On/Off switch. The `enum` factory creates
a native enum selector using the popup controller shared by stock menu rows.
Its choices come from the DataItem's option mask and GUI enum-label table.
A feature may instead register another factory with this interface:

```c
#include "custom_settings.h"

void *factory(unsigned int var_id, unsigned int label_id,
              const custom_menu_context_t *context);
```

This keeps menu presentation independent from the descriptor table used for
storage. Numeric or otherwise specialized controls can supply a factory suited
to their native UI class.

The context exposes the stock clinical-menu rows during construction. A factory
may reuse controllers owned by those rows; the context pointer itself must not
be retained after the factory returns.

## Mode Visibility

Clinical menu rows are constructed once. During construction, the menu bridge
marks a `0xFFFF` entry visible in every mode. Other entries test the current
`MOP` bit in `mode_mask`. Visibility is applied through the native DataItem
API.

When at least one entry has a mode-dependent mask, the visibility handler is
registered with the shared MOP callback dispatcher. It runs after stock MOP
writeback and updates only those entries. Global entries do not require or use
the dispatcher.

## Adding a Feature

A feature using reclaimed persistence should:

1. install and validate its compiled payload independently
2. define standalone behavior for an unpatched `0xFFFF` ABI slot
3. claim an exact field from a reclaim pool, supplying `custom_name` when the
   new meaning should be published through AirbreakInfo
4. replace only the descriptor fields required by the new setting
5. optionally add a menu row with its section, label, mode mask, and factory
6. bind the resolved variable ID to the payload ABI slot

A feature may omit the claim when it only displays an existing DataItem. It may
also omit the menu row when the reclaimed field is controlled entirely by the
payload or another interface.

For example, the ASV backup-rate integration claims an enum, sets its default,
adds a mode-dependent row, and binds the payload's variable-ID slot:

```python
setting = self.custom_setting_claim("RIF", "patch-asv-backup-rate", custom_name="ASVBackupRateEnable")
self.custom_setting_define(setting, default_option=1)
self.custom_menu_add("therapy", setting, version["label_id"],
                     self.therapy_mode_mask("ASV", "ASVAuto"), "text_value")
self.custom_setting_bind(setting, backup_rate_var_slot)
```

`version["label_id"]` comes from the feature's per-version mapping;
`backup_rate_var_slot` is the address of its 16-bit ABI slot in the payload.

For an existing enum such as TSS, the feature registers persistence and menu
integration without claiming a reminder field:

```python
self.storage_register_members("HST", "TSS")
self.custom_enum_labels("TSS", dict(enumerate(menu["option_labels"])))
self.custom_menu_add("configuration", "TSS", menu["label_id"], 0xFFFF, "enum")
```

Here `menu` is the feature's version-specific label mapping. The feature also
sets the desired descriptor option count, option mask and RPC flags through the
generic descriptor API. Raw values beyond the native option count need their
own labels and a consumer that handles them; TSS adds raw value 3 (`Auto`).

Adding another reclaim provider requires a verified field pool and a provider
handler that detaches every stock writer of those fields. Version-specific
menu and callsite anchors belong in the provider layout; setting semantics and
GUI labels remain in the feature patch.

Compiled payload layout and ABI conventions are documented in
[Patch Payloads](patch_payloads.md). DataItem descriptor layouts are
documented in [CONF Block Format](conf_block_format.md).

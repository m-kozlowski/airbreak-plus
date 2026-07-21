# Air11 Firmware Maintenance Tools

`as11_version_tool.py` prepares the version-specific source inputs needed when
porting compiled patches to a new APPX release. It reads a new firmware image
and one already supported reference image, then writes a review bundle under
`tmp/`:

- a complete `vars_<version>.h`
- candidate `stubs_<version>.S`
- candidate entries for `python/lib/as11_patch_versions.py`
- candidate OTA descriptor words recovered from the firmware verifier table
- a code-cave candidate and Makefile integration snippets
- an address-transfer report with unresolved alternatives

Run it from the repository root:

```bash
python3 python/maintenance/as11_version_tool.py NEW.bin \
    --reference REFERENCE.bin
```

The tool does not modify tracked source files. Variable IDs are read directly
from the new CONF namespace. Code addresses are transferred using unchanged,
unique byte islands around known reference addresses and always require review
against the new firmware before installation.

Reviewed patch metadata lives in
`python/lib/as11_patch_versions.py`. Both the patcher and this tool consume that
registry directly.

To measure the porter against a firmware version that is already supported,
add `--self-check`:

```bash
python3 python/maintenance/as11_version_tool.py KNOWN_TARGET.bin \
    --reference KNOWN_REFERENCE.bin --self-check
```

The generated `self_check.tsv` reports each known value as `recovered`,
`missed`, or `wrong`. A `wrong` result makes the command fail; unresolved or
weak candidates remain `missed` and are not treated as recovered addresses.

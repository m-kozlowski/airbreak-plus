# as10_languages

## Name

`as10_languages.py` - export Air 10 translations and build a replacement language set.

## Contents

- [Synopsis](#synopsis)
- [Description](#description)
- [Arguments](#arguments)
- [Options](#options)
- [Commands](#commands)
  - [inspect](#inspect)
  - [export](#export)
  - [build](#build)
- [Source Format](#source-format)
- [Patched Images](#patched-images)
- [Output](#output)
- [Exit Status](#exit-status)
- [Examples](#examples)
- [See Also](#see-also)

## Synopsis

```text
as10_languages.py IMAGE inspect
as10_languages.py IMAGE export LANGUAGE -o FILE [--overwrite]
as10_languages.py IMAGE build [SOURCE ...] [-o FILE] [--dry-run]
                  [--overwrite] [--ignore-input-crc]
```

## Description

Export a language from a firmware image to an editable TSV file, or replace
the image's language set using TSV sources. Works offline on complete raw
1 MiB images with bootloader layouts `SX577-0200` or `SX585-0200`.

English comes from the input image by default. Supply one source file for each
other desired language. Languages omitted from the source list are removed;
with no sources, the result contains English only.

The builder preserves string IDs, replaces translations and the available
language list, and updates the CCX checksum. BLX and CDX remain unchanged.
It does not translate text, remap string IDs between firmware versions,
modify fonts, or check glyph coverage and text layout on the display.

## Arguments

| Argument | Meaning |
|----------|---------|
| `IMAGE` | Complete raw firmware image to inspect, export from, or rebuild |
| `LANGUAGE` | Case-insensitive language alias or LAN ID in decimal or `0x` hexadecimal notation; must exist in the image for export |
| `SOURCE` | UTF-8 TSV file whose `# language:` header identifies its language |
| `FILE` | Output path, distinct from the input image and all sources; parent directory must exist |

For example, `PL`, `18`, and `0x12` select Polish. Source filenames and
directories have no effect on language selection or version compatibility.
Choose sources whose string IDs match the target firmware; renaming a file
does not convert its contents.

Examples assume the repository's `python/` directory is on `PATH`.

## Options

| Option | Meaning |
|--------|---------|
| `-h`, `--help` | Show help; use `COMMAND --help` for command options |

A command is required. Command-specific options follow the command.

## Commands

### inspect

```text
inspect
```

Show the software version, string-ID range, language mask and default,
available language IDs and labels, and language resource usage and capacity.
If the resource area contains other data that must be retained, its size is
also reported.

```sh
as10_languages.py firmware.bin inspect
```

### export

```text
export LANGUAGE -o FILE [--overwrite]
```

Export all string IDs for one language, including empty strings. The output
includes the language header and can be edited and passed directly to `build`.

| Option | Meaning | Default |
|--------|---------|---------|
| `-o`, `--output FILE` | Write the TSV file | Required |
| `--overwrite` | Replace an existing output file | Off |

```sh
as10_languages.py firmware.bin export PL -o polish.tsv
```

### build

```text
build [SOURCE ...] [-o FILE] [--dry-run] [--overwrite] [--ignore-input-crc]
```

Replace the language set with English from the image and the supplied
non-English translations. Languages are ordered by numeric LAN ID, not source
argument order. The image's default language is retained if included;
otherwise the default becomes English.

When both regional variants are included and their menu names are identical,
`build` adds suffixes: `ES`/`LatAm` for Spanish, `PT`/`BR` for Portuguese,
and `TW`/`CN` for Chinese. Each menu language is checked separately;
distinct names and empty labels are left unchanged.

| Option | Meaning | Default |
|--------|---------|---------|
| `-o`, `--output FILE` | Write a separate complete firmware image | Required unless `--dry-run` |
| `--dry-run` | Build and verify the result without writing an image | Off |
| `--no-skip-english` | Use a supplied English TSV instead of ignoring it | Off |
| `--overwrite` | Replace an existing output file | Off |
| `--ignore-input-crc` | Allow invalid input block CRCs | Off |

English sources are ignored by default; use `--no-skip-english` to load one.
Missing English IDs retain the image text.

Missing source IDs use the resulting English text, with a warning for each
missing ID. Explicitly empty records remain empty. Duplicate languages,
invalid records, or insufficient resource space fail the build.

Japanese (`JA-13`, `JA-19`) and Chinese (`ZH-TW`, `ZH-CN`) cannot be included
in the same image. The build rejects that combination.

Translations must fit in the available CCX language space. Identical text is
stored once; unrelated data is preserved. Available capacity depends on the
image and selected translations. Use `--dry-run` to check a proposed set.

The builder checks input block CRCs, verifies the resulting translations and
CCX checksum, and writes the output only after validation. `inspect` and
`export` do not check CRCs. `--ignore-input-crc` does not repair invalid CRCs
in unchanged BLX or CDX blocks.

```sh
as10_languages.py firmware.bin build french.tsv polish.tsv --dry-run
as10_languages.py firmware.bin build french.tsv polish.tsv -o translated.bin
as10_languages.py firmware.bin build -o english.bin
```

## Source Format

Uses the same [TSV syntax and language aliases as s9_languages](s9_languages.md#source-format),
with the additional alias `CS` for LAN ID `20`. The target image's language
options determine which IDs are accepted.

```text
# language: PL
ID<TAB>text
```

`<TAB>` denotes a literal tab. IDs are string IDs, in decimal or `0x`
hexadecimal, within the range reported by `inspect`. They are not raw
string-table indexes. Record order does not matter; text spaces are preserved.

| Record | Meaning |
|--------|---------|
| `ID<TAB>text` | Translation for this ID |
| `ID<TAB>` | Intentional empty string |
| No record for an ID | Use the resulting English text, with a warning; missing English IDs use the image |

Text after decoding escapes must be valid UTF-8 and contain at most 255
Unicode code points per string, not 255 bytes. Embedded NUL is not allowed.
Export can preserve invalid UTF-8 bytes as `\xNN` escapes, but such text must
be corrected before building an Air 10 image.

## Patched Images

Prefer rebuilding languages before applying Airbreak patches. Custom settings
reuse existing string IDs, so stock translations applied afterwards can
replace custom setting labels with their former meanings.

Already-patched images are accepted. Use translations adapted to their custom
labels. A recognized Airbreak build stamp produces a warning, not a rejection.

Labels that the patcher added as new string IDs are kept. Sources do not
contain these IDs, so `build` reports each of them as missing and uses the
English text, which is what the patcher stores.

## Output

`inspect` prints image and capacity information. `export` writes a TSV file
and prints its string count. `build` prints the resulting language IDs, mask
and default, string counts, English fallback count, and resource usage.
It reports `Changes: CCX`; a dry run also confirms that no image was written.

Reports go to stdout. Warnings and errors go to stderr. Output files are
written atomically. Existing files require `--overwrite`; input and source
files cannot be used as outputs, including through hardlinks or path aliases.

## Exit Status

| Status | Meaning |
|--------|---------|
| `0` | Successful inspection, export, build, or dry run |
| `1` | Image, source, capacity, validation, or file error |
| `2` | Invalid command-line syntax |

English fallback and patched-image warnings do not make a successful build fail.

## Examples

Export two existing languages, edit their TSV files, and rebuild with only
English and those languages:

```sh
as10_languages.py firmware.bin export FR -o french.tsv
as10_languages.py firmware.bin export PL -o polish.tsv
as10_languages.py firmware.bin build french.tsv polish.tsv --dry-run
as10_languages.py firmware.bin build french.tsv polish.tsv -o translated.bin
as10_languages.py translated.bin inspect
```

Export English as a translation reference:

```sh
as10_languages.py firmware.bin export EN -o reference.tsv
```

For a new translation, change the header in the edited source to the target
language. `build` takes English from the input image unless an English TSV
is supplied with `--no-skip-english`.

## See Also

[as10_descriptors](as10_descriptors.md), [s9_languages](s9_languages.md),
[resmed_image](resmed_image.md), [Air10 patching](../guide/patching.md).

"""Air10 language resources built on the patcher's firmware framework."""
from contextlib import redirect_stdout
import io
from pathlib import Path
import re
import struct

from .as10_firmware import ASFirmware
from .language_tsv import export_tsv_entries, read_tsv, load_translations

# A relocated g[2] table ends with one zero record. Stock records always point
# to a locale array, so a zero pointer cannot occur inside the table.
G2_RECORD = 8
G2_TERMINATOR = bytes(G2_RECORD)
MAX_TEXT_IDS = 0x8000  # Firmware loads text IDs as signed 16-bit values.


class AS10LanguageFirmware(ASFirmware):
    """Read and validate the CCX string layout without a per-CDX address map."""

    def __init__(self, path, data=None):
        self.path = Path(path)
        data = self.path.read_bytes() if data is None else bytes(data)
        if len(data) != 0x100000:
            raise ValueError('expected a complete 1 MiB Air10 firmware image')
        with redirect_stdout(io.StringIO()):
            super().__init__(io.BytesIO(data), validate_crc=False)
        self.data = data

        self.g2 = self.globals_offset(2)
        self.g3 = g3 = self.globals_offset(3)
        if not self.ccx_off <= g3 < self.ccx_off + self.ccx_size:
            raise ValueError('invalid g[3] bounds')
        if self.ccx_off <= self.g2 < g3:
            # Stock placement: the records fill the space before g[3].
            if (g3 - self.g2) % G2_RECORD:
                raise ValueError('g[2] does not contain complete 8-byte records')
            self.text_count = (g3 - self.g2) // G2_RECORD
            self.g2_relocated = False
        else:
            self.text_count = self._relocated_text_count()
            self.g2_relocated = True
        self.lengths = [self.read_u16(self.g2 + tid * G2_RECORD) for tid in range(self.text_count)]

        self.load_firmware_string_metadata()
        self.languages = tuple(self.fw_lang_ids)
        self.lan = self.find_var('LAN')
        self.lnc = self.find_var('LNC')
        self.option_count = self.read_u8(self.lan + self.G8_NUM_OPTIONS)
        if not 0 < self.option_count <= 32 or self.languages[0] != 0:
            raise ValueError('unsupported LAN layout: English must occupy the first slot')
        if self.languages[-1] >= self.option_count:
            raise ValueError('compiled language ID exceeds LAN option count')

        self.start = self.read_u32(self.g2 + 4) - self.FLASH_BASE
        self.end = self.ccx_off + self.ccx_size - 2
        self.root = self.start - 8
        # The CCX accessor returns the adjacent root with ADDW r0,pc,#4; BX lr.
        # Preserve this entry point and root; only their pointed-to data moves.
        if not g3 <= self.root - 8 < self.start < self.end:
            raise ValueError('invalid CCX language resource bounds')
        if self.read_bytes(self.root - 8, 8) != bytes.fromhex('0ff2040070470000'):
            raise ValueError('unrecognized CCX raw-string table accessor')
        self.raw_table = self._raw_string_table_offset()
        self.used, self.texts = self._read_resources()

    def _relocated_text_count(self):
        """Count records of a g[2] table moved into the language arena."""
        end = self.ccx_off + self.ccx_size - 2
        if self.g2 % 4 or not self.g3 < self.g2 < end:
            raise ValueError('invalid relocated g[2] bounds')
        for tid in range(MAX_TEXT_IDS + 1):
            rec = self.g2 + tid * G2_RECORD
            if rec + G2_RECORD > end:
                break
            if self.data[rec:rec + G2_RECORD] == G2_TERMINATOR:
                if not tid:
                    raise ValueError('relocated g[2] table is empty')
                return tid
        raise ValueError('relocated g[2] table has no terminator')

    def _read_resources(self):
        """Reclaim referenced resources and erased space, preserving unrelated bytes.

        Custom label rewrites can leave old, unreferenced text behind. Other
        patches place data in this area too. An unowned interval of zero bytes
        between two owned bytes is alignment padding. In any other unowned
        interval, reserve the span from the first to the last byte that is not
        erased (0xFF). Zero bytes at its edges are kept: they can end other
        data, such as a zero field or a blank bitmap row. Embedded erased bytes
        in unknown data stay reserved as well.
        """
        covered = bytearray(self.end - self.start)

        def claim(off, size):
            if size < 0 or not self.start <= off <= self.end - size:
                raise ValueError(f'language resource outside CCX arena: 0x{off:X}+{size}')
            covered[off-self.start:off-self.start+size] = b'\1' * size

        stride = (2 * len(self.languages) + 3) & ~3
        arrays = set()
        indexes = {}
        for tid in range(self.text_count):
            row = self.read_u32(self.g2 + tid * 8 + 4) - self.FLASH_BASE
            if row % 4:
                raise ValueError(f'unaligned locale array for string {tid}')
            claim(row, stride)
            arrays.add((row, row + stride))
            for slot, language in enumerate(self.languages):
                indexes[tid, language] = self.read_u16(row + slot * 2)

        ids = set(indexes.values())
        if ids != set(range(max(ids) + 1)):
            raise ValueError('raw string IDs are not dense; cannot establish pointer table ownership')
        raw_end = self.raw_table + 4 * len(ids)
        if any(lo < raw_end and hi > self.raw_table for lo, hi in arrays):
            raise ValueError('raw pointer table overlaps locale arrays')
        claim(self.raw_table, 4 * len(ids))
        tables = arrays | {(self.raw_table, raw_end)}
        if self.g2_relocated:
            # The relocated table and its terminator belong to the arena.
            g2_end = self.g2 + (self.text_count + 1) * G2_RECORD
            claim(self.g2, g2_end - self.g2)
            tables.add((self.g2, g2_end))
        tables = sorted(tables)
        if any(hi > next_lo for (_, hi), (next_lo, _) in zip(tables, tables[1:])):
            raise ValueError('overlapping language tables')

        strings = {}
        for sid in ids:
            off = self.read_u32(self.raw_table + sid * 4) - self.FLASH_BASE
            claim(off, 1)
            end = self.data.find(b'\0', off, self.end)
            if end < 0:
                raise ValueError(f'unterminated raw string {sid}')
            if any(lo <= end and hi > off for lo, hi in tables):
                raise ValueError(f'raw string {sid} overlaps language tables')
            claim(off, end - off + 1)
            strings[sid] = self.data[off:end]

        self.available = bytearray(b'\1' * len(covered))
        self.reserved_ranges = []
        pos = 0
        while True:
            lo = covered.find(b'\0', pos)
            if lo < 0:
                break
            hi = covered.find(b'\1', lo)
            if hi < 0:
                hi = len(covered)
            gap = self.data[self.start+lo:self.start+hi]
            padding = lo > 0 and hi < len(covered) and not gap.strip(b'\0')
            if not padding and gap.strip(b'\xff'):
                first = lo + len(gap) - len(gap.lstrip(b'\xff'))
                last = lo + len(gap.rstrip(b'\xff'))
                self.available[first:last] = bytes(last - first)
                self.reserved_ranges.append((self.start + first, self.start + last))
            pos = hi
        self.owned = covered
        return sum(covered), {key: strings[index] for key, index in indexes.items()}

    def invalid_crcs(self):
        return [name for name, off, size in self.firmware_blocks()
                if self.crcfunc(self.read_bytes(off, size)) != 0]


def text_length(texts, tid):
    """Return the g[2] length field: the longest text in characters."""
    longest = 0
    for language, text in texts.items():
        try:
            length = len(text.decode('utf-8'))
        except UnicodeDecodeError:
            raise ValueError(f'string {tid}, language {language}: invalid UTF-8') from None
        if length > 255:
            raise ValueError(f'string {tid}, language {language}: {length} characters exceeds the 8-bit length accessor')
        longest = max(longest, length)
    return longest


def emit_string_tables(fw, languages, texts, lengths, *, share=False):
    """Rebuild the g[2] text tables of fw and return (data, layout).

    texts[tid] maps every language in languages to its UTF-8 text; lengths[tid]
    is the g[2] length field. IDs may be appended but not removed. The first
    locale row stays adjacent to the CCX root. g[2] moves into the arena when
    the stock records cannot hold every ID, and stays there on later rebuilds.
    Every arena byte that fw does not own is preserved.

    By default each (text ID, language) has its own raw index and each text ID
    its own locale row. With share, identical texts use one raw index and
    identical rows one row; the firmware lookup reads both layouts.
    """
    count = len(texts)
    if not fw.text_count <= count <= MAX_TEXT_IDS or len(lengths) != count:
        raise ValueError(f'cannot emit {count} text IDs for an image with {fw.text_count}')
    stride = (2 * len(languages) + 3) & ~3

    raw_texts, raw_index = [], {}
    rows, row_index, text_rows = [], {}, []
    for tid in range(count):
        row = []
        for language in languages:
            text = texts[tid][language]
            index = raw_index.get(text) if share else None
            if index is None:
                index = len(raw_texts)
                raw_texts.append(text)
                raw_index[text] = index
            row.append(index)
        row = tuple(row)
        index = row_index.get(row) if share else None
        if index is None:
            index = len(rows)
            rows.append(row)
            row_index[row] = index
        text_rows.append(index)
    if len(raw_texts) > 65536:
        raise ValueError('raw string indexes exceed 16-bit capacity')

    pool, pool_offsets = bytearray(), {}
    for text in raw_texts:
        if text not in pool_offsets:
            pool_offsets[text] = len(pool)
            pool.extend(text + b'\0')

    relocate = fw.g2_relocated or count > fw.text_count
    g2_size = (count + 1) * G2_RECORD if relocate else 0
    array_size = len(rows) * stride
    tail_size = g2_size + 4 * len(raw_texts) + len(pool)
    used = array_size + tail_size
    capacity = sum(fw.available)
    if used > capacity:
        raise ValueError(f'language resources need {used} bytes; arena has {capacity} (short by {used-capacity})')

    # Keep the first locale row adjacent to the CCX root for existing readers.
    # g[2], the pointer table and the text can occupy any remaining contiguous gap.
    free = bytearray(fw.available)
    if 0 in free[:array_size]:
        raise ValueError('expanded locale arrays would overwrite preserved data')
    free[:array_size] = bytes(array_size)
    pos = free.find(b'\1' * tail_size)
    while pos >= 0 and (fw.start + pos) % 4:
        pos = free.find(b'\1' * tail_size, pos + 1)
    if pos < 0:
        raise ValueError(f'no contiguous space for {tail_size} bytes of g[2]/pointers/text after preserving unrelated data')
    g2 = fw.start + pos if relocate else fw.g2
    raw_table = fw.start + pos + g2_size
    pool_start = raw_table + 4 * len(raw_texts)

    data = bytearray(fw.data)
    for i, available in enumerate(fw.available):
        if available:
            data[fw.start + i] = 255
    if relocate and not fw.g2_relocated:
        # Release the stock records; g[3] and its successors stay in place.
        data[fw.g2:fw.g3] = b'\xff' * (fw.g3 - fw.g2)
    data[pool_start:pool_start + len(pool)] = pool
    for index, row in enumerate(rows):
        off = fw.start + index * stride
        data[off:off + stride] = struct.pack(f'<{len(row)}H', *row).ljust(stride, b'\0')
    for index, text in enumerate(raw_texts):
        struct.pack_into('<I', data, raw_table + index * 4,
                         fw.FLASH_BASE + pool_start + pool_offsets[text])
    for tid in range(count):
        # Keep the unused halfword of existing records.
        pad = fw.read_u16(fw.g2 + tid * G2_RECORD + 2) if tid < fw.text_count else 0
        struct.pack_into('<HHI', data, g2 + tid * G2_RECORD, lengths[tid], pad,
                         fw.FLASH_BASE + fw.start + text_rows[tid] * stride)
    if relocate:
        data[g2 + count * G2_RECORD:g2 + (count + 1) * G2_RECORD] = G2_TERMINATOR
        struct.pack_into('<I', data, fw.globals_addr + 2 * 4, fw.FLASH_BASE + g2)
    struct.pack_into('<I', data, fw.root, fw.FLASH_BASE + raw_table)
    verify_string_tables(fw, data, languages, texts, lengths, g2)
    return data, {
        'used': used, 'capacity': capacity, 'unique_strings': len(pool_offsets),
        'raw_entries': len(raw_texts), 'rows': len(rows), 'raw_table': raw_table,
        'g2': g2, 'g2_relocated': relocate,
    }


def verify_string_tables(fw, data, languages, texts, lengths, g2):
    """Check rebuilt tables against texts and lengths; raise ValueError on mismatch.

    Strings are read as the firmware lookup reads them: globals[2], the g[2]
    record, the locale row and the raw pointer reached through the CCX root.
    Only bytes the rebuild may own can differ from fw: free arena bytes, the
    g[2] records, the stock records it released, the globals[2] slot and the root.
    """
    base = fw.FLASH_BASE
    count = len(texts)
    u16 = lambda off: struct.unpack_from('<H', data, off)[0]
    u32 = lambda off: struct.unpack_from('<I', data, off)[0]

    def offset(ptr, what):
        off = ptr - base
        if not fw.ccx_off <= off < fw.end:
            raise ValueError(f'string table verification: {what} 0x{ptr:08X} outside CCX')
        return off

    if offset(u32(fw.globals_addr + 2 * 4), 'globals[2]') != g2:
        raise ValueError('string table verification: globals[2] does not point to g[2]')
    relocated = g2 != fw.g2 or fw.g2_relocated
    if relocated and data[g2 + count * G2_RECORD:g2 + (count + 1) * G2_RECORD] != G2_TERMINATOR:
        raise ValueError('string table verification: relocated g[2] has no terminator')
    if not relocated and count != fw.text_count:
        raise ValueError('string table verification: stock g[2] cannot hold new IDs')
    raw = offset(u32(fw.root), 'raw string table')
    for tid in range(count):
        rec = g2 + tid * G2_RECORD
        if u16(rec) != lengths[tid]:
            raise ValueError(f'string table verification: length of string {tid}')
        row = offset(u32(rec + 4), f'locale row of string {tid}')
        for slot, language in enumerate(languages):
            text = offset(u32(raw + u16(row + slot * 2) * 4), f'text of string {tid}')
            end = data.find(b'\0', text, fw.end)
            if end < 0 or data[text:end] != texts[tid][language]:
                raise ValueError(f'string table verification: string {tid}, language {language}')

    allowed = bytearray(len(data))
    for i, available in enumerate(fw.available):
        allowed[fw.start + i] = available
    records = (fw.g2, fw.g3) if relocated and not fw.g2_relocated else (fw.g2, fw.g2 + fw.text_count * G2_RECORD)
    for lo, hi in (records, (fw.globals_addr + 8, fw.globals_addr + 12), (fw.root, fw.root + 4)):
        allowed[lo:hi] = b'\1' * (hi - lo)
    changed = next((off for off in range(len(data)) if data[off] != fw.data[off] and not allowed[off]), None)
    if changed is not None:
        raise ValueError(f'string table verification: rebuild changed preserved data at 0x{base + changed:08X}')


def export_tsv(fw, language):
    if language not in fw.languages:
        raise ValueError('language is not present in the image')
    return export_tsv_entries(language, {tid: fw.texts[tid, language] for tid in range(fw.text_count)})


def build_languages(fw, sources, ignore_input_crc=False, *, skip_english=True):
    bad = fw.invalid_crcs()
    if bad and not ignore_input_crc:
        raise ValueError('invalid input CRC: ' + ', '.join(bad))

    count = fw.text_count
    english = {tid: fw.texts[tid, 0] for tid in range(count)}
    translations, warnings = load_translations(sources, english, skip_english=skip_english)
    if any(not 0 <= lang < fw.option_count for lang in translations):
        raise ValueError(f'language must be within 0..{fw.option_count-1}')

    languages = sorted(translations)
    mask = sum(1 << language for language in languages)
    if mask & ((1 << 13) | (1 << 19)) and mask & ((1 << 16) | (1 << 17)):
        raise ValueError('Japanese and Chinese cannot be enabled together: firmware uses one font family')

    # Distinguish regional variants only when both are included and their menu
    # labels collide. Preserve distinct custom labels and explicitly empty text.
    base_str = fw.read_u16(fw.lan + fw.G8_BASE_STR)
    for first, second, first_suffix, second_suffix in (
        (4, 5, b' (ES)', b' (LatAm)'),
        (6, 7, b' (PT)', b' (BR)'),
        (16, 17, b' (TW)', b' (CN)'),
    ):
        if first not in translations or second not in translations:
            continue
        for texts in translations.values():
            label = texts[base_str + first]
            if label and label == texts[base_str + second]:
                texts[base_str + first] = label + first_suffix
                texts[base_str + second] = label + second_suffix

    lengths = [text_length({language: translations[language][tid] for language in languages}, tid)
               for tid in range(count)]
    texts = [{language: translations[language][tid] for language in languages}
             for tid in range(count)]
    data, layout = emit_string_tables(fw, languages, texts, lengths)
    used, capacity, shared = layout['used'], layout['capacity'], layout['unique_strings']
    raw_table = layout['raw_table']

    struct.pack_into('<I', data, fw.lan + fw.G8_BITMASK, mask)
    if data[fw.lan + fw.G8_DEFAULT] not in languages:
        data[fw.lan + fw.G8_DEFAULT] = 0

    # As in unlock_languages, do not let EEPROM restore an old LNC mask.
    # LAN maps compiled slots; LNC enables them and selects the font family.
    flags = fw.read_u16(fw.lnc + fw.G6_FLAGS) & ~1
    struct.pack_into('<H', data, fw.lnc + fw.G6_FLAGS, flags)
    struct.pack_into('<I', data, fw.lnc + fw.G6_DEFAULT, mask)
    struct.pack_into('>H', data, fw.end, fw.crcfunc(data[fw.ccx_off:fw.end]))

    # emit_string_tables() verified the strings and preserved data. Check the
    # language configuration written here and the CCX checksum.
    result = type(fw)(fw.path, data)
    if result.languages != tuple(languages):
        raise ValueError('output language mapping verification failed')
    if result.crcfunc(data[fw.ccx_off:fw.end+2]) != 0:
        raise ValueError('output CCX CRC verification failed')

    fallbacks = len(warnings)
    if re.fullmatch(r'SX\d{3}-\d{4}[+!~][0-9A-Za-z]{3,4}', fw.cdx_sid):
        warnings.append('image has an Airbreak build stamp; stock translations may overwrite custom labels. '
                        'Prefer rebuilding languages before patching, or use translations adapted to this image.')
    return bytes(data), warnings, {
        'languages': languages, 'texts': count, 'unique_strings': shared,
        'old_used': fw.used, 'used': used, 'capacity': capacity,
        'free': capacity - used, 'fallbacks': fallbacks,
        'preserved': fw.end - fw.start - capacity,
        'mask': mask, 'default': result.read_u8(result.lan + result.G8_DEFAULT),
        'table_before': fw.raw_table, 'table_after': raw_table,
    }

#!/usr/bin/env python3
"""Parser for Air11 external SPI NOR dumps.

The first 64 KiB erase block contains raw security and manufacturing data. The
remaining flash is split into Micrium uC/FS NOR devices. Each device is a
wear-levelled logical block device whose sectors contain a FAT12 filesystem.
"""

from __future__ import annotations

import binascii
import hashlib
import struct
from collections import Counter
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Iterable, Iterator, Optional


NOR_SIZE = 0x1000000
ERASE_BLOCK_SIZE = 0x10000
RAW_REGION_SIZE = ERASE_BLOCK_SIZE

BLOCK_MAGIC = b"FS NOR  "
BLOCK_HEADER_SIZE = 0x20
SECTOR_HEADER_SIZE = 0x10
LOW_FORMAT_VERSION = 0x0401
VALID_SECTOR_STATUS = 0xFFFF0000
ERASED_SECTOR_STATUS = 0xFFFFFFFF

SECURITY_DATA_OFFSET = 0x000
SECURITY_DATA_SIZE = 0x200
AUTH_KEY_RING_OFFSET = 0x000
AUTH_KEY_RING_SIZE = 0x100
OTA_KEY_OFFSET = 0x100
OTA_KEY_SIZE = 0x20
STEEHL_SECURITY_DATA_OFFSET = 0x180
STEEHL_SECURITY_DATA_SIZE = 0x80

VOLUME_NAMES = ("settings", "datalog", "upgrade")


class NorFormatError(ValueError):
    """The input does not match the Air11 uC/FS NOR layout."""


def crc16_ccitt_false(data: bytes) -> int:
    """Return CRC-16/CCITT-FALSE (poly 0x1021, init 0xffff)."""
    return binascii.crc_hqx(data, 0xFFFF)


@dataclass(frozen=True)
class RawRegion:
    name: str
    offset: int
    size: int
    aliases: tuple[str, ...] = ()


@dataclass(frozen=True)
class NamedKey:
    name: str
    offset: int
    size: int


NAMED_KEYS = (
    NamedKey("OTA", OTA_KEY_OFFSET, OTA_KEY_SIZE),
)


RAW_REGIONS = (
    RawRegion(
        "security-data", SECURITY_DATA_OFFSET, SECURITY_DATA_SIZE,
        ("security",),
    ),
    RawRegion(
        "auth-key-ring", AUTH_KEY_RING_OFFSET, AUTH_KEY_RING_SIZE,
        ("auth-keys",),
    ),
    RawRegion(
        "ota-key", OTA_KEY_OFFSET, OTA_KEY_SIZE,
        ("ota",),
    ),
    RawRegion(
        "steehl-security-data", STEEHL_SECURITY_DATA_OFFSET,
        STEEHL_SECURITY_DATA_SIZE, ("steehl-security",),
    ),
    RawRegion(
        "manufacturing-data", 0x00E000, 0x400,
        ("md0", "_md0"),
    ),
    RawRegion(
        "manufacturing-test-record", 0x00F000, 0x400,
        ("md1", "_md1"),
    ),
)


@dataclass(frozen=True)
class BlockHeader:
    offset: int
    erase_count: int
    version: int
    sector_size: int
    block_count: int
    stored_crc: int
    computed_crc: int

    @property
    def crc_ok(self) -> bool:
        return self.stored_crc == self.computed_crc


@dataclass(frozen=True)
class SectorRecord:
    physical_index: int
    offset: int
    logical_sector: int
    status: int
    stored_data_crc: int
    stored_header_crc: int
    computed_header_crc: int

    @property
    def header_crc_ok(self) -> bool:
        return self.stored_header_crc == self.computed_header_crc


@dataclass(frozen=True)
class FatInfo:
    oem: str
    volume_label: str
    fs_type: str
    bytes_per_sector: int
    sectors_per_cluster: int
    reserved_sectors: int
    fat_count: int
    root_entries: int
    sectors_per_fat: int
    total_sectors: int
    fat_copy_state: str


@dataclass(frozen=True)
class FatDirEntry:
    name: str
    short_name: str
    attributes: int
    first_cluster: int
    size: int

    @property
    def is_dir(self) -> bool:
        return bool(self.attributes & 0x10)


@dataclass(frozen=True)
class StagedUpgrade:
    container: bytes
    allocated_size: int
    trailing_nonzero_bytes: int

    @property
    def container_size(self) -> int:
        return len(self.container)

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.container).hexdigest()


class NorVolume:
    """One mounted Micrium uC/FS NOR logical block device."""

    def __init__(
            self, image: "As11NorImage", index: int, name: str,
            start: int, block_count: int, sector_size: int):
        self.image = image
        self.index = index
        self.name = name
        self.start = start
        self.block_count = block_count
        self.sector_size = sector_size
        self.record_size = SECTOR_HEADER_SIZE + sector_size
        self.sectors_per_block = (
            (ERASE_BLOCK_SIZE - BLOCK_HEADER_SIZE) // self.record_size
        )
        self.physical_sector_count = self.block_count * self.sectors_per_block
        reserve = max(
            self.physical_sector_count * 10 // 100,
            self.sectors_per_block,
        )
        self.logical_sector_count = self.physical_sector_count - reserve

        self.block_headers: list[Optional[BlockHeader]] = []
        self.invalid_block_indexes: list[int] = []
        self.mapping: list[Optional[SectorRecord]] = [
            None
        ] * self.logical_sector_count
        self.status_counts: Counter[int] = Counter()
        self.duplicate_valid_records = 0
        self.out_of_range_valid_records = 0
        self.mapped_header_crc_errors = 0
        self.mapped_data_crc_errors = 0

        self._mount()

    @property
    def end(self) -> int:
        return self.start + self.block_count * ERASE_BLOCK_SIZE

    @property
    def mapped_sector_count(self) -> int:
        return sum(record is not None for record in self.mapping)

    @property
    def unmapped_sector_count(self) -> int:
        return self.logical_sector_count - self.mapped_sector_count

    def _parse_block_header(self, block_index: int) -> Optional[BlockHeader]:
        offset = self.start + block_index * ERASE_BLOCK_SIZE
        raw = self.image.data[offset:offset + BLOCK_HEADER_SIZE]
        if len(raw) != BLOCK_HEADER_SIZE or raw[:8] != BLOCK_MAGIC:
            return None

        header = BlockHeader(
            offset=offset,
            erase_count=struct.unpack_from("<I", raw, 0x08)[0],
            version=struct.unpack_from("<H", raw, 0x0C)[0],
            sector_size=struct.unpack_from("<H", raw, 0x0E)[0],
            block_count=struct.unpack_from("<H", raw, 0x10)[0],
            stored_crc=struct.unpack_from("<H", raw, 0x1E)[0],
            computed_crc=crc16_ccitt_false(raw[:0x1E]),
        )
        if (
                header.version != LOW_FORMAT_VERSION
                or header.sector_size != self.sector_size
                or header.block_count != self.block_count
                or not header.crc_ok):
            return None
        return header

    def _parse_sector_record(
            self, block_index: int, slot: int,
            physical_index: int) -> SectorRecord:
        offset = (
            self.start + block_index * ERASE_BLOCK_SIZE
            + BLOCK_HEADER_SIZE + slot * self.record_size
        )
        raw = self.image.data[offset:offset + SECTOR_HEADER_SIZE]
        return SectorRecord(
            physical_index=physical_index,
            offset=offset,
            logical_sector=struct.unpack_from("<I", raw, 0x00)[0],
            status=struct.unpack_from("<I", raw, 0x04)[0],
            stored_data_crc=struct.unpack_from("<H", raw, 0x08)[0],
            stored_header_crc=struct.unpack_from("<H", raw, 0x0E)[0],
            computed_header_crc=crc16_ccitt_false(raw[:0x0E]),
        )

    def _mount(self) -> None:
        for block_index in range(self.block_count):
            header = self._parse_block_header(block_index)
            self.block_headers.append(header)
            if header is None:
                self.invalid_block_indexes.append(block_index)

        # The native mount accepts one block without a valid header. It is the
        # block currently reserved for erase/compaction and contributes no L2P
        # entries.
        if len(self.invalid_block_indexes) > 1:
            raise NorFormatError(
                f"{self.name}: {len(self.invalid_block_indexes)} invalid block "
                "headers; firmware accepts at most one"
            )

        for block_index, header in enumerate(self.block_headers):
            if header is None:
                continue
            for slot in range(self.sectors_per_block):
                physical_index = (
                    block_index * self.sectors_per_block + slot
                )
                record = self._parse_sector_record(
                    block_index, slot, physical_index
                )
                self.status_counts[record.status] += 1
                if record.status != VALID_SECTOR_STATUS:
                    continue
                if record.logical_sector >= self.logical_sector_count:
                    self.out_of_range_valid_records += 1
                    continue
                if self.mapping[record.logical_sector] is not None:
                    self.duplicate_valid_records += 1
                    continue
                self.mapping[record.logical_sector] = record

        for record in (r for r in self.mapping if r is not None):
            if not record.header_crc_ok:
                self.mapped_header_crc_errors += 1
            data = self._record_data(record)
            if crc16_ccitt_false(data) != record.stored_data_crc:
                self.mapped_data_crc_errors += 1

    def _record_data(self, record: SectorRecord) -> bytes:
        start = record.offset + SECTOR_HEADER_SIZE
        return self.image.data[start:start + self.sector_size]

    def read_sector(self, logical_sector: int) -> bytes:
        if not 0 <= logical_sector < self.logical_sector_count:
            raise IndexError(f"logical sector out of range: {logical_sector}")
        record = self.mapping[logical_sector]
        if record is None:
            return bytes(self.sector_size)
        return self._record_data(record)

    def read(self, offset: int, size: int) -> bytes:
        if offset < 0 or size < 0:
            raise ValueError("negative logical offset or size")
        end = offset + size
        capacity = self.logical_sector_count * self.sector_size
        if end > capacity:
            raise ValueError(
                f"logical read 0x{offset:x}..0x{end:x} exceeds "
                f"0x{capacity:x}"
            )
        if not size:
            return b""
        first = offset // self.sector_size
        last = (end - 1) // self.sector_size
        data = b"".join(self.read_sector(i) for i in range(first, last + 1))
        inner = offset - first * self.sector_size
        return data[inner:inner + size]

    def logical_image(self) -> bytes:
        return b"".join(
            self.read_sector(i) for i in range(self.logical_sector_count)
        )

    def with_logical_image(
            self, logical_image: bytes
    ) -> tuple[bytes, tuple[int, ...]]:
        expected = self.logical_sector_count * self.sector_size
        if len(logical_image) != expected:
            raise ValueError(
                f"{self.name}: logical image must be {expected} bytes, "
                f"got {len(logical_image)}"
            )

        changes = []
        for logical_sector in range(self.logical_sector_count):
            start = logical_sector * self.sector_size
            new_data = logical_image[start:start + self.sector_size]
            if new_data == self.read_sector(logical_sector):
                continue
            changes.append((logical_sector, new_data))

        # New FAT allocations reach logical sectors that have no current FTL
        # mapping. Assign those sectors to erased records in valid blocks.
        free_records = []
        for block_index, block_header in enumerate(self.block_headers):
            if block_header is None:
                continue
            for slot in range(self.sectors_per_block):
                physical_index = block_index * self.sectors_per_block + slot
                record = self._parse_sector_record(
                    block_index, slot, physical_index
                )
                if record.status == ERASED_SECTOR_STATUS:
                    free_records.append(record)

        required = sum(
            self.mapping[logical_sector] is None
            for logical_sector, _data in changes
        )
        if required > len(free_records):
            raise NorFormatError(
                f"{self.name}: need {required} free physical records, "
                f"found {len(free_records)}"
            )

        result = bytearray(self.image.data)
        free_iter = iter(free_records)
        changed_offsets = []
        for logical_sector, new_data in changes:
            record = self.mapping[logical_sector]
            if record is None:
                record = next(free_iter)
                header = bytearray(SECTOR_HEADER_SIZE)
                struct.pack_into("<I", header, 0x00, logical_sector)
                struct.pack_into("<I", header, 0x04, VALID_SECTOR_STATUS)
            else:
                header = bytearray(
                    result[record.offset:record.offset + SECTOR_HEADER_SIZE]
                )

            struct.pack_into(
                "<H", header, 0x08, crc16_ccitt_false(new_data)
            )
            struct.pack_into(
                "<H", header, 0x0E, crc16_ccitt_false(header[:0x0E])
            )
            result[
                record.offset:record.offset + SECTOR_HEADER_SIZE
            ] = header
            data_start = record.offset + SECTOR_HEADER_SIZE
            result[data_start:data_start + self.sector_size] = new_data
            changed_offsets.append(record.offset)

        return bytes(result), tuple(changed_offsets)

    def fat(self) -> "Fat12Volume":
        return Fat12Volume(self)


class As11NorImage:
    """A complete 16 MiB Air11 external NOR dump."""

    def __init__(self, data: bytes, source: Optional[Path] = None):
        if len(data) != NOR_SIZE:
            raise NorFormatError(
                f"expected a {NOR_SIZE}-byte NOR image, got {len(data)} bytes"
            )
        self.data = data
        self.source = source
        self.sha256 = hashlib.sha256(data).hexdigest()
        self.volumes = self._discover_volumes()

    @classmethod
    def from_file(cls, path: str | Path) -> "As11NorImage":
        source = Path(path)
        return cls(source.read_bytes(), source)

    @staticmethod
    def _candidate_header(data: bytes, offset: int) -> Optional[BlockHeader]:
        raw = data[offset:offset + BLOCK_HEADER_SIZE]
        if len(raw) != BLOCK_HEADER_SIZE or raw[:8] != BLOCK_MAGIC:
            return None
        header = BlockHeader(
            offset=offset,
            erase_count=struct.unpack_from("<I", raw, 0x08)[0],
            version=struct.unpack_from("<H", raw, 0x0C)[0],
            sector_size=struct.unpack_from("<H", raw, 0x0E)[0],
            block_count=struct.unpack_from("<H", raw, 0x10)[0],
            stored_crc=struct.unpack_from("<H", raw, 0x1E)[0],
            computed_crc=crc16_ccitt_false(raw[:0x1E]),
        )
        if (
                header.version != LOW_FORMAT_VERSION
                or not header.crc_ok
                or header.sector_size == 0
                or header.block_count == 0):
            return None
        return header

    def _discover_volumes(self) -> list[NorVolume]:
        volumes = []
        cursor = RAW_REGION_SIZE
        index = 0
        while cursor < len(self.data):
            # Native formatting permits one headerless block per device. If it
            # happens to be the first block, the next block still identifies
            # the device geometry and its start remains the current cursor.
            header = self._candidate_header(self.data, cursor)
            if header is None:
                header = self._candidate_header(
                    self.data, cursor + ERASE_BLOCK_SIZE
                )
            if header is None:
                raise NorFormatError(
                    f"no uC/FS NOR header at 0x{cursor:06x}"
                )
            end = cursor + header.block_count * ERASE_BLOCK_SIZE
            if end > len(self.data):
                raise NorFormatError(
                    f"volume at 0x{cursor:06x} extends past end of image"
                )
            name = (
                VOLUME_NAMES[index]
                if index < len(VOLUME_NAMES)
                else f"nor-{index}"
            )
            volumes.append(NorVolume(
                self, index, name, cursor,
                header.block_count, header.sector_size,
            ))
            cursor = end
            index += 1

        if cursor != len(self.data):
            raise NorFormatError(
                f"uC/FS devices end at 0x{cursor:x}, image at 0x{len(self.data):x}"
            )
        return volumes

    def volume(self, identifier: str | int) -> NorVolume:
        if isinstance(identifier, int):
            index = identifier
        else:
            value = identifier.strip().lower()
            if value.startswith("nor:"):
                value = value[4:]
            if value.isdigit():
                index = int(value)
            else:
                for volume in self.volumes:
                    if value in (volume.name, volume.name.replace("-", "")):
                        return volume
                raise KeyError(f"unknown NOR volume: {identifier}")
        if not 0 <= index < len(self.volumes):
            raise KeyError(f"unknown NOR volume: {identifier}")
        return self.volumes[index]

    def region(self, identifier: str) -> RawRegion:
        value = identifier.strip().lower()
        for region in RAW_REGIONS:
            if value == region.name or value in region.aliases:
                return region
        raise KeyError(f"unknown raw region: {identifier}")

    def read_region(self, identifier: str) -> bytes:
        region = self.region(identifier)
        return self.data[region.offset:region.offset + region.size]

    @staticmethod
    def named_key(identifier: str) -> NamedKey:
        value = identifier.strip().casefold()
        for key in NAMED_KEYS:
            if value == key.name.casefold():
                return key
        raise KeyError(f"unknown key: {identifier}")

    def key(self, identifier: str) -> bytes:
        key = self.named_key(identifier)
        return self.data[key.offset:key.offset + key.size]

    def with_key(self, value: bytes, identifier: str) -> bytes:
        key = self.named_key(identifier)
        if len(value) != key.size:
            raise ValueError(
                f"{key.name} key must be {key.size} bytes, "
                f"got {len(value)}"
            )
        result = bytearray(self.data)
        result[key.offset:key.offset + key.size] = value
        return bytes(result)

    def staged_upgrade(self) -> StagedUpgrade:
        raw = self.volume("upgrade").fat().read_file(
            "/UPGRADE/Upgrade.abc"
        )
        if len(raw) < 4:
            raise NorFormatError("staged Upgrade.abc is shorter than its header")
        size = struct.unpack_from("<I", raw, 0)[0]
        if not size:
            raise NorFormatError("no staged OTA container")
        if size > len(raw) - 4:
            raise NorFormatError(
                f"staged OTA size {size} exceeds Upgrade.abc size {len(raw)}"
            )
        container = raw[4:4 + size]
        if container[:4] != b"OTA!":
            raise NorFormatError("staged upgrade does not contain an OTA container")
        return StagedUpgrade(
            container=container,
            allocated_size=len(raw),
            trailing_nonzero_bytes=sum(value != 0 for value in raw[4 + size:]),
        )


class Fat12Volume:
    """Minimal read-only FAT12/VFAT parser for internal NOR inspection."""

    def __init__(self, volume: NorVolume):
        self.volume = volume
        boot = volume.read_sector(0)
        if len(boot) < 512 or boot[510:512] != b"\x55\xaa":
            raise NorFormatError(f"{volume.name}: no FAT boot signature")

        self.bytes_per_sector = struct.unpack_from("<H", boot, 0x0B)[0]
        self.sectors_per_cluster = boot[0x0D]
        self.reserved_sectors = struct.unpack_from("<H", boot, 0x0E)[0]
        self.fat_count = boot[0x10]
        self.root_entries = struct.unpack_from("<H", boot, 0x11)[0]
        total16 = struct.unpack_from("<H", boot, 0x13)[0]
        total32 = struct.unpack_from("<I", boot, 0x20)[0]
        self.total_sectors = total16 or total32
        self.sectors_per_fat = struct.unpack_from("<H", boot, 0x16)[0]

        if self.bytes_per_sector != volume.sector_size:
            raise NorFormatError(
                f"{volume.name}: FAT sector size {self.bytes_per_sector} "
                f"does not match FTL sector size {volume.sector_size}"
            )
        if (
                not self.sectors_per_cluster
                or not self.sectors_per_fat
                or not self.fat_count):
            raise NorFormatError(f"{volume.name}: invalid FAT geometry")
        if self.total_sectors > volume.logical_sector_count:
            raise NorFormatError(
                f"{volume.name}: FAT uses {self.total_sectors} sectors, "
                f"FTL exposes {volume.logical_sector_count}"
            )

        self.root_dir_sectors = (
            self.root_entries * 32 + self.bytes_per_sector - 1
        ) // self.bytes_per_sector
        self.fat_start = self.reserved_sectors
        self.root_start = (
            self.fat_start + self.fat_count * self.sectors_per_fat
        )
        self.data_start = self.root_start + self.root_dir_sectors
        data_sectors = self.total_sectors - self.data_start
        cluster_count = data_sectors // self.sectors_per_cluster
        if cluster_count >= 4085:
            raise NorFormatError(
                f"{volume.name}: filesystem is not FAT12 ({cluster_count} clusters)"
            )

        fat_size = self.sectors_per_fat * self.bytes_per_sector
        fat_copies = [
            volume.read(
                (self.fat_start + index * self.sectors_per_fat)
                * self.bytes_per_sector,
                fat_size,
            )
            for index in range(self.fat_count)
        ]
        self._fat = fat_copies[0]
        if len(fat_copies) == 1:
            fat_copy_state = "single"
        elif all(copy == self._fat for copy in fat_copies[1:]):
            fat_copy_state = "mirrored"
        elif all(
                copy[:3] == self._fat[:3]
                and not any(copy[3:])
                for copy in fat_copies[1:]):
            fat_copy_state = "secondary-header-only"
        else:
            fat_copy_state = "diverged"
        self.info = FatInfo(
            oem=self._ascii(boot[3:11]),
            volume_label=self._ascii(boot[0x2B:0x36]),
            fs_type=self._ascii(boot[0x36:0x3E]),
            bytes_per_sector=self.bytes_per_sector,
            sectors_per_cluster=self.sectors_per_cluster,
            reserved_sectors=self.reserved_sectors,
            fat_count=self.fat_count,
            root_entries=self.root_entries,
            sectors_per_fat=self.sectors_per_fat,
            total_sectors=self.total_sectors,
            fat_copy_state=fat_copy_state,
        )

    @staticmethod
    def _ascii(value: bytes) -> str:
        return value.decode("ascii", errors="replace").rstrip(" \x00")

    @staticmethod
    def _lfn_checksum(short_name: bytes) -> int:
        checksum = 0
        for value in short_name:
            checksum = (((checksum & 1) << 7) | (checksum >> 1)) + value
            checksum &= 0xFF
        return checksum

    def _fat_entry(self, cluster: int) -> int:
        offset = cluster + cluster // 2
        if offset + 1 >= len(self._fat):
            raise NorFormatError(f"FAT cluster out of range: {cluster}")
        pair = struct.unpack_from("<H", self._fat, offset)[0]
        return (pair >> 4 if cluster & 1 else pair) & 0x0FFF

    def _cluster_chain(self, first_cluster: int) -> Iterator[int]:
        if first_cluster < 2:
            return
        seen = set()
        cluster = first_cluster
        while 2 <= cluster < 0xFF8:
            if cluster in seen:
                raise NorFormatError(f"FAT cluster loop at {cluster}")
            seen.add(cluster)
            yield cluster
            cluster = self._fat_entry(cluster)
        if cluster == 0xFF7:
            raise NorFormatError("FAT chain reaches a bad cluster")

    def _read_cluster(self, cluster: int) -> bytes:
        sector = self.data_start + (cluster - 2) * self.sectors_per_cluster
        return self.volume.read(
            sector * self.bytes_per_sector,
            self.sectors_per_cluster * self.bytes_per_sector,
        )

    def _read_chain(self, first_cluster: int) -> bytes:
        return b"".join(
            self._read_cluster(cluster)
            for cluster in self._cluster_chain(first_cluster)
        )

    def _root_directory(self) -> bytes:
        return self.volume.read(
            self.root_start * self.bytes_per_sector,
            self.root_dir_sectors * self.bytes_per_sector,
        )

    @staticmethod
    def _decode_lfn_part(raw: bytes) -> str:
        encoded = raw[1:11] + raw[14:26] + raw[28:32]
        chars = []
        for offset in range(0, len(encoded), 2):
            code = struct.unpack_from("<H", encoded, offset)[0]
            if code in (0x0000, 0xFFFF):
                break
            chars.append(chr(code))
        return "".join(chars)

    @staticmethod
    def _short_name(raw: bytes) -> str:
        name = bytearray(raw[:8])
        if name and name[0] == 0x05:
            name[0] = 0xE5
        base = bytes(name).decode("cp437", errors="replace").rstrip()
        ext = raw[8:11].decode("cp437", errors="replace").rstrip()
        if raw[12] & 0x08:
            base = base.lower()
        if raw[12] & 0x10:
            ext = ext.lower()
        return f"{base}.{ext}" if ext else base

    def _parse_directory(self, data: bytes) -> list[FatDirEntry]:
        entries = []
        lfn_parts: dict[int, str] = {}
        lfn_checksum: Optional[int] = None
        for offset in range(0, len(data) - 31, 32):
            raw = data[offset:offset + 32]
            if raw[0] == 0x00:
                break
            if raw[0] == 0xE5:
                lfn_parts.clear()
                lfn_checksum = None
                continue
            if raw[11] == 0x0F:
                sequence = raw[0] & 0x1F
                if sequence:
                    lfn_parts[sequence] = self._decode_lfn_part(raw)
                    if lfn_checksum is None:
                        lfn_checksum = raw[13]
                    elif lfn_checksum != raw[13]:
                        lfn_parts.clear()
                        lfn_checksum = None
                continue

            short_raw = raw[:11]
            short_name = self._short_name(raw)
            if (
                    lfn_parts
                    and lfn_checksum == self._lfn_checksum(short_raw)
            ):
                name = "".join(lfn_parts[i] for i in sorted(lfn_parts))
            else:
                name = short_name
            lfn_parts.clear()
            lfn_checksum = None

            attributes = raw[11]
            if attributes & 0x08:
                continue
            first_cluster = (
                struct.unpack_from("<H", raw, 0x14)[0] << 16
                | struct.unpack_from("<H", raw, 0x1A)[0]
            )
            entries.append(FatDirEntry(
                name=name,
                short_name=short_name,
                attributes=attributes,
                first_cluster=first_cluster,
                size=struct.unpack_from("<I", raw, 0x1C)[0],
            ))
        return entries

    @staticmethod
    def _path_parts(path: str) -> tuple[str, ...]:
        value = PurePosixPath("/" + path.lstrip("/"))
        if ".." in value.parts:
            raise ValueError("parent path components are not allowed")
        return tuple(part for part in value.parts if part not in ("/", "."))

    def canonical_path(self, path: str) -> str:
        value = "/" + "/".join(self._path_parts(path))
        return value.rstrip("/") or "/"

    def _directory_entries(
            self, directory: Optional[FatDirEntry]) -> list[FatDirEntry]:
        data = (
            self._root_directory()
            if directory is None
            else self._read_chain(directory.first_cluster)
        )
        return self._parse_directory(data)

    def resolve(self, path: str) -> Optional[FatDirEntry]:
        current: Optional[FatDirEntry] = None
        for part in self._path_parts(path):
            if current is not None and not current.is_dir:
                raise FileNotFoundError(path)
            entries = self._directory_entries(current)
            current = next(
                (
                    entry for entry in entries
                    if part.casefold() in (
                        entry.name.casefold(), entry.short_name.casefold()
                    )
                ),
                None,
            )
            if current is None:
                raise FileNotFoundError(path)
        return current

    def iterdir(self, path: str = "/") -> list[FatDirEntry]:
        entry = self.resolve(path)
        if entry is not None and not entry.is_dir:
            raise NotADirectoryError(path)
        return [
            item for item in self._directory_entries(entry)
            if item.name not in (".", "..")
        ]

    def read_file(self, path: str) -> bytes:
        entry = self.resolve(path)
        if entry is None or entry.is_dir:
            raise IsADirectoryError(path)
        return self._read_chain(entry.first_cluster)[:entry.size]

    def walk(
            self, path: str = "/"
    ) -> Iterable[tuple[str, FatDirEntry]]:
        base = self.canonical_path(path)
        for entry in self.iterdir(base):
            child = (base.rstrip("/") + "/" + entry.name) or "/"
            yield child, entry
            if entry.is_dir:
                yield from self.walk(child)

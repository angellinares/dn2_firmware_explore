"""The Waverider store on the +Drive, format v1 (`docs/waverider-store.md`): bytes in, bytes out.

One subject: encoding and decoding the store's superblock and index, and planning
the writes for a set of tables. DNX is the writer on the computer; this is the
firmware project's own reading of the same document, kept so the two can be
checked against each other (`test/test_waverider_store.py` replays a plan DNX
produced), and so the firmware's reader can be tested against real store bytes.

Nothing here does I/O.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

REGION = 0x600000                  # the region's first sector
GROUP_SECTORS = 0x400              # 512 KiB: one erase group
GROUPS = {"A": 0, "B": GROUP_SECTORS}
DATA_START = 0x1000                # sectors, from the region's start
MAGIC = b"WRTB"
VERSION = 1
HEADER_BYTES = 64
INDEX_ENTRIES = 256
ENTRY_BYTES = 128
INDEX_BYTES = INDEX_ENTRIES * ENTRY_BYTES      # 32 KiB, sectors 1..64 of a group
SECTOR = 512
ALIGN = 8                          # extents start on an 8-sector (4 KiB) boundary

FLAG_USED = 1
FLAG_NO_INTERP = 2
KIND_WAVETABLE = 1
FORMAT_INT16_BE = 1

_P1, _P2, _P3, _P4, _P5 = 0x9E3779B1, 0x85EBCA77, 0xC2B2AE3D, 0x27D4EB2F, 0x165667B1
_M = 0xFFFFFFFF


def _rotl(x: int, r: int) -> int:
    return ((x << r) | (x >> (32 - r))) & _M


def xxh32(data: bytes, seed: int = 0) -> int:
    """xxHash32, as the DN2 image's own routine at 0x4014be0e computes it (checked on
    its vectors, docs/waverider-store.md). Input read as little-endian words."""
    n, i = len(data), 0
    if n >= 16:
        v = [(seed + _P1 + _P2) & _M, (seed + _P2) & _M, seed & _M, (seed - _P1) & _M]
        while i + 16 <= n:
            for k in range(4):
                (x,) = struct.unpack_from("<I", data, i)
                i += 4
                v[k] = (_rotl((v[k] + x * _P2) & _M, 13) * _P1) & _M
        h = (_rotl(v[0], 1) + _rotl(v[1], 7) + _rotl(v[2], 12) + _rotl(v[3], 18)) & _M
    else:
        h = (seed + _P5) & _M
    h = (h + n) & _M
    while i + 4 <= n:
        (x,) = struct.unpack_from("<I", data, i)
        h = (_rotl((h + x * _P3) & _M, 17) * _P4) & _M
        i += 4
    while i < n:
        h = (_rotl((h + data[i] * _P5) & _M, 11) * _P1) & _M
        i += 1
    h ^= h >> 15
    h = (h * _P2) & _M
    h ^= h >> 13
    h = (h * _P3) & _M
    h ^= h >> 16
    return h


@dataclass(frozen=True)
class Entry:
    """One used index entry."""
    name: str
    waves: int
    points: int
    start: int                     # sector, from the region's start
    length: int                    # bytes
    table_hash: int
    source_hash: int
    source_size: int
    gain: int = 0x10000            # 16.16: the level change, 1/peak
    interpolate: bool = True
    kind: int = KIND_WAVETABLE
    sample_format: int = FORMAT_INT16_BE

    def to_bytes(self) -> bytes:
        name = self.name.encode("cp1252")
        if len(name) > 63:
            raise ValueError(f"name {self.name!r} is longer than 63 bytes")
        flags = FLAG_USED | (0 if self.interpolate else FLAG_NO_INTERP)
        out = struct.pack(">HHHHHHIIIII", flags, self.kind, self.waves, self.points,
                          self.sample_format, 0, self.start, self.length,
                          self.table_hash, self.source_hash, self.source_size)
        out += name.ljust(64, b"\0") + struct.pack(">I", self.gain)
        return out.ljust(ENTRY_BYTES, b"\0")

    @classmethod
    def from_bytes(cls, raw: bytes) -> "Entry | None":
        flags, kind, waves, points, fmt, _, start, length, th, sh, ss = struct.unpack_from(
            ">HHHHHHIIIII", raw)
        if not flags & FLAG_USED:
            return None
        name = raw[32:96].split(b"\0", 1)[0].decode("cp1252")
        (gain,) = struct.unpack_from(">I", raw, 96)
        return cls(name, waves, points, start, length, th, sh, ss, gain,
                   not flags & FLAG_NO_INTERP, kind, fmt)


def index_bytes(entries: dict[int, Entry]) -> bytes:
    """The fixed 32 KiB index: entry n at n * 128, free entries zero."""
    out = bytearray(INDEX_BYTES)
    for n, e in entries.items():
        if not 0 <= n < INDEX_ENTRIES:
            raise ValueError(f"slot {n} is outside 0..{INDEX_ENTRIES - 1}")
        out[n * ENTRY_BYTES:(n + 1) * ENTRY_BYTES] = e.to_bytes()
    return bytes(out)


def superblock(generation: int, entry_count: int, index: bytes, data_end: int) -> bytes:
    """The superblock's sector: 64 bytes, its own hash at +60, then zeros."""
    head = struct.pack(">4sHHIIIII", MAGIC, VERSION, HEADER_BYTES, generation, entry_count,
                       INDEX_ENTRIES, ENTRY_BYTES, xxh32(index))
    head += struct.pack(">II", DATA_START, data_end)
    head = head.ljust(60, b"\0")
    head += struct.pack(">I", xxh32(head))
    return head.ljust(SECTOR, b"\0")


@dataclass(frozen=True)
class Superblock:
    generation: int
    entry_count: int
    index_hash: int
    data_start: int
    data_end: int


def read_superblock(sector: bytes) -> Superblock | None:
    """-> the superblock, or None if it does not check (magic, version, own hash)."""
    if len(sector) < HEADER_BYTES or sector[:4] != MAGIC:
        return None
    _, version, header, gen, count, entries, ebytes, ihash, start, end = struct.unpack_from(
        ">4sHHIIIIIII", sector)
    if (version != VERSION or header != HEADER_BYTES or entries != INDEX_ENTRIES
            or ebytes != ENTRY_BYTES or struct.unpack_from(">I", sector, 60)[0] != xxh32(sector[:60])):
        return None
    return Superblock(gen, count, ihash, start, end)


def current_group(groups: dict[str, tuple[bytes, bytes]]) -> str | None:
    """GROUPS -> (superblock sector, index): the current group, or None for an empty
    store. Valid means the superblock checks and so does its index hash. The higher
    generation wins; a tie goes to A."""
    best = None
    for name in ("A", "B"):
        sector, index = groups[name]
        sb = read_superblock(sector)
        if sb is None or xxh32(index) != sb.index_hash:
            continue
        if best is None or sb.generation > best[1]:
            best = (name, sb.generation)
    return best[0] if best else None


def plan_writes(group: str, generation: int, entries: dict[int, Entry],
                payloads: dict[int, bytes], data_end: int) -> list[dict]:
    """The writes for a store change, in the order they must happen: each payload,
    then the group's index, then its superblock. Sectors from the region's start."""
    writes = []
    for n in sorted(payloads):
        e, p = entries[n], payloads[n]
        if e.start % ALIGN or e.start < DATA_START or len(p) != e.length:
            raise ValueError(f"slot {n}: extent misaligned, before the data, or the wrong length")
        writes.append({"what": "data", "sector": e.start, "length": len(p), "hash": xxh32(p)})
    index = index_bytes(entries)
    base = GROUPS[group]
    writes.append({"what": "index", "sector": base + 1, "length": len(index), "hash": xxh32(index)})
    sb = superblock(generation, len(entries), index, data_end)
    writes.append({"what": "superblock", "sector": base, "length": len(sb), "hash": xxh32(sb)})
    return writes

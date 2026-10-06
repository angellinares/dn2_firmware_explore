"""A project's pool list, the 512-byte WRPL record (docs/for-dnx-waverider-pool.md §2, rev 4).

The firmware's side is csrc/wrstore/records.c; this builds and reads records for the
tests and for placing them on an emulated +Drive. Version 2 holds 128 entries; version 1
held 127, and reads as version 2 with an empty 128th entry.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

from . import store

MAGIC = 0x5752504C                  # 'WRPL'
VERSION = 2
BYTES = 512
ENTRIES = 128
V1_ENTRIES = 127
NONE = 0xFFFF
AUTOMATIC = 1
PROJECT_SLOTS = 129                 # 0 the working project, 1..128 as /projects
SECTOR_A = 0x800                    # sectors, from the store region's start
SECTOR_B = 0x900
HEAD = ">IHHIHH"                    # magic, version, project slot, generation, count, flags


def sector_a(p: int) -> int:
    return store.REGION + SECTOR_A + p


def sector_b(p: int) -> int:
    return store.REGION + SECTOR_B + p


def entries_of(version: int) -> int:
    return V1_ENTRIES if version == 1 else ENTRIES


@dataclass
class Record:
    project: int
    entries: list[int] = field(default_factory=list)   # store slots by pool index; NONE a gap
    automatic: bool = False
    generation: int = 0

    def positions(self, version: int = VERSION) -> list[int]:
        n = entries_of(version)
        return (list(self.entries) + [NONE] * n)[:n]

    def to_bytes(self, count: int | None = None, version: int = VERSION) -> bytes:
        pos = self.positions(version)
        used = sum(1 for s in pos if s != NONE) if count is None else count
        r = struct.pack(HEAD, MAGIC, version, self.project, self.generation, used,
                        AUTOMATIC if self.automatic else 0)
        r = (r + struct.pack(f">{len(pos)}H", *pos)).ljust(508, b"\0")
        return r + struct.pack(">I", store.xxh32(r))


def from_bytes(data: bytes) -> tuple[Record, dict]:
    """-> the record, and what a reader checks: magic, version, hash, count."""
    magic, version, project, generation, count, flags = struct.unpack_from(HEAD, data)
    n = entries_of(version)
    pos = list(struct.unpack_from(f">{n}H", data, 16))
    while pos and pos[-1] == NONE:
        pos.pop()
    rec = Record(project, pos, bool(flags & AUTOMATIC), generation)
    checks = {"magic": magic == MAGIC, "version": version, "known": version in (1, VERSION),
              "hash": struct.unpack_from(">I", data, 508)[0] == store.xxh32(data[:508]),
              "count": count == sum(1 for s in pos if s != NONE), "flags": flags,
              "reserved": not any(data[16 + 2 * n:508])}
    return rec, checks

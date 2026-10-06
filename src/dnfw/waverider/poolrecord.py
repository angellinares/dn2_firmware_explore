"""A project's pool list, the 512-byte WRPL record (docs/for-dnx-waverider-pool.md §2).

The firmware's side is csrc/wrstore/records.c; this builds and reads records for the
tests and for placing them on an emulated +Drive.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

from . import store

MAGIC = 0x5752504C                  # 'WRPL'
VERSION = 1
BYTES = 512
ENTRIES = 127
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


@dataclass
class Record:
    project: int
    entries: list[int] = field(default_factory=list)   # store slots by pool index; NONE a gap
    automatic: bool = False
    generation: int = 0

    def positions(self) -> list[int]:
        return (list(self.entries) + [NONE] * ENTRIES)[:ENTRIES]

    def to_bytes(self, count: int | None = None) -> bytes:
        pos = self.positions()
        used = sum(1 for s in pos if s != NONE) if count is None else count
        r = struct.pack(HEAD, MAGIC, VERSION, self.project, self.generation, used,
                        AUTOMATIC if self.automatic else 0)
        r = (r + struct.pack(f">{ENTRIES}H", *pos)).ljust(508, b"\0")
        return r + struct.pack(">I", store.xxh32(r))


def from_bytes(data: bytes) -> tuple[Record, dict]:
    """-> the record, and what a reader checks: magic, version, hash, count."""
    magic, version, project, generation, count, flags = struct.unpack_from(HEAD, data)
    pos = list(struct.unpack_from(f">{ENTRIES}H", data, 16))
    while pos and pos[-1] == NONE:
        pos.pop()
    rec = Record(project, pos, bool(flags & AUTOMATIC), generation)
    checks = {"magic": magic == MAGIC, "version": version == VERSION,
              "hash": struct.unpack_from(">I", data, 508)[0] == store.xxh32(data[:508]),
              "count": count == sum(1 for s in pos if s != NONE), "flags": flags}
    return rec, checks

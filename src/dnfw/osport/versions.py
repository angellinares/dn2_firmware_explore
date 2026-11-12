"""The stock Digitone II images the mods know, and what differs between them (issue #382).

Every mod is built per OS version: a spec for 1.11 and, once ported, one for 1.12, side by side
until the owner switches to 1.12 and archives 1.11. A mod reads the OS from the user's own stock
image with `identify`, never from a setting, so the file the user gives decides.

Every number here was read from the two stock images on 2026-11-12, and the 1.12 ones were
checked against other projects' claims (vault "OS 1.12 migration.md", the table of checked claims):
- the MAIN OS hashes: computed here. elekloader and modwerk record the same 1.12 hash;
- the reset clear's end: one literal in each image (`0x466b74d0`, `0x466b84d0`);
- the DMA section: the lowest and highest window literals (1.11 `0x4e6b8000`, 1.12 `0x4e6c0000`),
  the bounce buffer's bound (`+0x10000`), and the 0x40 past it that the 1.11 range always had;
- the loader cave: 138 zero bytes at `0x4028da6e` on 1.11; on 1.12 only 37 of those are zero,
  and the same 138-byte run sits at `0x4028dfae` (+0x540). Overtone puts our loader stub there.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

BASE = 0x40000400                       # where MAIN OS runs, on every version


@dataclass(frozen=True)
class Version:
    name: str                           # "1.11"
    syx_sha256: str                     # the distributed .syx
    main_sha256: str                    # MAIN OS, depacked
    main_length: int
    clear_end: int                      # the reset clears stock's data up to here
    dma: tuple[int, int]                # stock's DMA section, cached addresses (the window is +0x08000000)
    loader_cave: int                    # 138 zero bytes the platform's loader takes
    meta: bytes = b""                   # section 5: the build stamp, which no mod changes
    archived: bool = False              # True once the owner switches away from it

    @property
    def stock_end(self) -> int:
        """The first address past stock MAIN OS: where the platform's area starts"""
        return BASE + self.main_length


V111 = Version("1.11", "2af43e65e3d8390b41c9f66222620f8cce027d73ed87db00c80b440f628472e0",
               "57b06a7960b7c3dc9803bde6b31896b89a2fbdcc404a932ff503f3856d4d7a61", 3_192_192,
               0x466B74D0, (0x466B8000, 0x46701340), 0x4028DA6E, b"260908 14:25:18")
V112 = Version("1.12", "7e5b8a733d4ab1fdf7e5d22757f7d8eddaa3cbf71d0858874a791844c02ceb35",
               "a098f620019b2ad38fd7e0397df39501fb1cf6bc26d0283915f34c49446fdf1a", 3_196_288,
               0x466B84D0, (0x466C0000, 0x46709340), 0x4028DFAE, b"260930 10:59:50")
VERSIONS = {v.name: v for v in (V111, V112)}


class UnknownImage(ValueError):
    """A MAIN OS that is no stock image we know."""


def identify(main_os: bytes) -> Version:
    """The stock version this MAIN OS is (depacked, stock bytes only: the platform's area split off)"""
    sha = hashlib.sha256(main_os).hexdigest()
    for v in VERSIONS.values():
        if sha == v.main_sha256:
            return v
    lengths = ", ".join(f"{v.name} {v.main_length:,} B" for v in VERSIONS.values())
    raise UnknownImage(f"MAIN OS ({len(main_os):,} B) is no stock Digitone II image we know ({lengths})")


def by_length(main_os: bytes) -> Version | None:
    """The version whose stock length MAIN OS has, or None: for an image with the platform's area
    appended, whose stock part is then checked by its hash"""
    for v in VERSIONS.values():
        if len(main_os) >= v.main_length and identify_prefix(main_os, v):
            return v
    return None


AREA_MAGIC = b"DNFW"                    # dnfw.patch.area.MAGIC: neither stock image holds it anywhere


def of_main_os(content: bytes) -> Version:
    """The version of a MAIN OS that mods may have changed: an appended area starts with
    AREA_MAGIC exactly at its version's stock end (the stock ends differ by 4,096 B, and no stock
    image holds the magic); without an area, the stock length names it."""
    for v in VERSIONS.values():
        if len(content) > v.main_length and content[v.main_length:v.main_length + 4] == AREA_MAGIC:
            return v
    for v in VERSIONS.values():
        if len(content) == v.main_length:
            return v
    lengths = ", ".join(f"{v.name} {v.main_length:,} B" for v in VERSIONS.values())
    raise UnknownImage(f"MAIN OS ({len(content):,} B) is no Digitone II version we know ({lengths}), "
                       "with or without the platform's area")


def of_firmware(firmware) -> Version:
    """The version of a firmware file, from its build stamp (section 5), which no mod changes"""
    section = firmware.container.find(5)
    stamp = section.raw_payload if section is not None else b""
    for v in VERSIONS.values():
        if stamp == v.meta:
            return v
    raise UnknownImage(f"build stamp {stamp!r} is no Digitone II version we know")


def identify_prefix(main_os: bytes, v: Version) -> bool:
    return hashlib.sha256(main_os[:v.main_length]).hexdigest() == v.main_sha256

"""Install the startup loader and the appended area into a 1.11 MAIN OS.

The loader (`csrc/runtime/loader.S`) replaces the startup calls
`jsr data_init ; jsr bss_clear` at `0x4000053e` with one call to itself, and
copies the appended `DNFW` area out: data chunks to where the boot screen has
always run them, `CODE` chunks to their own load address (`dnfw.patch.area`).
One subject: putting those two things into a MAIN OS image, with every byte it
replaces checked against stock first.

The loader lives in a clean 138-byte cave no registered mod uses
(`0x4028da6e`, measured 2026-09-19 by `dnfw.patch.cave.classify` against every
mod's extents); it links at the next longword, `0x4028da70`, leaving 136 bytes.

On OS 1.12 (issue #382) the same 138 zero bytes sit at `0x4028dfae` (+0x540), and the area starts
at 1.12's stock end. `build` and `install` take the version (`dnfw.osport.versions`); 1.11 is the
default, so every 1.11 build is the bytes it always was. The start-up calls at `0x4000053e` are
the same bytes on both.
"""

from __future__ import annotations

import struct
from pathlib import Path

from . import area, cbuild
from ..osport import versions

BASE = 0x40000400
CALLS_VA = 0x4000053E
CALLS_STOCK = bytes.fromhex("4ebaff1c4ebaff6e")      # jsr data_init ; jsr bss_clear
CAVE_VA, CAVE_CAP = 0x4028DA6E, 138
LINK_VA = 0x4028DA70
SOURCE = Path(__file__).resolve().parents[3] / "csrc"


class LoaderError(ValueError):
    """The image is not stock where the loader must go, or it does not fit."""


def layout(os: str = "1.11") -> tuple[int, int, int]:
    """(cave, link address, area address) for OS: the cave from the version table, the loader
    at its next longword, the area at the stock end"""
    v = versions.VERSIONS[os]
    return v.loader_cave, (v.loader_cave + 3) & ~3, v.stock_end


def build(toolchain: cbuild.CToolchain | None = None, os: str = "1.11") -> cbuild.Linked:
    cave, link, _ = layout(os)
    defines = {"DN2_OS_" + os.replace(".", ""): 1} if os != "1.11" else None
    linked = cbuild.build([SOURCE / "runtime" / "loader.S"], base=link,
                          include=[SOURCE / "include"], defines=defines, toolchain=toolchain)
    room = cave + CAVE_CAP - link
    if len(linked.image) > room:
        raise LoaderError(f"the loader is {len(linked.image)} B; its cave holds {room}")
    return linked


def install(stock: bytes, chunks: list[tuple[bytes, bytes]],
            toolchain: cbuild.CToolchain | None = None, os: str = "1.11") -> bytearray:
    """Stock MAIN OS -> MAIN OS with the loader, its startup call and the area."""
    cave_va, link_va, area_va = layout(os)
    if BASE + len(stock) != area_va:
        raise LoaderError(f"MAIN OS ends at 0x{BASE + len(stock):08x}, not 0x{area_va:08x}: "
                          f"not stock Digitone II {os}, or something is already appended")
    content = bytearray(stock)
    at = CALLS_VA - BASE
    if content[at:at + 8] != CALLS_STOCK:
        raise LoaderError(f"0x{CALLS_VA:08x} holds {content[at:at + 8].hex()}, not the stock startup calls")
    cave = cave_va - BASE
    if any(content[cave:cave + CAVE_CAP]):
        raise LoaderError(f"the loader's cave at 0x{cave_va:08x} is not empty")

    linked = build(toolchain, os)
    content[link_va - BASE:link_va - BASE + len(linked.image)] = linked.image
    content[at:at + 8] = b"\x4e\xb9" + struct.pack(">I", linked["dnfw_boot"]) + b"\x4e\x71"
    blob = area.build(chunks)
    content += blob + bytes(-len(blob) % 4)
    return content

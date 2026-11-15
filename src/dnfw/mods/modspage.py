"""SETTINGS > SYSTEM > MODS: the mods a build holds, and their versions, on the instrument.

Not a mod a user picks: `dnfw mods apply` adds the page to every build, after the mods. The
owner's request (2026-11-15): a user reads the mods and versions from the instrument, with no
file to keep.

The page is one hook at the end of the SYSTEM menu's constructor and a CODE chunk in the
platform's area (`scripts/build_mods_page.py` has the method). The code is the same in every
build. The rows are data, written after the code: a 32-bit count, then 32 bytes for each row,
the name in 20 and the value in 12, both NUL-ended.

The rows: first the general ones (the OS version, the build's name and the commit the tool was
at), then one for each mod (its short name and its version from `dnfw.mods.history`).
"""

from __future__ import annotations

import json
import pathlib
import re
import struct

from . import RAM, Extent, ModError, Result, history, platform, specs

ID = "modspage"
NAME = "Mods page"
SUMMARY = "SETTINGS > SYSTEM > MODS lists the mods in the build, with their versions."
DEVICE = 0x15                      # Digitone II
SECTION = 3                        # MAIN OS
BASE = 0x40000400
SPEC = json.loads((pathlib.Path(__file__).with_name("modspage_code.json")).read_text())
SPECS = specs.load(__file__, "modspage")           # one per OS version (issue #382); SPEC is 1.11's
CODE_VA = SPEC["code"]["va"]
ROW, NAME_BYTES, VALUE_BYTES = 32, 20, 12
NAME_MAX = 12                      # a longer name runs into the value's column
ROWS_MAX = 64

# The name a mod's row shows (`scripts/build_mods_page.py` holds the list). A mod with none shows its id.
MENU_NAMES = SPEC["names"]
OS_ROW = "OS"
INFO_ROWS = 3                      # the general rows at the top: the OS, the build's name, the commit
SAFE = re.compile(r"[^A-Z0-9 .+\-_/]")


def text(s: str, most: int) -> str:
    """S as a row shows it: upper case, the characters the menu's font draws, MOST at most.
    `%` goes, because the value's text is also its own format."""
    return SAFE.sub(" ", s.upper())[:most].rstrip()


def rows(mod_ids, os: str, tag: str, commit: str) -> list[tuple[str, str]]:
    """The page's rows for a build of MOD_IDS on OS, named TAG, made at COMMIT"""
    out = []
    for mid in mod_ids:
        try:
            version = history.version(mid)
        except (KeyError, ValueError):
            version = ""
        out.append((text(MENU_NAMES.get(mid, mid), NAME_MAX), text(version, VALUE_BYTES - 1)))
    return info(os, tag, commit) + out


def info(os: str, tag: str, commit: str) -> list[tuple[str, str]]:
    """The general rows, before the mods: the OS, the build's name, the commit. Always INFO_ROWS."""
    short = (commit or "unknown")[:7] + ("+" if commit.endswith("+") else "")
    return [(OS_ROW, text(os, VALUE_BYTES - 1)),
            (text(tag, NAME_BYTES - 1) or "NO NAME", ""),
            (text("COMMIT " + short, NAME_BYTES - 1), "")]


def table(rows: list[tuple[str, str]]) -> bytes:
    """ROWS as the code reads them"""
    out = struct.pack(">I", len(rows))
    for name, value in rows:
        n, v = name.encode("ascii"), value.encode("ascii")
        if len(n) >= NAME_BYTES or len(v) >= VALUE_BYTES or b"%" in n + v:
            raise ModError(f"the MODS page cannot show the row {name!r} {value!r}")
        out += n.ljust(NAME_BYTES, b"\0") + v.ljust(VALUE_BYTES, b"\0")
    return out


def parse(data: bytes) -> list[tuple[str, str]]:
    """The rows of a table"""
    (count,) = struct.unpack_from(">I", data)
    cut = lambda b: b.split(b"\0")[0].decode("ascii")
    return [(cut(data[4 + ROW * k:4 + ROW * k + NAME_BYTES]), cut(data[4 + ROW * k + NAME_BYTES:4 + ROW * (k + 1)]))
            for k in range(count)]


def _chunk(others: list, spec: dict):
    """The page's chunk among a MAIN OS's chunks, or None"""
    for item in others:
        if item[0] == platform.area.CODE and platform.area.CodeChunk.unpack(item[1]).load == spec["code"]["va"]:
            return item
    return None


def existing(firmware) -> list[tuple[str, str]]:
    """The rows of the page FIRMWARE already holds: [] for an image with no page"""
    section = firmware.container.find(SECTION)
    if section is None:
        raise ModError("image has no MAIN OS section")
    original, others = platform.split(section.unpack())
    spec = specs.pick(SPECS, specs.of_main_os(original), ID)
    mine = _chunk(others, spec)
    if mine is None:
        return []
    return parse(platform.area.CodeChunk.unpack(mine[1]).image[len(spec["code"]["blob"]) // 2:])


def without(main: bytes) -> bytes:
    """MAIN (a MAIN OS) with no page: its chunk gone and its hook's site stock again. Unchanged
    without one. The safety check compares a rebuild with it (`dnfw.firmware.safety`)."""
    original, others = platform.split(main)
    spec = specs.pick(SPECS, specs.of_main_os(original), ID)
    mine = _chunk(others, spec)
    if mine is None:
        return main
    content = bytearray(original)
    for e in spec["edits"]:
        stock = bytes.fromhex(e["stock"])
        content[e["va"] - BASE:e["va"] - BASE + len(stock)] = stock
    rest = [item for item in others if item is not mine]
    return platform.join(bytes(content), rest) if rest else bytes(content)


def merge(old: list[tuple[str, str]], new: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """The rows of a build made on an image that has the page: NEW's general rows, then OLD's
    mods, each with NEW's version when both name it, then NEW's mods that OLD lacks"""
    fresh = dict(new[INFO_ROWS:])
    out = new[:INFO_ROWS] + [(n, fresh.pop(n, v)) for n, v in old[INFO_ROWS:]] + list(fresh.items())
    if len(out) > ROWS_MAX:
        raise ModError(f"the MODS page holds {ROWS_MAX} rows, and this build has {len(out)}")
    return out


def plan(firmware, mod_ids, os: str, tag: str, commit: str) -> list[tuple[str, str]]:
    """The rows of a build of MOD_IDS on FIRMWARE, which can hold the page already"""
    return merge(existing(firmware), rows(mod_ids, os, tag, commit))


def _size(spec: dict, count: int) -> int:
    return len(spec["code"]["blob"]) // 2 + 4 + ROW * count


def extents(firmware=None, os: str | None = None, count: int = 0) -> list[Extent]:
    """The bytes the page writes in a build with COUNT rows"""
    os = os or specs.of_firmware(firmware)
    spec = specs.pick(SPECS, os, ID)
    return ([Extent(SECTION, e["va"] - BASE, len(e["new"]) // 2, e["what"]) for e in spec["edits"]]
            + platform.extents(16 + _size(spec, count), os))


def apply(firmware, rows: list[tuple[str, str]]) -> Result:
    """FIRMWARE with the page and ROWS. An image that has the page keeps its hook and gets ROWS
    (`plan` gives a build's rows)."""
    section = firmware.container.find(SECTION)
    if section is None:
        raise ModError("image has no MAIN OS section")
    original, others = platform.split(section.unpack())
    os = specs.of_main_os(original)
    spec = specs.pick(SPECS, os, ID)
    mine = _chunk(others, spec)
    if mine is None:
        content = specs.apply_edits(original, spec, os)
    else:                              # the page is there: its hook stays, its rows are these
        for e in spec["edits"]:
            new = bytes.fromhex(e["new"])
            if original[e["va"] - BASE:e["va"] - BASE + len(new)] != new:
                raise ModError(f"0x{e['va']:08x} does not hold the MODS page's hook, and the image has its chunk")
        content = bytearray(original)
        others = [item for item in others if item is not mine]
    code_va, blob = spec["code"]["va"], bytes.fromhex(spec["code"]["blob"]) + table(rows)
    chunk = platform.area.CodeChunk(code_va, blob).pack()
    content = platform.join(bytes(content), others + [(platform.area.CODE, chunk)])
    return Result(payloads={SECTION: bytes(content)}, extents=extents(os=os, count=len(rows)),
                  notes=[f"SETTINGS > SYSTEM > MODS: {len(rows)} rows",
                         f"{len(spec['edits'])} hook in section 3, and a {len(blob):,} B CODE "
                         f"chunk at 0x{code_va:08x} in the platform's area"])


def ram(os: str = "1.11", count: int = 0) -> list[Extent]:
    """The RAM the page uses: its own chunk, the code, the kept menu's pointer and the rows"""
    spec = specs.pick(SPECS, os, ID)
    return [Extent(RAM, spec["code"]["va"], _size(spec, count),
                   "the MODS page's code and rows (a platform CODE chunk)")]

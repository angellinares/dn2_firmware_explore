"""Carry mod addresses from one OS version to another (issue #382).

`addr(os, va)` is how a generator names a stock address for an OS: the 1.11 address it was written
with, translated through the committed map for that OS (`map_<os>.json`, written by
`scripts/osport_survey.py --write`). An address the map did not decide stops the build, so a mod is
never built for an OS at a guessed address. The map holds addresses and how each was decided, no
firmware bytes.
"""

from __future__ import annotations

import functools
import json
import pathlib

from .versions import VERSIONS, Version, identify, by_length, UnknownImage   # noqa: F401

SOURCE = "1.11"                       # the version every mod's addresses are written for


class NotPorted(LookupError):
    """An address the map for that OS did not decide."""


@functools.cache
def _map(os: str) -> dict[int, dict]:
    path = pathlib.Path(__file__).with_name(f"map_{os}.json")
    if not path.exists():
        raise NotPorted(f"no address map for OS {os} ({path.name})")
    data = json.loads(path.read_text(encoding="utf-8"))
    if data["from"] != SOURCE or data["to"] != os:
        raise NotPorted(f"{path.name} maps {data['from']} to {data['to']}, not {SOURCE} to {os}")
    return {int(k, 16): v for k, v in data["addresses"].items()}


WINDOW = 0x08000000                    # the uncached window: the same RAM at address + WINDOW
RAM_TOP = 0x48000000
# The on-chip SRAM that the reset fills from the image. Every SRAM operand of every instruction the
# code map anchors names the same address on 1.11 and 1.12 (173 operands, 173 the same, 2026-11-12,
# from the votes), so an SRAM address carries over unchanged.
SRAM = (0x80000000, 0x80010000)


def _cached(va: int) -> int:
    return va - WINDOW if va >= 0x40000000 + WINDOW else va


def addr(os: str, va: int) -> int:
    """VA (a 1.11 address) on OS. Raises NotPorted when the map did not decide it.

    Mod RAM is not stock's, so it has no map entry: an address above the 1.11 DMA section stays
    the same on OS when it is above OS's DMA section too (that RAM passed the three checks on 1.12,
    vault "OS 1.12 migration.md"). One that OS's DMA section now covers is NotPorted: the mod moves."""
    if os == SOURCE:
        return va
    if os not in VERSIONS:
        raise NotPorted(f"no OS {os} in dnfw.osport.versions")
    if SRAM[0] <= va < SRAM[1]:
        return va
    old, new = VERSIONS[SOURCE], VERSIONS[os]
    ram = _cached(va)
    if old.dma[1] <= ram < RAM_TOP:
        if ram < new.dma[1]:
            raise NotPorted(f"0x{va:08x} is free on {SOURCE} but inside {os}'s DMA section "
                            f"(0x{new.dma[0]:08x}..0x{new.dma[1]:08x}): move it")
        return va
    row = _map(os).get(va)
    if row is None:
        raise NotPorted(f"0x{va:08x} has no {os} address in map_{os}.json: read it by hand and add it")
    return int(row["new"], 16)


def site(os: str, va: int, want: bytes, image: bytes, base: int = 0x40000400) -> tuple[int, bytes]:
    """A stock site a mod checks or edits, on OS: (its address, the stock bytes there).

    WANT is the site's 1.11 stock bytes and IMAGE the stock MAIN OS of OS. The bytes there must be
    WANT, or differ only in address words: each differing byte must lie in a four-byte word whose
    1.11 value `addr` maps to the word OS has there. Anything else raises NotPorted, so a guard or an
    edit never lands on code that changed."""
    new = addr(os, va)
    have = bytes(image[new - base:new - base + len(want)])
    if have == want:
        return new, have
    i, n = 0, len(want)
    while i < n:
        if want[i] == have[i]:
            i += 1
            continue
        for start in range(max(0, i - 3), min(i, n - 4) + 1):
            old_w = int.from_bytes(want[start:start + 4], "big")
            new_w = int.from_bytes(have[start:start + 4], "big")
            try:
                if addr(os, old_w) == new_w:
                    i = start + 4
                    break
            except NotPorted:
                continue
        else:
            raise NotPorted(f"0x{va:08x} -> 0x{new:08x} on {os}: {have.hex()} is not {want.hex()} "
                            f"with its addresses moved")
    return new, have


# Where a stock address can lie on 1.11: the image, its data and BSS, stock's DMA section (either
# window) and SRAM. A constant outside these is a size, an offset or a count, and stays.
STOCK_RANGES = ((0x40000400, 0x466B74D0), (0x466B8000, 0x46701340), (0x4E6B8000, 0x4E701340), SRAM)


def is_stock_address(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and any(
        lo <= value < hi for lo, hi in STOCK_RANGES)


def rebind(namespace: dict, os: str, overrides: dict | None = None) -> dict:
    """A copy of NAMESPACE (a build script's globals) for OS: every UPPERCASE constant that is a
    stock address goes through `addr`, and OVERRIDES (name -> value on OS) win, for an address the
    map cannot decide (one derived from another, or one no instruction names). An address neither
    decides raises NotPorted with its name."""
    out = dict(namespace)
    overrides = overrides or {}
    for name, value in namespace.items():
        if not name.isupper() or name in overrides or not is_stock_address(value):
            continue
        try:
            out[name] = addr(os, value)
        except NotPorted as exc:
            raise NotPorted(f"{name}: {exc}") from None
    out.update(overrides)
    return out


def render(template: str, namespace: dict, os: str, overrides: dict | None = None) -> str:
    """TEMPLATE, an f-string's text kept as a plain string, evaluated with NAMESPACE rebound for OS.
    For 1.11 it is the text the f-string always gave. The template can name OS, to pass the version
    to code it pulls in from another script."""
    ns = dict(namespace) if os == SOURCE else rebind(namespace, os, overrides)
    ns["OS"] = os
    return eval("f" + repr(template), ns)     # noqa: S307  (our own template, our own names)

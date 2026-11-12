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

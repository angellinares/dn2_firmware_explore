"""A mod's generated spec per OS version, and the checks every spec-driven mod makes (issue #382).

Each mod built for more than one OS keeps `<mod>_code.json` (1.11) and `<mod>_code_<os>.json` beside it.
The user's stock image chooses: a whole firmware file by its build stamp, a MAIN OS by where the
platform's area starts. A version a mod has no spec for is refused by name.

One subject: finding the spec and applying its guards and edits to a stock MAIN OS. The wording of
every refusal is 1.11's with the version in it, so the web patcher words them the same.
"""

from __future__ import annotations

import json
import pathlib

from . import ModError
from ..osport import versions

BASE = 0x40000400


def load(module_file: str, stem: str) -> dict[str, dict]:
    """{os: spec} for the mod beside MODULE_FILE: STEM_code.json is 1.11, STEM_code_<os>.json the others"""
    here = pathlib.Path(module_file)
    out = {"1.11": json.loads(here.with_name(f"{stem}_code.json").read_text())}
    for os in versions.VERSIONS:
        path = here.with_name(f"{stem}_code_{os}.json")
        if os != "1.11" and path.exists():
            out[os] = json.loads(path.read_text())
    return out


def of_firmware(firmware) -> str:
    """The OS of a firmware file (1.11 when no firmware is given: a caller listing 1.11's extents)"""
    if firmware is None:
        return "1.11"
    try:
        return versions.of_firmware(firmware).name
    except versions.UnknownImage as exc:
        raise ModError(str(exc)) from None


def of_main_os(content: bytes) -> str:
    try:
        return versions.of_main_os(content).name
    except versions.UnknownImage as exc:
        raise ModError(str(exc)) from None


def pick(specs: dict[str, dict], os: str, mod: str) -> dict:
    if os not in specs:
        raise ModError(f"{mod} is not yet ported to Digitone II {os}")
    return specs[os]


def apply_edits(original: bytes, spec: dict, os: str) -> bytearray:
    """ORIGINAL (stock MAIN OS, the platform's area split off) with SPEC's edits, after every guard
    and every edit's stock bytes are checked"""
    if len(original) < spec["stock_length"]:
        raise ModError(f"MAIN OS is {len(original):,} B, shorter than "
                       f"{spec['stock_length']:,}: not Digitone II {os}")
    for g in spec["guards"]:
        want = bytes.fromhex(g["bytes"])
        if original[g["va"] - BASE:g["va"] - BASE + len(want)] != want:
            raise ModError(f"0x{g['va']:08x} is not stock; this mod is for unmodified "
                           f"Digitone II {os}")
    for e in spec["edits"]:
        want = bytes.fromhex(e["stock"])
        if original[e["va"] - BASE:e["va"] - BASE + len(want)] != want:
            raise ModError(f"0x{e['va']:08x} is not stock; this mod is for unmodified "
                           f"Digitone II {os}, or another mod already wrote there")
    content = bytearray(original)
    for e in spec["edits"]:
        new = bytes.fromhex(e["new"])
        content[e["va"] - BASE:e["va"] - BASE + len(new)] = new
    return content

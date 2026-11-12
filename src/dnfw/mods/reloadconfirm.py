"""Reload confirm: an opt-in YES/NO prompt before FUNC + NO reloads the pattern.

FUNC + NO reloads the active pattern from its temporary save at once, and a
mistaken press loses the work since. This mod adds **SETTINGS > PERSONALIZE >
RELOAD CONFIRM**. Off, the default and what a fresh instrument reads, FUNC + NO
is stock. On, it asks first:

    ARE YOU SURE YOU WANT TO
    RELOAD THE PATTERN? Y/N

YES reloads exactly as FUNC + NO does (the same call, the same arguments); NO
leaves the pattern alone. A performer switches it off for the immediate reload.

**Passed on the instrument on 2026-10-04** as `reload-confirm2` (this mod's MAIN OS,
byte for byte): off is stock; on, NO keeps the edits and YES reverts them; the switch
survives a power cycle without SAVE PROJECT.

`scripts/build_reload_confirm.py` carries the reading of the firmware and the
emulator evidence: the key handler's NO case, the stock YES/NO prompt the
pattern menu's RELOAD uses, why our prompt drops the release of the NO that
opened it, the settings block the toggle's byte is persisted with, and the
PERSONALIZE item modelled on PAGE AUTOCOPY.

## How it applies

The code is assembled ahead of time (`scripts/gen_reloadconfirm_code.py` ->
`reloadconfirm_code.json`), so the browser applies exactly these bytes:

1. every guard and every edit's stock bytes are checked -- an image that
   differs is refused;
2. the two hooks are written: FUNC + NO's reload (`0x4005f1a2`) and the end of
   PERSONALIZE's constructor (`0x4009863e`), each a `jmp` into the chunk;
3. the routines are added to the platform's area as a `CODE` chunk at
   `0x467e0000`, which the platform's start-up loader copies there.

The toggle is one byte of RAM in the settings block (`0x405cd8ae`), which the
firmware already saves to the +Drive and restores; the mod writes it only
through the stock settings writer.
"""

from __future__ import annotations

import json
import pathlib

from . import RAM, Extent, ModError, Result, platform, specs

ID = "reloadconfirm"
NAME = "Reload confirm"
SUMMARY = "An opt-in YES/NO prompt before FUNC + NO reloads the pattern (SETTINGS > PERSONALIZE)."
DEVICE = 0x15                      # Digitone II
SECTION = 3                        # MAIN OS
BASE = 0x40000400
SPEC = json.loads((pathlib.Path(__file__).with_name("reloadconfirm_code.json")).read_text())
SPECS = specs.load(__file__, "reloadconfirm")      # one per OS version (issue #382); SPEC is 1.11's
CODE_VA = SPEC["code"]["va"]
BLOB = bytes.fromhex(SPEC["code"]["blob"])
FLAG = 0x405CD8AE                  # the toggle, in the settings block's unaddressed tail


def extents(firmware=None, os: str | None = None) -> list[Extent]:
    os = os or specs.of_firmware(firmware)
    spec = specs.pick(SPECS, os, ID)
    blob = bytes.fromhex(spec["code"]["blob"])
    return ([Extent(SECTION, e["va"] - BASE, len(e["new"]) // 2, e["what"]) for e in spec["edits"]]
            + platform.extents(16 + len(blob), os))


def apply(firmware) -> Result:
    section = firmware.container.find(SECTION)
    if section is None:
        raise ModError("image has no MAIN OS section")
    original, others = platform.split(section.unpack())
    os = specs.of_main_os(original)
    spec = specs.pick(SPECS, os, ID)
    content = specs.apply_edits(original, spec, os)
    code_va, blob = spec["code"]["va"], bytes.fromhex(spec["code"]["blob"])
    chunk = platform.area.CodeChunk(code_va, blob).pack()
    content = platform.join(bytes(content), others + [(platform.area.CODE, chunk)])

    return Result(payloads={SECTION: bytes(content)}, extents=extents(os=os),
                  notes=["SETTINGS > PERSONALIZE > RELOAD CONFIRM: off by default",
                         "on: FUNC + NO asks before reloading the pattern",
                         f"{len(spec['edits'])} hooks in section 3, and a {len(blob):,} B CODE "
                         f"chunk at 0x{code_va:08x} in the platform's area"])


def ram(os: str = "1.11") -> list[Extent]:
    """The RAM the code uses: its own chunk (with its prompt's vtable copy), and
    the toggle's byte in the settings block (it moves with the block on 1.12)."""
    spec = specs.pick(SPECS, os, ID)
    flag = spec.get("flag", FLAG)
    return [Extent(RAM, spec["code"]["va"], len(spec["code"]["blob"]) // 2,
                   "the mod's code and its prompt's vtable (a platform CODE chunk)"),
            Extent(RAM, flag, 1, "the RELOAD CONFIRM toggle, in the settings block's tail")]

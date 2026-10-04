"""P-locks for the arpeggiator: MODE, SPEED, RANGE and N.LEN per trig.

Stock Digitone II firmware keeps the ARPEGGIATOR settings on the sound only.
With this mod, holding a trig in grid recording and turning a value in the
ARPEGGIATOR menu locks it to that trig, like any parameter: the value shows
inverted while the trig is held, the trig blinks, the lock is saved with the
pattern, and trigless lock trigs change a running arp. **Passed on the
instrument on 2026-09-19.** `docs/ideas-backlog.md` §18 carries the history,
and `scripts/build_arp_plocks.py` the design, assembly and evidence.

A MODE lock stops where the menu stops: its ceiling is read from setMode's own
clamp (the immediate at `0x4004bf01`), 4 (CYCL) on stock and 6 (RAND) with
`arpmodes`. That read was added on 2026-09-26, after the hardware pass. It
shifts the UI cave by 10 bytes, and it is checked in the emulator
(`scripts/emu_arp_modes.py`, `scripts/emu_arp_plocks.py`), not yet on the
instrument.

**Fixed 2026-10-05: a lock trig with arp locks can be removed again.** On the
instrument (owner, 2026-10-05), FUNC + TRIG on a yellow lock trig carrying arp locks
turned it red and blinking instead of removing it, until a reboot. The stock clear
of a step's locks (`0x4003d14e`) recounts the step's lock count (table `+0x56f0`)
only when it clears a stock value itself; `clear_hook` cleared the arp locks before
it but never recounted, and the trig tidy-up (`0x400558f8`) frees a step only when
that count is 0. `clear_hook` now runs the stock recount (`0x4003ce3c`) whenever it
clears an arp lock. Measured in the emulator (the Rust core, `panel_drive`): the count
stayed 1 after FUNC + TRIG before, and is 0 after, as with a stock p-lock (the
control). `scripts/emu_arp_plocks.py` checks it (45/45; the old build fails the new
check). A quick tap leaving a locked lock trig in place is stock behaviour.

## How it applies

The code is assembled ahead of time (`scripts/gen_arpplocks_code.py` ->
`arpplocks_code.json`), so the bytes applied are exactly those tested:

1. every guard and every edit's stock bytes are checked -- an image that
   differs is refused;
2. the edits are written: four code caves, the hooks and a few byte patches.

Since 2026-10-02 its code is a platform `CODE` chunk (`dnfw.mods.platform`): 1,984
bytes assembled to run at `0x467c8000`, copied there by the platform's start-up
loader. Until then it sat in seven code caves of the image, two of them shared with
usbprobe and fxmod, so it combined with neither. The hooks and patches in MAIN OS
are the same, pointing at the chunk. RAM: 16 shadow sounds from `0x467c0000`, the
note list at `0x467c4900`, and the code from `0x467c8000`.
"""

from __future__ import annotations

import json
import pathlib

from . import RAM, Extent, ModError, Result, platform

ID = "arpplocks"
NAME = "Arpeggiator p-locks"
SUMMARY = "MODE, SPEED, RANGE and N.LEN of the arpeggiator lockable per trig."
DEVICE = 0x15                      # Digitone II
SECTION = 3                        # MAIN OS
BASE = 0x40000400
SPEC = json.loads((pathlib.Path(__file__).with_name("arpplocks_code.json")).read_text())


CODE_VA = SPEC["code"]["va"]
BLOB = bytes.fromhex(SPEC["code"]["blob"])


def extents(firmware=None) -> list[Extent]:
    return ([Extent(SECTION, e["va"] - BASE, len(e["new"]) // 2, e["what"]) for e in SPEC["edits"]]
            + platform.extents(16 + len(BLOB)))


def apply(firmware) -> Result:
    section = firmware.container.find(SECTION)
    if section is None:
        raise ModError("image has no MAIN OS section")
    original, others = platform.split(section.unpack())
    # Longer is fine: data appended after the stock end (lfowaves, bootscreen)
    # moves no address this mod writes or reads.
    if len(original) < SPEC["stock_length"]:
        raise ModError(f"MAIN OS is {len(original):,} B, shorter than "
                       f"{SPEC['stock_length']:,}: not Digitone II 1.11")
    for g in SPEC["guards"]:
        want = bytes.fromhex(g["bytes"])
        if original[g["va"] - BASE:g["va"] - BASE + len(want)] != want:
            raise ModError(f"0x{g['va']:08x} is not stock; this mod is for unmodified "
                           "Digitone II 1.11, or another mod already wrote there")
    for e in SPEC["edits"]:
        want = bytes.fromhex(e["stock"])
        if original[e["va"] - BASE:e["va"] - BASE + len(want)] != want:
            raise ModError(f"0x{e['va']:08x} is not stock; this mod is for unmodified "
                           "Digitone II 1.11, or another mod already wrote there")

    content = bytearray(original)
    for e in SPEC["edits"]:
        new = bytes.fromhex(e["new"])
        content[e["va"] - BASE:e["va"] - BASE + len(new)] = new
    chunk = platform.area.CodeChunk(CODE_VA, BLOB).pack()
    content = platform.join(bytes(content), others + [(platform.area.CODE, chunk)])

    return Result(payloads={SECTION: bytes(content)}, extents=extents(),
                  notes=["hold a trig in grid recording, turn MODE / SPEED / RANGE / N.LEN "
                         "in the ARPEGGIATOR menu: a p-lock",
                         f"{len(SPEC['edits'])} edits in section 3, and a {len(BLOB):,} B CODE "
                         f"chunk at 0x{CODE_VA:08x} in the platform's area"])


def ram() -> list[Extent]:
    """The RAM above BSS the code uses (`SPEC["ram"]`), for the platform's comparison."""
    return ([Extent(RAM, r["va"], r["bytes"], r["what"]) for r in SPEC.get("ram", [])]
            + [Extent(RAM, CODE_VA, len(BLOB), "the mod's code (a platform CODE chunk)")])


# Bytes that only look like RAM above BSS (`dnfw.mods.ramcheck`): `lea 0x40054690,%a4 ;
# rts` (49 f9 40 05 46 90 4e 75) straddles into 0x46904e75. It was at 0x4028d214 in its
# cave; in the chunk it is at 0x467c8794.
NOT_RAM = (0x467C8794,)

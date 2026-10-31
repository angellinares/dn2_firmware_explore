"""Arp offsets in scale: the arpeggiator's step offsets move by degrees of the track's scale.

Stock 1.11 adds each arp step's OFFSET in semitones, after the keyboard's SCALE
and ROOT have chosen the held notes, so an offset leaves the scale: in C major,
E plus 2 plays F#. This mod adds **SETTINGS > PERSONALIZE > ARP OFS IN SCALE**.
Off, the default and what a fresh instrument reads, the arp is stock. On, a
step's offset counts degrees of the track's KEYBOARD SETUP scale from its root:
in C major, E plus 2 plays G, and plus 7 is the octave.

- An offset of 0 plays the held note unchanged, even one outside the scale.
- A held note outside the scale is moved to the nearest scale note first (the
  lower one on a tie), then by degrees.
- The arp's octave (RANGE) still adds 12 semitones.
- SCALE CHROMATIC and MODE CHORD MEMORY keep stock's offsets in semitones.
- SCALE and ROOT are read per track or per pattern, as KEYBOARD SETUP's
  CONFIG says, from the pattern that is playing.

With the switch on, a step can also be marked to move in semitones. In the
ARPEGGIATOR menu, `[UP]` on an active step marks it and the step graph draws a
plus for it; `[DOWN]` removes the mark, and `[DOWN]` again mutes the step, as
stock. The marks belong to the sound: it saves them in its stored bytes
242..243, which stock zeroes and never reads, and keeps them in its value
slot 100, which no parameter uses. The menu's rotate, copy, paste, clear and
undo move them with the steps. With the switch off, every step moves in
semitones and the menu is stock's.

`scripts/build_arpscale.py` carries the reading of the arp step's tail and the
toggle's byte, `scripts/build_scale_degrees.py` where the playing pattern keeps a
track's scale and root and the move by degrees, and
`scripts/build_personalize_toggle.py` the PERSONALIZE item, which reloadconfirm
shares. `scripts/emu_arpscale.py` is the emulator check: stock and this mod playing a chord through the arp with the same
offsets, against the rule computed from the firmware's scale tables.

## How it applies

The code is assembled ahead of time (`scripts/gen_arpscale_code.py` ->
`arpscale_code.json`):

1. every guard and every edit's stock bytes are checked, and an image that
   differs is refused;
2. the hooks are written, each a `jmp` into the chunk or a stock `jsr` turned
   into a call of it: the arp step's tail (`0x4002a390`), PERSONALIZE's
   constructor after its last stock item (`0x40098630`), the stored sound's
   load and save at the step mask (`0x400dd5a0`, `0x400dd8c8`), the step
   graph (`0x40018b4a`), and seven of the ARPEGGIATOR menu's calls: the step's
   on/off, the rotate's mask, copy, clear, paste and the two calls of undo;
3. the routines are added to the platform's area as a `CODE` chunk at
   `0x467a8000`, which the platform's start-up loader copies there.

The toggle is one byte of RAM in the settings block (`0x405cd8af`, the byte after
reloadconfirm's), which the firmware already saves to the +Drive and restores;
the mod writes it only through the stock settings writer. The menu's copy and
undo record keep their marks in two words after the code.
"""

from __future__ import annotations

import json
import pathlib

from . import RAM, Extent, ModError, Result, platform

ID = "arpscale"
NAME = "Arp offsets in scale"
SUMMARY = ("The arp's step offsets move by degrees of the track's scale and root, not semitones "
           "(SETTINGS > PERSONALIZE > ARP OFS IN SCALE).")
DEVICE = 0x15                      # Digitone II
SECTION = 3                        # MAIN OS
BASE = 0x40000400
SPEC = json.loads((pathlib.Path(__file__).with_name("arpscale_code.json")).read_text())
CODE_VA = SPEC["code"]["va"]
BLOB = bytes.fromhex(SPEC["code"]["blob"])
FLAG = 0x405CD8AF                  # the toggle, in the settings block's unaddressed tail


def extents(firmware=None) -> list[Extent]:
    return ([Extent(SECTION, e["va"] - BASE, len(e["new"]) // 2, e["what"]) for e in SPEC["edits"]]
            + platform.extents(16 + len(BLOB)))


def apply(firmware) -> Result:
    section = firmware.container.find(SECTION)
    if section is None:
        raise ModError("image has no MAIN OS section")
    original, others = platform.split(section.unpack())
    if len(original) < SPEC["stock_length"]:
        raise ModError(f"MAIN OS is {len(original):,} B, shorter than "
                       f"{SPEC['stock_length']:,}: not Digitone II 1.11")
    for g in SPEC["guards"]:
        want = bytes.fromhex(g["bytes"])
        if original[g["va"] - BASE:g["va"] - BASE + len(want)] != want:
            raise ModError(f"0x{g['va']:08x} is not stock; this mod is for unmodified "
                           "Digitone II 1.11")
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
                  notes=["SETTINGS > PERSONALIZE > ARP OFS IN SCALE: off by default",
                         "on: arp step offsets count degrees of the track's scale from its root",
                         "on: [UP] on an active arp step marks it to move in semitones",
                         f"{len(SPEC['edits'])} edits in section 3, and a {len(BLOB):,} B CODE "
                         f"chunk at 0x{CODE_VA:08x} in the platform's area"])


def ram() -> list[Extent]:
    """The RAM the code uses: its own chunk, and the toggle's byte in the settings block."""
    return [Extent(RAM, CODE_VA, len(BLOB), "the mod's code (a platform CODE chunk)"),
            Extent(RAM, FLAG, 1, "the ARP OFS IN SCALE toggle, in the settings block's tail")]

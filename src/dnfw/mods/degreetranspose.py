"""Degree transpose: move the active track by degrees of its scale, as stock moves it by semitones.

Stock 1.11 transposes the active track in semitones with [FUNC] + [+]/[-] or
[TRK] + [+]/[-]. This mod adds the same move in degrees of the track's KEYBOARD
SETUP scale and root:

- [KEYBOARD] + [FUNC] + [+]/[-], or [KEYBOARD] + [TRK] + [+]/[-]: the active
  track, one degree a press;
- [KEYBOARD] + [TRK] + [FUNC] + [+]/[-]: stock's octave transpose of the track,
  changing the semitone amount by 12, as without [KEYBOARD].

The amount ranges over -7..+7 degrees, which reaches every note of the longest
scale (8 notes) up or down; anything further is an octave.

In C major, C E G up 1 degree plays D F A. A note outside the scale first moves
to the nearest note in it (the lower one on a tie), as ARP OFS IN SCALE does. A
track with no scale (CHROMATIC, or MODE CHORD MEMORY) moves by semitones. Stock's
transposes are added after. MIDI tracks move the same way, in the MIDI task where
stock adds its transposes to their notes; a layered copy (TRACK WILL TRIGGER)
moves by its own track's degrees, as stock moves it by its own track's transpose.

As with stock's transpose, the degree amount blinks while the keys are held and
takes effect when they are released. It shows where stock shows the track's
transpose, in the track box's header, marked with a tick ("+2'"). A box with both
degrees and semitones alternates between them. An octave changes only the semitone
amount, shown without a tick.

The recorded notes are never rewritten: the move is made as each note plays, so
0 degrees plays them as recorded. The amount belongs to the track in the pattern,
as stock's transpose does: each track of each pattern of each project has its
own, saved, loaded, copied and cleared with it. It sits in bits 2..5 of the
track's byte `+1187` in RAM (stored `+1176`), which stock's load and save drop.
So a project saved before this mod opens with no degrees, and stock firmware
plays a pattern this mod saved as recorded, and clears its degrees when it saves
that pattern.

`scripts/build_degreetranspose.py` carries the reading of the firmware (where a
note gets its pitch, where [+] and [-] are handled, where the amount lives), and
`scripts/emu_degreetranspose.py` the emulator check.

## How it applies

The code is assembled ahead of time (`scripts/gen_degreetranspose_code.py` ->
`degreetranspose_code.json`):

1. every guard and every edit's stock bytes are checked, and an image that
   differs is refused;
2. the eleven hooks are written, each a `jmp` into the chunk: the note's range
   check in the frame ISR (`0x400269a4`); a MIDI track's note-on and a live
   key's release in the MIDI task (`0x4012b1b0`, `0x4012b37c`); in the main
   screen's key handler, the [+]/[-] case (`0x4005fb76`) and the head, for
   releases (`0x4005ed2c`); the main screen's drawing of the track's transpose
   (`0x4005ca66`); its blink timer (`0x4005beb6`); the getter and setter of the
   stock setting that shares the track's byte (`0x40050454`, `0x4005049c`); the
   track default (`0x400e75a4`); and the reset of the track's semitone transpose
   (`0x400e7408`). Two masks in stock's load and save are widened in place
   (`0x400de1ec`, `0x400de28c`);
3. the routines are added to the platform's area as a `CODE` chunk at
   `0x467b0000`, which the platform's start-up loader copies there.
"""

from __future__ import annotations

import json
import pathlib

from . import RAM, Extent, ModError, Result, platform

ID = "degreetranspose"
NAME = "Degree transpose"
SUMMARY = ("Transpose the active track by degrees of its scale, not semitones "
           "(stock's [FUNC] or [TRK]+[+]/[-], with [KEYBOARD] added).")
DEVICE = 0x15                      # Digitone II
SECTION = 3                        # MAIN OS
BASE = 0x40000400
SPEC = json.loads((pathlib.Path(__file__).with_name("degreetranspose_code.json")).read_text())
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
                  notes=["[KEYBOARD]+[FUNC] or [TRK]+[+]/[-]: the active track, in degrees of its scale; "
                         "applied on release",
                         f"{len(SPEC['edits'])} edits in section 3, and a {len(BLOB):,} B CODE "
                         f"chunk at 0x{CODE_VA:08x} in the platform's area"])


def ram() -> list[Extent]:
    """The RAM the code uses: its own chunk. The amounts live in the pattern's own data."""
    return [Extent(RAM, CODE_VA, len(BLOB), "the mod's code (a platform CODE chunk)")]

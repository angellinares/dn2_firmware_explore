"""Track layering onto MIDI tracks: an audio track's layered notes go out over MIDI.

TRACK WILL TRIGGER lets a track trigger others. On stock Digitone II firmware a
MIDI destination stays silent: layering happens in the frame ISR, which copies
the note onto the destination as a synth note, and a MIDI track has no voice to
play it. This mod sends those notes out on the MIDI track's channel. **Passed on
the instrument on 2026-10-02** as `layer-midi6`: sequenced notes, chords,
retrigs and probability; INF holds until the sequencer stops; live keys with no
hanging notes; two audio sources into one MIDI track, and one source into
several MIDI tracks. `docs/layer-midi.md` carries the reading and the bench
history, and `scripts/build_layer_midi.py` the assembly and evidence.

## How it works

Two hooks in the frame ISR, one code cave:

1. at the head of the per-note body (`0x40026980`), every note the ISR voices
   passes once: a layered copy's note (record `+56` bit 17) on a MIDI track
   becomes a MIDI note-on on the batch the ISR already hands the MIDI task;
2. at the head of the per-note release body (`0x40026d32`), a layered copy's
   release on a MIDI track becomes a MIDI note-off, which the MIDI task matches
   to the note on whichever channel it is active and sends.

The note, velocity and length are the ISR's own note entry's. A record is taken
from the MIDI pool only while two are free: the stock allocator does not check
for an empty pool, and an empty pop corrupts low memory for good.

## How it applies

The code is assembled ahead of time (`scripts/gen_layermidi_code.py` ->
`layermidi_code.json`), so the browser applies exactly these bytes:

1. every guard (whole instructions and the code the hooks rely on) and every
   edit's stock bytes are checked -- an image that differs is refused;
2. the edits are written: two hooks and the code cave.

It writes only inside section 3, changes no length, and appends nothing. It
uses midiarp's cave on purpose: midiarp's voice-trigger hook also catches
layered copies on MIDI tracks, reading the wrong note fields, so the two must
not share an image.
"""

from __future__ import annotations

import json
import pathlib

from . import Extent, ModError, Result

ID = "layermidi"
NAME = "Layering onto MIDI tracks"
SUMMARY = "TRACK WILL TRIGGER onto a MIDI track sends the layered notes out over MIDI."
DEVICE = 0x15                      # Digitone II
SECTION = 3                        # MAIN OS
BASE = 0x40000400
SPEC = json.loads((pathlib.Path(__file__).with_name("layermidi_code.json")).read_text())


def extents(firmware=None) -> list[Extent]:
    return [Extent(SECTION, e["va"] - BASE, len(e["new"]) // 2, e["what"]) for e in SPEC["edits"]]


def apply(firmware) -> Result:
    section = firmware.container.find(SECTION)
    if section is None:
        raise ModError("image has no MAIN OS section")
    original = section.unpack()
    # Longer is fine: data appended after the stock end (lfowaves, bootscreen)
    # moves no address this mod writes or reads. The guards identify the build.
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

    return Result(payloads={SECTION: bytes(content)}, extents=extents(),
                  notes=["TRACK WILL TRIGGER onto a MIDI track plays it over MIDI",
                         "note-on as the layered note plays, note-off as it is released",
                         f"{len(SPEC['edits'])} edits in section 3, nothing appended"])

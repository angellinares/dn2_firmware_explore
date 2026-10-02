"""The arpeggiator on MIDI tracks: a MIDI track with the arp on arpeggiates over MIDI.

Stock Digitone II firmware hides the ARPEGGIATOR menu on MIDI tracks, and the
arp itself lives only on the synth voice path, so a MIDI track's notes never
meet it. This mod opens the menu, sends an arp-enabled MIDI track's notes
through the ISR's arpeggiator, and turns each note it plays into a MIDI record
on the batch the ISR already hands the MIDI task. **Passed on the instrument on
2026-09-17** as `arp-midi-play4`: offsets, velocity, SPD, RNG and N.LEN (1/32 to
1/4 within a millisecond), no stuck notes. `docs/ideas-backlog.md` §10 carries the
whole history, and `scripts/build_arp_midi_play.py` the assembly and evidence.

Two fixes and a move, 2026-10-03, reported by an external contributor (PR #176)
and checked here in the emulator (`scripts/emu_midiarp_layered.py`), **not yet on
the instrument**:

- **Layered copies.** TRACK WILL TRIGGER copies a note record onto the destination
  track in the frame ISR (`0x400255b4`, flag `+56` bit 17), and the copy of a
  sequencer trig keeps its notes in a list, not in the inline entry the hook read:
  random notes and lengths. Now a copy on a MIDI track is played only when its
  own track's arp is on and is playing it (the ISR fills the inline entry for an
  arp step, flag bit 19); otherwise it goes to the stock trigger, as with the arp
  off, which does nothing on a MIDI track. The hook reads the note from the ISR's
  entry (`%a2` at the call), which is the inline entry for an arp step and the
  list's entry otherwise.
- **The MIDI record pool.** `0x4012a408` pops its free list with no empty check;
  an empty pop clears low memory. The hook now takes a record only while four are
  free (the live MIDI sender allocates unguarded, so some are left to it) and
  drops the note otherwise.
- **The platform.** Its routines are a `CODE` chunk loaded at `0x467d0000`, not a
  cave that overlapped usbprobe's, so it combines with usbprobe.

## How it applies

The code is assembled ahead of time (`scripts/gen_midiarp_code.py` ->
`midiarp_code.json`), so the browser applies exactly these bytes:

1. every guard (whole instructions and the code the hooks rely on) and every
   edit's stock bytes are checked -- an image that differs is refused;
2. the edits are written: two menu bytes and five hooks, pointing at the chunk;
3. the routines are added to the platform's area (`dnfw.mods.platform`) as a
   592 B `CODE` chunk at `0x467d0000`, which the platform's start-up loader copies
   there, and their N.LEN lookup is rebuilt from this image's own length tables.

It writes only inside section 3 and changes no stock length; the appended area is
the platform's, shared with the other mods on it.
"""

from __future__ import annotations

import json
import pathlib
import struct

from . import RAM, Extent, ModError, Result, platform

ID = "midiarp"
NAME = "Arpeggiator on MIDI tracks"
SUMMARY = "The arpeggiator on MIDI tracks: the menu opens, and the arp plays out over MIDI."
DEVICE = 0x15                      # Digitone II
SECTION = 3                        # MAIN OS
BASE = 0x40000400
SPEC = json.loads((pathlib.Path(__file__).with_name("midiarp_code.json")).read_text())
LUT_BYTES = 128
CODE_VA = SPEC["code"]["va"]
BLOB = bytes.fromhex(SPEC["code"]["blob"])


def extents(firmware=None) -> list[Extent]:
    return ([Extent(SECTION, e["va"] - BASE, len(e["new"]) // 2, e["what"]) for e in SPEC["edits"]]
            + platform.extents(16 + len(BLOB)))


def nlen_lut(content: bytes) -> bytes:
    """For each N.LEN, the trig length index nearest in duration (ties shorter);
    INF becomes 126, the longest finite trig length. The MIDI task times notes
    only through the trig table."""
    def table(va: int) -> list[int]:
        at = va - BASE
        return list(struct.unpack(">128i", content[at:at + 512]))
    trig = table(SPEC["trig_lengths_va"])[:127]
    return bytes(126 if want < 0 else
                 min(range(127), key=lambda i: (abs(trig[i] - want), trig[i]))
                 for want in table(SPEC["arp_lengths_va"]))


def apply(firmware) -> Result:
    section = firmware.container.find(SECTION)
    if section is None:
        raise ModError("image has no MAIN OS section")
    original, others = platform.split(section.unpack())
    # Longer is fine: data appended after the stock end (lfowaves, bootscreen)
    # moves no address this mod writes or reads. The guards below are what
    # identify the build.
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
    blob = bytearray(BLOB)
    lut = SPEC["lut_va"] - CODE_VA
    blob[lut:lut + LUT_BYTES] = nlen_lut(original)
    chunk = platform.area.CodeChunk(CODE_VA, bytes(blob)).pack()
    content = platform.join(bytes(content), others + [(platform.area.CODE, chunk)])

    return Result(payloads={SECTION: bytes(content)}, extents=extents(),
                  notes=["ARPEGGIATOR menu opens on MIDI tracks",
                         "an arp-enabled MIDI track plays its arp out over MIDI",
                         f"{len(SPEC['edits'])} edits in section 3, and a {len(BLOB):,} B CODE "
                         f"chunk at 0x{CODE_VA:08x} in the platform's area"])


def ram() -> list[Extent]:
    """The RAM above BSS the code uses: only its own code, copied there by the loader."""
    return [Extent(RAM, CODE_VA, len(BLOB), "the mod's code (a platform CODE chunk)")]

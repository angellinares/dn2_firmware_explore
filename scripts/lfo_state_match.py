"""The LFO state records over song 1, matched against every sound's LFO settings.

    python scripts/lfo_state_match.py IMAGE.bin

The owner's question, 2026-10-10 (docs/song-rows-report.md): do the records lying over
song 1 match the LFO settings of a sound in the same file?

A state record is 40 bytes (stock evaluator A, measured in the emulator): phase, output,
two random words, fade level (`3f ff ff ff` once faded in), a word, DEST as a mirror slot
(+24), the output after DEP (+28), a phase copy, flags. So a record names its destination,
and the place of a record in the lattice names which LFO it is. A stored sound keeps
DEST as a p-lock id; stock's map at `0x401fd0b0` turns it into the slot. LFO4 (the mod)
stores the slot itself, at id 16.

Prints the records that name a destination, then every stored LFO whose destination is
one of them, then how the destinations fall on a period of 3 (stock: three LFOs a track)
and of 4 (LFO4 builds).
"""

from __future__ import annotations

import collections
import pathlib
import struct
import sys

ORIGIN, RECORD = 0xC3EE18, 40                   # image offset of the lattice; record size
KITS, KIT, SOUND, FIRST, VALUES = 0xAE0200, 10752, 359, 0x3C, 0x1C
DEST = 3                                        # SPD MULT FADE DEST WAVE SPH MODE DEP
NAMES = ("SPD", "MULT", "FADE", "DEST", "WAVE", "SPH", "MODE", "DEP")
# stock 1.11's id -> slot map (`0x401fd0b0`, 107 entries)
ID_TO_SLOT = (0, 1, 9, 17, 0, 2, 10, 18, 0, 3, 11, 19, 0, 4, 12, 20, 0, 5, 13, 21, 0, 6, 14, 22, 0, 7, 15, 23,
              0, 8, 16, 24, 0) + tuple(range(25, 65)) + (66, 67, 68, 69, 70, 71, 72, 73, 74, 79, 76, 77, 75, 80,
              81, 82, 83, 84, 85, 88, 86, 87, 89, 90, 91, 92, 94, 93, 95, 96, 97, 98, 78, 99)


def records(image: bytes, first=-12, last=70):
    for i in range(first, last):
        yield i, struct.unpack_from(">10i", image, ORIGIN + RECORD * i)


def stored_lfo(image: bytes, kit: int, track: int, lfo: int) -> tuple | None:
    """The eight stored values of LFO 1..4 of a sound, or None when the sound is not there."""
    at = KITS + KIT * kit + FIRST + SOUND * track
    if image[at:at + 4] != bytes.fromhex("beefbace"):
        return None
    ids = [4 * p + lfo if lfo < 4 else 4 * (p + 1) for p in range(8)]
    return tuple(struct.unpack_from(">H", image, at + VALUES + 2 * i)[0] for i in ids)


def slot_of(lfo: int, values: tuple) -> int:
    d = values[DEST] >> 8
    return d if lfo == 4 else (ID_TO_SLOT[d] if d < len(ID_TO_SLOT) else -1)


def main(argv=None) -> int:
    image = pathlib.Path((argv or sys.argv[1:])[0]).read_bytes()
    named = [(i, r) for i, r in records(image) if 0 < r[6] <= 100]
    print("records naming a destination:")
    for i, r in named:
        print(f"  record {i:3d}: slot {r[6]:3d}, output after DEP {r[7]:6d}, fade {r[4] & 0xFFFFFFFF:08x}")
    slots = {r[6] for _, r in named}
    print("stored LFOs with one of those destinations:")
    for kit in range(128):
        for track in range(16):
            for lfo in (1, 2, 3, 4):
                v = stored_lfo(image, kit, track, lfo)
                if v and slot_of(lfo, v) in slots:
                    print(f"  {'ABCDEFGH'[kit // 16]}{kit % 16 + 1:02d} track {track + 1:2d} LFO{lfo}: slot {slot_of(lfo, v):3d}  "
                          + " ".join(f"{n} {x:04x}" for n, x in zip(NAMES, v)))
    for period in (3, 4):
        by = collections.defaultdict(collections.Counter)
        for i, r in named:
            by[i % period][r[6]] += 1
        print(f"period {period}: " + "; ".join(f"position {k}: {dict(by[k])}" for k in sorted(by)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

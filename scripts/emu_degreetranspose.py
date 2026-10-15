"""degreetranspose in the emulator: a track moved by degrees through the keys, stock alongside.

    python scripts/emu_degreetranspose.py BUILD.syx [--stock STOCK.syx] [--case NAME ...]

Plays the sequencer headless (`scripts/emu_seqplay.py` and digikit's `panel_drive`,
as `scripts/emu_arpscale.py` does): four trigs on track 1, entered as C4 E4 F#4 C#5
(`emu_seqplay.py --note 5:4 --note 9:6 --note 13:12`), or a chord held live on the
KEYBOARD page. Before PLAY each case presses the mod's keys on the panel
([KEYBOARD] + [FUNC] or [TRK], then [+] or [-]), and writes SCALE, ROOT and the
per-track switch into the playback copy of the pattern through `panel_drive`'s
`poke` step, as `emu_arpscale.py` does.

Stock gets the same writes and the same stock keys, without the mod's: it is the
control, and its notes are the recorded notes plus stock's transposes. BUILD's
notes must equal the rule computed in Python (`emu_arpscale.reference`, from the
firmware's own scale tables) for the amount the case sets, plus the same
transposes, and the amount, read with `peek` from the playing pattern (track 1's
byte `+1187`), must be what the keys set. The screen is captured after the keys
are released: the track box's header must show the text the case names, drawn
here from the firmware's own small font where and as stock draws its transpose.

The four `octave-*` cases compare [KEYBOARD] + [TRK] or [PTN] + [FUNC] + [+]/[-]
with stock's octave gestures without [KEYBOARD]. They check exact octave pitches,
including accidentals at zero degrees, and the octave combined with a degree
amount. Peeks before the gesture, while held and after release check that the
semitone change waits for the release and that the degree amount is unchanged.

More checks, on BUILD alone except where stock is named:

- `pending`: while [KEYBOARD] + [FUNC] are held after two [+], the track's amount
  still reads 0 and its box blinks between empty and "+2'"; released, it reads 2
  and the box shows "+2'".
- `alternation`: a stock +1 semitone and +2 degrees on the same track; over five
  seconds its box shows both "+1" and "+2'", and nothing else.
- `scope`: +2 degrees on track 1 in A1, then A2 selected and -1 set there: A2's
  track 1 reads -1 and A1's still +2, and the box shows "-1'"; back on A1, both
  are unchanged and the box shows "+2'".
- `clear`: +1 semitone on track 1 and on the pattern, and +2 degrees; after
  clearing the pattern ([FUNC] + [PLAY]) and then the track (in GRID RECORDING),
  the track's semitone and its degrees are kept, and the pattern's semitone is
  reset, as on stock, which runs alongside as the control. Each clear must run
  the track default (`0x400e75a4`), so a clear that did nothing fails.
- `ptn-stock`: the same [KEYBOARD] + [PTN] + [+] pressed on stock and on BUILD:
  BUILD plays the same notes, sets the same semitone transposes, leaves the degrees
  at 0, and shows the same screen after the keys are released.
- `reload`: +2 degrees, the pattern saved ([FUNC] + [YES]), the amount changed,
  the pattern reloaded ([FUNC] + [NO]): the amount reads +2 again. The stored
  pattern the reload reads, captured as stock's loads of its tracks (`0x400ddf8a`)
  start, holds +2 in track 1's `+1176` and 0 in the other tracks'. The temporary
  save is stock's pattern save (`0x400de7a8`), which a project's save runs for
  each pattern, and the reload the pattern load a project's load runs.
- `stock-load`: on stock, the pattern saved ([FUNC] + [YES]) with +2 degrees and
  stock's own setting 3 (bits 0..1) in track 1's `+1176`, written into the save's
  buffer between stock's conversion (`0x400de7a8`) and its write to the card
  (`0x4012eb6c`), then reloaded ([FUNC] + [NO]), which reads the card: the card
  and stock's load get the byte with the degrees, and the playing pattern's byte,
  track 1's KEYBOARD SETUP and the notes are those of the same run with the stock
  bits alone. After PLAY, stock's next save writes `+1176` as the stock bits alone.
- `midi`: track 1 made a MIDI track on channel 1 (the masks and channel the
  firmware keeps for a track with the MIDI machine, written with `poke`), stock's
  +1 semitone, then +2 degrees: the MIDI note-ons, captured at the MIDI sender
  (`0x4012a7c6`), are stock's moved by +2 degrees, and each has its note-off.
  Stock, with the same masks and +1, is the control.
- `midi-live`: the same MIDI track, +2 degrees, a C E G chord held on the
  KEYBOARD page: E G B on and the same three off.
- `layered`: track 1 layered onto track 2 (TRACK WILL TRIGGER, the kit's mask at
  `+0x5ce0`) and +2 degrees on track 1 only: track 1 plays the moved notes, and
  its copies on track 2 play stock's, as stock moves a copy by its own track's
  transpose.
- `waverider`: STOCK and BUILD each with the waverider mod applied by
  `dnfw mods apply` (which needs numpy, as Waverider does); track 1 made a
  Waverider track in MACHINE SEL ([FUNC] + [SYN], WAVERIDER, the fifth machine).
  With +2 degrees on BUILD, its notes are the control's moved by the rule, and
  on both the sound's machine type (`+222`) reads 5.

Needs what `scripts/emu_seqplay.py` needs: a `panel_drive` that delivers the forced
interrupts and takes a literal `--capture` length (digikit #65 and #66; the
`feat/seqplay-chords` branch of angellinares/digikit has both), found through
`PANEL_DRIVE`. Its `poke` and `peek` steps write and read RAM, and `frame` saves
the screen.
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import struct
import subprocess
import sys
import tempfile
from dataclasses import dataclass

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "scripts")]

import build_arpscale as bs  # noqa: E402
import build_degreetranspose as bd  # noqa: E402
import build_scale_degrees as sd  # noqa: E402
import emu_arpscale as ea  # noqa: E402
import emu_seqplay as sp  # noqa: E402
from dnfw import seqframes as SF  # noqa: E402
from dnfw.cli.files import read_image  # noqa: E402
from dnfw.firmware.load import load  # noqa: E402

FUNC, PTN, TRK, KEYBOARD, PLUS, MINUS = bd.FUNC, bd.PTN, bd.TRK, bd.KEYBOARD, bd.PLUS, bd.MINUS
YES = 10                        # panel code of [YES]
TRIGS = [1, 5, 9, 13]
NOTES = {5: 4, 9: 6, 13: 12}    # C4 (a fresh trig's), E4, F#4 and C#5: twelve units of NOTE land on 73
LIVE_KEYS = (33, 35, 37)        # TRIG 9, 11, 13 on the KEYBOARD page: C4 E4 G4 in C major
LIVE_HOLD = "100M"
PATTERN_TRANSPOSE = 32          # the header's pattern transpose, in semitones
STOCK_TRANSPOSES = 0x80005380   # pattern, then the 16 tracks, as signed semitone bytes
STOCK_SPAN = 17
PATTERN_STRIDE = 0x1DE6E        # the project's patterns in RAM: A2 follows A1
TRACK_LOAD = 0x400DDF8A         # (track in RAM, stored track), for each track of a pattern's load
TRACKS = 16
STORED_FLAGS = 1176             # the track's byte, stored
DEGREES_BITS = 2 << bd.TRACK_SHIFT   # +2 degrees in that byte
STOCK_BITS = 0x03               # ... and stock's own setting 3 (bits 0..1); bit 7, a flag, silences the track
# Track 1 as a MIDI track on channel 1, as the MIDI machine leaves it: bit 0 of the
# kit's MIDI-track mask (+0x5cda) and of the copies the keys and ISR (0x8000537c) and
# the MIDI task (0x4461727c) read, and the MIDI task's flag for the track and channel.
KIT_MIDI_MASK, KIT_LAYERS = 0x5CDA, 0x5CE0     # u16s: MIDI tracks; track 1's layer destinations
MIDI_MASK_COPIES = (0x8000537C, 0x4461727C)
MIDI_FLAGS = 0x446163C4 + 4 * 908               # the MIDI task's flags for track 1: bit 0 MIDI
MIDI_CHANNEL = 0x4461647A                       # ... and its channel, 0 for channel 1
MIDI_SEND = 0x4012A7C6                          # (length, bytes): a MIDI message out
NOTE_ON = 0x90
SYN = 2                                         # panel code of [SYN]; [FUNC] + [SYN] opens MACHINE SEL
MACHINE_TYPE, WAVERIDER = 222, 5                # a sound's machine type in RAM; Waverider's
WAVERIDER_DOWNS = 4                             # MACHINE SEL: FM TONE, FM DRUM, WAVETONE, SWARMER, WAVERIDER

# The small font the transposes are drawn in: its record (the font object 0x44507eb8
# points at it) holds the advance, the height, then its widths, offsets and bitmaps.
FONT_RECORD = 0x40290174
# The track box's header, (x0, y0, x1, y1) from the screen's top-left, on black, the
# text centred on x 7 from row 14.
TRACK_SPOT = (1, 14, 13, 20)
TEXT_CENTRE, TEXT_TOP = 7, 14
BLINK_FRAMES, BLINK_GAP = 4, "16M"     # the blink flips every ~30.8M instructions
ALTERNATION_FRAMES, ALTERNATION_GAP = 6, "62M"


@dataclass(frozen=True)
class Case:
    """A case: the mod's key presses, stock's own, and the scale written before PLAY."""
    presses: tuple[tuple[tuple[int, ...], tuple[int, ...]], ...]   # (keys held, keys tapped) for the mod
    degrees: int                   # the active track's degrees the presses must leave
    scale: int = 0                 # header SCALE (0 Ionian, 0xff CHROMATIC)
    root: int = 0
    switch: int = 0x00             # the per-track switch: 0x07 = SCALE, ROOT, MODE from the track
    track_scale: tuple[int, int] | None = None   # (SCALE, ROOT) of track 1, with switch 0x07
    stock_semitones: int = 0       # semitone shift applied with stock keys or the octave gesture
    octave_modifier: int | None = None   # TRK or PTN: test its FUNC octave with KEYBOARD held
    live: bool = False             # the chord held on the KEYBOARD page instead of the trigs
    track_spot: tuple[str, ...] = ()     # what the track's box may show after the keys (none: unchecked)


CASES = {
    "track-ionian": Case((((KEYBOARD, FUNC), (PLUS, PLUS)),), degrees=2, track_spot=("+2'",)),
    "track-trk": Case((((KEYBOARD, TRK), (PLUS, PLUS)),), degrees=2, track_spot=("+2'",)),
    "track-down": Case((((KEYBOARD, FUNC), (MINUS,)),), degrees=-1, track_spot=("-1'",)),
    "track-limit": Case((((KEYBOARD, FUNC), (PLUS,) * (bd.MAX_DEGREES + 2)),), degrees=bd.MAX_DEGREES,
                        track_spot=(f"+{bd.MAX_DEGREES}'",)),   # stops at the limit
    "chromatic": Case((((KEYBOARD, FUNC), (PLUS, PLUS)),), degrees=2, scale=0xFF, track_spot=("+2'",)),
    "per-track": Case((((KEYBOARD, FUNC), (PLUS,)),), degrees=1, switch=0x07,
                      track_scale=(7, 2), track_spot=("+1'",)),   # the track's Pentatonic Minor on D
    "with-stock-transpose": Case((((KEYBOARD, FUNC), (PLUS, PLUS)),), degrees=2, stock_semitones=1,
                                 track_spot=("+2'", "+1")),
    "live": Case((((KEYBOARD, FUNC), (PLUS, PLUS)),), degrees=2, live=True, track_spot=("+2'",)),
    "octave-track-up": Case((), degrees=0, stock_semitones=12, octave_modifier=TRK),
    "octave-track-down": Case((((KEYBOARD, TRK), (PLUS, PLUS)),), degrees=2, stock_semitones=-12,
                              octave_modifier=TRK),
    "octave-pattern-down": Case((), degrees=0, stock_semitones=-12, octave_modifier=PTN),
    "octave-pattern-up": Case((((KEYBOARD, FUNC), (PLUS, PLUS)),), degrees=2, stock_semitones=12,
                              octave_modifier=PTN),
}


def signed4(value: int) -> int:
    return value - 16 if value & 8 else value


def signed8(value: int) -> int:
    return value - 256 if value & 0x80 else value


def degrees_at(peeks: dict[int, list[bytes]], lo: int, i: int = -1) -> int:
    """Track 1's degrees in the pattern at LO, from the I-th of `degree_peek`'s reads."""
    return signed4((peeks[lo + bd.TRACK_FLAGS][i][0] & bd.TRACK_MASK) >> bd.TRACK_SHIFT)


def degree_peek(lo: int) -> list[str]:
    return [f"peek:{lo + bd.TRACK_FLAGS:#x}:1"]


@dataclass(frozen=True)
class Rig:
    """What every check runs against."""
    build: pathlib.Path
    stock: pathlib.Path
    lo: int                       # the playback copy of A1
    kit: int                      # the kit in RAM
    tables: list
    font: SmallFont
    frames: pathlib.Path


class SmallFont:
    """The firmware's small font, read from the image: one byte a column, row r at bit 2 + r."""

    def __init__(self, content: bytes):
        def at(va: int, n: int) -> bytes:
            return content[va - sd.BASE:va - sd.BASE + n]
        _advance, height, widths, offsets, bitmaps = struct.unpack(">5I", at(FONT_RECORD, 20))
        self.height = height
        self.widths, self.offsets, self.bitmaps = at(widths, 256), at(offsets, 512), (at, bitmaps)

    def columns(self, text: str) -> list[int]:
        """The text's columns, one pixel apart, as stock draws it."""
        at, bitmaps = self.bitmaps
        out: list[int] = []
        for i, ch in enumerate(text):
            offset = struct.unpack_from(">h", self.offsets, 2 * ord(ch))[0]
            out += ([0] if i else []) + list(at(bitmaps + offset, self.widths[ord(ch)]))
        return out


def spot_pixels(font: SmallFont, text: str) -> list[str]:
    """The track's box as stock would draw TEXT in it: black, the text's pixels cleared."""
    x0, y0, x1, y1 = TRACK_SPOT
    rows = [["#"] * (x1 - x0 + 1) for _ in range(y1 - y0 + 1)]
    cols = font.columns(text)
    left = TEXT_CENTRE - len(cols) // 2
    for i, col in enumerate(cols):
        for r in range(font.height):
            if col >> (2 + r) & 1:
                rows[TEXT_TOP - y0 + r][left - x0 + i] = "."
    return ["".join(row) for row in rows]


def frame_pixels(frame: pathlib.Path, spot: tuple[int, int, int, int]) -> list[str]:
    fields = frame.read_text().split()
    width, bits = int(fields[1]), fields[3:]
    x0, y0, x1, y1 = spot
    return ["".join("#" if bits[y * width + x] == "1" else "." for x in range(x0, x1 + 1))
            for y in range(y0, y1 + 1)]


def spot_text(font: SmallFont, frame: pathlib.Path, candidates) -> str | None:
    """Which of CANDIDATES the track's box shows ("" for an empty box), or None."""
    shown = frame_pixels(frame, TRACK_SPOT)
    for text in candidates:
        if shown == spot_pixels(font, text):
            return text
    return None


def press_steps(presses) -> list[str]:
    out: list[str] = []
    for held, tapped in presses:
        out += [step for key in held for step in (f"press:{key}", "wait:10M")]
        out += [step for key in tapped for step in (f"tap:{key}", "wait:20M")]
        out += [step for key in reversed(held) for step in (f"release:{key}", "wait:10M")]
        out += ["wait:40M"]
    return out


def scale_pokes(lo: int, case: Case) -> list[str]:
    header = lo + sd.HEADER
    out = [f"poke:{header + sd.H_SCALE:#x}:{case.scale:02x}00{case.root:02x}",
           f"poke:{header + sd.H_SWITCH:#x}:{case.switch:02x}"]
    if case.track_scale is not None:
        scale, root = case.track_scale
        out.append(f"poke:{lo + sd.T_SCALE:#x}:{scale:02x}00{root:02x}")
    return out


def trig_steps(setup: list[str]) -> list[str]:
    """TRIGS entered with NOTES on track 1, SETUP, then PLAY."""
    steps = sp.script({1: TRIGS}, "300M", notes=NOTES)
    at = steps.index(f"tap:{sp.PLAY}")
    return steps[:at] + setup + steps[at:]


def held_chord() -> list[str]:
    """LIVE_KEYS held on the KEYBOARD page, then released."""
    return ([f"tap:{KEYBOARD}", "wait:40M"] + [f"press:{k}" for k in LIVE_KEYS]
            + [f"wait:{LIVE_HOLD}"] + [f"release:{k}" for k in LIVE_KEYS] + ["wait:20M"])


def script(case: Case, lo: int, mod_keys: bool) -> list[str]:
    if case.octave_modifier is None:
        stock_keys = press_steps((((FUNC,), (PLUS,) * case.stock_semitones),)) if case.stock_semitones else []
        setup = stock_keys + (press_steps(case.presses) if mod_keys else [])
    else:
        setup = press_steps(case.presses) if mod_keys else []
        peek = degree_peek(lo) + [f"peek:{STOCK_TRANSPOSES:#x}:{STOCK_SPAN}"]
        held = (KEYBOARD, case.octave_modifier, FUNC) if mod_keys else (case.octave_modifier, FUNC)
        setup += peek + [step for key in held for step in (f"press:{key}", "wait:10M")]
        key = PLUS if case.stock_semitones > 0 else MINUS
        setup += [f"tap:{key}", "wait:40M"] + peek
        setup += [step for key in reversed(held) for step in (f"release:{key}", "wait:10M")]
        setup += ["wait:40M"] + peek
    setup = scale_pokes(lo, case) + setup + degree_peek(lo) + ["frame:spots"]
    if case.live:
        return BOOTED + setup + held_chord()
    return trig_steps(setup)


def drive(image: pathlib.Path, steps: list[str], frames: pathlib.Path, captures: tuple[str, ...] = ()
          ) -> dict:
    """panel_drive's report of STEPS on IMAGE, with the DSP frames and CAPTURES captured.
    Frames go to FRAMES."""
    cmd = [str(sp.panel_drive()), str(image), "--ssi-hz", "96000", "--out", str(frames),
           "--capture", ",".join((f"{sp.EXCHANGE}:1:48", *captures)), "--steps", ",".join(steps)]
    done = subprocess.run(cmd, capture_output=True, text=True, timeout=1500)
    result = json.loads(done.stdout)
    if result["outcome"] != "done":
        raise SystemExit(f"{image.name}: fault {result['fault']}")
    return result


def captured(result: dict, pc: int) -> list[dict]:
    return [c for c in result["captures"] if int(c["pc"], 16) == pc]


def note_ons(result: dict) -> list[tuple[int, ...]]:
    """The notes of each note-on sent to the DSP, in order."""
    found = SF.events(captured(result, int(sp.EXCHANGE, 16)))
    return [tuple(int(n) for n in e.notes) for e in SF.note_ons(found) if e.notes]


def run(image: pathlib.Path, steps: list[str], frames: pathlib.Path = pathlib.Path(".")
        ) -> tuple[list[tuple[int, ...]], dict[int, list[bytes]]]:
    """-> (the notes of each note-on, in order; {address: the bytes of each peek there, in order})."""
    result = drive(image, steps, frames)
    return note_ons(result), peeks_of(result)


def peeks_of(result: dict) -> dict[int, list[bytes]]:
    """{address: the bytes of each peek there, in order}."""
    peeks: dict[int, list[bytes]] = {}
    for r in result["results"]:
        if "peek" in r:
            peeks.setdefault(int(r["peek"], 16), []).append(bytes.fromhex(r["hex"]))
    return peeks


def expected(case: Case, stock_notes: list[tuple[int, ...]], tables) -> list[tuple[int, ...]]:
    """BUILD's notes: each of stock's, less stock's transpose, moved by the case's degrees."""
    if case.track_scale is not None:
        scale, root = case.track_scale
    else:
        scale, root = case.scale, case.root
    semis = list(range(12)) if scale == 0xFF else tables[scale]
    shift = case.stock_semitones
    return [tuple(ea.reference(n - shift, case.degrees, semis, root) + shift for n in chord)
            for chord in stock_notes]


def pitches(notes: list[tuple[int, ...]], case: Case) -> list[int]:
    """The notes played, in order. A live chord's keys can reach the ISR one audio frame
    apart (stock splits it too, depending on when the keys land), so its pitches are
    compared as a set."""
    played = [n for chord in notes for n in chord]
    return sorted(played) if case.live else played


def verdict(ok: bool, detail: str = "") -> bool:
    print(f"  {'ok  ' if ok else 'FAIL'}  {detail}".rstrip())
    return ok


def check(rig: Rig, name: str, case: Case) -> bool:
    """Play CASE on stock and on the build, print both, and compare the build with the rule."""
    stock_notes, stock_peeks = run(rig.stock, script(case, rig.lo, mod_keys=False), rig.frames)
    built_notes, peeks = run(rig.build, script(case, rig.lo, mod_keys=True), rig.frames)
    degrees = degrees_at(peeks, rig.lo)
    want = expected(case, stock_notes, rig.tables)
    pad = " " * len(name)
    print(f"\n{name}: stock  {stock_notes}")
    print(f"{pad}  build  {built_notes}")
    print(f"{pad}  want   {want}")
    print(f"{pad}  degrees  {degrees} (want {case.degrees})")
    spot_ok = True
    if case.track_spot:
        shown = spot_text(rig.font, rig.frames / "spots.pbm", case.track_spot)
        print(f"{pad}  track box  {shown!r} (want one of {list(case.track_spot)})")
        spot_ok = shown is not None
    ok = (bool(stock_notes) and pitches(built_notes, case) == pitches(want, case)
          and degrees == case.degrees and spot_ok)
    if case.octave_modifier is not None:
        want_transposes = bytearray(STOCK_SPAN)
        index = 1 if case.octave_modifier == TRK else 0
        want_transposes[index] = case.stock_semitones & 0xFF
        want_peeks = [bytes(STOCK_SPAN), bytes(STOCK_SPAN), bytes(want_transposes)]
        unchanged = all(degrees_at(peeks, rig.lo, i) == case.degrees
                        for i in range(len(peeks[rig.lo + bd.TRACK_FLAGS])))
        print(f"{pad}  semitones before/held/released: "
              f"{[value.hex() for value in peeks[STOCK_TRANSPOSES]]}; degrees unchanged: {unchanged}")
        ok = (ok and unchanged and peeks[STOCK_TRANSPOSES] == want_peeks
              and stock_peeks[STOCK_TRANSPOSES] == want_peeks)
    return verdict(ok, f"{len(built_notes)} note-ons")


BOOTED = ["wait:1500M", f"tap:{sp.NO}", "wait:60M"]
DEGREES_SET = press_steps((((KEYBOARD, FUNC), (PLUS, PLUS)),))   # +2
# The pattern save ([FUNC] + [YES]) runs as [YES] goes down: it converts the pattern into
# a buffer, then writes the buffer to the project's file on the card, from which
# [FUNC] + [NO] reads it back.
SAVE = press_steps((((FUNC,), (YES,)),))
YES_HOLD = 10_000_000           # how long the stock-load check holds [YES]
SAVE_ROUTINE = 0x400DE7A8       # (buffer, pattern in RAM, ...): the pattern converted for saving
CARD_WRITE = 0x4012EB6C         # (file, buffer, ...): the buffer written to the card
TRACK_RECORD = 4                # track 1's place in a stored pattern
RECORD_PREFIX = TRACK_RECORD + STORED_FLAGS + 1   # the bytes of a write read here: up to track 1's byte
RELOAD = press_steps((((FUNC,), (sp.NO,)),))


def check_pending(rig: Rig) -> bool:
    """Held, the amount is pending: not written, and blinking; released, it is applied."""
    lo, font, frames = rig.lo, rig.font, rig.frames
    held = [step for i in range(BLINK_FRAMES) for step in (f"frame:held{i}", f"wait:{BLINK_GAP}")]
    steps = (BOOTED + [f"press:{KEYBOARD}", "wait:10M", f"press:{FUNC}",
                       "wait:10M", f"tap:{PLUS}", "wait:20M", f"tap:{PLUS}", "wait:20M"]
             + degree_peek(lo) + held
             + [f"release:{FUNC}", "wait:10M", f"release:{KEYBOARD}", "wait:60M"]
             + degree_peek(lo) + ["frame:released"])
    _, peeks = run(rig.build, steps, frames)
    held_amount, released_amount = degrees_at(peeks, lo, 0), degrees_at(peeks, lo, 1)
    seen = {spot_text(font, frames / f"held{i}.pbm", ("", "+2'")) for i in range(BLINK_FRAMES)}
    after = spot_text(font, frames / "released.pbm", ("+2'",))
    print(f"\npending: held, the degrees {held_amount} and the box shows {sorted(seen, key=str)}; "
          f"released, the degrees {released_amount} and the box {after!r}")
    return verdict(held_amount == 0 and seen == {"", "+2'"} and released_amount == 2 and after == "+2'")


def check_alternation(rig: Rig) -> bool:
    """A track with a stock +1 semitone and +2 degrees shows both, one after the other."""
    shots = [step for i in range(ALTERNATION_FRAMES) for step in (f"frame:alt{i}", f"wait:{ALTERNATION_GAP}")]
    steps = BOOTED + press_steps((((FUNC,), (PLUS,)),)) + DEGREES_SET + shots
    run(rig.build, steps, rig.frames)
    seen = [spot_text(rig.font, rig.frames / f"alt{i}.pbm", ("+2'", "+1")) for i in range(ALTERNATION_FRAMES)]
    print(f"\nalternation: the track's box over {ALTERNATION_FRAMES} frames {seen}")
    return verdict(set(seen) == {"+2'", "+1"})


def select_pattern(trig: int) -> list[str]:
    return [f"press:{PTN}", "wait:10M", f"tap:{trig}", "wait:10M", f"release:{PTN}", "wait:60M"]


def check_scope(rig: Rig) -> bool:
    """A1's degrees stay A1's: an amount set on A2 lands in A2, A1 keeps its own, and the
    track box shows each pattern's amount."""
    lo, a2 = rig.lo, rig.lo + PATTERN_STRIDE
    both = degree_peek(lo) + degree_peek(a2)
    down = press_steps((((KEYBOARD, FUNC), (MINUS,)),))   # -1
    steps = (BOOTED + DEGREES_SET + select_pattern(sp.TRIG1 + 1) + down + both + ["frame:on_a2"]
             + select_pattern(sp.TRIG1) + both + ["frame:back"])
    _, peeks = run(rig.build, steps, rig.frames)
    on_a2 = (degrees_at(peeks, lo, 0), degrees_at(peeks, a2, 0))
    back = (degrees_at(peeks, lo, 1), degrees_at(peeks, a2, 1))
    boxes = (spot_text(rig.font, rig.frames / "on_a2.pbm", ("-1'",)),
             spot_text(rig.font, rig.frames / "back.pbm", ("+2'",)))
    print(f"\nscope: on A2, A1 {on_a2[0]} and A2 {on_a2[1]}, the box {boxes[0]!r}; "
          f"back on A1, A1 {back[0]} and A2 {back[1]}, the box {boxes[1]!r}")
    return verdict(on_a2 == back == (2, -1) and boxes == ("-1'", "+2'"))


def peek_icounts(result: dict, address: int) -> list[int]:
    """When each peek at ADDRESS ran, in order."""
    return [int(r["icount"]) for r in result["results"] if "peek" in r and int(r["peek"], 16) == address]


def check_clear(rig: Rig) -> bool:
    """Clearing the pattern, then the track, keeps the track's +1 semitone and +2 degrees, as
    stock (the control, run alongside) keeps its semitones. The pattern clear must reset the
    pattern's +1 semitone, and each clear must run the track default, so a clear that did
    nothing fails."""
    lo = rig.lo
    track_semis, pattern_semis = lo + bd.LIVE_TRANSPOSE, lo + sd.HEADER + PATTERN_TRANSPOSE
    state = degree_peek(lo) + [f"peek:{track_semis:#x}:1", f"peek:{pattern_semis:#x}:1"]
    clear_pattern = press_steps((((FUNC,), (sp.PLAY,)),))
    clear_track = [f"tap:{sp.RECORD}", "wait:40M"] + clear_pattern + [f"tap:{sp.RECORD}", "wait:40M"]
    semitones = press_steps((((FUNC,), (PLUS,)), ((PTN,), (PLUS,))))

    def steps(mod_keys: bool) -> list[str]:
        degrees = DEGREES_SET if mod_keys else []
        return BOOTED + semitones + degrees + state + clear_pattern + state + clear_track + state

    stages = ("set", "pattern cleared", "track cleared")
    seen = {}
    for who, image in (("stock", rig.stock), ("build", rig.build)):
        result = drive(image, steps(who == "build"), rig.frames, (f"{bd.DEFAULT_SITE:#x}:0:0",))
        peeks, at = peeks_of(result), peek_icounts(result, track_semis)
        defaults = [int(c["icount"]) for c in captured(result, bd.DEFAULT_SITE)]
        ran = [sum(at[i - 1] < icount <= at[i] for icount in defaults) for i in (1, 2)]
        seen[who] = ([(signed8(peeks[track_semis][i][0]), signed8(peeks[pattern_semis][i][0]),
                       degrees_at(peeks, lo, i)) for i in range(len(stages))], ran)
    for i, stage in enumerate(stages):
        print(f"\nclear, {stage}: (track semitones, pattern semitones, degrees) "
              f"stock {seen['stock'][0][i]}, build {seen['build'][0][i]}")
    print(f"       the track default ran {seen['build'][1]} times in the two clears")
    want = [(1, 1, 2), (1, 0, 2), (1, 0, 2)]
    stock_semitones = [semis[:2] for semis in seen["stock"][0]]
    return verdict(seen["build"][0] == want and stock_semitones == [semis[:2] for semis in want]
                   and all(seen["build"][1]))


def check_ptn_stock(rig: Rig) -> bool:
    """[KEYBOARD] + [PTN] + [+] is stock's: the same notes, transposes, degrees and screen."""
    keys = press_steps((((KEYBOARD, PTN), (PLUS,)),))
    setup = keys + degree_peek(rig.lo) + [f"peek:{STOCK_TRANSPOSES:#x}:{STOCK_SPAN}"]
    screens, played, peeked = {}, {}, {}
    for who, image in (("stock", rig.stock), ("build", rig.build)):
        played[who], peeked[who] = run(image, trig_steps(setup + [f"frame:{who}"]), rig.frames)
        screens[who] = (rig.frames / f"{who}.pbm").read_text()
    transposes = {who: peeked[who][STOCK_TRANSPOSES][0].hex() for who in played}
    print(f"\nptn-stock: stock {played['stock']} transposes {transposes['stock']}\n"
          f"           build {played['build']} transposes {transposes['build']}, "
          f"degrees {degrees_at(peeked['build'], rig.lo)}; screens equal: {screens['stock'] == screens['build']}")
    return verdict(bool(played["stock"]) and played["stock"] == played["build"]
                   and transposes["stock"] == transposes["build"] and degrees_at(peeked["build"], rig.lo) == 0
                   and screens["stock"] == screens["build"])


def stored_tracks(result: dict) -> list[tuple[int, bytes]]:
    """(the stored track's address, its bytes) for each track of each pattern load."""
    return [(int(c["args"][1], 16), bytes.fromhex(c["hex"])) for c in captured(result, TRACK_LOAD)]


def check_reload(rig: Rig) -> bool:
    """The degrees go through stock's save and load of the pattern, in the stored format, and come back."""
    lo = rig.lo
    steps = (BOOTED + DEGREES_SET + SAVE + press_steps((((KEYBOARD, FUNC), (MINUS, MINUS, MINUS)),))
             + degree_peek(lo) + RELOAD + degree_peek(lo))
    result = drive(rig.build, steps, rig.frames, (f"{TRACK_LOAD:#x}:1:{STORED_FLAGS + 1}",))
    peeks = peeks_of(result)
    changed, reloaded = degrees_at(peeks, lo, 0), degrees_at(peeks, lo, 1)
    tracks = [signed4((stored[STORED_FLAGS] & bd.TRACK_MASK) >> bd.TRACK_SHIFT)
              for _, stored in stored_tracks(result)]
    print(f"\nreload: changed to {changed}, reloaded {reloaded}; stored, the tracks {tracks}")
    return verdict(changed == -1 and reloaded == 2 and tracks == [2] + [0] * (TRACKS - 1))


def check_stock_load(rig: Rig) -> bool:
    """Stock, given a saved pattern with degrees, plays it as recorded and keeps its own bits,
    and its next save clears the degrees."""
    lo = rig.lo
    mark = f"peek:{STOCK_TRANSPOSES:#x}:1"
    played_bytes = [f"peek:{lo + sd.T_SCALE:#x}:3", f"peek:{lo + bd.TRACK_FLAGS:#x}:1"]
    captures = (f"{TRACK_LOAD:#x}:1:{STORED_FLAGS + 1}", f"{SAVE_ROUTINE:#x}:0:0",
                f"{CARD_WRITE:#x}:1:{RECORD_PREFIX}")

    def steps(write: list[str], before: int) -> list[str]:
        """Save, with WRITE made BEFORE instructions after [YES] goes down; reload and play;
        then save again."""
        save = ([f"press:{FUNC}", "wait:10M", f"press:{YES}", mark, f"wait:{before}"] + write
                + [f"wait:{YES_HOLD - before}", f"release:{YES}", "wait:30M", f"release:{FUNC}", "wait:50M"])
        return trig_steps(save + RELOAD + played_bytes) + SAVE

    def report(result: dict) -> tuple[int, list[tuple[int, int, bytes]], list[tuple[int, bytes]]]:
        """(the mark's icount; each pattern write to the card after it, as (the save's icount,
        the write's, the bytes written); each track load after it, as (stored track, bytes))."""
        marked = int(next(r["icount"] for r in result["results"] if r.get("peek") == mark.split(":")[1]))
        after = [c for c in result["captures"] if int(c["icount"]) > marked]
        writes = []
        for save in (c for c in after if int(c["pc"], 16) == SAVE_ROUTINE):
            write = next(c for c in after if int(c["pc"], 16) == CARD_WRITE and int(c["icount"]) > int(save["icount"])
                         and c["args"][1] == save["args"][0])
            writes.append((int(save["icount"]), int(write["icount"]), bytes.fromhex(write["hex"])))
        loads = [(int(c["args"][1], 16), bytes.fromhex(c["hex"])) for c in after if int(c["pc"], 16) == TRACK_LOAD]
        return marked, writes, loads

    marked, writes, loads = report(drive(rig.stock, steps([], 1), rig.frames, captures))
    saved_at, written_at, record = writes[0]
    at, stored = loads[0]                          # track 1, as the reload loads it
    original = stored[STORED_FLAGS]
    buffer = at - TRACK_RECORD                     # where the save put the pattern
    before = (saved_at + written_at) // 2 - marked
    if not 0 < before < written_at - marked < YES_HOLD:
        raise SystemExit(f"stock-load: the save at {saved_at} and its card write at {written_at} "
                         f"do not fit in [YES]'s hold from {marked}")
    stock_byte = original | STOCK_BITS
    with_degrees = stock_byte | DEGREES_BITS

    runs = {}
    for name, value in (("plain", stock_byte), ("degrees", with_degrees)):
        write = [f"poke:{buffer + TRACK_RECORD + STORED_FLAGS:#x}:{value:02x}"]
        result = drive(rig.stock, steps(write, before), rig.frames, captures)
        runs[name] = (note_ons(result), peeks_of(result), *report(result)[1:])
    (plain, plain_peeks, _, _), (moved, peeks, writes, loads) = runs["plain"], runs["degrees"]
    on_card, loaded, saved_again = (writes[0][2][TRACK_RECORD + STORED_FLAGS], loads[0][1][STORED_FLAGS],
                                    writes[-1][2][TRACK_RECORD + STORED_FLAGS])
    same_bytes = all(peeks[lo + off] == plain_peeks[lo + off] for off in (sd.T_SCALE, bd.TRACK_FLAGS))
    print(f"\nstock-load: track 1's +1176 saved {original:#04x}, made {stock_byte:#04x}; with +2 degrees "
          f"written {on_card:#04x} to the card and loaded {loaded:#04x}")
    print(f"            without degrees {plain}\n            with degrees    {moved}")
    print(f"            playing pattern's SETUP and byte as without: {same_bytes}; saved again {saved_again:#04x}")
    return verdict(bool(plain) and on_card == loaded == with_degrees and moved == plain and same_bytes
                   and saved_again == stock_byte)


def midi_pokes(kit: int) -> list[str]:
    """Track 1 a MIDI track on channel 1 (the other tracks' bits are 0 at start-up)."""
    return ([f"poke:{mask + 1:#x}:01" for mask in (kit + KIT_MIDI_MASK, *MIDI_MASK_COPIES)]
            + [f"poke:{MIDI_FLAGS + 3:#x}:01", f"poke:{MIDI_CHANNEL:#x}:00"])


def midi_notes(result: dict) -> list[tuple[str, int]]:
    """The note messages sent, in order: ("on", note), or ("off", note) for velocity 0."""
    out = []
    for c in captured(result, MIDI_SEND):
        status, note, velocity = bytes.fromhex(c["hex"])[:3]
        if status & 0xF0 == NOTE_ON:
            out.append(("on" if velocity else "off", note))
    return out


def ionian(rig: Rig, degrees: int):
    """The rule for C Ionian (the pattern's scale the checks set)."""
    return lambda note: ea.reference(note, degrees, rig.tables[0], 0)


def midi_runs(rig: Rig, steps) -> tuple[list, list]:
    """(stock's MIDI notes, BUILD's), with STEPS(mod_keys) on each."""
    capture = (f"{MIDI_SEND:#x}:1:0",)
    return (midi_notes(drive(rig.stock, steps(False), rig.frames, capture)),
            midi_notes(drive(rig.build, steps(True), rig.frames, capture)))


def check_midi(rig: Rig) -> bool:
    """A MIDI track's sequenced notes move by its degrees, as stock's semitones move them,
    and each note-on has its note-off."""
    stock_semitone = press_steps((((FUNC,), (PLUS,)),))
    def steps(mod_keys: bool) -> list[str]:
        keys = stock_semitone + (DEGREES_SET if mod_keys else [])
        return trig_steps(midi_pokes(rig.kit) + scale_pokes(rig.lo, Case((), 0)) + keys)
    stock, built = midi_runs(rig, steps)
    move = ionian(rig, 2)
    want = [move(n - 1) + 1 for kind, n in stock if kind == "on"]
    ons = [n for kind, n in built if kind == "on"]
    offs = sorted(n for kind, n in built if kind == "off")
    print(f"\nmidi: stock {[n for kind, n in stock if kind == 'on']}\n      build {ons}\n      want  {want}; "
          f"note-offs {offs}")
    return verdict(bool(want) and ons == want and offs == sorted(ons))


def check_midi_live(rig: Rig) -> bool:
    """A chord held live on a MIDI track: the notes moved, and the same notes turned off."""
    def steps(mod_keys: bool) -> list[str]:
        keys = DEGREES_SET if mod_keys else []
        return (BOOTED + midi_pokes(rig.kit) + scale_pokes(rig.lo, Case((), 0)) + keys
                + held_chord() + ["wait:60M"])
    stock, built = midi_runs(rig, steps)
    move = ionian(rig, 2)
    want = sorted(move(n) for kind, n in stock if kind == "on")
    ons = sorted(n for kind, n in built if kind == "on")
    offs = sorted(n for kind, n in built if kind == "off")
    print(f"\nmidi-live: stock {stock}\n           build {built}; want on and off {want}")
    return verdict(len(want) == len(LIVE_KEYS) and ons == want and offs == want)


def check_layered(rig: Rig) -> bool:
    """Track 1 layered onto track 2, degrees on track 1 only: the copies play as stock's."""
    def steps(mod_keys: bool) -> list[str]:
        keys = DEGREES_SET if mod_keys else []
        layer = f"poke:{rig.kit + KIT_LAYERS:#x}:0002"          # track 1 -> track 2
        return trig_steps([layer] + scale_pokes(rig.lo, Case((), 0)) + keys)
    stock, _ = run(rig.stock, steps(False), rig.frames)
    built, _ = run(rig.build, steps(True), rig.frames)
    move = ionian(rig, 2)
    want = [tuple(sorted((chord[0], move(chord[0])))) for chord in stock]
    print(f"\nlayered: stock {stock}\n         build {built}\n         want  {want}")
    return verdict(bool(stock) and all(len(chord) == 2 and chord[0] == chord[1] for chord in stock)
                   and [tuple(sorted(chord)) for chord in built] == want)


def with_waverider(image: pathlib.Path, out: pathlib.Path) -> pathlib.Path:
    """IMAGE with the waverider mod applied by `dnfw mods apply`, written to OUT."""
    cmd = [sys.executable, "-m", "dnfw.cli.main", "mods", "apply", str(image), "--mod", "waverider", "-o", str(out)]
    done = subprocess.run(cmd, capture_output=True, text=True, timeout=600,
                          env=os.environ | {"PYTHONPATH": str(ROOT / "src")})
    if done.returncode:
        raise SystemExit(f"waverider on {image.name}: {(done.stderr or done.stdout)[-400:]}")
    return out


def check_waverider(rig: Rig) -> bool:
    """A Waverider track moves by its degrees, as an FM track does: Waverider plays the pitch
    the note hook moves."""
    machine_sel = (press_steps((((FUNC,), (SYN,)),)) + [x for _ in range(WAVERIDER_DOWNS)
                   for x in (f"tap:{sp.DOWN}", "wait:40M")] + [f"tap:{YES}", "wait:200M", f"tap:{sp.NO}", "wait:100M"])
    images = {"control": with_waverider(rig.stock, rig.frames / "waverider.syx"),
              "build": with_waverider(rig.build, rig.frames / "build-waverider.syx")}
    seen = {}
    for who, image in images.items():
        lo, first_sound, _ = ea.addresses(image)
        setup = (machine_sel + scale_pokes(lo, Case((), 0)) + (DEGREES_SET if who == "build" else [])
                 + [f"peek:{first_sound + MACHINE_TYPE:#x}:1"])
        notes, peeks = run(image, trig_steps(setup), rig.frames)
        seen[who] = (notes, peeks[first_sound + MACHINE_TYPE][0][0])
    (control, control_machine), (built, machine) = seen["control"], seen["build"]
    want = expected(Case((), 2), control, rig.tables)
    print(f"\nwaverider: machine types {control_machine} and {machine}\n"
          f"           control {control}\n           build   {built}\n           want    {want}")
    return verdict(bool(control) and control_machine == machine == WAVERIDER and built == want)


CHECKS = {"pending": check_pending, "alternation": check_alternation, "scope": check_scope,
          "clear": check_clear, "ptn-stock": check_ptn_stock, "reload": check_reload,
          "stock-load": check_stock_load, "midi": check_midi, "midi-live": check_midi_live,
          "layered": check_layered, "waverider": check_waverider}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("build", type=pathlib.Path)
    ap.add_argument("--stock", type=pathlib.Path, default=ea.STOCK)
    ap.add_argument("--case", action="append", choices=list(CASES) + list(CHECKS))
    a = ap.parse_args()
    stock_os = load(read_image(a.stock)).container.find(bs.MAIN_OS).unpack()
    tables, font = sd.scales(stock_os), SmallFont(stock_os)

    lo, first_sound, _ = ea.addresses(a.stock)
    kit = first_sound - ea.SOUND_FIRST
    print(f"playback copy {lo:#010x}, kit {kit:#010x}")
    names = a.case or list(CASES) + list(CHECKS)
    with tempfile.TemporaryDirectory() as tmp:
        rig = Rig(a.build, a.stock, lo, kit, tables, font, pathlib.Path(tmp))
        failures = sum(not (CHECKS[name](rig) if name in CHECKS else check(rig, name, CASES[name]))
                       for name in names)
    print(f"\n{failures} failing case(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())

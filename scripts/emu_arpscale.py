"""arpscale in the emulator: the arp's step offsets against a reference, stock alongside.

    python scripts/emu_arpscale.py BUILD.syx [--stock STOCK.syx] [--case NAME ...]

Plays the sequencer headless (`scripts/emu_seqplay.py` and digikit's `panel_drive`,
which runs the frame ISR, the step clock and the arp): a C major chord (C4 E4 G4)
on track 1's first trig, arp UP, as `emu_seqplay.py --chord 4,3 --chord-length 60 --arp UP`.
Before PLAY it writes, through `panel_drive`'s `poke` step:

- the sound's sixteen step offsets (`[0x800052a0] + 52 + 1163 x track`, `+358`);
- the toggle (`0x405cd8af`, 1 = on);
- SCALE, ROOT, MODE and the per-track switch in the playback copy of the
  pattern (`L = *0x42c5a9a0`: the header at `L + 0x1dd40`, the track at
  `L + 1701 x track`), whose addresses a first run reads with `peek`;
- the arp's LEN (16 steps) and step mask (all on).

The arp starts its step count again at every trig, so a note's step is its
place in its trig's run of notes.

The runs in `LIVE` play a case from the KEYBOARD page instead of a trig: track
3 selected and its arp UP, TRIG 9, 11 and 13 are held for about 24 arp steps,
with the sequencer stopped or, for one, playing an empty pattern. The keys follow the track's scale and root
(C4 E4 G4 in C major, D4 F4 A4 in D pentatonic minor). A live note's voice
record has no playback copy (`+44` is zero), so this checks the cave's other
way to the scale, and track 3 checks that it finds the right track.

The run in `LAYERED` lays track 1's trig onto track 2 (TRACK WILL TRIGGER), with
track 1's arp off and track 2's arp UP. The copy is a copy of the trig, so
track 2 arpeggiates the chord, and its voice record keeps track 1's playback
copy (`+44`) while naming track 2 (`+16`). Track 1 is C Ionian and track 2
Pentatonic Minor on D, each from its own KEYBOARD SETUP, so a lookup that took
the wrong track's part would play C Ionian. Track 1's chord, played as entered
at each trig, is set aside before the comparison.

For every case the same pokes go to stock and to BUILD. Stock is the control:
its notes must be the held note plus the offset in semitones, which also yields
the held note of each step (`stock - offset`). BUILD's notes must equal the rule
in `scripts/build_arpscale.py`, computed here in Python from the firmware's own
scale tables, independently of the ColdFire code. A case that keeps stock
behaviour (toggle off, CHROMATIC, CHORD MEMORY) must equal stock exactly.

The `marked-` cases also mark steps 2, 5, 10 and 15 to move in semitones (the sound's
`+0xdc`, bit n for step n): those steps must play stock's note and the others the rule;
with the toggle off, every step stock's.

The `step-` checks drive the ARPEGGIATOR menu from the panel on track 1:

- `step-keys`: `[UP]` and `[DOWN]` on step 3, the mask and the marks read after each press,
  with the toggle on (muted, degrees, semitones) and then off (stock's mute and unmute,
  which leave the step unmarked);
- `step-graph`: the screen with steps 2 and 13 marked, against stock with the same pokes.
  Toggle off, the two are the same pixel for pixel; on, they differ only in the two steps'
  boxes, and the lit pixels in each box form exactly a plus;
- `step-rotate`: `[FUNC]` + `[LEFT]`, then `[RIGHT]` twice, with LEN 8: the marks move as
  the mask does within LEN, and a mark past LEN stays;
- `step-clipboard`: copy on track 1, paste on track 2 and its undo, clear on track 1 and
  its undo: the marks follow, while the offsets and mask are stock's at every point;
- `step-store`: a temporary save (`[FUNC]` + `[YES]`), the marks changed, the reload
  (`[FUNC]` + `[NO]`): the build reads the saved marks back from the stored sound, and
  stock's slot 100 reads 0.

Needs what `scripts/emu_seqplay.py` needs: a `panel_drive` that delivers the forced
interrupts and takes a literal `--capture` length (digikit #65 and #66; the
`feat/seqplay-chords` branch of angellinares/digikit has both), found through
`PANEL_DRIVE`. Its `poke` and `peek` steps write and read RAM.
"""

from __future__ import annotations

import argparse
import collections
import itertools
import json
import pathlib
import subprocess
import sys
from typing import Literal

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "scripts")]

import build_arpscale as bs  # noqa: E402
import build_scale_degrees as sd  # noqa: E402
import emu_seqplay as sp  # noqa: E402
from dnfw import seqframes as SF  # noqa: E402
from dnfw.cli.files import read_image  # noqa: E402
from dnfw.firmware.load import load  # noqa: E402

STOCK = ROOT / "00_Resources/00_Firmware/Digitone_II_OS1.11_dist/Digitone_II_OS1.11.syx"

PLAYBACK = 0x42C5A9A0          # -> L, the playback copy of the pattern
SOUNDS = 0x800052A0            # -> the live sounds: + 52 + 1163 x track
SOUND_FIRST, SOUND_STRIDE, OFFSETS = 52, 1163, 358
ARP_LEN, ARP_MASK = 355, 356   # the arp's LEN (steps - 1) and its u16 step mask
TRACK = 0
C4 = 60                        # a fresh trig's note
CHORD = [4, 3]                 # C4, then +4 (E4), then +3 (G4)
TRIG_CHORD = tuple(itertools.accumulate([C4, *CHORD]))   # the chord as entered
CHORD_LEN = 60                 # units of the chord's note length: about 14 arp steps a trig
KEYBOARD = 18                  # panel code of [KEYBOARD]
LIVE_KEYS = (33, 35, 37)       # TRIG 9, 11, 13 on the KEYBOARD page: C4 E4 G4 in C major
LIVE_TRACK = 2                 # track 3: not track 1, so a wrong track index shows
LIVE_HOLD = "400M"             # how long the keys are held: about 24 arp steps
LAYER_DESTINATION = 1          # track 2
KIT_LAYERS = 0x5CE0            # [0x800052a0] + this: track 1's layer destinations, a u16 mask
STEP = 16.5e6                  # a sixteenth at 120 BPM, in instructions
RUN_GAP = 1.5 * STEP           # a longer gap between note-ons starts the next trig's run
OFFS = [0, 2, 2, -1, 3, -2, 7, -7, 1, 4, -3, 5, 0, -8, 9, -1]
STEP_MARKS = (1 << 1) | (1 << 4) | (1 << 9) | (1 << 14)   # steps 2, 5, 10, 15 in semitones
ARP, UP, DOWN, LEFT, RIGHT, YES = 51, 11, 14, 13, 15, 10   # panel codes
RECORD, PLAY, STOP = 19, 20, 21
GRAPH_X, GRAPH_STEP = 34, 4   # the step graph: step n's box is centred on x = 34 + 4 n

# name -> (toggle, header SCALE, ROOT, MODE, switch, track SCALE, ROOT, MODE, stock expected)
CASES = {
    "ionian-c":        (1, 0, 0, 0, 0x00, None, None, None, False),
    "hirajoshi-a":     (1, 17, 9, 0, 0x00, None, None, None, False),
    "per-track":       (1, 0, 0, 0, 0x07, 7, 2, 0, False),     # header Ionian C, track Pent. Min D
    "chord-memory":    (1, 0, 0, 5, 0x00, None, None, None, True),
    "toggle-off":      (0, 0, 0, 0, 0x00, None, None, None, True),
    "chromatic":       (1, 0xFF, 0, 0, 0x00, None, None, None, True),
    "marked-ionian-c": (1, 0, 0, 0, 0x00, None, None, None, False),
    "marked-toggle-off": (0, 0, 0, 0, 0x00, None, None, None, True),
}
CASE_MARKS = {"marked-ionian-c": STEP_MARKS, "marked-toggle-off": STEP_MARKS}

# How a run plays its chord: a trig on track 1, held on the KEYBOARD page with the
# sequencer stopped or playing, or a trig on track 1 layered onto track 2, whose arp plays it.
Source = Literal["trig", "stopped", "playing", "layered"]
ARP_TRACK: dict[Source, int] = {"trig": TRACK, "stopped": LIVE_TRACK, "playing": LIVE_TRACK,
                                "layered": LAYER_DESTINATION}
LIVE: dict[str, tuple[str, Source]] = {
    "live-ionian-c": ("ionian-c", "stopped"),
    "live-per-track": ("per-track", "stopped"),
    "live-toggle-off": ("toggle-off", "stopped"),
    "live-playing-ionian-c": ("ionian-c", "playing"),
}
LAYERED: dict[str, tuple[str, Source]] = {"layered-per-track": ("per-track", "layered")}
RUNS: dict[str, tuple[str, Source]] = {name: (name, "trig") for name in CASES} | LIVE | LAYERED


def reference(held: int, offset: int, semis: list[int], root: int) -> int:
    """The rule, in Python: `held` moved `offset` degrees of the scale `semis` from `root`."""
    if offset == 0:
        return held
    rel = held - root
    octave, pc = divmod(rel, 12)
    if pc not in semis:
        for d in range(1, 12):
            if (pc - d) % 12 in semis:
                octave += (pc - d) // 12
                pc = (pc - d) % 12
                break
            if (pc + d) % 12 in semis:
                octave += (pc + d) // 12
                pc = (pc + d) % 12
                break
    octaves, degree = divmod(semis.index(pc) + offset, len(semis))
    return root + 12 * (octave + octaves) + semis[degree]


def select(track_index: int) -> list[str]:
    """The panel steps that make TRACK_INDEX the active track: TRK held, its trig key."""
    return [f"press:{sp.TRK}", "wait:10M", f"tap:{sp.TRIG1 + track_index}",
            f"release:{sp.TRK}", "wait:30M"]


def live_script(extra: list[str], playing: bool) -> list[str]:
    """Select LIVE_TRACK, set its arp to UP, run EXTRA, then hold LIVE_KEYS on the
    KEYBOARD page, with the sequencer stopped or PLAYING."""
    arp = sp.arp_steps("UP")
    hold = ([f"tap:{KEYBOARD}", "wait:40M"] + [f"press:{k}" for k in LIVE_KEYS]
            + [f"wait:{LIVE_HOLD}"] + [f"release:{k}" for k in LIVE_KEYS] + ["wait:20M"])
    if playing:
        hold = [f"tap:{sp.PLAY}", "wait:30M"] + hold + [f"tap:{sp.STOP}", "wait:20M"]
    return ["wait:1500M", f"tap:{sp.NO}", "wait:60M"] + select(LIVE_TRACK) + arp + extra + hold


def runs(found: list[SF.NoteEvent]) -> list[list[SF.NoteEvent]]:
    """The note-ons, grouped into one run per trig: the arp starts its steps again at each."""
    grouped: list[list[SF.NoteEvent]] = []
    for event in SF.note_ons(found):
        if grouped and event.icount - grouped[-1][-1].icount <= RUN_GAP:
            grouped[-1].append(event)
        else:
            grouped.append([event])
    return grouped


def without_trig_chord(image: pathlib.Path, notes: list[int]) -> list[int]:
    """A layered run's first event, less track 1's chord as entered: the copy's first arp note."""
    present, chord = collections.Counter(notes), collections.Counter(TRIG_CHORD)
    rest = list((present - chord).elements())
    if chord - present or len(rest) != 1:
        raise SystemExit(f"{image.name}: a layered trig played {notes}, not track 1's chord "
                         f"{list(TRIG_CHORD)} and one arp note")
    return rest


def run(image: pathlib.Path, extra: list[str], source: Source) -> tuple[list, dict]:
    """-> ([(step, note), ...] in play order, {address: bytes peeked})."""
    if source in ("stopped", "playing"):
        steps = live_script(extra, source == "playing")
    else:
        layered = source == "layered"
        steps = sp.script({1: [1]}, "700M", chord=CHORD, chord_length=CHORD_LEN,
                          arp=None if layered else "UP")
        if layered:     # track 1's arp stays off; track 2's plays the copies
            extra = select(LAYER_DESTINATION) + sp.arp_steps("UP") + extra
        at = steps.index(f"tap:{sp.PLAY}")
        steps[at:at] = extra
    cmd = [str(sp.panel_drive()), str(image), "--ssi-hz", "96000",
           "--capture", f"{sp.EXCHANGE}:1:48", "--steps", ",".join(steps)]
    done = subprocess.run(cmd, capture_output=True, text=True, timeout=1500)
    result = json.loads(done.stdout)
    if result["outcome"] != "done":
        raise SystemExit(f"{image.name}: fault {result['fault']}")
    peeks = {int(r["peek"], 16): bytes.fromhex(r["hex"]) for r in result["results"] if "peek" in r}
    played = []
    for group in runs(SF.events(result["captures"])):
        for k, event in enumerate(group):
            notes = [int(n) for n in event.notes]
            if source == "layered" and k == 0:
                notes = without_trig_chord(image, notes)
            if notes:
                played.append((k, notes[0]))
    return played, peeks


def addresses(image: pathlib.Path) -> tuple[int, int, int]:
    """-> (L, the first sound, the switch byte as found)."""
    _, peeks = run(image, [f"peek:{PLAYBACK:#x}:4", f"peek:{SOUNDS:#x}:4"], "trig")
    lo = int.from_bytes(peeks[PLAYBACK], "big")
    sound = int.from_bytes(peeks[SOUNDS], "big") + SOUND_FIRST
    _, peeks = run(image, [f"peek:{lo + sd.HEADER + sd.H_SWITCH:#x}:1"], "trig")
    return lo, sound, peeks[lo + sd.HEADER + sd.H_SWITCH][0]


def pokes(lo: int, first_sound: int, case: tuple, track_index: int, marks: int) -> list[str]:
    toggle, hs, hr, hm, switch, ts, tr, tm, _ = case
    header = lo + sd.HEADER
    track = lo + sd.TRACK_STRIDE * track_index
    sound = first_sound + SOUND_STRIDE * track_index
    out = [f"poke:{sound + OFFSETS:#x}:" + bytes(o & 0xFF for o in OFFS).hex(),
           f"poke:{sound + ARP_LEN:#x}:0fffff",
           f"poke:{sound + bs.MARKS:#x}:{marks:04x}",

           f"poke:{bs.FLAG:#x}:{toggle:02x}",
           f"poke:{header + sd.H_SCALE:#x}:{hs:02x}{hm:02x}{hr:02x}",
           f"poke:{header + sd.H_SWITCH:#x}:{switch:02x}"]
    if ts is not None:
        out.append(f"poke:{track + sd.T_SCALE:#x}:{ts:02x}{tm:02x}{tr:02x}")
    return out


def layer_pokes(lo: int, first_sound: int) -> list[str]:
    """Track 1's own SCALE, MODE and ROOT set to C Ionian, which the layered case's scale
    on LAYER_DESTINATION differs from, and track 1 layered onto LAYER_DESTINATION."""
    kit = first_sound - SOUND_FIRST
    return [f"poke:{lo + sd.T_SCALE:#x}:000000",
            f"poke:{kit + KIT_LAYERS:#x}:{1 << LAYER_DESTINATION:04x}"]


def expected(case: tuple, stock_played: list, tables: list[list[int]], marks: int) -> list[int] | None:
    """-> the notes BUILD must play, or None when stock is not a valid control: each of
    stock's notes must be a note of a three-note chord, taken UP, plus its step's
    offset in semitones. A step in MARKS plays stock's note."""
    held = [note - OFFS[k % 16] for k, note in stock_played]
    chord = sorted(set(held))
    if len(chord) != len(CHORD) + 1 or any(h != chord[k % len(chord)]
                                           for h, (k, _) in zip(held, stock_played)):
        return None
    if case[-1]:
        return [note for _, note in stock_played]
    _toggle, hs, hr, _hm, switch, ts, tr, _tm, _ = case
    scale = ts if switch & 4 else hs
    root = tr if switch & 2 else hr
    return [note if marks >> (k % 16) & 1 else reference(h, OFFS[k % 16], tables[scale], root)
            for h, (k, note) in zip(held, stock_played)]


def check(name: str, case: tuple, images: dict, places: dict, tables, source: Source) -> bool:
    """Play CASE on stock and on the build, print both, and compare the build with the rule."""
    def setup(who: str) -> list[str]:
        lo, first_sound = places[who][:2]
        out = pokes(lo, first_sound, case, ARP_TRACK[source], CASE_MARKS.get(name, 0))
        return (out + layer_pokes(lo, first_sound)) if source == "layered" else out

    played = {who: run(images[who], setup(who), source)[0] for who in images}
    built = [note for _, note in played["build"]]
    print(f"\n{name}: stock  {[note for _, note in played['stock']]}")
    print(f"{' ' * len(name)}  build  {built}")
    want = expected(case, played["stock"], tables, CASE_MARKS.get(name, 0))
    if want is None:
        print("  FAIL  stock's notes are not the chord plus the offsets in semitones")
        return False
    print(f"{' ' * len(name)}  want   {want}")
    steps = {k % 16 for k, _ in played["stock"]}
    ok = built == want and len(steps) >= 12
    print(f"  {'ok  ' if ok else 'FAIL'}  {len(built)} notes over {len(steps)} of the 16 offsets")
    return ok


def tap(code: int) -> list[str]:
    return [f"tap:{code}", "wait:30M"]


def with_func(code: int) -> list[str]:
    return [f"press:{sp.FUNC}", "wait:10M", f"tap:{code}", f"release:{sp.FUNC}", "wait:40M"]


def drive(image: pathlib.Path, steps: list[str], out: pathlib.Path | None = None) -> list[dict]:
    """Boot IMAGE to its main screen, run STEPS, -> the peeks and frames, in order."""
    cmd = [str(sp.panel_drive()), str(image), "--ssi-hz", "96000",
           "--steps", ",".join(["wait:1500M", f"tap:{sp.NO}", "wait:60M"] + steps)]
    if out:
        cmd += ["--out", str(out)]
    done = subprocess.run(cmd, capture_output=True, text=True, timeout=1500)
    result = json.loads(done.stdout)
    if result["outcome"] != "done":
        raise SystemExit(f"{image.name}: fault {result['fault']}")
    return result["results"]


def words(results: list[dict]) -> list[int]:
    return [int(r["hex"], 16) for r in results if "peek" in r]


def arp_menu(sound: int, *, toggle: int, marks: int, length: int = 16, mask: int = 0xFFFF) -> list[str]:
    """Track 1's arp as the step checks start it, and its ARPEGGIATOR menu open."""
    return [f"poke:{sound + OFFSETS:#x}:" + bytes(o & 0xFF for o in OFFS).hex(),
            f"poke:{sound + ARP_LEN:#x}:{length - 1:02x}{mask:04x}",
            f"poke:{sound + bs.MARKS:#x}:{marks:04x}",
            f"poke:{bs.FLAG:#x}:{toggle:02x}", f"tap:{ARP}", "wait:40M"]


def verdict(name: str, ok: bool, detail: str) -> bool:
    print(f"\n{name}: {detail}\n  {'ok  ' if ok else 'FAIL'}")
    return ok


def check_keys(images: dict, places: dict) -> bool:
    """[UP]/[DOWN] on step 3: (toggle, key, the mask and the marks expected after it)."""
    step = 2
    presses = [(1, UP, 1, 1), (1, UP, 1, 1), (1, DOWN, 1, 0), (1, DOWN, 0, 0), (1, UP, 1, 0),
               (1, UP, 1, 1), (0, DOWN, 0, 0), (0, UP, 1, 0), (0, UP, 1, 0)]
    sound = places["build"][1]
    look = [f"peek:{sound + ARP_MASK:#x}:2", f"peek:{sound + bs.MARKS:#x}:2"]
    steps = arp_menu(sound, toggle=1, marks=0) + tap(RIGHT) + tap(RIGHT)
    for toggle, key, _, _ in presses:
        steps += [f"poke:{bs.FLAG:#x}:{toggle:02x}"] + tap(key) + look
    found = words(drive(images["build"], steps))
    got = list(zip(found[0::2], found[1::2]))
    want = [(0xFFFF & ~((not on) << step), marked << step) for _, _, on, marked in presses]
    return verdict("step-keys", got == want, "(mask, marks) after each press\n"
                   f"  got  {[(hex(m), hex(k)) for m, k in got]}\n  want {[(hex(m), hex(k)) for m, k in want]}")


def frame(path: str) -> list[list[int]]:
    rows = pathlib.Path(path).read_text().split("\n")[2:66]
    return [[int(v) for v in row.split()] for row in rows]


def screens(images: dict, places: dict, marks: int, out: pathlib.Path) -> dict[str, list[list[int]]]:
    """Each image's ARPEGGIATOR menu with MARKS and step 2 selected, toggle on ('who-on'),
    then toggle off ('who-off')"""
    shots = {}
    for who in images:
        steps = (arp_menu(places[who][1], toggle=1, marks=marks) + tap(RIGHT)
                 + [f"frame:{who}-on", f"poke:{bs.FLAG:#x}:00"] + tap(RIGHT) + tap(LEFT)
                 + [f"frame:{who}-off"])
        shots |= {pathlib.Path(r["frame"]).stem: frame(r["frame"])
                  for r in drive(images[who], steps, out) if "frame" in r}
    return shots


def plus_drawn(on: list[list[int]], diff: set, step: int, half: int) -> tuple[bool, set]:
    """-> (whether STEP's box, 2 x HALF + 1 wide, holds exactly a plus in ON, the
    differing pixels in it)"""
    cx = GRAPH_X + GRAPH_STEP * step
    mine = {(x, y) for x, y in diff if abs(x - cx) <= half}
    ys = sorted(y for _, y in mine)
    if not ys or ys[-1] - ys[0] != 2 * half:
        return False, mine
    cy = ys[0] + half
    span = range(-half, half + 1)
    lit = {(cx + dx, cy + dy) for dx in span for dy in span if on[cy + dy][cx + dx]}
    plus = {(cx + d, cy) for d in span} | {(cx, cy + d) for d in span}
    return lit == plus, mine


def check_graph(images: dict, places: dict, out: pathlib.Path) -> bool:
    """Steps 2 (selected, a 5 x 5 box) and 13 (3 x 3) marked; toggle on, then off."""
    marked = {1: 2, 12: 1}              # step -> its box's half-width
    shots = screens(images, places, sum(1 << s for s in marked), out)
    off_same = shots["build-off"] == shots["stock-off"]
    on, base = shots["build-on"], shots["stock-on"]
    diff = {(x, y) for y in range(64) for x in range(128) if on[y][x] != base[y][x]}
    found = [plus_drawn(on, diff, s, h) for s, h in marked.items()]
    boxes_ok = all(drawn for drawn, _ in found)
    claimed = set().union(*(mine for _, mine in found))
    ok = off_same and boxes_ok and claimed == diff
    return verdict("step-graph", ok, f"toggle off equal to stock: {off_same}; toggle on: "
                   f"{len(diff)} pixels differ, {len(diff - claimed)} outside the marked boxes, "
                   f"a plus in each box: {boxes_ok} (frames in {out})")


def rotated(marks: int, length: int, left: bool) -> int:
    """The marks after a rotate, as stock moves the mask: within LENGTH, the rest kept."""
    inside = (1 << length) - 1
    m = marks & inside
    if left:
        m = (m >> 1) | ((m & 1) << (length - 1))
    else:
        m = ((m << 1) & inside) | (m >> (length - 1))
    return (marks & ~inside) | m


def check_rotate(images: dict, places: dict) -> bool:
    """LEN 8 with steps 1 and 4 marked and one mark past LEN: [FUNC] + [LEFT], then
    [FUNC] + [RIGHT] twice. The mask is stock's (the control), the marks the model's."""
    length, mask, marks = 8, 0xFF5D, (1 << 0) | (1 << 3) | (1 << 12)
    found = {}
    for who in images:
        sound = places[who][1]
        look = [f"peek:{sound + ARP_MASK:#x}:2", f"peek:{sound + bs.MARKS:#x}:2"]
        steps = (arp_menu(sound, toggle=1, marks=marks, length=length, mask=mask)
                 + with_func(LEFT) + look + with_func(RIGHT) + with_func(RIGHT) + look)
        found[who] = words(drive(images[who], steps))
    once = rotated(marks, length, left=True)
    want_marks = [once, rotated(rotated(once, length, left=False), length, left=False)]
    masks_moved = found["stock"][0] != mask and found["build"][0::2] == found["stock"][0::2]
    ok = masks_moved and found["build"][1::2] == want_marks
    return verdict("step-rotate", ok, f"masks stock {[hex(m) for m in found['stock'][0::2]]} "
                   f"build {[hex(m) for m in found['build'][0::2]]}; marks "
                   f"{[hex(m) for m in found['build'][1::2]]}, want {[hex(m) for m in want_marks]}")


def check_clipboard(images: dict, places: dict) -> bool:
    """Copy on track 1, paste on track 2, paste again (its undo); clear on track 1,
    clear again (its undo). The offsets must be stock's at each point."""
    t1_marks, t2_marks = 0x0012, 0x0300
    found = {}
    for who in images:
        one = places[who][1]
        two = one + SOUND_STRIDE
        look = [f"peek:{one + OFFSETS:#x}:16", f"peek:{one + bs.MARKS:#x}:2",
                f"peek:{two + OFFSETS:#x}:16", f"peek:{two + bs.MARKS:#x}:2"]
        steps = (arp_menu(one, toggle=1, marks=t1_marks) + [f"poke:{two + bs.MARKS:#x}:{t2_marks:04x}"]
                 + with_func(RECORD) + tap(sp.TRIG1 + 1) + with_func(STOP) + look + with_func(STOP) + look
                 + tap(sp.TRIG1) + with_func(PLAY) + look + with_func(PLAY) + look)
        found[who] = words(drive(images[who], steps))
    offs, zero = int(bytes(o & 0xFF for o in OFFS).hex(), 16), 0
    stock_offsets = [found["stock"][k] for k in range(len(found["stock"])) if k % 2 == 0]
    # after: paste (t1, t2), its undo, clear, its undo: the offsets of tracks 1 and 2
    want_stock = [offs, offs, offs, zero, zero, zero, offs, zero]
    build_offsets = [found["build"][k] for k in range(len(found["build"])) if k % 2 == 0]
    marks = [found["build"][k] for k in range(len(found["build"])) if k % 2 == 1]
    want_marks = [t1_marks, t1_marks, t1_marks, t2_marks, 0, t2_marks, t1_marks, t2_marks]
    ok = stock_offsets == want_stock and build_offsets == stock_offsets and marks == want_marks
    return verdict("step-clipboard", ok, f"stock's offsets as expected: {stock_offsets == want_stock}, "
                   f"the build's equal to stock's: {build_offsets == stock_offsets}; marks "
                   f"{[hex(m) for m in marks]}, want {[hex(m) for m in want_marks]}")


def check_store(images: dict, places: dict) -> bool:
    """Marks on track 1, a temporary save, the marks changed, the reload."""
    saved, later = 0xA5A5, 0x0001
    found = {}
    for who in images:
        sound = places[who][1]
        look = [f"peek:{sound + bs.MARKS:#x}:2"]
        steps = ([f"poke:{sound + bs.MARKS:#x}:{saved:04x}"] + with_func(YES) + ["wait:100M"]
                 + [f"poke:{sound + bs.MARKS:#x}:{later:04x}"] + look + with_func(sp.NO) + ["wait:100M"] + look)
        found[who] = words(drive(images[who], steps))
    ok = found["build"] == [later, saved] and found["stock"] == [later, 0]
    return verdict("step-store", ok, f"slot 100 before and after the reload: build "
                   f"{[hex(m) for m in found['build']]} (want {[hex(later), hex(saved)]}), stock "
                   f"{[hex(m) for m in found['stock']]} (want {[hex(later), '0x0']})")


CHECKS = {"step-keys": check_keys, "step-graph": check_graph, "step-rotate": check_rotate,
          "step-clipboard": check_clipboard, "step-store": check_store}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("build", type=pathlib.Path)
    ap.add_argument("--stock", type=pathlib.Path, default=STOCK)
    ap.add_argument("--case", action="append", choices=list(RUNS) + list(CHECKS))
    ap.add_argument("--frames", type=pathlib.Path, default=ROOT / "out/emu-arpscale",
                    help="where step-graph writes its screens")
    a = ap.parse_args()
    tables = sd.scales(load(read_image(a.stock)).container.find(bs.MAIN_OS).unpack())

    images = {"stock": a.stock, "build": a.build}
    places = {who: addresses(image) for who, image in images.items()}
    for who, (lo, sound, switch) in places.items():
        print(f"{who}: playback copy {lo:#010x}, first sound {sound:#010x}, switch {switch:#04x}")

    chosen = a.case or list(RUNS) + list(CHECKS)
    failures = sum(not check(name, CASES[RUNS[name][0]], images, places, tables, RUNS[name][1])
                   for name in chosen if name in RUNS)
    a.frames.mkdir(parents=True, exist_ok=True)
    failures += sum(not (CHECKS[name](images, places, a.frames) if name == "step-graph"
                         else CHECKS[name](images, places))
                    for name in chosen if name in CHECKS)
    print(f"\n{failures} failing case(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())

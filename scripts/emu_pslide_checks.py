"""The checks of `scripts/emu_pslide.py`: a case's frames on the build against stock's, its step
flags and the counts it asked for. The cases, their keys and what each shows are in that script's
docstring.
"""

from __future__ import annotations

import dataclasses
import pathlib
import sys
from typing import Callable

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "src")]

from dnfw import seqframes as SF  # noqa: E402
from dnfw.waverider.frame import slot_offset  # noqa: E402

SLOT_A, SLOT_B = 71, 72              # the FLTR page's knobs A and B on the default sound (ATK, DEC)
SLOT_ALGO = 25                       # the SYN page's knob A on FM TONE (ALGO), which does not slide
FLTR_SLOTS = (71, 72, 73, 74, 67, 68, 66, 69)   # FLTR page 1's knobs A to H
NEXT = 7                             # SLD's last value; knob E is turned one unit past it
SLD_BITS = 0x0068
STEP = 187.5                         # audio frames a step at 120 BPM (1,500 frames a second)
FRAME_BYTES = 2688                   # the whole frame (dnfw.waverider.frame)
SETTLED = 60                         # frames after which stock's smoother has reached a jump's target
HOLD = 50                            # frames a slide must stay on its target after it arrives
LIST_FREED = 0x401389CA              # the list release's free: the list's count reached 0
APPLIER = 0x400DB092                 # the lock applier's entry (arpplocks hooks it)
LISTED = 0x40026C2A                  # the note path's applier call: the note's trig has a lock list
END_POKE = 0x0800                    # the target a knob-like write sets in a slide's last frame (knob-end)


# ---- runs ----

@dataclasses.dataclass
class Run:
    outcome: str
    faults: list[int]
    frames: list[bytes]
    peeks: list[bytes]
    counts: dict[int, int]
    icounts: list[int] = dataclasses.field(default_factory=list)    # each captured frame's instruction count
    peek_at: list[int] = dataclasses.field(default_factory=list)    # each peek's instruction count
    regs: list[tuple[int, list[int]]] = dataclasses.field(default_factory=list)   # (pc, D0-D7) at each logged hit
    regs_dropped: int = 0        # hits past panel_drive's log
    screens: list[list[list[int]]] = dataclasses.field(default_factory=list)   # each frame: step's 64 rows of 128 pixels

    def __post_init__(self):
        self.notes = []                  # (frame from the first note, mask), a note a run of one mask
        last = 0
        for i, f in enumerate(self.frames):
            mask = int.from_bytes(f[SF.NOTE_ON:SF.NOTE_ON + 2], "big") if len(f) > SF.NOTE_ON + 1 else 0
            if mask and mask != last:
                self.notes.append((i, mask))
            last = mask
        self.first = self.notes[0][0] if self.notes else 0
        self.notes = [(i - self.first, m) for i, m in self.notes]

    def note(self, n: int) -> tuple[int, int]:
        """The Nth note: (its frame, its first voice)"""
        frame, mask = self.notes[n]
        return frame, (mask & -mask).bit_length() - 1

    def voices(self, n: int) -> list[int]:
        return [v for v in range(16) if self.notes[n][1] >> v & 1]

    def series(self, voice: int, slot: int) -> list[int]:
        at = slot_offset(voice, slot)
        if at + 2 > FRAME_BYTES:
            raise ValueError(f"voice {voice} slot {slot} is past the {FRAME_BYTES} bytes captured")
        return [int.from_bytes(f[at:at + 2], "big") for f in self.frames[self.first:]]

    def value(self, frame: int, voice: int, slot: int = SLOT_A) -> int:
        return self.series(voice, slot)[frame]

    def word(self, peek: int, step: int) -> int:
        return int.from_bytes(self.peeks[peek][2 * (step - 1):2 * step], "big")


def screen(pbm: pathlib.Path) -> list[list[int]]:
    """panel_drive's `frame:` file (P1, 128 x 64) as 64 rows of 128 pixels, 1 lit"""
    bits = pbm.read_text().split("\n", 2)[2].split()
    return [[int(bits[128 * y + x]) for x in range(128)] for y in range(64)]


# ---- checks ----

def sld(word: int) -> int:
    return (word >> 3 & 1) | (word >> 4 & 6)


def glides(run: Run, voice: int, slot: int, start: int, length: float, a: int, b: int, what: str,
           lag: int = 0) -> list[str]:
    """VOICE's SLOT reads A in frame START, follows the line to B, reaches B within a frame and a
    half of START + LENGTH (a start in that frame moves no slide) and stays. LAG: frames a slide
    may trail the line by when it moves every second or fourth frame."""
    s = run.series(voice, slot)
    tolerance = max(2, abs(b - a) // 512) + abs(b - a) * lag / length
    for k in range(start, min(start + int(length), len(s))):
        line = a + (b - a) * (k - start) / length
        if abs(s[k] - line) > tolerance:
            return [f"{what}: frame {k} reads {s[k]}, the line {line:.0f}"]
    arrive = next((k for k in range(start, len(s)) if s[k] == b), None)
    if arrive is None:
        return [f"{what}: never reaches {b}"]
    out = []
    if abs(arrive - (start + length)) > 1.5 + lag:
        out.append(f"{what}: reaches {b} in frame {arrive}, not {start + length:.0f}")
    if any(v != b for v in s[arrive:arrive + HOLD]):
        out.append(f"{what}: leaves {b} after frame {arrive}")
    return out


def jumps(run: Run, voice: int, slot: int, frame: int, b: int, what: str) -> list[str]:
    return [] if b in run.series(voice, slot)[frame:frame + 2] else [f"{what}: does not jump to {b} in frame {frame}"]


def ends(run: Run) -> tuple[int, int]:
    """(stock's value before step 5, step 5's lock): step 1's voice and step 5's voice"""
    (_, v1), (k5, v5) = run.note(0), run.note(1)
    return run.value(1, v1), run.value(k5 + 1, v5)


def check_length(steps: float) -> Callable:
    def check(b: Run, s: Run) -> list[str]:
        a, target = ends(s)
        k, v = b.note(1)
        return glides(b, v, SLOT_A, k, steps * STEP, a, target, "step 5") + jumps(s, s.note(1)[1], SLOT_A,
                                                                                  s.note(1)[0], target, "stock")
    return check


def check_return(b: Run, s: Run) -> list[str]:
    _, target = ends(s)
    k9, v9 = s.note(2)
    sound = s.value(k9 + 1, v9)
    k, v = b.note(2)
    return glides(b, v, SLOT_A, k, STEP, target, sound, "step 9") + ([] if sound != target else ["no return"])


def check_next(b: Run, s: Run) -> list[str]:
    a, target = ends(s)
    k5, v5 = b.note(1)
    return (glides(b, b.note(0)[1], SLOT_A, 0, k5, a, target, "step 1")
            + ([] if abs(k5 - 4 * STEP) <= 1 else [f"step 5 plays in frame {k5}"]))


def check_next_track_2(b: Run, s: Run) -> list[str]:
    """Track 2: step 1 NEXT glides to step 5's lock, which the lock records of track 2 give"""
    return check_next(b, s)


def check_speed(b: Run, s: Run) -> list[str]:
    """Track 2 at 2x in per-track mode: step 5 plays two 1x steps in, and its 4-step slide takes two
    1x steps"""
    k, v = b.note(1)
    out = [] if abs(k - 2 * STEP) <= 2 else [f"step 5 plays in frame {k}: the speed did not take"]
    a, target = ends(s)
    return out + glides(b, v, SLOT_A, k, 2 * STEP, a, target, "step 5 at 2x")


def check_preview_off(b: Run, s: Run) -> list[str]:
    """Step 1's SLD turned up and back to OFF while stopped (the second peek): step 1's lock jumps as
    on stock from the first note"""
    if sld(b.word(0, 1)) == 0 or sld(b.word(1, 1)) != 0:
        return [f"setup: step 1's SLD {sld(b.word(0, 1))} then {sld(b.word(1, 1))}, not up then OFF"]
    _, v = b.note(0)
    return as_stock_from(b, s, v, SLOT_A, -2, "step 1")


def check_locktrig_off(b: Run, s: Run) -> list[str]:
    """Step 1 slides knobs A and B over 16 steps. A lock trig on step 5 without SLD locks knob A: from
    it, knob A is stock's (the slide no longer writes it), and knob B goes on on its line"""
    _, v = b.note(0)
    at = round(4 * STEP)
    return (as_stock_from(b, s, v, SLOT_A, at, "knob A after the lock trig")
            + on_line_until(b, v, SLOT_B, 0, round(15 * STEP), 16 * STEP, b.value(0, v, SLOT_B),
                            s.value(2, v, SLOT_B), "step 1, knob B"))


def check_next_preset(b: Run, s: Run) -> list[str]:
    """Step 5 NEXT with a preset lock of another machine: its values change at once, as stock's"""
    k, v = b.note(1)
    return as_stock_from(b, s, v, SLOT_A, k, "step 5")


def check_next_preset_same(b: Run, s: Run) -> list[str]:
    """Step 5 NEXT with a preset lock of the same machine: it glides from its lock to step 9's"""
    (k5, v5), (k9, v9) = s.note(1), s.note(2)
    a, target = s.value(k5 + 1, v5), s.value(k9 + 1, v9)
    k, v = b.note(1)
    return glides(b, v, SLOT_A, k, b.note(2)[0] - k, a, target, "step 5")


def check_locktrig_preset(b: Run, s: Run) -> list[str]:
    """Step 1 plays a preset lock of another machine. On its voice, the lock trig on step 5 with SLD
    changes knob A at once, as stock's"""
    _, v = b.note(0)
    return as_stock_from(b, s, v, SLOT_A, round(4 * STEP), "the lock trig on step 1's voice")


def check_knob_end(b: Run, s: Run) -> list[str]:
    """Step 5's 4-step slide, its voice's target written (as a knob writes it) between its last update
    and its arrival: the value leaves the slide and goes to the written target, not the lock"""
    _, target = ends(s)
    k, v = b.note(1)
    after = b.series(v, SLOT_A)[round(k + 4 * STEP) + 2:round(k + 4 * STEP) + 200]
    if target in after:
        return [f"it reaches the lock {target} after the write"]
    # stock's smoother takes the value toward the written target over many frames
    return [] if abs(after[-1] - END_POKE) * 20 < abs(target - END_POKE) else [
        f"200 frames on it reads {after[-1]}, not near the written {END_POKE} (the lock {target})"]


SLD_LOCKED = (range(21, 46), range(39, 58))    # stock's locked look around SLD's box: 3 pixels each side, 1 above and below


def locked_look(frame: list[list[int]]) -> bool:
    """SLD's box drawn as stock draws a locked value: the rows above and below it lit across"""
    xs, ys = SLD_LOCKED
    return all(frame[y][x] for y in (ys[0], ys[-1]) for x in xs)


def check_push(b: Run, s: Run) -> list[str]:
    """SLD 4 on steps 1 and 9. [TRIG 9] held: SLD's box looks locked; knob E's push keeps both;
    its release sets step 9's SLD to OFF and the box looks plain. Then knob C's push and knob F's
    (no parameter) with [TRIG 1] held, knob E's with nothing held, and knob E's on a SYN page with no
    parameter at E with [TRIG 1] held keep step 1's SLD"""
    got = [(sld(b.word(i, 1)), sld(b.word(i, 9))) for i in range(1, 7)]
    want = [(4, 4), (4, 0)] + [(4, 0)] * 4
    out = [] if got == want else [f"SLD of steps 1 and 9 after each push: {got}, not {want}"]
    if [locked_look(f) for f in b.screens] != [True, False]:
        out.append(f"SLD's box looks locked in {[locked_look(f) for f in b.screens]}, not [True, False]")
    return out


def check_unheld(b: Run, s: Run) -> list[str]:
    """Knob E turned with no trig held, then a part of a unit with step 1 held: SLD stays OFF"""
    return [] if sld(b.word(-1, 1)) == 0 == sld(s.word(-1, 1)) else [
        f"step 1's SLD {sld(b.word(-1, 1))} after the turns, stock {sld(s.word(-1, 1))}"]


def check_same_notes(b: Run, s: Run) -> list[str]:
    """The notes (frames and voices) are stock's, and there are some"""
    if not s.notes:
        return ["stock plays no note"]
    return [] if b.notes == s.notes else [f"{len(b.notes)} notes on the build, {len(s.notes)} on stock"]


def check_stop_first(b: Run, s: Run) -> list[str]:
    """Step 1 with SLD 4 and a lock and step 5 play, then STOP, then PLAY: the third note is the
    restart's step 1 (off the first pass's grid), and it glides from the value before it to its
    lock over 4 steps"""
    if len(b.notes) < 3 or b.notes[:3] != s.notes[:3]:
        return [f"the first notes differ from stock's: {b.notes[:3]}, {s.notes[:3]}"]
    k, v = b.note(2)
    if abs(k / (4 * STEP) - round(k / (4 * STEP))) < 0.05:
        return [f"the third note (frame {k}) is on the first pass's grid: no restart"]
    sk, sv = s.note(2)
    return glides(b, v, SLOT_A, k, 4 * STEP, b.value(k, v), s.value(sk + 1, sv), "the restart's step 1")


def raw_series(run: Run, voice: int, slot: int) -> list[int]:
    """VOICE's SLOT in every captured frame, before the first note too"""
    at = slot_offset(voice, slot)
    return [int.from_bytes(f[at:at + 2], "big") for f in run.frames]


def check_locktrig_first(b: Run, s: Run) -> list[str]:
    """A lock trig on step 1, the first step played from STOP, locks knob A with SLD 4: from the
    frame stock jumps in, voice 5 (which step 2's note does not take) follows the line to stock's
    lock over 4 steps. The captures of the two runs are frame for frame the same until then"""
    mine, theirs = raw_series(b, 5, SLOT_A), raw_series(s, 5, SLOT_A)
    jump = next((f for f in range(1, len(theirs)) if theirs[f] != theirs[f - 1]), None)
    if jump is None:
        return ["stock's lock trig does not change voice 5"]
    a, target = theirs[jump - 1], theirs[jump + SETTLED]
    tolerance = max(2, abs(target - a) // 512)
    for f in range(jump, jump + round(4 * STEP)):
        line = a + (target - a) * (f - jump) / (4 * STEP)
        if abs(mine[f] - line) > tolerance:
            return [f"voice 5: frame {f - jump} of the slide reads {mine[f]}, the line {line:.0f}"]
    return [] if target in mine[jump + round(4 * STEP) - 2:jump + round(4 * STEP) + 3] else ["voice 5 does not reach the lock"]


def check_next_track_length(b: Run, s: Run) -> list[str]:
    """Per-track mode, track 1's length 8: step 5 NEXT glides from its locks to step 1's values, the
    sound's, and arrives as step 1 plays again, 8 steps after the first"""
    if len(s.notes) < 3 or abs(s.notes[2][0] - 8 * STEP) > 1:
        return [f"stock's notes {s.notes[:3]}: the track's length 8 did not take"]
    (k5, v5), (k1, v1) = s.note(1), s.note(2)
    out = []
    for slot in (SLOT_A, SLOT_B):
        out += glides(b, b.note(1)[1], slot, b.note(1)[0], k1 - k5, s.value(k5 + 1, v5, slot),
                      s.value(k1 + 1, v1, slot), f"step 5, slot {slot}")
    return out


def check_next_alone(b: Run, s: Run) -> list[str]:
    """Step 1 NEXT and no other trig: the next trig is step 1 itself, a cycle on, so its lock stays"""
    _, v = b.note(0)
    return as_stock_from(b, s, v, SLOT_A, -2, "step 1")


def check_frames_stock(b: Run, s: Run) -> list[str]:
    """No trig has SLD: the frames are stock's"""
    n = min(len(b.frames) - b.first, len(s.frames) - s.first)
    differ = [i for i in range(n) if b.frames[b.first + i] != s.frames[s.first + i]]
    return [] if n > 1000 and not differ else [f"{len(differ)} of {n} frames differ from stock's, the first {differ[:1]}"]


def check_other_track(b: Run, s: Run) -> list[str]:
    """Track 2's step 1 slides knob A over 16 steps. A lock trig without SLD on track 1, which has no
    slide, leaves it on its line"""
    _, v = b.note(0)
    return on_line_until(b, v, SLOT_A, 0, round(15 * STEP), 16 * STEP, b.value(0, v), s.value(2, v), "track 2's step 1")


def check_locktrig_next(b: Run, s: Run) -> list[str]:
    """A lock trig on step 5 with NEXT locks knob B: step 1's voice takes the lock at once, then glides
    to step 9's lock and arrives as step 9 plays"""
    _, v = b.note(0)
    at = round(4 * STEP)
    k9, v9 = s.note(1)
    return glides(b, v, SLOT_B, at, k9 - at, s.value(at + 2, v, SLOT_B), s.value(k9 + 1, v9, SLOT_B),
                  "step 1's voice, knob B")


def check_next_micro(b: Run, s: Run) -> list[str]:
    """Step 1 NEXT, step 5 locked and a quarter step late by micro timing (rule 8): step 1 arrives at
    step 5's lock on step 5's grid time, before step 5's note"""
    a, target = ends(s)
    k5, _ = b.note(1)
    out = [] if k5 - 4 * STEP > STEP / 8 else [f"step 5 plays in frame {k5}: its micro timing did not take"]
    return out + glides(b, b.note(0)[1], SLOT_A, 0, 4 * STEP, a, target, "step 1")


def check_next_loop(steps: int, looped: bool) -> Callable:
    """Step 9 (the second note) glides from its lock to step 25's lock (the third note), or, with
    page 1 looped, to step 1's value (the first note's)"""
    def check(b: Run, s: Run) -> list[str]:
        k9, v9 = s.note(1)
        start = s.value(k9 + 1, v9)
        end = s.note(0) if looped else s.note(2)
        target = s.value(end[0] + 1, end[1])
        k, v = b.note(1)
        return glides(b, v, SLOT_A, k, steps * STEP, start, target, "step 9")
    return check


def leaves(b: Run, s: Run, voice: int | None = None) -> tuple[int | None, list[int], int, int]:
    """Step 5's 16-step slide on the build (knob, stop), on its first voice or VOICE: (the frame its
    value leaves the line, the series, the slide's end, the lock)"""
    a, target = ends(s)
    k, v = b.note(1)
    v = v if voice is None else voice
    series, length = b.series(v, SLOT_A), 16 * STEP
    tolerance = max(2, abs(target - a) // 512)
    leave = next((f for f in range(k, len(series))
                  if abs(series[f] - (a + (target - a) * (f - k) / length)) > tolerance), None)
    return leave, series, round(k + length), target


def check_knob(b: Run, s: Run, voice: int | None = None) -> list[str]:
    leave, series, end, target = leaves(b, s, voice)
    knob = b.series(b.note(0)[1], SLOT_A)[-1]     # step 1's voice: the knob's value, as stock writes it
    if leave is None or leave >= end:
        return ["the value stays on the slide"]
    if target in series[leave:] or series[-1] != knob:
        return [f"after frame {leave} it ends on {series[-1]}, the knob {knob}, the lock {target}"]
    return []


def check_knob_chord(b: Run, s: Run) -> list[str]:
    """Rule 1 on step 5's chord: each of its voices leaves the slide and ends on the knob's value"""
    voices = b.voices(1)
    out = [] if len(voices) == 3 else [f"step 5 plays {len(voices)} voices, not 3"]
    return out + [f"voice {v}: {p}" for v in voices for p in check_knob(b, s, v)]


def check_stop(b: Run, s: Run) -> list[str]:
    leave, series, end, _ = leaves(b, s)
    if leave is None or leave >= end:
        return ["the slide runs on after STOP"]
    moved = sorted(set(series[leave - 1:]))
    return [] if len(moved) == 1 else [f"after frame {leave} it moves: {moved[:4]}"]


def check_pattern(b: Run, s: Run) -> list[str]:
    """Step 9's 16-step slide: on the line until pattern 2 starts, 16 steps after the first note,
    and from that frame where the line was"""
    a, target = ends(s)
    k, v = b.note(1)
    series, start, tolerance = b.series(v, SLOT_A), round(16 * STEP), max(2, abs(target - a) // 512)
    line = a + (target - a) * (start - k) / (16 * STEP)
    out = [] if abs(series[start] - line) <= tolerance else [
        f"frame {start} (pattern 2's first) reads {series[start]}, the line {line:.0f}"]
    moved = sorted(set(series[start:]))
    return out + ([] if len(moved) == 1 else [f"it moves after frame {start}: {moved[:4]}"])


def check_tempo(b: Run, s: Run) -> list[str]:
    a, target = ends(s)
    k, v = b.note(1)
    series = b.series(v, SLOT_A)
    arrive = next((f for f in range(k, len(series)) if series[f] == target), None)
    if arrive is None:
        return ["never reaches the lock"]
    rate = int.from_bytes(b.peeks[-1][:4], "big")
    before = (series[k + 300] - series[k]) / 300
    after = (series[arrive - 1] - series[arrive - 301]) / 300
    want = before * rate / 14400
    out = [] if abs(after - want) <= 0.01 * before else [f"slope {after:.3f} after, {want:.3f} for the rate {rate}"]
    return out + ([] if arrive > k + 16 * STEP + 2 else [f"arrives in frame {arrive}, not later than 16 steps"])


def check_machine(slides: bool) -> Callable:
    def check(b: Run, s: Run) -> list[str]:
        a, target = ends(s)
        k, v = b.note(1)
        if slides:
            return glides(b, v, SLOT_A, k, 4 * STEP, a, target, "step 5, the same machine")
        return jumps(b, v, SLOT_A, k, target, "step 5, another machine")
    return check


def check_machine_chord(b: Run, s: Run) -> list[str]:
    """Each voice of step 5's chord, preset-locked to another machine, reads what stock's does"""
    voices = b.voices(1)
    out = [] if len(voices) == 3 else [f"step 5 plays {len(voices)} voices, not 3"]
    return out + [p for v in voices for p in as_stock_from(b, s, v, SLOT_A, b.note(1)[0] - 2, f"voice {v}")]


def check_joins(b: Run, s: Run) -> list[str]:
    """Retrig, chord and arp: every voice that starts during step 5's slide starts on its line and
    lands on the lock with it."""
    a, target = ends(s)
    k, _ = b.note(1)
    out, length = [], 4 * STEP
    later = [i for i, (frame, _) in enumerate(b.notes) if k <= frame < k + length]
    if len(later) < 2 and len(b.voices(1)) < 2:
        return ["no second voice joins"]
    for i in later:
        frame = b.notes[i][0]
        for v in b.voices(i):
            line = a + (target - a) * (frame - k) / length
            got = b.value(frame, v)
            if abs(got - line) > max(2, abs(target - a) // 512):
                out.append(f"voice {v} starts in frame {frame} on {got}, the line {line:.0f}")
            if b.value(round(k + length) + 2, v) != target:
                out.append(f"voice {v} is not on the lock after the slide")
    return out


def check_overlap(b: Run, s: Run) -> list[str]:
    (_, v1), (k5, v5) = s.note(0), s.note(1)
    lock1, lock5 = s.value(2, v1), s.value(k5 + 1, v5)
    (_, b1), (bk5, b5) = b.note(0), b.note(1)
    sound, reached = b.value(0, b1), b.value(bk5, b1)
    return (glides(b, b1, SLOT_A, 0, 16 * STEP, sound, lock1, "step 1")
            + glides(b, b5, SLOT_A, bk5, 4 * STEP, reached, lock5, "step 5"))


def check_locktrig(takes: bool) -> Callable:
    def check(b: Run, s: Run) -> list[str]:
        _, v1 = s.note(0)
        lock1 = s.value(2, v1)
        at = round(4 * STEP)
        _, b1 = b.note(0)
        sound = b.value(0, b1)
        if takes:
            lock = s.value(at + 2, v1)                   # stock: the lock trig's value on that voice
            reached = b.value(at, b1)
            return glides(b, b1, SLOT_A, at, STEP, reached, lock, "the lock trig on step 1's voice")
        out = glides(b, b1, SLOT_A, 0, 16 * STEP, sound, lock1, "step 1, knob A")
        for v in range(6):
            out += glides(b, v, SLOT_B, at, STEP, b.value(at, v, SLOT_B), s.value(at + 2, v, SLOT_B),
                          f"voice {v}, knob B")
        return out
    return check


def check_locktrig_chord(b: Run, s: Run) -> list[str]:
    """Step 1's chord slides knob A over 16 steps; the lock trig on step 5 locks knob A over a step:
    each chord voice glides from where the chord's slide was to the lock trig's value, and stays"""
    at, voices = round(4 * STEP), b.voices(0)
    out = [] if len(voices) == 3 else [f"step 1 plays {len(voices)} voices, not 3"]
    for v in voices:
        out += glides(b, v, SLOT_A, at, STEP, b.value(at, v), s.value(at + 2, v), f"the lock trig on chord voice {v}")
    return out


def check_arpplocks(b: Run, s: Run) -> list[str]:
    """arpplocks, against arpplocks alone: track 1's arp on UP plays step 1's long note, which slides
    FLTR knob A over 16 steps; the lock trig on step 5 locks the arp's MODE and slides knob B. The
    notes are the same (frame and voices), and so are arpplocks' track-1 arp state, the sound the
    ISR reads SPEED and N.LEN from, and the shadow sound with the arp lock (the last three peeks);
    step 1's voice is between its start and the lock two steps in"""
    out = []
    if b.notes != s.notes:
        at = next(i for i, (x, y) in enumerate(zip(b.notes + [None], s.notes + [None])) if x != y)
        out.append(f"note {at + 1} differs from arpplocks alone's: {b.notes[at:at + 1]}, {s.notes[at:at + 1]}")
    for i, what in ((-3, "the arp state"), (-2, "the arp's sound"), (-1, "the shadow")):
        if b.peeks[i] != s.peeks[i]:
            out.append(f"{what} differs from arpplocks alone's")
    _, v = b.note(0)
    start, lock, now = b.value(0, v), s.value(2, v), b.value(round(2 * STEP), v)
    return out + ([] if min(start, lock) < now < max(start, lock) else
                  [f"step 1's voice reads {now} two steps in, from {start} to the lock {lock}"])


def check_direct_jump(b: Run, s: Run) -> list[str]:
    """directjump on, pattern 2 (a trig on every step) cued in the PTN view during step 9's 16-step
    slide (rule 2): the notes are directjump alone's, and step 9's value is on the line until
    pattern 2's first note there and stays where it was from it (two frames' leeway, two steps)"""
    a, target = ends(s)
    k, v = b.note(1)
    starts = [f for f, _ in s.notes if f > k]
    if not starts or starts[0] > k + 16 * STEP:
        return [f"pattern 2 does not start during the slide on directjump alone ({starts[:1]})"]
    first = starts[0]
    out = [] if b.notes == s.notes else ["the notes differ from directjump alone's"]
    out += on_line_until(b, v, SLOT_A, k, first + 1, 16 * STEP, a, target, "step 9")
    still = sorted(set(b.series(v, SLOT_A)[first + 2:first + 2 + round(2 * STEP)]))
    return out + ([] if len(still) == 1 else [f"from pattern 2's first note (frame {first}) it moves: {still[:4]}"])


def carried() -> list[int]:
    """The slots the frame to the DSP carries"""
    out = []
    for slot in range(101):
        try:
            slot_offset(0, slot)
        except ValueError:
            continue
        out.append(slot)
    return out


def check_lfo4(b: Run, s: Run) -> list[str]:
    """lfo4, against lfo4 alone: track 1 on FM DRUM, LFO 4 aimed at TUNE (below the clamp), step 5
    locking TUNE (SYN knob A) with SLD 2. On step 5's voice the frames differ in one slot, by the line
    from the value before the lock to the lock less the lock, and by nothing once it arrives: LFO 4
    modulates the slid value as it modulates the lock. LFO 4 moves that slot in lfo4 alone's frames"""
    k, v = b.note(1)
    slots = [x for x in carried() if b.value(k + 100, v, x) != s.value(k + 100, v, x)]
    if len(slots) != 1:
        return [f"the frames differ in slots {slots} 100 frames into step 5's slide, not in one"]
    slot, length = slots[0], 2 * STEP
    mine, theirs = b.series(v, slot), s.series(v, slot)
    d = [x - y for x, y in zip(mine, theirs)]
    out = []
    # from SETTLED frames in: lfo4 alone's value has reached the lock through stock's smoother
    span = d[k + SETTLED] / (1 - SETTLED / length)      # (the value before the lock) - (the lock)
    tolerance = max(2, abs(span) // 256)
    for f in range(k + SETTLED, round(k + length) - 1):
        want = span * (1 - (f - k) / length)
        if abs(d[f] - want) > tolerance:
            out.append(f"frame {f}: the difference is {d[f]}, the line {want:.0f}")
            break
    end = round(k + length) + 2
    if any(d[end:end + HOLD]):
        out.append(f"after the slide the frames still differ from lfo4 alone's (slot {slot})")
    return out + ([] if len(set(theirs[end:end + 300])) > 1 else [f"LFO 4 does not move slot {slot} on lfo4 alone"])


def check_control(b: Run, s: Run) -> list[str]:
    """Peeks: step 1 +3 and step 5 +8 (NEXT is the last value); both held -1; knob E with no trig
    held; step 1 -5 (OFF is the first); knob E on TRIG PAGE 1 with step 5 held (stock's LFO.T); then
    48 steps, step 33 held on page 3, +2."""
    want = [(3, 7), (2, 6), (2, 6), (0, 6), (0, 6)]
    got = [(sld(b.word(i, 1)), sld(b.word(i, 5))) for i in range(5)]
    out = [] if got == want else [f"SLD of steps 1 and 5: {got}, not {want}"]
    out += [] if sld(b.word(5, 33)) == 2 else [f"step 33's SLD {sld(b.word(5, 33))}, not 2"]
    out += [f"stock's SLD of step {n}: {sld(s.word(i, n))}" for i in range(6) for n in (1, 5, 33) if sld(s.word(i, n))]
    others = [(b.word(i, n) & ~SLD_BITS, s.word(i, n) & ~SLD_BITS) for i in range(6) for n in (1, 5, 33)]
    return out + [f"other bits {x:#06x}, stock {y:#06x}" for x, y in others if x != y]


def on_line_until(b: Run, voice: int, slot: int, start: int, until: int, length: float, a: int, target: int,
                  what: str) -> list[str]:
    s, tolerance = b.series(voice, slot), max(2, abs(target - a) // 512)
    for k in range(start, until):
        line = a + (target - a) * (k - start) / length
        if abs(s[k] - line) > tolerance:
            return [f"{what}: frame {k} reads {s[k]}, the line {line:.0f}"]
    return []


def as_stock_from(b: Run, s: Run, voice: int, slot: int, frame: int, what: str) -> list[str]:
    """From FRAME on, VOICE's SLOT reads what stock's does: no slide writes it"""
    mine, theirs = b.series(voice, slot)[frame + 2:frame + 200], s.series(voice, slot)[frame + 2:frame + 200]
    return [] if mine == theirs else [f"{what}: from frame {frame} it reads {mine[:3]}..., stock {theirs[:3]}..."]


def check_mono(b: Run, s: Run) -> list[str]:
    """VOICES 1: step 5's note (no SLD) takes the voice of step 1's slide, which stops writing it"""
    (_, v), (k5, v5) = b.note(0), b.note(1)
    if v5 != v:
        return [f"step 5 plays on voice {v5}, not step 1's {v}"]
    a, lock1 = b.value(0, v), s.value(2, s.note(0)[1])
    return (on_line_until(b, v, SLOT_A, 0, k5, 16 * STEP, a, lock1, "step 1")
            + as_stock_from(b, s, v, SLOT_A, k5, "after step 5"))


def check_mono_locktrig(b: Run, s: Run) -> list[str]:
    """VOICES 1: step 9's note takes the voice of step 5's lock-trig slide, which stops writing it"""
    (_, v), (k9, v9) = b.note(0), b.note(1)
    at = round(4 * STEP)
    if v9 != v:
        return [f"step 9 plays on voice {v9}, not {v}"]
    a, lock = b.value(at, v, SLOT_B), s.value(at + 2, v, SLOT_B)
    return (on_line_until(b, v, SLOT_B, at, k9, 16 * STEP, a, lock, "the lock trig")
            + as_stock_from(b, s, v, SLOT_B, k9, "after step 9"))


def check_steal(b: Run, s: Run) -> list[str]:
    """Track 2's notes cycle through the voices: the one that takes step 1's voice stops its slide there"""
    (_, v), a, lock1 = b.note(0), b.value(0, b.note(0)[1]), s.value(2, s.note(0)[1])
    taken = next((frame for frame, mask in b.notes[1:] if mask >> v & 1 and frame < 16 * STEP), None)
    if taken is None:
        return [f"no note takes voice {v} during step 1's slide"]
    return (on_line_until(b, v, SLOT_A, 0, taken, 16 * STEP, a, lock1, "step 1")
            + as_stock_from(b, s, v, SLOT_A, taken, "after track 2 takes the voice"))


def check_takeover(b: Run, s: Run) -> list[str]:
    """Lock trigs on steps 2 to 9, each knob A over 16 steps: each takes the voices from the one
    before (whose slides end) and glides from where they were. Without the end, the pool runs out."""
    out = []
    for n in range(2, 10):
        at = round((n - 1) * STEP)
        for v in (0, 8, 15):
            start, lock = b.value(at, v), s.value(at + 2, v)
            out += on_line_until(b, v, SLOT_A, at, at + round(STEP), 16 * STEP, start, lock, f"step {n}, voice {v}")
    return out


def check_pool(b: Run, s: Run) -> list[str]:
    """Lock trigs on steps 2 to 8, each a different FLTR knob over 16 steps, 16 voices each: the
    pool (96) runs out during the seventh, whose knob jumps as on stock on the voices left without
    a slide; the first's slides go on on the line"""
    at8, knob, at2 = round(7 * STEP), FLTR_SLOTS[6], round(STEP)
    jumped = [v for v in range(16) if b.value(at8 + 2, v, knob) == s.value(at8 + 2, v, knob) != b.value(at8 - 3, v, knob)]
    out = [] if jumped else ["no voice of step 8 jumps: the pool did not run out"]
    return out + on_line_until(b, 0, FLTR_SLOTS[0], at2, round(15 * STEP), 16 * STEP, b.value(at2, 0),
                               s.value(at2 + 2, 0, FLTR_SLOTS[0]), "step 2, voice 0")


def check_conditions(b: Run, s: Run) -> list[str]:
    """Step 1 NEXT, steps 5 to 9 locked and LST on the build (they do not play): step 1 arrives at
    step 5's lock on step 5's frame (rule 7). The control plays the same steps without LST, so its
    step 5 gives the lock. Stock tests a trig's condition (0x400d8752) before it gives the trig a
    list, so steps 5 to 9, with SLD and LST, prepare no slide."""
    played = [frame for frame, _ in b.notes if 0 < frame < 16 * STEP]
    if played:
        return [f"the build plays notes at frames {played[:3]}: the LST trigs played"]
    k5, v5 = s.note(1)
    if abs(k5 - 4 * STEP) > 1:
        return [f"the control's step 5 plays in frame {k5}"]
    a, target = s.value(0, s.note(0)[1]), s.value(k5 + 1, v5)
    return glides(b, b.note(0)[1], SLOT_A, 0, 4 * STEP, a, target, "step 1") + ([] if target != a else ["no slide"])


def check_every_step(b: Run, s: Run) -> list[str]:
    """Each note of two passes: its voice, 195 frames on (its 1-step slide has arrived), reads the
    lock stock's same note jumped to"""
    if len(s.notes) < 32 or len(b.notes) < 32:
        return [f"{len(b.notes)} notes on the build, {len(s.notes)} on stock, not 32"]
    for n in range(32):
        (kb, vb), (ks, vs) = b.note(n), s.note(n)
        lock, got = s.value(ks + 2, vs), b.value(kb + 195, vb)
        if got != lock:
            return [f"note {n + 1} (frame {kb}, voice {vb}) reads {got} after its slide, stock's lock {lock}"]
    return []


def check_muted(b: Run, s: Run) -> list[str]:
    """Track 1 quick-muted ([FUNC] + [TRIG 1]) for 18 steps of trigs with SLD 1: each step's slide
    waits for a note that does not come, the places fill and the oldest goes. After the unmute the
    first note slides again: in its frame + 20 its value is between its start and stock's lock."""
    later = [(frame, mask) for (before, _), (frame, mask) in zip(b.notes, b.notes[1:]) if frame - before > 3 * STEP]
    if not later:
        return ["no note after a muted stretch"]
    frame, mask = later[0]
    v = (mask & -mask).bit_length() - 1
    start, now = b.value(frame, v), b.value(frame + 20, v)
    sframe, smask = next((f, m) for f, m in s.notes if f >= frame - 2)
    lock = s.value(sframe + 2, (smask & -smask).bit_length() - 1)
    return [] if min(start, lock) < now < max(start, lock) else [
        f"the first note after the unmute (frame {frame}) reads {start} then {now}, stock's lock {lock}"]


def check_stop_pending(b: Run, s: Run) -> list[str]:
    """STOP after step 5 is evaluated and before its note, then PLAY: step 1 plays as on stock (no
    slide of the stopped pass reaches it), and step 5 slides from stock's value before it to its lock"""
    restart = [i for i, ((before, _), (frame, _)) in enumerate(zip(b.notes, b.notes[1:]), 1) if frame - before > 3 * STEP]
    if not restart or len(b.notes) < restart[0] + 2:
        return ["no restart with steps 1 and 5"]
    (k1, v1), (k5, v5) = b.note(restart[0]), b.note(restart[0] + 1)
    out = [] if b.series(v1, SLOT_A)[k1:k1 + 300] == s.series(v1, SLOT_A)[k1:k1 + 300] else [
        f"the restart's step 1 (frame {k1}) differs from stock"]
    return out + glides(b, v5, SLOT_A, k5, 4 * STEP, b.value(k5, v5), s.value(k5 + 1, v5), "the restart's step 5")


def check_residual(b: Run, s: Run) -> list[str]:
    """Step 5 locks FLTR knob A and SYN knob A (ALGO, which does not slide): A glides, ALGO jumps as on stock"""
    k, v = b.note(1)
    sk, sv = s.note(1)
    out = check_length(4)(b, s)
    algo, before = s.value(sk + 1, sv, SLOT_ALGO), s.value(1, s.note(0)[1], SLOT_ALGO)
    if algo == before:
        out.append("stock's ALGO lock does not change the value")
    return out + ([] if b.value(k + 1, v, SLOT_ALGO) == algo else
                  [f"ALGO reads {b.value(k + 1, v, SLOT_ALGO)} after the note, stock {algo}"])


def check_dense(b: Run, s: Run) -> list[str]:
    """A lock trig on step 5 locking every knob of six pages, SLD 2, on 16 voices: its first frame
    counts over 1,024 writes, so slides move every fourth then every second frame, and each still lands"""
    at, out = round(4 * STEP), []
    for v in range(16):
        out += glides(b, v, SLOT_A, at, 2 * STEP, b.value(at, v), s.value(at + 2, v), f"voice {v}", lag=4)
        if b.value(at + 2, v, SLOT_ALGO) != s.value(at + 2, v, SLOT_ALGO):
            out.append(f"voice {v}: ALGO does not jump as on stock")
    return out


def check_clock_back(b: Run, s: Run) -> list[str]:
    """The clock poked back ten frames' worth during step 5's 16-step slide (as an external clock
    can move it): the slide waits, never moves back, and still lands"""
    a, target = ends(s)
    k, v = b.note(1)
    series = b.series(v, SLOT_A)
    back = [f for f in range(k, len(series) - 1) if series[f + 1] < series[f]]
    arrive = next((f for f in range(k, len(series)) if series[f] == target), None)
    return (([] if not back else [f"the value moves back at frame {back[0]}"])
            + ([] if arrive and arrive > k + 16 * STEP else [f"arrives in frame {arrive}"]))


# ---- the edits ----

def check_words(steps_carry: dict[int, int], same: tuple[int, ...] = ()) -> Callable:
    """STEPS_CARRY: step -> the SLD bits the build's word holds where stock's holds none; SAME: steps
    whose word is stock's. Every other bit is stock's. Reads the last peek."""
    def check(b: Run, s: Run) -> list[str]:
        out = []
        for step, bits in steps_carry.items():
            mine, theirs = b.word(-1, step), s.word(-1, step)
            if mine & SLD_BITS != bits or mine & ~SLD_BITS != theirs & ~SLD_BITS:
                out.append(f"step {step}: {mine:#06x}, stock {theirs:#06x}, want SLD bits {bits:#06x}")
        return out + [f"step {n}: {b.word(-1, n):#06x}, stock {s.word(-1, n):#06x}"
                      for n in same if b.word(-1, n) != s.word(-1, n)]
    return check


# ---- data stock reads (stock only) ----

def check_stock_plays(b: Run, s: Run) -> list[str]:
    """B is stock with SLD's bits poked on its trigs, S stock without: the bits are there, both play
    their notes, and the frames are the same."""
    out = [] if sld(b.word(1, 1)) == sld(b.word(1, 5)) == NEXT else ["the bits were not poked"]
    if len(b.notes) < 2 or len(s.notes) < 2:
        out.append(f"{len(b.notes)} notes with the bits, {len(s.notes)} without: not both steps")
    n = min(len(b.frames) - b.first, len(s.frames) - s.first)
    differ = [i for i in range(n) if b.frames[b.first + i] != s.frames[s.first + i]]
    return out + ([] if n > 2000 and not differ else [f"{len(differ)} of {n} frames differ, the first {differ[:1]}"])


def check_stock_reload(b: Run, s: Run) -> list[str]:
    """Peeks: seeded (step 1 0x03e9, step 5 0x0021), zeroed, reloaded"""
    words = [(b.word(i, 1), b.word(i, 5)) for i in range(3)]
    return [] if words == [(0x03E9, 0x0021), (0, 0), (0x03E9, 0x0021)] else [
        f"steps 1 and 5: {[(f'{x:#06x}', f'{y:#06x}') for x, y in words]}"]

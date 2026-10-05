"""The song position the ColdFire writes into every frame for MOVE's SYNC
(`csrc/waverider/sync.c`, M10b-2), frame by frame, in the same integer arithmetic.

The DSP turns it into a phase (`live.move_step`): 2^32 of the position is
`live.SYNC_LOOP` sixteenths, so every SYNC length's phase is the position times a
whole number. `docs/sequencer-playhead.md` has the step bytes this reads.

This module is pure: numbers in, numbers out.
"""

from __future__ import annotations

from dataclasses import dataclass

from .live import SYNC_LOOP

SIXTEENTH = 2_700_000            # tempo words (BPM x 120) summed over a sixteenth at 1500 frames a second
STOP_FRAMES = 8                  # both step bytes 0 this long: a STOP


def position(sixteenths: int, ticks: int) -> int:
    """The frame's u32 for SIXTEENTHS since PLAY (mod SYNC_LOOP) and TICKS of tempo
    summed since the last step, as sync.c forms it."""
    frac = min(min(ticks, SIXTEENTH - 1) * 1024 // 42188, 0xFFFF)
    x = (sixteenths % SYNC_LOOP) << 16 | frac
    return (170 * x + 2 * x // 3) & 0xFFFFFFFF


@dataclass
class SongPos:
    """sync.c's state, one `frame(now, next, tempo)` call per frame."""

    sixteenths: int = 0
    ticks: int = 0
    last_step: int = 0
    still: int = 0
    stops: int = 0
    steps: int = 0

    def frame(self, now: int, nxt: int, tempo: int) -> int:
        if now == 0 and nxt == 0:
            if self.still < STOP_FRAMES:
                self.still += 1
                if self.still == STOP_FRAMES:
                    self.stops += 1
                    self.sixteenths = 0
                    self.last_step = 0
            if self.still == STOP_FRAMES:
                self.ticks = 0
        else:
            self.still = 0
        if now != nxt and now != self.last_step:
            self.last_step = now
            self.steps += 1
            self.sixteenths = (self.sixteenths + 1) % SYNC_LOOP
            self.ticks = 0
        if self.still < STOP_FRAMES and self.ticks < SIXTEENTH:
            self.ticks += tempo & 0xFFFF
        self.ticks = min(self.ticks, SIXTEENTH - 1)
        return position(self.sixteenths, self.ticks)


def playing(frames: int, bpm: float, length: int = 16, start_frame: int = 0):
    """(now, next) step bytes for FRAMES frames of a pattern of LENGTH steps that starts
    playing at START_FRAME (stopped before it), at BPM: the sequencer's own steps."""
    per = 1500 * 60 / (4 * bpm)
    for f in range(frames):
        if f < start_frame:
            yield 0, 0
            continue
        s = int((f - start_frame) / per) % length
        yield s, (s + 1) % length

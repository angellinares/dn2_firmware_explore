"""The Formant type's filter, in the model: five resonators in cascade, as IIR0 will run them.

    cascade(position, shift) -> five biquads in IIR0's stored order (A0, A1, B1, A2, B2), float32
    level(position, shift)   -> the gain that makes every vowel as loud as A at no shift
    run(x, biquads, states)  -> one block through the cascade, in IIR0's float order (float32)

The owner chose the cascade form and the Formant type as IIR0's first job (2026-10-17,
docs/waverider-formant.md). Which knobs feed `position`, `shift` and the mix is still open, so
this module takes the three as numbers.

- `position` 0..4 runs through the vowels A, E, I, O, U, with a linear blend of each
  formant's frequency and bandwidth between two neighbours.
- `shift` is a frequency ratio for all five formants (1.0: the table's bass voice).
- Each resonator is Klatt's two-pole form, y = A x + B y[-1] + C y[-2] with A = 1 - B - C (a gain
  of 1 at 0 Hz). As an IIR0 biquad that is A0 = A, A1 = A2 = 0, B1 = B, B2 = C (B = -a).
- `run` uses the order measured on silicon (accelprobe1, ElekLabs/digikit#122): y = A0 x + s1,
  s1 = (A1 x + s2) + B1 y, s2 = A2 x + B2 y, each product and sum rounded to float32.
"""

from __future__ import annotations

import math
import struct

RATE = 48000
# vowel: (F1..F5 Hz, BW1..BW5 Hz), the published bass-voice values
VOWELS = (
    ("A", (600, 1040, 2250, 2450, 2750), (60, 70, 110, 120, 130)),
    ("E", (400, 1620, 2400, 2800, 3100), (40, 80, 100, 120, 120)),
    ("I", (250, 1750, 2600, 3050, 3340), (60, 90, 100, 120, 120)),
    ("O", (400, 750, 2400, 2600, 2900), (40, 80, 100, 120, 120)),
    ("U", (350, 600, 2400, 2675, 2950), (40, 80, 100, 120, 120)),
)
NYQUIST_GUARD = 0.45                     # no formant above 0.45 x the rate: a raised shift stops there
# The level evens out the vowels for a source whose spectrum falls about 6 dB an octave, as a
# Waverider oscillator's does: a leaky integrator, pole 0.99 (about 76 Hz), before the cascade.
# For white noise (no tilt) the five vowels spread 9.9 dB on Prim. at 110 Hz; with the tilt 2.3 dB.
LEVEL_TILT = 0.99


def _f32(x: float) -> float:
    return struct.unpack("<f", struct.pack("<f", x))[0]


def formants(position: float, shift: float = 1.0) -> tuple[tuple[float, ...], tuple[float, ...]]:
    """(F1..F5, BW1..BW5) at POSITION (0..4, A..U) with every frequency times SHIFT."""
    p = min(max(position, 0.0), len(VOWELS) - 1.0)
    i = min(int(p), len(VOWELS) - 2)
    f = p - i
    (_, fa, ba), (_, fb, bb) = VOWELS[i], VOWELS[i + 1]
    freqs = tuple(min((x + (y - x) * f) * shift, NYQUIST_GUARD * RATE) for x, y in zip(fa, fb))
    bws = tuple(x + (y - x) * f for x, y in zip(ba, bb))
    return freqs, bws


def resonator(freq: float, bw: float) -> tuple[float, float, float, float, float]:
    """One formant as an IIR0 biquad, float32: (A0, A1, B1, A2, B2). A0 comes from B and C as
    they are stored, so the gain at 0 Hz is 1 to float32's precision (a low formant's A0 is about
    0.003, and rounding the three apart left it 1.3e-5 off)."""
    c = _f32(-math.exp(-2 * math.pi * bw / RATE))
    b = _f32(2 * math.exp(-math.pi * bw / RATE) * math.cos(2 * math.pi * freq / RATE))
    return (_f32(1 - b - c), 0.0, b, 0.0, c)


def cascade(position: float, shift: float = 1.0) -> list[tuple[float, ...]]:
    freqs, bws = formants(position, shift)
    return [resonator(f, b) for f, b in zip(freqs, bws)]


def power_gain(biquads, n: int = 8192, tilt: float = LEVEL_TILT) -> float:
    """The cascade's power gain for a source tilted down by a leaky integrator (pole TILT; 0 is
    white noise): the energy of the tilted impulse response through the cascade (float64)."""
    y, acc = [], 0.0
    for k in range(n):
        acc = (1.0 if k == 0 else 0.0) + tilt * acc
        y.append(acc)
    for a0, _, b1, _, b2 in biquads:
        out, y1, y2 = [], 0.0, 0.0
        for v in y:
            o = a0 * v + b1 * y1 + b2 * y2
            out.append(o)
            y2, y1 = y1, o
        y = out
    return sum(v * v for v in y)


_REFERENCE = None


def level(position: float, shift: float = 1.0) -> float:
    """The gain, float32, that gives the cascade at POSITION and SHIFT the power gain of A at no
    shift (for LEVEL_TILT's source), so a sweep through the vowels keeps about one loudness."""
    global _REFERENCE
    if _REFERENCE is None:
        _REFERENCE = power_gain(cascade(0.0))
    return _f32(math.sqrt(_REFERENCE / power_gain(cascade(position, shift))))


# The vowel's glide: a p-lock or a fast LFO can move the position by up to 4 (A to U) between two
# blocks. With `level`, the loudness changes by under 2 dB either way. An instant jump from I to O
# leaves one waveform step 2.1 times the sound's 99th-percentile step (Prim. at 110 Hz); with the
# glide it is 0.7 times, as for the other jumps. The position moves toward the knob's by at most
# GLIDE_STEP a block, so A to U takes 32 blocks (21 ms). A note on the voice takes the knob's
# position at once, as TRIM's slew does (live.trim_slew).
GLIDE_STEP = 0.125


def glide(last: float | None, target: float, note_on: bool) -> float:
    """This block's position, from LAST (None before the first block) toward TARGET."""
    if last is None or note_on:
        return target
    return min(max(target, last - GLIDE_STEP), last + GLIDE_STEP)


def run(x: list[float], biquads, states: list[list[float]]) -> list[float]:
    """X (one block) through the cascade in IIR0's float order; STATES holds [s1, s2] per biquad
    (IIR0's stored words 5 and 6) and is updated in place, as Save State keeps them."""
    out = []
    for v in x:
        v = _f32(v)
        for (a0, a1, b1, a2, b2), s in zip(biquads, states):
            y = _f32(_f32(a0 * v) + s[0])
            s[0] = _f32(_f32(_f32(a1 * v) + s[1]) + _f32(b1 * y))
            s[1] = _f32(_f32(a2 * v) + _f32(b2 * y))
            v = y
        out.append(v)
    return out


# The Formant type on page 5 (owner, 2026-10-17: AMT is the vowel, so an LFO can sweep it; layout
# A on IIR0). The knobs' frame words (0..127 << 8):
#   AMT (slot 48): the vowel, 0..127 -> position 0..4 (A..U); the only LFO destination of the row
#   P1  (slot 64): the shift, 0..127 -> a ratio 2^(P1 / 127), 1.0 (the table's bass voice, a new
#                  sound's 0) to 2.0 (an octave up)
#   P2  (slot 63): the dry part, y = (1 - d) wet + d dry, d = P2 / 127: a new sound's 0 is fully
#                  filtered, so TYPE Formant is heard at once. This form is exact at both ends
#                  (0: the filtered sound, 127: the dry sound, bit for bit); wet + d (dry - wet)
#                  is not exact at 127.
KNOB_MAX = 0x7F00


def position_of(vowel_word: int) -> float:
    return 4.0 * (vowel_word & 0xFFFF) / KNOB_MAX


def shift_of(shift_word: int) -> float:
    return 2.0 ** ((shift_word & 0xFFFF) / KNOB_MAX)


def leveled(position: float, shift: float) -> list[tuple[float, ...]]:
    """The cascade with `level` folded into the first biquad's A0, as the DSP stores it: the gain
    costs no multiply."""
    bq = cascade(position, shift)
    a0, a1, b1, a2, b2 = bq[0]
    bq[0] = (_f32(a0 * level(position, shift)), a1, b1, a2, b2)
    return bq


class Voice:
    """One voice's Formant: the biquads' states (Save State), the glided vowel position."""

    def __init__(self):
        self.states = [[0.0, 0.0] for _ in range(len(VOWELS))]
        self.position = None

    def block(self, mix: list[float], vowel_word: int, shift_word: int, dry_word: int, note_on: bool) -> list[float]:
        """One block: AMT's VOWEL_WORD, P1's SHIFT_WORD, P2's DRY_WORD."""
        self.position = glide(self.position, position_of(vowel_word), note_on)
        wet = run(mix, leveled(self.position, shift_of(shift_word)), self.states)
        d = _f32((dry_word & 0xFFFF) / KNOB_MAX)
        e = _f32(1.0 - d)
        return [_f32(_f32(e * w) + _f32(d * m)) for m, w in zip(mix, wet)]

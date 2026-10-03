"""What Milestone 5's type-5 loop computes from a track's own state: the contract
`csrc/waverider/sharc/machine5_live.asm` is held to, bit for bit.

The loop reads three things the frame unpack `sw 0x1c2712` has already put in DSP
memory, measured by running that unpack (`scripts/sharc_waverider_m5.py`):

| what | where | form |
|---|---|---|
| SLOT, WaveTone's `TBL1` (param 27) | the frame copy `0x25c48c`, offset `222 + 146t` | 16-bit, the sound's value: 0x0000 or 0x0100 |
| POS, WaveTone's `WAV1` (param 26) | the frame copy, offset `220 + 146t` | 16-bit, the sound's value: 0..0x7800 |
| pitch | engine `+0x1387c + 4t` (`0x254b14 + 4t`) | float semitones, note + fine/256 |
| TUNE, WaveTone's `TUN1` (param 25, Milestone 6) | the frame copy, offset `218 + 146t` | 16-bit, the sound's value: word / 256 - 64 semitones |

The unpack writes a type-5 track's machine parameters nowhere else: its record's
machine window is left as it is (measured, the same for any parameter value), so
the loop reads the copy of the frame the unpack itself made.

and turns them into `reader_m5.asm`'s parameter block:

- **table**: the directory's entry for `TBL1 >> 8`; at or above the count plays 0;
- **pos**: `min(WAV1, 0x7800) << 5`, Q16 frames (0x7800 << 5 is frame 15);
- **inc**: from the note plus TUN1, through a 129-entry float32 table `T` of phase steps
  (`increment_table`): `k = trunc(n)`, `fr = n - k`, `inc = trunc(T[k] + fr *
  (T[k+1] - T[k]))`, every operation rounded to float32 in the loop's order;
- **phase**: carried in the block from one block to the next, from 0.

**The frame carries the sound's own values** (read on the instrument through the
USB probe, 2026-09-30, `tools/dn2probe_frame.py`): TUN1 `0x4000` at 0, `0x4100` at
+1, `0x4c00` at +12, `0x3400` at -12; WAV1 `0x7800` at the top; TBL1 `0x0100` at 1.
Until then this module, the loop and the gates read **half** the sound's value, as
frames from the ColdFire emulator had shown (FREQ 0x6117 -> 0x308c, WAV1 0x7800 ->
0x3c00, TBL1 0x0100 -> 0x0080). Those frames were taken while the values were still
gliding to their targets after the snapshot loaded (the same run shows slot 0 and
the level headers gliding with nothing touched), so "half" was a moment, not a
scale. On the instrument that put POS's last frame halfway up WAV1, kept TBL1 1 on
table 0, and read TUN1 0 as +64 semitones.

This module is pure: numbers in, numbers out.
"""

from __future__ import annotations

import math
import struct

from . import render

RATE = 48000.0
A4_NOTE, A4_HZ = 69, 440.0
NOTES = 129                      # T[0..128]; T[128] is only read with fr = 0
POS_MAX = 0x7800                 # WAV1's range in the frame: the sound's own
POS_SHIFT = 5                    # 0x7800 << 5 == 15 << 16
SLOT_SHIFT = 8                   # TBL1 1: 0x0100, in the sound and in the frame
TUN1_ZERO = 0x4000               # TUN1's frame word for 0 semitones: the sound's own
LEV1_UNITY = 0x6400              # LEV1 100, the default: gain exactly 1.0 (Milestone 9a)
GAIN_STEP = 1 / 25600            # the loop's constant, as float32 0x3823d70a


def _f32(x: float) -> float:
    return struct.unpack("<f", struct.pack("<f", x))[0]


def note_hz(note: float) -> float:
    return A4_HZ * 2.0 ** ((note - A4_NOTE) / 12.0)


def increment_table() -> list[float]:
    """T[k], k = 0..128: the u32 phase step for note k at 48 kHz, as float32."""
    return [_f32(note_hz(k) / RATE * 2.0 ** 32) for k in range(NOTES)]


def table_bytes() -> bytes:
    """The increment table as the DSP reads it: little-endian float32."""
    return struct.pack("<%df" % NOTES, *increment_table())


def trunc(x: float) -> int:
    """SHARC `Rn = TRUNC Fx` for the values the loop meets (0 <= x < 2^31)."""
    return int(math.trunc(x))


def increment(note: float, table: list[float] | None = None) -> int:
    """The loop's inc for a note cell value, float32 in the loop's order."""
    t = table or increment_table()
    n = _f32(note)
    n = min(n, 127.0)
    n = max(n, 0.0)
    k = trunc(n)
    fr = _f32(n - _f32(float(k)))
    d = _f32(t[k + 1] - t[k])
    e = _f32(fr * d)
    return trunc(_f32(t[k] + e)) & 0xFFFFFFFF


def tuned(note: float, tun1: int = TUN1_ZERO) -> float:
    """The note cell plus TUN1, as the loop forms it: a NaN, an infinity or a negative
    note is +0.0 first; then + (word / 128 - 64) semitones, float32; below 0 is 0.

    The scale was read on the instrument through the USB probe (0x4000 at 0, 0x4100
    at +1, 0x4c00 at +12, 0x3400 at -12): one semitone per coarse step and fine / 256
    of one, which the display shows as -5..+5 octaves."""
    n = _f32(note)
    if math.isnan(n) or math.isinf(n) or n < 0 or (n == 0 and math.copysign(1.0, n) < 0):
        n = 0.0
    t = _f32(_f32(float(tun1 & 0xFFFF) / 256.0) - 64.0)
    n = _f32(n + t)
    return 0.0 if n < 0 else n


# -- M10a: MOVE, the per-oscillator modulator (csrc/waverider/sharc/modulator.asm) --
# The frame slots of each oscillator's RATE, MPOS, MLEV, MOVE, and the shared TRIG
# (TYPE) and PRST (RSET).
MOVE_SLOTS = ((29, 28, 38, 40, 46, 39), (35, 34, 43, 44, 46, 39))
MPOS_NONE = 0x3200                 # MPOS 50: no movement
TRIG_RESTART = 0x0000              # TRIG's default (TYPE 0): a note restarts the shape
PRST_OFF, PRST_ON, PRST_RANDOM = 0x0000, 0x0100, 0x0200   # RSET: the oscillators on a note
# F[j] = 2^32 / 1500 x 2^(j / 10) / 32: a block's phase step at RATE j; << (r div 10)
MOVE_RATE = tuple(round(2 ** 32 / 1500 * 2 ** (j / 10) / 32) for j in range(10))
MPOS_SCALE = 0x7800 / (0x3200 * 0xFFFF)
MLEV_SCALE, SHAPE_SCALE = 1 / 0x7F00, 1 / 0xFFFF
# MOVE 0..10 (M10b-4), sorted by nature: the one-shots, which stop at their end; the
# loops; the random shapes, which draw a value each cycle. (M10b-1 had five: Ramp Down,
# Ramp Up, Tri Once, Tri Loop, Square; a sound saved with those reads the new order.)
MOVE_SHAPES = ("Ramp Up", "Ramp Down", "Exp Up", "Exp Down", "Tri Once",
               "Up Loop", "Down Loop", "Tri Loop", "Square",
               "Rnd Hold", "Rnd Glide")
ONE_SHOTS = 5                      # shapes 0..4 stop at their end; 5.. loop
RND_HOLD, RND_GLIDE = 9, 10
# the random shapes' generator (shapes.asm): x = rotate(x, 7) + RND_ADD, one state
# for every voice, drawn on a cycle's wrap and on a note's restart; the value is x >> 16
RND_ADD = 0x6D2B79F5
EXP_SCALE = 2.0 ** -32             # Exp: x^3 / 2^32, in float32
GLIDE_IN, GLIDE_TWO, GLIDE_THREE = 2.0 ** -16, 2.0, 3.0


def move_offsets() -> tuple[tuple[int, ...], ...]:
    """Per oscillator, the frame byte offsets (168 + 2 s) the modulator reads."""
    return tuple(tuple(168 + 2 * s for s in slots) for slots in MOVE_SLOTS)


def move_band(move: int) -> int:
    b = (move & 0xFFFF) >> 8
    return min(b, len(MOVE_SHAPES) - 1)


def move_restarts(trig_mode: int, triggered: bool) -> bool:
    """TRIG Retrig and a note on this voice: the shape starts again."""
    return not (trig_mode & 0xFFFF) >> 8 and triggered


def move_step(phase: int, rate: int, move: int, trig_mode: int, triggered: bool) -> int:
    """The phase after one block, as the modulator steps it."""
    if move_restarts(trig_mode, triggered):
        phase = 0
    r = min((rate & 0xFFFF) >> 8, 100)
    inc = (MOVE_RATE[r % 10] << (r // 10)) & 0xFFFFFFFF
    new = (phase + inc) & 0xFFFFFFFF
    if move_band(move) < ONE_SHOTS and new < phase:
        new = 0xFFFFFFFF
    return new


def rnd_next(x: int) -> int:
    """The random shapes' generator step."""
    return ((((x << 7) | (x >> 25)) & 0xFFFFFFFF) + RND_ADD) & 0xFFFFFFFF


class MoveRandom:
    """The random shapes' state: the generator, and per voice and oscillator the value
    before (a) and the value now (b), 16 bits each; all zero at boot."""

    def __init__(self) -> None:
        self.x = 0
        self.held: dict[int, list[int]] = {}

    def values(self, key: int) -> list[int]:
        return self.held.setdefault(key, [0, 0])

    def step(self, key: int, start: int, new: int, move: int, restarted: bool) -> None:
        """After one block of a random shape: a new value on a wrap or a restart."""
        if move_band(move) < RND_HOLD:
            return
        if restarted or new < start:
            ab = self.values(key)
            self.x = rnd_next(self.x)
            ab[0], ab[1] = ab[1], self.x >> 16


def _exp(x: int) -> int:
    f = _f32(float(x))
    return trunc(_f32(_f32(_f32(f * f) * f) * _f32(EXP_SCALE)))


def _glide(x: int, a: int, b: int) -> int:
    """a to b over the cycle on a smoothstep, u^2 (3 - 2u), in float32."""
    u = _f32(_f32(float(x)) * _f32(GLIDE_IN))
    s = _f32(_f32(u * u) * _f32(GLIDE_THREE - _f32(u * GLIDE_TWO)))
    fa = _f32(float(a))
    return trunc(_f32(_f32(_f32(_f32(float(b)) - fa) * s) + fa))


def move_shape(phase: int, move: int, held: tuple[int, int] = (0, 0)) -> int:
    """The shape's value, 0..0xffff, at this phase; HELD is (a, b) for the random
    shapes."""
    x, band = phase >> 16, move_band(move)
    if band in (0, 5):
        return x
    if band in (1, 6):
        return 0xFFFF - x
    if band == 2:
        return _exp(x)
    if band == 3:
        return _exp(0xFFFF - x)
    if band == 8:
        return 0xFFFF if x < 0x8000 else 0
    if band == RND_HOLD:
        return held[1]
    if band == RND_GLIDE:
        return _glide(x, *held)
    return (x if x < 0x8000 else 0xFFFF - x) << 1


def move_apply(wav: int, lev: int, mpos: int, mlev: int, s: int) -> tuple[int, int]:
    """POS and LEV after the modulator, in its float32 order; MPOS 50 and MLEV 0 leave
    them untouched."""
    d = (mpos & 0xFFFF) - MPOS_NONE
    if d:
        f = _f32(_f32(_f32(float(d)) * _f32(float(s))) * _f32(MPOS_SCALE))
        wav = max(wav + trunc(f), 0)
    m = mlev & 0xFFFF
    if m:
        a = _f32(_f32(float(m)) * _f32(MLEV_SCALE))
        b = _f32(1.0 - _f32(_f32(float(s)) * _f32(SHAPE_SCALE)))
        g = _f32(1.0 - _f32(a * b))
        lev = trunc(_f32(_f32(float(lev)) * g))
    return wav, lev


def tuned2(note: float, tun2: int, tun1: int) -> float:
    """Osc 2's note (Milestone 9b): DETN is a detune from osc 1, so the loop adds
    (TUN2 + TUN1) in semitones, float32, where osc 1 adds TUN1; otherwise as `tuned`."""
    n = _f32(note)
    if math.isnan(n) or math.isinf(n) or n < 0 or (n == 0 and math.copysign(1.0, n) < 0):
        n = 0.0
    t1 = _f32(_f32(float(tun1 & 0xFFFF) / 256.0) - 64.0)
    t2 = _f32(_f32(float(tun2 & 0xFFFF) / 256.0) - 64.0)
    n = _f32(n + _f32(t2 + t1))
    return 0.0 if n < 0 else n


def position(wav1: int) -> int:
    """The loop's Q16 frame position for the frame's 16-bit WAV1 word."""
    return min(wav1 & 0xFFFF, POS_MAX) << POS_SHIFT


def slot(tbl1: int, count: int) -> int:
    """The directory slot the loop plays for the frame's 16-bit TBL1 word."""
    s = (tbl1 & 0xFFFF) >> SLOT_SHIFT
    return s if s < count else 0


def gain(lev1: int) -> float:
    """The reader's gain for the frame's 16-bit LEV1 word (Milestone 9a): LEV1 x
    f32(1/25600) in float32, as the loop computes it; exactly 1.0 at 100."""
    return _f32(_f32(float(lev1 & 0xFFFF)) * _f32(GAIN_STEP))


def render_blocks(tables, blocks, block: int = 32, phase: int = 0,
                  precision: str = "float32") -> tuple[list[float], int]:
    """The loop's output for a sequence of blocks, each (note, WAV1, TBL1[, TUN1[, LEV1]])
    -- the frame's 16-bit words; TUN1 defaults to 0 semitones, LEV1 to 100: the phase
    carries across blocks and across slot changes, as the reader block holds it. Each
    sample is the reader's y times the gain, rounded to float32 (reader_m9.asm)."""
    out: list[float] = []
    table_t = increment_table()
    for note, wav1, tbl1, *rest in blocks:
        tun1 = rest[0] if rest else TUN1_ZERO
        g = gain(rest[1] if len(rest) > 1 else LEV1_UNITY)
        tab = tables[slot(tbl1, len(tables))]
        samples, phase = render.render(tab, phase, increment(tuned(note, tun1), table_t),
                                       position(wav1),
                                       block, precision)
        out += [_f32(g * y) for y in samples] if precision == "float32" else [g * y for y in samples]
    return out, phase


def render_two(tables, blocks, block: int = 32, precision: str = "float32") -> list[float]:
    """The loop's output with both oscillators (Milestone 9b), each block
    (note, osc1, osc2[, (TRIG, triggered)]) with each osc (WAV, TBL, TUN, LEV[, RATE,
    MPOS, MLEV, MOVE]), the frame's 16-bit words. With the M10a fields the modulator
    (move_step / move_shape / move_apply) moves POS and LEV first, per oscillator.
    Osc 1 writes y1 x gain1; osc 2, unless its LEV is 0 (the loop then skips it), adds
    y2 x gain2 to that, both rounded to float32 as reader_m9.asm does. Osc 2's TUN is
    a detune from osc 1 (`tuned2`). Each oscillator keeps its own phase from block to
    block."""
    out: list[float] = []
    phase = [0, 0]
    mphase = [0, 0]
    rnd = MoveRandom()
    table_t = increment_table()
    for blk in blocks:
        note, oscs = blk[0], blk[1:3]
        trig_mode, triggered, *rest = blk[3] if len(blk) > 3 else (TRIG_RESTART, False)
        prst = rest[0] if rest else PRST_OFF
        mixed: list[float] = []
        for k, osc in enumerate(oscs):
            wav, tbl, tun, lev = osc[:4]
            if k and not lev & 0xFFFF:
                continue
            if len(osc) > 4:                    # M10a: RATE, MPOS, MLEV, MOVE
                rate, mpos, mlev, move = osc[4:8]
                restarted = move_restarts(trig_mode, triggered)
                start = 0 if restarted else mphase[k]
                mphase[k] = move_step(mphase[k], rate, move, trig_mode, triggered)
                rnd.step(k, start, mphase[k], move, restarted)
                wav, lev = move_apply(wav, lev, mpos, mlev,
                                      move_shape(mphase[k], move, tuple(rnd.values(k))))
            if len(osc) > 4 and triggered and (prst & 0xFFFF) >> 8:
                if (prst & 0xFFFF) >> 8 != 1:
                    raise ValueError("PRST Random starts from the DSP's cycle counter: no reference")
                phase[k] = 0                    # PRST On: the oscillator restarts
            g = gain(lev)
            samples, phase[k] = render.render(tables[slot(tbl, len(tables))], phase[k],
                                              increment(tuned(note, tun) if k == 0 else
                                                        tuned2(note, tun, oscs[0][2]), table_t),
                                              position(wav), block, precision)
            y = [_f32(g * v) for v in samples] if precision == "float32" else [g * v for v in samples]
            if k == 0:
                mixed = y
            else:
                mixed = ([_f32(a + b) for a, b in zip(mixed, y)] if precision == "float32"
                         else [a + b for a, b in zip(mixed, y)])
        out += mixed
    return out

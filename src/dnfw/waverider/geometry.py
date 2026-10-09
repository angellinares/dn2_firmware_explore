"""Mip-mapped tables of any geometry (stage 3): F frames of N points, N a power of two.

`dnfw.waverider.mip` is the shipped reader's model, fixed at 512 points and 8 levels. This
is the same scheme with the frame length a parameter, for the pool's tables (Tonverk's
waves are 64..4096 samples, `docs/waverider-tables.md`):

- **levels** k = 0 .. log2(N) - 2: level k keeps harmonics 1 .. (N >> (k + 1)) - 1, so the
  last level (4 points at OVERSAMPLE 2, more at 8) holds the fundamental alone;
- a level's length is the shortest power of two giving its top harmonic OVERSAMPLE points a
  cycle, capped at N (`mip.points`, generalised);
- a block plays the lowest level whose top harmonic stays below LIMIT_HZ (hermite2 ships
  28 kHz, `mip.LIMIT_HZ`);
- the reader is hermite2's: the four taps blended between the two frames, then one
  Catmull-Rom (`render.hermite`), here in float64 (no DSP rounding modelled).

At N = 512 the levels and the level choice are `mip`'s exactly (test/test_geometry.py).
Pure: numbers in, numbers out.
"""

from __future__ import annotations

import numpy as np

from . import mip

OVERSAMPLE = mip.OVERSAMPLE
LIMIT_HZ = 28000
RATE = 48000


def bits(points: int) -> int:
    b = points.bit_length() - 1
    if points != 1 << b or not 3 <= b <= 16:
        raise ValueError(f"a frame is a power of two, 8..65536 points, not {points}")
    return b


def levels(points: int) -> int:
    """How many levels a frame of POINTS has: down to the fundamental alone."""
    return bits(points) - 1


def top_harmonic(points: int, level: int) -> int:
    return (points >> (level + 1)) - 1


def level_points(points: int, level: int, oversample: int = OVERSAMPLE) -> int:
    if level == 0:
        return points
    need = oversample * (top_harmonic(points, level) + 1)
    return min(points, 1 << max(2, (need - 1).bit_length()))


def frame_levels(frame: np.ndarray, oversample: int = OVERSAMPLE) -> list[np.ndarray]:
    """One frame (floats or ints) -> its levels, level 0 the frame itself (as floats)."""
    frame = np.asarray(frame, dtype=float)
    n = len(frame)
    spectrum = np.fft.rfft(frame)
    out = [frame.copy()]
    for k in range(1, levels(n)):
        m = level_points(n, k, oversample)
        keep = np.zeros(m // 2 + 1, dtype=complex)
        top = top_harmonic(n, k)
        keep[: top + 1] = spectrum[: top + 1]
        out.append(np.fft.irfft(keep, m) * (m / n))
    return out


def table_levels(table, oversample: int = OVERSAMPLE) -> list[np.ndarray]:
    """A table (frames x points) -> levels[k], an array frames x level_points(k)."""
    per = [frame_levels(f, oversample) for f in table]
    return [np.array([p[k] for p in per]) for k in range(len(per[0]))]


def level_for(inc: int, points: int, limit_hz: int = LIMIT_HZ) -> int:
    """The level a block at phase increment INC (u32, a whole cycle is 2^32) plays."""
    lim = limit_hz * (1 << 32) // RATE
    k, last = 0, levels(points) - 1
    while k < last and top_harmonic(points, k) * (inc & 0xFFFFFFFF) >= lim:
        k += 1
    return k


def size_bytes(frames: int, points: int, oversample: int = OVERSAMPLE, guards: int = 3) -> int:
    """A mip-mapped table's int16 bytes, every level of every frame, with GUARDS a row."""
    return 2 * frames * sum(level_points(points, k, oversample) + guards for k in range(levels(points)))


def increment(freq: float) -> int:
    return int(round(freq / RATE * (1 << 32))) & 0xFFFFFFFF


def _catmull(ym, y0, y1, y2, t):
    return y0 + 0.5 * t * ((y1 - ym) + t * ((2 * ym - 5 * y0 + 4 * y1 - y2) + t * (3 * (y0 - y1) + y2 - ym)))


def render(table_lv: list[np.ndarray], freq: float, positions: list[float], block: int = 32,
           limit_hz: int = LIMIT_HZ) -> np.ndarray:
    """Samples at FREQ Hz, one block of BLOCK per entry of POSITIONS (float frame positions,
    0 .. frames - 1), the level chosen per block (it is fixed for a note here), full scale
    = the table's own scale."""
    inc = increment(freq)
    points = table_lv[0].shape[1]
    lv = table_lv[level_for(inc, points, limit_hz)]
    frames, n = lv.shape
    b = bits(n)
    out = np.empty(block * len(positions))
    phase = 0
    steps = np.arange(block, dtype=np.uint64) * np.uint64(inc)
    for j, pos in enumerate(positions):
        ph = (np.uint64(phase) + steps) & np.uint64(0xFFFFFFFF)
        idx = (ph >> np.uint64(32 - b)).astype(np.int64)
        t = (ph & np.uint64((1 << (32 - b)) - 1)).astype(float) / (1 << (32 - b))
        f0 = int(np.floor(pos))
        f1 = min(f0 + 1, frames - 1)
        ff = pos - f0
        row = lv[f0] + ff * (lv[f1] - lv[f0])
        taps = [row[(idx + d) % n] for d in (-1, 0, 1, 2)]
        out[j * block:(j + 1) * block] = _catmull(*taps, t)
        phase = (phase + block * inc) & 0xFFFFFFFF
    return out

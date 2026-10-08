"""Mip-mapped wavetables: each frame stored again per octave, without the harmonics that
would alias there (the SHARC study's B1).

A 512-point frame holds harmonics 1..255. Played at fundamental f0, harmonic h folds back
below Nyquist (24 kHz) once h * f0 >= 24 kHz, which a bright table reaches from the
middle of the keyboard. So each frame is kept at levels k = 0..7:

- **level 0** is the frame itself, unchanged: 512 points, harmonics up to 255;
- **level k** has 512 >> k points and keeps harmonics 1 .. (256 >> k) - 1, the rest
  removed in the frequency domain (exact for a periodic frame), so level 7 is 4 points
  holding the fundamental alone. A level's harmonics are the frame's own, at the same
  amplitude and phase; only the ones above the cut are gone.

**Level lengths.** With halved lengths (2 points a cycle of a level's top harmonic, 1,020
points a frame in all) linear interpolation's images come back into the band; measured
(`scripts/waverider_mip_alias.py`, 2026-10-08), a bright table is only -39 to -25 dB from
C4 to C8 that way, and a sine gets worse than without levels. `OVERSAMPLE` sets the points a
cycle; 8 (levels 0-2 at 512, then 256 .. 16: 2,032 points a frame, 4x the memory) holds a
bright table to -58 .. -47 dB, and a sine at -57 dB at C8.

**Which level a block plays** is chosen once a block from the phase increment the reader
already has: the lowest k whose top harmonic stays below Nyquist, `((256 >> k) - 1) * inc
< 2**31` (f0 = inc * 48000 / 2**32, so h * f0 < 24000 is h * inc < 2**31). A note low
enough plays level 0, exactly as today.

This module is pure: numbers in, numbers out.
"""

from __future__ import annotations

import numpy as np

POINTS = 512
LEVELS = 8                        # 512 .. 4 points
HALF = 1 << 31                    # Nyquist, in phase-increment units


OVERSAMPLE = 8                    # points per cycle of a level's top harmonic, at least (2026-10-08: 2
                                  # and 4 let linear interpolation's images back; 8 holds bright tables to -47 dB at C8)


def points(level: int, oversample: int = OVERSAMPLE) -> int:
    """A level's frame length: the shortest power of two giving its top harmonic at least
    OVERSAMPLE points a cycle, capped at 512. OVERSAMPLE 2 halves the length per level."""
    if level == 0:
        return POINTS
    need = oversample * (top_harmonic(level) + 1)
    return min(POINTS, 1 << max(2, (need - 1).bit_length()))


def top_harmonic(level: int) -> int:
    """The highest harmonic level LEVEL keeps."""
    return (POINTS >> (level + 1)) - 1


def level_for(inc: int) -> int:
    """The level a block at phase increment INC (u32) plays: the lowest that doesn't alias."""
    k = 0
    while k < LEVELS - 1 and top_harmonic(k) * (inc & 0xFFFFFFFF) >= HALF:
        k += 1
    return k


def _clip16(v: np.ndarray) -> list[int]:
    return [int(x) for x in np.clip(np.rint(v), -32768, 32767)]


def frame_levels(frame: list[int], oversample: int = OVERSAMPLE) -> list[list[int]]:
    """One 512-point frame -> its eight levels (level 0 is the frame itself)."""
    if len(frame) != POINTS:
        raise ValueError(f"a frame is {POINTS} points, not {len(frame)}")
    spectrum = np.fft.rfft(np.asarray(frame, dtype=float))       # bins 0..256
    out = [list(frame)]
    for k in range(1, LEVELS):
        n = points(k, oversample)
        keep = np.zeros(n // 2 + 1, dtype=complex)
        keep[: top_harmonic(k) + 1] = spectrum[: top_harmonic(k) + 1]
        out.append(_clip16(np.fft.irfft(keep, n) * (n / POINTS)))
    return out


def table_levels(table: list[list[int]], oversample: int = OVERSAMPLE) -> list[list[list[int]]]:
    """A table (frames x 512) -> levels[k][frame] (frames x points(k))."""
    per_frame = [frame_levels(f, oversample) for f in table]
    return [[pf[k] for pf in per_frame] for k in range(LEVELS)]


def size_bytes(frames: int = 16, oversample: int = OVERSAMPLE) -> int:
    """A mip-mapped table's int16 bytes: every level of every frame."""
    return 2 * frames * sum(points(k, oversample) for k in range(LEVELS))


def render(levels: list[list[list[int]]], phase: int, inc: int, pos: int, count: int,
           precision: str = "ideal", interp: str = "linear") -> tuple[list[float], int]:
    """`dnfw.waverider.render.render` on the level this block's increment plays."""
    from . import render as reader          # noqa: PLC0415
    return reader.render(levels[level_for(inc)], phase, inc, pos, count, precision, interp)

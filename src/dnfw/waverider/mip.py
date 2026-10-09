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

import os

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


def limit_units(limit_hz: int) -> int:
    """A level's harmonic limit in phase-increment units (24 kHz is HALF)."""
    return limit_hz * (1 << 32) // 48000


def thresholds(limit_hz: int) -> list[int]:
    """The reader's T[k], k = 0..6: a block plays level k while inc < T[k]
    (ceil(limit / top harmonic), so top_harmonic(k) * inc < limit)."""
    lim = limit_units(limit_hz)
    return [-(-lim // top_harmonic(k)) for k in range(LEVELS - 1)]


def level_for(inc: int, limit_hz: int | None = None) -> int:
    """The level a block at phase increment INC (u32) plays: the lowest whose top harmonic
    stays below LIMIT_HZ (24 kHz: nothing aliases; above it, the harmonics past Nyquist
    fold back to 48 kHz - h, at or above 48 kHz - LIMIT_HZ)."""
    lim = limit_units(LIMIT_HZ if limit_hz is None else limit_hz)
    k = 0
    while k < LEVELS - 1 and top_harmonic(k) * (inc & 0xFFFFFFFF) >= lim:
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


# Between samples: the reader a build ships, "linear" (reader_mip.asm), "hermite"
# (reader_miph.asm) or "hermite2" (reader_miph2.asm: 16-bit loads from guarded rows, the
# frames blended before one cubic). The default is hermite2 (the owner's pick, 2026-10-09:
# mip2h); the comparison builds set DNFW_WAVERIDER_INTERP, and everything (the image, the
# reference, the gates) follows it.
INTERP = os.environ.get("DNFW_WAVERIDER_INTERP", "hermite2")
if INTERP not in ("linear", "hermite", "hermite2"):
    raise ValueError(f"DNFW_WAVERIDER_INTERP is {INTERP!r}, not linear, hermite or hermite2")

# The harmonic limit a level is chosen against (2026-10-08): 24 kHz (nothing aliases, but
# just above an octave step the band ends near 12 kHz) for mip1 / mip1h; hermite2 ships
# 28 kHz (the worst band 14 kHz, every alias it adds between 20 and 24 kHz). The reader's
# thresholds are literals in its source, so each reader has one limit.
LIMITS = {"linear": 24000, "hermite": 24000, "hermite2": 28000}
LIMIT_HZ = LIMITS[INTERP]

# hermite2's rows carry guard samples, so its four taps (i-1 .. i+2) never wrap: one
# sample before the frame (its last) and two after (its first two).
GUARD_BEFORE, GUARD_AFTER = 1, 2


def guarded() -> bool:
    return INTERP == "hermite2"


def row_points(level: int, oversample: int = OVERSAMPLE) -> int:
    """The int16 a stored row of LEVEL takes: its points, plus the guards for hermite2."""
    return points(level, oversample) + ((GUARD_BEFORE + GUARD_AFTER) if guarded() else 0)


class MipTable(list):
    """A table (a list of 512-point frames, as everywhere else) that also carries its
    levels: the reader plays it mip-mapped. Code that only reads frames sees a table."""

    def __init__(self, frames, oversample: int = OVERSAMPLE):
        super().__init__(frames)
        self.oversample = oversample
        self._levels = None

    @property
    def levels(self) -> list[list[list[int]]]:
        if self._levels is None:
            self._levels = table_levels(list(self), self.oversample)
        return self._levels

    def dsp_bytes(self) -> bytes:
        """The table in the DSP's DDR: level 0..7 one after another, each frame-major,
        little-endian int16 (dnfw.waverider.render.dsp_bytes per level); for hermite2 each
        row is [last, frame..., first, second] (`row_points`), after the stage 3 header
        reader_miph2.asm reads (dnfw.waverider.table3)."""
        from . import render as reader  # noqa: PLC0415
        if not guarded():
            return b"".join(reader.dsp_bytes(level) for level in self.levels)
        from . import table3  # noqa: PLC0415
        return table3.dsp_bytes(self.levels)


def level_offsets(frames: int = 16, oversample: int = OVERSAMPLE) -> list[int]:
    """Each level's byte offset in a MipTable's DSP bytes."""
    out, at = [], 0
    for k in range(LEVELS):
        out.append(at)
        at += 2 * frames * row_points(k, oversample)
    return out


def level_records(frames: int = 16, oversample: int = OVERSAMPLE) -> bytes:
    """reader_mip.asm's level records, 8 words each: the byte offset, log2 of a frame's
    bytes, the word index's shift, one sample of phase, the fraction mask and scale, and
    (reader_miph.asm, Hermite) the scale of half the fraction. reader_miph2.asm reads the
    same words: its row stride is 2^(word 1) + 6 bytes (the guards), its sample index is
    phase >> (32 - b) (word 5 as a shift)."""
    import struct  # noqa: PLC0415
    out = b""
    for k, off in enumerate(level_offsets(frames, oversample)):
        b = points(k, oversample).bit_length() - 1
        one = 1 << (32 - b)
        out += struct.pack("<IIiIIiiI", off, b + 1, -(33 - b), one, one - 1, -(32 - b), -(33 - b), 0)
    return out


def read(table, phase: int, inc: int, pos: int, count: int, precision: str = "ideal"):
    """What the shipped reader plays for TABLE: its levels for a MipTable, level 0
    otherwise, between samples by INTERP."""
    from . import render as reader  # noqa: PLC0415
    from . import table3  # noqa: PLC0415
    if isinstance(table, table3.Table3):
        return table3.read(table, phase, inc, pos, count, precision)
    if isinstance(table, MipTable):
        return render(table.levels, phase, inc, pos, count, precision, INTERP)
    # a plain table: hermite2 hands it to opt2's linear reader (reader_m9.asm's wr5_plain)
    return reader.render(table, phase, inc, pos, count, precision,
                         "linear" if INTERP == "hermite2" else INTERP)

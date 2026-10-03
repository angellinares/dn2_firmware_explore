"""Tonverk-size test tables (64 frames x 2048 points), for the stress-test build only.

Tonverk plays wavetables of up to 64 waves of up to 2048 samples (its manual, section
5.2.5). Before the pool's table size is chosen, a build plays two tables of that size,
so the SHARC's cost can be measured and the aliasing heard. Both are our own
synthesis, full band (up to harmonic 1023, the most a 2048-point frame holds):

- slot 0: a sine growing into a saw, harmonic count 1 -> 1023 on a log scale;
- slot 1: a pulse narrowing from a square (duty 0.5) to a thin pulse (0.03).

Each frame peaks at 0.9 of int16 full scale. numpy is needed here only (the build of
the stress test), and is imported lazily.
"""

from __future__ import annotations

FRAMES = 64
POINTS = 2048
HARMONICS = POINTS // 2 - 1          # 1023: below the frame's Nyquist
PEAK = 0.9 * 32767


def _frame(amps) -> list[int]:
    import numpy as np  # noqa: PLC0415
    spectrum = np.zeros(POINTS // 2 + 1, dtype=complex)
    h = np.arange(1, len(amps) + 1)
    spectrum[h] = -1j * np.asarray(amps) * POINTS / 2          # sines
    wave = np.fft.irfft(spectrum, POINTS)
    wave *= PEAK / np.max(np.abs(wave))
    return [int(v) for v in np.rint(wave)]


def saw_growing() -> list[list[int]]:
    out = []
    for f in range(FRAMES):
        count = max(1, round(HARMONICS ** (f / (FRAMES - 1))))
        out.append(_frame([1.0 / h for h in range(1, count + 1)]))
    return out


def pulse_narrowing() -> list[list[int]]:
    import math  # noqa: PLC0415
    out = []
    for f in range(FRAMES):
        duty = 0.5 + (0.03 - 0.5) * f / (FRAMES - 1)
        out.append(_frame([math.sin(math.pi * h * duty) / h for h in range(1, HARMONICS + 1)]))
    return out


def tables() -> list[list[list[int]]]:
    return [saw_growing(), pulse_narrowing()]

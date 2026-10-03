"""Tonverk-size test tables (64 frames x 2048 points), for the stress-test build only.

Tonverk plays wavetables of up to 64 waves of up to 2048 samples (its manual, section
5.2.5). Before the pool's table size is chosen, a build plays two tables of that size,
so the SHARC's cost can be measured and the aliasing heard. Both are our own
synthesis, full band (up to harmonic 1023, the most a 2048-point frame holds):

- slot 0: a sine growing into a saw: 1, 10, 102 and 1023 harmonics;
- slot 1: a pulse narrowing from a square (duty 0.5) to a thin pulse (0.03), in 4 steps.

Each frame peaks at 0.9 of int16 full scale. numpy is needed here only (the build of
the stress test), and is imported lazily.

**4 distinct frames per table, each held for 16 frames** (2026-10-04). The first build,
64 distinct frames a table, made a 2.98 MB `.syx`, and the instrument faulted at 89 % of
the transfer (V09 M6 P40001946, in the prio-9 task), while every image flashed before was
2.44 MB or less. Repeated frames compress to almost nothing, so this image is no bigger
than m10b4's; the SHARC still holds and reads 512 KB of tables in the same pattern, which
is what the stress test measures. The sound steps through the four.
"""

from __future__ import annotations

FRAMES = 64
POINTS = 2048
HARMONICS = POINTS // 2 - 1          # 1023: below the frame's Nyquist
PEAK = 0.9 * 32767
DISTINCT = 4                         # spectra per table, each held for FRAMES // DISTINCT frames


def _frame(amps) -> list[int]:
    import numpy as np  # noqa: PLC0415
    spectrum = np.zeros(POINTS // 2 + 1, dtype=complex)
    h = np.arange(1, len(amps) + 1)
    spectrum[h] = -1j * np.asarray(amps) * POINTS / 2          # sines
    wave = np.fft.irfft(spectrum, POINTS)
    wave *= PEAK / np.max(np.abs(wave))
    return [int(v) for v in np.rint(wave)]


def _held(frames: list[list[int]]) -> list[list[int]]:
    return [frames[f * DISTINCT // FRAMES] for f in range(FRAMES)]


def saw_growing() -> list[list[int]]:
    out = []
    for g in range(DISTINCT):
        count = max(1, round(HARMONICS ** (g / (DISTINCT - 1))))
        out.append(_frame([1.0 / h for h in range(1, count + 1)]))
    return _held(out)


def pulse_narrowing() -> list[list[int]]:
    import math  # noqa: PLC0415
    out = []
    for g in range(DISTINCT):
        duty = 0.5 + (0.03 - 0.5) * g / (DISTINCT - 1)
        out.append(_frame([math.sin(math.pi * h * duty) / h for h in range(1, HARMONICS + 1)]))
    return _held(out)


def tables() -> list[list[list[int]]]:
    return [saw_growing(), pulse_narrowing()]

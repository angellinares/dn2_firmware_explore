"""Stage 3's test set: one table at four geometries, as WAVs for DNX and as renders to hear.

    python scripts/waverider_geometry_set.py [--out out/waverider/geometry]

**The source** (ours, generated): 64 frames of 2048 points, harmonics 1..1023. A quiet
saw-like floor (1/h, all 1,023 harmonics) under a formant that sweeps across the table,
from the fundamental at frame 0 to harmonic ~900 at frame 63 (a Gaussian a quarter of an
octave wide, on a log-harmonic axis). Moving POS moves one peak: with 16 frames the peak
jumps 0.65 octave between neighbouring frames and the crossfade between them is two
peaks; at 512 points everything above harmonic 255 is gone, which a low note hears.

**The four tables**, each from the source through `dnfw.waverider.reduce.to_int16` (what
the import does today: frames linearly interpolated to the count, points box-filtered,
normalised to 32767), so each differs from the next in one thing:

    WRtest_64x2048_wt2048.wav   Tonverk's default geometry
    WRtest_64x512_wt512.wav     fewer points (harmonics above 255 folded down by the box filter)
    WRtest_16x2048_wt2048.wav   fewer frames
    WRtest_16x512_wt512.wav     today's geometry

`_wt<N>` is Tonverk's naming convention for the wave length (`docs/waverider-tables.md`).
Each also goes out as `WRtest_<F>x<N>.raw`: the +Drive store's payload, int16 big-endian,
frame-major, no header, which DNX writes as it is (a WAV's header and little-endian data
are not; DNX converted the first set, store slots 78..81, 2026-10-09).

**The renders** (`dnfw.waverider.geometry`, hermite2's reader with mip levels at 28 kHz, any
geometry), each one WAV with the four tables in that order, 0.6 s apart, the four at one gain:

    sweep_C2.wav    POS 0 -> end -> 0 over 8 s at C2 (65.4 Hz): frames and points both heard
    sweep_C4.wav    the same at C4 (261.6 Hz): mostly frames
    held_C1.wav     C1 (32.7 Hz) held 3 s at POS 85 % (the formant high): mostly points
"""

from __future__ import annotations

import argparse
import pathlib
import sys
import wave

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from dnfw.waverider import geometry as G   # noqa: E402
from dnfw.waverider import reduce           # noqa: E402

FRAMES, POINTS, TOP = 64, 2048, 1023
GEOMETRIES = ((64, 2048), (64, 512), (16, 2048), (16, 512))
BLOCK, GAP = 32, 0.6
NOTES = {"C1": 32.703, "C2": 65.406, "C4": 261.626}


def source() -> list[list[float]]:
    h = np.arange(1, TOP + 1)
    x = np.arange(POINTS) / POINTS
    basis = np.sin(2 * np.pi * np.outer(h, x))                     # harmonics x points
    floor = 0.08 / h
    out = []
    for k in range(FRAMES):
        centre = np.log2(900) * k / (FRAMES - 1)
        formant = np.exp(-0.5 * ((np.log2(h) - centre) / 0.25) ** 2) / np.sqrt(h)
        out.append(list((floor + formant) @ basis))
    return out


def write_wav(path: pathlib.Path, samples: np.ndarray) -> None:
    """Floats (full scale 1.0) or int16 values (an integer array, written as they are)."""
    if np.issubdtype(samples.dtype, np.integer):
        pcm = samples.astype("<i2").tobytes()
    else:
        pcm = np.clip(np.rint(samples * 32767), -32768, 32767).astype("<i2").tobytes()
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(G.RATE)
        w.writeframes(pcm)


def sweep(frames: int, seconds: float) -> list[float]:
    blocks = int(seconds * G.RATE / BLOCK)
    top = frames - 1
    half = (blocks - 1) / 2
    return [top * (1 - abs(j - half) / half) for j in range(blocks)]


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--out", type=pathlib.Path, default=ROOT / "out" / "waverider" / "geometry")
    a = p.parse_args(argv)
    src = source()
    tables = {g: reduce.to_int16(src, count=g[0], points=g[1]) for g in GEOMETRIES}
    for (f, n), t in tables.items():
        write_wav(a.out / "tables" / f"WRtest_{f}x{n}_wt{n}.wav", np.array(t, dtype=np.int16).ravel())
        (a.out / "tables" / f"WRtest_{f}x{n}.raw").write_bytes(np.array(t, dtype=">i2").tobytes())
        print(f"  {f:2d} x {n:4d}: {2 * f * n / 1024:6.0f} KB as stored, "
              f"{G.size_bytes(f, n) / 1024:6.0f} KB with levels and guards")
    levels = {g: G.table_levels(t) for g, t in tables.items()}
    tests = {"sweep_C2": ("C2", lambda f: sweep(f, 8.0)),
             "sweep_C4": ("C4", lambda f: sweep(f, 8.0)),
             "held_C1": ("C1", lambda f: [0.85 * (f - 1)] * int(3.0 * G.RATE / BLOCK))}
    renders = {}
    for name, (note, positions) in tests.items():
        renders[name] = [G.render(levels[g], NOTES[note], positions(g[0]), BLOCK) / 32768 for g in GEOMETRIES]
    gap = np.zeros(int(GAP * G.RATE))
    for name, rs in renders.items():
        peak = max(np.max(np.abs(r)) for r in rs)           # one gain per file, the same for its four
        joined = np.concatenate([np.concatenate([r * 0.8 / peak, gap]) for r in rs])
        write_wav(a.out / f"{name}.wav", joined)
        print(f"  {name}.wav: {len(joined) / G.RATE:.1f} s ({', '.join(f'{f}x{n}' for f, n in GEOMETRIES)})")
    print(f"  wrote {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

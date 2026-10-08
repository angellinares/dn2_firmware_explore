"""How much mip-mapping removes Waverider's aliasing: the reference readers, before and after.

    python scripts/waverider_mip_alias.py [--out out/waverider]

For each table and each note from C2 to C8 it renders 32,768 samples with the reference
reader (`dnfw.waverider.render`, ideal precision) at level 0, as the DSP plays today, and
on the level `dnfw.waverider.mip` picks, and measures in a Blackman-Harris-windowed FFT:

- **alias**: the power away from the note's harmonics below Nyquist (±6 bins of each,
  DC excluded), relative to the power on them, in dB. Lower is cleaner.
- **kept**: the power on those harmonics after mip-mapping relative to before, in dB: 0 is
  nothing lost; below 0 is the top end a level gives up just above an octave boundary.

The tables (no Elektron data, formulas only): **saw255**, a saw with all 255 harmonics a
512-point frame holds (the worst case: what a bright imported table is like), and the
baked **table 0**'s brightest frame (a 32-harmonic saw). It also writes, for listening,
a run up the keyboard on saw255 (C2 to C8, half a second a note) before and after:
OUT/mip_before.wav and OUT/mip_after.wav.
"""

from __future__ import annotations

import argparse
import math
import pathlib
import struct
import sys
import wave

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from dnfw.waverider import dsp, mip, render  # noqa: E402

RATE = 48000
N = 1 << 15
NOTES = list(range(36, 109, 12))           # C2 .. C8


def saw255() -> list[list[int]]:
    p = np.arange(512) * 2 * np.pi / 512
    s = sum(((-1) ** (h + 1)) * np.sin(h * p) / h for h in range(1, 256))
    frame = [int(v) for v in np.rint(s / np.abs(s).max() * 32000)]
    return [frame] * 16


def note_hz(n: int) -> float:
    return 440.0 * 2 ** ((n - 69) / 12)


def blackman_harris(n: int) -> np.ndarray:
    k = np.arange(n) * 2 * np.pi / (n - 1)
    return 0.35875 - 0.48829 * np.cos(k) + 0.14128 * np.cos(2 * k) - 0.01168 * np.cos(3 * k)


def harmonic_powers(x: np.ndarray, f0: float) -> tuple[float, float]:
    """(power on the harmonics below Nyquist, power elsewhere but DC)."""
    mag2 = np.abs(np.fft.rfft(x * blackman_harris(len(x)))) ** 2
    df = RATE / len(x)
    on = np.zeros(len(mag2), dtype=bool)
    on[: 7] = True                              # DC
    dc = on.copy()
    h = 1
    while h * f0 < RATE / 2:
        c = int(round(h * f0 / df))
        on[max(0, c - 6): c + 7] = True
        h += 1
    harm = mag2[on & ~dc].sum()
    return float(harm), float(mag2[~on].sum())


def play(levels, inc, pos, count, use_mip):
    if use_mip:
        out, _ = mip.render(levels, 0, inc, pos, count)
    else:
        out, _ = render.render(levels[0], 0, inc, pos, count)
    return np.asarray(out)


def write_wav(path: pathlib.Path, samples: np.ndarray) -> None:
    pcm = np.clip(np.rint(samples * 0.5 * 32767), -32768, 32767).astype("<i2").tobytes()
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1), w.setsampwidth(2), w.setframerate(RATE)
        w.writeframes(pcm)


def report(tables, oversample) -> None:
    print(f"{'table':8s} {'note':>5s} {'Hz':>7s} {'level':>5s} {'alias before':>13s} {'alias after':>12s} {'kept':>7s}")
    for name, (table, pos) in tables.items():
        levels = mip.table_levels(table, oversample)
        for n in NOTES:
            f0 = note_hz(n)
            inc = render.increment(f0)
            h0, a0 = harmonic_powers(play(levels, inc, pos, N, False), f0)
            h1, a1 = harmonic_powers(play(levels, inc, pos, N, True), f0)
            db = lambda x, y: 10 * math.log10(max(x, 1e-30) / max(y, 1e-30))
            print(f"{name:8s} {('C' + str(n // 12 - 1)):>5s} {f0:7.1f} {mip.level_for(inc):5d} "
                  f"{db(a0, h0):10.1f} dB {db(a1, h1):9.1f} dB {db(h1, h0):5.1f} dB")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", type=pathlib.Path, default=ROOT / "out/waverider")
    ap.add_argument("--oversample", type=int, nargs="+", default=[mip.OVERSAMPLE],
                    help="points per cycle of a level's top harmonic; several compare them")
    ap.add_argument("--no-wav", action="store_true")
    a = ap.parse_args(argv)
    a.out.mkdir(parents=True, exist_ok=True)
    tables = {"saw255": (saw255(), 0), "table 0": (dsp.tables()[0], 15 << 16)}
    for os_ in a.oversample:
        print()
        print(f"oversample {os_}: {mip.size_bytes(oversample=os_):,} B a table "
              f"(lengths {[mip.points(k, os_) for k in range(mip.LEVELS)]})")
        report(tables, os_)
    if a.no_wav:
        return 0
    levels = mip.table_levels(saw255(), a.oversample[-1])
    before, after = [], []
    for n in range(36, 109):
        inc = render.increment(note_hz(n))
        before.append(play(levels, inc, 0, RATE // 2, False))
        after.append(play(levels, inc, 0, RATE // 2, True))
    write_wav(a.out / "mip_before.wav", np.concatenate(before))
    write_wav(a.out / f"mip_after_os{a.oversample[-1]}.wav", np.concatenate(after))
    print(f"  -> {a.out / 'mip_before.wav'}, {a.out / ('mip_after_os%d.wav' % a.oversample[-1])} "
          "(saw255, C2 to C8, 0.5 s a note)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

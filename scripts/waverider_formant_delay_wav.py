"""Layout A's one-block delay, by ear: the Formant on time, and 32 samples (0.67 ms) late.

    python scripts/waverider_formant_delay_wav.py [--out out/waverider/formant_delay]

Layout A runs IIR0 after the last voice, so the filtered sound of a block comes out in the next
block. The source is the model's oscillator (Prim., 110 Hz, a note at 0.25 s after silence). The
vowel sweeps A to U and back at 0.25 Hz, and the filter is dnfw.waverider.formant (float32,
IIR0's order, the level and the glide). Five files, 4 s each:

- wet_on_time, wet_late: 100 % filtered, on time and one block late (they should sound the same);
- mix50_on_time: half dry, half filtered, both on time;
- mix50_wet_late: the dry on time and the filtered one block late (a comb filter: notches every
  1.5 kHz, from the 0.67 ms between the two);
- mix50_both_late: the dry delayed by one block too, so the two line up again.

Prints, for each mix, the depth of the comb: the level at the notches (1.5, 3, 4.5 kHz) against
the level between them, over the steady part.
"""

from __future__ import annotations

import argparse
import functools
import math
import pathlib
import struct
import sys
import wave

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from dnfw.waverider import dsp, formant, live  # noqa: E402

RATE, BLOCK, SECONDS = 48000, 32, 4.0
level = functools.lru_cache(maxsize=None)(formant.level)   # the DSP will use a table


def source() -> list[float]:
    blocks = int(SECONDS * RATE / BLOCK)
    start = int(0.25 * RATE / BLOCK)
    osc1 = (0, 0, 0x4000, 0x6400, 0x3200, live.MPOS_NONE, 0, 0, 0, 0)
    blk = [(45.0, osc1, (0, 0, 0x4000, 0), (0, b == start, live.PRST_OFF, 0, 0, 0)) for b in range(blocks)]
    y = live.render_two(dsp.tables(), blk, BLOCK)
    return [0.0] * (start * BLOCK) + y[start * BLOCK:]          # silence until the note


def filtered(x: list[float]) -> list[float]:
    out, states, pos = [], [[0.0, 0.0] for _ in range(5)], None
    for k in range(0, len(x), BLOCK):
        t = k / RATE
        target = round(2.0 - 2.0 * math.cos(2 * math.pi * 0.25 * t), 3)   # A..U..A every 4 s
        pos = formant.glide(pos, target, k == 0)
        g = level(round(pos, 3))
        out += [formant._f32(g * v) for v in formant.run(x[k:k + BLOCK], formant.cascade(pos), states)]
    return out


def late(y: list[float]) -> list[float]:
    return [0.0] * BLOCK + y[:-BLOCK]


def comb_depth(y: list[float]) -> float:
    """dB: the level between the notches minus the level at them (1.5, 3 and 4.5 kHz)."""
    seg = np.array(y[int(1.0 * RATE):int(3.5 * RATE)])
    s = np.abs(np.fft.rfft(seg * np.hanning(len(seg)))) ** 2
    f = np.fft.rfftfreq(len(seg), 1 / RATE)
    band = lambda c: 10 * math.log10(s[(f > c - 60) & (f < c + 60)].mean() + 1e-20)
    at = np.mean([band(c) for c in (1500, 3000, 4500)])
    between = np.mean([band(c) for c in (750, 2250, 3750)])
    return between - at


def write(path: pathlib.Path, y: list[float], peak: float) -> None:
    fade = int(0.02 * RATE)                              # 20 ms out, so the file's end does not click
    y = y[:-fade] + [v * (fade - 1 - i) / fade for i, v in enumerate(y[-fade:])]
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(b"".join(struct.pack("<h", round(v / peak * 0.5 * 32767)) for v in y))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", type=pathlib.Path, default=ROOT / "out/waverider/formant_delay")
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    x = source()
    wet = filtered(x)
    g = math.sqrt(sum(v * v for v in x) / sum(v * v for v in wet))          # the dry as loud as the filtered
    dry = [v / g for v in x]
    files = {
        "wet_on_time": wet,
        "wet_late": late(wet),
        "mix50_on_time": [0.5 * (d + w) for d, w in zip(dry, wet)],
        "mix50_wet_late": [0.5 * (d + w) for d, w in zip(dry, late(wet))],
        "mix50_both_late": [0.5 * (d + w) for d, w in zip(late(dry), late(wet))],
    }
    peak = max(max(abs(v) for v in y) for y in files.values())
    for name, y in files.items():
        write(a.out / f"{name}.wav", y, peak)
    print(f"wrote {len(files)} files to {a.out}, {SECONDS:.0f} s each, one scale for all")
    for name in ("mix50_on_time", "mix50_wet_late", "mix50_both_late"):
        print(f"  {name:16} comb depth {comb_depth(files[name]):+.1f} dB (between the notches minus at them)")
    print(f"  wet_late equals wet_on_time shifted by {BLOCK} samples: {files['wet_late'][BLOCK:] == wet[:-BLOCK]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

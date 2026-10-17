"""The Formant type as the DSP plays it, not looped: a WAV to hear before a flash.

    python scripts/waverider_formant_demo_wav.py [--note 48] [--seconds 9]

live.render_two with page 5's TYPE at Formant, which formant.asm matches bit for bit
(scripts/sharc_formant_voice.py). Table 0 at POS 64, osc 1 alone, a note at the start. Three
parts of equal length: AMT sweeps the vowel A to U and back, then P1 sweeps the shift up and
down at the vowel A, then P2 sweeps from wet to dry and back at the vowel A (each part
starts where the last ends, so nothing jumps). Writes
out/waverider/formant_demo.wav (32-bit float, 48 kHz).
"""

from __future__ import annotations

import argparse
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from dnfw.audio import wavio                     # noqa: E402
from dnfw.waverider import dsp, live             # noqa: E402

BLOCK = 32


def tri(x: float) -> float:
    """0 up to 1 and back to 0 as x goes 0..1."""
    return 2 * x if x < 0.5 else 2 - 2 * x


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--note", type=float, default=48.0)
    ap.add_argument("--seconds", type=float, default=9.0)
    a = ap.parse_args(argv)
    n = int(a.seconds * 48000 / BLOCK)
    third = n // 3
    osc1 = (0x4000, 0, 0x4000, 0x6400, 0x3200, live.MPOS_NONE, 0, 0, 0, 0)
    blocks, shapes = [], []
    for b in range(n):
        part, x = divmod(b, third)
        x /= third
        amt, p1, p2 = (round(0x7F00 * tri(x)), 0, 0) if part == 0 else \
            (0, round(127 * tri(x)) << 8, 0) if part == 1 else (0, 0, round(0x7F00 * tri(x)))
        blocks.append((a.note, osc1, (0, 0, 0x4000, 0), (0, b == 0, live.PRST_OFF, 0, 0, 0)))
        shapes.append((0, 0, live.TYPE_FORMANT << 8, amt, 0, 0, p1, p2))
    out = live.render_two(dsp.tables(), blocks, BLOCK, "float32", shapes=shapes)
    path = ROOT / "out/waverider/formant_demo.wav"
    path.parent.mkdir(parents=True, exist_ok=True)
    wavio.write(path, out, 48000, f"Waverider Formant, note {a.note:g}, not looped: AMT A..U..A, then P1 up and down, "
                                  "then P2 wet to dry and back, all at A from 3 s")
    print(path, len(out), "samples")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""The Formant type's two filter forms, by ear: a cascade of five resonators and five band-passes in parallel.

    python scripts/waverider_formant_wav.py [--out out/waverider/formant]

A design aid for docs/waverider-formant.md, not the DSP's code. The source is the model's
oscillator (dnfw.waverider.live.render_two, the reader the DSP matches bit for bit): osc 1 alone
on the baked table TBL at POS, LEV 100, a held note. The vowels are the published bass-voice
formant values (frequency, bandwidth and level of F1 to F5). Each form plays the five vowels
for 0.7 s each, then a sweep from A to U over 2 s. The coefficients change once a block (32
samples), as the DSP would change them.

- cascade: five two-pole resonators in series (Klatt's form, unity gain at 0 Hz). The levels of
  the formants follow from their frequencies and bandwidths; the table's levels are not used.
- parallel: five band-passes (constant 0 dB peak), each times the table's level, added.

Writes dry.wav, cascade.wav and parallel.wav, and cascade_level.wav and parallel_level.wav with a
gain for each vowel (blended as the formants are) so that every vowel is as loud as the loudest, and cascade_model.wav: dnfw.waverider.formant's
float32 cascade in IIR0's order with its level gain (equal power for white noise), what the DSP will compute. The two forms are scaled by one factor each so
that their overall RMS is the same; the vowels keep their levels relative to each other. Prints
each vowel's RMS in each form.
"""

from __future__ import annotations

import argparse
import math
import pathlib
import struct
import sys
import wave

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from dnfw.waverider import dsp, formant, live  # noqa: E402

RATE, BLOCK = 48000, 32
# vowel: (F1..F5 Hz, BW1..BW5 Hz, level dB of F1..F5), bass voice
VOWELS = {
    "A": ((600, 1040, 2250, 2450, 2750), (60, 70, 110, 120, 130), (0, -7, -9, -9, -20)),
    "E": ((400, 1620, 2400, 2800, 3100), (40, 80, 100, 120, 120), (0, -12, -9, -12, -18)),
    "I": ((250, 1750, 2600, 3050, 3340), (60, 90, 100, 120, 120), (0, -30, -16, -22, -28)),
    "O": ((400, 750, 2400, 2600, 2900), (40, 80, 100, 120, 120), (0, -11, -21, -20, -40)),
    "U": ((350, 600, 2400, 2675, 2950), (40, 80, 100, 120, 120), (0, -20, -32, -28, -36)),
}
ORDER = "AEIOU"


def source(seconds: float, table: int, pos: int, note: float) -> list[float]:
    blocks = int(seconds * RATE / BLOCK)
    osc1 = (pos, table << 8, 0x4000, 0x6400, 0x3200, live.MPOS_NONE, 0, 0, 0, 0)
    blk = [(note, osc1, (0, 0, 0x4000, 0), (0, b == 0, live.PRST_OFF, 0, 0, 0)) for b in range(blocks)]
    return live.render_two(dsp.tables(), blk, BLOCK)


def vowel_at(t: float) -> tuple:
    """The formants at time T: each vowel 0.7 s, then a sweep A..U over 2 s (linear blend)."""
    if t < 3.5:
        return VOWELS[ORDER[min(int(t / 0.7), 4)]]
    x = min((t - 3.5) / 2.0, 1.0) * 4
    i = min(int(x), 3)
    a, b, f = VOWELS[ORDER[i]], VOWELS[ORDER[i + 1]], x - i
    return tuple(tuple(p + (q - p) * f for p, q in zip(pa, pb)) for pa, pb in zip(a, b))


def resonator(freq: float, bw: float) -> tuple[float, float, float]:
    c = -math.exp(-2 * math.pi * bw / RATE)
    b = 2 * math.exp(-math.pi * bw / RATE) * math.cos(2 * math.pi * freq / RATE)
    return 1 - b - c, b, c


def bandpass(freq: float, bw: float) -> tuple[float, ...]:
    w = 2 * math.pi * freq / RATE
    alpha = math.sin(w) / (2 * freq / bw)
    a0 = 1 + alpha
    return alpha / a0, 0.0, -alpha / a0, -2 * math.cos(w) / a0, (1 - alpha) / a0


def vowel_weights(t: float) -> dict[str, float]:
    """How much of each vowel is in the blend at time T (vowel_at's weights)."""
    if t < 3.5:
        return {ORDER[min(int(t / 0.7), 4)]: 1.0}
    x = min((t - 3.5) / 2.0, 1.0) * 4
    i = min(int(x), 3)
    return {ORDER[i]: 1 - (x - i), ORDER[i + 1]: x - i}


def render(x: list[float], form: str, level: dict[str, float] | None = None) -> list[float]:
    """LEVEL, a gain per vowel (blended as the formants are), evens out the vowels' loudness."""
    out = [0.0] * len(x)
    state = [[0.0, 0.0, 0.0, 0.0] for _ in range(5)]
    for start in range(0, len(x), BLOCK):
        freqs, bws, levels = vowel_at(start / RATE)
        g = sum(level[v] * w for v, w in vowel_weights(start / RATE).items()) if level else 1.0
        if form == "cascade":
            co = [resonator(f, b) for f, b in zip(freqs, bws)]
            for n in range(start, min(start + BLOCK, len(x))):
                v = x[n]
                for k, (a, b, c) in enumerate(co):
                    s = state[k]
                    y = a * v + b * s[0] + c * s[1]
                    s[1], s[0] = s[0], y
                    v = y
                out[n] = g * v
        else:
            co = [bandpass(f, b) for f, b in zip(freqs, bws)]
            gains = [10 ** (g / 20) for g in levels]
            for n in range(start, min(start + BLOCK, len(x))):
                v, acc = x[n], 0.0
                for k, (b0, b1, b2, a1, a2) in enumerate(co):
                    s = state[k]                            # x1, x2, y1, y2
                    y = b0 * v + b1 * s[0] + b2 * s[1] - a1 * s[2] - a2 * s[3]
                    s[1], s[0], s[3], s[2] = s[0], v, s[2], y
                    acc += gains[k] * y
                out[n] = g * acc
    return out


def render_model(x: list[float]) -> list[float]:
    """The cascade as dnfw.waverider.formant builds and runs it (float32, IIR0's order, its level
    gain): the position follows the same timeline, A=0 .. U=4, the coefficients once a block."""
    out, states = [], [[0.0, 0.0] for _ in range(5)]
    for start in range(0, len(x), BLOCK):
        t = start / RATE
        pos = min(int(t / 0.7), 4) if t < 3.5 else min((t - 3.5) / 2.0, 1.0) * 4
        g = formant.level(pos)
        out += [formant._f32(g * v) for v in formant.run(x[start:start + BLOCK], formant.cascade(pos), states)]
    return out


def rms_db(x: list[float]) -> float:
    return 10 * math.log10(max(sum(v * v for v in x) / max(len(x), 1), 1e-20))


def write(path: pathlib.Path, x: list[float], scale: float) -> None:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(b"".join(struct.pack("<h", max(-32767, min(32767, round(v * scale * 32767)))) for v in x))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", type=pathlib.Path, default=ROOT / "out/waverider/formant")
    ap.add_argument("--table", type=int, default=0, help="the baked table (0: Prim., rich at POS 0)")
    ap.add_argument("--pos", type=lambda s: int(s, 0), default=0)
    ap.add_argument("--note", type=float, default=45.0, help="as the frame carries it: 36 is 65.4 Hz, 45 is 110 Hz")
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    x = source(5.5, a.table, a.pos, a.note)
    forms = {f: render(x, f) for f in ("cascade", "parallel")}
    for f in ("cascade", "parallel"):                      # the same, with a gain per vowel
        y = forms[f]
        rms = {v: rms_db(y[int((i * 0.7 + 0.2) * RATE):int((i + 1) * 0.7 * RATE)]) for i, v in enumerate(ORDER)}
        top = max(rms.values())
        forms[f + "_level"] = render(x, f, {v: 10 ** ((top - r) / 20) for v, r in rms.items()})
    forms["cascade_model"] = render_model(x)          # what the DSP will compute
    target = rms_db(x) - 6
    peak = 0.0
    scales = {}
    for f, y in forms.items():
        scales[f] = 10 ** ((target - rms_db(y)) / 20)
        peak = max(peak, max(abs(v) for v in y) * scales[f])
    trim = min(1.0, 0.7 / peak) if peak else 1.0             # one trim for both: their RMS stays equal
    write(a.out / "dry.wav", x, 0.5 / max(abs(v) for v in x))
    for f, y in forms.items():
        write(a.out / f"{f}.wav", y, scales[f] * trim)
    print(f"wrote dry, cascade, parallel, cascade_level and parallel_level to {a.out}; each 5.5 s: A E I O U (0.7 s each), then A..U")
    for f, y in forms.items():
        cells = []
        for i, v in enumerate(ORDER):
            seg = y[int((i * 0.7 + 0.2) * RATE):int((i + 1) * 0.7 * RATE)]
            cells.append(f"{v} {rms_db(seg) + 20 * math.log10(scales[f]):+.1f}")
        print(f"  {f:8} RMS by vowel (dB, same scale within the form): " + ", ".join(cells))
    return 0


if __name__ == "__main__":
    sys.exit(main())

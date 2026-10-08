"""The reference wavetable reader: what `csrc/waverider/sharc/reader.asm` must compute.

Milestone 1 (`docs/waverider-feasibility.md`) runs our own SHARC code offline
and compares it with this. So this module fixes the **contract**, bit for bit
where it can be:

- **The table in DSP memory** is the baked 16 x 512 int16, frame-major,
  **little-endian** (`dsp_bytes`) -- two samples to a 32-bit word, the even one
  in the low half. The ColdFire build holds the same integers big-endian
  (`bake.to_bytes`); which side swaps is a question for the transfer, not here.
- **Phase** is a u32 accumulator: bits 31..23 index the 512 samples, bits 22..0
  are the fraction to the next one, and it wraps mod 2^32, which is mod 512
  samples. `increment(freq, rate)` gives the step. A shorter frame (a mip level,
  `dnfw.waverider.mip`: 512 >> k points) takes its index from the top 9 - k bits
  and its fraction from the rest; the step and the cycle are the same.
- **Frame position** is Q16: bits 19..16 the frame 0..15, bits 15..0 the
  fraction towards the next frame; frame 15 has no next and interpolates with
  itself.
- **Output** is float, full scale 1.0 = int16 32768.

Two precisions, because they answer different questions:

- `precision="ideal"` is the interpolation in double precision -- what the
  sound *should* be. The gate's max error is measured against it.
- `precision="float32"` rounds after every operation, in the order the SHARC
  code performs them. A DSP that rounds to nearest in single precision should
  match it **exactly**; a mismatch count says whether it does.
"""

from __future__ import annotations

import math
import struct

from . import reduce

PHASE_BITS = 32
INDEX_SHIFT = 23          # bits 31..23 of the phase are the sample index
FRAC_MASK = (1 << INDEX_SHIFT) - 1
POS_ONE = 1 << 16         # Q16 frame position
FULL_SCALE = 32768.0


def dsp_bytes(table: list[list[int]]) -> bytes:
    """-> the table as the SHARC reader expects it: little-endian int16, frame-major."""
    return b"".join(struct.pack("<h", v) for f in table for v in f)


def increment(freq: float, rate: float = 48000.0, points: int = reduce.POINTS) -> int:
    """-> the u32 phase step for `freq` Hz at `rate`, for a `points`-sample cycle.

    The accumulator's full range is one cycle, so the step is freq / rate of it;
    `points` is only checked -- the index width is fixed at 9 bits (512).
    """
    if points != 1 << (PHASE_BITS - INDEX_SHIFT):
        raise ValueError(f"the phase layout is fixed at {1 << (PHASE_BITS - INDEX_SHIFT)} points")
    if not 0 <= freq < rate / 2:
        raise ValueError(f"{freq} Hz is outside 0..{rate / 2} at {rate} Hz")
    return int(round(freq / rate * (1 << PHASE_BITS))) & 0xFFFFFFFF


def position(pos: float, frames: int = reduce.FRAMES) -> int:
    """-> Q16 frame position for a float position 0..frames-1."""
    if not 0 <= pos <= frames - 1:
        raise ValueError(f"position {pos} is outside 0..{frames - 1}")
    return int(round(pos * POS_ONE))


def _f32(x: float) -> float:
    return struct.unpack("<f", struct.pack("<f", x))[0]


def hermite(ym: float, y0: float, y1: float, y2: float, hfr: float, r) -> float:
    """4-point, 3rd-order Hermite (Catmull-Rom) between y0 and y1, the SHARC study's B2,
    in the form reader_miph.asm computes, each operation rounded by R in this order. HFR
    is half the sample fraction (the DSP converts the fraction one power of two lower,
    exactly), so no float constant is needed:

        c3 = ((t + t) + t) + (y2 - ym)              t = y0 - y1      3(y0 - y1) + y2 - ym
        c1 = y1 - ym
        c2 = ((a + a) + ((b + b) + (b + b))) - d    a = ym - y0, b = y1 - y0, d = y2 - y0
        fr = hfr + hfr                              exact
        y  = ((c3 * fr + c2) * fr + c1) * hfr + y0
    """
    t = r(y0 - y1)
    c3 = r(r(r(t + t) + t) + r(y2 - ym))
    c1 = r(y1 - ym)
    a = r(ym - y0)
    a2 = r(a + a)
    bb = r(y1 - y0)
    b2 = r(bb + bb)
    b4 = r(b2 + b2)
    c2 = r(r(a2 + b4) - r(y2 - y0))
    fr = r(hfr + hfr)
    return r(r(r(r(r(r(c3 * fr) + c2) * fr) + c1) * hfr) + y0)


def render(table: list[list[int]], phase: int, inc: int, pos: int, count: int,
           precision: str = "ideal", interp: str = "linear") -> tuple[list[float], int]:
    """-> (`count` samples, the phase after them).

    `phase`, `inc` are u32 (see the module docstring); `pos` is Q16. INTERP is between
    samples: "linear" (the DSP's today), "hermite" (`hermite` on each frame, then the frames
    blended) or "hermite2" (each of the four taps blended between the frames first, then one
    `hermite`: the same curve in exact arithmetic, half the cubics; reader_miph2.asm).
    """
    frames, points = len(table), len(table[0])
    bits = points.bit_length() - 1
    if points != 1 << bits or not 2 <= bits <= PHASE_BITS - INDEX_SHIFT:
        raise ValueError(f"a frame must be a power of two, 4..{1 << (PHASE_BITS - INDEX_SHIFT)} "
                         f"points, not {points}")
    shift = PHASE_BITS - bits                 # 23 at 512 points; a mip level's is wider (dnfw.waverider.mip)
    if not 0 <= pos <= (frames - 1) * POS_ONE:
        raise ValueError(f"position {pos:#x} is outside 0..{(frames - 1) * POS_ONE:#x}")
    if count < 1:
        raise ValueError("count must be at least 1")
    if precision not in ("ideal", "float32"):
        raise ValueError(f"unknown precision {precision!r}")
    if interp not in ("linear", "hermite", "hermite2"):
        raise ValueError(f"unknown interpolation {interp!r}")
    r = _f32 if precision == "float32" else (lambda x: x)
    f0 = pos >> 16
    f1 = min(f0 + 1, frames - 1)
    ff = (pos & 0xFFFF) / POS_ONE           # exact in float32 too
    row0, row1 = table[f0], table[f1]
    out = []
    for _ in range(count):
        k0 = phase >> shift
        k1 = (k0 + 1) % points
        # exact at 512 points (23 bits); a mip level's wider fraction is rounded to float32,
        # as the DSP's FLOAT of it is
        fr = r((phase & ((1 << shift) - 1)) / (1 << shift))
        if interp == "linear":
            s00, s01 = row0[k0] / FULL_SCALE, row0[k1] / FULL_SCALE
            s10, s11 = row1[k0] / FULL_SCALE, row1[k1] / FULL_SCALE
            a = r(s00 + r(fr * r(s01 - s00)))
            b = r(s10 + r(fr * r(s11 - s10)))
        elif interp == "hermite":
            km, k2 = (k0 - 1) % points, (k0 + 2) % points
            hfr = r((phase & ((1 << shift) - 1)) / (1 << (shift + 1)))
            a = hermite(*(row0[k] / FULL_SCALE for k in (km, k0, k1, k2)), hfr, r)
            b = hermite(*(row1[k] / FULL_SCALE for k in (km, k0, k1, k2)), hfr, r)
        else:
            km, k2 = (k0 - 1) % points, (k0 + 2) % points
            hfr = r((phase & ((1 << shift) - 1)) / (1 << (shift + 1)))
            taps = []
            for k in (km, k0, k1, k2):
                sa, sb = row0[k] / FULL_SCALE, row1[k] / FULL_SCALE
                taps.append(r(sa + r(ff * r(sb - sa))))
            out.append(hermite(*taps, hfr, r))
            phase = (phase + inc) & 0xFFFFFFFF
            continue
        out.append(r(a + r(ff * r(b - a))))
        phase = (phase + inc) & 0xFFFFFFFF
    return out, phase


def render_blocks(table: list[list[int]], inc: int, positions: list[int], block: int,
                  phase: int = 0, precision: str = "ideal") -> list[float]:
    """Render one `block` of samples per entry of `positions`, carrying the phase --
    a frame position updated once per block, the way a DSP updates a parameter."""
    out: list[float] = []
    for pos in positions:
        samples, phase = render(table, phase, inc, pos, block, precision)
        out += samples
    return out


def sweep(frames: int, blocks: int) -> list[int]:
    """-> `blocks` Q16 positions sweeping frame 0 to frame `frames`-1 and back."""
    if blocks < 2:
        raise ValueError("a sweep needs at least two blocks")
    top = (frames - 1) * POS_ONE
    half = (blocks - 1) / 2
    return [int(round(top * (1 - abs(k - half) / half))) for k in range(blocks)]


def pcm16(samples: list[float]) -> bytes:
    """-> little-endian int16 PCM, clipped, rounded half away from zero."""
    out = bytearray()
    for v in samples:
        x = max(-1.0, min(32767 / 32768, v)) * FULL_SCALE
        out += struct.pack("<h", int(math.floor(abs(x) + 0.5)) * (1 if x >= 0 else -1))
    return bytes(out)

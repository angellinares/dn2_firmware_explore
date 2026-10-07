"""Page 4's scope, as csrc/ui/scope.c draws it, so a frame can be predicted pixel for pixel.

The trace is a ring of int16 samples (ui/trace_ring.h): a window of `width x SPC` samples
after the latest rising zero crossing in the SEARCH samples before it (armed below
-peak/8), scaled to the peak, each column the min..max of its samples and the last of
the column before. A peak below QUIET draws the centre line. The capture side
(csrc/dn2/audio_tap.c) is mirrored by `track_block`: tracks 1-6 from the SSI0 window,
7-16 from the reply records (docs/waverider-pages34.md)."""

from __future__ import annotations

SPC, SEARCH, QUIET, RING = 8, 512, 64, 2048
BOX = dict(x0=24, x1=121, y0=15, y1=39)          # page.c scope_box: the wave's span


def _div(a: int, b: int) -> int:
    """C's int division: towards zero."""
    q = abs(a) // abs(b)
    return q if (a >= 0) == (b > 0) else -q


def strip(ring: list[int], end: int, x0: int, x1: int, y0: int, y1: int) -> set:
    """ring[i % RING] the samples, end the write count -> the lit pixels (x, y up)."""
    at = lambda i: ring[i % RING]
    w, cy, half = x1 - x0 + 1, (y0 + y1) >> 1, (y1 - y0) >> 1
    span = w * SPC
    start = end - span - SEARCH
    peak = max(abs(at(i)) for i in range(start, end))
    if peak < QUIET:
        return {(x, cy) for x in range(x0, x1 + 1)}
    trig, armed, h = end - span, False, peak >> 3
    for i in range(start, start + SEARCH):
        v = at(i)
        if v < -h:
            armed = True
        elif armed and v >= 0:
            trig, armed = i, False
    lit = set()
    last = _div(at(trig) * half, peak)
    for k in range(w):
        lo = hi = last
        for j in range(SPC):
            y = _div(at(trig + k * SPC + j) * half, peak)
            lo, hi, last = min(lo, y), max(hi, y), y
        lit |= {(x0 + k, cy + y) for y in range(lo, hi + 1)}
    return lit


def s24(b: bytes) -> int:
    v = int.from_bytes(b, "big", signed=True)
    return v - (1 << 24) if v >= 1 << 23 else v


def reply_block(records: bytes, track: int) -> list[int]:
    """Tracks 7..16 (0-based 6..15): 32 records of 84 B -> 32 int16, as audio_tap.c."""
    c = 2 * (track - 6)
    out = []
    for k in range(32):
        r = records[84 * k + 3 * c: 84 * k + 3 * c + 6]
        out.append((s24(r[:3]) + s24(r[3:])) >> 9)
    return out

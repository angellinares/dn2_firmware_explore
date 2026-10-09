"""Waverider's waveform display: the screen's copy of the tables the SHARC plays.

The page (`csrc/waverider/page.c`, M8.1) draws the wave across the middle of the
screen, between the two strips of controls, the way Tonverk's Wavefinder page lays
it out (User Manual OS 1.4.1, p. 94). This module holds the data it draws from:
`dsp.tables()`, the tables baked into section 7, reduced to one **span** per screen
column.

A column is the frame's minimum to its maximum over the points the column stands
for, as a sample editor's overview draws. Point samples cannot show these tables:
at 16 columns the overtone table's 16th partial put every sample on a zero crossing
and drew a flat line (M8, emulator, 2026-10-01). At the strip's width the partial
is about 6 pixels a cycle, and a span still never loses it.

    per frame: WIDTH minima, then WIDTH maxima, signed bytes (-127..127)
    2 tables x 16 frames x 2 x WIDTH bytes

When the tables move to the +Drive (`docs/waverider-tables.md`), this copy is made
at load time instead.

The reader's mapping, which the page reproduces: `TBL1 >> 8` picks the table,
`min(WAV1, 0x7800)` the position across the 16 frames, interpolated between the two
frames either side.

This module is pure: it computes the spans and writes them as C.
"""

from __future__ import annotations

from . import dsp

POS_ID, TBL_ID = 239, 247         # WAV1 (POS) and TBL1 (TBL)
POS2_ID, TBL2_ID = 243, 251       # WAV2 and TBL2: osc 2's, on page 2 (Milestone 9b)
POS_MAX = 0x7800                  # the reader's clamp on WAV1
TABLES = 2
FRAMES = 16
WIDTH = 96                        # screen columns the strip spans


def _byte(v: int) -> int:
    return max(-127, min(127, round(v * 127 / 32767)))


def spans(width: int = WIDTH) -> list[list[tuple[list[int], list[int]]]]:
    """-> [table][frame] = (minima, maxima), `width` signed bytes each. Column c
    covers points floor(c*P/width) .. floor((c+1)*P/width) of a P-point frame, the
    last point shared with the next column so neighbours meet."""
    out = []
    for table in dsp.tables():
        points = len(table[0])
        rows = []
        for frame in table:
            lo, hi = [], []
            for c in range(width):
                a, b = c * points // width, (c + 1) * points // width
                col = [frame[k % points] for k in range(a, b + 1)]
                lo.append(_byte(min(col)))
                hi.append(_byte(max(col)))
            rows.append((lo, hi))
        out.append(rows)
    return out


def c_source() -> str:
    """The spans and the reader's constants, as C for `wr_gen.h`."""
    rows = []
    for table in spans():
        frames = []
        for lo, hi in table:
            frames.append("  {{" + ",".join(map(str, lo)) + "},\n   {" + ",".join(map(str, hi)) + "}}")
        rows.append(" {\n" + ",\n".join(frames) + "\n }")
    return (f"#define WR_POS_ID {POS_ID}\n#define WR_TBL_ID {TBL_ID}\n"
            f"#define WR_POS2_ID {POS2_ID}\n#define WR_TBL2_ID {TBL2_ID}\n"
            f"#define WR_POS_MAX {POS_MAX:#x}\n#define WR_TABLES {TABLES}\n"
            f"#define WR_FRAMES {FRAMES}\n#define WR_WIDTH {WIDTH}\n"
            f"static const signed char wr_spans[WR_TABLES][WR_FRAMES][2][WR_WIDTH] = {{\n"
            + ",\n".join(rows) + "\n};\n")


def _byte_c(v: int) -> int:
    """pool.c's to_byte: v * 127 / 32767 to nearest, halves away from zero (C division)."""
    n = v * 127 + (16383 if v >= 0 else -16383)
    b = abs(n) // 32767 * (1 if n >= 0 else -1)
    return max(-127, min(127, b))


SHOWN = 16                     # the page's frames of a pool table (pool.h: WR_POOL_SPANS)


def shown_frame(d: int, frames: int) -> int:
    """The table frame pool.c shows as frame D: the nearest to d x (F - 1) / 15, the one
    a POS of d plays (`table3.position`)."""
    return (2 * d * (frames - 1) + SHOWN - 1) // (2 * (SHOWN - 1))


def pool_spans(table: list[list[int]], samples: int | None = None, width: int = WIDTH) -> bytes:
    """A pool table's display spans as `csrc/waverider/pool.c` makes them while its
    chunks pass, [shown frame][min, max][column] signed bytes, 16 shown frames whatever
    the table's (`shown_frame`); column c of N points covers c N / 96 .. (c + 1) N / 96, the
    same rounding as C. SAMPLES limits it to the table's first samples (the rest stay at
    pool.c's start, min 127 and max -127)."""
    frames, points = len(table), len(table[0])
    flat = [v for f in table for v in f]
    n = len(flat) if samples is None else samples
    out = [[[127] * width, [-127] * width] for _ in range(SHOWN)]
    starts = [c * points // width for c in range(width + 1)]
    shows = {f: [d for d in range(SHOWN) if shown_frame(d, frames) == f] for f in range(frames)}
    for k in range(n):
        f, p = divmod(k, points)
        if not shows[f]:
            continue
        b = _byte_c(flat[k])
        cols = [max(c for c in range(width) if starts[c] <= p)]
        if p == starts[cols[0]] and cols[0] > 0:
            cols.append(cols[0] - 1)
        if p == 0:
            cols.append(width - 1)
        for d in shows[f]:
            for c in cols:
                out[d][0][c] = min(out[d][0][c], b)
                out[d][1][c] = max(out[d][1][c], b)
    return b"".join(bytes(x & 0xFF for x in lohi) for fr in out for lohi in fr)

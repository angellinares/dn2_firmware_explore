"""Stage 3 tables: the DSP's layout of a mip-mapped table of any geometry, and what its
level builder starts from.

A table is F frames of N points (N a power of two, `geometry`). In the DSP's DDR it is a
header, then every level one after another, each frame-major, each row guarded for
hermite2 ([last, x0 .. x(L-1), x0, x1], `mip.row_points`), little-endian int16:

    +0x000  F                      frames
    +0x004  float32 S              the position's scale: POS (0 .. 15 frames, Q16) x S
    +0x008  F - 1                  the last frame
    +0x00c  K - 1                  the thresholds the reader tests (K levels)
    +0x010  T[0 .. 15]             a block plays level k while inc < T[k] (`thresholds`)
    +0x050  record[0 .. K-1]       32 bytes each, `mip.level_records`'s words; word 0 the
                                   level's byte offset from the table's first byte
    +0x400  the rows

reader_miph2.asm reads the table pointer with bit 0 set as one of these: the baked tables
(16 x 512, S = 1) and the pool's, which build3.asm builds on the DSP when they load.

**The position.** POS is 0 .. 15 frames in Q16 whatever the table (the loop's
`min(WAV1, 0x7800) << 5`), so the reader scales it: pos = trunc(f32(POS) x S), S =
f32((F - 1) / 15) rounded up (`scale`), exact for F = 16 (S = 1). `position` is the model.

**The templates** (`templates`): per frame length N = 64 .. 4096, what the builder copies
into a table's header and what it walks to build it: the header with F = 1 and each
record's word 0 the bytes a frame takes before level k (the builder writes 0x400 + F x
that), then per level a build row (L, log2 L, H, a row's bytes). `scales` is S per F.

Pure: numbers in, numbers out.
"""

from __future__ import annotations

import struct

import numpy as np

from . import geometry as G
from . import mip

HEADER_BYTES = 0x400
THRESHOLDS = 16                       # T[0..15]: up to 17 levels (N up to 2^18)
RECORDS_AT = 0x50
RECORD_BYTES = 32
POS_FRAMES = 15                       # POS spans 0 .. 15 frames
GUARDS = mip.GUARD_BEFORE + mip.GUARD_AFTER

# What the pool plays (pool.c's gate, store.h): Tonverk's geometries
MIN_POINTS, MAX_POINTS = 64, 4096
MAX_FRAMES = 64

# templates: one block of TEMPLATE_BYTES per N, by log2 N - 6
TEMPLATE_BYTES = 0x400
TEMPLATE_HEADER = RECORDS_AT + RECORD_BYTES * 15      # the header part the builder copies (K <= 15)
BUILD_ROWS_AT = 0x240                                 # then 16 bytes a level: L, log2 L, H, row bytes
TEMPLATE_SIZES = tuple(1 << b for b in range(MIN_POINTS.bit_length() - 1, MAX_POINTS.bit_length()))


def _f32(x: float) -> float:
    return struct.unpack("<f", struct.pack("<f", x))[0]


def playable(frames: int, points: int) -> bool:
    """The geometries the pool builds and plays."""
    return 1 <= frames <= MAX_FRAMES and MIN_POINTS <= points <= MAX_POINTS and points & (points - 1) == 0


def scale(frames: int) -> float:
    """f32 (F - 1) / 15, rounded up when inexact, so POS 15 frames lands on frame F - 1
    itself (and never past it: the excess is under half a Q16 step)."""
    s = np.float32((frames - 1) / POS_FRAMES)
    if float(s) * POS_FRAMES < frames - 1:
        s = np.nextafter(s, np.float32(np.inf))
    return float(s)


def position(pos: int, frames: int) -> int:
    """The reader's Q16 frame position for POS (0 .. 15 << 16) in a table of FRAMES."""
    return int(np.trunc(np.float32(pos) * np.float32(scale(frames))))


def row_bytes(points: int, level: int) -> int:
    return 2 * (G.level_points(points, level) + GUARDS)


def frame_bytes_before(points: int, level: int) -> int:
    """A frame's bytes in the levels before LEVEL (each level is frame-major)."""
    return sum(row_bytes(points, k) for k in range(level))


def level_offset(frames: int, points: int, level: int) -> int:
    return HEADER_BYTES + frames * frame_bytes_before(points, level)


def size_bytes(frames: int, points: int) -> int:
    return level_offset(frames, points, G.levels(points))


def thresholds(points: int, limit_hz: int = G.LIMIT_HZ) -> list[int]:
    """T[k], k = 0 .. K-2: ceil(limit / top harmonic of level k), in phase units."""
    lim = limit_hz * (1 << 32) // G.RATE
    return [-(-lim // G.top_harmonic(points, k)) for k in range(G.levels(points) - 1)]


def _records(points: int, offsets: list[int]) -> bytes:
    out = b""
    for k, off in enumerate(offsets):
        b = G.level_points(points, k).bit_length() - 1
        one = 1 << (32 - b)
        out += struct.pack("<IIiIIiiI", off, b + 1, -(33 - b), one, one - 1, -(32 - b), -(33 - b), 0)
    return out


def header(frames: int, points: int) -> bytes:
    k = G.levels(points)
    t = thresholds(points)
    out = bytearray(HEADER_BYTES)
    struct.pack_into("<IfII", out, 0, frames, scale(frames), frames - 1, k - 1)
    struct.pack_into(f"<{len(t)}I", out, 0x10, *t)
    rec = _records(points, [level_offset(frames, points, j) for j in range(k)])
    out[RECORDS_AT:RECORDS_AT + len(rec)] = rec
    return bytes(out)


def dsp_bytes(levels: list) -> bytes:
    """levels[k] (frames x L_k, ints) -> the table as the DSP keeps it: header, rows."""
    frames, points = len(levels[0]), len(levels[0][0])
    rows = [[int(f[-1])] + [int(v) for v in f] + [int(v) for v in f[:mip.GUARD_AFTER]]
            for level in levels for f in level]
    return header(frames, points) + b"".join(struct.pack(f"<{len(r)}h", *r) for r in rows)


def template(points: int) -> bytes:
    """build3.asm's template for frames of POINTS: the header part (F = 1, record word 0 a
    frame's bytes before the level), then a build row per level."""
    k = G.levels(points)
    if k > 15:
        raise ValueError("more than 15 levels")
    out = bytearray(header(1, points)[:TEMPLATE_HEADER] + bytes(TEMPLATE_BYTES - TEMPLATE_HEADER))
    for j in range(k):
        struct.pack_into("<I", out, RECORDS_AT + RECORD_BYTES * j, frame_bytes_before(points, j))
        size = G.level_points(points, j)
        struct.pack_into("<IIII", out, BUILD_ROWS_AT + 16 * j, size, size.bit_length() - 1,
                         G.top_harmonic(points, j), row_bytes(points, j))
    return bytes(out)


def templates() -> bytes:
    return b"".join(template(n) for n in TEMPLATE_SIZES)


def scales() -> bytes:
    """S for F = 1 .. MAX_FRAMES, float32 each (entry F - 1)."""
    return struct.pack(f"<{MAX_FRAMES}f", *(scale(f) for f in range(1, MAX_FRAMES + 1)))


def build_header(tmpl: bytes, frames: int) -> bytes:
    """What build3.asm writes from a template: the model of its header copy."""
    out = bytearray(tmpl[:TEMPLATE_HEADER] + bytes(HEADER_BYTES - TEMPLATE_HEADER))
    k = struct.unpack_from("<I", out, 0x0C)[0] + 1
    struct.pack_into("<IfI", out, 0, frames, scale(frames), frames - 1)
    for j in range(k):
        at = RECORDS_AT + RECORD_BYTES * j
        struct.pack_into("<I", out, at, HEADER_BYTES + frames * struct.unpack_from("<I", out, at)[0])
    return bytes(out)


class Table3(list):
    """A stage 3 table as the reader plays it: its frames (a list, as everywhere else)
    and its levels as built (LEVELS[k]: frames x L_k ints, the DSP's own when read back
    from it). `read` is reader_miph2.asm's model for it."""

    def __init__(self, levels):
        super().__init__([list(f) for f in levels[0]])
        self.levels = [[list(map(int, f)) for f in lv] for lv in levels]
        self.frames, self.points = len(levels[0]), len(levels[0][0])

    @classmethod
    def from_dsp(cls, data: bytes) -> "Table3":
        """The DSP's bytes of a table (`dsp_bytes`'s layout) -> its levels."""
        frames, _, _, k1 = struct.unpack_from("<IfII", data, 0)
        out = []
        for k in range(k1 + 1):
            off, b1 = struct.unpack_from("<II", data, RECORDS_AT + RECORD_BYTES * k)
            size = 1 << (b1 - 1)
            rows = np.frombuffer(data, "<i2", frames * (size + GUARDS), off).reshape(frames, size + GUARDS)
            out.append(rows[:, mip.GUARD_BEFORE:mip.GUARD_BEFORE + size].tolist())
        return cls(out)


def level_for(inc: int, points: int) -> int:
    """The reader's level for phase increment INC: the first k with inc < T[k], else the last."""
    for k, t in enumerate(thresholds(points)):
        if (inc & 0xFFFFFFFF) < t:
            return k
    return G.levels(points) - 1


def read(table: Table3, phase: int, inc: int, pos: int, count: int, precision: str = "ideal"):
    """What reader_miph2.asm plays for TABLE: POS (0 .. 15 frames, Q16) scaled to its
    frames, the level by its thresholds, hermite2 between the samples."""
    from . import render as reader  # noqa: PLC0415
    return reader.render(table.levels[level_for(inc, table.points)], phase, inc,
                         position(pos, table.frames), count, precision, "hermite2")

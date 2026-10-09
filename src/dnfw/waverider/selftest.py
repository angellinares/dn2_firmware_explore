"""A diagnostic DSP stream: does the stage 3 FFT run on the DSP as it runs in the emulator?

    section7_selftest(stock) -> stock DN2 1.11's section 7, plus the idle-time stub
        (`dsp.section7_idle_only`), plus selftest.asm (in the idle loop's back edge, as
        ddrscan.asm), fft3.asm and spec3.asm, and the test's data in DDR.

selftest.asm runs the whole level build for two frames of N points every idle call
(`csrc/waverider/sharc/selftest.asm`): fft3 forward, spec3's split, a join and an
inverse fft3 per level (`geometry.level_points`, `geometry.top_harmonic`), and folds
every output word into a hash. The host reads the first run's hash (REF), the latest, a
count of runs that differed from REF and the cycles of each phase through reply word 2
(`tools/dn2selftest.py`); scripts/sharc_selftest_check.py runs the same code in the
emulator for the hash REF must equal.

The data (two frames, the twiddle tables) loads with the stream; the arrays the code
writes are in DDR past the stock image, each 4 N bytes and 1 KB of slack apart (fft3's
loads run ahead), the sources aligned to 4 N bytes as fft3 needs.
"""

from __future__ import annotations

import json
import pathlib
import struct

import numpy as np

from dnfw.image import bootstream, sharc_object
from dnfw.waverider import dsp
from dnfw.waverider import geometry as G

POINTS = 256
SEED = 2026_10_09
CODE_DM = 0x2DF000                      # selftest.asm, after idle_load.asm's padding
CODE_SW = CODE_DM // 2                  # 0x16f800, ddrscan.asm's: the same back-edge JUMP
STATE_DM = 0x2DF800                     # saves, hash, cycles, PUB
STATE_BYTES = 0x100
TEST_DM = 0x2DF900                      # the test block: sizes, array addresses, level rows
TEST_BYTES = 0x140
PUB_DM = STATE_DM + 0xC0
PUB_ENTRIES = 16
PUB_NAMES = ("runs", "differs", "ref lo", "ref hi", "hash lo", "hash hi",
             "forward cycles", "split cycles", "fft3 h after the forward", "run cycles",
             "STKYX", "PCSTKP", "MODE1", "L6", "L7", "a 10-iteration loop counted")
FFT3_DM, SPEC3_DM = 0x2E2000, 0x2E2800  # their PLACEMENT IS FIXED lines
SPEC3_JOIN_SW = 0x171469                # selftest.asm's CALL; checked against spec3.json
SHARC = pathlib.Path(__file__).resolve().parents[3] / "csrc" / "waverider" / "sharc"
ARRAYS = ("src_re", "src_im", "dst_re", "dst_im", "twr", "twi", "ar", "ai", "br", "bi", "zr", "zi")


def layout(points: int = POINTS) -> dict[str, int]:
    """Each array's DDR byte address, a 4 N + 1 KB stride from Waverider's DDR region's
    start, rounded to 4 N bytes (fft3's source alignment; the inverse's source is ZI)."""
    n = 4 * points
    stride = (n + 1024 + n - 1) // n * n
    return {name: dsp.DDR_REGION[0] + k * stride for k, name in enumerate(ARRAYS)}


def frames(points: int = POINTS) -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(SEED)
    return (rng.standard_normal(points).astype(np.float32),
            rng.standard_normal(points).astype(np.float32))


def twiddles(points: int = POINTS) -> tuple[np.ndarray, np.ndarray]:
    """fft3.asm's tables: entry h + k = (cos, -sin)(pi k / h) for each half-width h < N."""
    wr, wi = np.zeros(points, np.float32), np.zeros(points, np.float32)
    h = 1
    while h < points:
        a = np.pi * np.arange(h) / h
        wr[h:2 * h], wi[h:2 * h] = np.cos(a), -np.sin(a)
        h *= 2
    return wr, wi


def test_block(points: int = POINTS) -> bytes:
    """selftest.asm's test block at TEST_DM: N, log2 N, the level count, the twelve array
    addresses, then a 16-byte row per level k >= 1: L, log2 L, H, 0."""
    at = layout(points)
    rows = [(G.level_points(points, k), G.level_points(points, k).bit_length() - 1, G.top_harmonic(points, k))
            for k in range(1, G.levels(points))]
    out = bytearray(TEST_BYTES)
    struct.pack_into("<III", out, 0, points, points.bit_length() - 1, len(rows))
    struct.pack_into("<12I", out, 12, *(at[a] for a in ARRAYS))
    for k, (size, bits, top) in enumerate(rows):
        struct.pack_into("<IIII", out, 0x40 + 16 * k, size, bits, top, 0)
    return bytes(out)


def _object(name: str) -> tuple[bytes, dict]:
    spec = json.loads((SHARC / f"{name}.json").read_text(encoding="utf-8"))
    return sharc_object.load_bytes(bytes.fromhex(spec["object_parcels_be"])), spec


def _labels(name: str) -> dict[str, int]:
    """name.asm's labels -> sw, from its committed .json's instruction offsets."""
    spec = json.loads((SHARC / f"{name}.json").read_text(encoding="utf-8"))
    out, k = {}, 0
    for t in (ln.split("//", 1)[0].strip() for ln in (SHARC / f"{name}.asm").read_text(encoding="utf-8").splitlines()):
        if not t or t.startswith("."):
            continue
        if t.endswith(":"):
            out[t[:-1]] = k
            continue
        k += 1
    base = int(spec["load_sw"], 16)
    return {lab: base + spec["instruction_offsets"][i] // 2 for lab, i in out.items()
            if i < len(spec["instruction_offsets"])}


def section7_selftest(stock: bytes, points: int = POINTS) -> bytes:
    """Stock + the idle stub + selftest.asm (the idle loop's back edge goes to it, and it
    goes on to the idle stub) + fft3.asm + spec3.asm + the test's data."""
    if _labels("spec3")["wr_spec3_join."] != SPEC3_JOIN_SW:
        raise dsp.DspError("selftest.asm's CALL to wr_spec3_join is stale: spec3.asm moved it")
    code, _ = _object("selftest")
    fft3, _ = _object("fft3")
    spec3, _ = _object("spec3")
    from dnfw.waverider import ddrscan                   # the same back-edge JUMP (to 0x16f800)
    jump = ddrscan.objects()["scan_jump"]
    if STATE_DM - CODE_DM - len(code) < 64:
        raise dsp.DspError("selftest.asm leaves fewer than 64 bytes before its state block")
    if len(fft3) > SPEC3_DM - FFT3_DM or SPEC3_DM + len(spec3) > 0x2E4000:
        raise dsp.DspError("fft3/spec3 overrun their placements")
    at = layout(points)
    fa, fb = frames(points)
    wr, wi = twiddles(points)
    added = [("selftest.asm", dsp.dm_to_load(CODE_DM), code + bytes(STATE_DM - CODE_DM - len(code))),
             ("selftest state", dsp.dm_to_load(STATE_DM), bytes(STATE_BYTES)),
             ("selftest test block", dsp.dm_to_load(TEST_DM), test_block(points)),
             ("fft3.asm", dsp.dm_to_load(FFT3_DM), fft3),
             ("spec3.asm", dsp.dm_to_load(SPEC3_DM), spec3)]
    dsp._check_free(stock, added)
    data = [(at["src_re"], fa), (at["src_im"], fb), (at["twr"], wr), (at["twi"], wi)]
    extra = b"".join(bootstream.block(where, payload) for _, where, payload in added) + \
        b"".join(bootstream.block(where, arr.astype("<f4").tobytes()) for where, arr in data)
    out = bytearray(bootstream.insert_before_final(dsp.section7_idle_only(stock), extra))
    bootstream.write_span(out, dsp.l2_sw_to_load(dsp.IDLE_SITE_SW), jump)
    return dsp._finish(out)


def decode(word: int) -> tuple[int, int]:
    """A reply word 2 as the ColdFire reads it (big-endian u32) -> (PUB index, value)."""
    return word >> 27, word & 0x7FFFFFF

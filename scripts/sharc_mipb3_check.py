"""A table's mip levels built on the DSP (mipb3 + fft3 + spec3) in digikit's SHARC runner, against the model.

    python scripts/sharc_mipb3_check.py [--frames 4] [--points 2048] [--where l1|ddr]

The table is FRAMES frames of N int16 (saws near full scale, so the band-limited levels
overshoot and the clip is exercised, plus a little noise). For each pair of frames:
mipb3's in (int16 to split floats), fft3 forward, spec3's split, level 0 out from the
floats (S = 0), then per level k >= 1 spec3's join, an inverse fft3 and mipb3's out (S =
log2 N + 1), each row [last, x0 .. x(L-1), x0, x1] as the reader reads it, the levels one
after another, each frame-major. The model: geometry.frame_levels, rounded (np.rint) and
clipped to int16 (as dnfw.waverider.mip). Prints rows that differ, the largest difference
(a float32 transform rounds a value on the other side of .5 now and then: 1 LSB is the
gate) and the cycles.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
import tempfile

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import sharc_fft3_check as K                                    # noqa: E402
import sharc_levels3_check as V                                 # noqa: E402
from dnfw import progress, sharcemu                             # noqa: E402
from dnfw.image import bootstream, sharc_object                 # noqa: E402
from dnfw.sharccycles import costs as C                         # noqa: E402
from dnfw.waverider import dsp                                  # noqa: E402
from dnfw.waverider import geometry as G                        # noqa: E402

F, m5 = K.F, K.m5
MIPB3_DM = dsp.MIPB3_DM
PB = 0x2E40C0                                    # mipb3.asm's parameter block
GUARDS = 3


def stream(stock: bytes) -> bytes:
    blocks = b""
    for name, dm in (("fft3", K.FFT3_DM), ("spec3", V.SPEC3_DM), ("mipb3", MIPB3_DM)):
        code = sharc_object.load_bytes(bytes.fromhex(json.loads((K.SHARC / f"{name}.json").read_text())["object_parcels_be"]))
        blocks += bootstream.block(dsp.dm_to_load(dm), code)
    return bootstream.insert_before_final(dsp.section7_idle_only(stock), blocks)


def table(frames: int, n: int) -> np.ndarray:
    rng = np.random.default_rng(21)
    t = np.arange(n) / n
    rows = []
    for f in range(frames):
        saw = 2 * ((t * (1 + f % 3) + f / frames) % 1.0) - 1
        rows.append(np.clip(np.rint(31000 * saw + 600 * rng.standard_normal(n)), -32768, 32767))
    return np.array(rows, dtype=np.int16)


def model_rows(tab: np.ndarray) -> list[np.ndarray]:
    """levels[k]: frames x (L + 3) int16, each row [last, x.., x0, x1]."""
    per = [G.frame_levels(f.astype(float)) for f in tab]
    out = []
    for k in range(len(per[0])):
        lv = np.clip(np.rint(np.array([p[k] for p in per])), -32768, 32767).astype(np.int64)
        out.append(np.concatenate([lv[:, -1:], lv, lv[:, :2]], axis=1))
    return out


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--image", type=pathlib.Path, default=ROOT / "00_Resources/00_Firmware/Digitone_II_OS1.11_dist.zip")
    p.add_argument("--digikit", type=pathlib.Path, default=sharcemu.path())
    p.add_argument("--frames", type=int, default=4)
    p.add_argument("--points", type=int, default=2048)
    p.add_argument("--where", choices=("ddr", "l1"), default="l1")
    a = p.parse_args(argv)
    from sharc_bus_check import BusCheck             # noqa: PLC0415
    n, nf = a.points, a.frames
    if nf % 2:
        p.error("an even number of frames")
    dk = m5.m1.Digikit(a.digikit)
    m5.fx.bind(str(a.digikit / "tools"))
    m5.m4.IMAGE = a.image
    stock = m5.m1.dn2_section7(a.image)
    image = m5.Image(dk, stream(stock))
    sw3, swb = V.labels("spec3"), V.labels("mipb3")
    costs = C.load(K.F.COSTS)
    at = V.arrays(n, a.where)
    tab = table(nf, n)
    want = model_rows(tab)
    sizes = [G.level_points(n, k) for k in range(G.levels(n))]
    offsets = np.cumsum([0] + [2 * nf * (s + GUARDS) for s in sizes[:-1]])
    out_base = 0x80B00000                         # the levels (DDR)
    tab_base = 0x80A80000                         # the table (DDR)
    totals: dict[str, float] = {}

    def call(r, entry, what):
        r = r.fresh_call(entry, return_address=F.RETURN)
        with BusCheck(m5.fx) as rec:
            res = m5.fx.run(r, 50_000_000, m5.fixups({}), stop_at=(F.RETURN,))
        if rec.count:
            raise SystemExit(f"{what}: " + rec.report())
        if res[0] != "stop":
            raise SystemExit(f"{what} at {entry:#x}: {res[0]} {res[1]}")
        cycles, _, _ = C.estimate(dict(rec.model.counts), costs)
        totals[what] = totals.get(what, 0) + cycles
        return r

    def poke(st, block, pairs):
        for off, v in pairs:
            m5.m2.poke(st, block + off, v)

    def fft(st, m, sre, sim, dre, dim):
        poke(st, K.P3, ((0, sre), (4, sim), (8, dre), (12, dim), (16, m), (20, m.bit_length() - 1),
                        (24, at["twr"]), (28, at["twi"])))

    def out(r, src, size, row, s, bus="DM"):
        poke(r.state, PB, ((20, src), (24, size), (28, row), (32, s)))
        return call(r, swb["wr_mipb3_out." if bus == "DM" else "wr_mipb3_out_pm."], "out")

    with progress.Job("mipb3 check", total=nf // 2) as job, tempfile.TemporaryDirectory(dir=m5.OUT) as tmp:
        snap, m2mach = m5.snapshot_path(dk, stock, pathlib.Path(tmp))
        r = m5.init_on(snap, m2mach, image)
        wr, wi = K.twiddles(n)
        F.poke_floats(r.state, at["twr"], np.concatenate([wr, np.zeros(16, np.float32)]))
        F.poke_floats(r.state, at["twi"], np.concatenate([wi, np.zeros(16, np.float32)]))
        raw = tab.astype("<i2").tobytes()
        for k in range(0, len(raw), 4):
            m5.m2.poke(r.state, tab_base + k, int.from_bytes(raw[k:k + 4], "little"))
        for f in range(0, nf, 2):
            job.update(step=f"frames {f}, {f + 1}")
            poke(r.state, PB, ((0, tab_base + 2 * n * f), (4, tab_base + 2 * n * (f + 1)), (8, n),
                               (12, at["src_re"]), (16, at["src_im"])))
            r = call(r, swb["wr_mipb3_in."], "in")
            fft(r.state, n, at["src_re"], at["src_im"], at["dst_re"], at["dst_im"])
            r = call(r, K.FFT3_SW, "forward")
            V_spec = ((0, at["dst_re"]), (4, at["dst_im"]), (8, n), (12, at["ar"]), (16, at["ai"]),
                      (20, at["br"]), (24, at["bi"]))
            poke(r.state, V.PS, V_spec)
            r = call(r, sw3["wr_spec3_split."], "split")
            row = lambda k, fr: out_base + int(offsets[k]) + 2 * fr * (sizes[k] + GUARDS)
            r = out(r, at["src_re"], n, row(0, f), 0)
            r = out(r, at["src_im"], n, row(0, f + 1), 0, "PM")
            for k in range(1, G.levels(n)):
                L, H = sizes[k], G.top_harmonic(n, k)
                poke(r.state, V.PS, ((0, at["zr"]), (4, at["zi"]), (8, L), (12, at["ar"]), (16, at["ai"]),
                                     (20, at["br"]), (24, at["bi"]), (28, H)))
                r = call(r, sw3["wr_spec3_join."], "join")
                fft(r.state, L, at["zr"], at["zi"], at["dst_re"], at["dst_im"])   # join wrote i conj Z
                r = call(r, K.FFT3_SW, "inverse")
                r = out(r, at["dst_im"], L, row(k, f), n.bit_length(), "PM")        # frame a: the imaginary part
                r = out(r, at["dst_re"], L, row(k, f + 1), n.bit_length())
            job.advance()
        worst, bad_rows, rows = 0, 0, 0
        for k in range(G.levels(n)):
            width = sizes[k] + GUARDS
            for fr in range(nf):
                base = out_base + int(offsets[k]) + 2 * fr * width
                got = np.array([m5.m2.word(r.state, (base + 2 * j) & ~3) >> (16 * ((base + 2 * j) & 2 and 1))
                                for j in range(width)], dtype=np.uint32).astype(np.uint16).astype(np.int16)
                d = np.abs(got.astype(np.int64) - want[k][fr])
                rows += 1
                worst = max(worst, int(d.max()))
                bad_rows += int(d.max() > 1)
    print(f"  {nf} frames x {n}, {G.levels(n)} levels: {rows} rows, largest difference {worst} LSB, "
          f"rows over 1 LSB: {bad_rows}")
    per_frame = {k: v / nf for k, v in totals.items()}
    print("  cycles a frame: " + ", ".join(f"{k} ~{v:,.0f}" for k, v in per_frame.items())
          + f"; all ~{sum(per_frame.values()):,.0f}")
    ok = worst <= 1
    print("  PASS" if ok else "  FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

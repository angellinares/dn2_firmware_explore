"""fft.asm in digikit's SHARC runner: it computes numpy's FFT, and what it costs.

    python scripts/sharc_fft_check.py [--sizes 16 256 2048] [--where ddr|l1]

Assembles nothing: reads csrc/waverider/sharc/fft.json (scripts/build_fft.py --assemble
writes it). Builds stock + the idle stub (`dsp.section7_idle_only`) plus fft.asm at sw
0x16f800, its twiddle table (NMAX 4096) at DM 0x2e0000 and its parameter block at
0x2e4000, then, on the engine-init snapshot, for each size N and both directions:
writes N random complex floats, calls wr_fft, and checks the result against numpy (the
inverse unscaled, x N). Prints the instructions and the cycle model's estimate
(dnfw.sharccycles, data/sharc_cycles/costs.json) per call, and what building the levels
of a 64-frame table at N points would cost from them (`geometry.level_points`: one
forward transform of N, one inverse per level after level 0, which is the frame itself).
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import struct
import sys
import tempfile

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import sharc_waverider_m5 as m5                                # noqa: E402
from dnfw.image import bootstream, sharc_object                 # noqa: E402
from dnfw.sharccycles import costs as C                         # noqa: E402
from dnfw.waverider import dsp                                  # noqa: E402
from dnfw.waverider import geometry as G                        # noqa: E402
from dnfw import sharcemu  # noqa: E402

FFT_SW, FFT_DM = 0x16F800, 0x2DF000
TW_DM, NMAX = 0x2E0000, 4096
PARAMS_DM = 0x2E4000
DATA = {"ddr": 0x80A00000, "l1": 0x2E4100}
RETURN = dsp.IDLE_RETURN_SW
CODE = ROOT / "csrc" / "waverider" / "sharc" / "fft.json"
COSTS = ROOT / "data" / "sharc_cycles" / "costs.json"


def twiddles() -> bytes:
    t = np.arange(NMAX // 2)
    a = 2 * np.pi * t / NMAX
    return np.column_stack([np.cos(a), -np.sin(a)]).astype("<f4").tobytes()


def stream(stock: bytes) -> bytes:
    code = sharc_object.load_bytes(bytes.fromhex(json.loads(CODE.read_text())["object_parcels_be"]))
    base = dsp.section7_idle_only(stock)
    extra = (bootstream.block(dsp.dm_to_load(FFT_DM), code + bytes(0x800 - len(code)))
             + bootstream.block(dsp.dm_to_load(TW_DM), twiddles()))
    return bootstream.insert_before_final(base, extra)


def poke_floats(st, at: int, values: np.ndarray) -> None:
    for k, w in enumerate(np.asarray(values, dtype="<f4").view("<u4")):
        m5.m2.poke(st, at + 4 * k, int(w))


def read_floats(st, at: int, n: int) -> np.ndarray:
    return np.array([m5.m2.word(st, at + 4 * k) or 0 for k in range(n)], dtype="<u4").view("<f4")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--image", type=pathlib.Path, default=ROOT / "00_Resources/00_Firmware/Digitone_II_OS1.11_dist.zip")
    p.add_argument("--digikit", type=pathlib.Path,
                   default=sharcemu.path())
    p.add_argument("--sizes", type=int, nargs="+", default=[16, 256, 2048])
    p.add_argument("--where", choices=sorted(DATA), default="ddr")
    a = p.parse_args(argv)
    from sharc_cycles_recorder import Recorder       # noqa: PLC0415
    dk = m5.m1.Digikit(a.digikit)
    m5.fx.bind(str(a.digikit / "tools"))
    m5.m4.IMAGE = a.image
    stock = m5.m1.dn2_section7(a.image)
    image = m5.Image(dk, stream(stock))
    table = C.load(COSTS)
    rng = np.random.default_rng(7)
    data = DATA[a.where]
    per = {}
    ok_all = True
    with tempfile.TemporaryDirectory(dir=m5.OUT) as tmp:
        snap, m2mach = m5.snapshot_path(dk, stock, pathlib.Path(tmp))
        for n in a.sizes:
            for sign in (1.0, -1.0):
                init = m5.init_on(snap, m2mach, image)
                st = init.state
                x = (rng.standard_normal(n) + 1j * rng.standard_normal(n)).astype(np.complex64)
                poke_floats(st, data, np.column_stack([x.real, x.imag]).ravel())
                for off, v in ((0, data), (4, n), (8, TW_DM), (12, NMAX * 4)):
                    m5.m2.poke(st, PARAMS_DM + off, v)
                m5.m2.poke(st, PARAMS_DM + 16, int(np.array(sign, "<f4").view("<u4")))
                r = init.fresh_call(FFT_SW, return_address=RETURN)
                with Recorder(m5.fx) as rec:
                    res = m5.fx.run(r, 50_000_000, m5.fixups({}), stop_at=(RETURN,))
                y = read_floats(r.state, data, 2 * n).reshape(-1, 2)
                y = y[:, 0] + 1j * y[:, 1]
                want = np.fft.fft(x) if sign > 0 else np.fft.ifft(x) * n
                err = np.max(np.abs(y - want)) / np.max(np.abs(want))
                counts = dict(rec.model.counts)
                cycles, _, unpriced = C.estimate(counts, table)
                ok = res[0] != "max" and err < 1e-5
                ok_all &= ok
                per[(n, sign)] = (counts.get("instructions", 0), cycles)
                print(f"  N {n:5d} {'forward' if sign > 0 else 'inverse'}: {res[0]:>8s}  max error {err:.2e}  "
                      f"instructions {counts.get('instructions', 0):>9,}  cycles ~{cycles:>11,.0f}  "
                      f"{'PASS' if ok else 'FAIL'}" + (f"  (unpriced {unpriced})" if unpriced else ""))
    # a 64-frame table at the largest size measured: forward N, then one inverse per level
    n = max(a.sizes)
    sizes = [G.level_points(n, k) for k in range(G.levels(n))]
    known = {k[0] for k in per}
    if all(s in known for s in sizes[1:]):
        inv = sizes[1:]                          # level 0 is the frame itself: no transform back
        cyc = per[(n, 1.0)][1] + sum(per[(s, -1.0)][1] for s in inv)
        print(f"  levels of one {n}-point frame (forward {n}, inverses {inv}): ~{cyc:,.0f} cycles; "
              f"a 64-frame table ~{64 * cyc / 1e6:.1f} M cycles = {64 * cyc / 1e9 * 1000:.0f} ms of the 1 GHz core")
    else:
        fwd = per[(n, 1.0)][1]
        print(f"  (measure the level sizes {sorted(set(sizes))} too for a table's total; one {n}-point forward ~{fwd:,.0f} cycles)")
    return 0 if ok_all else 1


if __name__ == "__main__":
    raise SystemExit(main())

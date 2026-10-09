"""The real-input FFT (fft.asm + rfft.asm) in digikit's SHARC runner, against numpy, and its cost.

    python scripts/sharc_rfft_check.py [--sizes 32 512 4096]

N real floats as M = N/2 complex: forward is wr_fft (M points) then wr_rfft_post, which
must give numpy's rfft packed (slot 0 = X[0], X[M]); inverse is wr_rfft_pre then wr_fft
with SIGN -1, which must give N x irfft. `split_post` / `split_pre` are the same steps in
Python, checked against numpy first (to 1e-12). Prints instructions and the cycle model's
estimate per transform, and what a 64-frame table's levels at the largest N cost from
them (one forward of N, one inverse per level after level 0, `geometry.level_points`).
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
import tempfile

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import sharc_fft_check as F                                     # noqa: E402
from dnfw.image import bootstream, sharc_object                 # noqa: E402
from dnfw.sharccycles import costs as C                         # noqa: E402
from dnfw.waverider import dsp                                  # noqa: E402
from dnfw.waverider import geometry as G                        # noqa: E402
from dnfw import sharcemu  # noqa: E402

m5 = F.m5
RFFT_SW, RFFT_DM = 0x16F900, 0x2DF200
POST_SW, PRE_SW = 0x16F900, None                 # PRE_SW: wr_rfft_pre, from rfft.json's offsets
RP = 0x2E4020                                    # rfft.asm's parameter block
SHARC = ROOT / "csrc" / "waverider" / "sharc"


def split_post(Z: np.ndarray, n: int) -> np.ndarray:
    m = n // 2
    X = np.zeros(m + 1, complex)
    X[0], X[m] = Z[0].real + Z[0].imag, Z[0].real - Z[0].imag
    for k in range(1, m // 2 + 1):
        A, B = Z[k], np.conj(Z[m - k])
        E, O = (A + B) / 2, -1j * (A - B) / 2
        W = np.exp(-2j * np.pi * k / n)
        X[k], X[m - k] = E + W * O, np.conj(E - W * O)
    return X


def split_pre(X: np.ndarray, n: int) -> np.ndarray:
    m = n // 2
    Z = np.zeros(m, complex)
    Z[0] = (X[0] + X[m]).real + 1j * (X[0] - X[m]).real
    for k in range(1, m // 2 + 1):
        A, B = X[k], np.conj(X[m - k])
        E, O = A + B, (A - B) * np.exp(2j * np.pi * k / n)
        Z[m - k], Z[k] = np.conj(E - 1j * O), E + 1j * O
    return Z


def model_check() -> float:
    rng = np.random.default_rng(3)
    worst = 0.0
    for n in (16, 512, 2048):
        x = rng.standard_normal(n)
        z = x[0::2] + 1j * x[1::2]
        worst = max(worst, np.max(np.abs(split_post(np.fft.fft(z), n) - np.fft.rfft(x))))
        zi = np.fft.ifft(split_pre(np.fft.rfft(x), n)) * (n // 2)
        back = np.empty(n)
        back[0::2], back[1::2] = zi.real, zi.imag
        worst = max(worst, np.max(np.abs(back - n * x)) / n)
    return worst


def objects():
    load = lambda name: json.loads((SHARC / f"{name}.json").read_text())
    rf = load("rfft")
    src = [ln.split("//", 1)[0].strip() for ln in (SHARC / "rfft.asm").read_text().splitlines()]
    labels, k = {}, 0
    for t in src:
        if not t or t.startswith("."):
            continue
        if t.endswith(":"):
            labels[t[:-1].rstrip(".")] = k
            continue
        k += 1
    pre = RFFT_SW + rf["instruction_offsets"][labels["wr_rfft_pre"]] // 2
    return (sharc_object.load_bytes(bytes.fromhex(load("fft")["object_parcels_be"])),
            sharc_object.load_bytes(bytes.fromhex(rf["object_parcels_be"])), pre)


def stream(stock: bytes, fft: bytes, rfft: bytes) -> bytes:
    base = dsp.section7_idle_only(stock)
    extra = (bootstream.block(dsp.dm_to_load(F.FFT_DM), fft + bytes(0x200 - len(fft)))
             + bootstream.block(dsp.dm_to_load(RFFT_DM), rfft + bytes(0x600 - len(rfft)))
             + bootstream.block(dsp.dm_to_load(F.TW_DM), F.twiddles()))
    return bootstream.insert_before_final(base, extra)


def params(st, data: int, n: int, sign: float) -> None:
    m = n // 2
    f32 = lambda v: int(np.array(v, "<f4").view("<u4"))
    for off, v in ((0, data), (4, m), (8, F.TW_DM), (12, F.NMAX * 4), (16, f32(sign))):
        m5.m2.poke(st, F.PARAMS_DM + off, v)
    for off, v in ((0, data), (4, m), (8, F.TW_DM), (12, F.NMAX * 8 // n), (16, f32(0.5))):
        m5.m2.poke(st, RP + off, v)


def call(runner, sw, rec_counts):
    from sharc_cycles_recorder import Recorder       # noqa: PLC0415
    r = runner.fresh_call(sw, return_address=F.RETURN)
    with Recorder(m5.fx) as rec:
        res = m5.fx.run(r, 50_000_000, m5.fixups({}), stop_at=(F.RETURN,))
    for k, v in rec.model.counts.items():
        rec_counts[k] = rec_counts.get(k, 0) + v
    return r, res[0]


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--image", type=pathlib.Path, default=ROOT / "00_Resources/00_Firmware/Digitone_II_OS1.11_dist.zip")
    p.add_argument("--digikit", type=pathlib.Path,
                   default=sharcemu.path())
    p.add_argument("--sizes", type=int, nargs="+", default=[32, 512])
    a = p.parse_args(argv)
    err = model_check()
    print(f"  the Python split against numpy: max error {err:.1e}")
    dk = m5.m1.Digikit(a.digikit)
    m5.fx.bind(str(a.digikit / "tools"))
    m5.m4.IMAGE = a.image
    stock = m5.m1.dn2_section7(a.image)
    fft, rfft, pre_sw = objects()
    image = m5.Image(dk, stream(stock, fft, rfft))
    table = C.load(F.COSTS)
    rng = np.random.default_rng(11)
    data = F.DATA["ddr"]
    per, ok_all = {}, err < 1e-9
    with tempfile.TemporaryDirectory(dir=m5.OUT) as tmp:
        snap, m2mach = m5.snapshot_path(dk, stock, pathlib.Path(tmp))
        for n in a.sizes:
            m = n // 2
            x = rng.standard_normal(n).astype(np.float32)
            for direction in ("forward", "inverse"):
                init = m5.init_on(snap, m2mach, image)
                if direction == "forward":
                    F.poke_floats(init.state, data, x)
                    params(init.state, data, n, 1.0)
                    counts = {}
                    r, s1 = call(init, F.FFT_SW, counts)
                    r, s2 = call(r, POST_SW, counts)
                    y = F.read_floats(r.state, data, n).reshape(-1, 2)
                    got = y[:, 0] + 1j * y[:, 1]
                    X = np.fft.rfft(x.astype(float))
                    want = np.concatenate([[X[0] + 1j * X[m]], X[1:m]])
                    e = np.max(np.abs(got - want)) / np.max(np.abs(want))
                else:
                    X = np.fft.rfft(x.astype(float))
                    packed = np.concatenate([[X[0].real + 1j * X[m].real], X[1:m]])
                    F.poke_floats(init.state, data, np.column_stack([packed.real, packed.imag]).ravel())
                    params(init.state, data, n, -1.0)
                    counts = {}
                    r, s1 = call(init, pre_sw, counts)
                    r, s2 = call(r, F.FFT_SW, counts)
                    got = F.read_floats(r.state, data, n)
                    e = np.max(np.abs(got - n * x)) / np.max(np.abs(n * x))
                cycles, _, unpriced = C.estimate(counts, table)
                ok = s1 == s2 == "stop" and e < 1e-5
                ok_all &= ok
                per[(n, direction)] = cycles
                print(f"  N {n:5d} real {direction}: max error {e:.2e}  instructions {counts.get('instructions', 0):>9,}"
                      f"  cycles ~{cycles:>11,.0f}  {'PASS' if ok else 'FAIL'}" + (f"  (unpriced {unpriced})" if unpriced else ""))
    n = max(a.sizes)
    inv = [G.level_points(n, k) for k in range(1, G.levels(n))]
    if all((s, "inverse") in per for s in inv):
        cyc = per[(n, "forward")] + sum(per[(s, "inverse")] for s in inv)
        print(f"  levels of one {n}-point frame (forward {n}, inverses {inv}): ~{cyc:,.0f} cycles; "
              f"a 64-frame table ~{64 * cyc / 1e6:.1f} M cycles")
    return 0 if ok_all else 1


if __name__ == "__main__":
    raise SystemExit(main())

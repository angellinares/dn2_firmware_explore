"""fft2.asm (SIMD, hardware loops) in digikit's SHARC runner, against numpy and against fft.asm's cost.

    python scripts/sharc_fft2_check.py [--sizes 8 128 1024]

Reads csrc/waverider/sharc/fft2.json (scripts/build_fft.py --assemble). Builds stock + the
idle stub plus fft2.asm at sw 0x16fc00, its SIMD twiddle table ((sin, -sin, cos, cos) of
2 pi t / NMAX forward, the sines negated inverse, NMAX 4096) in DDR, and its parameter block at 0x2e4040; for each size M
(complex points) and both directions writes M random complex floats, calls wr_fft2, and
checks the result against numpy (the inverse unscaled). Prints instructions and the cycle
model's estimate.
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

m5 = F.m5
FFT2_SW, FFT2_DM = 0x16FC00, 0x2DF800
P2 = 0x2E4040
TW2 = 0x80B00000                        # the SIMD twiddle table, in DDR (32 KB at NMAX 4096)
NMAX = 4096
SHARC = ROOT / "csrc" / "waverider" / "sharc"


def twiddles2(sign: float = 1.0, nmax: int = NMAX) -> np.ndarray:
    """fft2.asm's table: (sin, -sin, cos, cos) forward, (-sin, sin, cos, cos) inverse."""
    a = 2 * np.pi * np.arange(nmax // 2) / nmax
    return np.column_stack([sign * np.sin(a), -sign * np.sin(a), np.cos(a), np.cos(a)]).astype("<f4").ravel()


def stream(stock: bytes) -> bytes:
    code = sharc_object.load_bytes(bytes.fromhex(json.loads((SHARC / "fft2.json").read_text())["object_parcels_be"]))
    base = dsp.section7_idle_only(stock)
    extra = bootstream.block(dsp.dm_to_load(FFT2_DM), code + bytes(0x600 - len(code)))
    return bootstream.insert_before_final(base, extra)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--image", type=pathlib.Path, default=ROOT / "00_Resources/00_Firmware/Digitone_II_OS1.11_dist.zip")
    p.add_argument("--digikit", type=pathlib.Path,
                   default=pathlib.Path(os.environ.get("DNFW_DIGIKIT_SHARC", ROOT.parent / "digikit-wt-sharcemu")))
    p.add_argument("--sizes", type=int, nargs="+", default=[8, 128])
    p.add_argument("--parts", action="store_true", help="print the cycle model's breakdown per call")
    p.add_argument("--compact", action="store_true", help="a twiddle table for M itself (NMAX = M), not for 4096")
    p.add_argument("--where", choices=("ddr", "l1"), default="ddr", help="where the data sits (l1: DM 0x2e5000)")
    a = p.parse_args(argv)
    from sharc_cycles_recorder import Recorder       # noqa: PLC0415
    dk = m5.m1.Digikit(a.digikit)
    m5.fx.bind(str(a.digikit / "tools"))
    m5.m4.IMAGE = a.image
    stock = m5.m1.dn2_section7(a.image)
    image = m5.Image(dk, stream(stock))
    table = C.load(F.COSTS)
    rng = np.random.default_rng(5)
    data = {"ddr": F.DATA["ddr"], "l1": 0x2E5000}[a.where]
    ok_all = True
    f32 = lambda v: int(np.array(v, "<f4").view("<u4"))
    with tempfile.TemporaryDirectory(dir=m5.OUT) as tmp:
        snap, m2mach = m5.snapshot_path(dk, stock, pathlib.Path(tmp))
        for m in a.sizes:
            for sign in (1.0, -1.0):
                init = m5.init_on(snap, m2mach, image)
                st = init.state
                nmax = m if a.compact else NMAX
                F.poke_floats(st, TW2, twiddles2(sign, nmax))
                x = (rng.standard_normal(m) + 1j * rng.standard_normal(m)).astype(np.complex64)
                F.poke_floats(st, data, np.column_stack([x.real, x.imag]).ravel())
                for off, v in ((0, data), (4, m), (8, m.bit_length() - 1), (12, TW2), (16, nmax // 2 * 4)):
                    m5.m2.poke(st, P2 + off, v)
                r = init.fresh_call(FFT2_SW, return_address=F.RETURN)
                with Recorder(m5.fx) as rec:
                    res = m5.fx.run(r, 50_000_000, m5.fixups({}), stop_at=(F.RETURN,))
                y = F.read_floats(r.state, data, 2 * m).reshape(-1, 2)
                y = y[:, 0] + 1j * y[:, 1]
                want = np.fft.fft(x) if sign > 0 else np.fft.ifft(x) * m
                err = np.max(np.abs(y - want)) / np.max(np.abs(want))
                counts = dict(rec.model.counts)
                cycles, parts, unpriced = C.estimate(counts, table)
                ok = res[0] == "stop" and err < 1e-5
                ok_all &= ok
                print(f"  M {m:5d} {'forward' if sign > 0 else 'inverse'}: {res[0]:>5s}  max error {err:.2e}  "
                      f"instructions {counts.get('instructions', 0):>9,}  cycles ~{cycles:>11,.0f}  "
                      f"{'PASS' if ok else 'FAIL'}" + (f"  (unpriced {unpriced})" if unpriced else ""))
                if a.parts:
                    print("    " + ", ".join(f"{k} {v:,.0f}" for k, v in sorted(parts.items(), key=lambda kv: -kv[1]) if v))
    return 0 if ok_all else 1


if __name__ == "__main__":
    raise SystemExit(main())

"""fft3.asm (split arrays, two butterflies an issue) in digikit's SHARC runner, against numpy, and its cost.

    python scripts/sharc_fft3_check.py [--sizes 8 64 1024] [--parts]

Reads csrc/waverider/sharc/fft3.json (scripts/build_fft.py --assemble). Builds stock + the
idle stub plus fft3.asm at sw 0x171000, the per-stage twiddle tables (TWR[h + k] =
cos(pi k / h), TWI[h + k] = -sin(pi k / h)) and the parameter block at 0x2e4060; for each
size M (complex points) writes M random complex floats as split arrays (re, im) (DDR or
L1, --where),
calls wr_fft3 forward, and inverse with the real and imaginary pointers swapped, and
checks both against numpy (the inverse unscaled). Prints instructions, the cycle model's
estimate (and its breakdown with --parts) and the fix-ups the run needed.
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

import sharc_fft_check as F                                     # noqa: E402
from dnfw import progress, sharcemu                             # noqa: E402
from dnfw.image import bootstream, sharc_object                 # noqa: E402
from dnfw.sharccycles import costs as C                         # noqa: E402
from dnfw.waverider import dsp                                  # noqa: E402

m5 = F.m5
FFT3_SW, FFT3_DM = 0x171000, 0x2E2000
P3 = 0x2E4060
SHARC = ROOT / "csrc" / "waverider" / "sharc"
SLACK = 1024
# what code the audio interrupt can preempt must leave as it found it (fft3.asm's header):
# the C runtime's constant M registers, the stack pointer I7, every L and B register
# (digikit UREG codes: I 16.., M 32.., L 48.., B 64..)
KEPT = [32 + m for m in (5, 6, 7, 13, 14, 15)] + [23] + list(range(48, 80))
UREG_NAME = {**{32 + m: f"M{m}" for m in range(16)}, 23: "I7",
             **{48 + k: f"L{k}" for k in range(16)}, **{64 + k: f"B{k}" for k in range(16)}}                                     # past each array: a stage's loads run ahead


def layout(m: int, where: str) -> dict[str, int]:
    """The six arrays' byte addresses. ddr: packed one after another (cache sets apart),
    the sources aligned to 4 M bytes. l1: no instruction touches one L1 block twice (PRM
    4-35): the first pass loads a source and stores its destination together, the stages
    move the destination's real (DM) and imaginary (PM) parts together, and the twiddles
    load as a pair; so source re, destination im and TWI in block 1, source im,
    destination re and TWR in block 0."""
    n = 4 * m
    up = lambda a: (a + n - 1) // n * n
    if where == "l1":
        b1, b0 = 0x2C0000, 0x240000
        return {"src_re": b1, "dst_im": b1 + n + SLACK, "twi": b1 + 2 * (n + SLACK),
                "src_im": b0, "dst_re": b0 + n + SLACK, "twr": b0 + 2 * (n + SLACK)}
    out, base = {}, 0x80A00000
    for side in ("re", "im"):
        tw = "twr" if side == "re" else "twi"
        out[f"src_{side}"], out[f"dst_{side}"], out[tw] = base, base + n, base + 2 * n + SLACK
        base = up(out[tw] + n + SLACK)
    return out


def twiddles(m: int) -> tuple[np.ndarray, np.ndarray]:
    """fft3.asm's tables for M points: entry h + k = w_k for each half-width h < M."""
    wr, wi = np.zeros(m, np.float32), np.zeros(m, np.float32)
    h = 1
    while h < m:
        a = np.pi * np.arange(h) / h
        wr[h:2 * h], wi[h:2 * h] = np.cos(a), -np.sin(a)
        h *= 2
    return wr, wi


def stream(stock: bytes) -> bytes:
    code = sharc_object.load_bytes(bytes.fromhex(json.loads((SHARC / "fft3.json").read_text())["object_parcels_be"]))
    if len(code) > 0x2000:
        raise SystemExit(f"fft3 is {len(code)} bytes, over its 8 KB at DM {FFT3_DM:#x}")
    base = dsp.section7_idle_only(stock)
    return bootstream.insert_before_final(base, bootstream.block(dsp.dm_to_load(FFT3_DM), code))


def params(st, m: int, inverse: bool, at: dict[str, int]) -> None:
    sre, sim, dre, dim = (at["src_re"], at["src_im"], at["dst_re"], at["dst_im"])
    if inverse:
        sre, sim, dre, dim = sim, sre, dim, dre
    for off, v in ((0, sre), (4, sim), (8, dre), (12, dim), (16, m), (20, m.bit_length() - 1),
                   (24, at["twr"]), (28, at["twi"])):
        m5.m2.poke(st, P3 + off, v)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--image", type=pathlib.Path, default=ROOT / "00_Resources/00_Firmware/Digitone_II_OS1.11_dist.zip")
    p.add_argument("--digikit", type=pathlib.Path, default=sharcemu.path())
    p.add_argument("--sizes", type=int, nargs="+", default=[8, 64])
    p.add_argument("--parts", action="store_true", help="print the cycle model's breakdown per call")
    p.add_argument("--where", choices=("ddr", "l1"), default="ddr", help="where the arrays sit (see layout)")
    a = p.parse_args(argv)
    from sharc_cycles_recorder import Recorder       # noqa: PLC0415
    dk = m5.m1.Digikit(a.digikit)
    m5.fx.bind(str(a.digikit / "tools"))
    m5.m4.IMAGE = a.image
    stock = m5.m1.dn2_section7(a.image)
    image = m5.Image(dk, stream(stock))
    table = C.load(F.COSTS)
    rng = np.random.default_rng(7)
    ok_all = True
    with progress.Job("fft3 check", total=2 * len(a.sizes)) as job, \
            tempfile.TemporaryDirectory(dir=m5.OUT) as tmp:
        snap, m2mach = m5.snapshot_path(dk, stock, pathlib.Path(tmp))
        for m in a.sizes:
            for inverse in (False, True):
                job.update(step=f"M {m} {'inverse' if inverse else 'forward'}")
                init = m5.init_on(snap, m2mach, image)
                st = init.state
                at = layout(m, a.where)
                wr, wi = twiddles(m)
                F.poke_floats(st, at["twr"], np.concatenate([wr, np.zeros(16, np.float32)]))
                F.poke_floats(st, at["twi"], np.concatenate([wi, np.zeros(16, np.float32)]))
                x = (rng.standard_normal(m) + 1j * rng.standard_normal(m)).astype(np.complex64)
                F.poke_floats(st, at["src_re"], x.real.astype(np.float32))
                F.poke_floats(st, at["src_im"], x.imag.astype(np.float32))
                params(st, m, inverse, at)
                fix = m5.fixups({})
                r = init.fresh_call(FFT3_SW, return_address=F.RETURN)
                before = {c: r.state.uregs.get(c) for c in KEPT}
                with Recorder(m5.fx) as rec:
                    res = m5.fx.run(r, 50_000_000, fix, stop_at=(F.RETURN,))
                y = F.read_floats(r.state, at["dst_re"], m) + 1j * F.read_floats(r.state, at["dst_im"], m)
                want = np.fft.ifft(x) * m if inverse else np.fft.fft(x)
                err = np.max(np.abs(y - want)) / np.max(np.abs(want))
                counts = dict(rec.model.counts)
                cycles, parts, unpriced = C.estimate(counts, table)
                changed = [UREG_NAME[c] for c in KEPT if r.state.uregs.get(c) != before[c]]
                ok = res[0] == "stop" and err < 1e-5 and not changed
                ok_all &= ok
                print(f"  M {m:5d} {'inverse' if inverse else 'forward'}: {res[0]:>5s}  max error {err:.2e}  "
                      f"instructions {counts.get('instructions', 0):>8,}  cycles ~{cycles:>9,.0f}  "
                      f"{'PASS' if ok else 'FAIL'}" + (f"  (unpriced {unpriced})" if unpriced else ""))
                if res[0] != "stop":
                    print(f"    {res[1]}")
                if changed:
                    print(f"    changed what stock code relies on: {', '.join(changed)}")
                if a.parts:
                    print("    " + ", ".join(f"{k} {v:,.0f}" for k, v in sorted(parts.items(), key=lambda kv: -kv[1]) if v))
                    print("    fix-ups: " + ", ".join(f"{k} {v}" for k, v in sorted(fix.counts.items())))
                job.advance()
    return 0 if ok_all else 1


if __name__ == "__main__":
    raise SystemExit(main())

"""Two frames' mip levels on the DSP (fft3.asm + spec3.asm) in digikit's SHARC runner, against the model, and the cost.

    python scripts/sharc_levels3_check.py [--points 2048] [--where l1|ddr]

Frame a in the real array and frame b in the imaginary one: one forward fft3 of N points,
spec3's split to both spectra, then per level k >= 1 (dnfw.waverider.geometry: L =
level_points, H = top_harmonic) spec3's join and an inverse fft3 of L points, whose real
part is frame a's level and imaginary part frame b's, 2N times the model's
(geometry.frame_levels). Two random frames by default. Prints each call's instructions
and cycle estimate, each level's error against the model, and the total per frame.
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
from dnfw import progress, sharcemu                             # noqa: E402
from dnfw.image import bootstream, sharc_object                 # noqa: E402
from dnfw.sharccycles import costs as C                         # noqa: E402
from dnfw.waverider import dsp                                  # noqa: E402
from dnfw.waverider import geometry as G                        # noqa: E402

F, m5 = K.F, K.m5
SPEC3_SW, SPEC3_DM = 0x171400, 0x2E2800
PS = 0x2E40A0                                    # spec3.asm's parameter block


def labels(name: str) -> dict[str, int]:
    """name.asm's labels -> sw, from its .json's instruction offsets."""
    spec = json.loads((K.SHARC / f"{name}.json").read_text())
    out, k = {}, 0
    for t in (ln.split("//", 1)[0].strip() for ln in (K.SHARC / f"{name}.asm").read_text().splitlines()):
        if not t or t.startswith("."):
            continue
        if t.endswith(":"):
            out[t[:-1]] = k
            continue
        k += 1
    base = int(spec["load_sw"], 16)
    return {lab: base + spec["instruction_offsets"][i] // 2 for lab, i in out.items() if i < len(spec["instruction_offsets"])}


def stream(stock: bytes) -> bytes:
    blocks = b""
    for name, dm in (("fft3", K.FFT3_DM), ("spec3", SPEC3_DM)):
        code = sharc_object.load_bytes(bytes.fromhex(json.loads((K.SHARC / f"{name}.json").read_text())["object_parcels_be"]))
        blocks += bootstream.block(dsp.dm_to_load(dm), code)
    return bootstream.insert_before_final(dsp.section7_idle_only(stock), blocks)


def arrays(n: int, where: str) -> dict[str, int]:
    """fft3's six arrays (K.layout) for N points, then the four spectra and the join's Z."""
    at = K.layout(n, where)
    bins = 4 * (n // 2 + 1) + K.SLACK
    top = max(at.values()) + 4 * n + K.SLACK
    if where == "l1":                      # A and B on the real side's block 1, Z beside them
        top = 0x2C0000 + 3 * (4 * n + K.SLACK)
    for name in ("ar", "ai", "br", "bi", "zr", "zi"):
        if name[0] == "z":                 # the inverse's sources: fft3 wants 4 L-byte alignment
            top = (top + 4 * n - 1) // (4 * n) * (4 * n)
        at[name] = top
        top += bins if name[0] in "ab" else 4 * n + K.SLACK
    return at


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--image", type=pathlib.Path, default=ROOT / "00_Resources/00_Firmware/Digitone_II_OS1.11_dist.zip")
    p.add_argument("--digikit", type=pathlib.Path, default=sharcemu.path())
    p.add_argument("--points", type=int, default=2048)
    p.add_argument("--where", choices=("ddr", "l1"), default="l1")
    a = p.parse_args(argv)
    from sharc_cycles_recorder import Recorder       # noqa: PLC0415
    n = a.points
    dk = m5.m1.Digikit(a.digikit)
    m5.fx.bind(str(a.digikit / "tools"))
    m5.m4.IMAGE = a.image
    stock = m5.m1.dn2_section7(a.image)
    image = m5.Image(dk, stream(stock))
    sw = labels("spec3")
    table = C.load(K.F.COSTS)
    at = arrays(n, a.where)
    rng = np.random.default_rng(13)
    fa, fb = rng.standard_normal(n).astype(np.float32), rng.standard_normal(n).astype(np.float32)
    want_a, want_b = G.frame_levels(fa), G.frame_levels(fb)
    total, ok_all = 0.0, True

    def call(r, entry):
        nonlocal total
        r = r.fresh_call(entry, return_address=F.RETURN)
        with Recorder(m5.fx) as rec:
            res = m5.fx.run(r, 50_000_000, m5.fixups({}), stop_at=(F.RETURN,))
        cycles, _, _ = C.estimate(dict(rec.model.counts), table)
        total += cycles
        if res[0] != "stop":
            raise SystemExit(f"{entry:#x}: {res[0]} {res[1]}")
        return r, rec.model.counts.get("instructions", 0), cycles

    def fft(st, m, src_re, src_im, dst_re, dst_im):
        for off, v in ((0, src_re), (4, src_im), (8, dst_re), (12, dst_im), (16, m), (20, m.bit_length() - 1),
                       (24, at["twr"]), (28, at["twi"])):
            m5.m2.poke(st, K.P3 + off, v)

    def spec(st, zr, zi, size, h=0):
        for off, v in ((0, zr), (4, zi), (8, size), (12, at["ar"]), (16, at["ai"]), (20, at["br"]),
                       (24, at["bi"]), (28, h)):
            m5.m2.poke(st, PS + off, v)

    levels = G.levels(n)
    with progress.Job("levels3 check", total=levels + 1) as job, tempfile.TemporaryDirectory(dir=m5.OUT) as tmp:
        snap, m2mach = m5.snapshot_path(dk, stock, pathlib.Path(tmp))
        r = m5.init_on(snap, m2mach, image)
        wr, wi = K.twiddles(n)
        F.poke_floats(r.state, at["twr"], np.concatenate([wr, np.zeros(16, np.float32)]))
        F.poke_floats(r.state, at["twi"], np.concatenate([wi, np.zeros(16, np.float32)]))
        F.poke_floats(r.state, at["src_re"], fa)
        F.poke_floats(r.state, at["src_im"], fb)
        job.update(step="forward + split")
        fft(r.state, n, at["src_re"], at["src_im"], at["dst_re"], at["dst_im"])
        r, i1, c1 = call(r, K.FFT3_SW)
        spec(r.state, at["dst_re"], at["dst_im"], n)
        r, i2, c2 = call(r, sw["wr_spec3_split."])
        print(f"  forward fft3 N {n}: {i1:,} instructions, ~{c1:,.0f} cycles; split: {i2:,}, ~{c2:,.0f}")
        sa = np.fft.rfft(fa.astype(float)); sb = np.fft.rfft(fb.astype(float))
        got = lambda k: F.read_floats(r.state, at[k], n // 2 + 1)
        e = max(np.max(np.abs(got("ar") + 1j * got("ai") - 2 * sa)), np.max(np.abs(got("br") + 1j * got("bi") - 2 * sb)))
        e /= 2 * max(np.max(np.abs(sa)), np.max(np.abs(sb)))
        ok_all &= e < 1e-5
        print(f"    both spectra against numpy: max error {e:.1e}")
        job.advance()
        for k in range(1, levels):
            L, H = G.level_points(n, k), G.top_harmonic(n, k)
            job.update(step=f"level {k}: L {L}, H {H}")
            spec(r.state, at["zr"], at["zi"], L, H)
            r, i3, c3 = call(r, sw["wr_spec3_join."])
            fft(r.state, L, at["zi"], at["zr"], at["dst_im"], at["dst_re"])      # the inverse
            r, i4, c4 = call(r, K.FFT3_SW)
            la = F.read_floats(r.state, at["dst_re"], L) / (2 * n)
            lb = F.read_floats(r.state, at["dst_im"], L) / (2 * n)
            scale = max(np.max(np.abs(want_a[k])), np.max(np.abs(want_b[k])))
            e = max(np.max(np.abs(la - want_a[k])), np.max(np.abs(lb - want_b[k]))) / scale
            ok = e < 1e-5
            ok_all &= ok
            print(f"  level {k}: L {L:5d} H {H:4d}  join {i3:>6,} instr ~{c3:>7,.0f}  inverse {i4:>7,} ~{c4:>8,.0f}  "
                  f"max error {e:.1e}  {'PASS' if ok else 'FAIL'}")
            job.advance()
    print(f"  two frames, all levels: ~{total:,.0f} cycles; a frame ~{total / 2:,.0f}; "
          f"a 64-frame table ~{32 * total / 1e6:.2f} M cycles")
    return 0 if ok_all else 1


if __name__ == "__main__":
    raise SystemExit(main())

"""selftest.asm in digikit's SHARC runner: the hash the silicon's REF must equal.

    python scripts/sharc_selftest_check.py [--runs 2] [--write 00_Resources/02_Builds/NAME.json]

Builds the selftest's section 7 (dnfw.waverider.selftest: stock, the idle stub,
selftest.asm, fft3.asm, spec3.asm, two frames and the twiddles in DDR) and runs
wr_selftest from the engine-init snapshot to its JUMP to wr_idle, RUNS times. Checks:

- every run's hash is the first's (PUB[1] = 0) and PUB[0] counts the runs;
- the hash recomputed here from the words each hash call reads (hooked at
  wr_selftest_hash) equals the DSP's;
- the two spectra and every level match the model (geometry.frame_levels), read from
  the words the hash calls read.

Prints REF; --write saves it (and the build's sizes) for tools/dn2selftest.py.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import struct
import sys
import tempfile

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import sharc_fft_check as F                                     # noqa: E402
from dnfw import progress, sharcemu                             # noqa: E402
from dnfw.waverider import geometry as G                        # noqa: E402
from dnfw.waverider import selftest as S                        # noqa: E402

m5 = F.m5
IDLE_SW = 0x16F500


def rotl5(h: int) -> int:
    return ((h << 5) | (h >> 27)) & 0xFFFFFFFF


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--image", type=pathlib.Path, default=ROOT / "00_Resources/00_Firmware/Digitone_II_OS1.11_dist.zip")
    p.add_argument("--digikit", type=pathlib.Path, default=sharcemu.path())
    p.add_argument("--runs", type=int, default=2)
    p.add_argument("--write", type=pathlib.Path)
    a = p.parse_args(argv)
    dk = m5.m1.Digikit(a.digikit)
    m5.fx.bind(str(a.digikit / "tools"))
    m5.m4.IMAGE = a.image
    stock = m5.m1.dn2_section7(a.image)
    image = m5.Image(dk, S.section7_selftest(stock))
    hash_sw = S._labels("selftest")["wr_selftest_hash."]
    n = S.POINTS
    fa, fb = S.frames(n)
    want_a, want_b = G.frame_levels(fa), G.frame_levels(fb)
    sa, sb = np.fft.rfft(fa.astype(float)), np.fft.rfft(fb.astype(float))
    ok, ref, hashes = True, None, []
    with progress.Job("selftest check", total=a.runs) as job, tempfile.TemporaryDirectory(dir=m5.OUT) as tmp:
        snap, m2mach = m5.snapshot_path(dk, stock, pathlib.Path(tmp))
        r = m5.init_on(snap, m2mach, image)
        for run in range(a.runs):
            job.update(step=f"run {run + 1}")
            r = r.fresh_call(S.CODE_SW, return_address=F.RETURN)
            fix = m5.fixups({})
            h, reads = 0, []
            while True:
                res = m5.fx.run(r, 50_000_000, fix, stop_at=(hash_sw, IDLE_SW))
                if res[0] != "stop":
                    raise SystemExit(f"run {run + 1}: {res[0]} {res[1]}")
                if res[1] == IDLE_SW:
                    break
                u = r.state.uregs
                base, count = u[0].value, u[2].value                 # R0 the array, R2 its words
                words = [m5.m2.word(r.state, base + 4 * k) for k in range(count)]
                reads.append(np.array(words, dtype=np.uint32))
                for w in words:
                    h = rotl5(h) ^ w
                fix.last.clear()
                m5.fx.run(r, 1, fix)                                 # step off the hook
            dsp_h = m5.m2.word(r.state, S.STATE_DM + 0xA8)
            pub = [m5.m2.word(r.state, S.PUB_DM + 4 * k) for k in range(S.PUB_ENTRIES)]
            hashes.append(dsp_h)
            ref = (pub[3] << 27) | pub[2]
            print(f"  run {run + 1}: hash {dsp_h:#010x} (here {h:#010x}), PUB runs {pub[0]}, differs {pub[1]}, "
                  f"REF {ref:#010x}")
            ok &= dsp_h == h and pub[0] == run + 1 and pub[1] == 0 and ref == hashes[0]
            # the values the hash calls read: AR AI BR BI, then each level's a and b
            f = [x.view("<f4").astype(float) for x in reads]
            e = max(np.max(np.abs(f[0] + 1j * f[1] - 2 * sa)), np.max(np.abs(f[2] + 1j * f[3] - 2 * sb)))
            e /= 2 * max(np.max(np.abs(sa)), np.max(np.abs(sb)))
            worst = e
            for k in range(1, G.levels(n)):
                la, lb = f[4 + 2 * (k - 1)] / (2 * n), f[5 + 2 * (k - 1)] / (2 * n)
                scale = max(np.max(np.abs(want_a[k])), np.max(np.abs(want_b[k])))
                worst = max(worst, max(np.max(np.abs(la - want_a[k])), np.max(np.abs(lb - want_b[k]))) / scale)
            print(f"    spectra and {G.levels(n) - 1} levels against the model: max error {worst:.1e}")
            ok &= worst < 1e-5
            job.advance()
    print(f"  REF {hashes[0]:#010x}: {'PASS' if ok else 'FAIL'}")
    if a.write and ok:
        a.write.write_text(json.dumps({"ref": hashes[0], "points": n, "seed": S.SEED,
                                       "levels": G.levels(n) - 1}, indent=2) + "\n", encoding="utf-8")
        print(f"  wrote {a.write}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

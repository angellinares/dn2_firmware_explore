"""Page 5's taming on every voice slot, in digikit's SHARC runner, bit for bit.

    python scripts/sharc_waverider_tame_voices.py [--digikit DIR] [--slots 0 .. 15] [--blocks 8] [--note 84]

Taming reads osc 2's increment from the voice's own reader block (phase.asm's wr_ph_tame, by
the track), so each slot is a case. For each slot t: Waverider on frame track t with track 0's
machine page, both oscillators on, WARP 127 and FM 127, a note at block 1 (C6 by default, where
both are tamed but not to 0). The track buffer must equal `live.render_two` fed the DSP's own
inputs for track t, bit for bit, and differ from the same model with taming off.

Frames come from `base_frame` (Python). Taming reads no frame word of its own, so the ColdFire's
send-time writes reach it only through the words page 5 already reads.
Exit 0 when every slot passes.
"""

from __future__ import annotations

import argparse
import pathlib
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import sharc_waverider_m5 as g                 # noqa: E402
from dnfw.waverider import dsp, live          # noqa: E402
from dnfw.waverider import frame as FR        # noqa: E402
from dnfw import sharcemu  # noqa: E402

FOLD, NPOS, TYPE, AMT, WARP, FM = live.SHAPE_SLOTS[:6]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--digikit", type=pathlib.Path, default=sharcemu.path())
    ap.add_argument("--image", type=pathlib.Path,
                    default=ROOT / "00_Resources/00_Firmware/Digitone_II_OS1.11_dist.zip")
    ap.add_argument("--slots", type=int, nargs="*", default=list(range(16)))
    ap.add_argument("--blocks", type=int, default=8)
    ap.add_argument("--note", type=int, default=84)
    a = ap.parse_args(argv)

    dk = g.m1.Digikit(a.digikit)
    g.fx.bind(str(a.digikit / "tools"))
    g.m4.IMAGE = a.image
    stock = g.m1.dn2_section7(a.image)
    sound, machines = g.m4.init_sound(a.image)
    wr = g.Image(dk, dsp.with_preinstalled(stock))
    tables = dsp.model_tables()
    page = {**machines.get(1, {}), g.TUN1: g.TUN1_ZERO, g.SMTH1: 0, g.SMTH2: 0}
    words = {g.WAV1: 0x4000, g.LEV2: 0x6400, WARP: 0x7F00, FM: 0x7F00}
    ok = True
    with tempfile.TemporaryDirectory(dir=g.OUT) as tmp:
        snap, m2mach = g.snapshot_path(dk, stock, pathlib.Path(tmp))
        init = g.init_on(snap, m2mach, wr)
        for t in a.slots:
            def fb(b, t=t):
                if t == 0:
                    return g.base_frame(sound, machines, trigger=(b == 1), overrides=words,
                                        note=a.note << 8).to_bytes()
                f = g.base_frame(sound, machines, others={t: 5})
                f.sound(t, page)
                f.header(FR.NOTE, t, a.note << 8)
                for s, v in words.items():
                    f.param(t, s, v)
                if b == 1:
                    f.trigger(t)
                return f.to_bytes()

            shapes = []

            def at_loop(r, t=t):
                shapes.append(tuple(g.frame_word(r.state, FR.slot_offset(t, s)) for s in live.SHAPE_SLOTS))

            run = g.run_blocks(g.native_on(init, wr), fb, a.blocks, extra_hooks={dsp.COUNT_SW: at_loop})
            if not run["ok"]:
                print(f"  FAIL slot {t}: halted {run.get('halt')}")
                ok = False
                continue
            got = g.track_series(run, t)
            ins = [i[t] for i in run["t5_inputs"] if t in i]
            seq = [(i["note"], (i["wav1"], i["tbl1"], i["tun1"], i["lev1"], *i["move1"], i["sync"][0], i["smth"][0]),
                    (*i["osc2"], *i["move2"], i["sync"][1], i["smth"][1]),
                    (i["trig"], i["triggered"], i["prst"], i["song"], i["tempo"], i["dclk"])) for i in ins]
            trims = [i["trim"] for i in ins]
            per_shape = shapes[-len(seq):]
            want = live.render_two(tables, seq, g.BLOCK, "float32", trims=trims, shapes=per_shape)
            keep, live.tame = live.tame, lambda inc, h: 1.0
            try:
                untamed = live.render_two(tables, seq, g.BLOCK, "float32", trims=trims, shapes=per_shape)
            finally:
                live.tame = keep
            bad = g.mismatches(got, want)
            tamed = sum(1 for x, y in zip(want, untamed) if x != y)
            loud = sum(1 for x in got if x)
            passed = bad == 0 and tamed > 0 and loud > 0
            ok &= passed
            print(f"  {'ok  ' if passed else 'FAIL'} slot {t}: {len(got)} samples, {loud} nonzero, mismatches {bad}, "
                  f"samples taming changes {tamed}", flush=True)
    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

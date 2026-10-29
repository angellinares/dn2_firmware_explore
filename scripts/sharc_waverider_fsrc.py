"""Waverider's FSRC (page 5 knob D, FM's modulator: fsrc.asm, fsrc_mix.asm) in digikit's SHARC
runner, bit for bit.

    python scripts/sharc_waverider_fsrc.py [--digikit DIR] [--blocks 8] [--only TEXT] [--slots 0 .. 15]

From the Milestone 2 post-init snapshot, on the section 7 the mod ships (`dnfw.waverider.dsp.section7`),
type-5 render blocks as `scripts/sharc_waverider_m5.py` runs them (a note at block 1), with page 3's
and page 5's frame words set. Each case runs on frame track 0, and the two marked "every slot" on each
of the 16 voice slots (the sub's phase, the noise's state and the reader blocks are the voice's own).

| case | must hold |
|---|---|
| FSRC SUB, FM 0 | bit for bit the model, and the same as without page 5: FSRC alone does nothing |
| FSRC SUB, FM 64, SUB 0, LEV2 0 (every slot) | bit for bit the model, FM changes samples, and the sub's FM differs from osc 2's |
| FSRC SUB, FM 127, SUB 100 SQR -2, WARP 64, osc 2 on | the same, the sub heard and moving osc 1 |
| FSRC SUB, PLS, SRC OSC2, FM 80, Ring AMT 100, osc 2 on | the same: the sub follows osc 1 under FSRC SUB |
| FSRC NOIS, FM 20, NOIS 0, LEV2 0 (every slot) | the same, with the noise |
| FSRC NOIS, FM 64, NOIS 100 PNK DEC 40, SUB 100, FOLD 32, osc 2 on | the same |
| FSRC 64, an old sound's word, FM 40 | the same: it plays NOIS, as the page shows it |
| FSRC SUB, the Formant, noise on, osc 2 on | the same (IIR0 runs in the engine) |
| FSRC SUB, then OSC2 from block 3 | the same across the change |
| tamed: FSRC SUB, FM 127 at C7 | the same, and taming changes samples |

`scripts/sharc_formant_voice.py` (case fsrc) runs FSRC with the Formant on two tracks, the in-flight voice included.
Exit 0 when every case passes.
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

FOLD, FSRC, TYPE, AMT, WARP, FM = live.SHAPE_SLOTS[:6]
SUB, OCT, WAVE, SRC = live.SUB_SLOTS
NOIS, NTYPE, COLR, DEC = live.NOISE_SLOTS
SUB_, NOIS_ = 0x0100, 0x0200                   # FSRC's words


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--digikit", type=pathlib.Path, default=sharcemu.path())
    ap.add_argument("--image", type=pathlib.Path,
                    default=ROOT / "00_Resources/00_Firmware/Digitone_II_OS1.11_dist.zip")
    ap.add_argument("--blocks", type=int, default=8)
    ap.add_argument("--only", action="append", default=[], metavar="TEXT")
    ap.add_argument("--slots", type=int, nargs="*", default=list(range(16)))
    a = ap.parse_args(argv)

    dk = g.m1.Digikit(a.digikit)
    g.fx.bind(str(a.digikit / "tools"))
    g.m4.IMAGE = a.image
    stock = g.m1.dn2_section7(a.image)
    sound, machines = g.m4.init_sound(a.image)
    wr = g.Image(dk, dsp.section7(stock))
    tables = dsp.tables()
    page = {**machines.get(1, {}), g.TUN1: g.TUN1_ZERO, g.SMTH1: 0, g.SMTH2: 0}
    noise_off = dict(zip(live.NOISE_SLOTS, live.NOISE_OFF))
    on2 = {g.LEV2: 0x6400}
    every = a.slots
    cases = [   # (name, words, slots, FM expected, note, FSRC from block JUMP_AT)
        ("FSRC SUB, FM 0", {g.LEV2: 0, FSRC: SUB_, SUB: 0x6400}, [0], False, 60, None),
        ("FSRC SUB, FM 64, SUB 0, LEV2 0", {g.LEV2: 0, FSRC: SUB_, FM: 0x4000}, every, True, 60, None),
        ("FSRC SUB, FM 127, SUB 100 SQR -2, WARP 64, osc 2 on",
         {**on2, FSRC: SUB_, FM: 0x7F00, SUB: 0x6400, OCT: 0x0100, WAVE: 0x0200, WARP: 0x4000}, [0], True, 60, None),
        ("FSRC SUB, PLS, SRC OSC2, FM 80, Ring AMT 100, osc 2 on",
         {**on2, FSRC: SUB_, FM: 0x5000, SUB: 0x3000, WAVE: 0x0300, SRC: 0x0100, TYPE: 0x0100, AMT: 0x6400},
         [0], True, 60, None),
        ("FSRC NOIS, FM 20, NOIS 0, LEV2 0", {g.LEV2: 0, FSRC: NOIS_, FM: 0x1400}, every, True, 60, None),
        ("FSRC NOIS, FM 64, NOIS 100 PNK DEC 40, SUB 100, FOLD 32, osc 2 on",
         {**on2, FSRC: NOIS_, FM: 0x4000, NOIS: 0x6400, NTYPE: 0x0100, DEC: 0x2800, SUB: 0x6400, FOLD: 0x2000},
         [0], True, 60, None),
        ("FSRC 64, an old sound's word, FM 40", {**on2, FSRC: 0x4000, FM: 0x2800}, [0], True, 60, None),
        ("FSRC SUB, the Formant, noise on, osc 2 on",
         {**on2, FSRC: SUB_, FM: 0x3000, SUB: 0x5000, TYPE: 0x0300, AMT: 0x4000, NOIS: 0x3000}, [0], True, 60, None),
        ("FSRC SUB, then OSC2 from block 3", {**on2, FSRC: SUB_, FM: 0x5000, SUB: 0x4000}, [0], True, 60, 0),
        ("tamed: FSRC SUB, FM 127 at C7", {**on2, FSRC: SUB_, FM: 0x7F00}, [0], True, 96, None),
    ]
    if a.only:
        cases = [c for c in cases if any(t in c[0] for t in a.only)]
    ok = True
    with tempfile.TemporaryDirectory(dir=g.OUT) as tmp:
        snap, m2mach = g.snapshot_path(dk, stock, pathlib.Path(tmp))
        init = g.init_on(snap, m2mach, wr)
        for name, words, slots, expect_fm, note, after in cases:
            for t in slots:
                w = {**noise_off, g.WAV1: 0x4000, **words}

                def fb(b, t=t, w=w, note=note, after=after):
                    o = {**w, FSRC: after} if after is not None and b >= g.JUMP_AT else w
                    if t == 0:
                        return g.base_frame(sound, machines, trigger=(b == 1), overrides=o, note=note << 8).to_bytes()
                    f = g.base_frame(sound, machines, others={t: 5})
                    f.sound(t, page)
                    f.header(FR.NOTE, t, note << 8)
                    for s, v in o.items():
                        f.param(t, s, v)
                    if b == 1:
                        f.trigger(t)
                    return f.to_bytes()

                subs, noises, shapes = [], [], []

                def at_loop(r, t=t):
                    word = lambda s: g.frame_word(r.state, FR.slot_offset(t, s))
                    subs.append(tuple(word(s) for s in live.SUB_SLOTS))
                    noises.append(tuple(word(s) for s in live.NOISE_SLOTS))
                    shapes.append(tuple(word(s) for s in live.SHAPE_SLOTS))

                run = g.run_blocks(g.native_on(init, wr), fb, a.blocks, extra_hooks={dsp.COUNT_SW: at_loop})
                if not run["ok"]:
                    print(f"  FAIL {name}, slot {t}: halted {run.get('halt')}", flush=True)
                    ok = False
                    continue
                got = g.track_series(run, t)
                ins = [i[t] for i in run["t5_inputs"] if t in i]
                seq = [(i["note"], (i["wav1"], i["tbl1"], i["tun1"], i["lev1"], *i["move1"], i["sync"][0], i["smth"][0]),
                        (*i["osc2"], *i["move2"], i["sync"][1], i["smth"][1]),
                        (i["trig"], i["triggered"], i["prst"], i["song"], i["tempo"], i["dclk"])) for i in ins]
                n = len(seq)
                kw = dict(subs=subs[-n:], noises=noises[-n:], trims=[i["trim"] for i in ins], voice=t)
                per_shape = shapes[-n:]
                want = live.render_two(tables, seq, g.BLOCK, "float32", shapes=per_shape, **kw)
                plain = live.render_two(tables, seq, g.BLOCK, "float32", **kw)
                osc2 = live.render_two(tables, seq, g.BLOCK, "float32", shapes=[(s[0], 0, *s[2:]) for s in per_shape], **kw)
                bad = g.mismatches(got, want)
                heard = sum(1 for x, y in zip(want, plain) if x != y)
                own = sum(1 for x, y in zip(want, osc2) if x != y)
                loud = sum(1 for x in got if x)
                passed = bad == 0 and loud > 0 and ((heard > 0 and own > 0) if expect_fm else heard == 0)
                extra = ""
                if name.startswith("tamed"):
                    keep, live.tame = live.tame, lambda inc, h: 1.0
                    try:
                        untamed = live.render_two(tables, seq, g.BLOCK, "float32", shapes=per_shape, **kw)
                    finally:
                        live.tame = keep
                    tamed = sum(1 for x, y in zip(want, untamed) if x != y)
                    passed = passed and tamed > 0
                    extra = f", taming changes {tamed}"
                ok &= passed
                print(f"  {'ok  ' if passed else 'FAIL'} {name}, slot {t}: {len(got)} samples, {loud} nonzero, "
                      f"mismatches {bad}, FM changes {heard}, differs from OSC2 {own}{extra}", flush=True)
    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

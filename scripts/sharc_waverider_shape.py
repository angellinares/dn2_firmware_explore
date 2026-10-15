"""Waverider's page 5 (page5.asm: FOLD, NPOS, TYPE Ring / AM with AMT) in digikit's SHARC
runner, bit for bit.

    python scripts/sharc_waverider_shape.py [--digikit DIR] [--blocks 8] [--seconds 2.5]

From the Milestone 2 post-init snapshot, on the section 7 the mod ships
(`dnfw.waverider.dsp.section7`), type-5 render blocks as `scripts/sharc_waverider_m5.py`
runs them (a note at block 1), with page 5's frame words (slots 58 FOLD, 61 NPOS, 62 TYPE,
48 AMT) set:

| case | must hold |
|---|---|
| all 0 (the control) | the track buffer is `live.render_two`'s without page 5, bit for bit |
| FOLD 64 | bit for bit `live.render_two` with page 5, and the fold changes samples |
| FOLD 127, osc 2 on | the same |
| NPOS 100 | the same (the voice's own generator) |
| Ring, AMT 127, osc 2 on | the same |
| AM, AMT 64, osc 2 on | the same |
| Ring, AMT 127, osc 2 off | the same: o2 is 0, so the mix is scaled by 1 - a |
| all four with the sub | Ring, FOLD and NPOS together, before the sub |

Writes out/waverider/shape_*.wav (48 kHz, 16-bit mono, LOOPED from the runner's blocks) and
shape_report.json. Exit 0 when every case passes.
"""

from __future__ import annotations

import argparse
import json
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

FOLD, NPOS, TYPE, AMT = live.SHAPE_SLOTS
SUB = live.SUB_SLOTS[0]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--digikit", type=pathlib.Path, default=sharcemu.path())
    ap.add_argument("--image", type=pathlib.Path,
                    default=ROOT / "00_Resources/00_Firmware/Digitone_II_OS1.11_dist.zip")
    ap.add_argument("--blocks", type=int, default=8)
    ap.add_argument("--seconds", type=float, default=2.5)
    a = ap.parse_args(argv)

    dk = g.m1.Digikit(a.digikit)
    g.fx.bind(str(a.digikit / "tools"))
    g.m4.IMAGE = a.image
    stock = g.m1.dn2_section7(a.image)
    sound, machines = g.m4.init_sound(a.image)
    wr = g.Image(dk, dsp.section7(stock))
    tables = dsp.tables()

    on2 = {g.LEV2: 0x6400}
    cases = [
        ("control: all 0", {g.LEV2: 0}),
        ("FOLD 64", {g.LEV2: 0, FOLD: 0x4000}),
        ("FOLD 127, osc 2 on", {**on2, FOLD: 0x7F00}),
        ("NPOS 100", {g.LEV2: 0, NPOS: 0x6400}),
        ("Ring, AMT 127, osc 2 on", {**on2, TYPE: 0x0100, AMT: 0x7F00}),
        ("AM, AMT 64, osc 2 on", {**on2, TYPE: 0x0200, AMT: 0x4000}),
        ("Ring, AMT 127, osc 2 off", {g.LEV2: 0, TYPE: 0x0100, AMT: 0x7F00}),
        ("all four with the sub", {**on2, TYPE: 0x0100, AMT: 0x5000, FOLD: 0x3000, NPOS: 0x2000, SUB: 0x6400}),
    ]
    checks, report, wavs = {}, {"blocks": a.blocks, "cases": {}}, []
    g.OUT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=g.OUT) as tmp:
        snap, m2mach = g.snapshot_path(dk, stock, pathlib.Path(tmp))
        init = g.init_on(snap, m2mach, wr)
        for name, words in cases:
            over = {g.WAV1: 0x4000, **words}

            def fb(b, over=over):
                return g.base_frame(sound, machines, trigger=(b == 1), overrides=over).to_bytes()

            subs, shapes, voices = [], [], []

            def at_loop(r):
                subs.append(tuple(g.frame_word(r.state, FR.slot_offset(0, s)) for s in live.SUB_SLOTS))
                shapes.append(tuple(g.frame_word(r.state, FR.slot_offset(0, s)) for s in live.SHAPE_SLOTS))

            def at_npos(r):
                voices.append(16 - (g.m2.word(r.state, 0x2DDE80) or 0))

            run = g.run_blocks(init, fb, a.blocks, extra_hooks={dsp.COUNT_SW: at_loop, dsp.PAGE5_SW: at_npos})
            if not run["ok"]:
                checks[name] = False
                report["cases"][name] = {"halt": run.get("halt")}
                continue
            got = g.track_series(run, 0)
            seq = [(i[0]["note"], (i[0]["wav1"], i[0]["tbl1"], i[0]["tun1"], i[0]["lev1"], *i[0]["move1"],
                                   i[0]["sync"][0], i[0]["smth"][0]),
                    (*i[0]["osc2"], *i[0]["move2"], i[0]["sync"][1], i[0]["smth"][1]),
                    (i[0]["trig"], i[0]["triggered"], i[0]["prst"], i[0]["song"], i[0]["tempo"], i[0]["dclk"]))
                   for i in run["t5_inputs"] if 0 in i]
            n = len(seq)
            per_sub, per_shape = (subs[-n:] or None), (shapes[-n:] or None)
            t = voices[0] if voices else 0
            want = live.render_two(tables, seq, g.BLOCK, "float32", subs=per_sub, shapes=per_shape, voice=t)
            plain = live.render_two(tables, seq, g.BLOCK, "float32", subs=per_sub)
            bad = g.mismatches(got, want)
            heard = sum(1 for x, y in zip(want, plain) if x != y)
            page5 = any(words.get(s, 0) for s in (FOLD, NPOS, AMT))
            checks[name] = bad == 0 and (heard > 0 if page5 else heard == 0)
            report["cases"][name] = {"mismatches": bad, "samples_page5_changes": heard, "voice": t,
                                     "voices_seen": sorted(set(voices)),
                                     "frame_words": per_shape[-1] if per_shape else None}
            tag = name.split(":")[0].replace(",", "").replace(" ", "_").lower()
            g.wav(f"shape_{tag}.wav", got, a.seconds, wavs, f"the runner: {name}, note 60")
    report["checks"] = checks
    report["wavs"] = wavs
    (g.OUT / "shape_report.json").write_text(json.dumps(report, indent=1, default=str) + "\n")
    for k, v in checks.items():
        print(f"  {'ok  ' if v else 'FAIL'} {k}  {report['cases'][k]}")
    for w in wavs:
        print(f"  wav {w['file']}: {w['what']}")
    passed = all(checks.values())
    print("PASS" if passed else "FAIL", f"{sum(checks.values())}/{len(checks)}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())

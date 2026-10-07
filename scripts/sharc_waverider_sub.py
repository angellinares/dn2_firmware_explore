"""Waverider's sub-oscillator (page 3, sub.asm) in digikit's SHARC runner, bit for bit.

    python scripts/sharc_waverider_sub.py [--digikit DIR] [--blocks 8] [--seconds 2.5]

From the Milestone 2 post-init snapshot, on the section 7 the mod ships
(`dnfw.waverider.dsp.section7`), type-5 render blocks as `scripts/sharc_waverider_m5.py`
runs them, with the sub's four frame words (params 50..53: SUB, OCT, WAVE, SRC) set:

| case | must hold |
|---|---|
| SUB 0 (the control) | the track buffer is `live.render_two`'s without a sub, bit for bit |
| SUB 100, OCT -1, SIN, SRC OSC1 | bit for bit `live.render_two` with the sub |
| SUB 100, OCT -2, TRI | the same |
| SUB 80, SQR, SRC OSC2, osc 2 on (detuned) | the same: the sub follows osc 2's increment |
| SUB 100, PLS, SRC OSC2, osc 2 off (LEV2 0) | the same: a skipped osc 2 has no increment, so osc 1's |

Each case's frame words are read back from the DSP's frame copy, as the reference is fed
the inputs the DSP holds. Writes out/waverider/sub_*.wav (48 kHz, 16-bit mono, LOOPED
from the runner's blocks) and sub_report.json. Exit 0 when every case passes.
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import sharc_waverider_m5 as g                 # noqa: E402
from dnfw.waverider import dsp, live          # noqa: E402
from dnfw.waverider import frame as FR        # noqa: E402

SUB, OCT, WAVE, SRC = live.SUB_SLOTS
DETUNE = 0x4000 + 7 * 256                      # osc 2 a fifth up: the SRC OSC2 case hears it


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--digikit", type=pathlib.Path,
                    default=pathlib.Path(os.environ.get("DNFW_DIGIKIT_SHARC",
                                                        ROOT.parent / "digikit-wt-sharcemu")))
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

    cases = [
        ("control: SUB 0", {SUB: 0}, False),
        ("SIN, OCT -1, SRC OSC1", {SUB: 0x6400, OCT: 0x0000, WAVE: 0x0000, SRC: 0x0000}, False),
        ("TRI, OCT -2", {SUB: 0x6400, OCT: 0x0100, WAVE: 0x0100, SRC: 0x0000}, False),
        ("SQR, SRC OSC2, osc 2 on (a fifth up)", {SUB: 0x5000, OCT: 0x0000, WAVE: 0x0200, SRC: 0x0100}, True),
        ("PLS, SRC OSC2, osc 2 off", {SUB: 0x6400, OCT: 0x0000, WAVE: 0x0300, SRC: 0x0100}, False),
    ]
    checks, report, wavs = {}, {"blocks": a.blocks, "cases": {}}, []
    g.OUT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=g.OUT) as tmp:
        snap, m2mach = g.snapshot_path(dk, stock, pathlib.Path(tmp))
        init = g.init_on(snap, m2mach, wr)
        for name, words, osc2_on in cases:
            over = {g.WAV1: 0x4000, **words}
            over[g.LEV2] = 0x6400 if osc2_on else 0
            if osc2_on:
                over[g.TUN2] = DETUNE

            def fb(b, over=over):
                return g.base_frame(sound, machines, trigger=(b == 1), overrides=over).to_bytes()

            subs = []

            def at_loop(r):
                subs.append(tuple(g.frame_word(r.state, FR.slot_offset(0, s)) for s in live.SUB_SLOTS))

            # at the block counter (once a block, after the unpack): run_blocks keeps its own
            # hook at the loop's entry, which an extra hook there would replace
            run = g.run_blocks(init, fb, a.blocks, extra_hooks={dsp.COUNT_SW: at_loop})
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
            per_block = subs[-len(seq):] if subs else None
            want = live.render_two(tables, seq, g.BLOCK, "float32", subs=per_block)
            plain = live.render_two(tables, seq, g.BLOCK, "float32")
            bad = g.mismatches(got, want)
            heard = sum(1 for x, y in zip(want, plain) if x != y)
            checks[name] = bad == 0 and (heard == 0 if words[SUB] == 0 else heard > 0)
            report["cases"][name] = {"mismatches": bad, "samples_the_sub_changes": heard,
                                     "frame_words": per_block[-1] if per_block else None}
            tag = name.split(":")[0].split(",")[0].replace(" ", "_").lower()
            g.wav(f"sub_{tag}.wav", got, a.seconds, wavs, f"the runner: {name}, note 60")
    report["checks"] = checks
    report["wavs"] = wavs
    (g.OUT / "sub_report.json").write_text(json.dumps(report, indent=1, default=str) + "\n")
    for k, v in checks.items():
        d = report["cases"][k]
        print(f"  {'ok  ' if v else 'FAIL'} {k}  {d}")
    for w in wavs:
        print(f"  wav {w['file']}: {w['what']}")
    passed = all(checks.values())
    print("PASS" if passed else "FAIL", f"{sum(checks.values())}/{len(checks)}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())

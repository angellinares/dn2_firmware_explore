"""DCLK holding a jump until the running fade ends (2026-10-07), bit for bit in digikit's SHARC runner.

    python scripts/sharc_waverider_dclk_hold.py [--digikit DIR] [--blocks 12] [--seconds 2.5]

The owner heard clicks with an LFO on TBL: a table change faster than the fade restarted
it, cutting the old wave off. dclk.asm now holds the fade's target while a fade runs,
and the next jump starts once it ends. Track 0 is Waverider, osc 1 alone, POS mid-table,
TBL switching between the two baked tables:

| case | must hold |
|---|---|
| DCLK Off, TBL every block (the control) | bit for bit `live.render_two`; it clicks (steps as large as the switch) |
| DCLK 3 ms, TBL every block | bit for bit; the largest sample step no larger than the wave's own |
| DCLK 3 ms, TBL every 2 blocks | the same |
| DCLK 18 ms, TBL every block | the same |

"The wave's own" step is the largest step of the same run with TBL held at table 0.
Writes out/waverider/dclkhold_*.wav and dclkhold_report.json. Exit 0 when every case passes.
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

DCLK = live.DCLK_SLOT


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--digikit", type=pathlib.Path,
                    default=pathlib.Path(os.environ.get("DNFW_DIGIKIT_SHARC",
                                                        ROOT.parent / "digikit-wt-sharcemu")))
    ap.add_argument("--image", type=pathlib.Path,
                    default=ROOT / "00_Resources/00_Firmware/Digitone_II_OS1.11_dist.zip")
    ap.add_argument("--blocks", type=int, default=12)
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
        ("control: DCLK Off, TBL every block", 0, 1),
        ("DCLK 3 ms, TBL every block", live.DCLK_DEFAULT, 1),
        ("DCLK 3 ms, TBL every 2 blocks", live.DCLK_DEFAULT, 2),
        ("DCLK 18 ms, TBL every block", 0x5000, 1),
    ]
    checks, report, wavs = {}, {"blocks": a.blocks, "cases": {}}, []
    g.OUT.mkdir(parents=True, exist_ok=True)

    def step(ys):
        return max(abs(x - y) for x, y in zip(ys[g.BLOCK:], ys[g.BLOCK + 1:]))

    with tempfile.TemporaryDirectory(dir=g.OUT) as tmp:
        snap, m2mach = g.snapshot_path(dk, stock, pathlib.Path(tmp))
        init = g.init_on(snap, m2mach, wr)

        def series(dclk, period):
            def fb(b):
                tbl = 0x0100 if period and (b // period) % 2 else 0x0000
                over = {g.WAV1: 0x3000, g.TBL1: tbl, g.LEV2: 0, DCLK: dclk}
                return g.base_frame(sound, machines, trigger=(b == 0), overrides=over).to_bytes()
            run = g.run_blocks(init, fb, a.blocks)
            if not run["ok"]:
                return run, None, None
            seq = [(i[0]["note"], (i[0]["wav1"], i[0]["tbl1"], i[0]["tun1"], i[0]["lev1"], *i[0]["move1"],
                                   i[0]["sync"][0], i[0]["smth"][0]),
                    (*i[0]["osc2"], *i[0]["move2"], i[0]["sync"][1], i[0]["smth"][1]),
                    (i[0]["trig"], i[0]["triggered"], i[0]["prst"], i[0]["song"], i[0]["tempo"], i[0]["dclk"]))
                   for i in run["t5_inputs"] if 0 in i]
            return run, g.track_series(run, 0), live.render_two(tables, seq, g.BLOCK, "float32")

        _, held, _ = series(0, 0)
        own = step(held) if held else None
        report["wave_own_step"] = own
        for name, dclk, period in cases:
            run, got, want = series(dclk, period)
            if got is None:
                checks[name] = False
                report["cases"][name] = {"halt": run.get("halt")}
                continue
            bad = g.mismatches(got, want)
            s_got = step(got)
            ok_step = s_got > 2 * own if dclk == 0 else s_got <= own * 1.05
            checks[name] = bad == 0 and ok_step
            report["cases"][name] = {"mismatches": bad, "largest_step": s_got}
            tag = name.split(":")[-1].strip().replace(" ", "_").replace(",", "").lower()
            g.wav(f"dclkhold_{tag}.wav", got, a.seconds, wavs, f"the runner: {name}")
    report["checks"] = checks
    report["wavs"] = wavs
    (g.OUT / "dclkhold_report.json").write_text(json.dumps(report, indent=1, default=str) + "\n")
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

"""Waverider's noise (page 3, noise.asm) in digikit's SHARC runner, bit for bit.

    python scripts/sharc_waverider_noise.py [--digikit DIR] [--blocks 8] [--seconds 2.5]

From the Milestone 2 post-init snapshot, on the section 7 the mod ships
(`dnfw.waverider.dsp.section7`), type-5 render blocks as `scripts/sharc_waverider_m5.py`
runs them (a note at block 1), with the noise's four frame words (params 54..57: NOIS,
TYPE, COLR, DEC) set:

| case | must hold |
|---|---|
| NOIS 0 (the control) | the track buffer is `live.render_two`'s without noise, bit for bit |
| WHT, COLR 0, DEC Inf | bit for bit `live.render_two` with the noise (`NoiseVoice`) |
| PNK, COLR -64, DEC Inf | the same |
| BRN, COLR +63, DEC 40 | the same: silent until the note restarts the envelope |
| DIG, DEC 0, with the sub on (SIN) | the same, after the sub |

The reference's voice is the one noise.asm ran for (16 - the block counter at its
entry), so its seed is that voice's. Writes out/waverider/noise_*.wav (48 kHz, 16-bit
mono, LOOPED from the runner's blocks) and noise_report.json. Exit 0 when every case passes.
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

NOIS, TYPE, COLR, DEC = live.NOISE_SLOTS
SUB = live.SUB_SLOTS[0]


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
        ("control: NOIS 0", {NOIS: 0}),
        ("WHT, COLR 0, DEC Inf", {NOIS: 0x6400, TYPE: 0x0000, COLR: 0x4000, DEC: 0x7F00}),
        ("PNK, COLR -64, DEC Inf", {NOIS: 0x6400, TYPE: 0x0100, COLR: 0x0000, DEC: 0x7F00}),
        ("BRN, COLR +63, DEC 40", {NOIS: 0x7F00, TYPE: 0x0200, COLR: 0x7F00, DEC: 0x2800}),
        ("DIG, DEC 0, with the sub", {NOIS: 0x5000, TYPE: 0x0300, COLR: 0x4000, DEC: 0x0000, SUB: 0x6400}),
    ]
    checks, report, wavs = {}, {"blocks": a.blocks, "cases": {}}, []
    g.OUT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=g.OUT) as tmp:
        snap, m2mach = g.snapshot_path(dk, stock, pathlib.Path(tmp))
        init = g.init_on(snap, m2mach, wr)
        for name, words in cases:
            over = {g.WAV1: 0x4000, g.LEV2: 0, **words}

            def fb(b, over=over):
                return g.base_frame(sound, machines, trigger=(b == 1), overrides=over).to_bytes()

            subs, noises, voices = [], [], []

            def at_loop(r):
                subs.append(tuple(g.frame_word(r.state, FR.slot_offset(0, s)) for s in live.SUB_SLOTS))
                noises.append(tuple(g.frame_word(r.state, FR.slot_offset(0, s)) for s in live.NOISE_SLOTS))

            def at_noise(r):
                voices.append(16 - (g.m2.word(r.state, 0x2DDE80) or 0))

            run = g.run_blocks(init, fb, a.blocks, extra_hooks={dsp.COUNT_SW: at_loop, dsp.NOISE_SW: at_noise})
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
            per_sub, per_noise = (subs[-n:] or None), (noises[-n:] or None)
            t = voices[0] if voices else 0
            seed = live.noise_seeds()[t]
            saved = live.noise_seeds
            live.noise_seeds = lambda: (seed,) * 16          # the reference plays voice 0: give it voice t's seed
            try:
                want = live.render_two(tables, seq, g.BLOCK, "float32", subs=per_sub, noises=per_noise)
            finally:
                live.noise_seeds = saved
            plain = live.render_two(tables, seq, g.BLOCK, "float32", subs=per_sub)
            bad = g.mismatches(got, want)
            heard = sum(1 for x, y in zip(want, plain) if x != y)
            checks[name] = bad == 0 and (heard == 0 if words[NOIS] == 0 else heard > 0)
            report["cases"][name] = {"mismatches": bad, "samples_the_noise_changes": heard, "voice": t,
                                     "voices_seen": sorted(set(voices)),
                                     "frame_words": per_noise[-1] if per_noise else None}
            tag = name.split(":")[0].split(",")[0].replace(" ", "_").lower()
            g.wav(f"noise_{tag}.wav", got, a.seconds, wavs, f"the runner: {name}, note 60")
    # the runner renders 8 blocks; to hear the noise itself, the reference the runner
    # matched (live.NoiseVoice) plays 6 s: the four types, two notes each at DEC 60, then
    # WHT at COLR -64 and +63 (DEC Inf); the noise alone, no oscillator
    tour = []
    for words in ([(0x6400, k << 8, 0x4000, 0x3C00)] * 1 for k in range(4)):
        v = live.NoiseVoice(live.noise_seeds()[0])
        for b in range(48000 // g.BLOCK):
            tour += v.render(words[0], b in (0, 750), g.BLOCK)
    for colr in (0x0000, 0x7F00):
        v = live.NoiseVoice(live.noise_seeds()[0])
        for b in range(48000 // g.BLOCK):
            tour += v.render((0x6400, 0, colr, 0x7F00), b == 0, g.BLOCK)
    g.wav("noise_reference_tour.wav", tour, len(tour) / g.RATE, wavs,
          "the reference (bit for bit with the runner above): WHT, PNK, BRN, DIG at DEC 60, two notes "
          "a second; then WHT at COLR -64, then +63; 1 s each, the noise alone", normalise=True)
    report["checks"] = checks
    report["wavs"] = wavs
    (g.OUT / "noise_report.json").write_text(json.dumps(report, indent=1, default=str) + "\n")
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

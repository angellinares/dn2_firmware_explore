"""What page 3's sub and noise cost the DSP, in digikit's SHARC runner: instructions.

    python scripts/sharc_waverider_p3_cost.py [--digikit DIR] [--blocks 4]

Track 0 is Waverider (both oscillators on, a note at block 1), tracks 1-15 MIDI. Each
case differs from the control (page 5 all 0) in one control: FOLD, NPOS, TYPE Ring or AM
with AMT; the last has all of them. The difference is per voice, since page5.asm runs once
per type-5 voice and block (NPOS once per oscillator). The
16-voice figure multiplies it by 16 (an extrapolation, not a run); a frame is one
32-sample block, 666,667 cycles at 1 GHz (docs/sharc-load.md). Instructions are
not cycles: our code runs from L1, where the two are close, but the instrument's
load (tools/dn2sharc_load.py --idle) is the real gate. Writes
out/waverider/p5_cost.json.
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
from dnfw import sharcemu  # noqa: E402

FOLD, NPOS, TYPE, AMT = live.SHAPE_SLOTS
FRAME_CYCLES = 666_667


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--digikit", type=pathlib.Path,
                    default=sharcemu.path())
    ap.add_argument("--image", type=pathlib.Path,
                    default=ROOT / "00_Resources/00_Firmware/Digitone_II_OS1.11_dist.zip")
    ap.add_argument("--blocks", type=int, default=4)
    a = ap.parse_args(argv)
    dk = g.m1.Digikit(a.digikit)
    g.fx.bind(str(a.digikit / "tools"))
    g.m4.IMAGE = a.image
    stock = g.m1.dn2_section7(a.image)
    sound, machines = g.m4.init_sound(a.image)
    wr = g.Image(dk, dsp.section7(stock))
    cases = [
        ("control: page 5 all 0", {}),
        ("FOLD 64", {FOLD: 0x4000}),
        ("NPOS 64", {NPOS: 0x4000}),
        ("control, DCLK 0", {live.DCLK_SLOT: 0}),
        ("NPOS 64, DCLK 0", {NPOS: 0x4000, live.DCLK_SLOT: 0}),
        ("Ring, AMT 64", {TYPE: 0x0100, AMT: 0x4000}),
        ("AM, AMT 64", {TYPE: 0x0200, AMT: 0x4000}),
        ("all: AM, FOLD, NPOS", {TYPE: 0x0200, AMT: 0x4000, FOLD: 0x4000, NPOS: 0x4000}),
    ]
    got = {}
    with tempfile.TemporaryDirectory(dir=g.OUT) as tmp:
        snap, m2mach = g.snapshot_path(dk, stock, pathlib.Path(tmp))
        init = g.init_on(snap, m2mach, wr)
        for name, words in cases:
            over = {g.WAV1: 0x4000, g.LEV2: 0x6400, **words}

            def fb(b, over=over):
                return g.base_frame(sound, machines, trigger=(b == 1), overrides=over).to_bytes()

            run = g.run_blocks(init, fb, a.blocks)
            got[name] = run["instructions"] if run["ok"] else None
    base = got[cases[0][0]]
    report = {"blocks": a.blocks, "cases": {}}
    for name, n in got.items():
        per_block = None if n is None or base is None else (n - base) / a.blocks
        report["cases"][name] = {"instructions": n, "per_voice_per_block": per_block,
                                 "x16_share_of_a_frame": None if per_block is None
                                 else round(16 * per_block / FRAME_CYCLES, 4)}
        print(f"  {name:36s} {n}  +{per_block}/block/voice"
              + ("" if per_block is None else f"  x16 = {100 * 16 * per_block / FRAME_CYCLES:.1f} % of a frame"))
    g.OUT.mkdir(parents=True, exist_ok=True)
    (g.OUT / "p5_cost.json").write_text(json.dumps(report, indent=1) + "\n")
    return 0 if all(v is not None for v in got.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())

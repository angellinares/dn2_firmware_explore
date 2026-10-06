"""Waverider's worst case in the SHARC runner, beside the factory machines: instructions per
block with every voice busy.

    python scripts/sharc_waverider_stress.py [--blocks 16] [--image ZIP] [--digikit DIR]

The runner counts instructions, not cycles: no cache misses, no DDR stalls. So these figures
rank the cases and size the code's share. The instrument's `dn2sharc_load.py --idle` gives
the load itself. Every case runs the firmware's own per-block routine (`sw 0x1c2712`) on
frames for all 16 tracks, a note on each at block 1, as `sharc_waverider_m5.py` does:

- `stock_wavetone`: the stock section 7, all 16 tracks WaveTone (the factory baseline);
- `stock_fmtone`: the same on FM Tone;
- `wr_default`: Waverider on all 16, both oscillators, the init sound;
- `wr_worst`: Waverider on all 16, both oscillators, each with MOVE Square on POS (full
  depth) at the fastest SYNC (1/32 T, TRIG Free), SMTH 60, and DCLK 100 ms, so every block
  of every oscillator is mid-crossfade (two reader passes);
- `wr_worst_dclk_off`: the same with DCLK Off (the crossfade's own cost is the difference).

Writes out/waverider/stress_report.json. Pure measurement; it gates nothing.
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

import sharc_dn2_fixups as fx                                  # noqa: E402
import sharc_waverider_m4 as m4                                # noqa: E402
import sharc_waverider_m5 as g                                 # noqa: E402
import sharc_waverider_render as m1                            # noqa: E402
from dnfw.waverider import dsp, live                           # noqa: E402
from dnfw.waverider import frame as FR                         # noqa: E402

OUT = ROOT / "out" / "waverider"
TRACKS = range(16)


def all_tracks(sound, machines, machine, per_track=None, song=False):
    def fb(b):
        f = g.base_frame(sound, machines, t0=machine, others={t: machine for t in TRACKS if t},
                         trigger=(b == 1), trigger_others=True)
        for t in TRACKS:
            f.sound(t, machines.get(machine, {}) if machine in machines else machines.get(1, {}))
            for s, v in (per_track or {}).items():
                f.param(t, s, v)
        if song:
            p = (b * live.trunc(g.SYNC_TEMPO * live.SYNC_K)) & 0xFFFFFFFF
            f.put(live.SYNC_POSITION, p & 0xFFFF)
            f.put(live.SYNC_POSITION + 2, p >> 16)
            f.put(live.SYNC_TEMPO, g.SYNC_TEMPO)
        return f.to_bytes()
    return fb


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--image", type=pathlib.Path,
                    default=ROOT / "00_Resources/00_Firmware/Digitone_II_OS1.11_dist.zip")
    ap.add_argument("--digikit", type=pathlib.Path,
                    default=pathlib.Path(os.environ.get("DNFW_DIGIKIT_SHARC", ROOT.parent / "digikit-wt-sharcemu")))
    ap.add_argument("--blocks", type=int, default=16)
    a = ap.parse_args(argv)
    dk = m1.Digikit(a.digikit)
    fx.bind(str(a.digikit / "tools"))
    m4.IMAGE = a.image
    stock = m1.dn2_section7(a.image)
    sound, machines = m4.init_sound(a.image)
    wr_img, stock_img = g.Image(dk, dsp.section7(stock)), g.Image(dk, stock)
    worst = {g.WAV1: 0, g.MPOS1: 0x6400, g.MOVE1: 0x0800, g.RATE1: 0x6400, g.TRIG: 0x100, g.SYNC1: 0x100,
             g.WAV2: 0x7800, g.MPOS2: 0, g.MOVE2: 0x0800, g.RATE2: 0x6400, g.SYNC2: 0x100,
             g.SMTH1: 0x3C00, g.SMTH2: 0x3C00, g.DCLK: 0x7F00}
    cases = {
        "stock_wavetone": (stock_img, all_tracks(sound, machines, 1)),
        "stock_fmtone": (stock_img, all_tracks(sound, machines, 0)),
        "wr_default": (wr_img, all_tracks(sound, machines, 5)),
        "wr_worst": (wr_img, all_tracks(sound, machines, 5, worst, song=True)),
        "wr_worst_dclk_off": (wr_img, all_tracks(sound, machines, 5, {**worst, g.DCLK: 0}, song=True)),
    }
    out = {}
    with tempfile.TemporaryDirectory(dir=OUT) as tmp:
        snap, m2mach = g.snapshot_path(dk, stock, pathlib.Path(tmp))
        for name, (img, frames) in cases.items():
            init = g.init_on(snap, m2mach, img)
            r = g.run_blocks(init, frames, a.blocks)
            per = round(r.get("instructions", 0) / a.blocks) if r["ok"] else None
            out[name] = {"ok": r["ok"], "halt": r.get("halt"), "instructions_per_block": per,
                         "loop_entries": r.get("loop_entries"), "wall_s": r.get("wall_s")}
            print(f"{name:20s} {'ok' if r['ok'] else 'HALT ' + str(r.get('halt'))}  "
                  f"{per if per else '-':>10} instructions a block", flush=True)
    base = out["stock_wavetone"]["instructions_per_block"]
    for v in out.values():
        if v["instructions_per_block"] and base:
            v["vs_stock_wavetone"] = round(v["instructions_per_block"] / base, 3)
    (OUT / "stress_report.json").write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v.get("vs_stock_wavetone") for k, v in out.items()}))
    return 0 if all(v["ok"] for v in out.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())

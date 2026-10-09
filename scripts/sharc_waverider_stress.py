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
- `dclk_off` / `dclk_100ms`: a pair that differs only in DCLK. It's the init sound with POS jumping
  between 0 and 120 on every block (osc 2 the other way round), so with DCLK on every oscillator
  of every voice is mid-crossfade on every block after the note. The run counts the reader's
  calls to show the second pass ran. Nothing else (SYNC, MOVE, SMTH) is touched: a first version
  stacked them in, and SMTH's glide and a full-depth MOVE hid the jumps (owner, 2026-10-06:
  each pair differs only in the feature measured).

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
from dnfw import sharcemu  # noqa: E402

OUT = ROOT / "out" / "waverider"
TRACKS = range(16)


def all_tracks(sound, machines, machine, per_track=None, song=False, jumping=False):
    def fb(b):
        f = g.base_frame(sound, machines, t0=machine, others={t: machine for t in TRACKS if t},
                         trigger=(b == 1), trigger_others=True)
        for t in TRACKS:
            f.sound(t, machines.get(machine, {}) if machine in machines else machines.get(1, {}))
            for s, v in (per_track or {}).items():
                f.param(t, s, v)
            if jumping:                         # POS jumps on every block, both oscillators
                f.param(t, g.WAV1, 0x7800 if b % 2 else 0)
                f.param(t, g.WAV2, 0 if b % 2 else 0x7800)
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
                    default=sharcemu.path())
    ap.add_argument("--blocks", type=int, default=16)
    ap.add_argument("--cases", default="", help="comma-separated subset of the cases to run")
    a = ap.parse_args(argv)
    dk = m1.Digikit(a.digikit)
    fx.bind(str(a.digikit / "tools"))
    m4.IMAGE = a.image
    stock = m1.dn2_section7(a.image)
    sound, machines = m4.init_sound(a.image)
    wr_img, stock_img = g.Image(dk, dsp.section7(stock)), g.Image(dk, stock)
    dclk = {g.DCLK: 0x7F00}
    cases = {
        "stock_wavetone": (stock_img, all_tracks(sound, machines, 1)),
        "stock_fmtone": (stock_img, all_tracks(sound, machines, 0)),
        "wr_default": (wr_img, all_tracks(sound, machines, 5)),
        "dclk_off": (wr_img, all_tracks(sound, machines, 5, {g.DCLK: 0}, jumping=True)),
        "dclk_100ms": (wr_img, all_tracks(sound, machines, 5, dclk, jumping=True)),
    }
    if a.cases:
        cases = {k: v for k, v in cases.items() if k in a.cases.split(",")}
    out = {}
    with tempfile.TemporaryDirectory(dir=OUT) as tmp:
        snap, m2mach = g.snapshot_path(dk, stock, pathlib.Path(tmp))
        for name, (img, frames) in cases.items():
            init = g.init_on(snap, m2mach, img)
            calls = [0]

            def count(r):
                calls[0] += 1
            r = g.run_blocks(init, frames, a.blocks, extra_hooks={dsp.READER_SW: count}
                             if img is wr_img else None)
            per = round(r.get("instructions", 0) / a.blocks) if r["ok"] else None
            out[name] = {"ok": r["ok"], "halt": r.get("halt"), "instructions_per_block": per,
                         "loop_entries": r.get("loop_entries"), "wall_s": r.get("wall_s"),
                         "reader_calls_per_block": round(calls[0] / a.blocks, 1)}
            print(f"{name:20s} {'ok' if r['ok'] else 'HALT ' + str(r.get('halt'))}  "
                  f"{per if per else '-':>10} instructions a block, "
                  f"{out[name]['reader_calls_per_block']} reader calls", flush=True)
    base = out.get("stock_wavetone", {}).get("instructions_per_block") or 293546   # the last full run
    for v in out.values():
        if v["instructions_per_block"] and base:
            v["vs_stock_wavetone"] = round(v["instructions_per_block"] / base, 3)
    (OUT / "stress_report.json").write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v.get("vs_stock_wavetone") for k, v in out.items()}))
    return 0 if all(v["ok"] for v in out.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())

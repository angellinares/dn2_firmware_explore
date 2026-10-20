"""A long render of the Waverider voice in digikit's SHARC runner, not looped, for `dnfw wav report`.

    python scripts/sharc_waverider_long.py CASE [--blocks 375] [--note 60] [--chunk 25] [--python]

The other runner tests render 12 blocks (8 ms) and loop them to fill a WAV, so a report
on their files describes the loop. This one renders BLOCKS blocks in a row (375 is a
quarter of a second) and writes them as they are, in 32-bit float. It runs them in
digikit's Rust engine (scripts/sharc_native.py), about 0.6 seconds a block, and names its
files long_CASE_native_*. `--python` runs the Python runner instead, as a second opinion:
about 11 seconds a block, so 375 blocks take over an hour, in files long_CASE_*.

Track 0 is Waverider on table 0, triggered on the first block. The cases with moving
controls check that a change to the DSP code sounds the same while parameters move:

| case | what changes |
|---|---|
| hold | nothing: osc 1 alone, POS stays mid-table |
| sweep | osc 1 alone, POS moves from 0 to 120 over the render, a step each block |
| pitch | osc 1 alone, the note glides from 12 to 120, across every mip level |
| move_pos | osc 1 alone, MOVE moves POS (OFS1 100, PD1 100) |
| move_lev | osc 1 alone, MOVE moves the level (DRIF 127, ATK 7, PD1 100) |
| levels | osc 1 alone, LEV1 rises and falls every 100 blocks, TRIM steps every 47 blocks |
| osc2 | osc 2 on, off a third of the time, its POS and its detune (up to 12 semitones) moving, MOVE on its POS |
| warpfm | both oscillators, WARP rises from 0 to 127 while FM falls from 127 to 0 |
| retrig | both oscillators, a note every 30 blocks and a retrigger 3 blocks later, POS jumping with DCLK on |
| warp127 | both oscillators at the same pitch, WARP 127 held (taming, 0.3.5, acts from about D#4) |
| fm127 | both oscillators at the same pitch, FM 127 held (taming acts from about G#4) |
| fm_lev2 | FM 127 held, LEV2 100, then 50, then 0, a third of the render each (0.3.6: the FM stays, osc 2 fades) |

A note other than 60 goes into the file names: long_CASE_nNOTE_native_*.

Every block's machine output is compared bit for bit with `live.render_two` fed the
inputs the DSP unpacked, whichever engine ran. Writes out/waverider/long_CASE_machine.wav (the oscillator's
output, the samples compared), long_CASE_amp_out.wav (after the amp) and
long_CASE_report.json, each chunk as it finishes. Exit 0 when no sample differs.
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
from dnfw import progress, sharcemu            # noqa: E402
from dnfw.audio import wavio                   # noqa: E402
from dnfw.waverider import dsp, live           # noqa: E402
from dnfw.waverider import frame as FR        # noqa: E402

FOLD, NPOS, TYPE, AMT, WARP, FM = live.SHAPE_SLOTS[:6]
SOLO = {g.TBL1: 0, g.LEV2: 0}                          # osc 1 alone: the loop skips osc 2
ON2 = {g.TBL1: 0, g.TBL2: 0, g.LEV2: 0x6400}
TRIMS = (live.TRIM_DEFAULT_WORD, 0x7F00, 0, 0x2000)
NOTES = (48, 60, 67, 72, 36)


def ramp(b, n, lo, hi):
    return round(lo + (hi - lo) * b / max(n - 1, 1))


def tri(b, period, lo, hi):
    """LO up to HI and back down over PERIOD blocks."""
    p = (b % period) / period
    return round(lo + (hi - lo) * (2 * p if p < 0.5 else 2 - 2 * p))


# case(b, n) -> (the frame words, the note word or None for --note, a trigger on block b,
# TRIM's word or None for the sound's own)
CASES = {
    "hold": lambda b, n: ({**SOLO, g.WAV1: 0x3000}, None, b == 0, None),
    "sweep": lambda b, n: ({**SOLO, g.WAV1: ramp(b, n, 0, 0x7800)}, None, b == 0, None),
    "pitch": lambda b, n: ({**SOLO, g.WAV1: 0x4000}, ramp(b, n, 12 << 8, 120 << 8), b == 0, None),
    "move_pos": lambda b, n: ({**SOLO, g.WAV1: 0, g.MPOS1: 0x6400, g.MOVE1: 0, g.RATE1: 0x6400},
                              None, b == 0, None),
    "move_lev": lambda b, n: ({**SOLO, g.WAV1: 0x4000, g.MLEV1: 0x7F00, g.MOVE1: 0x0700, g.RATE1: 0x6400},
                              None, b == 0, None),
    "levels": lambda b, n: ({**SOLO, g.WAV1: 0x4000, g.LEV1: tri(b, 100, 0x0800, 0x7F00)},
                            None, b == 0, TRIMS[b // 47 % 4]),
    "osc2": lambda b, n: ({**ON2, g.WAV1: 0x2000, g.WAV2: tri(b, 150, 0, 0x7800),
                           g.TUN2: g.TUN1_ZERO + tri(b, 120, -0x0C00, 0x0C00),
                           g.LEV2: 0 if b // 40 % 3 == 2 else 0x6400,
                           g.MPOS2: 0x6400, g.MOVE2: 0, g.RATE2: 0x5000}, None, b == 0, None),
    "warpfm": lambda b, n: ({**ON2, g.WAV1: 0x3000, g.WAV2: 0x5000, g.TUN2: g.TUN1_ZERO + 7 * 256,
                             WARP: ramp(b, n, 0, 0x7F00), FM: ramp(b, n, 0x7F00, 0)}, None, b == 0, None),
    "warp127": lambda b, n: ({**ON2, g.WAV1: 0, g.WAV2: 0, WARP: 0x7F00}, None, b == 0, None),
    "fm127": lambda b, n: ({**ON2, g.WAV1: 0, g.WAV2: 0, FM: 0x7F00}, None, b == 0, None),
    "fm_lev2": lambda b, n: ({**ON2, g.WAV1: 0, g.WAV2: 0, FM: 0x7F00,
                              g.LEV2: (0x6400, 0x3200, 0)[min(3 * b // n, 2)]}, None, b == 0, None),
    "retrig": lambda b, n: ({**ON2, g.WAV1: 0x7000 if b // 30 % 2 else 0x1000, g.DCLK: live.DCLK_DEFAULT,
                             g.TUN2: g.TUN1_ZERO + 3 * 256}, NOTES[b // 30 % 5] << 8,
                            b % 30 in (0, 3), None),
}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("case", choices=sorted(CASES))
    ap.add_argument("--digikit", type=pathlib.Path, default=sharcemu.path())
    ap.add_argument("--image", type=pathlib.Path,
                    default=ROOT / "00_Resources/00_Firmware/Digitone_II_OS1.11_dist.zip")
    ap.add_argument("--blocks", type=int, default=375)
    ap.add_argument("--note", type=int, default=60)
    ap.add_argument("--chunk", type=int, default=25, help="blocks between writes of the files")
    ap.add_argument("--python", action="store_true", help="the Python runner, a second opinion (default: digikit's Rust engine)")
    ap.add_argument("--native", action="store_true", help="the default; kept for old command lines")
    a = ap.parse_args(argv)
    a.native = not a.python
    if a.python:
        g.os.environ["DNFW_WAVERIDER_PYTHON"] = "1"

    dk = g.m1.Digikit(a.digikit)
    g.fx.bind(str(a.digikit / "tools"))
    g.m4.IMAGE = a.image
    stock = g.m1.dn2_section7(a.image)
    sound, machines = g.m4.init_sound(a.image)
    wr = g.Image(dk, dsp.section7(stock))
    tables = dsp.tables()
    case = CASES[a.case]
    g.OUT.mkdir(parents=True, exist_ok=True)
    what = f"Waverider, table 0, note {a.note}, case {a.case}"
    tag = a.case + ("" if a.note == 60 else f"_n{a.note}") + ("_native" if a.native else "")
    engine = "the runner (native engine)" if a.native else "the runner"
    machine, amp, seq, report = [], [], [], {"case": a.case, "note": a.note, "blocks": a.blocks}
    subs, shapes, trims = [], [], []

    def write(done, halt=None):
        want = live.render_two(tables, seq, g.BLOCK, "float32", subs=subs, shapes=shapes, trims=trims)
        bad = g.mismatches(machine, want)
        for name, data, stage in (("machine", machine, "the machine's output, compared with the model"),
                                  ("amp_out", amp, "after the amp, not compared")):
            wavio.write(g.OUT / f"long_{tag}_{name}.wav", data, g.RATE,
                        f"{engine}, not looped, {done} blocks: {what}; {stage}")
        report.update(rendered_blocks=done, samples=len(machine), mismatches=bad, halt=halt)
        (g.OUT / f"long_{tag}_report.json").write_text(json.dumps(report, indent=1) + "\n")
        return bad

    bad = 0
    with tempfile.TemporaryDirectory(dir=g.OUT) as tmp, \
            progress.Job(f"runner long {tag}", total=a.blocks) as job:
        snap, m2mach = g.snapshot_path(dk, stock, pathlib.Path(tmp))
        state = g.init_on(snap, m2mach, wr)
        if a.native:
            state = g.native_on(state, wr)
        for first in range(0, a.blocks, a.chunk):
            n = min(a.chunk, a.blocks - first)

            def fb(b, first=first):
                over, note, trig, trim = case(first + b, a.blocks)
                f = g.base_frame(sound, machines, trigger=trig, overrides=over,
                                 note=a.note << 8 if note is None else note)
                if trim is not None:
                    f.param(0, g.TRIM_SLOT, trim)
                return f.to_bytes()

            got_sub, got_shape = [], []

            def at_loop(r):                     # page 3's and page 5's words, as the shape test reads them
                got_sub.append(tuple(g.frame_word(r.state, FR.slot_offset(0, s)) for s in live.SUB_SLOTS))
                got_shape.append(tuple(g.frame_word(r.state, FR.slot_offset(0, s)) for s in live.SHAPE_SLOTS))
            run = g.run_blocks(state, fb, n, extra_hooks={dsp.COUNT_SW: at_loop})
            if not run["ok"]:
                write(first + run["blocks"], run.get("halt"))
                print(f"FAIL halted in block {first + run['blocks']}: {run.get('halt')}")
                return 1
            machine += g.track_series(run, 0)
            amp += run["amp_out"]
            k = sum(1 for i in run["t5_inputs"] if 0 in i)
            assert len(got_shape) >= k, (len(got_shape), k)
            subs += got_sub[-k:]
            shapes += got_shape[-k:]
            trims += [i[0]["trim"] for i in run["t5_inputs"] if 0 in i]
            seq += [(i[0]["note"], (i[0]["wav1"], i[0]["tbl1"], i[0]["tun1"], i[0]["lev1"], *i[0]["move1"],
                                    i[0]["sync"][0], i[0]["smth"][0]),
                     (*i[0]["osc2"], *i[0]["move2"], i[0]["sync"][1], i[0]["smth"][1]),
                     (i[0]["trig"], i[0]["triggered"], i[0]["prst"], i[0]["song"], i[0]["tempo"], i[0]["dclk"]))
                    for i in run["t5_inputs"] if 0 in i]
            state = run["state"]
            bad = write(first + n)
            job.update(done=first + n, detail=f"{bad} samples differ from the model")
            print(f"  {first + n}/{a.blocks} blocks, {bad} samples differ from the model", flush=True)
    print("PASS" if bad == 0 else "FAIL", f"{len(machine)} samples, {bad} differ from the model")
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())

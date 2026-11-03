"""A pool table reloaded while a note sounds from it: is there a click?

    python scripts/sharc_waverider_reload.py [--digikit DIR] [--lead 24] [--tail 24] [--per-call 7]

Stage 3's load protocol drops an entry from build3's directory while its levels are rebuilt
(`docs/waverider-stage3.md`, "The load"): a voice on that entry plays slot 0, silence since 2026-11-03
(pool tables only), until the entry is whole again. That is two table switches in the middle of a note, at whatever phase the
oscillator is in. This runs it in the runner and measures the step each switch makes.

Per scenario, one held note (TBL1 slot 1 = pool entry 0, WAV1 mid-table, note 60, triggered
at block 1), then the reload's load frames, one to a block (a load frame takes the place of a
parameter frame: the DSP renders the block on the frame it already holds), then build3's idle
calls with `--per-call` render blocks between them (a call is a pair of frames, about 1.7 M
cycles, at the ~35 % idle the load meter shows with a chord playing), then `--tail` blocks.

| scenario | what it isolates |
|---|---|
| none | no reload: the note's own roughness, the baseline |
| same | the entry reloaded with the table it already holds: only the two switches |
| other | a different table: the switches plus the change of timbre |

The track's machine output (before the amp) is written to out/waverider/reload_*.wav (48 kHz,
16-bit, the whole timeline, not looped) with reload_report.json. The measure is the second
difference |s[n+1] - 2 s[n] + s[n-1]|: a smooth oscillation has a small one, a step has a
large one. The report gives each scenario's largest value in the reload window against
none's largest anywhere after the onset, where it falls (which block, which table the reader
had), and the table pointer the reader was handed in each block.

Exit 0 when the report was written; whether a click exists is the report's content.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import struct
import sys
import tempfile
import wave

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import sharc_load_command as lc                              # noqa: E402
import sharc_waverider_m5 as g                               # noqa: E402
from sharc_waverider_pool import table                       # noqa: E402
from dnfw.waverider import dsp, testtable                    # noqa: E402
from dnfw.waverider import loadframes as LF                  # noqa: E402
from dnfw import sharcemu                                    # noqa: E402

SLOT = 0x0100
NONE_SW, POOLED_SW = 0x16FE1C, 0x16EE17    # pool.asm: wr_pool_none. and wr_t5v_pooled
GEOMETRY = {0: (16, 512)}


def load_frames(tab, generation: int, seq: int) -> list[bytes]:
    """Magic cleared, the table as stored, the directory, its magic last."""
    be = LF.table_be(tab)
    be += bytes(512 * LF.sectors(len(tab), len(tab[0])) - len(be))
    out = [LF.magic_frame(0, seq)]
    out += LF.table_frames(LF.pool_address(0) - dsp.LOAD_AREA[0], be, seq + 1)
    out += LF.directory_frames(GEOMETRY, generation, seq + len(out))
    return out


def one_build_call(runner):
    runner = runner.fresh_call(dsp.BUILD3_SW, return_address=dsp.IDLE_RETURN_SW)
    res = g.fx.run(runner, 200_000_000, g.fixups({}), stop_at=(dsp.IDLE_RETURN_SW,))
    if res[0] != "stop":
        raise SystemExit(f"build3: {res[0]} {res[1]}")
    return runner


def built_pointer(runner) -> int:
    return lc.word_at(runner, dsp.BUILT_DM) or 0


def settled(runner) -> bool:
    return (lc.word_at(runner, dsp.BUILD_STATE_DM + 4) or 0) >= dsp.POOL_SLOTS


def timeline(init, frames, reload_tab, lead, tail, per_call, label):
    """-> samples, per block {phase, built, pointer}, the block where the reload began.

    Phases: lead (the old table), load (a load frame in place of the parameter frame),
    build (build3 called every PER_CALL blocks until the entry is whole), tail."""
    series, blocks, state = [], [], init
    n_load = len(load_frames(reload_tab, 2, 1)) if reload_tab else 0
    limit = lead + n_load + 12 * per_call + tail     # 8 pair-calls expected; 12 allowed
    pending: list[bytes] = []
    reload_at = None
    rebuilding = False
    old_ptr = None
    dropped = False
    since_call = 0
    tail_blocks = 0
    k = 0
    while True:
        phase = "lead" if reload_at is None else "tail"
        if reload_tab is not None and k >= lead and reload_at is None:
            reload_at = k
            old_ptr = built_pointer(state)
            pending = load_frames(reload_tab, 2, 1000)
        if pending:
            ok, got = lc.to_render_call(state, LF.dsp_view(pending.pop(0)))
            if not ok:
                raise SystemExit(f"{label}: load frame: {got}")
            state = got["runner"]
            phase = "load"
            rebuilding = not pending
        elif rebuilding:
            phase = "build"
            if since_call % per_call == 0:
                state = one_build_call(state)
                # entry 0 whole: BUILT[0] names another region than the old table's (build3
                # builds into the spare and swaps; until then it names the old table, which
                # plays on). build3 then goes on past the 127 empty entries; no voice
                # depends on that, so it is not waited for.
                # (A build that drops the entry first, as stage 3 did before the spare region,
                # names the same table again: dropped, then back.)
                now_ptr = built_pointer(state)
                dropped |= now_ptr == 0
                if now_ptr != 0 and (now_ptr != old_ptr or dropped):
                    rebuilding = False
                    phase = "tail"
            since_call += 1
        route = {"none": 0, "pooled_r2": []}

        def count_none(_r):
            route["none"] += 1

        def take_pointer(r):
            route["pooled_r2"].append(g.m2.word_reg(r, "R2"))

        run = g.run_blocks(state, lambda _b, k=k: frames(k), 1,
                           extra_hooks={NONE_SW: count_none, POOLED_SW: take_pointer})
        if not run["ok"]:
            raise SystemExit(f"{label}: block {k}: {run.get('halt')}")
        state = run["state"]
        series += g.track_series(run, 0)
        rb = run["reader_blocks"][-1].get(0) if run["reader_blocks"] else None
        blocks.append({"k": k, "phase": phase, "built": built_pointer(state),
                       "pointer": rb[0] if rb else None, "none_hits": route["none"],
                       "pooled_r2": route["pooled_r2"]})
        print(f"    {label} block {k} {phase}", flush=True)
        k += 1
        if reload_tab is None:
            if k >= lead + tail:
                return series, blocks, None
        elif phase == "tail" and not pending and not rebuilding:
            tail_blocks += 1
            if tail_blocks >= tail:
                return series, blocks, reload_at
        if reload_tab is not None and k > limit:
            raise SystemExit(f"{label}: block {k}, still {phase}: more than the {limit} expected "
                             f"({lead} lead, {n_load} load, {12 * per_call} build, {tail} tail)")


def d2(series: list[float]) -> list[float]:
    return [abs(series[n + 1] - 2 * series[n] + series[n - 1]) for n in range(1, len(series) - 1)]


def write_wav(path: pathlib.Path, series: list[float]) -> None:
    peak = max((abs(x) for x in series), default=0) or 1.0
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(48000)
        w.writeframes(b"".join(struct.pack("<h", int(round(32000 * x / peak))) for x in series))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--digikit", type=pathlib.Path, default=sharcemu.path())
    ap.add_argument("--image", type=pathlib.Path,
                    default=ROOT / "00_Resources/00_Firmware/Digitone_II_OS1.11_dist.zip")
    ap.add_argument("--lead", type=int, default=24, help="blocks of the table before the reload")
    ap.add_argument("--tail", type=int, default=24, help="blocks after the entry is whole")
    ap.add_argument("--per-call", type=int, default=2, help="render blocks per build3 call")
    ap.add_argument("--scenarios", default="none,same,other")
    ap.add_argument("--dclk-off", action="store_true",
                    help="DCLK (the crossfade at a jump) off: the control for where a step comes from")
    ap.add_argument("--tag", default="", help="suffix of the output files, so a control keeps its own")
    a = ap.parse_args(argv)

    dk = g.m1.Digikit(a.digikit)
    g.fx.bind(str(a.digikit / "tools"))
    g.m4.IMAGE = a.image
    stock = g.m1.dn2_section7(a.image)
    sound, machines = g.m4.init_sound(a.image)
    wr = g.Image(dk, dsp.section7(stock))
    import numpy as np                                          # noqa: PLC0415
    t = np.arange(512) / 512
    # two SMOOTH waves, so the measure sees only a switch: a saw's own edge is as big a step
    # as any switch and would hide it (the first two runs of this script used a saw and
    # could not have told). A is the fundamental, B the third harmonic; every frame alike.
    tab_a = [np.rint(16000 * np.sin(2 * np.pi * t)).astype(int).tolist()] * 16
    tab_b = [np.rint(16000 * np.sin(2 * np.pi * 3 * t)).astype(int).tolist()] * 16

    def frames(k):
        over = {g.LEV2: 0, g.WAV1: 0x4000, g.TBL1: len(dsp.TABLES_DM) * SLOT}
        if a.dclk_off:
            over[g.DCLK] = 0
        return g.base_frame(sound, machines, trigger=(k == 1), overrides=over).to_bytes()

    wanted = a.scenarios.split(",")
    reloads = {"none": None, "same": tab_a, "other": tab_b}
    g.OUT.mkdir(parents=True, exist_ok=True)
    report = {"lead": a.lead, "tail": a.tail, "per_call": a.per_call, "scenarios": {}}
    with tempfile.TemporaryDirectory(dir=g.OUT) as tmp:
        snap, m2mach = g.snapshot_path(dk, stock, pathlib.Path(tmp))
        init = g.init_on(snap, m2mach, wr)
        print("  loading table A through command 4", flush=True)
        state = init
        for f in load_frames(tab_a, 1, 1):
            ok, got = lc.to_render_call(state, LF.dsp_view(f))
            if not ok:
                raise SystemExit(f"initial load: {got}")
            state = got["runner"]
        for _ in range(4000):
            if settled(state) and built_pointer(state):
                break
            state = one_build_call(state)
        else:
            raise SystemExit("table A was not built")
        base_state = state

        baseline = None
        for name in wanted:
            series, blocks, reload_at = timeline(base_state, frames, reloads[name], a.lead, a.tail,
                                                 a.per_call, name)
            block = len(series) // len(blocks)
            curve = d2(series)
            onset = 4 * block                       # the note's first blocks, before it settles
            steady = max(curve[onset:], default=0.0) if reload_at is None else None
            if name == "none":
                baseline = steady
            window = (reload_at or 0) * block
            peak = max(curve[window:], default=0.0)
            where = curve.index(peak, window) + 1 if peak else 0
            report["scenarios"][name] = {
                "blocks": len(blocks), "block_samples": block, "reload_at_block": reload_at,
                "second_difference_max": peak, "at_sample": where, "at_block": where // block,
                "phase_at_max": blocks[where // block]["phase"] if where // block < len(blocks) else None,
                "pointers": [b["pointer"] for b in blocks],
                "built": [b["built"] for b in blocks],
                "none_hits": [b["none_hits"] for b in blocks],
                "pooled_r2": [b["pooled_r2"] for b in blocks],
                "phases": [b["phase"] for b in blocks],
            }
            write_wav(g.OUT / f"reload_{name}{a.tag}.wav", series)
            print(f"  {name}: {len(blocks)} blocks, reload at {reload_at}, "
                  f"largest second difference {peak:.5f} at block {where // block}")
        if baseline:
            for name, s in report["scenarios"].items():
                s["against_none"] = s["second_difference_max"] / baseline
            report["baseline_none_max"] = baseline
            print(f"  baseline (none, after the onset): {baseline:.5f}")
            for name, s in report["scenarios"].items():
                print(f"  {name}: {s['against_none']:.2f} x the baseline")
    (g.OUT / f"reload_report{a.tag}.json").write_text(json.dumps(report, indent=1) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

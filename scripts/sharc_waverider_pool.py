"""Waverider's +Drive pool in digikit's SHARC runner: load frames in, the levels built in the idle task, a pool table out.

    python scripts/sharc_waverider_pool.py [--digikit DIR] [--blocks 8] [--load-frames FILE]

From the Milestone 2 post-init snapshot, on the section 7 the mod ships
(`dnfw.waverider.dsp.section7`), nothing poked into DDR: the pool gets there the way it
will on the instrument. Each load frame goes through the firmware's own per-frame
handler (sw 0x1c9d6b) to command 4 (`load.asm`), up to the render call, as
`scripts/sharc_load_command.py` runs it. The frames are `dnfw.waverider.loadframes`'s
(the request directory's magic cleared, the tables as stored, the directory, its magic
last), or the ColdFire's own, captured in the emulator (`--load-frames`: 2,688-byte
frames as the ColdFire holds them, back to back). Then the idle loop's back edge runs
build3.asm (`wr_build3`) call after call until every entry is done, and type-5 render
blocks, as `scripts/sharc_waverider_m5.py` step 3 runs them:

| case | must hold |
|---|---|
| no pool (the boot stream's zeros) | TBL1 slot 2 plays slot 0 (the reader's table pointer = baked table 0) |
| the pool's frames | every load frame accepted (reply word 6 = its sequence); DDR holds each table as stored and the request directory |
| before the idle task builds | slot 2 still plays slot 0 |
| built | build3's directory names entry 0's levels; they are `table3`'s layout of the stored table's levels (header exact, rows within 1 LSB: sharc_build3_check.py) |
| slot 2 | plays them: the pointer = entry 0's levels, the machine tap bit-exact to `dnfw.waverider.live` with the levels the DSP built as slot 2 (`table3.read`) |
| slot 3 | entry 1, 5 frames of 1024 points: bit-exact the same way (POS scaled to its frames) |
| slot 1, the same pool | still baked table 1 (the control) |
| slot 4, an empty entry | slot 0 |
| the 128th entry | its table ends at the load area's last byte; slot 129 plays its levels |

Writes out/waverider/pool_*.wav (48 kHz, 16-bit mono, >= 2 s; LOOPED from the runner's
blocks, with a PREVIEW from the reference beside it) and pool_report.json. Exit 0 when
every case passes.
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import struct
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import sharc_load_command as lc                # noqa: E402
import sharc_waverider_m5 as g                 # noqa: E402
from dnfw.waverider import dsp, live, render, testtable   # noqa: E402
from dnfw.waverider import geometry as G       # noqa: E402
from dnfw.waverider import table3 as T3        # noqa: E402
from dnfw.waverider import loadframes as LF    # noqa: E402
from dnfw import sharcemu  # noqa: E402

SLOT = 0x0100                                  # TBL1 per slot: slot = TBL1 >> 8
REPLY_ACK = lc.REPLY_BASE + 0x18                # reply word 6, load.asm's answer


def send_loads(state, frames: list[bytes]) -> tuple[object, list[dict]]:
    """Each frame (ColdFire order) through the handler, from STATE; -> (the last
    runner, per frame {seq, acked, refused})."""
    out, r = [], state
    for f in frames:
        ok, got = lc.to_render_call(r, LF.dsp_view(f))
        if not ok:
            out.append({"halt": got["halt"]})
            return r, out
        r = got["runner"]
        seq = struct.unpack_from(">HH", f, 8)
        sent = seq[1] << 16 | seq[0]
        ack = lc.word_at(r, REPLY_ACK)
        out.append({"seq": sent, "acked": ack == lc.swapped(sent), "load_ran": got["load"],
                    "to_copy": got["at"] == lc.RENDER_CALL and got["R12"] == lc.FRAME_COPY})
    return r, out


def ddr(runner, at: int, n: int) -> bytes:
    """N bytes of DDR, 16 bits at a time (the runner reads a 32-bit word only half
    written as 0: a table's last int16 can share a word with nothing)."""
    out = bytearray()
    for k in range(0, n, 2):
        v = g.fx._dm_read(runner.state, at + k, 2)
        out += struct.pack("<H", v.value & 0xFFFF if isinstance(v, g.fx.Const) else 0)
    return bytes(out[:n])


def build(runner, calls: int = 4000):
    """The idle loop's back edge, call after call, until build3 has been through every
    entry -> (the runner, the calls)."""
    for n in range(calls):
        if (lc.word_at(runner, dsp.BUILD_STATE_DM + 4) or 0) >= dsp.POOL_SLOTS and n:
            return runner, n
        runner = runner.fresh_call(dsp.BUILD3_SW, return_address=dsp.IDLE_RETURN_SW)
        res = g.fx.run(runner, 200_000_000, g.fixups({}), stop_at=(dsp.IDLE_RETURN_SW,))
        if res[0] != "stop":
            raise SystemExit(f"build3, call {n + 1}: {res[0]} {res[1]}")
    raise SystemExit(f"build3 did not finish in {calls} calls")


def table(frames: int, points: int, seed: int) -> list[list[int]]:
    """A table of FRAMES x POINTS int16: a saw darkening to a sine, with a little noise."""
    import numpy as np  # noqa: PLC0415
    rng = np.random.default_rng(seed)
    t = np.arange(points) / points
    out = []
    for f in range(frames):
        keep = max(1, int(round(G.top_harmonic(points, 0) * (1 - f / max(frames, 1)) ** 3)))
        saw = sum(np.sin(2 * np.pi * h * t) / h for h in range(1, keep + 1))
        out.append(np.clip(np.rint(18000 * saw + 300 * rng.standard_normal(points)), -32768, 32767).astype(int).tolist())
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--digikit", type=pathlib.Path,
                    default=sharcemu.path())
    ap.add_argument("--image", type=pathlib.Path,
                    default=ROOT / "00_Resources/00_Firmware/Digitone_II_OS1.11_dist.zip")
    ap.add_argument("--blocks", type=int, default=8)
    ap.add_argument("--seconds", type=float, default=2.5)
    ap.add_argument("--load-frames", type=pathlib.Path,
                    help="the ColdFire's load frames (captured), instead of dnfw.waverider.loadframes'")
    a = ap.parse_args(argv)
    if a.seconds < 2:
        raise SystemExit("--seconds must be at least 2")

    dk = g.m1.Digikit(a.digikit)
    g.fx.bind(str(a.digikit / "tools"))
    g.m4.IMAGE = a.image
    stock = g.m1.dn2_section7(a.image)
    sound, machines = g.m4.init_sound(a.image)
    wr = g.Image(dk, dsp.section7(stock))
    baked = dsp.tables()
    pool = testtable.pool_table()                       # entry 0: 16 x 512
    odd = table(5, 1024, 7)                             # entry 1: 5 x 1024
    geometry = {0: (16, 512), 1: (5, 1024)}             # entry 2: empty
    stored = {0: pool, 1: odd}

    if a.load_frames:
        raw = a.load_frames.read_bytes()
        loads = [raw[k:k + LF.FRAME_BYTES] for k in range(0, len(raw), LF.FRAME_BYTES)]
        source = str(a.load_frames)
    else:
        loads = [LF.magic_frame(0, 1)]
        for j, tab in stored.items():
            be = LF.table_be(tab)
            be += bytes(512 * LF.sectors(len(tab), len(tab[0])) - len(be))      # whole sectors
            loads += LF.table_frames(LF.pool_address(j) - dsp.LOAD_AREA[0], be, len(loads) + 1)
        loads += LF.directory_frames(geometry, 1, len(loads) + 1)
        source = "dnfw.waverider.loadframes"

    def frames(tbl1, wav1=0x4000, **kw):
        def fb(b):
            return g.base_frame(sound, machines, trigger=(b == 1),
                                overrides={g.LEV2: 0, g.WAV1: wav1, g.TBL1: tbl1}, **kw).to_bytes()
        return fb

    report = {"load_frames": source, "frames": len(loads), "blocks": a.blocks}
    checks, wavs = {}, []
    g.OUT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=g.OUT) as tmp:
        snap, m2mach = g.snapshot_path(dk, stock, pathlib.Path(tmp))
        init = g.init_on(snap, m2mach, wr)

        def pointer(run):
            rb = run["reader_blocks"][-1].get(0) if run["ok"] and run["reader_blocks"] else None
            return rb[0] if rb else None

        none = g.run_blocks(init, frames(2 * SLOT), a.blocks)
        checks["no pool: slot 2 plays slot 0"] = pointer(none) == dsp.TABLES_DM[0]

        loaded, sent = send_loads(init, loads)
        report["sent"] = sent
        if a.load_frames:                               # what the ColdFire sent: read it back from DDR
            words = struct.unpack("<128I", ddr(loaded, dsp.POOL_GEOMETRY, 512))
            geometry = {j: (w & 0xFFFF, w >> 16) for j, w in enumerate(words) if w}
            stored = {j: [list(struct.unpack(f"<{n}h", ddr(loaded, LF.pool_address(j) + 2 * n * f, 2 * n)))
                          for f in range(fr)] for j, (fr, n) in geometry.items()}
            report["geometry"] = geometry
        checks["every load frame reaches load.asm and is accepted"] = (
            bool(sent) and all(s.get("load_ran") and s.get("acked") and s.get("to_copy") for s in sent))
        checks["DDR holds each table as stored"] = all(
            ddr(loaded, LF.pool_address(j), 2 * len(t) * len(t[0])) == render.dsp_bytes(t) for j, t in stored.items())
        checks["DDR holds the request directory, its magic"] = (
            ddr(loaded, dsp.POOL_DIR, 16) == struct.pack("<4I", dsp.POOL_MAGIC, dsp.POOL_SLOTS, 1, 0)
            and all(struct.unpack("<I", ddr(loaded, dsp.POOL_GEOMETRY + 4 * j, 4))[0] == f | n << 16
                    for j, (f, n) in geometry.items()))
        early = g.run_blocks(loaded, frames(2 * SLOT), a.blocks)
        checks["before the idle task builds: slot 2 plays slot 0"] = pointer(early) == dsp.TABLES_DM[0]

        built, calls = build(loaded)
        report["build_calls"] = calls
        levels_at = [dsp.LEVELS_AT + j * dsp.LEVELS_SLOT for j in range(dsp.POOL_SLOTS)]
        names = [lc.word_at(built, dsp.BUILT_DM + 4 * j) for j in range(dsp.POOL_SLOTS)]
        checks["build3 names each entry with a table, and no other"] = names == [
            levels_at[j] | 1 if j in geometry else 0 for j in range(dsp.POOL_SLOTS)]
        got = {j: T3.Table3.from_dsp(ddr(built, levels_at[j], T3.size_bytes(*geometry[j]))) for j in stored}
        worst = 0
        for j, tab in stored.items():
            import numpy as np  # noqa: PLC0415
            want = [np.clip(np.rint(lv), -32768, 32767) for lv in G.table_levels(np.array(tab, float))]
            worst = max(worst, max(int(np.max(np.abs(np.array(gl) - w))) for gl, w in zip(got[j].levels, want)))
        report["levels_worst_lsb"] = worst
        checks["the levels built are the model's within 1 LSB"] = worst <= 1
        tables = [*baked] + [got.get(j, baked[0]) for j in range(max(got) + 1)]   # the reference: the pool as built

        play = g.run_blocks(built, frames(2 * SLOT), a.blocks)
        mism = g.mismatches(g.track_series(play, 0), g.reference_for(play, 0, tables)) if play["ok"] else -1
        report["pool_mismatches"] = mism
        checks["slot 2 plays entry 0's levels (the reader's table pointer)"] = pointer(play) == levels_at[0] | 1
        checks["slot 2 is bit-exact to dnfw.waverider.live with the levels built"] = mism == 0
        play3 = g.run_blocks(built, frames(3 * SLOT, wav1=0x5a00), a.blocks)
        mism3 = g.mismatches(g.track_series(play3, 0), g.reference_for(play3, 0, tables)) if play3["ok"] else -1
        report["odd_mismatches"] = mism3
        checks[f"slot 3, {'%d x %d' % geometry[1]}: its levels, bit-exact (POS scaled to its frames)"] = (
            pointer(play3) == levels_at[1] | 1 and mism3 == 0)
        ctrl = g.run_blocks(built, frames(1 * SLOT), a.blocks)
        checks["slot 1 still plays baked table 1"] = pointer(ctrl) == dsp.TABLES_DM[1]
        empty = next(j for j in range(dsp.POOL_SLOTS) if j not in geometry)
        gone = g.run_blocks(built, frames((2 + empty) * SLOT), a.blocks)
        checks[f"slot {2 + empty}, an empty entry: slot 0"] = pointer(gone) == dsp.TABLES_DM[0]

        # the 128th entry: its table ends at the load area's last byte
        last = dsp.POOL_SLOTS - 1
        be = LF.table_be(pool)
        tail = [LF.magic_frame(0, 300)]
        tail += LF.table_frames(LF.pool_address(last) - dsp.LOAD_AREA[0], be, 301)
        tail += LF.directory_frames({last: (16, 512)}, 2, 301 + len(tail))
        full, sent4 = send_loads(built, tail)
        full, _ = build(full)
        top = g.run_blocks(full, frames((2 + last) * SLOT), a.blocks)
        at_last = dsp.LEVELS_AT + last * dsp.LEVELS_SLOT
        checks[f"the 128th entry: slot {2 + last} (TBL1 {(2 + last) * SLOT:#06x}) plays its levels"] = (
            all(s.get("acked") for s in sent4) and LF.pool_address(last) + dsp.POOL_RAW_BYTES == dsp.LOAD_AREA[1]
            and pointer(top) == at_last | 1)

        series = g.track_series(play, 0) if play["ok"] else []
        g.wav("pool_slot2_runner.wav", series, a.seconds, wavs,
              "the runner: TBL1 slot 2 = the pool table loaded through command 4, WAV1 64, note 60")
        g.wav("pool_slot2_preview.wav", g.preview(tables, 60.0, 0, 0x7800, 2 * SLOT, a.seconds),
              a.seconds, wavs, "PREVIEW (the reference, not the runner): the pool table swept "
                               "POS 0 -> 120, note 60")
    report["checks"] = checks
    report["wavs"] = wavs
    (g.OUT / "pool_report.json").write_text(json.dumps(report, indent=1, default=str) + "\n")
    for k, v in checks.items():
        print(f"  {'ok  ' if v else 'FAIL'} {k}")
    for w in wavs:
        print(f"  wav {w['file']}: {w['what']}")
    passed = all(checks.values())
    print("PASS" if passed else "FAIL", f"{sum(checks.values())}/{len(checks)}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())

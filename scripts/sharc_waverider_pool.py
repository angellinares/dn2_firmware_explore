"""Waverider's +Drive pool in digikit's SHARC runner: load frames in, a pool table out.

    python scripts/sharc_waverider_pool.py [--digikit DIR] [--blocks 8] [--load-frames FILE]

From the Milestone 2 post-init snapshot, on the section 7 the mod ships
(`dnfw.waverider.dsp.section7`), nothing poked into DDR: the pool gets there the way it
will on the instrument. Each load frame goes through the firmware's own per-frame
handler (sw 0x1c9d6b) to command 4 (`load.asm`), up to the render call, as
`scripts/sharc_load_command.py` runs it. The frames are `dnfw.waverider.loadframes`'s,
or the ColdFire's own, captured in the emulator (`--load-frames`: 2,688-byte frames as
the ColdFire holds them, back to back). Then type-5 render blocks, as
`scripts/sharc_waverider_m5.py` step 3 runs them:

| case | must hold |
|---|---|
| no pool (the boot stream's zeros) | TBL1 slot 2 plays slot 0 (the reader's table pointer = baked table 0) |
| the pool table, then its directory | every load frame accepted (reply word 6 = its sequence); DDR holds the table in the reader's layout; slot 2 plays it: the pointer = pool entry 0, the machine tap bit-exact to `dnfw.waverider.live` with the pool table as slot 2 |
| slot 1, the same pool | still baked table 1 (the control) |
| slot 3, past the pool's count of 1 | slot 0 |
| a directory whose entry 0 is empty | slot 2 plays slot 0 |

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
from dnfw.waverider import loadframes as LF    # noqa: E402

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
    return b"".join(struct.pack("<I", lc.word_at(runner, at + k)) for k in range(0, n, 4))


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
    pool = testtable.pool_table()
    tables = [*baked, pool]                     # the reference: slot 2 is pool entry 0
    at0 = LF.pool_address(0)

    if a.load_frames:
        raw = a.load_frames.read_bytes()
        loads = [raw[k:k + LF.FRAME_BYTES] for k in range(0, len(raw), LF.FRAME_BYTES)]
        source = str(a.load_frames)
    else:
        loads = LF.table_frames(at0 - dsp.LOAD_AREA[0], LF.table_be(pool), 1)
        loads += LF.directory_frames({0: at0}, len(loads) + 1)
        source = "dnfw.waverider.loadframes"
    empty_dir = LF.directory_frames({}, 100)
    short_dir = LF.table_frames(dsp.POOL_DIR - dsp.LOAD_AREA[0], LF.pool_directory({0: at0}, count=1), 101)

    def frames(tbl1, **kw):
        def fb(b):
            return g.base_frame(sound, machines, trigger=(b == 1),
                                overrides={g.LEV2: 0, g.WAV1: 0x4000, g.TBL1: tbl1}, **kw).to_bytes()
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
        checks["every load frame reaches load.asm and is accepted"] = (
            bool(sent) and all(s.get("load_ran") and s.get("acked") and s.get("to_copy") for s in sent))
        in_ddr = ddr(loaded, at0, dsp.TABLE_BYTES)
        checks["DDR holds the pool table in the reader's layout"] = in_ddr == render.dsp_bytes(pool)
        checks["DDR holds the pool directory"] = (
            ddr(loaded, dsp.POOL_DIR, 12) == struct.pack("<3I", dsp.POOL_MAGIC, dsp.POOL_SLOTS, at0))

        play = g.run_blocks(loaded, frames(2 * SLOT), a.blocks)
        mism = g.mismatches(g.track_series(play, 0), g.reference_for(play, 0, tables)) if play["ok"] else -1
        report["pool_mismatches"] = mism
        checks["slot 2 plays pool entry 0 (the reader's table pointer)"] = pointer(play) == at0
        checks["slot 2 is bit-exact to dnfw.waverider.live with the pool table"] = mism == 0
        ctrl = g.run_blocks(loaded, frames(1 * SLOT), a.blocks)
        checks["slot 1 still plays baked table 1"] = pointer(ctrl) == dsp.TABLES_DM[1]

        short, sent2 = send_loads(loaded, short_dir)
        past = g.run_blocks(short, frames(3 * SLOT), a.blocks)
        checks["slot 3, past a pool of 1: slot 0"] = (
            all(s.get("acked") for s in sent2) and pointer(past) == dsp.TABLES_DM[0])
        emptied, sent3 = send_loads(loaded, empty_dir)
        gone = g.run_blocks(emptied, frames(2 * SLOT), a.blocks)
        checks["an empty entry: slot 2 plays slot 0"] = (
            all(s.get("acked") for s in sent3) and pointer(gone) == dsp.TABLES_DM[0])

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

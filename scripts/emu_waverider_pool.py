"""Waverider's pool on the ColdFire, in digikit's Rust emulator: the store on the
+Drive in, the loader's frames out.

    python scripts/emu_waverider_pool.py SYX [--panel-drive EXE] [--out DIR]

The build's own layout (`src/dnfw/mods/waverider_code.json`) says where to look. The
+Drive is zeros but for a store, written here with `dnfw.waverider.store`: slot 0 the
pool test table (`testtable.pool_table`), slot 3 the baked test table, and slot 5 a
table the pool cannot play (32 waves). The image boots from reset with `panel_drive
--card-extent`.

**The emulator runs no audio ISR** (the stock send 0x400cf7be and our hook at
0x40025e82 never execute, measured), so this plays its part and the DSP's. From the UI
loop it calls `wr_frame_src` itself with a quiet frame, as the hook would, then reads
the chunk the loader picked out of its queue, and acknowledges it as load.asm does:
the chunk's sequence in reply word 6 (0x800053a4 + 0x18), which nothing else writes
(on the instrument too: tools/dn2replyscan.py). A run with no acknowledgement shows the give-up instead.

| check | must hold |
|---|---|
| the store | wr_store: generation 1, no read errors |
| the pool | slots 0 and 3 (slot 5, 32 waves, left out); names their first five characters |
| the frames | every frame the loader sent is `dnfw.waverider.loadframes`'s, byte for byte: table 0 to pool 0, table 3 to pool 1, then the directory naming both |
| acknowledged | the pool reads ready, count 2, every chunk acked once and none resent |
| the display spans | both pool tables' spans at 0x46a00000 equal `dnfw.waverider.wave.pool_spans` |
| no answer | a second boot, never acknowledged: the loader gives up after 8 timeouts and the pool offers nothing |

The frames go to out/waverider/emu_pool_frames.bin, for
`scripts/sharc_waverider_pool.py --load-frames`. Exit 0 when every check passes.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import struct
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from dnfw.waverider import loadframes as LF        # noqa: E402
from dnfw.waverider import store as ST             # noqa: E402
from dnfw.waverider import testtable, wave         # noqa: E402

PANEL = ROOT.parent / "digikit-rust/out/native/target-host/release/examples/panel_drive.exe"
POOL_FIELDS = "magic state count fills generation changes_seen spare".split()
LOAD_FIELDS = ("magic queued sent resent acked refused timeouts held read_errors last_rc "
               "want_sector want_bytes want_dest done_bytes failed queue queue_chunks").split()
STORE_FIELDS = "magic group generation read_errors reads changes".split()
FRAME = LF.FRAME_BYTES
UI_LOOP = 0x4002E464              # coldfire.POLL_SITE: the UI loop, where our calls are made
REPLY_ACK = 0x800053A4 + 0x18     # reply word 6, load.asm's answer
SPANS = 0x46A00000
SPAN_BYTES = 16 * 2 * 96
QUIET = "00" * 44                 # a frame's first 44 bytes, its masks (32..43) zero


def store_extents(work: pathlib.Path) -> tuple[list[str], dict]:
    """-> panel_drive's --card-extent arguments, and what was stored."""
    tables = {0: ("Pulse narrowing", testtable.pool_table()), 3: ("Saw to sine", testtable.table())}
    entries, payloads = {}, {}
    for n, (name, t) in tables.items():
        data = LF.table_be(t)
        entries[n] = ST.Entry(name, 16, 512, ST.slot_start(n), len(data), ST.xxh32(data), 0, len(data))
        payloads[n] = data
    wide = bytes(32 * 512 * 2)                     # 32 waves: stored, not playable
    entries[5] = ST.Entry("Too wide", 32, 512, ST.slot_start(5), len(wide), ST.xxh32(wide), 0, len(wide))
    payloads[5] = wide
    index = ST.index_bytes(entries)
    files = {ST.REGION: ST.superblock(1, len(entries), index, ST.DATA_END), ST.REGION + 1: index}
    files.update({ST.REGION + ST.slot_start(n): p for n, p in payloads.items()})
    args = []
    for sector, data in files.items():
        f = work / f"s{sector:x}.bin"
        f.write_bytes(data)
        args += ["--card-extent", f"{sector:#x}:{f}"]
    return args, {"tables": tables, "payloads": payloads}


def expected_frames(stored, seq: int = 1) -> list[bytes]:
    out = []
    for j, n in enumerate(sorted(stored["tables"])):
        f = LF.table_frames(LF.pool_address(j) - LF.pool_address(0), stored["payloads"][n], seq)
        out += f
        seq += len(f)
    return out + LF.directory_frames({0: LF.pool_address(0), 1: LF.pool_address(1)}, seq)


def fields(hexdata: str, names: list[str]) -> dict:
    raw = bytes.fromhex(hexdata)
    return dict(zip(names, struct.unpack(f">{len(names)}I", raw[:4 * len(names)])))


def drive(a, extents, layout, steps: list[str], tmp) -> dict:
    cmd = [str(a.panel_drive), str(a.syx), *extents, "--out", tmp,
           "--call-at", f"{UI_LOOP:#x}", "--call-fn", f"{layout['wr_frame_src']:#x}",
           "--steps", ",".join(steps)]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)
    lines = r.stdout.strip().splitlines()
    if not lines:
        raise SystemExit(f"panel_drive said nothing: {r.stderr[-2000:]}")
    return json.loads(lines[-1])


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("syx", type=pathlib.Path)
    ap.add_argument("--panel-drive", type=pathlib.Path, default=PANEL)
    ap.add_argument("--out", type=pathlib.Path, default=ROOT / "out/waverider")
    ap.add_argument("--wait", default="1200M", help="instructions past the UI (the pool starts at 5 s)")
    a = ap.parse_args(argv)
    layout = json.loads((ROOT / "src/dnfw/mods/waverider_code.json").read_text())["layout"]
    pool_at, load_at, store_at = layout["wr_pool"], layout["wr_load"], layout["wr_store"]
    a.out.mkdir(parents=True, exist_ok=True)
    pool_bytes = 4 * len(POOL_FIELDS) + 127 + 127 * 8
    status = [f"peek:{pool_at:#x}:{pool_bytes}", f"peek:{load_at:#x}:{4 * len(LOAD_FIELDS)}",
              f"peek:{store_at:#x}:{4 * len(STORE_FIELDS)}"]

    with tempfile.TemporaryDirectory() as tmp:
        extents, stored = store_extents(pathlib.Path(tmp))
        want = expected_frames(stored)
        # the queue's address, from a first look
        first = drive(a, extents, layout, [f"wait:{a.wait}", *status], tmp)
        load0 = fields([r for r in first["results"] if "hex" in r][1]["hex"], LOAD_FIELDS)
        queue, slots = load0["queue"], load0["queue_chunks"]
        # the exchange, played: per chunk a quiet frame twice (the rule wants it and
        # the one before it quiet), the chunk read back, its sequence acknowledged.
        # then a write's mark (wr_store.changes, which route.c's commit raises) and the
        # same exchange again: the refill, its sequences going on from the first fill's
        again = expected_frames(stored, len(want) + 1)
        steps = [f"wait:{a.wait}"]
        for k, f in enumerate(want + again):
            if k == len(want):
                steps += [f"send:{QUIET}", "wait:40M", *status,
                          f"poke:{store_at + 20:#x}:00000001"]
            s = struct.unpack_from(">HH", f, 8)
            seq = s[1] << 16 | s[0]
            # the first call takes the last acknowledgement; the UI pass then queues
            # what comes next; two quiet frames send it
            steps += [f"send:{QUIET}", "wait:20M", f"send:{QUIET}", f"send:{QUIET}",
                      f"peek:{queue + FRAME * (k % slots):#x}:{FRAME}",
                      f"poke:{REPLY_ACK:#x}:{seq:08x}"]
        steps += ["wait:20M", f"send:{QUIET}", "wait:40M", *status,
                  f"peek:{SPANS:#x}:{2 * SPAN_BYTES}"]
        run = drive(a, extents, layout, steps, tmp)
        res = [r for r in run["results"] if "hex" in r]
        got = [bytes.fromhex(r["hex"]) for r in res if r.get("peek") and int(r["peek"], 16) >= queue
               and int(r["peek"], 16) < queue + FRAME * slots]
        got, got_again = got[:len(want)], got[len(want):]
        mids = [r for r in res if r.get("peek") == f"{pool_at:#x}"]
        pool_first = fields(mids[0]["hex"], POOL_FIELDS)
        tail = res[-4:]
        pool, load, st = (fields(tail[0]["hex"], POOL_FIELDS), fields(tail[1]["hex"], LOAD_FIELDS),
                          fields(tail[2]["hex"], STORE_FIELDS))
        praw = bytes.fromhex(tail[0]["hex"])
        slot_of = list(praw[4 * len(POOL_FIELDS):4 * len(POOL_FIELDS) + 2])
        nb = praw[4 * len(POOL_FIELDS) + 127:]
        names = [nb[8 * j:8 * j + 8].split(b"\0")[0].decode("cp1252") for j in range(2)]
        spans = bytes.fromhex(tail[3]["hex"])
        # no answer: never acknowledged
        silent = drive(a, extents, layout, [f"wait:{a.wait}"] + [f"send:{QUIET}"] * 260
                       + ["wait:20M", *status], tmp)
        sres = [r for r in silent["results"] if "hex" in r]
        sp, sl = fields(sres[0]["hex"], POOL_FIELDS), fields(sres[1]["hex"], LOAD_FIELDS)

    (a.out / "emu_pool_frames.bin").write_bytes(b"".join(got))
    model_spans = b"".join(wave.pool_spans(stored["tables"][n][1]) for n in sorted(stored["tables"]))
    frames_ok = [g == w for g, w in zip(got, want)]
    checks = {
        "every run ran to its end": all(r.get("outcome") == "done" for r in (first, run, silent)),
        "the store: generation 1, no read errors": st["generation"] == 1 and st["read_errors"] == 0,
        "the pool took slots 0 and 3, not 5 (32 waves)": slot_of == [0, 3],
        "their names' first five characters": names == ["Pulse", "Saw t"],
        f"all {len(want)} frames are dnfw.waverider.loadframes', byte for byte":
            len(got) == len(want) and all(frames_ok),
        "the pool reads ready with 2 tables after the first fill": pool_first["state"] == 3
            and pool_first["count"] == 2 and pool_first["fills"] == 1,
        "after a write's mark it fills again: the same frames, sequences going on":
            len(got_again) == len(again) and all(g == w for g, w in zip(got_again, again))
            and pool["state"] == 3 and pool["count"] == 2 and pool["fills"] == 2 and pool["changes_seen"] == 1,
        "every chunk of both fills acked once, none resent":
            load["acked"] == 2 * len(want) and load["sent"] == 2 * len(want) and load["resent"] == 0
            and not load["failed"],
        "both pool tables' spans are wave.pool_spans'": spans == model_spans,
        "never acknowledged: the loader gives up after 8 timeouts, the pool offers nothing":
            sl["failed"] == 1 and sl["timeouts"] == 8 and sl["acked"] == 0 and sp["state"] == 5
            and sp["count"] == 0,
    }
    report = {"pool": pool, "slot_of": slot_of, "names": names, "load": load, "store": st,
              "frames_ok": frames_ok, "silent": {"pool": sp, "load": sl}, "checks": checks,
              "wall": [x.get("wall_seconds") for x in (first, run, silent)]}
    (a.out / "emu_pool_report.json").write_text(json.dumps(report, indent=1) + "\n")
    for k, v in checks.items():
        print(f"  {'ok  ' if v else 'FAIL'} {k}")
    print(json.dumps({"pool": pool, "load": load, "silent_load": sl}))
    passed = all(checks.values())
    print("PASS" if passed else "FAIL", f"{sum(checks.values())}/{len(checks)}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())

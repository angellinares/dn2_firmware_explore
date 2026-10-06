"""SAVE PROJECT AS and LOAD PROJECT carry the pool lists, in the emulator.

    python scripts/emu_waverider_projects.py BUILD.syx [--card out/dk-dn2-card.img] [--frames]

One panel_drive run on the card image (docs/for-dnx-waverider-pool.md §2, the hooks in
csrc/wrstore/projects.c). The panel does what the owner would; the Data API, through the
SysEx router as DNX sends it, writes and reads the records:
1. SAVE PROJECT AS 002 with no record 0: record 2 becomes an automatic record;
2. DNX writes record 0 = [3, NONE, 0]; SAVE PROJECT AS 003: record 3 is that list;
3. DNX writes record 0 = [7]; LOAD PROJECT 003: record 0 is [3, NONE, 0] again;
4. LOAD PROJECT 002: record 0 is automatic;
5. CREATE NEW (in the LOAD list): record 0 is an empty list, stored and not automatic.
After each step the records are read back over /wavepool, and wr_projects is peeked.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import struct
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from dnfw.waverider import poolrecord as PR                         # noqa: E402
from emu_waverider_rename import Frames, dec                        # noqa: E402
from emu_waverider_wavepool import container                        # noqa: E402

PANEL = ROOT.parent / "digikit-rust/out/native/target-host/release/examples/panel_drive.exe"
ROUTER = ["--call-at", "0x4002e464", "--call-fn", "0x4012166e", "--call-args", "2",
          "--capture", "0x401233f2:0:1"]
NO, SETTINGS, YES, UP, DOWN = 12, 8, 10, 11, 14
NONE = PR.NONE


def taps(*keys, wait="40M"):
    return [s for k in keys for s in (f"tap:{k}", f"wait:{wait}")]


def project_menu():
    """From the main screen to SETTINGS > PROJECT, the cursor on LOAD PROJECT"""
    return taps(NO, NO, NO, SETTINGS, YES) + taps(UP, UP, UP)


def to_slot(index):
    """In a slot list: to the top, then INDEX rows down"""
    return taps(*([UP] * 10), wait="40M") + taps(*([DOWN] * index), wait="40M")


def save_as(slot, tag):
    return (project_menu() + taps(DOWN, YES, wait="60M") + to_slot(slot - 1)
            + taps(YES, wait="80M") + [f"frame:{tag}_name"] + taps(YES, wait="900M")
            + [f"frame:{tag}_done"] + taps(NO, NO, NO, wait="40M"))


def load(row, tag):
    """ROW in the load list (it lists saved projects only, then CREATE NEW)"""
    return (project_menu() + taps(YES, wait="60M") + to_slot(row) + [f"frame:{tag}_list"]
            + taps(YES, wait="80M") + [f"frame:{tag}_ask1"])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("build")
    ap.add_argument("--card", default=str(ROOT / "out/dk-dn2-card.img"))
    ap.add_argument("--out", default=str(ROOT / "out/wrprojects"))
    a = ap.parse_args()
    out = pathlib.Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    layout = json.loads((ROOT / "src/dnfw/mods/waverider_code.json").read_text())["layout"]
    projects_at = layout["wr_projects"]

    f = Frames()
    steps: list[str] = ["tap:12", "wait:30M"]
    reads: dict[str, int] = {}                     # label -> index of its open in f.lines

    def api_write(label, p, entries, automatic=False):
        start = len(f.lines)
        f.write(label, f"/wavepool/{p}", container(PR.Record(p, entries, automatic).to_bytes(), p, 0x50))
        steps.extend(f"send:{h}" for _, h in f.lines[start:])

    def api_read(label, p):
        start = len(f.lines)
        f.handle += 1
        f.frame(label + ":open", 0x54, f"/wavepool/{p}\0".encode() + struct.pack(">I", 0x4000))
        f.frame(label + ":seq1", 0x55, struct.pack(">II", f.handle, 1))
        steps.extend(f"send:{h}" for _, h in f.lines[start:])
        reads[label] = start

    def peek(label):
        steps.append(f"peek:{projects_at:#x}:28")

    steps += save_as(2, "s2")
    api_read("after_s2_rec2", 2)
    peek("p1")
    api_write("w0a", 0, [3, NONE, 0])
    steps += save_as(3, "s3")
    api_read("after_s3_rec3", 3)
    api_write("w0b", 0, [7])
    steps += load(1, "l3")                         # rows: 002, 003, CREATE NEW
    steps += taps(NO, wait="60M") + ["frame:l3_ask2"] + taps(YES, wait="1500M") + ["frame:l3_done"]
    api_read("after_l3_rec0", 0)
    peek("p2")
    steps += load(0, "l2") + taps(NO, wait="60M") + ["frame:l2_ask2"] + taps(YES, wait="1500M")
    steps += ["frame:l2_done"]
    api_read("after_l2_rec0", 0)
    peek("p3")
    steps += (project_menu() + taps(YES, wait="60M") + to_slot(2) + ["frame:n_list"]
              + taps(YES, wait="80M") + ["frame:n_ask1"] + taps(YES, wait="900M") + ["frame:n_done"])
    api_read("after_new_rec0", 0)
    peek("p4")

    steps_file = out / "steps.txt"
    steps_file.write_text("\n".join(steps) + "\n")
    r = subprocess.run([str(PANEL), a.build, "--card-image", a.card, "--out", str(out), *ROUTER,
                        "--regs-at", "0x400f6960,0x400f6a2c", "--steps", f"@{steps_file}"],
                       capture_output=True, text=True, timeout=3600)
    report = json.loads(r.stdout.strip().splitlines()[-1])
    (out / "report.json").write_text(json.dumps(report, indent=1))
    if report["outcome"] != "done":
        print("FAIL", report["outcome"], report.get("fault"))
        return 1
    stream = b"".join(bytes.fromhex(c["hex"]) for c in report["captures"])
    replies = [dec((m + b"\xf7").hex())[5:] for m in stream.split(b"\xf7") if m.startswith(b"\xf0")]
    # the replies come in request order, one each; the router's reply to a request
    # carries the request's message id in its first two bytes, so match by that
    by_id = {}
    for m in stream.split(b"\xf7"):
        if m.startswith(b"\xf0"):
            d = dec((m + b"\xf7").hex())
            by_id[(d[2] << 7) | d[3]] = d[5:]
    ids = {label: k + 1 for k, (label, _) in enumerate(f.lines)}

    def record(label):
        d = by_id.get(ids[label + ":seq1"], b"")
        at = d.find(bytes.fromhex("ac11d303"))
        if at < 0:
            return None
        rec, checks = PR.from_bytes(d[at + 31:at + 31 + 512])
        return rec

    peeks = [bytes.fromhex(x["hex"]) for x in report["results"] if "hex" in x]
    counters = [struct.unpack(">7I", p) for p in peeks]
    calls = [(x["pc"], int(x["stack"][2], 16)) for x in report["regs"]]
    ok = True

    def check(what, cond, detail=""):
        nonlocal ok
        ok &= bool(cond)
        print(("PASS " if cond else "FAIL ") + what + (f"  ({detail})" if detail else ""))

    r2, r3, l3, l2, nw = (record(x) for x in ("after_s2_rec2", "after_s3_rec3", "after_l3_rec0",
                                              "after_l2_rec0", "after_new_rec0"))
    check("the stock calls: save 1, 128; save 2, 128; load 2; ...; load 1",
          [c for c in calls if c[0] == "0x400f6a2c"] == [("0x400f6a2c", 2), ("0x400f6a2c", 1)]
          and ("0x400f6960", 1) in calls and ("0x400f6960", 2) in calls, calls)
    check("SAVE AS 002 with no record 0: record 2 automatic, stored",
          r2 and r2.automatic and r2.generation >= 1 and r2.project == 2, r2)
    check("SAVE AS 003: record 3 is record 0's list [3, NONE, 0]",
          r3 and not r3.automatic and r3.entries == [3, NONE, 0] and r3.project == 3, r3)
    check("LOAD 003: record 0 is [3, NONE, 0] again", l3 and not l3.automatic and l3.entries == [3, NONE, 0]
          and l3.project == 0, l3)
    check("LOAD 002: record 0 automatic", l2 and l2.automatic and l2.project == 0, l2)
    check("CREATE NEW: record 0 an empty list, stored, not automatic",
          nw and not nw.automatic and nw.entries == [] and nw.project == 0 and nw.generation > l2.generation, nw)
    check("wr_projects: 2 saves, 2 loads, 1 created, none failed",
          len(counters) == 4 and counters[0][1] == 1 and counters[2][1] == 2 and counters[2][2] == 2
          and counters[3][6] == 1 and counters[3][5] == 0, counters)
    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

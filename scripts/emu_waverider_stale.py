"""A pattern change marks every voice unplayed, so page 1 draws no modulation from an old sound (instrument, wrl2b, 2026-11-03).

    python scripts/emu_waverider_stale.py BUILD.syx --layout CODE.json [--out DIR] [--control]

The owner's report: on a new pattern with Waverider on track 1, POS moved on page 1 with no LFO and no
MOVE in the sound; again after FM Tone tracks took the page's voice. Each pattern has its own kit, and
a voice holds the old kit's sound until its next note. With a Waverider in both patterns, no
`unplayed` bit was set (events.c), so the page read voices that still ran the old sound's MOVE.
The frame hook now sets every bit when the live kit (0x800052a0, &kits[active pattern]) changes.

The emulator runs no pattern load, so the case pokes the kit pointer. With --ssi-hz 96000 the
audio-frame interrupt runs the hook:
1. clear `unplayed` and read it (`u0`): the voices read as another machine, so the hook sets the bits
   again, which shows it ran;
2. make every track a Waverider in the builder's copy, clear and read (`u1`);
3. poke the kit pointer one kit up (23,921 B, as on the instrument) and read (`u2`);
4. clear and read again (`u3`).

Pass: `u0` and `u2` are 0xffff, `u1` and `u3` are 0. With --control (a build without the fix): `u2`
equals `u1`, the report's state.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import subprocess

ROOT = pathlib.Path(__file__).resolve().parent.parent

UNPLAYED_AT = 26                         # struct wr_events (events.h): magic, clears, notes[16], shown_osc, scope_track
LIVE_KIT = 0x800052A0                    # &kits[active pattern] (events.c)
KIT_STRIDE = 23921
TRACK_COPY = 0x80003AF0 + 3468             # the frame builder's per-track copy, 153 B a track (docs/machine-list.md)
SSI_PANEL = ROOT.parent / "digikit-rust/out/native/target-readwatch/release/examples/panel_drive.exe"
SSI_CWD = ROOT.parent / "digikit-wt-readwatch"
STOCK_SYX_SHA256 = "2af43e65e3d8390b41c9f66222620f8cce027d73ed87db00c80b440f628472e0"   # Digitone II 1.11, for --base

TO_WAVERIDER = (["tap:12", "wait:30M", "press:17", "wait:20M", "tap:2", "wait:40M", "release:17", "wait:60M"]
                + [x for _ in range(4) for x in ("tap:14", "wait:40M")] + ["tap:10", "wait:200M", "tap:2", "wait:60M"])


def run(panel, build, out, steps, extra=(), cwd=None):
    out.mkdir(parents=True, exist_ok=True)
    (out / "steps.txt").write_text("\n".join(steps) + "\n")
    r = subprocess.run([str(panel), str(build), "--out", str(out), "--watch", "0x4011ea6a", *extra,
                        "--steps", f"@{out / 'steps.txt'}"], capture_output=True, text=True, timeout=3600,
                       cwd=cwd)
    lines = r.stdout.strip().splitlines()
    if not lines:
        raise SystemExit(f"panel_drive said nothing (rc {r.returncode}): {r.stderr[-2000:]}")
    return json.loads(lines[-1])


def kit_case(a, events, out):
    at = events + UNPLAYED_AT
    clear = [f"poke:{at:#x}:0000", "wait:20M", f"peek:{at:#x}:2"]
    # u0: the emulator's voices read as another machine, so the hook sets a cleared bit again: it ran
    s = list(TO_WAVERIDER) + ["wait:100M", f"peek:{LIVE_KIT:#x}:4"] + clear
    # every track a Waverider in the builder's per-track copy (0x80003af0 + 3468 + 153t, byte 0: the
    # machine type, which the frame carries at 148 + 2t), so the hook keeps a cleared bit
    s += [f"poke:{TRACK_COPY + 153 * t:#x}:05" for t in range(16)] + ["wait:20M"]
    s += clear                                                                     # u1
    s += ["@kit", "wait:20M", f"peek:{at:#x}:2"]                                   # u2
    s += clear                                                                     # u3
    flags = ("--ssi-hz", "96000", "--base", STOCK_SYX_SHA256)
    first = run(a.ssi_panel, a.build, out / "kit0", s[:s.index("@kit")], flags, a.ssi_cwd)
    kit = int(next(r["hex"] for r in first["results"] if r.get("peek") == f"{LIVE_KIT:#010x}"), 16)
    s[s.index("@kit")] = f"poke:{LIVE_KIT:#x}:{kit + KIT_STRIDE:08x}"
    report = run(a.ssi_panel, a.build, out / "kit", s, flags, a.ssi_cwd)
    seen = [int(r["hex"], 16) for r in report["results"] if r.get("peek") == f"{at:#010x}"]
    print(f"kit: live kit 0x{kit:08x}; unplayed u0, u1, u2, u3: {' '.join(f'0x{x:04x}' for x in seen)}")
    checks = {"kit: no fault": all(w["hits"] == 0 for w in report.get("watched", [])) and report.get("outcome") == "done",
              "kit: four readings": len(seen) == 4}
    if len(seen) == 4:
        u0, u1, u2, u3 = seen
        checks["kit: the frame hook ran (u0: it set the cleared bits of the other machine's voices)"] = u0 == 0xFFFF
        checks["kit: Waverider voices keep a cleared bit (u1)"] = u1 == 0
        if a.control:
            checks["control: a kit change leaves the bits as they were"] = u2 == u1
        else:
            checks["a kit change marks every voice unplayed"] = u2 == 0xFFFF
            checks["no kit change: the bits stay as cleared"] = u3 == u1
    return checks


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("build")
    ap.add_argument("--layout", default=str(ROOT / "src/dnfw/mods/waverider_code.json"))
    ap.add_argument("--out", default=str(ROOT / "out/wr-stale"))
    ap.add_argument("--ssi-panel", default=str(SSI_PANEL), help="a panel_drive with --ssi-hz")
    ap.add_argument("--ssi-cwd", default=str(SSI_CWD), help="its digikit checkout (it reads the device files there)")
    ap.add_argument("--control", action="store_true", help="a build from before the fix")
    a = ap.parse_args(argv)
    a.build = pathlib.Path(a.build).resolve()
    out = pathlib.Path(a.out).resolve()
    events = json.loads(pathlib.Path(a.layout).read_text())["layout"]["wr_events"]
    checks = kit_case(a, events, out)
    for k, v in checks.items():
        print("ok  " if v else "FAIL", k)
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())

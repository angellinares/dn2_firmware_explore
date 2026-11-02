"""A new Waverider track's page 1 shows a voice's modulation only once that voice has played as a Waverider.

    python scripts/emu_waverider_unplayed.py BUILD.syx --layout CODE.json [--out DIR] [--control]

The owner's report (2026-11-02): POS moved on page 1 of a track just made a Waverider, until a track
key. The voices of the track (and idle voices, which read as track 1's) still hold what they last
played, LFOs included, and the frame marks them Waverider at once. events.c now keeps a bit per voice,
`wr_events.unplayed`, set while the voice is another machine and cleared by its first note-on as a
Waverider; page.c skips a voice whose bit is set.

The emulator runs no audio frame hook, so the voice's state is written by hand, as
emu_waverider_captures.py writes it (voice 0 on track 1, machine 5, POS1's heard value swung about the
knob), and so is the bit. One panel_drive run from reset, track 1 made a Waverider in MACHINE SEL, then
three frames of page 1:
1. `knobs`: no voice of the track is a Waverider (voice 0's machine 0);
2. `unplayed`: voice 0 a Waverider with modulation on POS1, its `unplayed` bit as boot leaves it (set);
3. `played`: the same with the bit cleared, as one note-on clears it.

Pass: `unplayed` draws as `knobs` (the knobs alone) and `played` differs from `knobs` (the
modulation shows, the positive control). With --control (a build from before the fix, whose struct
has no `unplayed`): `unplayed` differs from `knobs`, the report's state.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import emu_waverider_captures as C  # noqa: E402

UNPLAYED_AT = 26                         # struct wr_events (events.h): magic, clears, notes[16], shown_osc, scope_track


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("build")
    ap.add_argument("--layout", default=str(ROOT / "src/dnfw/mods/waverider_code.json"))
    ap.add_argument("--out", default=str(ROOT / "out/wr-unplayed"))
    ap.add_argument("--panel-drive", default=str(C.PANEL))
    ap.add_argument("--control", action="store_true", help="a build from before the fix")
    a = ap.parse_args(argv)
    out = pathlib.Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    events = json.loads(pathlib.Path(a.layout).read_text())["layout"]["wr_events"]
    knob = 40 << 8

    s = ["tap:12", "wait:30M", "press:17", "wait:20M", "tap:2", "wait:40M", "release:17", "wait:60M"]
    s += [x for _ in range(4) for x in ("tap:14", "wait:40M")] + ["tap:10", "wait:200M", "tap:2", "wait:60M"]
    s += [C.put(C.POS1, knob), f"poke:{C.MACHINE:#x}:0000"]
    s += C.redraw() + ["frame:knobs"]
    s += C.modulation(C.POS1, knob, 0x1800) + C.redraw() + ["frame:unplayed"]
    if not a.control:
        s += [f"poke:{events + UNPLAYED_AT:#x}:fffe"]          # voice 0 has played as a Waverider
    s += C.modulation(C.POS1, knob, 0x1800) + C.redraw() + ["frame:played"]
    (out / "steps.txt").write_text("\n".join(s) + "\n")
    r = subprocess.run([a.panel_drive, a.build, "--out", str(out), "--watch", "0x4011ea6a",
                        "--steps", f"@{out / 'steps.txt'}"], capture_output=True, text=True, timeout=3600)
    lines = r.stdout.strip().splitlines()
    if not lines:
        raise SystemExit(f"panel_drive said nothing (rc {r.returncode}): {r.stderr[-2000:]}")
    report = json.loads(lines[-1])
    from PIL import Image, ImageOps
    frames = {}
    for n in ("knobs", "unplayed", "played"):
        p = out / f"{n}.pbm"
        if p.exists():
            frames[n] = p.read_bytes()
            ImageOps.invert(Image.open(p).convert("L")).resize((512, 256), Image.NEAREST).save(out / f"{n}.png")
    checks = {
        "no fault (the reporter at 0x4011ea6a never ran)": all(w["hits"] == 0 for w in report.get("watched", [])),
        "all three frames written": len(frames) == 3,
    }
    if len(frames) == 3:
        if a.control:
            checks["control: the unplayed voice's modulation shows (the report's state)"] = frames["unplayed"] != frames["knobs"]
        else:
            checks["an unplayed voice: page 1 shows the knobs alone"] = frames["unplayed"] == frames["knobs"]
            checks["the same voice once played: its modulation shows (the positive control)"] = frames["played"] != frames["knobs"]
    print("outcome", report.get("outcome"), "frames:", " ".join(str(out / f"{n}.png") for n in frames))
    for k, v in checks.items():
        print("ok  " if v else "FAIL", k)
    return 0 if all(checks.values()) and report.get("outcome") == "done" else 1


if __name__ == "__main__":
    raise SystemExit(main())

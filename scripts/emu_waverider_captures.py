"""Screen captures of Waverider's five pages and of its modulation markers, for the manual.

    python scripts/emu_waverider_captures.py BUILD.syx [--out out/wrcaps]

One panel_drive run from reset (digikit-wt-forced's panel driver). Track 1 is made a Waverider
track in MACHINE SEL, then each setting is written into the sound in RAM (the kit pointer
0x800052a0 read 0x4210c08c on this boot; slot s at sound + 20 + 2s, big-endian, the record's
scale, as wtedit.c's TBL load writes it) and the pages are stepped round once so the page
redraws. A turn of the encoder is too coarse here: small turns are swallowed and a burst
accelerates past the range.

The emulator runs no audio tick, so two things are written in by hand, and the captions say so:
- **Modulation:** the page draws a voice's heard value against its target (page.c, `mod_offset`:
  `0x800068e4` and `0x80003af0`, slot s of voice v at +34 + 202v + 2s). Voice 0 is given track 1
  and machine 5, the target set to the knob, and the heard value swung either side a few times so
  the page learns the range. The speed tier comes from LFO1's settings in the target row
  (SPD, MULT, DEST, DEP): slow (under 3 Hz), medium (3 to 12 Hz) and fast (over 12 Hz).
- **The scope** (pages 4 and 5): its ring is filled with 2,048 samples of the DSP code's own
  output, a held C4 rendered in digikit's SHARC runner (`out/runner_long/keep/long_hold_native_amp_out.wav`).

Writes OUT/<name>.pbm and OUT/<name>.png (inverted, white on black as the OLED shows them, 2:1).
"""

from __future__ import annotations

import argparse
import json
import pathlib
import struct
import subprocess


import numpy as np

import sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))
from dnfw.waverider import dsp, live  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
PANEL = ROOT.parent / "digikit-wt-forced/out/target/release/examples/panel_drive.exe"
SOUND = 0x4210C0C0                   # track 1's sound: kit 0x4210c08c + 52
TARGETS, VALUES = 0x80003AF0, 0x800068E4
OWNER, MACHINE = 0x80005308, 0x80005E60 + 148
RING = 0x467F7C8C                    # wr_events.scope -> wr_scope_ring (the drive chunk's .data)
RUNNER_WAV = ROOT / "out/runner_long/keep/long_hold_native_amp_out.wav"
POS1, TBL1, POS2, TBL2 = 26, 27, 32, 33
SUB_LEV, SUB_WAVE, NOIS_LEV, NOIS_COL, NOIS_DEC = 50, 52, 54, 56, 57
FOLD, WARP, FM, NPOS, AMT = 58, 59, 60, 61, 48
SHAPE_TYPE, LEV2 = 62, 36


def put(slot, value):
    return f"poke:{SOUND + 20 + 2 * slot:#x}:{value & 0xFFFF:04x}"


def row(base, slot, value):
    return f"poke:{base + 34 + 2 * slot:#x}:{value & 0xFFFF:04x}"


def redraw(page_taps=5):
    """step the SYN pages round once: the page redraws with the values written"""
    return [s for _ in range(page_taps) for s in ("tap:2", "wait:40M")] + ["wait:160M"]


def to_page(n):
    """from page 1 to page n"""
    return [s for _ in range(n - 1) for s in ("tap:2", "wait:60M")] + ["wait:160M"]


def shaped_ring(shape, osc2_lev=0) -> bytes:
    """The scope's 2,048 samples for a page 5 SHAPE (FOLD, NPOS, TYPE, AMT): the model's held C4
    (dnfw.waverider.live, which page5.asm matches bit for bit), osc 1 Prim. at POS 40, osc 2 Harm.
    at POS 30 and level OSC2_LEV, scaled as ring_samples scales the runner's."""
    seq = [(60.0, (40 << 8, 0, 0x4000, 0x6400), (30 << 8, 0x100, 0x4000, osc2_lev))] * 72
    x = np.array(live.render_two(dsp.tables(), seq, shapes=[shape] * 72)[-2048:])
    x = x / max(1e-9, np.abs(x).max()) * 0.8
    return (np.round(x * 32767).astype(">i2")).tobytes()


def ring_samples() -> bytes:
    raw = RUNNER_WAV.read_bytes()                  # mono 32-bit float (dnfw.wav), which `wave` refuses
    at = 12
    while raw[at:at + 4] != b"data":
        at += 8 + struct.unpack_from("<I", raw, at + 4)[0]
    n = struct.unpack_from("<I", raw, at + 4)[0]
    x = np.frombuffer(raw[at + 8:at + 8 + n], dtype="<f4").astype(np.float64)
    x = x[len(x) // 2:len(x) // 2 + 2048]
    x = x / max(1e-9, np.abs(x).max()) * 0.8
    return (np.round(x * 32767).astype(">i2")).tobytes()


def modulation(slot, knob, swing, lfo=None, final=None):
    """voice 0 on track 1 as a Waverider voice, target = knob, the heard value swung +-swing"""
    s = [f"poke:{OWNER:#x}:00000000", f"poke:{MACHINE:#x}:0005", row(TARGETS, slot, knob)]
    for k in range(1, 9):                                  # LFO1's eight settings: none
        s.append(row(TARGETS, k, 0x4000 if k in (1, 8) else 0))
    if lfo:
        spd, mult = lfo
        s += [row(TARGETS, 1, 0x4000 + spd), row(TARGETS, 2, mult << 8), row(TARGETS, 4, slot << 8),
              row(TARGETS, 8, 0x4000 + 0x1800)]
    for _ in range(3):
        s += [row(VALUES, slot, knob + swing), "wait:60M", row(VALUES, slot, knob - swing), "wait:60M"]
    s += [row(VALUES, slot, knob + swing // 2 if final is None else final), "wait:120M"]
    return s


def clear_modulation(slot, knob):
    return [row(TARGETS, slot, knob), row(VALUES, slot, knob), f"poke:{MACHINE:#x}:0000", "wait:300M"]


def main() -> int:
    global RUNNER_WAV
    ap = argparse.ArgumentParser()
    ap.add_argument("build")
    ap.add_argument("--out", default=str(ROOT / "out/wrcaps"))
    ap.add_argument("--panel-drive", default=str(PANEL))
    ap.add_argument("--runner-wav", default=str(RUNNER_WAV))
    a = ap.parse_args()
    RUNNER_WAV = pathlib.Path(a.runner_wav)
    out = pathlib.Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    names = []

    def frame(n):
        names.append(n)
        return [f"frame:{n}"]

    s = ["tap:12", "wait:30M", "press:17", "wait:20M", "tap:2", "wait:40M", "release:17", "wait:60M"]
    s += [x for _ in range(4) for x in ("tap:14", "wait:40M")] + ["tap:10", "wait:200M", "tap:2", "wait:60M"]
    # the sound: osc 1 Prim. at POS 40, osc 2 Harm. at POS 30; sub and noise up; Shape's knobs set
    s += [put(POS1, 40 << 8), put(TBL1, 0x0000), put(POS2, 30 << 8), put(TBL2, 0x0100),
          put(SUB_LEV, 100 << 8), put(SUB_WAVE, 1 << 8), put(NOIS_LEV, 60 << 8), put(NOIS_COL, 0x5000),
          put(NOIS_DEC, 70 << 8), put(FOLD, 0x5800), put(WARP, 0x3000), put(FM, 0x2000), put(NPOS, 0x4800),
          put(AMT, 0x6000)]
    ring = ring_samples()
    s += [f"poke:{RING:#x}:{2048:08x}{ring.hex()}"]
    s += redraw() + frame("page1")
    for n in (2, 3, 4, 5):
        s += ["tap:2", "wait:60M"]
        if n == 4:
            s += [f"poke:{RING:#x}:{2048:08x}{ring.hex()}", "wait:120M"]
        if n == 5:                                             # page 5 plays: the scope shows its settings
            p5 = shaped_ring((0x5800, 0x4800, 0, 0x6000))
            s += [f"poke:{RING:#x}:{2048:08x}{p5.hex()}", "wait:120M"]
        s += frame(f"page{n}")
        if n == 5:   # TYPE turned from Off to AM with knob E (push held; 40 counts are two steps), osc 2
            # on, FOLD and NPOS off: the header names the value, the scope shows the model's AM at AMT 100
            s += [put(LEV2, 100 << 8), put(FOLD, 0), put(NPOS, 0), put(SHAPE_TYPE, 0), put(AMT, 100 << 8),
                  f"poke:{RING:#x}:{2048:08x}{shaped_ring((0, 0, 0x0200, 100 << 8), 0x6400).hex()}", "wait:60M"]
            # a turn without the push first (it changes nothing), then the push held and two steps; the
            # frame is taken while the push is held, before the header slides back to the project name
            s += ["turn:5:40", "wait:20M", "press:45", "wait:20M", "turn:5:40", "wait:30M", f"frame:page5_am",
                  "release:45", "wait:30M"]
            names.append("page5_am")
            s += [put(LEV2, 0), put(SHAPE_TYPE, 0), put(AMT, 0x6000)]
    s += ["tap:2", "wait:160M"]                                    # back on page 1
    # modulation on osc 1's POS: none (the control), slow, medium, fast
    # POS at 60 swept +-50 (frames 10 to 110, a saw to a sine), so the two frames drawn at
    # the medium and fast speeds are plainly different (owner, 2026-10-14)
    knob, swing = 60 << 8, 50 << 8
    s += [put(POS1, knob)] + redraw() + frame("mod_none")
    s += modulation(POS1, knob, swing) + frame("mod_slow") + clear_modulation(POS1, knob)
    s += modulation(POS1, knob, swing, lfo=(0x3000, 5)) + frame("mod_medium") + clear_modulation(POS1, knob)
    s += modulation(POS1, knob, swing, lfo=(0x3000, 7)) + frame("mod_fast") + clear_modulation(POS1, knob)
    # on TBL: two tables either side of Prim.
    s += modulation(TBL1, 0x0000, 0x0100, final=0x0100) + frame("mod_tbl") + clear_modulation(TBL1, 0x0000)
    s += redraw() + frame("mod_after")

    steps = out / "steps.txt"
    steps.write_text("\n".join(s) + "\n")
    r = subprocess.run([a.panel_drive, a.build, "--out", str(out), "--watch", "0x4011ea6a",
                        "--steps", f"@{steps}"], capture_output=True, text=True, timeout=3600)
    report = json.loads(r.stdout.strip().splitlines()[-1])
    (out / "report.json").write_text(json.dumps({k: v for k, v in report.items() if k != "captures"}, indent=1))
    from PIL import Image, ImageOps
    for n in names:
        p = out / f"{n}.pbm"
        if p.exists():
            ImageOps.invert(Image.open(p).convert("L")).resize((256, 128), Image.NEAREST).save(out / f"{n}.png")
    print(report["outcome"], "fault reporter:", report.get("watched"), "frames:", ", ".join(names))
    return 0 if report["outcome"] == "done" else 1


if __name__ == "__main__":
    raise SystemExit(main())

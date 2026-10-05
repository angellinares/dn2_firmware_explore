"""Render what MOVE's SYNC (M10b-2) should sound like, from the reference model.

    python scripts/waverider_sync_preview.py [--out out/waverider]

`dnfw.waverider.live.render_two` (bit-exact to the DSP in the runner gate) fed the
song position `songpos` computes from a pattern playing at 120 BPM, frame by frame,
as the ColdFire's sync.c does. Half a second stopped, then PLAY. A click track is
mixed in afterwards (a click on each beat, a louder one on step 1) so the lock can be
heard; it is not part of the instrument's sound. Writes, 48 kHz mono 16-bit:

- `m10b2_sync_gate.wav`: SYN1 On, TRIG Free, MOVE Square on MLEV 127, RATE 1/8: the
  level gates on every eighth, the first gate opening on step 1.
- `m10b2_sync_ramp.wav`: SYN1 On, TRIG Free, MOVE Up Loop on POS (MPOS 100), RATE
  1 bar: POS sweeps once a bar and starts again on step 1.
- `m10b2_sync_retrig.wav`: SYN1 On, TRIG Retrig, the same ramp at 1/4, with a note on
  steps 1 and 7: the ramp starts at each note and lasts a quarter at the tempo.
"""

from __future__ import annotations

import argparse
import array
import math
import pathlib
import sys
import wave

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from dnfw.waverider import dsp, live, songpos  # noqa: E402

BPM, TEMPO = 120.0, 14400
SECONDS, STOPPED = 6.0, 0.5
NOTE = 48.0


def rate_for(name: str) -> int:
    """the lowest RATE (<< 8) whose note length is NAME"""
    idx = next(i for i, n in enumerate(live.SYNC_NOTES) if n[0] == name)
    return live.SYNC_INDEX.index(idx) << 8


def blocks(osc1: dict, trig: int, notes_at_steps=(0,)) -> list:
    n = int(SECONDS * 1500)
    start = int(STOPPED * 1500)
    sp = songpos.SongPos()
    per = 1500 * 60 / (4 * BPM)
    out = []
    for f, (now, nxt) in enumerate(songpos.playing(n, BPM, 16, start)):
        p = sp.frame(now, nxt, TEMPO)
        step_f = (f - start) / per if f >= start else -1
        hit = f >= start and int(step_f) % 16 in notes_at_steps and (f - start) % per < 1
        o1 = (osc1["wav"], 0, live.TUN1_ZERO, 0x6400, osc1["rate"], osc1["mpos"], osc1["mlev"],
              osc1["move"], 0x100)
        o2 = (0, 0, live.TUN1_ZERO, 0)
        out.append((NOTE, o1, o2, (trig, hit, live.PRST_ON, p, TEMPO)))
    return out


def clicks(samples: list[float]) -> list[float]:
    """a click on each beat, louder on step 1, from PLAY on"""
    out = list(samples)
    start = int(STOPPED * 48000)
    beat = int(48000 * 60 / BPM)
    for k, at in enumerate(range(start, len(out), beat)):
        amp = 0.6 if k % 4 == 0 else 0.25
        for i in range(240):
            if at + i < len(out):
                out[at + i] += amp * math.sin(2 * math.pi * 2000 * i / 48000) * (1 - i / 240)
    return out


def write(path: pathlib.Path, samples: list[float]) -> None:
    peak = max(1e-9, max(abs(x) for x in samples))
    g = 0.9 / peak
    pcm = array.array("h", (int(max(-1, min(1, x * g)) * 32767) for x in samples))
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(48000)
        w.writeframes(pcm.tobytes())
    print(f"wrote {path} ({len(samples) / 48000:.1f} s)")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", type=pathlib.Path, default=ROOT / "out" / "waverider")
    a = ap.parse_args(argv)
    a.out.mkdir(parents=True, exist_ok=True)
    tables = dsp.tables()
    gate = {"wav": 0x3c00, "rate": rate_for("1/8"), "mpos": live.MPOS_NONE, "mlev": 0x7F00, "move": 0x0800}
    ramp = {"wav": 0, "rate": rate_for("1 bar"), "mpos": 0x6400, "mlev": 0, "move": 0x0500}
    quarter = {**ramp, "rate": rate_for("1/4")}
    for name, osc, trig, notes in (("gate", gate, 0x100, (0,)), ("ramp", ramp, 0x100, (0,)),
                                   ("retrig", quarter, 0x000, (0, 6))):
        y = live.render_two(tables, blocks(osc, trig, notes), 32)
        start = int(STOPPED * 48000)
        y = [0.0] * start + y[start:]             # silent while stopped, as the amp would be
        write(a.out / f"m10b2_sync_{name}.wav", clicks(y))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

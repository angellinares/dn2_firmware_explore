"""Sweep the instrument's whole SDRAM for a value that steps with the sequencer, over the
USB probe, in two phases (read-only: PEEK only; quit Transfer first).

    python tools/dn2memsweep.py changed --out out/probe-frames/sweep.pkl
    python tools/dn2memsweep.py focus --out out/probe-frames/sweep.pkl --passes 12 --bpm 120 --steps 8

1. `changed`: two passes over 0x40000400..0x48000000 in 1 KB chunks; keeps the chunks
   that differ between them (about 7 minutes a pass at the probe's ~310 KB/s).
2. `focus`: repeated, timed passes over only those chunks, the note-on counter beside
   them; then the step-rate test of `dn2stepscan` (a value that advances at the
   pattern's step rate in any of its tick multiples and wraps at the pattern's length).
"""

from __future__ import annotations

import argparse
import pathlib
import pickle
import struct
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import dn2probe as P          # noqa: E402
import winmidi                # noqa: E402

LO, HI, CHUNK = 0x40000400, 0x48000000, 1024


def read(pr, a, n):
    return P.decode_peek(pr.call(P.req_peek, a, n))["data"]


def changed(pr, out):
    first = {}
    t = time.perf_counter()
    for a in range(LO, HI, CHUNK):
        first[a] = read(pr, a, min(CHUNK, HI - a))
    print(f"pass 1: {time.perf_counter() - t:.0f} s", flush=True)
    moving = []
    t = time.perf_counter()
    for a in range(LO, HI, CHUNK):
        if read(pr, a, min(CHUNK, HI - a)) != first[a]:
            moving.append(a)
    print(f"pass 2: {time.perf_counter() - t:.0f} s; {len(moving)} chunks changed "
          f"({len(moving) * CHUNK / 1e6:.1f} MB)", flush=True)
    pickle.dump({"moving": moving}, open(out, "wb"))


def focus(pr, out, passes, bpm, steps, notes_at):
    saved = pickle.load(open(out, "rb"))
    moving = saved["moving"]
    runs = []
    for k in range(passes):
        data, stamps = [], []
        t = time.perf_counter()
        for a in moving:
            t1 = time.perf_counter()
            data.append(read(pr, a, CHUNK))
            stamps.append((t1 + time.perf_counter()) / 2)
        notes = sum(read(pr, notes_at, 16)) if notes_at else None
        runs.append((data, stamps, notes))
        print(f"focus pass {k}: {time.perf_counter() - t:.1f} s", flush=True)
    saved["runs"] = runs
    pickle.dump(saved, open(out, "wb"))
    analyse(saved, bpm, steps)


def analyse(saved, bpm, steps):
    moving, runs = saved["moving"], saved["runs"]
    rate_steps = bpm / 60 * 4
    t0 = runs[0][1][0]
    found = []
    for ci, a in enumerate(moving):
        ts = [r[1][ci] - t0 for r in runs]
        for width, fmt in ((1, "B"), (2, ">H"), (4, ">I")):
            for off in range(0, CHUNK - width + 1, width):
                v = [struct.unpack_from(fmt, r[0][ci], off)[0] for r in runs]
                if len(set(v)) < 4:
                    continue
                for per in (1, 2, 3, 4, 6, 8, 12, 24, 48, 96):
                    r = rate_steps * per
                    for mod in [steps * per * k for k in (1, 2, 4, 8)] + [1 << (8 * width)]:
                        if max(v) >= mod:
                            continue
                        a0 = v[0] - r * ts[0]
                        if all(min(abs(vi - (a0 + r * ti) % mod), mod - abs(vi - (a0 + r * ti) % mod))
                               <= max(1.0, 0.6 * per) for vi, ti in zip(v, ts)):
                            found.append((a + off, width, per, mod, v))
                        break
    for addr, width, per, mod, v in found[:80]:
        print(f"{addr:#010x} u{8 * width:<2} {per} per step, wraps at {mod}: {v}")
    print(f"{len(found)} candidates")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("phase", choices=("changed", "focus", "analyse"))
    ap.add_argument("--out", type=pathlib.Path, default=pathlib.Path("out/probe-frames/sweep.pkl"))
    ap.add_argument("--passes", type=int, default=12)
    ap.add_argument("--bpm", type=float, default=120.0)
    ap.add_argument("--steps", type=int, default=8, help="the pattern's length")
    ap.add_argument("--notes", type=lambda s: int(s, 0), default=0, help="a note-on counter to read beside")
    ap.add_argument("--port", default="Digitone II")
    a = ap.parse_args(argv)
    if a.phase == "analyse":
        analyse(pickle.load(open(a.out, "rb")), a.bpm, a.steps)
        return 0
    a.out.parent.mkdir(parents=True, exist_ok=True)
    port = winmidi.Port(a.port, None, None)
    try:
        pr = P.Probe(port)
        if a.phase == "changed":
            changed(pr, a.out)
        else:
            focus(pr, a.out, a.passes, a.bpm, a.steps, a.notes)
    finally:
        port.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

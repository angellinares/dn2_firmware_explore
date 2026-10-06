"""Find the sequencer's step position on the instrument, over the USB probe: read a RAM
range in 1 KB chunks, each timed, several passes, while a pattern plays at a known tempo;
then keep the bytes and words that follow `start + rate x t`, wrapping, at the time
their own chunk was read.

    python tools/dn2stepscan.py --lo 0x4030b980 --hi 0x40600000 --passes 5 --bpm 120

The per-chunk times are what make a slow pass usable: a step at 120 BPM lasts 125 ms,
and a pass over 3 MB takes ~10 s, but each 1 KB chunk is read within a few
milliseconds of its own timestamp. The rates tried are 1, 2, 3, 4, 6, 8, 12, 24, 48 and 96 counts
per sixteenth; the wraps are 16 to 256 steps' worth, and the type's own wrap.

Read-only: PEEK only. Quit Transfer first. Saves the raw passes for re-analysis.
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

CHUNK = 1024


def scan(pr, lo, hi):
    data, stamps = bytearray(), []
    for a in range(lo, hi, CHUNK):
        n = min(CHUNK, hi - a)
        t = time.perf_counter()
        data += P.decode_peek(pr.call(P.req_peek, a, n))["data"]
        stamps.append((t + time.perf_counter()) / 2)
    return bytes(data), stamps


def analyse(passes, lo, bpm, tol_steps=0.6):
    steps_per_s = bpm / 60 * 4
    t0 = passes[0][1][0]
    out = []
    size = len(passes[0][0])
    for width, fmt in ((1, "B"), (2, ">H"), (4, ">I")):
        for off in range(0, size - width + 1, width):
            v = [struct.unpack_from(fmt, d, off)[0] for d, _ in passes]
            if len(set(v)) < 3:
                continue
            ts = [s[off // CHUNK] - t0 for _, s in passes]
            for per in (1, 2, 3, 4, 6, 8, 12, 24, 48, 96):
                r = steps_per_s * per
                for mod in [8 * per * k for k in (1, 2, 4, 8, 16, 32)] + [1 << (8 * width)]:
                    if max(v) >= mod:
                        continue
                    tol = max(1.0, tol_steps * per)
                    a0 = v[0] - r * ts[0]
                    bad = 0
                    for vi, ti in zip(v, ts):
                        pred = (a0 + r * ti) % mod
                        d = abs(vi - pred)
                        bad += min(d, mod - d) > tol
                    if bad == 0:
                        out.append((width, per, mod, lo + off, v))
                    break
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--lo", type=lambda s: int(s, 0), default=0x4030B980)
    ap.add_argument("--hi", type=lambda s: int(s, 0), default=0x40600000)
    ap.add_argument("--passes", type=int, default=5)
    ap.add_argument("--bpm", type=float, default=120.0)
    ap.add_argument("--port", default="Digitone II")
    ap.add_argument("--out", type=pathlib.Path, default=pathlib.Path("out/probe-frames/stepscan_big.pkl"))
    ap.add_argument("--reanalyse", action="store_true", help="analyse --out without the instrument")
    a = ap.parse_args(argv)
    if a.reanalyse:
        saved = pickle.load(open(a.out, "rb"))
        passes, lo = saved["passes"], saved["lo"]
    else:
        port = winmidi.Port(a.port, None, None)
        try:
            pr = P.Probe(port)
            passes = []
            for k in range(a.passes):
                t = time.perf_counter()
                passes.append(scan(pr, a.lo, a.hi))
                print(f"pass {k}: {len(passes[-1][0]):,} B in {time.perf_counter() - t:.1f} s", flush=True)
        finally:
            port.close()
        lo = a.lo
        a.out.parent.mkdir(parents=True, exist_ok=True)
        pickle.dump({"passes": passes, "lo": lo, "bpm": a.bpm}, open(a.out, "wb"))
    found = analyse(passes, lo, a.bpm)
    for width, per, mod, addr, v in found[:60]:
        print(f"{addr:#010x} u{8 * width:<2} {per} per step, wraps at {mod}: {v}")
    print(f"{len(found)} candidates")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

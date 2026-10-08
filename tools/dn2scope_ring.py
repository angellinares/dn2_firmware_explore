"""Page 4's scope ring, read over the USB probe: is the captured stream continuous?

    python tools/dn2scope_ring.py LABEL [--ring 0x467f74ec] [--n 3] [--dir out/scope-ring]

The ISR pushes the shown track's 32 samples a frame into wr_scope_ring (csrc/ui/trace_ring.h:
u32 write count, then 2,048 int16). This reads it N times (read-only PEEK), saves each, and
compares the sample-to-sample steps that cross a 32-sample block boundary with the steps
inside blocks. A continuous capture has boundary steps like the inside ones; a block taken
twice, skipped, or from the half still being filled shows as boundary steps far larger, and
as blocks equal to an earlier one.

**The read itself can tear.** A 4 KB read is several PEEKs (PEEK_MAX 1,024), about
4 ms each, and the ISR writes ~6 blocks per round trip into the oldest positions
while they are read, so the snapshot's oldest blocks are the newest audio: one
seam, at a block boundary, about 6 blocks per round trip in (2026-10-08: the
boundary-step excess first read as the DSP's, clustered at blocks 6, 12, 18 on
every track and patch). So the write count is read again after the data, and the
blocks written meanwhile, plus one, are left out of the analysis. `big_boundary`
and `big_inside` count steps over twice the snapshot's inside p99 at and away
from block starts: a continuous capture has them in the 1:31 ratio of the steps.

Read-only: PEEK only. Quit Transfer first (memory probe-after-flash).
"""
from __future__ import annotations

import argparse
import os
import pathlib
import sys
import time

sys.path.insert(0, os.path.dirname(__file__))

import dn2probe as dp                                          # noqa: E402
from dn2probe_frame import read                                # noqa: E402

RING = 2048


def analyse(blob: bytes, w_after: int | None = None) -> dict:
    """BLOB (the write count, then the ring) -> continuity figures. W_AFTER, the write
    count read after the ring, drops the blocks the ISR overwrote during the read."""
    w = int.from_bytes(blob[:4], "big")
    s = [int.from_bytes(blob[4 + 2 * i: 6 + 2 * i], "big", signed=True) for i in range(RING)]
    order = [s[(w + i) % RING] for i in range(RING)]            # oldest first
    torn = 0 if w_after is None else min(RING, ((w_after - w) & 0xFFFFFFFF) + 32)
    inside, boundary = [], []
    for i in range(torn + 1, RING):
        (boundary if (w + i) % 32 == 0 else inside).append(abs(order[i] - order[i - 1]))
    if not inside or not boundary:
        return {"w": w, "torn": torn, "peak": max(map(abs, s)), "usable": 0}
    blocks = [tuple(order[k:k + 32]) for k in range(torn, RING - 31, 32)]
    repeats = sum(1 for k in range(1, len(blocks)) if blocks[k] in blocks[max(0, k - 4):k])
    mean = lambda v: sum(v) / len(v) if v else 0.0
    p99 = sorted(inside)[int(0.99 * len(inside))]
    return {"w": w, "torn": torn, "peak": max(map(abs, s)), "step_inside": mean(inside),
            "step_boundary": mean(boundary), "worst_boundary": max(boundary), "worst_inside": max(inside),
            "big_boundary": sum(1 for d in boundary if d > 2 * p99),
            "big_inside": sum(1 for d in inside if d > 2 * p99), "repeated_blocks": repeats}


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("label")
    p.add_argument("--ring", type=lambda v: int(v, 0), default=0x467F751C)   # scope2; scope1 had it at 0x467F74EC
    p.add_argument("--n", type=int, default=3)
    p.add_argument("--dir", type=pathlib.Path, default=pathlib.Path("out/scope-ring"))
    p.add_argument("--port", default="Digitone II")
    a = p.parse_args(argv)
    import winmidi
    a.dir.mkdir(parents=True, exist_ok=True)
    port = winmidi.Port(a.port, None, None)
    try:
        pr = dp.Probe(port)
        for k in range(a.n):
            blob = read(pr, a.ring, 4 + 2 * RING)
            w_after = int.from_bytes(read(pr, a.ring, 4), "big")
            (a.dir / f"{a.label}.{k:02d}.bin").write_bytes(blob + w_after.to_bytes(4, "big"))
            r = analyse(blob, w_after)
            print(f"{a.label}.{k}: " + "  ".join(f"{n} {v:.0f}" if isinstance(v, float) else f"{n} {v}" for n, v in r.items()))
            time.sleep(0.2)
    finally:
        port.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Which words of the SHARC's reply never change, on the instrument, over the USB probe.

    python tools/dn2replyscan.py [--samples 40] [--out out/probe-frames/replyscan.json]

The reply the ColdFire receives each frame is 2,748 bytes at 0x800053a4 (the stock
send's receive buffer). This reads it SAMPLES times and reports each 32-bit word's
distinct values: a word that reads 0 in every sample, idle and while playing, is a
candidate for a value of our own the DSP writes and the ColdFire does not use. A
candidate is not proof: the ColdFire's reads must be checked statically too.

Read-only: PEEK only. Quit Transfer first (memory probe-after-flash).
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import dn2probe as P          # noqa: E402
import winmidi                # noqa: E402

REPLY, LENGTH = 0x800053A4, 2748


def read(pr, addr, length):
    out = b""
    while len(out) < length:
        n = min(P.PEEK_MAX, length - len(out))
        r = P.decode_peek(pr.call(P.req_peek, addr + len(out), n))
        out += r["data"]
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--samples", type=int, default=40)
    ap.add_argument("--gap", type=float, default=0.25, help="seconds between samples")
    ap.add_argument("--port", default="Digitone II")
    ap.add_argument("--out", type=pathlib.Path, default=pathlib.Path("out/probe-frames/replyscan.json"))
    a = ap.parse_args(argv)
    port = winmidi.Port(a.port, None, None)
    pr = P.Probe(port)
    seen: dict[int, set[int]] = {}
    for _ in range(a.samples):
        data = read(pr, REPLY, LENGTH)
        for off in range(0, LENGTH - 3, 4):
            seen.setdefault(off, set()).add(int.from_bytes(data[off:off + 4], "big"))
        time.sleep(a.gap)
    zero = [off for off, v in seen.items() if v == {0}]
    const = {off: next(iter(v)) for off, v in seen.items() if len(v) == 1 and v != {0}}
    runs, start = [], None
    for off in range(0, LENGTH - 3, 4):
        if off in zero and start is None:
            start = off
        if off not in zero and start is not None:
            runs.append((start, off))
            start = None
    if start is not None:
        runs.append((start, LENGTH - LENGTH % 4))
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps({"samples": a.samples, "zero_words": zero,
                                 "constant_nonzero": {hex(k): hex(v) for k, v in const.items()},
                                 "zero_runs": [[hex(s), hex(e)] for s, e in runs]}, indent=1) + "\n")
    print(f"{len(zero)} words always 0, {len(const)} constant non-zero, of {len(seen)}")
    print("zero runs (offset from the reply's start):",
          ", ".join(f"{s:#x}..{e:#x}" for s, e in runs[:40]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Read the stage 3 FFT self-test from a selftest build (scripts/build_selftest.py), over the USB probe.

    python tools/dn2selftest.py BUILD.json [--for 10] [--watch 0] [--port "Digitone II"]

selftest.asm runs the whole level build for two frames in the DSP's idle task, over and
over, and publishes one entry at a time through reply word 2 (the ColdFire's 0x800053ac):
IDX << 27 | value. This reads that word for FOR seconds, keeps the latest value per index,
and prints:

- runs completed (PUB[0]) and runs whose hash differed from the first run's (PUB[1]);
- REF, the first run's hash, against BUILD.json's (the emulator's, written by the build):
  equal means the DSP computes what the emulator does;
- the cycles of the forward transform, the split, the levels and a whole run (EMUCLK).

`--watch N` repeats every N seconds until stopped. All zeros with no index seen means the
build has no self-test (or the word is not reply word 2).
"""
from __future__ import annotations

import argparse
import json
import pathlib
import struct
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))

from dnfw.waverider import selftest  # noqa: E402

REPLY = 0x800053A4
WORD2 = REPLY + 8


def collect(dp, pr, seconds: float) -> dict[int, int]:
    """IDX -> its latest value, from reply word 2 read for SECONDS."""
    seen: dict[int, int] = {}
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        data = dp.decode_peek(pr.call(dp.req_peek, WORD2, 4))["data"]
        word = struct.unpack(">I", data[:4])[0]
        if word:
            idx, val = selftest.decode(word)
            if idx < selftest.PUB_ENTRIES:
                seen[idx] = val
    return seen


def report(seen: dict[int, int], expected: dict) -> str:
    if not seen:
        return "  reply word 2 stayed 0: no self-test in this build, or it never published"
    lines = [f"  indices seen: {len(seen)} of {selftest.PUB_ENTRIES}"]
    if 0 in seen:
        lines.append(f"  runs: {seen[0]:,}")
    if 1 in seen:
        lines.append(f"  runs whose hash differed from the first: {seen[1]:,}")
    if 2 in seen and 3 in seen:
        ref = (seen[3] << 27) | seen[2]
        want = expected["ref"]
        verdict = "MATCHES the emulator" if ref == want else f"DIFFERS from the emulator's {want:#010x}"
        lines.append(f"  REF {ref:#010x}: {verdict}")
    if 4 in seen and 5 in seen:
        lines.append(f"  latest hash {(seen[5] << 27) | seen[4]:#010x}")
    for k in range(6, selftest.PUB_ENTRIES):
        if k in seen:
            lines.append(f"  {selftest.PUB_NAMES[k]}: {seen[k]:,} ({seen[k]:#x})")
    return "\n".join(lines)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0],
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("expected", type=pathlib.Path, help="the build's .json (the emulator's hash)")
    p.add_argument("--for", dest="duration", type=float, default=10.0)
    p.add_argument("--watch", type=float, default=0.0)
    p.add_argument("--port", default="Digitone II")
    a = p.parse_args(argv)
    expected = json.loads(a.expected.read_text(encoding="utf-8"))
    import dn2probe as dp
    import winmidi
    port = winmidi.Port(a.port, None, None)
    try:
        pr = dp.Probe(port)
        while True:
            seen = collect(dp, pr, a.duration)
            print(time.strftime("%H:%M:%S"))
            print(report(seen, expected))
            if not a.watch:
                return 0
            time.sleep(a.watch)
    finally:
        port.close()


if __name__ == "__main__":
    raise SystemExit(main())

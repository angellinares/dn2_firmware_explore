"""Read the cache coherence probe's result from a cohprobe build (scripts/build_cohprobe.py), over the USB probe.

    python tools/dn2cohprobe.py [--for 20] [--watch 0] [--port "Digitone II"]

cohprobe.asm writes a DDR word on one data bus and reads it on the other in the DSP's idle
task, in five cases, and publishes one entry at a time through reply word 2 (the
ColdFire's 0x800053ac): IDX << 27 | value. This reads that word for FOR seconds, keeps the
latest value per index, and prints:

- the probe's calls (PUB[0]) and the reads it checked (16 per case and call);
- per case, the bad reads (not the value just written) and how many of those were stale
  (the line's value before the write);
- the first bad read: its case, line, value and the value expected;
- SHL1C_CFG and SHL1C_CFG2 as the DSP reads them.

Cases A, B and C cross buses on DDR. D (same bus) and E (L1, no cache) are the controls.
0 bad reads in A, B and C with the controls at 0 means the caches agree, as the SHARC+
Programming Reference says. Bad reads in A, B or C with the controls at 0 means they do not.
Bad reads in D or E mean the probe itself is wrong. All zeros with no index seen means the
build has no probe (or the word is not reply word 2).
"""
from __future__ import annotations

import argparse
import pathlib
import struct
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))

from dnfw.waverider import cohprobe  # noqa: E402

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
            idx, val = cohprobe.decode(word)
            if idx < cohprobe.PUB_ENTRIES:
                seen[idx] = val
    return seen


def joined(seen: dict[int, int], lo: int) -> int | None:
    if lo in seen and lo + 1 in seen:
        return seen[lo] | seen[lo + 1] << 27
    return None


def report(seen: dict[int, int]) -> str:
    if not seen:
        return "  reply word 2 stayed 0: no probe in this build, or it never published"
    lines = [f"  indices seen: {len(seen)} of {cohprobe.PUB_ENTRIES}"]
    if 0 in seen:
        lines.append(f"  probe calls: {seen[0]:,} (reads checked per case: {cohprobe.LINES * seen[0]:,})")
    for k, (case, (what, _)) in enumerate(cohprobe.CASES.items()):
        bad, stale = seen.get(1 + k), seen.get(6 + k)
        lines.append(f"  {case} {what}: bad {'?' if bad is None else f'{bad:,}'}, "
                     f"stale {'?' if stale is None else f'{stale:,}'}")
    if 11 in seen:
        first = cohprobe.first_bad(seen[11])
        if first is None:
            lines.append("  first bad read: none")
        else:
            got, want = joined(seen, 12), joined(seen, 14)
            lines.append(f"  first bad read: case {first[0]}, line {first[1]}, read "
                         f"{'?' if got is None else f'{got:#010x}'}, expected {'?' if want is None else f'{want:#010x}'}")
    for name, lo in (("SHL1C_CFG", 16), ("SHL1C_CFG2", 18)):
        v = joined(seen, lo)
        lines.append(f"  {name}: {'? (read longer)' if v is None else f'{v:#010x}'}")
    missing = sorted(set(range(cohprobe.PUB_ENTRIES)) - set(seen))
    if missing:
        lines.append(f"  not seen yet (read longer): {missing}")
    return "\n".join(lines)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0],
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--for", dest="duration", type=float, default=20.0)
    p.add_argument("--watch", type=float, default=0.0)
    p.add_argument("--port", default="Digitone II")
    a = p.parse_args(argv)
    import dn2probe as dp
    import winmidi
    port = winmidi.Port(a.port, None, None)
    try:
        pr = dp.Probe(port)
        while True:
            seen = collect(dp, pr, a.duration)
            print(time.strftime("%H:%M:%S"))
            print(report(seen))
            if not a.watch:
                return 0
            time.sleep(a.watch)
    finally:
        port.close()


if __name__ == "__main__":
    raise SystemExit(main())

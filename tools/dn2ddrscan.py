"""Read the DDR scanner's result from a ddrscan build (scripts/build_ddrscan.py), over the USB probe.

    python tools/dn2ddrscan.py [--for 10] [--watch 0] [--port "Digitone II"]

ddrscan.asm reads the DSP's spare DDR (0x80531000..0xa0000000, filled with a pattern at
boot) back in the idle task and publishes, one entry at a time, through reply word 2 (the
ColdFire's 0x800053ac): IDX << 27 | value. This reads that word for FOR seconds, keeps the
latest value per index, and prints:

- passes over the span completed (PUB[0]);
- the words that differed from the pattern in the last pass (PUB[1]), the first and the
  last of them (PUB[2], PUB[3], as DDR addresses);
- every 2 MB granule that ever held one (PUB[4..19], sticky since boot).

`--watch N` repeats the read every N seconds until stopped, printing when passes or the
count change. All zeros with no index seen means the build has no scanner (or the word is
not reply word 2). The answer is the count once passes is 1 or more: 0 means nothing but
the boot kernel's fill wrote the span; a count close to the whole span (126,860,288 words)
means the fill did not take (the pattern never landed).
"""
from __future__ import annotations

import argparse
import pathlib
import struct
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))

from dnfw.waverider import ddrscan  # noqa: E402

REPLY = 0x800053A4
WORD2 = REPLY + 8
SPAN_WORDS = (ddrscan.SPAN[1] - ddrscan.SPAN[0]) // 4


def collect(dp, pr, seconds: float) -> dict[int, int]:
    """IDX -> its latest value, from reply word 2 read for SECONDS."""
    seen: dict[int, int] = {}
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        data = dp.decode_peek(pr.call(dp.req_peek, WORD2, 4))["data"]
        word = struct.unpack(">I", data[:4])[0]
        if word:
            idx, val = ddrscan.decode(word)
            if idx < ddrscan.PUB_ENTRIES:
                seen[idx] = val
    return seen


def report(seen: dict[int, int]) -> str:
    if not seen:
        return "  reply word 2 stayed 0: no scanner in this build, or it never published"
    addr = lambda v: ddrscan.DDR[0] + 4 * v
    lines = [f"  indices seen: {len(seen)} of {ddrscan.PUB_ENTRIES}"]
    if 0 in seen:
        lines.append(f"  passes completed: {seen[0]}")
    if 1 in seen:
        n = seen[1]
        lines.append(f"  words that differ from the pattern, last pass: {n:,} of {SPAN_WORDS:,}")
        if n and 2 in seen and 3 in seen:
            lines.append(f"  first {addr(seen[2]):#010x}, last {addr(seen[3]):#010x}")
    bitmap = [seen.get(4 + k) for k in range(16)]
    if all(w is not None for w in bitmap):
        g = ddrscan.granules(bitmap)
        lines.append("  2 MB granules ever written: " + (", ".join(
            f"{ddrscan.DDR[0] + k * ddrscan.GRANULE:#010x}" for k in g) if g else "none"))
    else:
        lines.append(f"  granule bitmap: {sum(w is not None for w in bitmap)} of 16 words seen (read longer)")
    return "\n".join(lines)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0],
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--for", dest="duration", type=float, default=10.0)
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

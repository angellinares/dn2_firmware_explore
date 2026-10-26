"""Read the stall probe's timings (scripts/build_stallprobe.py) over the USB probe.

    python tools/dn2stall.py [--for 120] [--port "Digitone II"] [--save out/stall_reading.json]
    python tools/dn2stall.py --load out/stall_reading.json

stall.asm runs its tests in the idle task (docs/sharc-stall-probe.md) and publishes each test's
least and most cycles, half a word at a time, through reply word 2 (the ColdFire's 0x800053ac):
TAG << 16 | HALF. This reads that word until every half is seen twice with the same value (or
FOR seconds pass), rebuilds the words and prints, per pair, the stall of one pair against its
control, and per reader, the cycles of one sample.

Quit Transfer first. All zeros with no tag means the build has no stall code. `--save` keeps
the words, so a reading can be printed again offline with `--load`.
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

from dnfw.waverider import stallprobe as sp  # noqa: E402

REPLY = 0x800053A4
WORD2 = REPLY + 8


def collect(dp, pr, seconds: float) -> dict[int, int]:
    """Half index -> half, each seen twice with the same value, until all are or SECONDS pass."""
    want = 2 * len(sp.published())
    seen: dict[int, list[int]] = {}
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        data = dp.decode_peek(pr.call(dp.req_peek, WORD2, 4))["data"]
        word = struct.unpack(">I", data[:4])[0]
        if word:
            k, half = sp.decode(word)
            if 0 <= k < want:
                seen.setdefault(k, []).append(half)
        if len(seen) == want and all(len(v) >= 2 and v[-1] == v[-2] for v in seen.values()):
            break
    return {k: v[-1] for k, v in seen.items()}


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0],
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--for", dest="duration", type=float, default=120.0)
    p.add_argument("--port", default="Digitone II")
    p.add_argument("--save", type=pathlib.Path)
    p.add_argument("--load", type=pathlib.Path, help="print a saved reading, without the instrument")
    a = p.parse_args(argv)
    if a.load:
        words = json.loads(a.load.read_text(encoding="utf-8"))
    else:
        import dn2probe as dp
        import winmidi
        port = winmidi.Port(a.port, None, None)
        try:
            pr = dp.Probe(port)
            halves = collect(dp, pr, a.duration)
        finally:
            port.close()
        print(time.strftime("%H:%M:%S"), f"halves seen: {len(halves)} of {2 * len(sp.published())}")
        if not halves:
            print("  reply word 2 stayed 0: no stall code in this build, or it never published")
            return 1
        words = sp.words(halves)
        if a.save:
            a.save.parent.mkdir(parents=True, exist_ok=True)
            a.save.write_text(json.dumps(words, indent=1) + "\n", encoding="utf-8", newline="\n")
    print("\n".join(sp.report(words)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

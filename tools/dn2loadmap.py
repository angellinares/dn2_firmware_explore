"""Read a loadmap build's stage map over the USB probe (dnfw.waverider.loadmap).

    python tools/dn2loadmap.py [--windows 1] [--for 240] [--port "Digitone II"] [--save out/loadmap/LABEL.json]
    python tools/dn2loadmap.py --load out/loadmap/LABEL.json

The DSP keeps cycles and passes per stage of its frame over a window of 4,096 blocks (2.7 s).
Every 32nd window goes to SNAP, which then stays the same for 87 s, and every block one half of
SNAP goes out in reply word 2 (the ColdFire's copy at 0x800053ac), the next half each block.
This reads the word with PEEK until it holds every half of WINDOWS SNAPs, each half seen twice
with the same value, or FOR seconds pass. It prints each window: per segment, its passes and
cycles per block, the cycles of one pass, and its share of a frame (666,667 cycles), with and
without the marks' own cost.

The first SNAP comes 87 s after boot. Quit Transfer first: the probe needs the MIDI port.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))

from dnfw.waverider import loadmap as L  # noqa: E402

REPLY = 0x800053A4


def collect(dp, pr, windows: int, seconds: float) -> list[dict]:
    """Complete SNAPs, in the order they completed, as {"seq": s, "words": [...]}."""
    seen: dict[int, dict[int, dict[int, int]]] = {}     # seq -> index -> half -> times seen
    done: list[dict] = []
    reads = other = clash = 0
    t0 = time.monotonic()
    end = t0 + seconds
    while time.monotonic() < end and len(done) < windows:
        data = dp.decode_peek(pr.call(dp.req_peek, REPLY + L.WORD2_AT, 4))["data"]
        reads += 1
        got = L.decode_half(int.from_bytes(data[:4], "big"))
        if got is None:
            other += 1
            continue
        seq, i, half = got
        if any(w["seq"] == seq for w in done):
            continue
        votes = seen.setdefault(seq, {}).setdefault(i, {})
        votes[half] = votes.get(half, 0) + 1
        clash += len(votes) > 1 and votes[half] == 1
        firm = {k: h for k, v in seen[seq].items() for h, n in v.items() if n >= 2 and len(v) == 1}
        if len(firm) == L.HALVES:
            done.append({"seq": seq, "words": L.words_from_halves(firm)})
            del seen[seq]
            print(f"  SNAP {seq} complete after {reads} reads, {time.monotonic() - t0:.0f} s")
    rate = reads / max(1e-9, time.monotonic() - t0)
    print(f"{reads} reads ({rate:.1f} a second), {other} without a loadmap tag, {clash} halves read two ways, "
          f"{len(done)} SNAPs complete")
    for seq, got in seen.items():
        print(f"  SNAP {seq}: {len(got)} of {L.HALVES} halves seen")
    return done


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0],
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--windows", type=int, default=1)
    p.add_argument("--for", dest="duration", type=float, default=240.0)
    p.add_argument("--port", default="Digitone II")
    p.add_argument("--save", type=pathlib.Path)
    p.add_argument("--load", type=pathlib.Path, help="print a saved reading, without the instrument")
    a = p.parse_args(argv)
    if a.load:
        wins = json.loads(a.load.read_text(encoding="utf-8"))
    else:
        import dn2probe as dp
        import winmidi
        port = winmidi.Port(a.port, None, None)
        try:
            pr = dp.Probe(port)
            wins = collect(dp, pr, a.windows, a.duration)
        finally:
            port.close()
        if not wins:
            print("  no complete SNAP: not a loadmap build, less than 87 s since boot, or reads too slow for FOR")
            return 1
        if a.save:
            a.save.parent.mkdir(parents=True, exist_ok=True)
            a.save.write_text(json.dumps(wins, indent=1) + "\n", encoding="utf-8", newline="\n")
    for w in wins:
        print("\n".join(L.table(L.snapshot(w["words"]))))
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

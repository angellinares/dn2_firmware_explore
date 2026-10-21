"""Read a loadmap build's stage map over the USB probe (dnfw.waverider.loadmap).

    python tools/dn2loadmap.py [--windows 3] [--for 60] [--port "Digitone II"] [--save out/loadmap/LABEL.json]
    python tools/dn2loadmap.py --load out/loadmap/LABEL.json

The DSP keeps cycles and passes per stage of its frame, and every 4,096 blocks (2.7 s) it
publishes them as three pages, one at a time, in reply rows 1-12 (the ColdFire's copy at
0x800053a4). This reads the rows with PEEK until WINDOWS windows are complete or FOR seconds
pass, and prints each window: per segment, its passes and cycles per block, the cycles of one
pass, and its share of a frame (666,667 cycles), with and without the marks' own cost.

The first window after boot starts from an arbitrary EMUCLK, so skip it. Quit Transfer first:
the probe needs the MIDI port.
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
    """Complete windows, in order of SEQ, as {"seq": s, "pages": {p: 22 words}}."""
    got: dict[int, dict[int, list[int]]] = {}
    done: list[dict] = []
    reads = torn = 0
    end = time.monotonic() + seconds
    while time.monotonic() < end and len(done) < windows:
        data = dp.decode_peek(pr.call(dp.req_peek, REPLY + L.ROWS_AT, L.ROWS_SPAN))["data"]
        reads += 1
        page = L.decode_page(L.page_words(data))
        if page is None:
            torn += 1
            continue
        seq, p, words = page
        got.setdefault(seq, {})[p] = words
        if len(got[seq]) == L.PAGES and all(w["seq"] != seq for w in done):
            done.append({"seq": seq, "pages": got.pop(seq)})
    print(f"{reads} reads, {torn} without a valid page, {len(done)} windows complete")
    return done


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0],
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--windows", type=int, default=3)
    p.add_argument("--for", dest="duration", type=float, default=60.0)
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
            print("  no loadmap page seen: not a loadmap build, or the rows are not reaching the ColdFire")
            return 1
        if a.save:
            a.save.parent.mkdir(parents=True, exist_ok=True)
            a.save.write_text(json.dumps(wins, indent=1) + "\n", encoding="utf-8", newline="\n")
    for w in wins:
        pages = {int(k): v for k, v in w["pages"].items()}
        print("\n".join(L.table(L.snapshot(pages))))
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

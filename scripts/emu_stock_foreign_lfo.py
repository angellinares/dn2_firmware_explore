"""What stock 1.11's LFO evaluator does with a waveform or destination it does not have.

    python scripts/emu_stock_foreign_lfo.py [--frames 64]

The owner's question, 2026-10-10 (rivvi's song rows, docs/song-rows-report.md): a
project saved with the mods holds LFO waveforms and destinations stock has never
seen. If stock plays such a project, does its LFO write where it should not?

Evaluator A (`0x40137726`) in the `ui1200M` snapshot (stock 1.11), LFO3 on track 1
through the mirror, as scripts/emu_lfo_trigmodes.py drives it. Every write the call
makes is classed: the mirror buffer, the two output buffers, the LFO state block,
the random generator's two words and the stack are the evaluator's own; anything
else is a stray. Each foreign value runs beside a control (TRI on a stock
destination), and a run that faults is reported as a fault.

This is the evaluator alone: whether stock's LOAD lets such a value reach it is a
separate question (arp mode is bounded there, docs/mods.md).
"""

from __future__ import annotations

import argparse
import collections
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import emu_lfo_trigmodes as lt                               # noqa: E402
from emulib.machine import STACK                             # noqa: E402

STOCK_WAVES, STOCK_DEST = 7, 66                              # stock's waveform count; LFO3's own cell


def own_ranges(env):
    buf, _rate, out1, out2, span = env
    return [(buf, buf + span), (out1, out1 + 256), (out2, out2 + 256),
            (lt.A_STATE, lt.A_STATE + 0x780), (0x402A0DF8, 0x402A0E00), (STACK - 0x4000, STACK + 0x1000)]


def case(m, env, wave, dest, frames, strays):
    lt.DEST = dest
    try:
        seen = lt.run(m, *env, 1, wave, frames, 8)
    except Exception as e:                                    # a jump through a bad pointer, an unmapped access
        return "FAULT %s" % str(e)[:60]
    moved = len(set(seen)) > 1
    n = sum(strays.values())
    if not n:
        return "clean, the destination %s" % ("moves" if moved else "stays put")
    where = ", ".join("0x%08x x%d" % (a, c) for a, c in sorted(strays.items())[:6])
    return "STRAY %d writes: %s" % (n, where)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--frames", type=int, default=64)
    p.add_argument("--blind", action="store_true",
                   help="the detector's own control: stop counting the mirror buffer as the evaluator's, so every case must report strays")
    a = p.parse_args()
    m, env = lt._machine(False)
    own = own_ranges(env)[1:] if a.blind else own_ranges(env)
    strays = collections.Counter()

    def note(pc, address, value, size):
        if not any(lo <= address < hi for lo, hi in own):
            strays[address] += 1

    m.watch_writes(0, 0xFFFFFFFF, note)
    rows = [("control: TRI on its own destination", 0, STOCK_DEST)]
    rows += [("waveform %d" % w, w, STOCK_DEST) for w in range(STOCK_WAVES, 16)]
    rows += [("waveform %d" % w, w, STOCK_DEST) for w in (32, 127, 255)]
    rows += [("destination %d" % d, 0, d) for d in (99, 100, 101, 110, 127, 128, 200, 255)]
    bad = 0
    for name, wave, dest in rows:
        strays.clear()
        verdict = case(m, env, wave, dest, a.frames, strays)
        bad += not verdict.startswith("clean")
        print("%-38s %s" % (name, verdict))
        if verdict.startswith("FAULT"):
            m, env = lt._machine(False)                       # a faulted machine is not reused
            own = own_ranges(env)
            m.watch_writes(0, 0xFFFFFFFF, note)
    print("%d of %d cases wrote outside the evaluator's own memory or faulted" % (bad, len(rows)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

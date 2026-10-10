"""Does the LFO evaluator's state get written into the project image? Boot, then watch.

    python scripts/emu_lfo_state_escape.py --build out/lfo4-reset1 [--frames 400]

rivvi's song 1 and the owner's SKETCHPAD hold the LFO evaluator's state records (40
bytes per LFO, each starting 3f ff ff ff) over the start of song 1's storage, RAM
0x4120c770 on (docs/song-rows-report.md). This boots a build from reset as
emu_boot_engine.py does, gives every live sound an LFO4 when the build has one, and
calls evaluator A with its backup flag off and on. Every write that lands in the
project's working image (0x405cd96c, 12,890,116 bytes) is reported with its PC.
"""

from __future__ import annotations

import argparse
import collections
import json
import os
import pathlib
import struct
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import emu_boot_engine as be                                  # noqa: E402
from unicorn import UC_HOOK_MEM_WRITE                         # noqa: E402
from unicorn.m68k_const import UC_M68K_REG_PC                 # noqa: E402

IMAGE, IMAGE_LEN = 0x405CD96C, 12_890_116
SONG1 = 0x4120C770                                            # 0x200 before stored song 1


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--build", default="out/lfo4-reset1")
    p.add_argument("--limit", type=int, default=400_000_000)
    p.add_argument("--frames", type=int, default=8)
    p.add_argument("--mode", type=int, default=None,
                   help="TRIG MODE for LFO1..3 on every track (3 ONE, 4 HALF), so a build's ONE/HALF code runs")
    a = p.parse_args()
    build = os.path.join(be.ROOT, a.build)
    symbols = pathlib.Path(f"{build}/symbols.json")
    sym = {k: int(v, 16) for k, v in json.loads(symbols.read_text()).items()} if symbols.exists() else {}
    holder = {}
    m, st, stop = be.dspboot.run(be.SYX, open(f"{build}/section_3_MAIN_OS.bin", "rb").read(),
                                 limit=a.limit, machine_out=holder)
    print(f"  booted {os.path.basename(build)}: {st['n']:,} instructions, stop {stop!r}")
    after = be.After(m.uc)
    span = be.MIRROR_AT + be.TRACKS * be.MIRROR_BYTES + 32
    buf = after.alloc(span)
    after.write(buf, struct.pack(">H", be.REST) * (span // 2))
    if a.mode is not None:                                    # MODE is the 7th of an LFO's eight slots
        for t_ in range(be.TRACKS):
            row = buf + be.MIRROR_AT + be.MIRROR_BYTES * t_
            for lfo in range(3):
                first = 1 + 8 * lfo
                after.write(row + 2 * (first + 1), struct.pack(">H", 8 << 8))      # MULT 8: cycles end soon
                after.write(row + 2 * (first + 3), struct.pack(">H", 66 << 8))     # DEST: a stock cell
                after.write(row + 2 * (first + 6), struct.pack(">H", a.mode << 8))
                after.write(row + 2 * (first + 7), struct.pack(">H", 0x6000))      # DEP
        print(f"  LFO1..3 on every track: TRIG MODE {a.mode}")
    frac = after.alloc(len(be.SET_FRAC))
    after.write(frac, be.SET_FRAC)
    after.call(frac)
    rate = after.long(be.RATE)
    out1, out2 = after.alloc(256), after.alloc(256)
    if "ext_set" in sym:
        base = after.long(0x800052A0)
        for t in range(be.TRACKS if base else 0):
            sound = base + 52 + be.SOUND_BYTES * t
            after.call(sym["ext_set"], sound, 3, 76 << 8)
            after.call(sym["ext_set"], sound, 7, 0x7000)
        print(f"  LFO4 set on the {be.TRACKS if base else 0} live sounds")

    hits = collections.Counter()

    def wrote(uc, access, address, size, value, user):
        hits[(address & ~0xFF, uc.reg_read(UC_M68K_REG_PC))] += 1

    m.uc.hook_add(UC_HOOK_MEM_WRITE, wrote, begin=IMAGE, end=IMAGE + IMAGE_LEN)
    for flag in (0, 1, 0xFF, 0x100):
        hits.clear()
        for f in range(a.frames):
            # with --mode: one trigger, then none, so a ONE or HALF cycle runs to its stop
            trig = 0xFFFF if (a.mode is None or f == 0) else 0
            after.call(be.EVAL_A, buf, rate, trig, trig, out1, out2, flag)
        if a.mode is not None:
            cells = {struct.unpack(">H", bytes(after.uc.mem_read(buf + be.MIRROR_AT + 2 * 66, 2)))[0]}
            print(f"      track 1's destination cell after the run: {sorted(hex(c) for c in cells)}")
        n = sum(hits.values())
        print(f"  backup flag {flag:#x}: {n} writes into the project image")
        for (page, pc), c in sorted(hits.items())[:12]:
            near = " <- song 1's area" if SONG1 <= page < SONG1 + 0xC00 else ""
            print(f"      0x{page:08x}.. from pc 0x{pc:08x} x{c}{near}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

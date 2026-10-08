"""What stock 1.11's LFO does after TRIG MODE ONE and HALF stop, in the emulator.

    python scripts/emu_lfo_trigmodes.py [--frames 400]

Community report (docs/ideas-backlog.md 36): with a square LFO, ONE turns the
modulation off after one cycle and HALF jumps back to the middle, where the user
expected the LFO to hold its position. The static read of evaluator A (1.11
`0x40137726`): on crossing the cycle's middle in HALF (mode 4), or its end in ONE
(mode 3), the LFO's output is set from a per-waveform table (HALF `0x4020b2ec`;
ONE `0x4020b308`, or `0x4020b324` at negative speed) and a stop flag is set; once
stopped the waveform isn't evaluated and the output stays that constant.

This drives evaluator A frame by frame in the `ui1200M` snapshot (stock 1.11),
LFO3 on track 1 through the mirror the frame builder fills (slots 17..24, the
same as scripts/emu_lfo4_vs_lfo3.py), one trigger on frame 0 and none after, and
prints the destination cell's trajectory for TRIG (the control: it keeps running)
and for ONE and HALF, per waveform.
"""

from __future__ import annotations

import argparse
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from emulib.machine import SNAP, Machine                     # noqa: E402

EVAL_A = 0x40137726
MIRROR_AT, MIRROR_BYTES, TRACKS = 34, 202, 16
REST = 0x4000
RATE = 0x402A0DEC
SET_FRAC = bytes.fromhex("a93c000000204e75")                # movel #32,%macsr ; rts
TRACK = 0
SLOT0, DEST = 17, 66                                        # LFO3's eight mirror slots; its cell
MODES = {"TRIG": 1, "ONE": 3, "HALF": 4}
WAVES = {"TRI": 0, "SIN": 1, "SQR": 2, "SAW": 3}
# --hold: the two stores that put the stop table's value in the output (state +84)
HOLD_SITES = ((0x401378EC, bytes.fromhex("25500054")),     # HALF: movel %a0@,%a2@(84)
              (0x40137920, bytes.fromhex("25480054")))     # ONE:  movel %a0,%a2@(84)
NOP2 = bytes.fromhex("4e714e71")


SPH_SHIFT = 8
SPD = 0x7000                                                # SPD's cell: 0x4000 is 0, below it negative


def run(m, buf, rate, out1, out2, span, mode, wave, frames, mult, sph=0):
    block = MIRROR_AT + TRACK * MIRROR_BYTES
    #       SPD     MULT    FADE    DEST        WAVE       SPH  MODE       DEP
    row = (SPD, mult << 8, 0x4000, DEST << 8, wave << 8, (sph << SPH_SHIFT) & 0xFFFF, mode << 8, 0x6000)
    resting = bytearray(struct.pack(">H", REST) * (span // 2))
    for k, value in enumerate(row):
        at = block + 2 * (SLOT0 + k)
        resting[at:at + 2] = struct.pack(">H", value)
    seen = []
    for f in range(frames):
        m.write(buf, bytes(resting))
        trig = 0xFFFF if f == 0 else 0
        m.call(EVAL_A, buf, rate, trig, trig, out1, out2, 0)
        seen.append(struct.unpack(">H", m.read(buf + block + 2 * DEST, 2))[0])
    return seen


def describe(seen):
    last_change = max((i for i in range(1, len(seen)) if seen[i] != seen[i - 1]), default=0)
    return (f"{len(set(seen))} distinct, span {min(seen):#06x}..{max(seen):#06x}, "
            f"last change at frame {last_change}, final {seen[-1]:#06x}"
            + (" (= centre)" if seen[-1] == REST else ""))


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--frames", type=int, default=400)
    p.add_argument("--mult", type=int, default=8, help="MULT index (the speed doubles per step)")
    p.add_argument("--hold", action="store_true", help="NOP the two stop-table stores: hold the last output")
    p.add_argument("--spd", type=lambda v: int(v, 0), default=0x7000, help="SPD's cell (0x4000 = 0; below it the LFO runs backwards)")
    p.add_argument("--sph-shift", type=int, default=8, help="SPH's cell = SPH << this (8 or 9: which the panel writes is the question)")
    p.add_argument("--period", action="store_true", help="the free-running period, and where each SPH starts")
    p.add_argument("--sph", type=int, nargs="+", default=None,
                   help="start phases (SPH, 0..127) to sweep: prints, per mode, the frame each stops at")
    a = p.parse_args()
    global SPH_SHIFT, SPD
    SPH_SHIFT, SPD = a.sph_shift, a.spd
    m = Machine(SNAP)
    if a.hold:
        for at, stock in HOLD_SITES:
            assert m.read(at, 4) == stock, f"{at:#x} is not the stock store"
            m.write(at, NOP2)
        print("  --hold: the stop-table stores are NOPs")
    span = MIRROR_AT + TRACKS * MIRROR_BYTES + 32
    buf = m.alloc(span)
    frac = m.alloc(len(SET_FRAC))
    m.write(frac, SET_FRAC)
    m.call(frac)
    rate = m.long(RATE)
    out1, out2 = m.alloc(256), m.alloc(256)
    if a.period:
        # TRIG on TRI, SPH 0: the frames between successive maxima, and the phase word (state +80)
        seen = run(m, buf, rate, out1, out2, span, MODES["TRIG"], 0, a.frames, a.mult, 0)
        peaks = [i for i in range(1, len(seen) - 1) if seen[i] >= seen[i - 1] and seen[i] > seen[i + 1]]
        print(f"  TRI TRIG peaks at frames {peaks[:8]}; period {[b - a2 for a2, b in zip(peaks, peaks[1:])][:6]}")
        for sph in a.sph or [0, 32, 64, 96, 127]:
            seen = run(m, buf, rate, out1, out2, span, MODES["TRIG"], 0, 4, a.mult, sph)
            print(f"  SPH {sph:3d}: TRIG starts {seen[0]:#06x}")
        return 0
    if a.sph is not None:
        # the free-running period, from TRIG at SPH 0: frames between two maxima
        for wname, wave in (("TRI", 0), ("SIN", 1), ("SAW", 3)):
            for mname in ("ONE", "HALF"):
                row = []
                for sph in a.sph:
                    seen = run(m, buf, rate, out1, out2, span, MODES[mname], wave, a.frames, a.mult, sph)
                    stop = max((i for i in range(1, len(seen)) if seen[i] != seen[i - 1]), default=0)
                    row.append(f"SPH {sph:3d}: stops at {stop:3d}, start {seen[0]:#06x}, end {seen[-1]:#06x}")
                print(f"  {wname} {mname:4s} " + " | ".join(row))
        return 0
    for wname, wave in WAVES.items():
        for mname, mode in MODES.items():
            seen = run(m, buf, rate, out1, out2, span, mode, wave, a.frames, a.mult)
            print(f"  {wname} {mname:4s}: {describe(seen)}")
            if mname == "TRIG":
                print(f"           first frames: {[hex(v) for v in seen[:: max(1, len(seen) // 24)]]}")
            if mname != "TRIG":
                # the frames around the stop
                i = max((i for i in range(1, len(seen)) if seen[i] != seen[i - 1]), default=0)
                print(f"           around the stop: {[hex(v) for v in seen[max(0, i - 4):i + 3]]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

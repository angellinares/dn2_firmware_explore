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
              (0x40137920, bytes.fromhex("25480054")),     # ONE:  movel %a0,%a2@(84)
              (0x401374E4, bytes.fromhex("2ab03c00")),     # B (MIDI) HALF: movel %a0@(0,%d3:l:4),%a5@
              (0x4013751E, bytes.fromhex("2a81")))         # B (MIDI) ONE:  movel %d1,%a5@
NOP2 = bytes.fromhex("4e714e71")


SPH_SHIFT = 8
SPD = 0x7000                                                # SPD's cell: 0x4000 is 0, below it negative


def run(m, buf, rate, out1, out2, span, mode, wave, frames, mult, sph=0, trigs=(0,), fade=0x4000):
    if MIDI:
        return run_b(m, mode, wave, frames, mult, sph, trigs, fade)
    block = MIRROR_AT + TRACK * MIRROR_BYTES
    #       SPD     MULT    FADE    DEST        WAVE       SPH  MODE       DEP
    row = (SPD, mult << 8, fade, DEST << 8, wave << 8, (sph << SPH_SHIFT) & 0xFFFF, _mode_at(mode, 0) << 8, 0x6000)
    resting = bytearray(struct.pack(">H", REST) * (span // 2))
    for k, value in enumerate(row):
        at = block + 2 * (SLOT0 + k)
        resting[at:at + 2] = struct.pack(">H", value)
    _reset(m)
    seen = []
    mode_cell = block + 2 * (SLOT0 + 6)
    for f in range(frames):
        resting[mode_cell:mode_cell + 2] = struct.pack(">H", _mode_at(mode, f) << 8)
        m.write(buf, bytes(resting))
        trig = 0xFFFF if f in trigs else 0
        m.call(EVAL_A, buf, rate, trig, trig, out1, out2, 0)
        seen.append(struct.unpack(">H", m.read(buf + block + 2 * DEST, 2))[0])
    return seen


EVAL_B = 0x401373DC                                        # the MIDI tracks' LFOs
B_PARAMS = 0x44616448                                      # its parameter block (track 0 at the base)
B_STATE = 0x4463F498                                       # its state block; the first LFO run is fields +80..
B_RATE = 0x200000                                          # the tempo-derived rate words at +3360/+3424 are 0 in
                                                           # ui1200M (no MIDI track running): ~55 frames a cycle
B_FIELDS = {"SPD": 34, "MULT": 36, "FADE": 38, "WAVE": 42, "SPH": 44, "MODE": 46}
MIDI = False
A_STATE = 0x4463FC18                                       # evaluator A's state block (and B_STATE): 0x780 B each
PRISTINE: dict = {}                                        # id(machine) -> the blocks as the snapshot holds them


def _reset(m):
    """Both LFO state blocks back to the snapshot's, so every case starts the same."""
    if id(m) in PRISTINE:
        for at, data in PRISTINE[id(m)]:
            m.write(at, data)


def run_b(m, mode, wave, frames, mult, sph=0, trigs=(0,), fade=0x4000):
    """Evaluator B, track 0, its first LFO: the parameters written each frame, the output
    (state +84, the same field A uses) read after the call."""
    vals = {"SPD": SPD, "MULT": mult << 8, "FADE": fade, "WAVE": wave << 8,
            "SPH": (sph << SPH_SHIFT) & 0xFFFF, "MODE": 0}
    _reset(m)
    m.write(B_PARAMS + 3360, struct.pack(">I", B_RATE))
    m.write(B_PARAMS + 3424, struct.pack(">I", B_RATE))
    seen = []
    for f in range(frames):
        vals["MODE"] = _mode_at(mode, f) << 8
        for k, at in B_FIELDS.items():
            m.write(B_PARAMS + at, struct.pack(">H", vals[k]))
        m.call(EVAL_B, B_PARAMS, 0, 1 if f in trigs else 0)
        seen.append(struct.unpack(">i", m.read(B_STATE + 84, 4))[0] >> 16)
    return seen


def _mode_at(mode, f):
    """MODE is a TRIG MODE, or {frame: mode} (the mode from that frame on)."""
    if not isinstance(mode, dict):
        return mode
    return mode[max(k for k in mode if k <= f)]


def _machine(fix: bool):
    m = Machine(SNAP)
    if fix:
        import build_lfo_length as fx                    # noqa: PLC0415
        payload, at = fx.assemble_stubs(fx.SOURCE, fx.CODE_VA)
        m.write(fx.CODE_VA, payload)
        for va, stock, label in fx.HOOKS:
            new = bytes.fromhex("4ef9") + struct.pack(">I", at[label])
            m.write(va, new + bytes.fromhex("4e71") * ((len(stock) - len(new)) // 2))
        m.flush()
    # the LFO state blocks, and the random generator RND draws from (0x4013739c: two words at
    # 0x402a0df8), which the two machines would otherwise advance differently
    PRISTINE[id(m)] = [(at, m.read(at, 0x780)) for at in (A_STATE, B_STATE)] + [(0x402A0DF8, m.read(0x402A0DF8, 8))]
    span = MIRROR_AT + TRACKS * MIRROR_BYTES + 32
    buf, frac = m.alloc(span), m.alloc(len(SET_FRAC))
    m.write(frac, SET_FRAC)
    m.call(frac)
    return m, (buf, m.long(RATE), m.alloc(256), m.alloc(256), span)


def _stop(seen, after):
    """The last frame that changes, from AFTER on (the run's stop, if it stops)."""
    return max((i for i in range(max(after, 1), len(seen)) if seen[i] != seen[i - 1]), default=after)


REF_LEN: dict = {}


def regress(a) -> int:
    """Stock vs lfolength. Pass: outside ONE / HALF with SPH > 0 the fixed machine equals
    stock exactly; ONE / HALF trace TRIG (the same trigs) until each stop, and each run
    after a trig is stock's SPH-0 length."""
    global SPD
    stock, sargs = _machine(False)
    fixed, fargs = _machine(True)
    frames = a.frames
    patterns = {"one trig": (0,), "retrig mid-run": (0, 15), "retrig after the stop": (0, 75)}
    fails = total = 0
    for spd in (0x7000, 0x1000):
        SPD = spd
        for fade in (0x4000, 0x6000):
            for wname, wave in [w for w in (("TRI", 0), ("SIN", 1), ("SQR", 2), ("SAW", 3), ("EXP", 4), ("RMP", 5), ("RND", 6))
                                if not a.waves or w[0] in a.waves]:
                for sph in (0, 32, 64, 96):
                    for pname, trigs in patterns.items():
                        for mname, mode in (("FREE", 0), ("TRIG", 1), ("HOLD", 2), ("ONE", 3), ("HALF", 4)):
                            total += 1
                            s_ = run(stock, *sargs, mode, wave, frames, a.mult, sph, trigs, fade)
                            f_ = run(fixed, *fargs, mode, wave, frames, a.mult, sph, trigs, fade)
                            if mode not in (3, 4) or sph == 0 or wave == 6:
                                ok = s_ == f_
                                why = "differs from stock"
                            else:
                                t_ = run(fixed, *fargs, 1, wave, frames, a.mult, sph, trigs, fade)
                                key = (mode, wave, fade, spd)
                                if key not in REF_LEN:      # stock's run length: SPH 0, one trig
                                    z = run(stock, *sargs, mode, wave, frames, a.mult, 0, (0,), fade)
                                    REF_LEN[key] = _stop(z, 0)
                                L = REF_LEN[key]
                                ok, why = True, ""
                                starts = list(trigs) + [frames]
                                for k, t0 in enumerate(trigs):
                                    end = min(t0 + L, starts[k + 1])
                                    if f_[t0:end] != t_[t0:end]:
                                        ok, why = False, f"not TRIG's waveform after the trig at {t0}"
                                        break
                                    if starts[k + 1] > t0 + L + 1 and _stop(f_[:starts[k + 1]], t0) > t0 + L:
                                        ok, why = False, f"runs past {L} frames after the trig at {t0}"
                                        break
                            if not ok:
                                fails += 1
                                print(f"  FAIL SPD {spd:#x} FADE {fade:#x} {wname} SPH {sph} {pname} {mname}: {why}")
    print(f"  {total - fails}/{total} cases pass ({'B, MIDI' if MIDI else 'A, audio'})")
    return 0 if not fails else 1


def describe(seen):
    last_change = max((i for i in range(1, len(seen)) if seen[i] != seen[i - 1]), default=0)
    return (f"{len(set(seen))} distinct, span {min(seen):#06x}..{max(seen):#06x}, "
            f"last change at frame {last_change}, final {seen[-1]:#06x}"
            + (" (= centre)" if seen[-1] == REST else ""))


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--frames", type=int, default=400)
    p.add_argument("--mult", type=int, default=8, help="MULT index (the speed doubles per step)")
    p.add_argument("--fix", action="store_true",
                   help="install scripts/build_lfo_length.py's hooks and code (lfolength): ONE/HALF from the start phase")
    p.add_argument("--hold", action="store_true", help="NOP the two stop-table stores: hold the last output")
    p.add_argument("--spd", type=lambda v: int(v, 0), default=0x7000, help="SPD's cell (0x4000 = 0; below it the LFO runs backwards)")
    p.add_argument("--sph-shift", type=int, default=8, help="SPH's cell = SPH << this (8 or 9: which the panel writes is the question)")
    p.add_argument("--midi", action="store_true", help="drive evaluator B (MIDI tracks) instead of A")
    p.add_argument("--switch", action="store_true", help="change the TRIG MODE mid-run: the fixed machine must equal stock")
    p.add_argument("--waves", nargs="+", default=None, help="--regress: only these waveforms (TRI SIN SQR SAW EXP RMP RND)")
    p.add_argument("--regress", action="store_true",
                   help="stock vs lfolength over the whole grid (modes, waveforms, SPH, speed, fade, retrigs)")
    p.add_argument("--compare", action="store_true", help="ONE / HALF against TRIG from the same SPH, frame by frame")
    p.add_argument("--period", action="store_true", help="the free-running period, and where each SPH starts")
    p.add_argument("--sph", type=int, nargs="+", default=None,
                   help="start phases (SPH, 0..127) to sweep: prints, per mode, the frame each stops at")
    a = p.parse_args()
    global SPH_SHIFT, SPD, MIDI
    SPH_SHIFT, SPD, MIDI = a.sph_shift, a.spd, a.midi
    m = Machine(SNAP)
    if a.fix:
        import build_lfo_length as fix                   # noqa: PLC0415
        payload, at = fix.assemble_stubs(fix.SOURCE, fix.CODE_VA)
        m.write(fix.CODE_VA, payload)
        for va, stock, label in fix.HOOKS:
            assert m.read(va, len(stock)) == stock, f"{va:#x} is not stock"
            new = bytes.fromhex("4ef9") + struct.pack(">I", at[label])
            new += bytes.fromhex("4e71") * ((len(stock) - len(new)) // 2)
            m.write(va, new)
        m.flush()
        print(f"  --fix: lfolength's 4 hooks, {len(payload)} B at {fix.CODE_VA:#x}")
    if a.hold:
        for at, stock in HOLD_SITES:
            assert m.read(at, len(stock)) == stock, f"{at:#x} is not the stock store"
            m.write(at, NOP2[:len(stock)])
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
    if a.switch:
        stock, sargs = _machine(False)
        fixed, fargs = _machine(True)
        bad = 0
        for wname, wave in (("TRI", 0), ("SIN", 1), ("SAW", 3)):
            for frm, to in ((3, 0), (3, 2), (4, 0), (3, 1), (4, 1)):
                for sph in (32, 64, 96):
                    sched = {0: frm, 10: to}
                    s_ = run(stock, *sargs, sched, wave, 100, a.mult, sph)
                    f_ = run(fixed, *fargs, sched, wave, 100, a.mult, sph)
                    ok = s_ == f_
                    bad += not ok
                    if not ok:
                        k = next(i for i in range(len(s_)) if s_[i] != f_[i])
                        print(f"  FAIL {wname} SPH {sph} mode {frm} -> {to} at frame 10: first differs at {k}")
        print(f"  mode changes mid-run: {'all equal stock' if not bad else f'{bad} differ'}")
        return 0 if not bad else 1
    if a.regress:
        return regress(a)
    if a.compare:
        # each ONE / HALF against TRIG from the same start phase (TRIG is the waveform as it
        # runs free): until the stop they should match frame for frame
        worst = 0
        for wname, wave in (("TRI", 0), ("SIN", 1), ("SAW", 3)):
            for sph in a.sph or [0, 16, 32, 48, 63, 64, 80, 96, 112, 127]:
                trig = run(m, buf, rate, out1, out2, span, MODES["TRIG"], wave, a.frames, a.mult, sph)
                cells = []
                for mname in ("ONE", "HALF"):
                    seen = run(m, buf, rate, out1, out2, span, MODES[mname], wave, a.frames, a.mult, sph)
                    stop = max((i for i in range(1, len(seen)) if seen[i] != seen[i - 1]), default=0)
                    d = max(abs(x - y) for x, y in zip(seen[:stop], trig[:stop])) if stop else 0
                    worst = max(worst, d)
                    cells.append(f"{mname} {stop:3d} frames, max diff from TRIG {d:#x}")
                print(f"  {wname} SPH {sph:3d}: " + " | ".join(cells))
        print(f"  worst difference from TRIG before a stop: {worst:#x}")
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

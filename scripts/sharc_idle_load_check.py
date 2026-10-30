"""The idle-time stub in digikit's SHARC runner: FreeRTOS's idle loop, patched, goes round.

    python scripts/sharc_idle_load_check.py [--instructions 240000]

Starts the idle task at the top of its loop (sw 0xb88aab, `dnfw.waverider.dsp`'s
IDLE_RETURN_SW) on the engine-init snapshot with the built section 7, and runs it.
Checks, each against the machine's own state:

- the loop goes round: the top is reached again and again, and nothing outside the
  idle loop, its callee and the stub runs;
- the stub counts every pass (DM 0x2de114) and, on a quiet idle task, adds each
  pass's cycles to the idle total (0x2de110);
- reply word 1 of both reply pages (0x2c49d4, 0x2c59d4) holds that total with its
  halves swapped, as the per-frame handler stores word 0;
- a busy stretch (4,096 cycles or more since the previous pass) of a frame or more
  (666,667 cycles) adds 1 to OVERRUNS (0x2de140), and reply word 3 of both pages
  (0x2c49dc, 0x2c59dc) holds OVERRUNS, halves swapped. A stretch 1 cycle short does not;
- the stub keeps the longest stretch of each window of 1,500 stretches (0x2de144, the
  count at 0x2de148). When a window closes, reply word 4 of both pages (0x2c49e0,
  0x2c59e0) holds that longest, halves swapped, and a new window starts at 0;
- R8, R9, R10 and R11, the only registers it touches, are what they were at every
  return to the loop's top.

The runner's EMUCLK does not advance, so the stub's clock is fed in: right after its
`R8 = EMUCLK` (sw 0x16f514) R8 is set to a counter. The counter steps STEP cycles on
odd passes and a busy stretch on even passes (a preemption): mostly 10,000 to 14,999
cycles, with stretches of exactly FRAME - 1 and FRAME among them. The counter starts
just below 2^32, so it wraps on a short step. The idle total must then be exactly the
sum of the short steps: the stretches left out, the wrap handled. The run stops at the
loop's top, so every pass it counts is complete. The instrument is where the figure
means anything.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import sharc_waverider_m5 as m5                                # noqa: E402
from dnfw.waverider import dsp                                  # noqa: E402
from dnfw import sharcemu  # noqa: E402

PASSES, TOTAL, LAST = 0x2DE114, 0x2DE110, 0x2DE10C
OVERRUNS, LONGEST, STRETCHES = 0x2DE140, 0x2DE144, 0x2DE148
REPLY_WORD1 = (0x2C49D4, 0x2C59D4)
REPLY_WORD3, REPLY_WORD4 = (0x2C49DC, 0x2C59DC), (0x2C49E0, 0x2C59E0)
SENTINELS = {"R8": 0x11111111, "R9": 0x22222222, "R10": 0x33333333, "R11": 0x44444444}
# idle_load.asm's constants: R11 = 4096 (THRESHOLD), R11 = 666667 (a frame), R11 = 1500 (a window)
THRESHOLD, FRAME, WINDOW = 4096, 666_667, 1500
STEP, GAP = 100, 10_000
START = 0xFFFFFFC0                                  # the counter wraps on the first short step
PASS_LIMIT = 10_000                                 # the instructions one pass may take


def after_emuclk() -> int:
    """The sw address of the instruction after the stub's `R8 = EMUCLK;`, from its object."""
    spec = json.loads((ROOT / "csrc/waverider/sharc/idle_load.json").read_text(encoding="utf-8"))
    src = [ln.split("//", 1)[0].strip() for ln in (ROOT / "csrc/waverider/sharc/idle_load.asm").read_text().splitlines()]
    src = [c for c in src if c and not c.startswith(".") and not c.endswith(":")]
    return dsp.IDLE_SW + spec["instruction_offsets"][src.index("R8 = EMUCLK;") + 1] // 2


def stretch(j: int) -> int:
    """The length of the Jth busy stretch the clock feeds (J from 1)."""
    if j % 100 == 25:
        return FRAME - 1                            # one cycle short of a frame: not an overrun
    if j % 100 == 75:
        return FRAME                                # a frame exactly: an overrun
    return GAP + (j * 37) % 5000


def clock(n: int, prev: int) -> int:
    """The fed clock at pass N (from 0). PREV is the clock at pass N - 1."""
    if n == 0:
        return START
    return (prev + (STEP if n % 2 else stretch(n // 2))) & 0xFFFFFFFF


def model(fed):
    """What the stub must leave, from the fed clock. A gap since the previous pass below
    THRESHOLD is idle, and a gap of THRESHOLD or more is a busy stretch. A stretch of FRAME
    or more is an overrun. The longest stretch takes every stretch that is not shorter
    (IF LT skips the store). At the WINDOW-th stretch the window's longest is published and
    both words start again at 0. The previous pass is 0 at the first pass (the build
    zero-fills the state block)."""
    last = total = overruns = longest = count = windows = 0
    word4 = None
    for now in fed:
        d = (now - last) & 0xFFFFFFFF
        if d < THRESHOLD:
            total = (total + d) & 0xFFFFFFFF
        else:
            if d >= FRAME:
                overruns += 1
            if d >= longest:
                longest = d
            count += 1
            if count >= WINDOW:
                word4, longest, count, windows = longest, 0, 0, windows + 1
        last = now
    return {"total": total, "overruns": overruns, "longest": longest, "count": count,
            "windows": windows, "word4": word4}


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--image", type=pathlib.Path,
                   default=ROOT / "00_Resources/00_Firmware/Digitone_II_OS1.11_dist.zip")
    p.add_argument("--digikit", type=pathlib.Path,
                   default=sharcemu.path())
    p.add_argument("--instructions", type=int, default=240_000,
                   help="run at least this many, then stop at the loop's next top")
    a = p.parse_args(argv)
    dk = m5.m1.Digikit(a.digikit)
    m5.fx.bind(str(a.digikit / "tools"))
    m5.m4.IMAGE = a.image
    stock = m5.m1.dn2_section7(a.image)
    image = m5.Image(dk, dsp.section7(stock))
    tops, pcs, fed = [], set(), []
    at_clock = after_emuclk()
    with tempfile.TemporaryDirectory(dir=m5.OUT) as tmp:
        snap, m2mach = m5.snapshot_path(dk, stock, pathlib.Path(tmp))
        init = m5.init_on(snap, m2mach, image)
        i7 = m5.m2.word_reg(init, "I7")
        r = init.fresh_call(dsp.IDLE_RETURN_SW,
                            regs={"I5": 0x2D0608, "R15": 1, "I6": i7, "I7": i7 - 16, **SENTINELS},
                            return_address=dsp.IDLE_RETURN_SW)
        before = [[m5.m2.word(r.state, w) or 0 for w in words] for words in (REPLY_WORD3, REPLY_WORD4)]

        def at_top(runner):
            tops.append({k: m5.m2.word_reg(runner, k) for k in SENTINELS})

        def feed(runner):
            now = clock(len(fed), fed[-1] if fed else 0)
            fed.append(now)
            runner.state.uregs[m5.fx.UREG_CODES["R8"]] = m5.fx.Const(now)

        f = m5.fixups({dsp.IDLE_RETURN_SW: at_top, dsp.IDLE_SW: lambda runner: pcs.add("stub"),
                       at_clock: feed})
        used, res = 0, None
        while used < a.instructions:                # one pass a call: each call stops at the loop's top
            res = m5.fx.run(r, PASS_LIMIT, f, stop_at={dsp.IDLE_RETURN_SW})
            used += res[2]
            if res[0] != "stop":
                break
        st = r.state
        passes = m5.m2.word(st, PASSES) or 0
        total = m5.m2.word(st, TOTAL) or 0
        words = [m5.m2.word(st, w) or 0 for w in REPLY_WORD1]
        overruns, longest, count = (m5.m2.word(st, w) or 0 for w in (OVERRUNS, LONGEST, STRETCHES))
        w3 = [m5.m2.word(st, w) or 0 for w in REPLY_WORD3]
        w4 = [m5.m2.word(st, w) or 0 for w in REPLY_WORD4]
    swapped = ((total << 16) | (total >> 16)) & 0xFFFFFFFF
    # the first pass differences against the zeroed LAST word: a stretch, left out
    want = sum(d for d in ((b - a) & 0xFFFFFFFF for a, b in zip(fed, fed[1:])) if d < 4096) & 0xFFFFFFFF
    m = model(fed[:passes])
    sw = lambda v: ((v << 16) | (v >> 16)) & 0xFFFFFFFF
    # the stretches from the clock alone: the first pass's (from LAST = 0), then each even pass's
    lengths = [START] + [stretch(n // 2) for n in range(2, passes, 2)]
    frames = sum(1 for d in lengths if d >= FRAME)
    short_by_1 = sum(1 for d in lengths if d == FRAME - 1)
    closed = len(lengths) // WINDOW
    wrapped = any(b < a for a, b in zip(fed, fed[1:]))
    print(f"  run ended: {res[0] if res else None} after {used} instructions; loop tops {len(tops)}, "
          f"stub passes {passes}, idle total {total}")
    print(f"  reply word 1: {words[0]:#010x} / {words[1]:#010x}   (total swapped {swapped:#010x})")
    print(f"  OVERRUNS {overruns}  longest {longest}  stretches {count}  (model {m['overruns']} / "
          f"{m['longest']} / {m['count']}; stretches fed {len(lengths)}, windows closed {m['windows']})")
    print(f"  reply word 3: {w3[0]:#010x} / {w3[1]:#010x}   word 4: {w4[0]:#010x} / {w4[1]:#010x}   "
          f"(before the run: {[[f'{v:#010x}' for v in x] for x in before]})")
    checks = {
        "the idle loop goes round (its top reached 10+ times)": len(tops) >= 10,
        "the run stopped at the loop's top": res is not None and res[0] == "stop",
        "the stub ran": "stub" in pcs,
        "the stub counts every pass (passes = loop tops - 1, within 1)": abs(passes - (len(tops) - 1)) <= 1,
        "R8-R11 unchanged at every return to the top": all(t == SENTINELS for t in tops),
        "reply word 1 of both pages holds the idle total, halves swapped":
            words[0] == words[1] == swapped and (total == 0 or words[0] != 0),
        "the idle total is exactly the sum of the short steps (gaps left out)": total == want > 0,
        "the fed clock wrapped during the run, and the total did not jump": wrapped and total == want,
        "OVERRUNS, the window's longest stretch and its count are exactly what the stub's rule gives (model)":
            (overruns, longest, count) == (m["overruns"], m["longest"], m["count"]),
        "each stretch of a frame or more is an overrun, a stretch 1 cycle short is not":
            overruns == frames and frames >= 2 and short_by_1 >= 1,
        "a window of 1,500 stretches closed, and the next one counts from 0":
            m["windows"] == closed >= 1 and count == len(lengths) - WINDOW * closed,
        "the open window's longest is the longest stretch fed since the window closed":
            longest == max(lengths[WINDOW * closed:], default=0) > 0,
        "reply word 3 of both pages holds OVERRUNS, halves swapped":
            w3[0] == w3[1] == sw(overruns) and overruns > 0,
        "reply word 4 of both pages holds the closed window's longest stretch, halves swapped":
            m["word4"] is not None and w4[0] == w4[1] == sw(m["word4"])
            and m["word4"] == max(lengths[WINDOW * (closed - 1):WINDOW * closed]),
    }
    for k, v in checks.items():
        print(f"  {'PASS' if v else 'FAIL'}  {k}")
    bad = [t for t in tops if t != SENTINELS][:3]
    if bad:
        print("  first differing registers:", bad)
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())

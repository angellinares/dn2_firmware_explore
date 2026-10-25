"""stall.asm in digikit's SHARC engine (Rust): the suite runs, the two readers agree, and the probe reads it.

    python scripts/sharc_stall_check.py [--digikit DIR] [--steps 3000000]

Builds `dnfw.waverider.stallprobe.section7_stall` and starts the idle task at its loop's top
on the engine-init snapshot, as scripts/sharc_accel_check.py does, then runs. Checks, each
against the machine's state:

- the idle loop goes round, through stall.asm and then the idle stub;
- every register stall.asm uses (R0-R15, I0-I4) holds at its exit what it held at its entry;
- the suite ran once, and every test was timed (its least is no longer the boot value);
- the old and the new reader wrote the same SAMPLES samples, bit for bit, none zero or not
  finite: the two loops compute the same thing, so the instrument compares like with like;
- reply word 2 of both pages carries TAG << 16 | HALF, halves swapped, and the halves seen
  rebuild the words in memory (what tools/dn2stall.py reads on the instrument).

It prints each test's time in the engine, where EMUCLK counts instructions: the stall
probe's numbers on the instrument are read against these.
"""

from __future__ import annotations

import argparse
import math
import pathlib
import struct
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import sharc_waverider_m5 as m5                                # noqa: E402
from dnfw import sharcemu                                       # noqa: E402
from dnfw.waverider import dsp, stallprobe as sp                # noqa: E402

REGS = sp.REGS
SENTINELS = {f"R{k}": 0x01010101 * (k + 1) for k in range(16)}
SENTINELS.update({f"I{k}": 0x002C0100 + 0x100 * k for k in range(5)})


def run(dk, stock, steps):
    import sharc_native  # noqa: PLC0415
    image = m5.Image(dk, sp.section7_stall(stock))
    tops, entries, exits, replies = [], [], [], []
    with tempfile.TemporaryDirectory(dir=m5.OUT) as tmp:
        snap, m2mach = m5.snapshot_path(dk, stock, pathlib.Path(tmp))
        init = m5.init_on(snap, m2mach, image)
        i7 = m5.m2.word_reg(init, "I7")
        eng = sharc_native.Engine(sharcemu.native_library(), image.memory, init)
        U = m5.fx.UREG_CODES
        for base, blob in ((sp.STATE_DM, sp.state()),):
            for k in range(0, len(blob), 4):
                eng.poke(base + k, int.from_bytes(blob[k:k + 4], "little"))
        eng.core.fresh_call(dsp.IDLE_RETURN_SW, dsp.IDLE_RETURN_SW)
        for name, v in {"I5": 0x2D0608, "R15": 1, "I6": i7, "I7": i7 - 16, **SENTINELS}.items():
            eng.set_reg(U[name], v)
        regs = lambda e: {k: e.native_reg(U[k]) for k in REGS}  # noqa: E731

        def at_top(e):
            tops.append(1)
            w = [e.native_word(x) or 0 for x in sp.REPLY_WORD2]
            if not replies or replies[-1] != w:
                replies.append(w)

        hooks = {dsp.IDLE_RETURN_SW: at_top, sp.STALL_SW: lambda e: entries.append(regs(e)),
                 dsp.IDLE_SW: lambda e: exits.append(regs(e))}
        res = eng.run(steps, hooks, stop_at=-1)
        memory = {name: eng.native_word(at) or 0 for name, at in sp.published()}
        outs = {name: [eng.native_word(buf + 4 * k) or 0 for k in range(sp.SAMPLES)]
                for name, *_, buf in sp.READERS}
    return res, tops, entries, exits, replies, memory, outs


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--image", type=pathlib.Path,
                   default=ROOT / "00_Resources/00_Firmware/Digitone_II_OS1.11_dist.zip")
    p.add_argument("--digikit", type=pathlib.Path, default=sharcemu.path())
    p.add_argument("--steps", type=int, default=3_000_000)
    a = p.parse_args(argv)
    dk = m5.m1.Digikit(a.digikit)
    m5.fx.bind(str(a.digikit / "tools"))
    m5.m4.IMAGE = a.image
    stock = m5.m1.dn2_section7(a.image)

    res, tops, entries, exits, replies, memory, outs = run(dk, stock, a.steps)
    halves = {}
    for w in replies:
        if w[0]:
            k, half = sp.decode(((w[0] << 16) | (w[0] >> 16)) & 0xFFFFFFFF)
            halves[k] = half
    rebuilt = sp.words(halves)
    old, new = outs["reader_old"], outs["reader_new"]
    floats = [struct.unpack("<f", struct.pack("<I", v))[0] for v in old]
    print(f"  run ended: {res[0]} after {res[2]:,} steps ({getattr(res[1], 'reason', res[1])}); "
          f"loop tops {len(tops)}, stall calls {len(entries)}")
    print("\n".join(sp.report(memory)))
    print(f"  reader samples: old {old[:3]} ..., new {new[:3]} ...")
    checks = {
        "the idle loop goes round (10+ tops)": len(tops) >= 10,
        "stall.asm runs each pass (calls = tops within 1)": abs(len(entries) - len(tops)) <= 1,
        "R0-R15 and I0-I4 at stall.asm's exit equal its entry, every call":
            len(exits) >= len(entries) - 1 > 0 and all(x == y for x, y in zip(entries, exits)),
        "the suite ran once": memory["runs"] == 1,
        "every test was timed": all(memory[f"{t}.least"] != sp.LEAST0 for t in sp.tests()),
        "the two readers wrote the same samples, bit for bit": old == new,
        "every sample is finite and not 0": all(v and math.isfinite(f) for v, f in zip(old, floats)),
        "reply word 2 is the same on both pages, each time": all(w[0] == w[1] for w in replies),
        "every half published decodes to its word in memory":
            bool(halves) and all(rebuilt[k] == memory[k] for k in rebuilt),
        "every half was published": len(halves) == 2 * len(sp.published()),
    }
    for k, v in checks.items():
        print(f"  {'PASS' if v else 'FAIL'}  {k}")
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())

"""ddrscan.asm in digikit's SHARC runner: it finds the words someone else wrote, and only those.

    python scripts/sharc_ddrscan_check.py [--instructions 1500000]

Builds `dnfw.waverider.ddrscan.section7_ddrscan` on a small span (8 KB, the same code and
state layout as the instrument build's 507 MB), starts the idle task at its loop's top on
the engine-init snapshot, writes the pattern over the span (the fill blocks' job on the
chip) and changes three words in it, then runs. Checks, each against the machine's state:

- the idle loop goes round, through the scanner and then the idle stub;
- every register the scanner uses (R0-R5, I0) holds at its exit (the idle stub's entry)
  what it held at its entry, at every call (the loop's top is no reference: the idle loop
  calls C code there, which may change the scratch registers);
- each completed pass publishes exactly the planted words: their count, the first and the
  last, and their 2 MB granule's bit, and a planted word written back to the pattern
  mid-run leaves the next pass's count;
- reply word 2 of both pages carries IDX << 27 | PUB[IDX], halves swapped, for each index
  the run reached;
- a span with no planted word publishes a count of 0 (the control).
"""

from __future__ import annotations

import argparse
import os
import pathlib
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import sharc_waverider_m5 as m5                                # noqa: E402
from dnfw.waverider import ddrscan, dsp                         # noqa: E402

SPAN = (0x80531000, 0x80533000)
PLANTS = (0x80531010, 0x80532000, 0x80532FFC)
SENTINELS = {"R0": 0x0A0A0A0A, "R1": 0x1B1B1B1B, "R2": 0x2C2C2C2C, "R3": 0x3D3D3D3D, "R4": 0x4E4E4E4E,
             "R5": 0x5F5F5F5F, "I0": 0x002C0100, "R8": 0x11111111, "R9": 0x22222222, "R10": 0x33333333,
             "R11": 0x44444444}
OFF = lambda a: (a - ddrscan.DDR[0]) >> 2


def run_case(dk, stock, plants, instructions, unplant_after=None):
    image = m5.Image(dk, ddrscan.section7_ddrscan(stock, span=SPAN))
    tops, scans, replies, exits = [], [], [], []
    regs = ("R0", "R1", "R2", "R3", "R4", "R5", "I0")
    with tempfile.TemporaryDirectory(dir=m5.OUT) as tmp:
        snap, m2mach = m5.snapshot_path(dk, stock, pathlib.Path(tmp))
        init = m5.init_on(snap, m2mach, image)
        st = init.state
        for k, b in enumerate(ddrscan.state(SPAN)[i:i + 4] for i in range(0, ddrscan.SCAN_STATE_BYTES, 4)):
            m5.m2.poke(st, ddrscan.SCAN_STATE_DM + 4 * k, int.from_bytes(b, "little"))
        for a in range(*SPAN, 4):
            m5.m2.poke(st, a, ddrscan.PATTERN)
        for a in plants:
            m5.m2.poke(st, a, 0x12345678)
        i7 = m5.m2.word_reg(init, "I7")
        r = init.fresh_call(dsp.IDLE_RETURN_SW, regs={"I5": 0x2D0608, "R15": 1, "I6": i7, "I7": i7 - 16,
                                                      **SENTINELS},
                            return_address=dsp.IDLE_RETURN_SW)

        def at_top(runner):
            tops.append({k: m5.m2.word_reg(runner, k) for k in SENTINELS})
            w = [m5.m2.word(runner.state, x) or 0 for x in ddrscan.REPLY_WORD2]
            if not replies or replies[-1] != w:
                replies.append(w)
            if unplant_after is not None and m5.m2.word(runner.state, ddrscan.PUB_DM) == unplant_after:
                m5.m2.poke(runner.state, plants[0], ddrscan.PATTERN)

        def at_scan(runner):
            scans.append({k: m5.m2.word_reg(runner, k) for k in regs})

        def at_exit(runner):
            exits.append({k: m5.m2.word_reg(runner, k) for k in regs})

        f = m5.fixups({dsp.IDLE_RETURN_SW: at_top, ddrscan.SCAN_SW: at_scan, dsp.IDLE_SW: at_exit})
        res = m5.fx.run(r, instructions, f)
        pub = [m5.m2.word(r.state, ddrscan.PUB_DM + 4 * k) or 0 for k in range(ddrscan.PUB_ENTRIES)]
    return res, tops, scans, replies, pub, exits


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--image", type=pathlib.Path,
                   default=ROOT / "00_Resources/00_Firmware/Digitone_II_OS1.11_dist.zip")
    p.add_argument("--digikit", type=pathlib.Path,
                   default=pathlib.Path(os.environ.get("DNFW_DIGIKIT_SHARC", ROOT.parent / "digikit-wt-sharcemu")))
    p.add_argument("--instructions", type=int, default=1_500_000)
    a = p.parse_args(argv)
    dk = m5.m1.Digikit(a.digikit)
    m5.fx.bind(str(a.digikit / "tools"))
    m5.m4.IMAGE = a.image
    stock = m5.m1.dn2_section7(a.image)

    res, tops, scans, replies, pub, exits = run_case(dk, stock, PLANTS, a.instructions, unplant_after=2)
    granule = (PLANTS[0] - ddrscan.DDR[0]) // ddrscan.GRANULE
    print(f"  run ended: {res[0]}; loop tops {len(tops)}, scanner calls {len(scans)}, passes {pub[0]}")
    print(f"  PUB[0..4]: {[hex(v) for v in pub[:5]]}; granules {ddrscan.granules(pub[4:20])}")
    seen = {}
    for w in replies:
        if w[0]:
            sw = ((w[0] << 16) | (w[0] >> 16)) & 0xFFFFFFFF
            idx, val = ddrscan.decode(sw)
            seen.setdefault(idx, set()).add(val)
    print(f"  reply word 2 indices seen: {sorted(seen)}")
    _, _, _, _, ctl, _ = run_case(dk, stock, (), 400_000)
    print(f"  control (nothing planted): passes {ctl[0]}, count {ctl[1]}, granules {ddrscan.granules(ctl[4:20])}")
    checks = {
        "the idle loop goes round (10+ tops)": len(tops) >= 10,
        "the scanner runs each pass (calls = tops within 1)": abs(len(scans) - len(tops)) <= 1,
        "R0-R5 and I0 at the scanner's exit equal its entry, every call":
            len(exits) >= len(scans) - 1 > 0 and all(a == b for a, b in zip(scans, exits)),
        "3+ passes completed": pub[0] >= 3,
        "after the first planted word was put back, a pass counts the other two": pub[1] == 2,
        "first and last are the second and third planted words":
            (pub[2], pub[3]) == (OFF(PLANTS[1]), OFF(PLANTS[2])),
        "the sticky bitmap holds their 2 MB granule, and only it": ddrscan.granules(pub[4:20]) == [granule],
        "reply word 2 is the same on both pages, each time": all(w[0] == w[1] for w in replies),
        "every published value is PUB[IDX] at some point (passes and counts move)":
            bool(seen) and all(i < ddrscan.PUB_ENTRIES for i in seen)
            and (4 not in seen or seen[4] == {pub[4]}),
        "the control: passes complete with a count of 0 and no granule":
            ctl[0] >= 1 and ctl[1] == 0 and not ddrscan.granules(ctl[4:20]),
    }
    for k, v in checks.items():
        print(f"  {'PASS' if v else 'FAIL'}  {k}")
    bad = [(a, b) for a, b in zip(scans, exits) if a != b][:2]
    if bad:
        print("  first differing entry/exit:", bad)
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())

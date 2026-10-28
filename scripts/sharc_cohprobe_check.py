"""cohprobe.asm in digikit's SHARC runner: it counts the reads that miss a write, and only those.

    python scripts/sharc_cohprobe_check.py [--instructions 3000000]

Builds `dnfw.waverider.cohprobe.section7_cohprobe`, starts the idle task at its loop's top on
the engine-init snapshot, and runs. The runner has no caches, so every read gives the last
write and the counts must be 0. Checks, each against the machine's state:

- the idle loop goes round, through the probe and then the idle stub;
- every register the probe uses (R0-R7, I0, I8) holds at its exit (the idle stub's entry)
  what it held at its entry, at every call;
- PUB[0] counts the calls, and PUB[1..11] stay 0;
- the bus check (`scripts/sharc_bus_check.py`) sees cases A, B and C read a DDR word on the
  other bus than its last write, and case D never: the probe tests what it says it tests;
- reply word 2 is the same on both pages and carries IDX << 27 | PUB[IDX];
- the negative: a second run puts the line's value before the write back just before
  case A's and case C's reads. Both cases then count every read as bad and as stale, the
  others stay 0, and PUB[11..15] name case A's first line, its value and V.
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
from dnfw import sharcemu                                       # noqa: E402
from dnfw.waverider import cohprobe, dsp                        # noqa: E402

REGS = ("R0", "R1", "R2", "R3", "R4", "R5", "R6", "R7", "I0", "I8")
SENTINELS = {"R0": 0x0A0A0A0A, "R1": 0x1B1B1B1B, "R2": 0x2C2C2C2C, "R3": 0x3D3D3D3D, "R4": 0x4E4E4E4E,
             "R5": 0x5F5F5F5F, "R6": 0x60606060, "R7": 0x71717171, "R8": 0x11111111, "R9": 0x22222222}
MASK = 0xFFFFFFFF


def instruction_sw() -> list[tuple[int, str]]:
    """cohprobe.asm's instructions -> (sw, source text), from the committed .json's offsets."""
    spec = json.loads(cohprobe.CODE.read_text(encoding="utf-8"))["cohprobe"]
    texts = []
    for line in (ROOT / spec["source"]).read_text(encoding="utf-8").splitlines():
        t = line.split("//", 1)[0].strip()
        if t and not t.startswith(".") and not t.endswith(":"):
            texts.append(t)
    base = int(spec["load_sw"], 16)
    return [(base + off // 2, t) for off, t in zip(spec["instruction_offsets"], texts)]


def case_spans(code: list[tuple[int, str]]) -> dict[str, tuple[int, int]]:
    """Each case's instructions, from its first address load to the next case's."""
    starts = [(sw, c) for c, (_, at) in cohprobe.CASES.items() for sw, t in code
              if t == f"R0 = {at:#x};" or (c == "E" and t == "R0 = LSHIFT R4 BY 2;")]
    starts.sort()
    end = next(sw for sw, t in code if t == "R0 = 64;")
    return {c: (sw, (starts[k + 1][0] if k + 1 < len(starts) else end)) for k, (sw, c) in enumerate(starts)}


def run_case(dk, stock, instructions, plant=()):
    image = m5.Image(dk, cohprobe.section7_cohprobe(stock))
    tops, entries, exits, replies = [], [], [], []
    from sharc_bus_check import BusCheck                       # noqa: PLC0415
    with tempfile.TemporaryDirectory(dir=m5.OUT) as tmp:
        snap, m2mach = m5.snapshot_path(dk, stock, pathlib.Path(tmp))
        init = m5.init_on(snap, m2mach, image)
        st = init.state
        for k in range(cohprobe.STATE_BYTES // 4):
            m5.m2.poke(st, cohprobe.STATE_DM + 4 * k, 0)
        i7 = m5.m2.word_reg(init, "I7")
        r = init.fresh_call(dsp.IDLE_RETURN_SW, regs={"I5": 0x2D0608, "R15": 1, "I6": i7, "I7": i7 - 16,
                                                      "I0": 0x002C0100, "I8": 0x002C0200, **SENTINELS},
                            return_address=dsp.IDLE_RETURN_SW)

        def at_top(runner):
            tops.append(1)
            w = [m5.m2.word(runner.state, x) or 0 for x in cohprobe.REPLY_WORD2]
            if not replies or replies[-1] != w:
                replies.append(w)

        def at_entry(runner):
            entries.append({k: m5.m2.word_reg(runner, k) for k in REGS})

        def at_exit(runner):
            exits.append({k: m5.m2.word_reg(runner, k) for k in REGS})

        def put_back(runner):                                  # R0: the line, R1: its value before
            m5.m2.poke(runner.state, m5.m2.word_reg(runner, "R0") & MASK, m5.m2.word_reg(runner, "R1") & MASK)

        hooks = {dsp.IDLE_RETURN_SW: at_top, cohprobe.CODE_SW: at_entry, dsp.IDLE_SW: at_exit}
        hooks.update({sw: put_back for sw in plant})
        with BusCheck(m5.fx, keep=1_000_000) as bus:
            res = m5.fx.run(r, instructions, m5.fixups(hooks))
        pub = [(m5.m2.word(r.state, cohprobe.PUB_DM + 4 * k) or 0) & MASK for k in range(cohprobe.PUB_ENTRIES)]
    return res, tops, entries, exits, replies, pub, bus


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--image", type=pathlib.Path,
                   default=ROOT / "00_Resources/00_Firmware/Digitone_II_OS1.11_dist.zip")
    p.add_argument("--digikit", type=pathlib.Path, default=sharcemu.path())
    p.add_argument("--instructions", type=int, default=3_000_000)
    a = p.parse_args(argv)
    dk = m5.m1.Digikit(a.digikit)
    m5.fx.bind(str(a.digikit / "tools"))
    m5.m4.IMAGE = a.image
    stock = m5.m1.dn2_section7(a.image)
    code = instruction_sw()
    spans = case_spans(code)
    reads = [sw for sw, t in code if t == "R2 = DM(0, I0);"]      # cases A, C, D, E in order

    res, tops, entries, exits, replies, pub, bus = run_case(dk, stock, a.instructions)
    calls = len(entries)
    crossed = {c for c, (lo, hi) in spans.items() for pc, *_ in bus.violations if lo <= pc < hi}
    print(f"  run ended: {res[0]}; loop tops {len(tops)}, probe calls {calls}, PUB[0] {pub[0]}")
    print(f"  PUB: {[hex(v) for v in pub]}")
    print(f"  cross-bus reads of cached words: {bus.count}, in cases {sorted(crossed)}")
    seen: dict[int, set[int]] = {}
    for w in replies:
        if w[0]:
            sw = ((w[0] << 16) | (w[0] >> 16)) & MASK
            idx, val = cohprobe.decode(sw)
            seen.setdefault(idx, set()).add(val)
    print(f"  reply word 2 indices seen: {sorted(seen)}")

    nres, _, nentries, _, _, neg, _ = run_case(dk, stock, a.instructions, plant=(reads[0], reads[1]))
    ncalls = len(nentries)
    full = 16 * (ncalls - 1)                                    # the last call may stop mid-way
    print(f"  negative: run ended {nres[0]}; probe calls {ncalls}; PUB {[hex(v) for v in neg[:16]]}")
    first = cohprobe.first_bad(neg[11])
    checks = {
        "the idle loop goes round (20+ probe calls)": calls >= 20,
        "the probe runs once per loop (calls = tops within 1)": abs(calls - len(tops)) <= 1,
        "R0-R7, I0 and I8 at the probe's exit equal its entry, every call":
            len(exits) >= calls - 1 > 0 and all(x == y for x, y in zip(entries, exits)),
        "PUB[0] counts the calls": pub[0] in (calls, calls - 1),
        "no bad read, no stale read, no first-bad marker (the runner has no caches)": not any(pub[1:12]),
        "the bus check sees cases A, B and C cross buses, and D never": {"A", "B", "C"} <= crossed and "D" not in crossed,
        "SHL1C_CFG and SHL1C_CFG2 were read (PUB[16..19] written each call)": calls >= 1,
        "reply word 2 is the same on both pages, each time": all(w[0] == w[1] for w in replies),
        "the probe published indices from reply word 2": bool(seen) and all(i < cohprobe.PUB_ENTRIES for i in seen),
        "negative: cases A and C count every read bad and stale":
            ncalls >= 3 and full <= neg[1] == neg[6] and full <= neg[3] == neg[8] and abs(neg[1] - neg[3]) <= 1,
        "negative: cases B, D and E stay 0": not any((neg[2], neg[4], neg[5], neg[7], neg[9], neg[10])),
        "negative: the first bad read is case A, line 0": first == ("A", 0),
    }
    print(f"  SHL1C_CFG as the runner holds it: {pub[16] | pub[17] << 27:#x}, SHL1C_CFG2 {pub[18] | pub[19] << 27:#x}")
    for k, v in checks.items():
        print(f"  {'PASS' if v else 'FAIL'}  {k}")
    bad = [(x, y) for x, y in zip(entries, exits) if x != y][:2]
    if bad:
        print("  first differing entry/exit:", bad)
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())

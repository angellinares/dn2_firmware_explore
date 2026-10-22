"""Check the loadmap build in digikit's runner: its records against the plain build's own steps.

    python scripts/sharc_loadmap_check.py

Runs four blocks of the per-block routine (sw 0x1c2712, track 0 Waverider with a note at block
1, both oscillators on, tracks 1-15 MIDI) twice in the Python runner: on Waverider's section 7,
and on the same stream with the loadmap marks (dnfw.waverider.loadmap). The runner's EMUCLK does
not move, so the mark's `R8 = EMUCLK` is fed the number of instructions run so far: a segment's
"cycles" are then its instructions. Checks:

- the run ends normally, and every track buffer of every block equals the plain run's, bit for bit;
- block 2's records, from its dispatch mark to block 3's: each segment's instructions minus one
  mark per pass (the null segment's own size) equal what the plain run executes between the
  same targets, exactly; and each segment's passes are the plain run's arrivals at its target;
- with BLOCKS preset to 131,071, the first block closes a SNAP window: SNAP holds the records
  (header, SEQ 1), and in block k reply word 2 of both reply pages holds half k of SNAP, tagged;
- the marks leave no trace: R0-R15, I0-I7, M0-M7, MODE1 and ASTAT at each stage's target are
  the plain run's.

Nothing here touches an instrument.
"""

from __future__ import annotations

import os
import pathlib
import sys
import tempfile

os.environ["DNFW_WAVERIDER_PYTHON"] = "1"             # the fed clock needs the Python runner's hooks
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import sharc_waverider_m5 as g                         # noqa: E402
from dnfw import sharcemu                              # noqa: E402
from dnfw.waverider import dsp, loadmap as L           # noqa: E402

BLOCKS = 4
REGS = [f"R{k}" for k in range(16)] + [f"I{k}" for k in range(8)] + [f"M{k}" for k in range(8)] + ["MODE1", "ASTATX"]


class Steps:
    """fx.OBSERVER: counts instructions; optionally logs (pc, step) of every step."""

    def __init__(self, log: bool):
        self.n, self.log, self.pcs = 0, log, []

    def before(self, runner, insn):
        if self.log:
            self.pcs.append(runner.state.pc_sw)

    def after(self, runner, insn, emulated):
        self.n += 1

    def skipped(self, pc):
        self.n += 1
        if self.log:
            self.pcs.append(pc)


def regs(r) -> tuple:
    out = []
    for name in REGS:
        try:
            out.append(g.m2.word_reg(r, name))
        except Exception:                               # a register the binding does not name
            out.append(None)
    return tuple(out)


def main() -> int:
    dk_path = sharcemu.path()
    dk = g.m1.Digikit(dk_path)
    g.fx.bind(str(dk_path / "tools"))
    stock = g.m1.dn2_section7(g.m4.IMAGE)
    sound, machines = g.m4.init_sound(g.m4.IMAGE)
    plain = dsp.section7(stock)
    marked = L.apply(plain)
    spec = L._code()
    marks = spec["marks"]
    lab = {k: int(v, 16) for k, v in spec["loadmap"]["labels"].items()}
    text = (ROOT / spec["loadmap"]["source"]).read_text(encoding="utf-8")
    lines = [ln for ln in text.splitlines()
             if (t := ln.split("//", 1)[0].strip()) and not t.startswith(".") and not t.endswith(":")]
    after_clock = L.MARK_SW + spec["loadmap"]["instruction_offsets"][
        next(k for k, ln in enumerate(lines) if "R8 = EMUCLK;" in ln) + 1] // 2
    over = {g.WAV1: 0x4000, g.LEV2: 0x6400}
    frames = lambda b: g.base_frame(sound, machines, trigger=(b == 1), overrides=over).to_bytes()
    targets = {m["target_sw"]: k for k, m in enumerate(marks)}
    # a stock mark is one call site's: other calls of the same routine do not pass a stub
    site_of = {}
    for p in spec["patches"]:
        name, _, rest = p["what"].partition(": sw ")
        if rest:
            site_of[next(k for k, m in enumerate(marks) if m["name"] == name)] = int(rest.split()[0], 16)
    # run_blocks taps these itself: an extra hook there would replace its own
    taken = {g.m3.DISPATCH, dsp.LOOP_SW, dsp.READER_SW, g.LOOP_RESUME, g.m3.AMP_STAGE, g.AMP_RETURN,
             g.SETUP_GUARD, g.SETUP_TABLE_READ, g.SETUP_NONE, 0x1C2712}
    checks = {}
    with tempfile.TemporaryDirectory(dir=g.OUT) as tmp:
        snap, mach = g.snapshot_path(dk, stock, pathlib.Path(tmp))

        # the plain run: every pc, and the registers at each mark target
        obs = Steps(log=True)
        g.fx.OBSERVER = obs
        seen_plain = {}
        hooks_p = {t: (lambda r, t=t: seen_plain.setdefault(t, regs(r))) for t in targets if t not in taken}
        block_start = []
        hooks_p[0x1C2712] = lambda r: block_start.append(len(obs.pcs))
        run_p = g.run_blocks(g.init_on(snap, mach, g.Image(dk, plain)), frames, BLOCKS, extra_hooks=hooks_p)
        pcs_p = obs.pcs

        # the marked run: the fed clock, the records at each dispatch mark, rows after block 0
        obs2 = Steps(log=False)
        g.fx.OBSERVER = obs2
        init = g.init_on(snap, mach, g.Image(dk, marked))
        g.m2.poke(init.state, L.STATE_DM + 0x18, L.SNAP_EVERY - 1)   # BLOCKS: block 0 closes a SNAP window
        at_dispatch, seen_marked, word2, snapw = [], {}, [], []

        def feed(r):
            r.state.uregs[g.fx.UREG_CODES["R8"]] = g.fx.Const(obs2.n & 0xFFFFFFFF)

        def records(r):
            at_dispatch.append([(g.m2.word(r.state, L.RECORDS_DM + L.RECORD_BYTES * k) or 0,
                                 g.m2.word(r.state, L.RECORDS_DM + L.RECORD_BYTES * k + 4) or 0)
                                for k in range(L.N)])

        def tail(r):
            word2.append([g.m2.word(r.state, a) or 0 for a in L.REPLY_WORD2])
            if not snapw:
                snapw.extend(g.m2.word(r.state, L.SNAP_AT + 4 * k) or 0 for k in range(L.HALVES // 2))

        hooks_m = {after_clock: feed, L.stub_sw(1): records, L.stub_sw(30): tail}
        for t in targets:
            if t not in hooks_m and t not in taken and t != L.stub_sw(4):
                hooks_m.setdefault(t, (lambda r, t=t: seen_marked.setdefault(t, regs(r))))
        run_m = g.run_blocks(init, frames, BLOCKS, extra_hooks=hooks_m)
    g.fx.OBSERVER = None

    checks["both runs end normally"] = run_p["ok"] and run_m["ok"]
    checks["every track buffer, every block, bit for bit"] = run_p["buffer_bits"] == run_m["buffer_bits"]
    checks["registers at every stage's target are the plain run's"] = all(
        seen_marked.get(t) == v for t, v in seen_plain.items() if t in seen_marked)

    # block 2 in the plain run, from its dispatch arrival to block 3's: the arrivals at each
    # target (not by falling through), and the steps from each arrival to the next
    seg_p, pass_p, cur, dispatches = [0] * L.N, [0] * L.N, None, 0
    for i in range(block_start[2], len(pcs_p)):
        pc = pcs_p[i]
        k = targets.get(pc)
        if k is not None and k in site_of and not (0 <= pcs_p[i - 1] - site_of[k] <= 6):
            k = None                                      # the routine, called from somewhere else
        if k is not None and not (0 < pc - pcs_p[i - 1] <= 3):
            if k == 1:
                dispatches += 1
                if dispatches == 2:
                    break
            if dispatches:
                pass_p[k] += 1
                cur = k
        if dispatches and cur is not None:
            seg_p[cur] += 1
    d = [(b[0] - a[0], b[1] - a[1]) for a, b in zip(at_dispatch[2], at_dispatch[3])] if len(at_dispatch) > 3 else []
    if not d:
        print("the marked run did not pass block 3's dispatch mark:", run_m.get("ok"), run_m.get("halt"),
              len(at_dispatch), "dispatch arrivals; plain ok", run_p.get("ok"))
        return 1
    per = d[3][0] // max(1, d[3][1])                      # one mark, in instructions
    print(f"one mark: {per} instructions (the null segment, {d[3][1]} passes)")
    print(f"{'k':>2} {'mark':10s} {'passes':>6s} {'plain':>6s} {'instr':>8s} {'- marks':>8s} {'plain':>8s}")
    exact = True
    for k, m in enumerate(marks):
        cyc, n = d[k]
        net = cyc - n * per
        ok = (n == pass_p[k] and net == seg_p[k]) if m["name"] not in ("null", "publish", "s_tail", "splice") else True
        exact &= ok
        print(f"{k:2d} {m['name']:10s} {n:6d} {pass_p[k]:6d} {cyc:8d} {net:8d} {seg_p[k]:8d} {'' if ok else '  <- differs'}")
    checks["each segment's instructions, less its marks, are the plain run's"] = exact

    checks["SNAP's header: 'LM' | 31, 4096 blocks, SEQ 1"] = snapw[:3] == [L.MAGIC | L.N, L.WINDOW_BLOCKS, 1]
    halves_ok = len(word2) == BLOCKS
    for k, (a, b) in enumerate(word2):
        got = L.decode_half(L.unswap(a))                  # the ColdFire's big-endian read swaps the halves
        want = snapw[k >> 1] >> 16 if k & 1 else snapw[k >> 1] & 0xFFFF
        print(f"block {k}: reply word 2 {a:#010x} {b:#010x} -> {got}")
        halves_ok &= got == (1, k, want)
    checks[f"blocks 0-{BLOCKS - 1}: reply word 2 holds SNAP's halves 0-{BLOCKS - 1}, tagged SEQ 1"] = halves_ok
    checks["both reply pages hold the same word"] = all(a == b for a, b in word2)
    for name, ok in checks.items():
        print(f"{'PASS' if ok else 'FAIL'}  {name}")
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())

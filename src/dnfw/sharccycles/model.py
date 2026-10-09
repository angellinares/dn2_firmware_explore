"""A step stream -> counts of the events the SHARC+ prices.

Each rule below names its source. A count is in one of two units, which
costs.py records per key: events (a branch outcome, a cache miss: priced in
cycles per event) or PRM stall cycles (a dependency at distance d stalls
`cost - (d - 1)` cycles by the tables; the key's cost then scales that, 1.0 by
default). Rules the tables give no number for are counted all the same, so the
instrument can price them.
"""

from __future__ import annotations

import collections

from . import regions
from .btb import BTB
from .cache import Cache
from .events import LOAD, MOVE, Step
from .forms import CALL, CJUMP, DO, JUMP, RFRAME, RTI, RTS

DAG_LOAD_STALL = 4         # PRM Table 4-38 #1 (also 4-40 #3, an indirect branch)
CJUMP_I6_STALL = 6         # PRM Table 4-40 #1, #2
I6 = 6


class Model:
    def __init__(self) -> None:
        self.counts: collections.Counter[str] = collections.Counter()
        self.btb = BTB()
        self.dcache = Cache()                           # the DM data cache
        self.pcache = Cache()                           # the PM data cache: separate, not coherent (fftselftest2)
        self.icache = Cache()
        self.conflict = collections.OrderedDict()      # the 32-entry conflict cache, by pc
        self._n = 0                                     # steps seen
        self._iwrite: dict[int, tuple[int, str]] = {}   # I register -> (step, how)
        self._prev = None                               # the previous Step
        self._frame_at: int | None = None               # step of the last CJUMP / RFRAME

    def feed(self, s: Step) -> None:
        c = self.counts
        n = self._n
        c["instructions"] += 1
        if s.emulated:
            c["emulated"] += 1
        st = s.static
        self._fetch(s)
        self._dag(n, st)
        self._compute(st)
        self._branch(s)
        self._memory(s)
        for reg, how in s.ireg_writes:
            self._iwrite[reg] = (n, how)
        if st.branch in (CJUMP, RFRAME):
            self._frame_at = n
        self._prev = s
        self._n = n + 1

    # -- the rules ---------------------------------------------------------------------

    def _fetch(self, s: Step) -> None:
        r = regions.code_region(s.pc)
        if r in regions.CACHED and not self.icache.access(s.pc * 2):
            self.counts[f"icache_miss_{r}"] += 1
        elif r == "unmapped":
            self.counts["fetch_unmapped"] += 1

    def _dag(self, n: int, st) -> None:
        """PRM Table 4-38 #1 / 4-40 #3: an I register loaded from memory, then used to
        address (or as an indirect branch's target) d instructions later, stalls
        4 - (d - 1). Ix = Rn isn't in the tables: counted apart on the same scale.
        Ix = immediate: no stall (4-38 #4). A DAG's own post-modify: none.
        4-40 #1: CJUMP/RFRAME, then I6 addressing: 6 - (d - 1). Only I6: a call's
        delay slots push through I7, which the table doesn't name (its #2, I6/I7
        read as registers, isn't modelled)."""
        uses = st.dag_uses + ((st.indirect,) if st.indirect is not None else ())
        for reg in set(uses):
            w = self._iwrite.get(reg)
            if w is None:
                continue
            d = n - w[0]
            stall = DAG_LOAD_STALL - (d - 1)
            if stall <= 0:
                continue
            if w[1] == LOAD:
                self.counts["dag_load_use"] += stall
            elif w[1] == MOVE:
                self.counts["dag_move_use"] += stall
        if self._frame_at is not None and I6 in uses:
            stall = CJUMP_I6_STALL - (n - self._frame_at - 1)
            if stall > 0:
                self.counts["cjump_i6_use"] += stall

    def _compute(self, st) -> None:
        """PRM Table 4-36 #1: a float compute or multiply, then a compute reading its
        result: 1. #3: a float multiply, then a fixed-point ALU op reading it
        (the table's number didn't survive the PDF; counted). Anomaly 20000072: a
        float compute into F0, then a single-operand compute (counted)."""
        prev = self._prev
        if prev is None or prev.emulated:
            return
        for p in prev.static.computes:
            if not p.float_op or not p.dests:
                continue
            for c in st.computes:
                if set(p.dests) & set(c.srcs):
                    if p.unit == "mul" and c.unit == "alu" and not c.float_op:
                        self.counts["fwd_fmul_to_fixed"] += 1
                    else:
                        self.counts["fwd_float"] += 1
                if 0 in p.dests and c.single_operand:
                    self.counts["anomaly_20000072"] += 1

    def _branch(self, s: Step) -> None:
        st = s.static
        c = self.counts
        if s.loop_exit:                             # PRM Table 4-41: 11 (E2-active, short,
            c["loop_exit_f1" if s.loop_f1 else "loop_exit"] += 1    # arithmetic); F1-active 0
        if st.branch in (None, DO, RFRAME):
            return
        if st.branch == RTI:
            c["rti"] += 1                           # PRM 4-40 note **: 7
            return
        taken = bool(s.taken)
        conditional = st.conditional and st.branch in (JUMP, CALL, RTS)
        key = self.btb.outcome(s.pc, conditional, taken, masked=s.in_loop)
        if key is not None:
            c[key + ("_db" if st.delayed and key != "br_wrong_nottaken" else "")] += 1

    def _memory(self, s: Step) -> None:
        c = self.counts
        blocks = collections.defaultdict(set)     # L1 block -> its accesses (8-byte pairs)
        for address, kind in [(a, "rd") for a in s.reads] + [(a, "wr") for a in s.writes]:
            r = regions.data_region(address)
            if r in regions.L1:
                # a SIMD or long-word transfer moves a word and the next as one 64-bit
                # access: the runner reports two addresses, the block sees one access
                blocks[r].add(address // 8)
            elif r in regions.CACHED:
                hit = (self.pcache if address in s.pm else self.dcache).access(address)
                c[f"{r}_{'hit' if hit else 'miss'}_{kind}"] += 1
            else:
                c[f"{r}_{kind}"] += 1
        c["l1_same_block"] += sum(len(k) - 1 for k in blocks.values() if len(k) > 1)   # PRM 4-35: 1
        if s.pm_data:
            # PRM 4-35: a PM data access misses the 32-entry conflict cache: 1
            if s.pc in self.conflict:
                self.conflict.move_to_end(s.pc)
            else:
                c["pm_conflict_miss"] += 1
                self.conflict[s.pc] = True
                if len(self.conflict) > 32:
                    self.conflict.popitem(last=False)


def count(steps) -> collections.Counter[str]:
    """STEPS (an iterable of Step) -> the event counts."""
    m = Model()
    for s in steps:
        m.feed(s)
    return m.counts

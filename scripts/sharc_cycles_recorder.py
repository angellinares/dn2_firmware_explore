"""digikit's runner -> dnfw.sharccycles steps: the one place the cycle model meets it.

    with Recorder(fx) as rec:
        ... any fx.run(...) ...
    rec.model.counts            # the event counts (dnfw.sharccycles.model)

While active it is fx.OBSERVER (scripts/sharc_dn2_fixups.py calls before/after
around each instruction). Each instruction's data addresses come from the runner's own
trace events (digikit's tools/sharc_dev/sharc_accesses.py), plus the reads and writes our
fix-ups in sharc_dn2_fixups make themselves, which no event records. Outside an
instruction (a harness tap, a hook) nothing is recorded.

Until 2026-10-25 this wrapped digikit's `_dm_read` / `_dm_write` by module name. The forms
modules import those names directly, and digikit main loads them as
tools.sharc_dev.sharc_core.*, so from 2026-10-21 the wrapper missed most loads and stores
(batcha1's second oscillator read 3,395 estimated cycles a block instead of 4,445).

Per step it works out what the model needs from the runner's state: whether a
branch went (a delayed branch leaves `state.pending` with a target; any other
leaves the pc off its fall-through), whether a hardware loop ended (the loop
stack shrank; F1-active when its DO had the mode bit and the loop ran 11 instructions
or more, PRM "Loop Categorization into F1-Active or E2-Active"), and which I registers got a new value (`uregs` entries replaced:
digikit's handlers build a fresh Value only when they assign), and how.
"""

from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from dnfw.sharccycles import events as ev          # noqa: E402
from dnfw.sharccycles import forms                 # noqa: E402
from dnfw.sharccycles.model import Model           # noqa: E402

try:                                               # digikit main from PR "sharc_accesses"
    from tools.sharc_dev.sharc_accesses import enable as _enable_events      # noqa: E402
    from tools.sharc_dev.sharc_accesses import step_accesses as _step_accesses  # noqa: E402
except ImportError:                                # shortcut: an older digikit checkout; drop when dnfw.sharcemu's has it
    _KINDS = {"load": "r", "load-pey": "r", "store": "w", "store-pey": "w"}
    _WIDTHS = {"byte": 1, "byte-sign-extended": 1, "short-word": 2, "short-word-sign-extended": 2,
               "normal-word": 4, "long-word": 8}

    def _enable_events(state) -> None:
        state.record_events = True

    def _step_accesses(events):
        from types import SimpleNamespace
        for e in events:
            kind, address = _KINDS.get(e.get("action", "")), e.get("address")
            if kind is not None and isinstance(address, int):
                width = 8 if e.get("long_word") else _WIDTHS.get(e.get("access_width", ""), 4)
                yield SimpleNamespace(kind=kind, address=address, width=width)


_I_CODES = tuple(range(16, 32))                    # digikit UREG_CODES I0..I15
_LOAD_FORMS = frozenset({"1a", "1b", "3a", "3b", "3c", "3d", "4a", "4b", "4d", "6a_mem",
                         "10a_rel", "14a", "15a", "15b"})


class Recorder:
    def __init__(self, fx, model: Model | None = None) -> None:
        self.fx = fx
        self.model = model or Model()
        self.skips = 0
        self._static: dict[int, forms.Static] = {}
        self._inside = False
        self._reads: list[int] = []
        self._writes: list[int] = []
        self._saved: list[tuple[object, str, object]] = []
        self._fix_reads: list[int] = []
        self._fix_writes: list[int] = []
        self._runner = None
        self._record_events = True
        self._trace_at = 0
        self._steps = 0
        self._loop_starts: list[tuple[bool, int]] = []   # per active loop: (F1 opcode, first step)

    # -- the context ---------------------------------------------------------------------

    def __enter__(self):
        concrete = sys.modules["sharc_core.memory"]._concrete_address
        rec = self

        def wrap_read(orig):
            def _dm_read(state, address, width, signed=False, **kw):
                if rec._inside:
                    a = concrete(address)
                    if a is not None:
                        rec._fix_reads.append(a)
                return orig(state, address, width, signed, **kw)   # newer digikit adds keywords (normal_word)
            return _dm_read

        def wrap_write(orig):
            def _dm_write(state, address, width, value, **kw):
                if rec._inside:
                    a = concrete(address)
                    if a is not None:
                        rec._fix_writes.append(a)
                return orig(state, address, width, value, **kw)
            return _dm_write

        # only our own fix-ups: the forms' accesses come from the events
        for name, wrap in (("_dm_read", wrap_read), ("_dm_write", wrap_write)):
            orig = getattr(self.fx, name, None)
            if orig is not None:
                self._saved.append((self.fx, name, orig))
                setattr(self.fx, name, wrap(orig))
        self.fx.OBSERVER = self
        return self

    def __exit__(self, *exc):
        self.fx.OBSERVER = None
        for mod, name, orig in reversed(self._saved):
            setattr(mod, name, orig)
        self._saved.clear()
        if self._runner is not None:               # leave the state as found: events off, trace short
            self._runner.state.record_events = self._record_events
            del self._runner.state.trace[:-1]
        return False

    # -- fx.run's calls ------------------------------------------------------------------

    def skipped(self, pc: int) -> None:
        self.skips += 1

    def before(self, runner, insn) -> None:
        st = runner.state
        self._pc = st.pc_sw
        self._insn = insn
        self._loops = len(st.loops)
        self._pending = st.pending
        u = st.uregs
        self._iregs = [u.get(c) for c in _I_CODES]
        if self._runner is not runner:
            self._runner, self._record_events = runner, st.record_events
        if not st.record_events:
            _enable_events(st)
        self._trace_at = len(st.trace)
        self._reads, self._writes = [], []
        self._fix_reads, self._fix_writes = [], []
        self._inside = True

    def after(self, runner, insn, emulated: bool) -> None:
        self._inside = False
        st = runner.state
        for a in _step_accesses(st.trace[self._trace_at:]):
            to = self._reads if a.kind == "r" else self._writes
            to.extend(range(a.address, a.address + max(4, a.width), 4))   # a 64-bit access: its two words
        for got, mine in ((self._reads, self._fix_reads), (self._writes, self._fix_writes)):
            got.extend(x for x in mine if x not in got)                  # a fix-up redoing a form's access
        del st.trace[:-1]                                                # bounded: nothing reads further back
        pc = self._pc
        static = self._static.get(pc)
        if static is None or static.form != insn.type_name:
            static = forms.classify(insn.type_name, insn.length_bytes, insn.fields)
            self._static[pc] = static
        taken = None
        if static.branch in (forms.JUMP, forms.CALL, forms.RTS, forms.RTI, forms.CJUMP):
            if static.delayed:
                p = st.pending
                taken = p is not None and p is not self._pending and p.target is not None
            else:
                taken = st.pc_sw != pc + static.length_sw
        loop_exit = len(st.loops) < self._loops and static.branch is None
        loop_f1 = False
        self._steps += 1
        if len(st.loops) > self._loops:
            self._loop_starts.append((bool(insn.fields.get("mode", 0)), self._steps))
        while len(self._loop_starts) > len(st.loops):
            f1, first = self._loop_starts.pop()
            loop_f1 = f1 and self._steps - first >= 11
        u = st.uregs
        writes = []
        for i, c in enumerate(_I_CODES):
            if u.get(c) is not self._iregs[i]:
                if static.ireg_imm:
                    how = ev.IMM
                elif static.ireg_move:
                    how = ev.MOVE
                elif i in static.dag_uses:
                    how = ev.DAG
                elif self._reads and static.form in _LOAD_FORMS:
                    how = ev.LOAD
                else:
                    how = ev.DAG
                writes.append((i, how))
        pm = ()
        if static.pm_data and (self._reads or self._writes):
            kind, dm_at, pm_at = self.buses(insn)
            pm = tuple(a for a in self._reads + self._writes if self.bus_of(kind, dm_at, pm_at, a) == "PM")
        self.model.feed(ev.Step(pc, static, taken, self._loops > 0, loop_exit,
                                tuple(self._reads), tuple(self._writes), tuple(writes),
                                static.pm_data, emulated, loop_exit and loop_f1, pm))

    # -- which bus moved an address ----------------------------------------------------

    def buses(self, insn) -> tuple[str, int | None, int | None]:
        """Type 1a: ("1a", its DAG1 address, its DAG2 address) as they were before the
        step; a form with a `g` field: "PM" when g is 1; anything else "DM"."""
        f, t = insn.fields, insn.type_name
        if t == "1a":
            dm = self._iregs[f["dmi[2:0]"]]
            pm = self._iregs[8 + ((f["pmi[2:2]"] << 2) | f["pmi[1:0]"])]
            value = lambda v: v.value if hasattr(v, "value") else None
            return "1a", value(dm), value(pm)
        if f.get("g"):
            return "PM", None, None
        return "DM", None, None

    @staticmethod
    def bus_of(kind, dm, pm, address) -> str:
        """Type 1a's DM transfer is at its DAG1 address (and the SIMD companion a word up),
        its PM transfer at its DAG2 address."""
        if kind != "1a":
            return kind
        if dm is not None and 0 <= address - dm <= 7:
            return "DM"
        if pm is not None and 0 <= address - pm <= 7:
            return "PM"
        return "DM"

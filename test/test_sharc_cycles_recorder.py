"""scripts/sharc_cycles_recorder.py takes each step's loads and stores from the runner's events.

The forms modules of digikit's runner import _dm_read and _dm_write by name, so the recorder
used to miss most accesses when it wrapped those names (2026-10-21 to 2026-10-25). It now reads
the trace events the forms record (digikit's tools/sharc_dev/sharc_accesses.py) and keeps the
trace bounded.
"""

from __future__ import annotations

import pathlib
import sys
from types import SimpleNamespace

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))


@pytest.fixture(scope="module")
def fx():
    from dnfw import sharcemu
    try:
        path = sharcemu.path()
    except Exception as exc:                      # noqa: BLE001  (no digikit checkout here)
        pytest.skip(f"no digikit runner: {exc}")
    import sharc_dn2_fixups as fx
    fx.bind(str(path / "tools"))
    return fx


def _step(rec, events):
    state = SimpleNamespace(pc_sw=0x100, loops=[], pending=None, uregs={}, record_events=False,
                            trace=[{"action": "earlier"}])
    runner = SimpleNamespace(state=state)
    insn = SimpleNamespace(type_name="15a", length_bytes=6, fields={"g": 0, "d": 1, "i": 0})
    rec.before(runner, insn)
    assert state.record_events, "the recorder must turn the runner's events on"
    state.trace.extend(events)                    # what the form records while it runs
    rec.after(runner, insn, True)
    return state


def test_a_steps_store_and_load_events_become_its_accesses(fx):
    import sharc_cycles_recorder as cr
    rec = cr.Recorder(fx)
    seen = []
    rec.model = SimpleNamespace(feed=lambda step: seen.append(step), counts={})
    with rec:
        state = _step(rec, [{"action": "store", "space": "DM", "address": 0x2DE6C0, "pc_sw": 0x100},
                            {"action": "load", "space": "DM", "address": 0x94C00000, "long_word": True,
                             "pc_sw": 0x100},
                            {"action": "compute", "pc_sw": 0x100}])
    step = seen[-1]
    assert step.writes == (0x2DE6C0,)
    assert step.reads == (0x94C00000, 0x94C00004)          # a 64-bit access: its two words
    assert len(state.trace) == 1                           # bounded after the step
    assert state.record_events is False                    # restored when the recorder exits


def test_the_forms_modules_are_not_patched(fx):
    import sharc_cycles_recorder as cr
    forms = [m for n, m in sys.modules.items() if m is not None and ".sharc_core.forms_" in n
             and hasattr(m, "_dm_write")]
    before = {id(m): m._dm_write for m in forms}
    with cr.Recorder(fx):
        assert all(m._dm_write is before[id(m)] for m in forms)

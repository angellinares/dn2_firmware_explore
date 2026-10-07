"""csrc/synth, csrc/ui and csrc/dn2 are machine-independent (owner, 2026-10-07: new code in parts any
machine can reuse): nothing in them includes a machine's headers or names its records."""
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]
MACHINES = ("waverider", "lfo4", "wrstore", "usbprobe", "wr_gen")   # dn2/ may include include/dn2_111.h, the OS


def _sources():
    for d in ("synth", "ui", "dn2"):
        yield from sorted((ROOT / "csrc" / d).glob("*.[ch]"))


def test_the_shared_modules_include_no_machine():
    bad = [f"{p.name}: {inc}" for p in _sources()
           for inc in re.findall(r'#include\s+"([^"]+)"', p.read_text())
           if any(m in inc for m in MACHINES)]
    assert not bad, bad


def test_the_shared_modules_name_no_waverider_record():
    bad = [p.name for p in _sources() if re.search(r"\bwr_|\bWR_", p.read_text())]
    assert not bad, bad

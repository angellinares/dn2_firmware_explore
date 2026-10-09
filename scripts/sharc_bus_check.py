"""Which bus touched each cached word: catches a DM read of data written on PM (and back).

    from sharc_bus_check import BusCheck
    with BusCheck(fx) as bus:
        ... fx.run(...) ...
    bus.violations            # [(pc, address, read bus, the bus that wrote it)]

On the SHARC+ the DM and PM data caches are separate and not coherent for cached memory
(DDR, L2): measured on the DN2 2026-10-09, fftselftest2-usbprobe, where fft3 wrote its
first pass on PM and read it back on DM and every result came out 0. The runner has no
caches, so code that breaks this passes there. This keeps, per word of cached memory,
the bus of its last write, and records any read on the other bus.

A step's bus is the recorder's (`Recorder.buses`, `Recorder.bus_of`): Type 1a's DM
transfer is the address in its DAG1 register (and the SIMD companion one word up), the PM
transfer the one in its DAG2 register; a form with a `g` field is PM when g is 1; anything
else DM. L1 is uncached and not tracked.
"""

from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from dnfw.sharccycles import regions                 # noqa: E402
from sharc_cycles_recorder import Recorder           # noqa: E402


class BusCheck(Recorder):
    def __init__(self, fx, keep: int = 20) -> None:
        super().__init__(fx)
        self.writer: dict[int, str] = {}
        self.violations: list[tuple[int, int, str, str]] = []
        self.count = 0
        self.keep = keep

    def after(self, runner, insn, emulated: bool) -> None:
        kind, dm, pm = self.buses(insn)
        for a in self._reads:
            if regions.data_region(a) not in regions.CACHED:
                continue
            bus = self.bus_of(kind, dm, pm, a)
            w = self.writer.get(a & ~3)
            if w is not None and w != bus:
                self.count += 1
                if len(self.violations) < self.keep:
                    self.violations.append((self._pc, a, bus, w))
        for a in self._writes:
            if regions.data_region(a) in regions.CACHED:
                self.writer[a & ~3] = self.bus_of(kind, dm, pm, a)
        super().after(runner, insn, emulated)

    def report(self) -> str:
        if not self.count:
            return "bus check: no cached word read on the other bus than its last write"
        lines = [f"bus check: {self.count} reads of a cached word on the other bus than its last write:"]
        lines += [f"  sw {pc:#x} read {a:#010x} on {b}, written on {w}" for pc, a, b, w in self.violations]
        return "\n".join(lines)

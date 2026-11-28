"""`scripts/emu_pslide.py --coverage`: the pslide chunk's conditional branches, and how often each
way of each ran, read from `panel_drive --count` on the instructions around it (`edges`).
"""

from __future__ import annotations

import collections
import dataclasses
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "scripts")]

from dnfw.image import objdump  # noqa: E402
from dnfw.mods import pslide  # noqa: E402
from emu_pslide_checks import Run  # noqa: E402

CODE = pslide.SPEC["code"]
BLOB, CODE_VA = bytes.fromhex(CODE["blob"]), CODE["va"]
LABELS = pslide.SPEC["labels"]
CONDITIONAL = re.compile(r"b(ne|eq|cs|cc|hi|ls|gt|ge|lt|le|pl|mi|vs|vc)[sbwl]? (0x[0-9a-f]+)")
TRANSFER = re.compile(r"(bra[sbwl]?|bsr[sbwl]?|jmp|jsr) (0x[0-9a-f]+)")


@dataclasses.dataclass
class Flow:
    """The counts `edges` has learned: the ways into each instruction, the instruction counts, and
    each branch's taken and not taken counts so far"""
    ways: dict[int, set]
    hits: dict[int, int]
    branch_at: set[int]
    taken: dict[int, int]
    not_taken: dict[int, int]

    def way(self, kind: str, src: int) -> int | None:
        """How often one way in was taken, or None while that is not known"""
        if kind == "entry":
            return None
        if kind == "branch":
            return self.taken.get(src)
        if kind == "fall" and src in self.branch_at:
            return self.not_taken.get(src)
        return self.hits[src]           # a fall from a plain instruction or a call's return, a jump, a call

    def settle(self, point: tuple[int, int, int]) -> bool:
        """One pass over the branch at POINT: -> whether it learned a count"""
        at, target, after = point
        learned = False
        for mine, pc, me in ((self.taken, target, ("branch", at)), (self.not_taken, after, ("fall", at))):
            others = [self.way(kind, src) for kind, src in self.ways[pc] if (kind, src) != me]
            if at not in mine and None not in others:
                mine[at] = self.hits[pc] - sum(others)
                learned = True
        if (at in self.taken) != (at in self.not_taken):
            known, unknown = (self.taken, self.not_taken) if at in self.taken else (self.not_taken, self.taken)
            unknown[at] = self.hits[at] - known[at]
            learned = True
        return learned


def branches() -> tuple[list[tuple[int, int, int]], dict[int, set]]:
    """The chunk's code up to its data (`sld_bits`): each conditional branch (its address, its
    target, the next instruction), and each instruction's ways in: ("branch" or "fall", from
    address), ("jump" or "call", from address), or ("entry", 0) for a routine that a hook or the
    hook bus enters"""
    code = objdump.disassemble(BLOB[:LABELS["sld_bits"] - CODE_VA], CODE_VA)
    entries = {int(e["new"][4:12], 16) for e in pslide.SPEC["edits"] if e["new"][:4] in ("4ef9", "4eb9")}
    ways: dict[int, set] = collections.defaultdict(set)
    for a in entries | {LABELS["slide_frame"]}:
        ways[a].add(("entry", 0))
    points = []
    for i in code:
        if m := CONDITIONAL.match(i.text):
            points.append((i.address, int(m.group(2), 16), i.end))
            ways[int(m.group(2), 16)].add(("branch", i.address))
            ways[i.end].add(("fall", i.address))
        elif m := TRANSFER.match(i.text):
            ways[int(m.group(2), 16)].add(("call" if m.group(1).startswith(("bsr", "jsr")) else "jump", i.address))
            if m.group(1).startswith(("bsr", "jsr")):
                ways[i.end].add(("fall", i.address))
        elif not i.text.startswith(("rts", "rte", "jmp")):
            ways[i.end].add(("fall", i.address))
    return points, ways


def counted(points: list[tuple[int, int, int]], ways: dict[int, set]) -> list[int]:
    """The instructions `edges` needs counted: each branch, its target and its next instruction, and
    every instruction from which those two are reached"""
    found = {pc for point in points for pc in point}
    for _, target, after in points:
        found |= {src for pc in (target, after) for kind, src in ways[pc] if kind != "entry"}
    return sorted(found)


def loop_tests(points: list[tuple[int, int, int]]) -> dict[int, tuple[int, int]]:
    """The tests of an empty count before a counted loop, which flow alone cannot split: a branch A
    on a data register's zero whose next instruction starts a loop that a `subq.l #1` of the same
    register and a branch B back close, B's next instruction being A's target. -> {A: (B, the
    register)}"""
    code = {i.address: i for i in objdump.disassemble(BLOB[:LABELS["sld_bits"] - CODE_VA], CODE_VA)}
    before = {i.end: i for i in code.values()}
    found = {}
    for at, target, after in points:
        test = before[at].text
        if not CONDITIONAL.match(code[at].text).group(1) == "eq" or not (m := re.search(r"%d(\d)$", test)):
            continue
        for back, loop_head, past in points:
            if loop_head == after and past == target and before[back].text == f"subql #1,%d{m.group(1)}":
                found[at] = (back, int(m.group(1)))
    return found


def seeds(loops: dict[int, tuple[int, int]], runs: list[Run]) -> tuple[dict[int, int], dict[int, int]]:
    """From each loop test's register at the test: the (taken, not taken) counts of the test and of
    its loop's branch back (a count of 0 skips the loop, n runs it n times and branches back n - 1).
    Exact only when no run dropped a logged hit"""
    taken: dict[int, int] = {}
    not_taken: dict[int, int] = {}
    for at, (back, reg) in loops.items():
        values = [d[reg] for run in runs for pc, d in run.regs if pc == at]
        taken[at], not_taken[at] = sum(v == 0 for v in values), sum(v > 0 for v in values)
        taken[back], not_taken[back] = sum(v - 1 for v in values if v > 0), not_taken[at]
    return taken, not_taken


def edges(points: list[tuple[int, int, int]], ways: dict[int, set], hits: dict[int, int],
          seeded: tuple[dict[int, int], dict[int, int]] = ({}, {})) -> dict[int, tuple[int | None, int | None]]:
    """Each branch's (taken, not taken) counts, by the flow into its target and its next
    instruction: an instruction runs as often as the ways into it are taken, so one way is the
    instruction's count less the others', and taken plus not taken is the branch's count. Repeated
    until nothing more follows. None where a way stays mixed with one that is not counted (a routine
    that a hook enters as well as code in the chunk)"""
    flow = Flow(ways, hits, {at for at, _, _ in points}, dict(seeded[0]), dict(seeded[1]))
    while any([flow.settle(point) for point in points]):
        pass
    return {at: (flow.taken.get(at), flow.not_taken.get(at)) for at, _, _ in points}

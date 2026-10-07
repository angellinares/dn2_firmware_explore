"""The SHARC+ branch target buffer: what each branch's prediction comes to.

Programming Reference, "Branch Predictor": 256 entries as 2 ways x 128 sets, LRU,
a 2-bit saturating counter per entry, enabled from reset (EE-375). A branch not
in the buffer is fetched past, i.e. predicted not taken. EE-375 Table 7 prices
the outcomes; its PDF text comes out with shifted columns, so this is our
reading of it, and the costs it names are in costs.py:

  conditional, predicted taken, taken            br_taken_ok       2 / 0 (DB)
  conditional, predicted not taken, not taken    (nothing)         0
  conditional, predicted taken, not taken        br_wrong_nottaken 11
  conditional, predicted not taken, taken        br_wrong_taken    11 / 9
  unconditional, in the buffer                   br_uncond_hit     2 / 0
  unconditional, not in the buffer               br_uncond_miss    6 / 4

EE-375 Table 8: prediction is masked while a hardware loop runs, so there every
branch costs what a miss does.
"""

from __future__ import annotations


class BTB:
    def __init__(self, sets: int = 128, ways: int = 2) -> None:
        self.sets, self.ways = sets, ways
        self._sets: list[list[list[int]]] = [[] for _ in range(sets)]   # [pc, counter], recent last

    def _entry(self, pc: int):
        for e in self._sets[pc % self.sets]:
            if e[0] == pc:
                return e
        return None

    def outcome(self, pc: int, conditional: bool, taken: bool, masked: bool = False) -> str | None:
        """The cost key of the branch at PC that went TAKEN (or not), updating the
        buffer; None when it costs nothing."""
        e = None if masked else self._entry(pc)
        predicted = e is not None and e[1] >= 2
        if not masked:
            self._update(pc, e, taken)
        if not conditional:
            return "br_uncond_hit" if e is not None else "br_uncond_miss"
        if predicted and taken:
            return "br_taken_ok"
        if predicted and not taken:
            return "br_wrong_nottaken"
        if taken:
            return "br_wrong_taken"
        return None

    def _update(self, pc: int, e, taken: bool) -> None:
        ways = self._sets[pc % self.sets]
        if e is None:
            if not taken:
                return
            if len(ways) == self.ways:
                ways.pop(0)
            e = [pc, 2]
            ways.append(e)
            return
        ways.remove(e)
        ways.append(e)
        e[1] = min(3, e[1] + 1) if taken else max(0, e[1] - 1)

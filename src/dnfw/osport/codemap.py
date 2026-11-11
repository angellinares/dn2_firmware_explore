"""Map addresses from one OS version's MAIN OS to another's (issue #382: 1.11 to 1.12).

Elektron relinks MAIN OS between versions. Most code only moves, but every absolute address in it
changes with the move, so the bytes differ even where the code does not. The map follows the method
the digitone-2-modding-skill describes for Overtone (MIT, references/firmware.md):

1. Decode both images into instructions with digikit's ColdFire-aware decoder
   (tools/coldfire/disasm.py: Capstone plus MVS/MVZ and FF1, which Capstone cannot read).
2. Give each instruction a key: its mnemonic and its operands, with every value that can be an
   address masked. A relinked instruction keeps its key.
3. Anchors: runs of RUN keys that occur once in each image. They give the code map.
4. Votes: in each anchored pair, an old operand value and its new value are one vote for the data
   map (constants, tables, BSS).

An address is then one of:
- `exact`: inside an anchored instruction;
- `bracketed`: between two anchors that moved by the same amount;
- `ambiguous`: between anchors that moved by different amounts (the code there changed);
- `none`: no anchor near enough.
A translated address is a candidate. A site is checked by its bytes before anything patches it.
"""

from __future__ import annotations

import bisect
import collections
import os
import pathlib
import re
import sys
from dataclasses import dataclass

BASE = 0x40000400
RUN = 10                       # instructions in an anchor (Overtone's method)
REACH = 0x4000                 # how far a bracketed translation may reach from its anchors
HEX = re.compile(r"\$([0-9a-fA-F]+)")
MIN_ADDRESS = 0x10000          # smaller values are displacements, counts and masks


def _digikit_disasm():
    root = pathlib.Path(os.environ.get("DNFW_DIGIKIT", "D:/01_Code/Z_Personal/digikit-main"))
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    from tools.coldfire.disasm import disasm     # noqa: E402  (digikit, AGPL-3.0)
    return disasm


@dataclass(frozen=True)
class Insn:
    address: int
    size: int
    key: str
    values: tuple[int, ...]     # the masked operand values, in order


def masked(mnemonic: str, operands: str) -> tuple[str, tuple[int, ...]]:
    """The instruction's key and the values masked out of it"""
    values: list[int] = []

    def mask(m: re.Match) -> str:
        v = int(m.group(1), 16)
        if v < MIN_ADDRESS:
            return m.group(0)
        values.append(v)
        return "$A"
    return f"{mnemonic} {HEX.sub(mask, operands)}", tuple(values)


def decode(image: bytes, end: int) -> list[Insn]:
    """Every instruction from BASE to END (the end of code)"""
    disasm = _digikit_disasm()
    out = []
    for address, hexbytes, mnemonic, operands in disasm(image, BASE, BASE, end):
        key, values = masked(mnemonic, operands)
        out.append(Insn(address, len(hexbytes) // 2, key, values))
    return out


@dataclass
class CodeMap:
    old: list[Insn]
    new: list[Insn]
    pairs: list[tuple[int, int]]           # (old index, new index) of anchored instructions
    votes: dict[int, collections.Counter]  # old operand value -> Counter of new values

    @classmethod
    def build(cls, old: list[Insn], new: list[Insn], run: int = RUN) -> "CodeMap":
        def grams(insns):
            seen: dict[tuple, list[int]] = collections.defaultdict(list)
            keys = [i.key for i in insns]
            for k in range(len(keys) - run + 1):
                seen[tuple(keys[k:k + run])].append(k)
            return seen
        a, b = grams(old), grams(new)
        pairs: dict[int, int] = {}
        for gram, where in a.items():
            if len(where) == 1 and len(b.get(gram, ())) == 1:
                i, j = where[0], b[gram][0]
                for d in range(run):
                    pairs.setdefault(i + d, j + d)
        ordered = sorted(pairs.items())
        votes: dict[int, collections.Counter] = collections.defaultdict(collections.Counter)
        for i, j in ordered:
            for v, w in zip(old[i].values, new[j].values):
                votes[v][w] += 1
        return cls(old, new, ordered, votes)

    def coverage(self) -> float:
        return len(self.pairs) / max(len(self.old), 1)

    def translate(self, address: int) -> tuple[int | None, str]:
        """(new address or None, how sure)"""
        starts = [self.old[i].address for i, _ in self.pairs]
        k = bisect.bisect_right(starts, address) - 1
        if k >= 0:
            i, j = self.pairs[k]
            o = self.old[i]
            if o.address <= address < o.address + o.size:
                return self.new[j].address + (address - o.address), "exact"
        before = self.pairs[k] if k >= 0 else None
        after = self.pairs[k + 1] if k + 1 < len(self.pairs) else None
        shift = lambda p: self.new[p[1]].address - self.old[p[0]].address       # noqa: E731
        near = lambda p: abs(self.old[p[0]].address - address) <= REACH          # noqa: E731
        if before and after and near(before) and near(after):
            if shift(before) == shift(after):
                return address + shift(before), "bracketed"
            return None, "ambiguous"
        return None, "none"

    def data(self, value: int) -> tuple[int | None, str]:
        """The new value of an old operand value, by the votes: (value, 'votes N/M') or (None, why)"""
        c = self.votes.get(value)
        if not c:
            return None, "no votes"
        (best, n), total = c.most_common(1)[0], sum(c.values())
        return (best, f"votes {n}/{total}") if n * 2 > total else (None, f"split {dict(c)}")

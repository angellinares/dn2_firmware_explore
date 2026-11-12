"""Every MAIN OS address the mods use, through the 1.11 -> 1.12 map (issue #382).

    python scripts/osport_survey.py OLD_MAIN_OS.bin NEW_MAIN_OS.bin DECODED_CACHE [--list]

The sources: each mod's `*_code.json` (edits and guards), `csrc/include/dn2_111.h` and the 0x4....... literals
in each mod's Python. An address in the image is code: the map translates it. An address past the image
(BSS, heap, stock's data) is data: the votes translate it. Mod RAM (0x466c0000 and up) is not stock's and
is left out. Per mod: how many the map decides, and which it cannot.
"""
import collections
import json
import pathlib
import pickle
import re
import sys

from dnfw.osport import codemap as C

ROOT = pathlib.Path(__file__).resolve().parent.parent
IMAGE_END_111 = 0x4030B980
MOD_RAM = 0x466B8000                       # stock's DMA section and the mods' RAM start here on 1.11
LIT = re.compile(r"0x(4[0-9A-Fa-f]{7})\b")


def sources():
    """(owner, address, what, stock bytes or None) for every address named"""
    mods = ROOT / "src/dnfw/mods"
    for js in sorted(mods.glob("*_code.json")):
        spec = json.loads(js.read_text())
        owner = js.stem.replace("_code", "")
        for e in spec.get("edits", []):
            yield owner, e["va"], "edit", bytes.fromhex(e["stock"]) if e.get("stock") else None
        for g in spec.get("guards", []):
            yield owner, g["va"], "guard", bytes.fromhex(g["bytes"]) if g.get("bytes") else None
    for py in sorted(mods.glob("*.py")):
        for m in LIT.finditer(py.read_text(encoding="utf-8")):
            yield py.stem, int(m.group(1), 16), "literal", None
    h = ROOT / "csrc/include/dn2_111.h"
    for m in LIT.finditer(h.read_text(encoding="utf-8")):
        yield "dn2_111.h", int(m.group(1), 16), "header", None


def mapped(v, m, d):
    """An old address word's new value, by the code map, the data map or the votes"""
    for f in (m.data, m.translate, d.translate):         # votes first: they are measured operand pairs
        got, _ = f(v)
        if got is not None:
            return got
    return None


def relocated(stock: bytes, here: bytes, m, d, lo: int = 0, hi: int | None = None) -> str:
    """'relocated' when every differing byte in [LO, HI) lies in an address word (which may reach into the
    margins) whose old value maps to its new value, else 'BYTES DIFFER'"""
    if len(here) != len(stock):
        return "BYTES DIFFER"
    n = len(stock)
    hi = n if hi is None else hi
    i = lo
    while i < hi:
        if stock[i] == here[i]:
            i += 1
            continue
        for start in range(max(0, i - 3), i + 1):            # the address word that covers byte i
            if start + 4 <= n:
                old_w = int.from_bytes(stock[start:start + 4], "big")
                new_w = int.from_bytes(here[start:start + 4], "big")
                if 0x40000000 <= old_w < 0x50000000 and mapped(old_w, m, d) == new_w:
                    i = start + 4
                    break
        else:
            return "BYTES DIFFER"
    return "relocated"


def main() -> int:
    old_img, new_img = (pathlib.Path(p).read_bytes() for p in sys.argv[1:3])
    old, new = pickle.loads(pathlib.Path(sys.argv[3]).read_bytes())
    m = C.CodeMap.build(old, new)
    d = C.DataMap.build(old_img, new_img, 0x401D0400, IMAGE_END_111, 0x401D0810, IMAGE_END_111 + 0x1000)
    checked = collections.Counter()
    per = collections.defaultdict(collections.Counter)
    undecided = collections.defaultdict(list)
    seen = set()
    for owner, a, what, stock in sources():
        if (owner, a) in seen or a >= MOD_RAM:
            continue
        seen.add((owner, a))
        if a < 0x401D0400:
            got, how = m.translate(a)
        elif a < IMAGE_END_111:
            got, how = d.translate(a)
            if got is None:
                got, how = m.data(a)
        else:
            got, how = m.data(a)
        if got is not None and stock:             # the site's stock bytes must be at the new address
            o, g = a - C.BASE, got - C.BASE
            if old_img[o:o + len(stock)] != stock:
                kind = "BYTES DIFFER"                 # the mod's own record of stock is wrong
            elif new_img[g:g + len(stock)] == stock:
                kind = "bytes match"
            else:                                     # 3 bytes either side: an edit may cover part of an operand
                kind = relocated(old_img[o - 3:o + len(stock) + 3], new_img[g - 3:g + len(stock) + 3], m, d,
                                 3, 3 + len(stock))
            here = new_img[g:g + len(stock)]
            checked[kind] += 1
            if kind == "BYTES DIFFER":
                undecided[owner].append((a, what, f"-> {got:#x} but bytes {here.hex()} != {stock.hex()}"))
        per[owner]["decided" if got is not None else "undecided"] += 1
        if got is None:
            undecided[owner].append((a, what, how))
    total = collections.Counter()
    for owner in sorted(per):
        c = per[owner]
        total.update(c)
        print(f"{owner:18} decided {c['decided']:4}  undecided {c['undecided']:4}")
    print(f"{'all':18} decided {total['decided']:4}  undecided {total['undecided']:4}")
    print(f"edit and guard sites decided: {dict(checked)}")
    if "--list" in sys.argv:
        for owner in sorted(undecided):
            for a, what, how in undecided[owner]:
                print(f"  {owner:18} {a:#010x} {what:8} {how[:70]}")
    print("OSPORT SURVEY DONE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Every MAIN OS address the mods use, through the 1.11 -> 1.12 map (issue #382).

    python scripts/osport_survey.py OLD_MAIN_OS.bin NEW_MAIN_OS.bin DECODED_CACHE [--list] [--write]

--write saves every decided address to src/dnfw/osport/map_1.12.json, which the generators read
through dnfw.osport.addr (addresses and how each was decided; no firmware bytes).

The sources: each mod's `*_code.json` (edits and guards), `csrc/include/dn2_111.h` and the 0x4....... literals
in each mod's Python and the generators' `scripts/build_*.py`. An address in the image is code: the map translates it. An address past the image
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
    for py in sorted((ROOT / "scripts").glob("build_*.py")):   # the generators' own hook and guard addresses
        for m in LIT.finditer(py.read_text(encoding="utf-8")):
            yield py.stem, int(m.group(1), 16), "build", None
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


def kind_of(stock, got, a, old_img, new_img, m, d) -> str:
    """How an edit or guard site's stock bytes stand at its new address (None for an address with no
    stock bytes): 'bytes match', 'relocated' or 'BYTES DIFFER'"""
    if not stock:
        return None
    o, g = a - C.BASE, got - C.BASE
    if old_img[o:o + len(stock)] != stock:
        return "BYTES DIFFER"                        # the mod's own record of stock is wrong
    if new_img[g:g + len(stock)] == stock:
        return "bytes match"
    # 3 bytes either side: an edit may cover part of an operand
    return relocated(old_img[o - 3:o + len(stock) + 3], new_img[g - 3:g + len(stock) + 3], m, d, 3, 3 + len(stock))


def main() -> int:
    old_img, new_img = (pathlib.Path(p).read_bytes() for p in sys.argv[1:3])
    old, new = pickle.loads(pathlib.Path(sys.argv[3]).read_bytes())
    m = C.CodeMap.build(old, new)
    d = C.DataMap.build(old_img, new_img, 0x401D0400, IMAGE_END_111, 0x401D0810, IMAGE_END_111 + 0x1000)
    checked = collections.Counter()
    per = collections.defaultdict(collections.Counter)
    undecided = collections.defaultdict(list)
    seen = set()
    decided: dict[int, dict] = {}
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
            kind = kind_of(stock, got, a, old_img, new_img, m, d)
            checked[kind] += 1
            if kind == "BYTES DIFFER":
                undecided[owner].append((a, what, f"-> {got:#x}: bytes differ"))
        check = kind_of(stock, got, a, old_img, new_img, m, d) if got is not None else None
        if got is not None and check != "BYTES DIFFER":
            row = decided.setdefault(a, {"new": got, "how": how, "check": None, "users": []})
            row["users"].append(f"{owner}:{what}")
            row["check"] = row["check"] or check
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
    if "--write" in sys.argv:
        out = ROOT / "src/dnfw/osport/map_1.12.json"
        rows = {f"0x{a:08x}": {"new": f"0x{r['new']:08x}", "how": r["how"], "check": r["check"],
                               "users": sorted(set(r["users"]))} for a, r in sorted(decided.items())}
        out.write_text(json.dumps({"from": "1.11", "to": "1.12", "addresses": rows}, indent=1) + chr(10),
                       encoding="utf-8", newline=chr(10))
        print(f"wrote {out.relative_to(ROOT)}: {len(rows)} addresses")
    if "--list" in sys.argv:
        for owner in sorted(undecided):
            for a, what, how in undecided[owner]:
                print(f"  {owner:18} {a:#010x} {what:8} {how[:70]}")
    print("OSPORT SURVEY DONE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

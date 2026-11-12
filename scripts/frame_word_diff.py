"""Which frame words does one OS's ColdFire write that another's does not? Two corpora from frame_corpus.py.

    python scripts/frame_word_diff.py OLD_CORPUS NEW_CORPUS [--words 0xa18,0x9a8]

Issue #382, phase 0 step 7. The DSP program is byte-identical in OS 1.11 and 1.12, so its readers
(sharc_frame_census.py) do not change. What can change is what the ColdFire writes: a word that one
OS leaves at zero, and that a mod therefore uses, may carry stock data in the other. naturarum's
report on issue #49 found such a word on 1.11 (0xa54 and 0xa56 under Waverider's song position).

Per 16-bit frame word, over every frame of each corpus: how many frames hold a non-zero value, and
how many distinct values. A word is "written" in a corpus when any frame holds it non-zero.
Reported: words written in NEW and never in OLD, and the reverse, and each --words word in both.
The corpus sets must be the same scenarios (frame_corpus.py's machines and patterns) for the
comparison to mean anything; the script says how many frames each holds.
"""
import argparse
import collections
import pathlib
import sys

FRAME = 2688


def census(root: pathlib.Path) -> tuple[int, dict[int, collections.Counter]]:
    files = sorted(root.rglob("*.frame_be.bin"))
    seen: dict[int, collections.Counter] = collections.defaultdict(collections.Counter)
    for f in files:
        b = f.read_bytes()
        if len(b) != FRAME:
            continue
        for off in range(0, FRAME, 2):
            seen[off][int.from_bytes(b[off:off + 2], "big")] += 1
    return len(files), seen


def written(seen: dict[int, collections.Counter]) -> set[int]:
    return {off for off, c in seen.items() if any(v for v in c)}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("old", type=pathlib.Path)
    ap.add_argument("new", type=pathlib.Path)
    ap.add_argument("--words", default="")
    a = ap.parse_args()
    n_old, old = census(a.old)
    n_new, new = census(a.new)
    print(f"frames: old {n_old}, new {n_new}")
    w_old, w_new = written(old), written(new)
    print(f"words written: old {len(w_old)}, new {len(w_new)} of {FRAME // 2}")
    for name, words, src in (("written in NEW only", sorted(w_new - w_old), new),
                             ("written in OLD only", sorted(w_old - w_new), old)):
        print(f"{name}: {len(words)}")
        for off in words:
            c = src[off]
            nz = sum(n for v, n in c.items() if v)
            top = ", ".join(f"{v:#06x} x{n}" for v, n in c.most_common(4))
            print(f"  {off:#06x}: non-zero in {nz} frames, {len(c)} values ({top})")
    for w in [int(x, 0) for x in a.words.split(",") if x]:
        for name, src, n in (("old", old, n_old), ("new", new, n_new)):
            c = src.get(w, collections.Counter())
            nz = sum(k for v, k in c.items() if v)
            print(f"  word {w:#06x} {name}: non-zero in {nz} of {n} frames, values {dict(c.most_common(4))}")
    print("FRAME WORD DIFF DONE")
    return 0


if __name__ == "__main__":
    sys.exit(main())

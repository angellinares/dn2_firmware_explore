"""What a project's licence lets this repository do with its code (dnfw.licencecheck).

    python tools/licence_check.py PATH [PATH ...] [--json]
    python tools/licence_check.py --all DIR [--json]

PATH is a local checkout. --all checks each folder in DIR and prints one line for each. Exit status:
0 all COPY, 1 any NO, 2 any OWNER or ASK and no NO.
"""
from __future__ import annotations

import argparse
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

from dnfw import licencecheck as L  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("paths", nargs="*", type=pathlib.Path)
    ap.add_argument("--all", type=pathlib.Path, help="check every folder in this directory")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if not a.paths and not a.all:
        ap.error("give a PATH or --all DIR")
    paths = list(a.paths)
    if a.all:
        paths += sorted(p for p in a.all.iterdir() if p.is_dir())
    results = [L.check(p) for p in paths]
    if a.json:
        print(L.as_json(results))
    elif a.all:
        for r in results:
            print(f"{r.verdict:6} {r.licence:20} {pathlib.Path(r.path).name}")
    else:
        print("\n\n".join(L.render(r) for r in results))
    return 1 if any(r.verdict == L.NO for r in results) else max(L.EXIT[r.verdict] for r in results)


if __name__ == "__main__":
    raise SystemExit(main())

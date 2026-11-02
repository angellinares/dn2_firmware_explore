"""The checkout under test: which code runs, and which resources it has.

    python -m dnfw.checkout          the checkout of the current folder (git's top level): print the
                                     report; exit 1 when dnfw runs from another checkout

A worktree or a second clone of this repository has its own `src/`. A test that starts a new
Python (`python -c "... dnfw.cli.main ..."`, as the build tests do) imports `dnfw` from whatever
`PYTHONPATH` names. Without it set, that is the main checkout's code, and the result describes the
wrong code (trwr2f, 2026-10-24: a worktree build used the main checkout's old code). Missing
`00_Resources` folders make tests skip, or read another checkout's files.

So a run states its checkout, and refuses when `dnfw` (in this process or in a child process)
comes from outside it. `test/conftest.py` puts this checkout's `src` first in `PYTHONPATH` and
prints the report in the pytest header.
"""

from __future__ import annotations

import os
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
RESOURCES = "00_Resources"


def child_dnfw(env: dict[str, str] | None = None) -> pathlib.Path | None:
    """-> where a new Python started with ENV (default: this process's) imports dnfw from."""
    r = subprocess.run([sys.executable, "-c", "import dnfw; print(dnfw.__file__)"],
                       capture_output=True, text=True, env=env, timeout=60)
    out = r.stdout.strip()
    return pathlib.Path(out).resolve() if r.returncode == 0 and out else None


def _inside(path: pathlib.Path | None, root: pathlib.Path) -> bool:
    """PATH is ROOT's own src/dnfw. Not "somewhere under ROOT": a worktree under
    ROOT/.claude/worktrees is under ROOT too, and its dnfw is not ROOT's."""
    return path is not None and path.resolve().parent == (root / "src" / "dnfw").resolve()


def report(root: pathlib.Path = ROOT, env: dict[str, str] | None = None) -> dict:
    """The facts of the checkout: its folder, where dnfw comes from here and in a child process,
    the 00_Resources folders present, whether out/ exists, and the progress folder."""
    import dnfw
    from dnfw import progress

    here = pathlib.Path(dnfw.__file__).resolve()
    child = child_dnfw(env)
    res = root / RESOURCES
    return {
        "checkout": root.resolve(),
        "dnfw": here,
        "dnfw_child": child,
        "inside": _inside(here, root),
        "inside_child": _inside(child, root),
        "resources": sorted(p.name for p in res.iterdir() if p.is_dir()) if res.is_dir() else [],
        "out": (root / "out").is_dir(),
        "progress": progress.DIR,
    }


def problems(r: dict) -> list[str]:
    """-> what makes a result from this checkout untrustworthy (empty when none)."""
    out = []
    if not r["inside"]:
        out.append(f"dnfw runs from {r['dnfw']}, outside the checkout {r['checkout']}")
    if not r["inside_child"]:
        out.append(f"a child process imports dnfw from {r['dnfw_child']}, outside the checkout "
                   f"{r['checkout']}: set PYTHONPATH={r['checkout'] / 'src'}")
    return out


def lines(r: dict) -> list[str]:
    """-> the report as short lines, for a pytest header or a sweep report."""
    return [f"checkout: {r['checkout']} (dnfw {'here' if r['inside'] else r['dnfw']}, "
            f"child {'here' if r['inside_child'] else r['dnfw_child']})",
            f"00_Resources: {', '.join(r['resources']) or 'none'}; out/: {'yes' if r['out'] else 'no'}",
            f"progress: {r['progress']}"]


def with_src_first(env: dict[str, str], root: pathlib.Path = ROOT) -> dict[str, str]:
    """ENV with ROOT/src first in PYTHONPATH, so child processes import this checkout's dnfw."""
    src = str(root / "src")
    parts = [p for p in env.get("PYTHONPATH", "").split(os.pathsep) if p and p != src]
    return {**env, "PYTHONPATH": os.pathsep.join([src, *parts])}


def toplevel(cwd: pathlib.Path | None = None) -> pathlib.Path:
    """-> the git checkout that holds CWD (default: the current folder), or ROOT outside git"""
    r = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True,
                       cwd=cwd, timeout=30)
    return pathlib.Path(r.stdout.strip()).resolve() if r.returncode == 0 and r.stdout.strip() else ROOT


def main() -> int:
    r = report(toplevel())
    for line in lines(r):
        print(line)
    bad = problems(r)
    for p in bad:
        print("refuse:", p)
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())

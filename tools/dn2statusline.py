"""Claude Code's status line for this project: the owner's own three rows, then one row of jobs.

Set in .claude/settings.local.json (statusLine, type command). Claude Code passes its
session JSON on stdin; this hands it unchanged to the user's status line script
(C:/Users/A/.claude/statusline.js, or DNFW_STATUSLINE_BASE), prints what it prints, and
adds one row from out/progress/ (dnfw.progress): the newest running job, its percentage,
time and step, and how many more are running. The row is always there, "no jobs" when
idle, so the prompt doesn't move when a job starts (the base script keeps a fixed height
for the same reason).
"""
from __future__ import annotations

import os
import pathlib
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))

BASE = os.environ.get("DNFW_STATUSLINE_BASE", "C:/Users/A/.claude/statusline.js")
C, D, G, R, Y, X = "\x1b[36m", "\x1b[90m", "\x1b[32m", "\x1b[31m", "\x1b[33m", "\x1b[0m"


def base_rows(stdin: bytes) -> str:
    if not pathlib.Path(BASE).exists():
        return ""
    try:
        r = subprocess.run(["node", BASE], input=stdin, capture_output=True, timeout=3)
        return r.stdout.decode("utf-8", "replace").rstrip("\n")
    except (OSError, subprocess.SubprocessError):
        return ""


def job_row() -> str:
    try:
        from dnfw import progress  # noqa: PLC0415
        items = progress.jobs()
    except Exception as e:  # noqa: BLE001 -- a status line must never fail
        return f"{D}jobs: {type(e).__name__}{X}"
    running = [d for d in items if d["state"] == "running"]
    if not running:
        last = next((d for d in items if d["state"] in ("done", "failed", "lost")), None)
        if last:
            col = {"done": G, "failed": R, "lost": Y}[last["state"]]
            return f"{D}no jobs · last:{X} {col}{last['name']} {last['state']}{X}"
        return f"{D}no jobs{X}"
    leaves = [d for d in running if not any(o.get("parent") == d["id"] for o in running)]
    d = max(leaves or running, key=lambda d: d.get("started", 0))
    names = [d["name"]]
    parent = next((o for o in running if o["id"] == d.get("parent")), None)
    if parent:
        names.insert(0, parent["name"])
    pct = f" {d['percent']:.0f}%" if d["percent"] is not None else ""
    step = f" · {d['step']}" if d.get("step") else ""
    more = len(running) - len(names)
    return (f"{C}▶ {' › '.join(names)}{X}{pct} · {progress.clock(d['elapsed'])}{step[:70]}"
            + (f" {D}(+{more} more){X}" if more > 0 else ""))


def main() -> int:
    stdin = sys.stdin.buffer.read() if not sys.stdin.isatty() else b"{}"
    rows = base_rows(stdin)
    out = (rows + "\n" if rows else "") + job_row()
    sys.stdout.buffer.write(out.encode("utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

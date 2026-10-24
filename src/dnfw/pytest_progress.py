"""A pytest run as a `dnfw.progress` job, so the pane and the status line show it while it runs.

pytest prints its result at the end, and a run under `python -m dnfw.progress run` shows only
that last line. With this plugin the run is a job of its own: done / total are the tests,
the step is the test running now, and the detail is the tally so far ("41 passed, 1 failed,
3 skipped"). Under `dnfw.progress run` the job shows as that command's child.

A slow fixture or loop inside a test reports its own stage with `stage`, a child job of the
run:

    from dnfw.pytest_progress import stage
    with stage("CLI builds", total=len(orders)) as s:
        for order in orders:
            s.advance(step="-".join(order))
            ...

`test/conftest.py` loads the hooks. Set DNFW_PYTEST_PROGRESS=0 to turn them off.
"""

from __future__ import annotations

import os
import pathlib

from . import progress

_run: progress.Job | None = None
_tally = {"passed": 0, "failed": 0, "skipped": 0, "error": 0}


def _on() -> bool:
    return os.environ.get("DNFW_PYTEST_PROGRESS", "1") != "0"


def _detail() -> str:
    return ", ".join(f"{n} {k}" for k, n in _tally.items() if n) or "starting"


def stage(name: str, total: int | None = None) -> progress.Job:
    """A child job of the test run (a plain job when there is no run)."""
    return progress.Job(name, total=total)


def pytest_collection_finish(session) -> None:
    global _run
    if not _on() or session.config.option.collectonly:
        return
    args = " ".join(pathlib.Path(a.split("::")[0]).name for a in session.config.args)[:60] or "test/"
    _run = progress.Job(f"pytest {args}", total=len(session.items))
    _run.__enter__()


def pytest_runtest_logstart(nodeid, location) -> None:
    if _run:
        _run.update(step=nodeid.split("::", 1)[-1][:80], detail=_detail())


def pytest_runtest_logreport(report) -> None:
    if not _run:
        return
    if report.when == "call":
        _tally["passed" if report.passed else "skipped" if report.skipped else "failed"] += 1
    elif report.failed:                                 # setup or teardown
        _tally["error"] += 1
    elif report.when == "setup" and report.skipped:
        _tally["skipped"] += 1


def pytest_runtest_logfinish(nodeid, location) -> None:
    if _run:
        _run.advance(detail=_detail())


def pytest_sessionfinish(session, exitstatus) -> None:
    global _run
    if not _run:
        return
    _run.update(detail=_detail(), state="done" if exitstatus == 0 else "failed", force=True)
    _run.__exit__(None, None, None)
    _run = None

"""A pytest run shows in the progress pane (dnfw.pytest_progress, owner 2026-10-24).

A small run in a subprocess, with its own progress folder: one test passes, one fails, one
skips, and one opens a stage. Its job files then hold the run (3 of 3... done, the tally,
failed) and the stage as the run's child.
"""

import json
import os
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent

TESTS = '''
import pytest
from dnfw.pytest_progress import stage

def test_passes():
    with stage("a slow part", total=2) as s:
        s.advance(step="one")
        s.advance(step="two")

def test_fails():
    assert False

def test_skips():
    pytest.skip("no corpus")
'''

CONFTEST = '''
from dnfw.pytest_progress import (pytest_collection_finish, pytest_runtest_logfinish,
    pytest_runtest_logreport, pytest_runtest_logstart, pytest_sessionfinish)
'''


def test_a_run_writes_its_job_and_its_stage(tmp_path):
    (tmp_path / "test_three.py").write_text(TESTS, encoding="utf-8")
    (tmp_path / "conftest.py").write_text(CONFTEST, encoding="utf-8")
    jobs = tmp_path / "progress"
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src"), "DNFW_PROGRESS_DIR": str(jobs)}
    env.pop("DNFW_PROGRESS_PARENT", None)
    done = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", str(tmp_path)],
                          capture_output=True, text=True, cwd=tmp_path, env=env)
    assert done.returncode == 1, done.stdout[-600:]
    found = [json.loads(p.read_text(encoding="utf-8")) for p in jobs.glob("*.json")]
    run = next(j for j in found if j["name"].startswith("pytest"))
    part = next(j for j in found if j["name"] == "a slow part")
    assert (run["done"], run["total"], run["state"]) == (3, 3, "failed")
    assert run["detail"] == "1 passed, 1 failed, 1 skipped"
    assert (part["parent"], part["done"], part["total"], part["state"]) == (run["id"], 2, 2, "done")


def test_it_can_be_turned_off(tmp_path):
    (tmp_path / "test_three.py").write_text(TESTS, encoding="utf-8")
    (tmp_path / "conftest.py").write_text(CONFTEST, encoding="utf-8")
    jobs = tmp_path / "progress"
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src"), "DNFW_PROGRESS_DIR": str(jobs),
           "DNFW_PYTEST_PROGRESS": "0"}
    subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", str(tmp_path / "test_three.py") + "::test_skips"],
                   capture_output=True, text=True, cwd=tmp_path, env=env)
    assert not [p for p in jobs.glob("*.json") if json.loads(p.read_text(encoding="utf-8"))["name"].startswith("pytest")]


def test_a_worktree_writes_to_the_main_checkout_s_folder():
    """The pane reads the main checkout's out/progress. A worktree's .git is a file, and its
    jobs went to the worktree's own out/progress until 2026-10-24, where the pane never saw them."""
    from dnfw import progress
    main = progress._main_checkout(ROOT)
    assert (main / ".git").is_dir()
    if (ROOT / ".git").is_file():                      # this run is in a worktree
        assert main != ROOT

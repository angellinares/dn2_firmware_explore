"""Where the emulator harnesses look for digikit and the untracked resources
(`scripts/emulib/paths.py`), from the main checkout and from a git worktree.

The harnesses run from worktrees under `.claude/worktrees/<name>/`. There the
checkout is the worktree, but digikit sits next to the main checkout, and
`00_Resources` (gitignored) is only in the main checkout unless linked in. The
order pinned here: the variable, this checkout, the main checkout, the first
default.
"""

import importlib.util
import os
import pathlib
import shutil
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
PATHS_PY = ROOT / "scripts" / "emulib" / "paths.py"
SYX_REL = "00_Resources/00_Firmware/Digitone_II_OS1.11_dist/Digitone_II_OS1.11.syx"

needs_git = pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")


def _load():
    spec = importlib.util.spec_from_file_location("emulib_paths_under_test", PATHS_PY)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


paths = _load()


def _git(*args, cwd):
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
                   cwd=cwd, check=True, capture_output=True)


def _checkout_with_worktree(tmp_path):
    """-> (main, worktree): a main checkout holding paths.py, and a worktree
    of it where this project makes them."""
    main = tmp_path / "dn2_firmware"
    (main / "scripts" / "emulib").mkdir(parents=True)
    shutil.copy(PATHS_PY, main / "scripts" / "emulib" / "paths.py")
    _git("init", "-q", cwd=main)
    _git("add", ".", cwd=main)
    _git("commit", "-q", "-m", "init", cwd=main)
    worktree = main / ".claude" / "worktrees" / "feature"
    _git("worktree", "add", "-q", "-b", "feature", str(worktree), cwd=main)
    return main.resolve(), worktree.resolve()


def _resolved_from(checkout):
    """-> paths.ROOT, MAIN, DIGIKIT and SYX as a harness run from CHECKOUT sees them."""
    env = {k: v for k, v in os.environ.items() if k not in ("DIGIKIT", "DT2_SYX")}
    code = ("import sys; sys.path.insert(0, 'scripts'); from emulib import paths; "
            "print(paths.ROOT, paths.MAIN, paths.DIGIKIT, paths.SYX, sep='\\n')")
    out = subprocess.run([sys.executable, "-c", code], cwd=checkout, env=env,
                         check=True, capture_output=True, text=True).stdout
    return [pathlib.Path(line) for line in out.splitlines()]


@needs_git
def test_the_main_checkout_is_itself(tmp_path):
    main, _ = _checkout_with_worktree(tmp_path)
    assert paths.main_checkout(main) == main


@needs_git
def test_a_worktree_finds_its_main_checkout(tmp_path):
    main, worktree = _checkout_with_worktree(tmp_path)
    assert paths.main_checkout(worktree) == main


def test_not_a_checkout_falls_back_to_root(tmp_path):
    assert paths.main_checkout(tmp_path) == tmp_path


def test_no_git_falls_back_to_root_quietly(tmp_path, monkeypatch):
    def missing(*args, **kwargs):
        raise FileNotFoundError("git")

    monkeypatch.setattr(paths.subprocess, "run", missing)
    assert paths.main_checkout(tmp_path) == tmp_path


def test_order_variable_then_root_then_main_then_first_default(tmp_path, monkeypatch):
    root, main = tmp_path / "worktree", tmp_path / "main"
    candidates = paths.local(SYX_REL, root, main)
    assert candidates == [root / SYX_REL, main / SYX_REL]

    monkeypatch.delenv("DT2_SYX", raising=False)
    assert paths.resolve("DT2_SYX", *candidates) == root / SYX_REL      # nothing exists

    (main / SYX_REL).parent.mkdir(parents=True)
    (main / SYX_REL).touch()
    assert paths.resolve("DT2_SYX", *candidates) == main / SYX_REL

    (root / SYX_REL).parent.mkdir(parents=True)
    (root / SYX_REL).touch()
    assert paths.resolve("DT2_SYX", *candidates) == root / SYX_REL

    monkeypatch.setenv("DT2_SYX", str(tmp_path / "elsewhere.syx"))
    assert paths.resolve("DT2_SYX", *candidates) == tmp_path / "elsewhere.syx"


def test_outside_a_worktree_root_is_looked_in_once(tmp_path):
    assert paths.local(SYX_REL, tmp_path, tmp_path) == [tmp_path / SYX_REL]


@needs_git
def test_a_harness_in_a_worktree_finds_digikit_and_the_firmware(tmp_path):
    """The case that broke: digikit beside the main checkout, `00_Resources`
    only in the main checkout, the harness run from a worktree."""
    main, worktree = _checkout_with_worktree(tmp_path)
    (main.parent / "digikit-up").mkdir()
    (main / SYX_REL).parent.mkdir(parents=True)
    (main / SYX_REL).touch()

    root, found_main, digikit, syx = _resolved_from(worktree)
    assert (root, found_main) == (worktree, main)
    assert digikit == main.parent / "digikit-up"
    assert syx == main / SYX_REL

    assert _resolved_from(main) == [main, main, main.parent / "digikit-up", main / SYX_REL]

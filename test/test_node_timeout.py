"""conftest gives a node child with no timeout of its own a limit, so a hung node fails the test."""

import shutil
import subprocess

import pytest


def test_a_hung_node_child_is_killed(monkeypatch):
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    monkeypatch.setitem(subprocess.run.__globals__, "NODE_TIMEOUT", 2)   # the wrapper conftest installs
    with pytest.raises(subprocess.TimeoutExpired):
        subprocess.run([node, "-e", "setTimeout(() => {}, 60000)"], capture_output=True)


def test_an_explicit_timeout_wins_and_other_programs_are_untouched():
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    assert subprocess.run([node, "-e", "1"], capture_output=True, timeout=60).returncode == 0
    assert subprocess.run(["git", "--version"], capture_output=True).returncode == 0

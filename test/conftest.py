"""Fixtures over the firmware corpus.

The corpus is not in this repository and never will be, so every test that
needs a real image skips cleanly when it is absent. A skipped corpus test says
so; it does not quietly pass. Outside CI the files are on this computer, so a
skip for a missing file is a failure there (MISSING).
"""

import os
import pathlib
import re
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

# Child processes (`python -c "... dnfw.cli.main ..."`) import this checkout's dnfw, not the one
# PYTHONPATH named before; the run refuses when they do not (dnfw.checkout)
from dnfw import checkout  # noqa: E402

os.environ.update(checkout.with_src_first(dict(os.environ), ROOT))
_CHECKOUT = None

# A node child with no timeout of its own gets NODE_TIMEOUT seconds. On 2026-11-04 two runs of
# js_codec_check.mjs wrote their output and never exited, and the suite waited 3.5 hours. With
# the limit, subprocess.run kills the child and the test fails with TimeoutExpired.
NODE_TIMEOUT = 900
_run = subprocess.run


def _run_with_node_timeout(args, *rest, **kwargs):
    first = args[0] if isinstance(args, (list, tuple)) and args else args
    if "timeout" not in kwargs and pathlib.Path(str(first)).stem.lower() == "node":
        kwargs["timeout"] = NODE_TIMEOUT
    return _run(args, *rest, **kwargs)


subprocess.run = _run_with_node_timeout


def _checkout():
    global _CHECKOUT
    if _CHECKOUT is None:
        _CHECKOUT = checkout.report(ROOT)
    return _CHECKOUT


def pytest_sessionstart(session):
    bad = checkout.problems(_checkout())
    if bad:
        pytest.exit("the checkout under test: " + "; ".join(bad), returncode=4)


def pytest_report_header(config):
    return checkout.lines(_checkout())


# A skip reason that names a missing file (the main334 rebuild: a worktree without its builds skipped).
# shortcut: matches the reason text; a new skip for a missing file must use one of these words
MISSING = re.compile(r"00_Resources|not present|no stock 1\.11")


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    report = (yield).get_result()
    if (report.skipped and not os.environ.get("CI") and isinstance(report.longrepr, tuple)
            and MISSING.search(report.longrepr[2])):
        report.outcome = "failed"
        report.longrepr = f"a file this test needs is missing: {report.longrepr[2]} (CI only skips this)"

# Every run shows in the progress pane: tests done, the one running, the tally (dnfw.pytest_progress).
from dnfw.pytest_progress import (  # noqa: E402,F401
    pytest_collection_finish, pytest_runtest_logfinish, pytest_runtest_logreport, pytest_runtest_logstart,
    pytest_sessionfinish)

FIRMWARE = checkout.resources_dir(ROOT) / "00_Firmware"

# Filename, and the facts each image should report. Written down rather than
# derived so a change in the tooling that silently alters them fails a test.
IMAGES = {
    "dn1": ("Digitone_and_Digitone_Keys_OS1.42A_dist.zip", 0x0D, "0097", "1.42A", False),
    "dn2": ("Digitone_II_OS1.10E_dist.zip", 0x15, "0050", "1.10E", True),
}


def _raw(key: str) -> bytes:
    from dnfw.cli.files import read_image

    name = IMAGES[key][0]
    path = FIRMWARE / name
    if not path.exists():
        pytest.skip(f"corpus image {name} not present under {FIRMWARE}")
    return read_image(path)


@pytest.fixture(scope="session")
def dn1_raw() -> bytes:
    return _raw("dn1")


@pytest.fixture(scope="session")
def dn2_raw() -> bytes:
    return _raw("dn2")


@pytest.fixture(scope="session")
def dn2(dn2_raw):
    from dnfw.firmware.load import load

    return load(dn2_raw)


@pytest.fixture(scope="session")
def dn1(dn1_raw):
    from dnfw.firmware.load import load

    return load(dn1_raw)

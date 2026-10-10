"""The download notice (`site/js/app/notice.js`): a click on a download link shows it,
and the file is saved only after the reader confirms. `scripts/js_notice_check.mjs`
runs it under node."""

import pathlib
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
HARNESS = ROOT / "scripts" / "js_notice_check.mjs"


def test_the_notice_guards_the_download():
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not on PATH; the notice cannot be checked")
    done = subprocess.run([node, str(HARNESS)], capture_output=True, text=True, cwd=ROOT)
    assert done.returncode == 0, done.stdout + done.stderr
    assert done.stdout.count("OK  ") == 5


def test_every_download_goes_through_the_notice():
    shell = (ROOT / "site/js/app/shell.js").read_text(encoding="utf-8")
    assert "guardDownload(link)" in shell
    for page in (ROOT / "site/js/app").glob("*-page.js"):
        if page.name == "bench-page.js":            # its download is a wavetable, not firmware
            continue
        assert "createObjectURL" not in page.read_text(encoding="utf-8"), page.name

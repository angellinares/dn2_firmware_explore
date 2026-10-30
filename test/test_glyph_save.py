"""The glyph editor's and animator's files out (`site/js/glyph-tools/glyph_tools.js`): the
date and time in download names and the option to turn it off, the download link, and a save
through a file handle that fails. `scripts/js_glyph_save_check.mjs` runs them under node."""

import pathlib
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
HARNESS = ROOT / "scripts" / "js_glyph_save_check.mjs"


def test_files_out_under_node():
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not on PATH; the files-out check cannot run")
    done = subprocess.run([node, str(HARNESS)], capture_output=True, text=True, cwd=ROOT)
    assert done.returncode == 0, done.stdout + done.stderr
    assert done.stdout.count("OK  ") == 12

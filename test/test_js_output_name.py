"""The file a mod page offers is named with the mod's version (`site/js/app/shell.js`), and
`site/js/mods/versions.js` is what `dnfw.mods.history` says. `scripts/js_output_name_check.mjs`
runs the naming under node."""

import pathlib
import shutil
import subprocess

import pytest

from dnfw.mods import history

ROOT = pathlib.Path(__file__).resolve().parent.parent


def test_the_download_is_named_with_the_version():
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not on PATH; the naming check cannot run")
    done = subprocess.run([node, str(ROOT / "scripts/js_output_name_check.mjs")], capture_output=True, text=True, cwd=ROOT)
    assert done.returncode == 0, done.stdout + done.stderr
    assert done.stdout.count("OK  ") >= 5 + 10


def test_the_sites_versions_are_the_record():
    path = ROOT / "site/js/mods/versions.js"
    assert path.read_text(encoding="utf-8") == history.versions_js(), \
        "run `dnfw mods changelog --js site/js/mods/versions.js`"

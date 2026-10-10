"""A mod withdrawn from the site (`site/js/mods/availability.js`): its page shows the
notice and builds nothing, the mod list marks it, other mods are untouched, and
removing the entry puts it back. `scripts/js_unavailable_check.mjs` runs it under node."""

import pathlib
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
HARNESS = ROOT / "scripts" / "js_unavailable_check.mjs"


def test_a_withdrawn_mod_is_not_offered():
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not on PATH; the withdrawn-mod check cannot run")
    done = subprocess.run([node, str(HARNESS)], capture_output=True, text=True, cwd=ROOT)
    assert done.returncode == 0, done.stdout + done.stderr
    assert done.stdout.count("OK  ") == 15


def test_the_pages_read_the_one_table():
    index = (ROOT / "site/index.html").read_text(encoding="utf-8")
    assert "js/app/index-page.js" in index
    for mod, page in (("lfo4", "lfo4-page.js"), ("fxmod", "fx-page.js")):
        assert f'flagFor("{mod}")' in (ROOT / "site/js/app" / page).read_text(encoding="utf-8")
        assert f'data-mod="{mod}"' in index

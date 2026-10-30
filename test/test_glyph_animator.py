"""The glyph animator (`site/glyph-animator.html`, model in `site/js/glyph-tools/glyph_anim_core.js`): the knob
picks the stock frame, the firmware format encodes and decodes, and the animation file
(`site/js/mods/glyph-anims.js`) round-trips. `scripts/js_glyph_anim_check.mjs` runs it under node."""

import pathlib
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
HARNESS = ROOT / "scripts" / "js_glyph_anim_check.mjs"


def test_the_animator_model_under_node():
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not on PATH; the animator check cannot run")
    done = subprocess.run([node, str(HARNESS)], capture_output=True, text=True, cwd=ROOT)
    assert done.returncode == 0, done.stdout + done.stderr
    assert done.stdout.count("OK  ") == 21


def test_the_two_editors_link_to_each_other():
    still = (ROOT / "site/glyph-editor.html").read_text(encoding="utf-8")
    anim = (ROOT / "site/glyph-animator.html").read_text(encoding="utf-8")
    assert 'href="glyph-animator.html"' in still and 'href="glyph-editor.html"' in anim
    for page in (still, anim):
        for src in ("glyph_anim_core.js", "glyph_icons.js", "glyph_font3x5.js", "glyph_text.js", "glyph_controls.js",
                    "glyph_tools.js", "glyph_fills_panel.js"):
            assert f'<script src="js/glyph-tools/{src}"></script>' in page
            assert (ROOT / "site/js/glyph-tools" / src).is_file()
        assert 'href="css/glyph-tools.css"' in page


def test_the_old_tools_paths_forward_to_the_site():
    # Desktop shortcuts and old links open tools/glyph_*.html: each forwards to its site page.
    for old, new in (("glyph_editor", "glyph-editor"), ("glyph_animator", "glyph-animator")):
        stub = (ROOT / f"tools/{old}.html").read_text(encoding="utf-8")
        assert f'url=../site/{new}.html' in stub and f'location.replace("../site/{new}.html"' in stub
        assert (ROOT / f"site/{new}.html").is_file()

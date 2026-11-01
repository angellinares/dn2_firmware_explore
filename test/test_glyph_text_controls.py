"""The glyph tools' Text and Controls tools (`site/js/glyph-tools/glyph_text.js`,
`glyph_controls.js`, the paste in `glyph_anim_core.js`): text layout, font files and the
control generators. `scripts/js_glyph_text_controls_check.mjs` runs them under node. The 3 x 5
font's classic script must match `src/dnfw/font3x5.json`, as `scripts/gen_font3x5.py` writes it."""

import importlib.util
import json
import pathlib
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
HARNESS = ROOT / "scripts" / "js_glyph_text_controls_check.mjs"


def test_text_and_controls_under_node():
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not on PATH; the text and controls check cannot run")
    done = subprocess.run([node, str(HARNESS)], capture_output=True, text=True, cwd=ROOT)
    assert done.returncode == 0, done.stdout + done.stderr
    assert done.stdout.count("OK  ") == 27


def test_the_font_scripts_are_generated_from_the_json():
    spec = importlib.util.spec_from_file_location("gen_font3x5", ROOT / "scripts/gen_font3x5.py")
    gen = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gen)
    font = json.loads((ROOT / "src/dnfw/font3x5.json").read_text())
    assert (ROOT / "site/js/glyph-tools/glyph_font3x5.js").read_bytes() == gen.classic_text(font).encode("utf-8")
    assert (ROOT / "site/js/font3x5.js").read_bytes() == gen.module_text(font).encode("utf-8")

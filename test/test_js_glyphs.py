"""The mod glyphs (`site/js/mods/glyphs.js`): one 16x16 1-bit glyph per offered mod, and every
page that shows one names a glyph that exists and loads the module that draws it.
`scripts/js_glyphs_check.mjs` checks the SVG they become under node."""

import pathlib
import re
import shutil
import subprocess

import pytest

from dnfw.cli.mods import REGISTRY

ROOT = pathlib.Path(__file__).resolve().parent.parent
SITE = ROOT / "site"
HARNESS = ROOT / "scripts" / "js_glyphs_check.mjs"
UNSHOWN = {"songguard", "usbprobe"}       # no card and no page of their own yet


def glyphs():
    src = (SITE / "js/mods/glyphs.js").read_text(encoding="utf-8")
    body = src.split("export const GLYPHS = {", 1)[1].split("\n};", 1)[0]
    return {m[0]: re.findall(r'"([^"]*)"', m[1]) for m in re.findall(r"(\w+): \[(.*?)\]", body, re.S)}


def test_every_offered_mod_has_a_16x16_glyph():
    found = glyphs()
    assert set(found) == set(REGISTRY) - UNSHOWN
    for mid, rows in found.items():
        assert len(rows) == 16 and all(re.fullmatch(r"[.#]{16}", r) for r in rows), mid
        assert sum(r.count("#") for r in rows) > 0, mid


def test_the_bug_fixes_and_only_they_carry_the_bug():
    src = (SITE / "js/mods/glyphs.js").read_text(encoding="utf-8")
    badge = re.findall(r'"([.#]{5})"', src.split("export const BUG_BADGE = [", 1)[1].split("]", 1)[0])
    assert len(badge) == 6
    index = (SITE / "index.html").read_text(encoding="utf-8")
    fixes = set(re.findall(r'<span class="mod-id">([a-z0-9]+)</span>',
                           index.split('id="bug-fixes"', 1)[1].split("<h2", 1)[0]))
    assert fixes, "the index lists no bug fixes"
    for mid, rows in glyphs().items():
        has = [r[11:] for r in rows[10:]] == badge
        assert has == (mid in fixes), mid
        if has:      # a dark row and column keep the bug apart from the rest of the glyph
            assert rows[9][10:] == "......" and all(r[10] == "." for r in rows[9:]), mid


def test_the_pages_name_known_glyphs_and_load_the_module():
    found = glyphs()
    shown = set()
    for page in SITE.glob("*.html"):
        text = page.read_text(encoding="utf-8")
        ids = re.findall(r'data-glyph="([a-z0-9]+)"', text)
        if not ids:
            continue
        shown |= set(ids)
        assert set(ids) <= set(found), page.name
        assert '<script type="module" src="js/app/glyphs-page.js"></script>' in text, page.name
        assert all('aria-hidden="true"' in tag for tag in re.findall(r"<span [^>]*data-glyph[^>]*>", text)), page.name
    assert shown == set(found)


def test_the_glyphs_draw_under_node():
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not on PATH; the glyph check cannot run")
    done = subprocess.run([node, str(HARNESS)], capture_output=True, text=True, cwd=ROOT)
    assert done.returncode == 0, done.stdout + done.stderr
    assert done.stdout.count("OK  ") == 46

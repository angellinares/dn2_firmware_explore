"""Every mod has a version and a changelog, and the site's pages show them (`dnfw.mods.history`)."""

import pathlib
import re

from dnfw.cli.mods import REGISTRY
from dnfw.mods import history

SITE = pathlib.Path(__file__).resolve().parent.parent / "site"
PAGES = sorted(SITE.glob("*.html"))


def test_every_mod_has_a_history_in_order():
    assert history.problems(REGISTRY) == []


def test_the_checks_see_a_bad_record(monkeypatch):
    r = history.Release
    monkeypatch.setitem(history.HISTORY, "fxmod", (r("1.0.0", "2026-10-11", ("a",)), r("1.1", "2026-10-12", ()),
                                                   r("1.0.1", "2026-10-10", ("b",))))
    monkeypatch.delitem(history.HISTORY, "lfo4")
    found = "\n".join(history.problems(REGISTRY))
    for expected in ("lfo4: no history", "'1.1' is not MAJOR.MINOR.PATCH", "says nothing changed",
                     "1.0.0 (2026-10-11) is listed above 1.0.1 (2026-10-10) and is not newer"):
        assert expected in found, found


def test_the_pages_show_the_current_record():
    for page in PAGES:
        text = page.read_text(encoding="utf-8")
        assert history.rewrite(text) == text, f"{page.name}: run `dnfw mods changelog --write site/*.html`"


def test_every_mod_page_and_card_has_its_regions():
    index = (SITE / "index.html").read_text(encoding="utf-8")
    cards = set(re.findall(r'<span class="mod-id">(\w+)</span>', index)) & set(REGISTRY)
    assert history.regions(index)[0] == cards and cards
    for page in PAGES:
        text = page.read_text(encoding="utf-8")
        mods = set(re.findall(r"<!-- dnfw:matrix-row (\w+) -->", text))
        if page.name != "index.html" and mods:
            assert history.regions(text) == (mods, mods), page.name


def test_a_new_release_reaches_the_page(monkeypatch):
    newer = history.Release("1.0.1", "2026-10-12", ("A fix <for> something.",))
    monkeypatch.setitem(history.HISTORY, "fxmod", (newer,) + history.HISTORY["fxmod"])
    text = history.rewrite((SITE / "fx.html").read_text(encoding="utf-8"))
    assert "<!-- dnfw:version fxmod -->v1.0.1<!-- /dnfw:version -->" in text
    assert "<li>A fix &lt;for&gt; something.</li>" in text
    assert text.index("v1.0.1</span>") < text.index("v1.0.0</span>")

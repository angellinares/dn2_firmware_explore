"""Every mod has a version and a changelog, and the site's pages show them (`dnfw.mods.history`)."""

import json
import pathlib
import re

import pytest

from dnfw.cli.mods import REGISTRY
from dnfw.mods import fingerprint, history
from dnfw.checkout import resources_dir  # noqa: E402

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


def test_a_link_in_a_change_is_a_link_on_the_page_and_words_in_the_terminal(monkeypatch):
    newer = history.Release("9.0.0", "2099-01-01", ("Fixed <a> step in [the DEST list](#dest-list).",))
    monkeypatch.setitem(history.HISTORY, "fxmod", (newer,) + history.HISTORY["fxmod"])
    assert '<li>Fixed &lt;a&gt; step in <a href="#dest-list">the DEST list</a>.</li>' in history.changes_html("fxmod")
    assert "    - Fixed <a> step in the DEST list." in history.changes_text("fxmod")
    assert history.links("fxmod") == {"dest-list"}
    assert history.problems(REGISTRY) == []


def test_a_link_that_is_not_words_and_an_id_is_a_problem(monkeypatch):
    for bad in ("See [the manual](https://example.com).", "See [the manual].", "See [](#x)."):
        newer = history.Release("9.0.0", "2099-01-01", (bad,))
        monkeypatch.setitem(history.HISTORY, "fxmod", (newer,) + history.HISTORY["fxmod"])
        assert any("a link is not [words](#id)" in p for p in history.problems(REGISTRY)), bad


def test_every_link_in_a_changes_list_has_its_target_on_that_page():
    linked = 0
    for page in PAGES:
        text = page.read_text(encoding="utf-8")
        ids = set(re.findall(r'\sid="([^"]+)"', text))
        for mod_id in history.regions(text)[1]:
            missing = history.links(mod_id) - ids
            assert not missing, f"{page.name}: {mod_id}'s changes link to {sorted(missing)}, not on the page"
            linked += len(history.links(mod_id))
    assert linked, "no change links to its page: the check checked nothing"


def test_a_page_with_several_version_regions_gets_all(monkeypatch):
    # Try it, What changes, and the documentation line of the manual and of the Technical tab
    text = (SITE / "waverider.html").read_text(encoding="utf-8")
    assert text.count("<!-- dnfw:version waverider -->") == 4
    newer = history.Release("9.0.0", "2099-01-01", ("A later version.",))
    monkeypatch.setitem(history.HISTORY, "waverider", (newer,) + history.HISTORY["waverider"])
    assert history.rewrite(text).count("<!-- dnfw:version waverider -->v9.0.0<!-- /dnfw:version -->") == 4


STOCK_111 = resources_dir(SITE.parent) / "00_Firmware/Digitone_II_OS1.11_dist.zip"


@pytest.fixture(scope="module")
def stock_111():
    from dnfw.cli.files import read_image
    from dnfw.firmware.load import load
    if not STOCK_111.exists():
        pytest.skip("Digitone II 1.11 is not in 00_Resources")
    return load(read_image(STOCK_111))


def test_a_mod_that_writes_other_bytes_has_a_new_version(stock_111):
    """arpscale, degreetranspose, fxmod and Waverider each shipped changed bytes under an old
    version before this check (found 2026-11-03)."""
    assert fingerprint.problems(stock_111, REGISTRY) == []


def test_the_fingerprint_check_sees_a_change(stock_111, monkeypatch, tmp_path):
    record = {m: dict(e) for m, e in fingerprint.recorded().items()}
    record["lfolength"]["sha256"] = "0" * 64
    monkeypatch.setattr(fingerprint, "RECORD", tmp_path / "fingerprints.json")
    fingerprint.RECORD.write_text(json.dumps(record))
    some = {m: REGISTRY[m] for m in ("lfolength", "reloadconfirm")}
    assert fingerprint.problems(stock_111, some) == [
        f"lfolength: writes other bytes than {history.version('lfolength')} did. Add a Release to "
        "src/dnfw/mods/history.py, then run `dnfw mods changelog --fingerprint STOCK_1.11`"]
    assert fingerprint.record(stock_111, some)[0].startswith("lfolength: writes other bytes")
    assert json.loads(fingerprint.RECORD.read_text())["lfolength"]["sha256"] == "0" * 64

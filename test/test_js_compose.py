"""The Mod Composer's rules (site/js/mods/compose.js), under node: what it offers, the order it
applies, what a choice blocks, and the command it shows. test_js_build_matches_cli.py checks that the
command builds the same bytes as the page."""

import json
import pathlib
import re
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
COMPOSE = (ROOT / "site/js/mods/compose.js").as_uri()
REGISTRY = (ROOT / "site/js/mods/registry.js").as_uri()


def _run(body: str):
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not on PATH; the composer's rules cannot be checked")
    script = (f'import * as c from "{COMPOSE}";\nimport {{ RUN }} from "{REGISTRY}";\n'
              f"const out = (() => {{ {body} }})();\nconsole.log(JSON.stringify(out));")
    done = subprocess.run([node, "--input-type=module", "-e", script], capture_output=True, text=True, cwd=ROOT)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def test_it_offers_every_mod_the_site_builds():
    got = _run("return { listed: c.GROUPS.flatMap((g) => g.mods), run: Object.keys(RUN) };")
    assert sorted(got["listed"]) == sorted(set(got["run"]) | {"transients", "bootscreen"})
    assert len(got["listed"]) == len(set(got["listed"]))


def test_lfo4_goes_last_as_on_the_cli():
    assert _run('return c.order(["lfo4", "fxmod", "waverider", "lfowaves"]);') == ["waverider", "fxmod", "lfowaves", "lfo4"]


def test_a_refused_pair_blocks_the_other_mod():
    got = _run('return [...c.blocked(["midiarp"], [["midiarp", "layermidi"], ["layermidi", "midiarp"]])];')
    assert got == [["layermidi", {"with": ["midiarp"], "full": False}]]


def test_a_build_with_waverider_holds_eleven_mods():
    got = _run('const ids = c.GROUPS.flatMap((g) => g.mods).slice(0, 11);'
               "return { ids, blocked: [...c.blocked(ids, [])] };")
    assert "waverider" in got["ids"]
    assert got["blocked"] == [["reloadconfirm", {"with": [], "full": True}], ["bootscreen", {"with": [], "full": True}]]
    without = _run('const ids = c.GROUPS.flatMap((g) => g.mods).filter((m) => m !== "waverider").slice(0, 11);'
                   "return [...c.blocked(ids, [])].map(([m]) => m);")
    assert without == ["waverider"]


def test_the_command_carries_each_file_option():
    lines = _run('return c.command(["bootscreen", "lfowaves", "transients"], {'
                 'transients: { equal: true, folder: "hits/" },'
                 'lfowaves: { files: [null, "t.json", null] },'
                 'bootscreen: { mode: "flash", image: "m.pgm" } }, { stock: "S.syx", out: "O.syx" });')
    assert lines == [["S.syx"], ["--mod", "transients", "--from", "hits/", "--equal-slots"],
                     ["--mod", "lfowaves", "--wavetable", "2=t.json"],
                     ["--mod", "bootscreen", "--boot-image", "m.pgm", "--boot-invert"], ["-o", "O.syx"]]


def test_the_page_has_a_panel_for_each_mod_that_takes_files():
    page = (ROOT / "site/compose.html").read_text(encoding="utf-8")
    for mod in _run("return c.TAKES_FILES;"):
        assert f'id="panel-{mod}"' in page
    script = (ROOT / "site/js/app/compose-page.js").read_text(encoding="utf-8")
    described = set(re.findall(r"^  (\w+): \[\"", script, re.M))
    assert described == set(_run("return c.GROUPS.flatMap((g) => g.mods);"))

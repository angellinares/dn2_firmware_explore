"""The licence check's fixed table, on small checkouts shaped like the real cases that went wrong."""

import json
import pathlib
import subprocess
import sys

import pytest

from dnfw import licencecheck as L

ROOT = pathlib.Path(__file__).resolve().parent.parent
NL = chr(10)
AGPL = f"   GNU AFFERO GENERAL PUBLIC LICENSE{NL}   Version 3, 19 November 2007{NL}"
GPL2 = f"   GNU GENERAL PUBLIC LICENSE{NL}   Version 2, June 1991{NL}"
GPL3 = f"   GNU GENERAL PUBLIC LICENSE{NL}   Version 3, 29 June 2007{NL}"
MIT = f"MIT License{NL}{NL}Permission is hereby granted, free of charge, to any person{NL}"


def project(tmp_path, files, name="p"):
    root = tmp_path / name
    root.mkdir()
    for path, text in files.items():
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    return root


def readme(text):
    return NL.join(["# Project", "", "Uses things.", "", "## Licence", "", text, "", "## Other", "", "More.", ""])


def verdict(tmp_path, files, name="p"):
    r = L.check(project(tmp_path, files, name))
    return r.licence, r.verdict


def test_agpl_or_later_is_ours(tmp_path):
    r = L.check(project(tmp_path, {"LICENSE": AGPL, "README.md": readme("AGPL-3.0-or-later. See [LICENSE](LICENSE).")}))
    assert (r.licence, r.verdict) == ("AGPL-3.0-or-later", L.COPY)
    assert "notices" in r.why


def test_agpl_with_no_or_later_goes_to_the_owner(tmp_path):
    files = {"LICENSE": AGPL, "README.md": readme("GNU Affero General Public License v3.0, see LICENSE.")}
    assert verdict(tmp_path, files) == ("AGPL-3.0-only", L.OWNER)


def test_gpl2_text_alone_is_only(tmp_path):
    assert verdict(tmp_path, {"LICENSE": GPL2}) == ("GPL-2.0-only", L.NO)


def test_gpl2_with_a_readme_statement_is_or_later(tmp_path):
    assert verdict(tmp_path, {"LICENSE": GPL2, "README.md": readme("GPL-2.0-or-later. See LICENSE.")}) == ("GPL-2.0-or-later", L.COPY)


def test_gpl2_with_a_notice_in_prose_is_or_later(tmp_path):
    notice = NL.join(["This program is free software, under the terms of the GNU General Public License as published by",
                      "the Free Software Foundation, either version 2 of the License, or (at your option)", "any later version.", ""])
    assert verdict(tmp_path, {"LICENSE": GPL2, "NOTICE": notice})[0] == "GPL-2.0-or-later"


def test_the_template_inside_the_licence_text_does_not_count(tmp_path):
    text = GPL2 + "How to Apply: either version 2 of the License, or (at your option) any later version." + NL
    assert verdict(tmp_path, {"LICENSE": text})[0] == "GPL-2.0-only"


def test_another_projects_licence_does_not_count(tmp_path):
    files = {"LICENSE": GPL2, "README.md": readme("GPL-2.0. It uses digikit (GPL-2.0-or-later).")}
    assert verdict(tmp_path, files)[0] == "GPL-2.0-only"


def test_a_notice_credit_lower_down_does_not_count(tmp_path):
    notice = NL * L.NOTICE_LINES + "From digikit, GPL-2.0-or-later." + NL
    assert verdict(tmp_path, {"LICENSE": GPL2, "NOTICE": notice})[0] == "GPL-2.0-only"


def test_a_mention_outside_the_licence_section_does_not_count(tmp_path):
    text = NL.join(["# Project", "", "Built with GPL-2.0-or-later tools.", "", "## Use", "", "Run it.", ""])
    assert verdict(tmp_path, {"LICENSE": GPL2, "README.md": text})[0] == "GPL-2.0-only"


def test_an_explicit_only_wins_over_a_later_mention(tmp_path):
    files = {"LICENSE": GPL2, "README.md": readme("GPL-2.0-only. An older release was GPL-2.0-or-later.")}
    assert verdict(tmp_path, files)[0] == "GPL-2.0-only"


def test_gpl3_or_later_and_only(tmp_path):
    assert verdict(tmp_path, {"LICENSE": GPL3, "README.md": readme("GPL-3.0-or-later.")}) == ("GPL-3.0-or-later", L.COPY)
    assert verdict(tmp_path, {"LICENSE": GPL3}, "q") == ("GPL-3.0-only", L.OWNER)


def test_mit(tmp_path):
    r = L.check(project(tmp_path, {"LICENSE": MIT}))
    assert (r.licence, r.verdict) == ("MIT", L.COPY)
    assert "THIRD-PARTY" in r.why


def test_no_licence_is_no(tmp_path):
    assert verdict(tmp_path, {"README.md": "# Project" + NL}) == ("none", L.NO)


def test_an_unknown_text_asks(tmp_path):
    assert verdict(tmp_path, {"LICENSE": "Software licence scope" + NL}) == ("unknown", L.ASK)


def test_several_licences_in_the_readme_ask(tmp_path):
    assert verdict(tmp_path, {"README.md": readme("Code (AVR): GPL3.0." + NL + "Code (STM32F): MIT license.")}) == ("mixed", L.ASK)


def test_only_prefixed_licence_files_ask(tmp_path):
    assert verdict(tmp_path, {"spleen-LICENSE": MIT, "font.bdf": "x"}) == ("mixed", L.ASK)


def test_other_licence_files_are_listed_and_scripts_are_not(tmp_path):
    r = L.check(project(tmp_path, {"LICENSE": MIT, "vendor/x/LICENSE": GPL2, "scripts/license.mjs": "code"}))
    assert r.other_licences == ["vendor/x/LICENSE: GPL-2.0"]


def test_a_standing_rule_outranks_a_copy(tmp_path):
    r = L.check(project(tmp_path, {"LICENSE": GPL2, "README.md": readme("GPL-2.0-or-later.")}, "dn2-cfw"))
    assert (r.licence, r.verdict) == ("GPL-2.0-or-later", L.OWNER)
    assert "method only" in r.why


def test_the_report_names_notice_ports_and_third_parties(tmp_path):
    files = {"LICENSE": MIT, "NOTICE": "Extra terms." + NL, "README.md": "# P" + NL + "A port of a commercial synth." + NL}
    out = L.render(L.check(project(tmp_path, files)))
    assert "read NOTICE" in out
    assert "port of a commercial synth" in out
    assert L.ELEKTRON in out


def test_every_licence_the_code_can_name_has_a_row():
    bases = ("AGPL-3.0", "GPL-3.0", "GPL-2.0")
    assert {f"{b}-{s}" for b in bases for s in ("only", "or-later")} <= set(L.TABLE)
    assert {"none", "mixed", "unknown", *L.PERMISSIVE} <= set(L.TABLE)


@pytest.mark.parametrize("prompt,fires", [
    ("is this AGPL-3.0 code ok to use?", True),
    ("check the licence of that repo", True),
    ("These guys built a thing: give it a look: https://github.com/someone/thing", True),
    ("set the input level to 0", False),
    ("how much DDR does a tape cost", False),
])
def test_the_routing_hook_sends_licence_prompts_to_the_tool(prompt, fires):
    done = subprocess.run([sys.executable, str(ROOT / ".claude/hooks/tool_routing.py")], input=json.dumps({"prompt": prompt}),
                          capture_output=True, text=True, check=True)
    assert ("tools/licence_check.py" in done.stdout) == fires


@pytest.mark.parametrize("files,status",[({"LICENSE": MIT}, 0), ({"LICENSE": GPL2}, 1), ({"LICENSE": AGPL}, 2)])
def test_the_cli_status(tmp_path, files, status):
    root = project(tmp_path, files)
    done = subprocess.run([sys.executable, str(ROOT / "tools/licence_check.py"), str(root)], capture_output=True, text=True, check=False)
    assert done.returncode == status
